from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from services.generation_interrupt import GenerationCancelledError
from services.http_client.http_client import HTTPClient, HttpResponseLike, HttpTransportError
from services.services_utils import JSONValue
from services.video_providers.errors import ProviderError
from services.video_providers.models import (
    ProviderCapabilities,
    ProviderProfile,
    ProviderTextToVideoRequest,
)


class _CreatedOperation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str


class _Video(BaseModel):
    model_config = ConfigDict(extra="ignore")
    uri: object


class _GeneratedSample(BaseModel):
    model_config = ConfigDict(extra="ignore")
    video: _Video


class _GenerateVideoResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    generatedSamples: list[_GeneratedSample]


class _OperationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    generateVideoResponse: _GenerateVideoResponse


class _OperationStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    done: StrictBool = False
    error: object | None = None
    response: _OperationResponse | None = None


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")
_ASPECT_RATIOS = {"16:9", "9:16"}
_DURATIONS = {4, 6, 8}
_RESOLUTIONS = {"720p", "1080p", "4k"}


class GoogleVeoTextToVideoProvider:
    """Gemini API adapter for Veo 3.1 long-running video operations."""

    provider_id = "google_veo"
    capabilities = ProviderCapabilities(text_to_video=True)

    def __init__(
        self,
        http: HTTPClient,
        *,
        poll_interval_s: float = 10.0,
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
        model_id = self._safe_token(request.model_id, field="model ID")
        parameters = self._parameters(request, model_id=model_id)
        self._raise_if_cancelled(is_cancelled)
        payload: dict[str, JSONValue] = {
            "instances": [{"prompt": request.prompt}],
            "parameters": parameters,
        }
        try:
            response = self._http.post(
                f"{base_url}/models/{model_id}:predictLongRunning",
                headers=self._headers(api_key, json_content=True),
                json_payload=payload,
                timeout=120,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not reach Google Veo",
                retryable=True,
            ) from exc
        if response.status_code not in (200, 201, 202):
            raise self._http_error(response.status_code, stage="submission")
        operation_name = self._operation_name(response, model_id=model_id)
        video_url = self._poll(
            base_url=base_url,
            operation_name=operation_name,
            api_key=api_key,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        self._raise_if_cancelled(is_cancelled)
        self._download(video_url, output_path, api_key=api_key)

    def _poll(
        self,
        *,
        base_url: str,
        operation_name: str,
        api_key: str,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + self._async_max_wait_s
        operation_url = f"{base_url}/{operation_name}"
        progress = 10
        while time.monotonic() < deadline:
            self._raise_if_cancelled(is_cancelled)
            try:
                response = self._http.get(
                    operation_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_NETWORK_ERROR",
                    "Could not reach the Google Veo operation",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise self._http_error(response.status_code, stage="status check")
            operation = self._operation_status(
                response,
                expected_name=operation_name,
            )
            video_url = self._handle_operation(operation, on_progress)
            if video_url is not None:
                return video_url
            progress = min(90, progress + 20)
            on_progress(progress)
            self._raise_if_cancelled(is_cancelled)
            time.sleep(self._poll_interval_s)
        raise self._error(
            "PROVIDER_TIMEOUT", "Google Veo generation timed out", retryable=True
        )

    def _handle_operation(
        self,
        operation: _OperationStatus,
        on_progress: Callable[[int], None],
    ) -> str | None:
        if not operation.done:
            return None
        if operation.error is not None:
            raise self._error(
                "PROVIDER_REJECTED", "Google Veo rejected the generation request"
            )
        if operation.response is None:
            raise self._invalid_response("Google Veo returned an empty operation result")
        samples = operation.response.generateVideoResponse.generatedSamples
        if not samples or not isinstance(samples[0].video.uri, str):
            raise self._invalid_response("Google Veo returned an invalid video result")
        video_url = samples[0].video.uri
        try:
            self._require_https_url(video_url)
        except ValueError as exc:
            raise self._invalid_response("Google Veo returned an invalid video result") from exc
        on_progress(100)
        return video_url

    @staticmethod
    def _raise_if_cancelled(is_cancelled: Callable[[], bool]) -> None:
        if is_cancelled():
            raise GenerationCancelledError()

    def _download(self, video_url: str, output_path: Path, *, api_key: str) -> None:
        try:
            response = self._http.get(
                video_url,
                headers=self._headers(api_key),
                timeout=300,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the Google Veo video",
                retryable=True,
            ) from exc
        if response.status_code != 200 or not response.content:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the Google Veo video",
                retryable=True,
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not save the Google Veo video",
                retryable=True,
            ) from exc

    def _operation_name(self, response: HttpResponseLike, *, model_id: str) -> str:
        try:
            name = _CreatedOperation.model_validate(response.json()).name
            self._validate_operation_name(name, model_id=model_id)
            return name
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response(
                "Google Veo returned an invalid operation response"
            ) from exc

    def _operation_status(
        self,
        response: HttpResponseLike,
        *,
        expected_name: str,
    ) -> _OperationStatus:
        try:
            operation = _OperationStatus.model_validate(response.json())
            if operation.name != expected_name:
                raise ValueError("operation name changed")
            return operation
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response(
                "Google Veo returned an invalid operation status"
            ) from exc

    @staticmethod
    def _configuration(profile: ProviderProfile) -> tuple[str, str]:
        if not profile.base_url or not profile.api_key:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="google_veo",
                message="Google Veo requires an API URL and credential",
            )
        parsed = urlparse(profile.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="google_veo",
                message="Google Veo requires an HTTPS API URL",
            )
        return profile.base_url.rstrip("/"), profile.api_key

    @staticmethod
    def _safe_token(value: str, *, field: str) -> str:
        if not _SAFE_TOKEN.fullmatch(value):
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="google_veo",
                message=f"Google Veo {field} is invalid",
            )
        return value

    @staticmethod
    def _validate_operation_name(value: str, *, model_id: str) -> None:
        match = re.fullmatch(
            r"models/([A-Za-z0-9._-]+)/operations/([A-Za-z0-9._-]+)",
            value,
        )
        if match is None or match.group(1) != model_id:
            raise ValueError("invalid operation name")

    @classmethod
    def _parameters(
        cls,
        request: ProviderTextToVideoRequest,
        *,
        model_id: str,
    ) -> dict[str, JSONValue]:
        if request.aspect_ratio not in _ASPECT_RATIOS:
            raise cls._unsupported("Google Veo supports 16:9 or 9:16 output")
        duration = cls._duration(request.duration)
        if request.resolution not in _RESOLUTIONS:
            raise cls._unsupported("Google Veo does not support the selected resolution")
        if request.resolution in {"1080p", "4k"} and duration != 8:
            raise cls._unsupported("Google Veo high-resolution output requires 8 seconds")
        if "-lite-" in model_id and request.resolution == "4k":
            raise cls._unsupported("Google Veo Lite does not support 4k output")
        if request.fps != 24:
            raise cls._unsupported("Google Veo output uses a fixed 24 FPS")
        if not request.generate_audio:
            raise cls._unsupported("Google Veo always generates audio")
        parameters: dict[str, JSONValue] = {
            "aspectRatio": request.aspect_ratio,
            "durationSeconds": str(duration),
            "resolution": request.resolution,
        }
        if request.seed is not None:
            parameters["seed"] = request.seed
        return parameters

    @staticmethod
    def _duration(value: int | float | None) -> int:
        if (
            value is None
            or isinstance(value, bool)
            or not float(value).is_integer()
            or int(value) not in _DURATIONS
        ):
            raise GoogleVeoTextToVideoProvider._unsupported(
                "Google Veo duration must be 4, 6, or 8 seconds"
            )
        return int(value)

    @staticmethod
    def _require_https_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("expected an absolute HTTPS URL")

    @staticmethod
    def _headers(api_key: str, *, json_content: bool = False) -> dict[str, str]:
        headers = {"x-goog-api-key": api_key}
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _http_error(status_code: int, *, stage: str) -> ProviderError:
        if status_code in (401, 403):
            return GoogleVeoTextToVideoProvider._error(
                "PROVIDER_AUTHENTICATION_FAILED",
                "Google Veo rejected the API credential",
            )
        return GoogleVeoTextToVideoProvider._error(
            "PROVIDER_REJECTED",
            f"Google Veo rejected the {stage}",
            retryable=status_code == 429 or status_code >= 500,
        )

    @staticmethod
    def _unsupported(message: str) -> ProviderError:
        return GoogleVeoTextToVideoProvider._error(
            "PROVIDER_CAPABILITY_UNSUPPORTED", message
        )

    @staticmethod
    def _invalid_response(message: str) -> ProviderError:
        return GoogleVeoTextToVideoProvider._error(
            "PROVIDER_RESPONSE_INVALID", message
        )

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> ProviderError:
        return ProviderError(
            code=code,
            provider="google_veo",
            message=message,
            retryable=retryable,
        )
