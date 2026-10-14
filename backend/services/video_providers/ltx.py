from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from pydantic import BaseModel, ConfigDict, ValidationError

from runtime_config.ltx_capabilities import api_caps, pixels_for
from services.generation_interrupt import GenerationCancelledError
from services.http_client.http_client import HTTPClient, HttpTransportError
from services.video_providers.errors import ProviderError
from services.video_providers.models import (
    ProviderCapabilities,
    ProviderProfile,
    ProviderTextToVideoRequest,
)


class _SubmitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str


class _JobResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    video_url: str | None = None


class _JobError(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str | None = None
    message: str | None = None


class _JobStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    result: _JobResult | None = None
    error: _JobError | None = None


_IN_PROGRESS = frozenset({"pending", "processing"})
_MODEL_PIPELINES = {
    "ltx-2-3-fast": "fast",
    "ltx-2-3-pro": "pro",
    "ltx-2-5-fast": "fast-2.5",
    "ltx-2-5-pro": "pro-2.5",
}


class LTXTextToVideoProvider:
    """LTX V2 text-to-video adapter for the shared provider boundary."""

    provider_id = "ltx"
    capabilities = ProviderCapabilities(text_to_video=True)

    def __init__(
        self,
        http: HTTPClient,
        *,
        poll_interval_s: float = 5.0,
        async_max_wait_s: float = 1200.0,
    ) -> None:
        self._http = http
        self._poll_interval_s = poll_interval_s
        self._async_max_wait_s = async_max_wait_s

    def generate(
        self,
        request: ProviderTextToVideoRequest,
        profile: ProviderProfile,
        output_path: Path,
        *,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        base_url, api_key = self._configuration(profile)
        self._raise_if_cancelled(is_cancelled)
        try:
            submit = self._http.post(
                f"{base_url}/v2/text-to-video",
                headers=self._headers(api_key),
                json_payload={
                    "prompt": request.prompt,
                    "model": request.model_id,
                    "duration": request.duration,
                    "resolution": self._pixel_resolution(request),
                    "fps": request.fps,
                    "generate_audio": request.generate_audio,
                },
                timeout=120,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not reach the LTX API",
                retryable=True,
            ) from exc

        if submit.status_code != 202:
            raise self._http_error(submit.status_code, stage="submission")
        try:
            job_id = _SubmitResponse.model_validate(submit.json()).id
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._error(
                "PROVIDER_RESPONSE_INVALID", "LTX returned an invalid submission response"
            ) from exc

        video_url = self._poll(
            base_url=base_url,
            api_key=api_key,
            job_id=job_id,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        self._raise_if_cancelled(is_cancelled)
        try:
            download = self._http.get(video_url, headers=None, timeout=300)
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the LTX video",
                retryable=True,
            ) from exc
        if download.status_code != 200 or not download.content:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the LTX video",
                retryable=True,
            )

        self._raise_if_cancelled(is_cancelled)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(download.content)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not save the LTX video",
                retryable=True,
            ) from exc

    def _poll(
        self,
        *,
        base_url: str,
        api_key: str,
        job_id: str,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + self._async_max_wait_s
        progress_by_status = {"pending": 10, "processing": 70}
        while time.monotonic() < deadline:
            self._raise_if_cancelled(is_cancelled)
            try:
                response = self._http.get(
                    f"{base_url}/v2/text-to-video/{job_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_NETWORK_ERROR",
                    "Could not reach the LTX API",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise self._http_error(response.status_code, stage="status check")
            try:
                status = _JobStatus.model_validate(response.json())
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                raise self._error(
                    "PROVIDER_RESPONSE_INVALID",
                    "LTX returned an invalid job status",
                ) from exc

            if status.status in _IN_PROGRESS:
                on_progress(progress_by_status[status.status])
                self._raise_if_cancelled(is_cancelled)
                time.sleep(self._poll_interval_s)
                continue
            if status.status == "completed":
                video_url = status.result.video_url if status.result is not None else None
                if not video_url:
                    raise self._error(
                        "PROVIDER_RESPONSE_INVALID",
                        "LTX completed without a video URL",
                    )
                on_progress(100)
                return video_url
            raise self._error("PROVIDER_REJECTED", "LTX rejected the generation request")

        raise self._error(
            "PROVIDER_TIMEOUT", "LTX generation timed out", retryable=True
        )

    @staticmethod
    def _configuration(profile: ProviderProfile) -> tuple[str, str]:
        if not profile.base_url or not profile.api_key:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="ltx",
                message="LTX requires an API URL and credential",
            )
        return profile.base_url.rstrip("/"), profile.api_key

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_if_cancelled(is_cancelled: Callable[[], bool]) -> None:
        if is_cancelled():
            raise GenerationCancelledError()

    @staticmethod
    def _pixel_resolution(request: ProviderTextToVideoRequest) -> str:
        pipeline = _MODEL_PIPELINES.get(request.model_id)
        if pipeline is None:
            pipeline = "pro-2.5" if request.model_id.endswith("pro") else "fast-2.5"
        try:
            width, height = pixels_for(
                api_caps(pipeline),  # type: ignore[arg-type]
                request.resolution,  # type: ignore[arg-type]
                request.aspect_ratio,  # type: ignore[arg-type]
            )
        except (KeyError, ValueError) as exc:
            raise ProviderError(
                code="PROVIDER_CAPABILITY_UNSUPPORTED",
                provider="ltx",
                message="LTX does not support the selected resolution and aspect ratio",
            ) from exc
        return f"{width}x{height}"

    @staticmethod
    def _http_error(status_code: int, *, stage: str) -> ProviderError:
        if status_code == 401:
            return LTXTextToVideoProvider._error(
                "PROVIDER_AUTHENTICATION_FAILED", "LTX rejected the API credential"
            )
        retryable = status_code == 429 or status_code >= 500
        return LTXTextToVideoProvider._error(
            "PROVIDER_REJECTED",
            f"LTX rejected the generation {stage}",
            retryable=retryable,
        )

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> ProviderError:
        return ProviderError(
            code=code,
            provider="ltx",
            message=message,
            retryable=retryable,
        )
