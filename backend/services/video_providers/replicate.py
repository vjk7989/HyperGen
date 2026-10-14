from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

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


class _PredictionURLs(BaseModel):
    model_config = ConfigDict(extra="ignore")
    get: str
    cancel: str


class _Prediction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    status: str
    output: object | None = None
    error: str | None = None
    urls: _PredictionURLs


_MODEL_NAME = r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"
_VERSION = r"[A-Fa-f0-9]{64}"
_MODEL_ID = re.compile(rf"^(?:{_MODEL_NAME}(?::{_VERSION})?|{_VERSION})$")
_PROGRESS = {"starting": 10, "processing": 70, "succeeded": 100}
_REJECTED_STATUSES = {"failed", "canceled", "aborted"}


class ReplicateTextToVideoProvider:
    """Replicate asynchronous prediction adapter for text-to-video models."""

    provider_id = "replicate"
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

        model_input: dict[str, JSONValue] = {
            "prompt": request.prompt,
            "duration": request.duration,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
            "generate_audio": request.generate_audio,
        }
        if request.seed is not None:
            model_input["seed"] = request.seed

        try:
            response = self._http.post(
                f"{base_url}/predictions",
                headers=self._headers(api_key, json_content=True),
                json_payload={"version": model_id, "input": model_input},
                timeout=120,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not reach Replicate",
                retryable=True,
            ) from exc
        if response.status_code not in (200, 201):
            raise self._http_error(response.status_code, stage="submission")

        prediction = self._prediction(response)
        video_url = self._wait_for_result(
            prediction=prediction,
            api_key=api_key,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        self._raise_if_cancelled(
            is_cancelled,
            prediction=prediction,
            api_key=api_key,
        )
        self._download(video_url, output_path, api_key)

    def _wait_for_result(
        self,
        *,
        prediction: _Prediction,
        api_key: str,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + self._async_max_wait_s
        current = prediction
        while True:
            video_url = self._handle_status(current, on_progress)
            if video_url is not None:
                return video_url
            self._raise_if_cancelled(
                is_cancelled,
                prediction=current,
                api_key=api_key,
            )
            if time.monotonic() >= deadline:
                raise self._error(
                    "PROVIDER_TIMEOUT",
                    "Replicate generation timed out",
                    retryable=True,
                )
            time.sleep(self._poll_interval_s)
            try:
                response = self._http.get(
                    current.urls.get,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_NETWORK_ERROR",
                    "Could not reach the Replicate prediction",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise self._http_error(response.status_code, stage="status check")
            current = self._prediction(response)

    def _handle_status(
        self,
        prediction: _Prediction,
        on_progress: Callable[[int], None],
    ) -> str | None:
        if prediction.status in _REJECTED_STATUSES:
            raise self._error(
                "PROVIDER_REJECTED", "Replicate rejected the generation request"
            )
        progress = _PROGRESS.get(prediction.status)
        if progress is None:
            raise self._error(
                "PROVIDER_RESPONSE_INVALID",
                "Replicate returned an unknown prediction status",
            )
        on_progress(progress)
        if prediction.status != "succeeded":
            return None
        if not isinstance(prediction.output, str):
            raise self._error(
                "PROVIDER_RESPONSE_INVALID",
                "Replicate returned an invalid video output",
            )
        try:
            self._require_https_url(prediction.output)
        except ValueError as exc:
            raise self._error(
                "PROVIDER_RESPONSE_INVALID",
                "Replicate returned an invalid video output",
            ) from exc
        return prediction.output

    def _prediction(self, response: HttpResponseLike) -> _Prediction:
        try:
            prediction = _Prediction.model_validate(response.json())
            self._require_https_url(prediction.urls.get)
            self._require_https_url(prediction.urls.cancel)
            return prediction
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._error(
                "PROVIDER_RESPONSE_INVALID",
                "Replicate returned an invalid prediction response",
            ) from exc

    def _raise_if_cancelled(
        self,
        is_cancelled: Callable[[], bool],
        *,
        prediction: _Prediction | None = None,
        api_key: str | None = None,
    ) -> None:
        if not is_cancelled():
            return
        if prediction is not None and api_key is not None:
            try:
                response = self._http.post(
                    prediction.urls.cancel,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Could not cancel the Replicate prediction",
                    retryable=True,
                ) from exc
            if response.status_code not in (200, 201, 202):
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Replicate did not accept the cancellation request",
                    retryable=response.status_code == 429
                    or response.status_code >= 500,
                )
        raise GenerationCancelledError()

    def _download(self, video_url: str, output_path: Path, api_key: str) -> None:
        try:
            response = self._http.get(
                video_url,
                headers=self._headers(api_key),
                timeout=300,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the Replicate video",
                retryable=True,
            ) from exc
        if response.status_code != 200 or not response.content:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the Replicate video",
                retryable=True,
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not save the Replicate video",
                retryable=True,
            ) from exc

    @staticmethod
    def _configuration(profile: ProviderProfile) -> tuple[str, str]:
        if not profile.base_url or not profile.api_key:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="replicate",
                message="Replicate requires an API URL and credential",
            )
        parsed = urlparse(profile.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="replicate",
                message="Replicate requires an HTTPS API URL",
            )
        return profile.base_url.rstrip("/"), profile.api_key

    @staticmethod
    def _model_id(model_id: str) -> str:
        if not _MODEL_ID.fullmatch(model_id):
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="replicate",
                message="Replicate model ID must use a documented model identifier",
            )
        return model_id

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
            return ReplicateTextToVideoProvider._error(
                "PROVIDER_AUTHENTICATION_FAILED",
                "Replicate rejected the API credential",
            )
        return ReplicateTextToVideoProvider._error(
            "PROVIDER_REJECTED",
            f"Replicate rejected the {stage}",
            retryable=status_code == 429 or status_code >= 500,
        )

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> ProviderError:
        return ProviderError(
            code=code,
            provider="replicate",
            message=message,
            retryable=retryable,
        )
