from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from services.generation_interrupt import GenerationCancelledError
from services.http_client.http_client import HTTPClient, HttpResponseLike, HttpTransportError
from services.video_providers.errors import ProviderError
from services.video_providers.models import (
    ProviderCapabilities,
    ProviderProfile,
    ProviderTextToVideoRequest,
)


class _SubmitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_id: str
    status_url: str
    response_url: str
    cancel_url: str


class _QueueStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    error: str | None = None
    error_type: str | None = None


class _VideoFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str


class _VideoResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    video: _VideoFile


_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9._~/-]+$")
_PROGRESS = {"IN_QUEUE": 10, "IN_PROGRESS": 70, "COMPLETED": 100}


class FalTextToVideoProvider:
    """fal queue adapter for text-to-video models with the common video schema."""

    provider_id = "fal"
    capabilities = ProviderCapabilities(text_to_video=True)

    def __init__(
        self,
        http: HTTPClient,
        *,
        poll_interval_s: float = 5.0,
        async_max_wait_s: float = 3600.0,
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
        model_id = self._model_id(request.model_id)
        self._raise_if_cancelled(is_cancelled)
        try:
            submit = self._http.post(
                f"{base_url}/{model_id}",
                headers=self._headers(api_key, json_content=True),
                json_payload={
                    "prompt": request.prompt,
                    "duration": self._duration(request.duration),
                    "aspect_ratio": request.aspect_ratio,
                    "generate_audio": request.generate_audio,
                    "negative_prompt": request.negative_prompt,
                },
                timeout=120,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not reach fal.ai",
                retryable=True,
            ) from exc
        if submit.status_code not in (200, 202):
            raise self._http_error(submit.status_code, stage="submission")
        envelope = self._submit_envelope(submit)

        result_url = self._poll(
            envelope=envelope,
            api_key=api_key,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        try:
            result_response = self._http.get(
                result_url,
                headers=self._headers(api_key),
                timeout=60,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not retrieve the fal.ai result",
                retryable=True,
            ) from exc
        if result_response.status_code != 200:
            raise self._http_error(result_response.status_code, stage="result retrieval")
        try:
            video_url = _VideoResult.model_validate(result_response.json()).video.url
            self._require_https_url(video_url)
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._error(
                "PROVIDER_RESPONSE_INVALID", "fal.ai returned an invalid video result"
            ) from exc

        self._raise_if_cancelled(is_cancelled, envelope=envelope, api_key=api_key)
        self._download(video_url, output_path)

    def _poll(
        self,
        *,
        envelope: _SubmitResponse,
        api_key: str,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + self._async_max_wait_s
        while time.monotonic() < deadline:
            self._raise_if_cancelled(
                is_cancelled, envelope=envelope, api_key=api_key
            )
            try:
                response = self._http.get(
                    envelope.status_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_NETWORK_ERROR",
                    "Could not reach the fal.ai queue",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise self._http_error(response.status_code, stage="status check")
            try:
                status = _QueueStatus.model_validate(response.json())
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                raise self._error(
                    "PROVIDER_RESPONSE_INVALID",
                    "fal.ai returned an invalid queue status",
                ) from exc
            if status.status not in _PROGRESS:
                raise self._error(
                    "PROVIDER_RESPONSE_INVALID",
                    "fal.ai returned an unknown queue status",
                )
            on_progress(_PROGRESS[status.status])
            self._raise_if_cancelled(
                is_cancelled, envelope=envelope, api_key=api_key
            )
            if status.status == "COMPLETED":
                if status.error is not None or status.error_type is not None:
                    raise self._error(
                        "PROVIDER_REJECTED", "fal.ai rejected the generation request"
                    )
                return envelope.response_url
            time.sleep(self._poll_interval_s)
        raise self._error(
            "PROVIDER_TIMEOUT", "fal.ai generation timed out", retryable=True
        )

    def _download(self, video_url: str, output_path: Path) -> None:
        try:
            response = self._http.get(video_url, headers=None, timeout=300)
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the fal.ai video",
                retryable=True,
            ) from exc
        if response.status_code != 200 or not response.content:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the fal.ai video",
                retryable=True,
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not save the fal.ai video",
                retryable=True,
            ) from exc

    def _submit_envelope(self, response: HttpResponseLike) -> _SubmitResponse:
        try:
            envelope = _SubmitResponse.model_validate(response.json())
            for url in (
                envelope.status_url,
                envelope.response_url,
                envelope.cancel_url,
            ):
                self._require_https_url(url)
            return envelope
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._error(
                "PROVIDER_RESPONSE_INVALID",
                "fal.ai returned an invalid queue submission response",
            ) from exc

    def _raise_if_cancelled(
        self,
        is_cancelled: Callable[[], bool],
        *,
        envelope: _SubmitResponse | None = None,
        api_key: str | None = None,
    ) -> None:
        if not is_cancelled():
            return
        if envelope is not None and api_key is not None:
            try:
                response = self._http.put(
                    envelope.cancel_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Could not cancel the fal.ai request",
                    retryable=True,
                ) from exc
            already_completed = False
            if response.status_code == 400:
                try:
                    raw_payload: object = response.json()
                    payload = (
                        cast(dict[str, object], raw_payload)
                        if isinstance(raw_payload, dict)
                        else {}
                    )
                    status_value = payload.get("status")
                    already_completed = (
                        isinstance(status_value, str)
                        and status_value == "ALREADY_COMPLETED"
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    already_completed = False
            if response.status_code != 202 and not already_completed:
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "fal.ai did not accept the cancellation request",
                    retryable=response.status_code >= 500,
                )
        raise GenerationCancelledError()

    @staticmethod
    def _configuration(profile: ProviderProfile) -> tuple[str, str]:
        if not profile.base_url or not profile.api_key:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="fal",
                message="fal.ai requires an API URL and credential",
            )
        parsed = urlparse(profile.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="fal",
                message="fal.ai requires an HTTPS API URL",
            )
        return profile.base_url.rstrip("/"), profile.api_key

    @staticmethod
    def _model_id(model_id: str) -> str:
        if (
            not _SAFE_MODEL_ID.fullmatch(model_id)
            or model_id.startswith("/")
            or any(part in ("", ".", "..") for part in model_id.split("/"))
        ):
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="fal",
                message="fal.ai model ID must be a relative model path",
            )
        return model_id

    @staticmethod
    def _duration(duration: int | float | None) -> str | None:
        if duration is None:
            return None
        return str(int(duration)) if float(duration).is_integer() else str(duration)

    @staticmethod
    def _require_https_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("expected an absolute HTTPS URL")

    @staticmethod
    def _headers(api_key: str, *, json_content: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Key {api_key}"}
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _http_error(status_code: int, *, stage: str) -> ProviderError:
        if status_code in (401, 403):
            return FalTextToVideoProvider._error(
                "PROVIDER_AUTHENTICATION_FAILED",
                "fal.ai rejected the API credential",
            )
        return FalTextToVideoProvider._error(
            "PROVIDER_REJECTED",
            f"fal.ai rejected the {stage}",
            retryable=status_code == 429 or status_code >= 500,
        )

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> ProviderError:
        return ProviderError(
            code=code,
            provider="fal",
            message=message,
            retryable=retryable,
        )
