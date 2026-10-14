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


class _CreatedTask(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str


class _TaskStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    progress: object | None = None
    output: list[object] | None = None


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")
_RATIOS = {("16:9", "720p"): "1280:720", ("9:16", "720p"): "720:1280"}
_RUNWAY_VERSION = "2024-11-06"


class RunwayTextToVideoProvider:
    """Runway task adapter for the Gen-4.5 text-to-video schema."""

    provider_id = "runway"
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
        model_id = self._safe_token(request.model_id, field="model ID")
        ratio = self._ratio(request.aspect_ratio, request.resolution)
        duration = self._duration(request.duration)
        self._raise_if_cancelled(is_cancelled)

        payload: dict[str, JSONValue] = {
            "model": model_id,
            "promptText": request.prompt,
            "duration": duration,
            "ratio": ratio,
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        try:
            response = self._http.post(
                f"{base_url}/text_to_video",
                headers=self._headers(api_key, json_content=True),
                json_payload=payload,
                timeout=120,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not reach Runway",
                retryable=True,
            ) from exc
        if response.status_code not in (200, 201, 202):
            raise self._http_error(response.status_code, stage="submission")
        task_id = self._created_task_id(response)
        video_url = self._poll(
            base_url=base_url,
            task_id=task_id,
            api_key=api_key,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        self._raise_if_cancelled(
            is_cancelled,
            task_url=f"{base_url}/tasks/{task_id}",
            api_key=api_key,
        )
        self._download(video_url, output_path)

    def _poll(
        self,
        *,
        base_url: str,
        task_id: str,
        api_key: str,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + self._async_max_wait_s
        task_url = f"{base_url}/tasks/{task_id}"
        while time.monotonic() < deadline:
            self._raise_if_cancelled(
                is_cancelled,
                task_url=task_url,
                api_key=api_key,
            )
            try:
                response = self._http.get(
                    task_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_NETWORK_ERROR",
                    "Could not reach the Runway task",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise self._http_error(response.status_code, stage="status check")
            status = self._task_status(response)
            video_url = self._handle_status(status, on_progress)
            if video_url is not None:
                return video_url
            self._raise_if_cancelled(
                is_cancelled,
                task_url=task_url,
                api_key=api_key,
            )
            time.sleep(self._poll_interval_s)
        raise self._error(
            "PROVIDER_TIMEOUT", "Runway generation timed out", retryable=True
        )

    def _handle_status(
        self,
        task: _TaskStatus,
        on_progress: Callable[[int], None],
    ) -> str | None:
        if task.status in {"FAILED", "CANCELLED"}:
            raise self._error(
                "PROVIDER_REJECTED", "Runway rejected the generation request"
            )
        if task.status == "PENDING":
            on_progress(10)
            return None
        if task.status == "THROTTLED":
            on_progress(20)
            return None
        if task.status == "RUNNING":
            if (
                isinstance(task.progress, bool)
                or not isinstance(task.progress, (int, float))
                or not 0 <= task.progress <= 1
            ):
                raise self._invalid_response("Runway returned invalid task progress")
            on_progress(30 + round(float(task.progress) * 60))
            return None
        if task.status != "SUCCEEDED":
            raise self._invalid_response("Runway returned an unknown task status")
        if task.output is None:
            raise self._invalid_response("Runway returned an invalid task output")
        output = task.output
        if not output or not isinstance(output[0], str):
            raise self._invalid_response("Runway returned an invalid task output")
        video_url = output[0]
        try:
            self._require_https_url(video_url)
        except ValueError as exc:
            raise self._invalid_response("Runway returned an invalid task output") from exc
        on_progress(100)
        return video_url

    def _raise_if_cancelled(
        self,
        is_cancelled: Callable[[], bool],
        *,
        task_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        if not is_cancelled():
            return
        if task_url is not None and api_key is not None:
            try:
                response = self._http.delete(
                    task_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Could not cancel the Runway task",
                    retryable=True,
                ) from exc
            if response.status_code not in (200, 202, 204):
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Runway did not accept the cancellation request",
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
                "Could not download the Runway video",
                retryable=True,
            ) from exc
        if response.status_code != 200 or not response.content:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the Runway video",
                retryable=True,
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not save the Runway video",
                retryable=True,
            ) from exc

    def _created_task_id(self, response: HttpResponseLike) -> str:
        try:
            task_id = _CreatedTask.model_validate(response.json()).id
            return self._safe_token(task_id, field="task ID")
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response(
                "Runway returned an invalid task submission response"
            ) from exc
        except ProviderError as exc:
            raise self._invalid_response(
                "Runway returned an invalid task submission response"
            ) from exc

    def _task_status(self, response: HttpResponseLike) -> _TaskStatus:
        try:
            return _TaskStatus.model_validate(response.json())
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response("Runway returned an invalid task response") from exc

    @staticmethod
    def _configuration(profile: ProviderProfile) -> tuple[str, str]:
        if not profile.base_url or not profile.api_key:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="runway",
                message="Runway requires an API URL and credential",
            )
        parsed = urlparse(profile.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="runway",
                message="Runway requires an HTTPS API URL",
            )
        return profile.base_url.rstrip("/"), profile.api_key

    @staticmethod
    def _safe_token(value: str, *, field: str) -> str:
        if not _SAFE_TOKEN.fullmatch(value):
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="runway",
                message=f"Runway {field} is invalid",
            )
        return value

    @staticmethod
    def _ratio(aspect_ratio: str, resolution: str) -> str:
        ratio = _RATIOS.get((aspect_ratio, resolution))
        if ratio is None:
            raise ProviderError(
                code="PROVIDER_CAPABILITY_UNSUPPORTED",
                provider="runway",
                message="Runway Gen-4.5 supports landscape or portrait 720p output",
            )
        return ratio

    @staticmethod
    def _duration(duration: int | float | None) -> int:
        if (
            duration is None
            or isinstance(duration, bool)
            or not float(duration).is_integer()
            or not 2 <= duration <= 10
        ):
            raise ProviderError(
                code="PROVIDER_CAPABILITY_UNSUPPORTED",
                provider="runway",
                message="Runway Gen-4.5 duration must be a whole number from 2 to 10",
            )
        return int(duration)

    @staticmethod
    def _require_https_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("expected an absolute HTTPS URL")

    @staticmethod
    def _headers(api_key: str, *, json_content: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Runway-Version": _RUNWAY_VERSION,
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _http_error(status_code: int, *, stage: str) -> ProviderError:
        if status_code in (401, 403):
            return RunwayTextToVideoProvider._error(
                "PROVIDER_AUTHENTICATION_FAILED",
                "Runway rejected the API credential",
            )
        return RunwayTextToVideoProvider._error(
            "PROVIDER_REJECTED",
            f"Runway rejected the {stage}",
            retryable=status_code == 429 or status_code >= 500,
        )

    @staticmethod
    def _invalid_response(message: str) -> ProviderError:
        return RunwayTextToVideoProvider._error("PROVIDER_RESPONSE_INVALID", message)

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> ProviderError:
        return ProviderError(
            code=code,
            provider="runway",
            message=message,
            retryable=retryable,
        )
