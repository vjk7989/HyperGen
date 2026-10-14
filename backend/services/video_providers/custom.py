from __future__ import annotations

import ipaddress
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import ParseResult, urlparse

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


class _CreatedJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: object


class _JobStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    state: object
    progress: object
    result_url: object | None = None


_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TERMINAL_FAILURES = {"failed", "cancelled"}
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


class CustomTextToVideoProvider:
    """Adapter for the HyperGen-compatible asynchronous REST contract."""

    provider_id = "custom"
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
        base_url, base = self._configuration(profile)
        self._validate_model(request.model_id)
        self._raise_if_cancelled(is_cancelled)
        payload: dict[str, JSONValue] = {
            "prompt": request.prompt,
            "model": request.model_id,
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "duration": request.duration,
            "fps": request.fps,
            "generate_audio": request.generate_audio,
        }
        try:
            response = self._http.post(
                f"{base_url}/v1/text-to-video",
                headers=self._headers(profile.api_key, json_content=True),
                json_payload=payload,
                timeout=120,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_NETWORK_ERROR",
                "Could not reach the custom video provider",
                retryable=True,
            ) from exc
        if response.status_code not in (200, 201, 202):
            raise self._http_error(response.status_code, stage="submission")
        job_id = self._job_id(response)
        result_url = self._poll(
            base_url=base_url,
            job_id=job_id,
            api_key=profile.api_key,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        self._raise_if_cancelled(
            is_cancelled,
            cancel_url=f"{base_url}/v1/text-to-video/{job_id}/cancel",
            api_key=profile.api_key,
        )
        result = self._safe_url(result_url, allow_query=True)
        download_key = profile.api_key if self._same_origin(base, result) else None
        self._download(result_url, output_path, api_key=download_key)

    def _poll(
        self,
        *,
        base_url: str,
        job_id: str,
        api_key: str | None,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + self._async_max_wait_s
        job_url = f"{base_url}/v1/text-to-video/{job_id}"
        cancel_url = f"{job_url}/cancel"
        while time.monotonic() < deadline:
            self._raise_if_cancelled(
                is_cancelled,
                cancel_url=cancel_url,
                api_key=api_key,
            )
            try:
                response = self._http.get(
                    job_url,
                    headers=self._headers(api_key),
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_NETWORK_ERROR",
                    "Could not reach the custom video job",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise self._http_error(response.status_code, stage="status check")
            status = self._job_status(response)
            progress = self._progress(status.progress)
            state = self._state(status.state)
            if state in _TERMINAL_FAILURES:
                raise self._error(
                    "PROVIDER_REJECTED",
                    "The custom provider rejected the generation request",
                )
            if state == "succeeded":
                if not isinstance(status.result_url, str):
                    raise self._invalid_response(
                        "The custom provider returned an invalid result URL"
                    )
                try:
                    self._safe_url(status.result_url, allow_query=True)
                except ValueError as exc:
                    raise self._invalid_response(
                        "The custom provider returned an invalid result URL"
                    ) from exc
                on_progress(100)
                return status.result_url
            on_progress(progress)
            self._raise_if_cancelled(
                is_cancelled,
                cancel_url=cancel_url,
                api_key=api_key,
            )
            time.sleep(self._poll_interval_s)
        raise self._error(
            "PROVIDER_TIMEOUT",
            "Custom video generation timed out",
            retryable=True,
        )

    def _raise_if_cancelled(
        self,
        is_cancelled: Callable[[], bool],
        *,
        cancel_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        if not is_cancelled():
            return
        if cancel_url is not None:
            try:
                response = self._http.post(
                    cancel_url,
                    headers=self._headers(api_key, json_content=True),
                    json_payload={},
                    timeout=60,
                )
            except HttpTransportError as exc:
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "Could not cancel the custom video job",
                    retryable=True,
                ) from exc
            if response.status_code not in (200, 202, 204):
                raise self._error(
                    "PROVIDER_CANCELLATION_FAILED",
                    "The custom provider did not accept cancellation",
                    retryable=response.status_code == 429
                    or response.status_code >= 500,
                )
        raise GenerationCancelledError()

    def _download(
        self,
        result_url: str,
        output_path: Path,
        *,
        api_key: str | None,
    ) -> None:
        try:
            response = self._http.get(
                result_url,
                headers=self._headers(api_key),
                timeout=300,
            )
        except HttpTransportError as exc:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the custom provider video",
                retryable=True,
            ) from exc
        if response.status_code != 200 or not response.content:
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not download the custom provider video",
                retryable=True,
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise self._error(
                "PROVIDER_DOWNLOAD_FAILED",
                "Could not save the custom provider video",
                retryable=True,
            ) from exc

    def _job_id(self, response: HttpResponseLike) -> str:
        try:
            value = _CreatedJob.model_validate(response.json()).id
            if not isinstance(value, str) or not _SAFE_JOB_ID.fullmatch(value):
                raise ValueError("invalid job ID")
            return value
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response(
                "The custom provider returned an invalid submission response"
            ) from exc

    def _job_status(self, response: HttpResponseLike) -> _JobStatus:
        try:
            return _JobStatus.model_validate(response.json())
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise self._invalid_response(
                "The custom provider returned an invalid job status"
            ) from exc

    @classmethod
    def _configuration(cls, profile: ProviderProfile) -> tuple[str, ParseResult]:
        if not profile.base_url:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="custom",
                message="The custom provider requires an API URL",
            )
        try:
            parsed = cls._safe_url(profile.base_url, allow_query=False)
        except ValueError as exc:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="custom",
                message="The custom provider API URL is invalid",
            ) from exc
        return profile.base_url.rstrip("/"), parsed

    @staticmethod
    def _validate_model(value: str) -> None:
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="custom",
                message="The custom provider model ID is invalid",
            )

    @staticmethod
    def _state(value: object) -> str:
        if not isinstance(value, str) or value not in {
            "queued",
            "running",
            "succeeded",
            "failed",
            "cancelled",
        }:
            raise CustomTextToVideoProvider._invalid_response(
                "The custom provider returned an invalid job state"
            )
        return value

    @staticmethod
    def _progress(value: object) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 100
        ):
            raise CustomTextToVideoProvider._invalid_response(
                "The custom provider returned invalid job progress"
            )
        return round(float(value))

    @staticmethod
    def _safe_url(value: str, *, allow_query: bool) -> ParseResult:
        parsed = urlparse(value)
        try:
            hostname = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise ValueError("invalid port") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or (parsed.query and not allow_query)
        ):
            raise ValueError("unsafe URL")
        if parsed.scheme == "http" and not CustomTextToVideoProvider._is_local_host(
            hostname
        ):
            raise ValueError("public HTTP is not permitted")
        return parsed

    @staticmethod
    def _is_local_host(hostname: str) -> bool:
        lowered = hostname.rstrip(".").lower()
        if lowered == "localhost" or lowered.endswith(".localhost"):
            return True
        try:
            address = ipaddress.ip_address(lowered)
        except ValueError:
            return False
        return (
            address.is_loopback
            or address.is_link_local
            or any(address in network for network in _PRIVATE_NETWORKS)
        )

    @staticmethod
    def _same_origin(left: ParseResult, right: ParseResult) -> bool:
        def origin(parsed: ParseResult) -> tuple[str, str | None, int | None]:
            default_port = 443 if parsed.scheme == "https" else 80
            return parsed.scheme, parsed.hostname, parsed.port or default_port

        return origin(left) == origin(right)

    @staticmethod
    def _headers(
        api_key: str | None,
        *,
        json_content: bool = False,
    ) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers or None

    @staticmethod
    def _http_error(status_code: int, *, stage: str) -> ProviderError:
        if status_code in (401, 403):
            return CustomTextToVideoProvider._error(
                "PROVIDER_AUTHENTICATION_FAILED",
                "The custom provider rejected the credential",
            )
        return CustomTextToVideoProvider._error(
            "PROVIDER_REJECTED",
            f"The custom provider rejected the {stage}",
            retryable=status_code == 429 or status_code >= 500,
        )

    @staticmethod
    def _invalid_response(message: str) -> ProviderError:
        return CustomTextToVideoProvider._error("PROVIDER_RESPONSE_INVALID", message)

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> ProviderError:
        return ProviderError(
            code=code,
            provider="custom",
            message=message,
            retryable=retryable,
        )
