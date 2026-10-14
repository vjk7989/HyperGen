from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from services.generation_interrupt import GenerationCancelledError
from services.http_client.http_client import HTTPClient, HttpResponseLike, HttpTransportError
from services.services_utils import JSONValue
from services.video_providers.errors import ProviderError
from services.video_providers.models import (
    ProviderCapabilities,
    ProviderProfile,
    ProviderTextToVideoRequest,
)


class _CreatedGeneration(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID


class _Assets(BaseModel):
    model_config = ConfigDict(extra="ignore")
    video: object | None = None


class _GenerationStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    state: str
    assets: _Assets | None = None


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")
_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"}
_RESOLUTIONS = {"540p", "720p", "1080p", "4k"}
_DURATIONS = {5, 9}


class LumaTextToVideoProvider:
    """Luma Dream Machine adapter for the Ray 2 video schema."""

    provider_id = "luma"
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
        model_id = self._safe_model_id(request.model_id)
        aspect_ratio = self._aspect_ratio(request.aspect_ratio)
        resolution = self._resolution(request.resolution)
        duration = self._duration(request.duration)
        self._raise_if_cancelled(is_cancelled)

        payload: dict[str, JSONValue] = {
            "prompt": request.prompt,
            "model": model_id,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration": duration,
        }
        try:
            response = self._http.post(
                f"{base_url}/generations/video",
                headers=self._headers(api_key, json_content=True),
                json_payload=payload,
                timeout=120,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not reach Luma",
                retryable=True,
            ) from exc
        if response.status_code not in (200, 201, 202):
            raise self._http_error(response.status_code, stage="submission")
        generation_id = self._created_generation_id(response)
        video_url = self._poll(
            base_url=base_url,
            generation_id=generation_id,
            api_key=api_key,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        self._raise_if_cancelled(
            is_cancelled,
            generation_url=f"{base_url}/generations/{generation_id}",
            api_key=api_key,
        )
        self._download(video_url, output_path)

    def _poll(
        self,
        *,
        base_url: str,
        generation_id: str,
        api_key: str,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + self._async_max_wait_s
        generation_url = f"{base_url}/generations/{generation_id}"
        while time.monotonic() < deadline:
            self._raise_if_cancelled(
                is_cancelled,
                generation_url=generation_url,
                api_key=api_key,
            )
            try:
                response = self._http.get(
                    generation_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_NETWORK_ERROR",
                    "Could not reach the Luma generation",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise self._http_error(response.status_code, stage="status check")
            status = self._generation_status(response)
            video_url = self._handle_status(status, on_progress)
            if video_url is not None:
                return video_url
            self._raise_if_cancelled(
                is_cancelled,
                generation_url=generation_url,
                api_key=api_key,
            )
            time.sleep(self._poll_interval_s)
        raise self._error(
            "PROVIDER_TIMEOUT", "Luma generation timed out", retryable=True
        )

    def _handle_status(
        self,
        generation: _GenerationStatus,
        on_progress: Callable[[int], None],
    ) -> str | None:
        if generation.state == "failed":
            raise self._error(
                "PROVIDER_REJECTED", "Luma rejected the generation request"
            )
        if generation.state == "queued":
            on_progress(10)
            return None
        if generation.state == "dreaming":
            on_progress(70)
            return None
        if generation.state != "completed":
            raise self._invalid_response("Luma returned an unknown generation state")
        if generation.assets is None or not isinstance(generation.assets.video, str):
            raise self._invalid_response("Luma returned an invalid generation asset")
        video_url = generation.assets.video
        try:
            self._require_https_url(video_url)
        except ValueError as exc:
            raise self._invalid_response("Luma returned an invalid generation asset") from exc
        on_progress(100)
        return video_url

    def _raise_if_cancelled(
        self,
        is_cancelled: Callable[[], bool],
        *,
        generation_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        if not is_cancelled():
            return
        if generation_url is not None and api_key is not None:
            try:
                response = self._http.delete(
                    generation_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Could not cancel the Luma generation",
                    retryable=True,
                ) from exc
            if response.status_code not in (200, 202, 204):
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Luma did not accept the cancellation request",
                    retryable=response.status_code == 429
                    or response.status_code >= 500,
                )
        raise GenerationCancelledError()

    def _download(self, video_url: str, output_path: Path) -> None:
        try:
            response = self._http.get(video_url, headers=None, timeout=300)
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the Luma video",
                retryable=True,
            ) from exc
        if response.status_code != 200 or not response.content:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the Luma video",
                retryable=True,
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not save the Luma video",
                retryable=True,
            ) from exc

    def _created_generation_id(self, response: HttpResponseLike) -> str:
        try:
            generation_id = _CreatedGeneration.model_validate(response.json()).id
            return str(generation_id)
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response(
                "Luma returned an invalid generation submission response"
            ) from exc

    def _generation_status(self, response: HttpResponseLike) -> _GenerationStatus:
        try:
            return _GenerationStatus.model_validate(response.json())
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response(
                "Luma returned an invalid generation response"
            ) from exc

    @staticmethod
    def _configuration(profile: ProviderProfile) -> tuple[str, str]:
        if not profile.base_url or not profile.api_key:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="luma",
                message="Luma requires an API URL and credential",
            )
        parsed = urlparse(profile.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="luma",
                message="Luma requires an HTTPS API URL",
            )
        return profile.base_url.rstrip("/"), profile.api_key

    @staticmethod
    def _safe_model_id(value: str) -> str:
        if not _SAFE_TOKEN.fullmatch(value):
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="luma",
                message="Luma model ID is invalid",
            )
        return value

    @staticmethod
    def _aspect_ratio(value: str) -> str:
        if value not in _ASPECT_RATIOS:
            raise ProviderError(
                code="PROVIDER_CAPABILITY_UNSUPPORTED",
                provider="luma",
                message="Luma does not support the selected aspect ratio",
            )
        return value

    @staticmethod
    def _resolution(value: str) -> str:
        if value not in _RESOLUTIONS:
            raise ProviderError(
                code="PROVIDER_CAPABILITY_UNSUPPORTED",
                provider="luma",
                message="Luma does not support the selected resolution",
            )
        return value

    @staticmethod
    def _duration(value: int | float | None) -> str:
        if (
            value is None
            or isinstance(value, bool)
            or not float(value).is_integer()
            or int(value) not in _DURATIONS
        ):
            raise ProviderError(
                code="PROVIDER_CAPABILITY_UNSUPPORTED",
                provider="luma",
                message="Luma Ray 2 duration must be 5 or 9 seconds",
            )
        return f"{int(value)}s"

    @staticmethod
    def _require_https_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("expected an absolute HTTPS URL")

    @staticmethod
    def _headers(api_key: str, *, json_content: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {api_key}"}
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _http_error(status_code: int, *, stage: str) -> ProviderError:
        if status_code in (401, 403):
            return LumaTextToVideoProvider._error(
                "PROVIDER_AUTHENTICATION_FAILED",
                "Luma rejected the API credential",
            )
        return LumaTextToVideoProvider._error(
            "PROVIDER_REJECTED",
            f"Luma rejected the {stage}",
            retryable=status_code == 429 or status_code >= 500,
        )

    @staticmethod
    def _invalid_response(message: str) -> ProviderError:
        return LumaTextToVideoProvider._error("PROVIDER_RESPONSE_INVALID", message)

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> ProviderError:
        return ProviderError(
            code=code,
            provider="luma",
            message=message,
            retryable=retryable,
        )
