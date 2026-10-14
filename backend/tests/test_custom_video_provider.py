from __future__ import annotations

import json
import logging
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

import pytest

from services.generation_interrupt import GenerationCancelledError
from services.http_client.http_client import HttpTransportError
from services.video_providers import (
    ProviderError,
    ProviderProfile,
    ProviderTextToVideoRequest,
)
from services.video_providers.custom import CustomTextToVideoProvider
from tests.fakes.services import FakeHTTPClient, FakeResponse


_SECRET = "custom-secret-never-log"
_BASE_URL = "https://video.example.com"
_MODEL_ID = "self-hosted/video:v2"
_JOB_ID = "job_abc-123"
_JOB_URL = f"{_BASE_URL}/v1/text-to-video/{_JOB_ID}"
_CANCEL_URL = f"{_JOB_URL}/cancel"
_SAME_ORIGIN_RESULT_URL = f"{_BASE_URL}/files/result.mp4"
_CROSS_ORIGIN_RESULT_URL = (
    "https://cdn.example.net/presigned/result.mp4?X-Amz-Signature=download-token"
)


def _profile(
    *,
    base_url: str = _BASE_URL,
    api_key: str | None = _SECRET,
) -> ProviderProfile:
    return ProviderProfile(
        provider_id="custom",
        base_url=base_url,
        model_id=_MODEL_ID,
        api_key=api_key,
    )


def _request() -> ProviderTextToVideoRequest:
    return ProviderTextToVideoRequest(
        prompt="A fox crosses a snowy ridge",
        model_id=_MODEL_ID,
        aspect_ratio="16:9",
        resolution="1080p",
        duration=5,
        fps=24,
        generate_audio=True,
        negative_prompt="compression artifacts",
        seed=123,
    )


def _provider(
    http: FakeHTTPClient,
    *,
    async_max_wait_s: float = 5.0,
) -> CustomTextToVideoProvider:
    return CustomTextToVideoProvider(
        http,
        poll_interval_s=0.0,
        async_max_wait_s=async_max_wait_s,
    )


def _generate(
    provider: CustomTextToVideoProvider,
    output_path: Path,
    *,
    profile: ProviderProfile | None = None,
    on_progress: Callable[[int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    provider.generate(
        _request(),
        profile or _profile(),
        output_path,
        on_progress=on_progress or (lambda _progress: None),
        is_cancelled=is_cancelled or (lambda: False),
    )


def _submit_response(*, job_id: object = _JOB_ID) -> FakeResponse:
    return FakeResponse(status_code=202, json_payload={"id": job_id})


def _status(
    state: object,
    *,
    progress: object = 0,
    result_url: object | None = None,
    error: str | None = None,
) -> FakeResponse:
    payload: dict[str, object | None] = {
        "state": state,
        "progress": progress,
    }
    if result_url is not None:
        payload["result_url"] = result_url
    if error is not None:
        payload["error"] = error
    return FakeResponse(status_code=200, json_payload=payload)


def _job_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/v1/text-to-video/{_JOB_ID}"


def _queue_immediate_success(
    http: FakeHTTPClient,
    *,
    result_url: str,
) -> None:
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _status("succeeded", progress=100, result_url=result_url),
        FakeResponse(status_code=200, content=b"video"),
    )


def test_custom_maps_request_tracks_progress_and_authenticates_same_origin_download(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _status("queued", progress=5),
        _status("running", progress=65),
        _status("succeeded", progress=100, result_url=_SAME_ORIGIN_RESULT_URL),
        FakeResponse(status_code=200, content=b"downloaded-video"),
    )
    progress: list[int] = []
    output_path = tmp_path / "queue-output" / "result.mp4"

    _generate(_provider(http), output_path, on_progress=progress.append)

    assert output_path.read_bytes() == b"downloaded-video"
    assert progress == [5, 65, 100]
    assert all(left < right for left, right in pairwise(progress))

    submit, queued, running, succeeded, download = http.calls
    assert submit.method == "post"
    assert submit.url == f"{_BASE_URL}/v1/text-to-video"
    assert submit.headers == {
        "Authorization": f"Bearer {_SECRET}",
        "Content-Type": "application/json",
    }
    assert submit.json_payload == {
        "prompt": "A fox crosses a snowy ridge",
        "model": _MODEL_ID,
        "aspect_ratio": "16:9",
        "resolution": "1080p",
        "duration": 5,
        "fps": 24,
        "generate_audio": True,
    }
    assert "negative_prompt" not in submit.json_payload
    assert "seed" not in submit.json_payload
    assert [call.url for call in (queued, running, succeeded)] == [_JOB_URL] * 3
    assert all(
        call.headers is not None
        and call.headers["Authorization"] == f"Bearer {_SECRET}"
        for call in (queued, running, succeeded)
    )
    assert download.url == _SAME_ORIGIN_RESULT_URL
    assert download.headers == {"Authorization": f"Bearer {_SECRET}"}


def test_custom_omits_authorization_when_profile_has_no_key(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    base_url = "http://localhost:8080"
    result_url = f"{base_url}/files/result.mp4"
    _queue_immediate_success(http, result_url=result_url)

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        profile=_profile(base_url=base_url, api_key=None),
    )

    assert all("Authorization" not in (call.headers or {}) for call in http.calls)


def test_custom_never_sends_bearer_to_cross_origin_https_result(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    _queue_immediate_success(http, result_url=_CROSS_ORIGIN_RESULT_URL)

    _generate(_provider(http), tmp_path / "result.mp4")

    submit, status, download = http.calls
    assert submit.headers is not None
    assert submit.headers["Authorization"] == f"Bearer {_SECRET}"
    assert status.headers is not None
    assert status.headers["Authorization"] == f"Bearer {_SECRET}"
    assert download.url == _CROSS_ORIGIN_RESULT_URL
    assert "Authorization" not in (download.headers or {})


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8080",
        "http://api.localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
        "http://10.0.0.7:8080",
        "http://172.16.1.7:8080",
        "http://192.168.1.7:8080",
        "http://169.254.1.7:8080",
        "http://[fd00::7]:8080",
        "http://[fe80::7]:8080",
    ],
)
def test_custom_allows_http_for_local_private_and_link_local_hosts(
    tmp_path: Path,
    base_url: str,
) -> None:
    http = FakeHTTPClient()
    result_url = f"{base_url}/files/result.mp4"
    _queue_immediate_success(http, result_url=result_url)

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        profile=_profile(base_url=base_url, api_key=None),
    )

    assert http.calls[0].url == f"{base_url}/v1/text-to-video"
    assert http.calls[1].url == _job_url(base_url)
    assert http.calls[2].url == result_url


@pytest.mark.parametrize(
    "base_url",
    [
        "http://video.example.com",
        "http://8.8.8.8",
        "http://[2001:4860:4860::8888]",
        "http://localhost.example.com",
        "ftp://video.example.com",
        "file:///tmp/video",
        "https://user:password@video.example.com",
        "https://video.example.com?tenant=one",
        "https://video.example.com#fragment",
    ],
)
def test_custom_rejects_unsafe_base_urls_before_submission(
    tmp_path: Path,
    base_url: str,
) -> None:
    http = FakeHTTPClient()

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http),
            tmp_path / "unsafe-base.mp4",
            profile=_profile(base_url=base_url),
        )

    assert raised.value.code == "PROVIDER_CONFIGURATION_INVALID"
    assert raised.value.provider == "custom"
    assert http.calls == []


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        ".",
        "..",
        "../escape",
        "job/escape",
        "job%2Fescape",
        "job?tenant=one",
        "job\\escape",
        "https://attacker.example/job",
    ],
)
def test_custom_rejects_unsafe_or_malformed_job_ids(
    tmp_path: Path,
    job_id: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response(job_id=job_id))

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "unsafe-id.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "custom"
    assert len(http.calls) == 1


def test_custom_local_cancellation_posts_to_cancel_endpoint(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    http.queue(
        "post",
        _submit_response(),
        FakeResponse(status_code=202, json_payload={"state": "cancelled"}),
    )
    http.queue("get", _status("queued", progress=10))
    cancelled = False

    def on_progress(_progress: int) -> None:
        nonlocal cancelled
        cancelled = True

    output_path = tmp_path / "cancelled.mp4"
    with pytest.raises(GenerationCancelledError):
        _generate(
            _provider(http),
            output_path,
            on_progress=on_progress,
            is_cancelled=lambda: cancelled,
        )

    assert [(call.method, call.url) for call in http.calls] == [
        ("post", f"{_BASE_URL}/v1/text-to-video"),
        ("get", _JOB_URL),
        ("post", _CANCEL_URL),
    ]
    cancel = http.calls[-1]
    assert cancel.headers is not None
    assert cancel.headers["Authorization"] == f"Bearer {_SECRET}"
    assert output_path.exists() is False


@pytest.mark.parametrize(
    "cancel_response",
    [
        FakeResponse(status_code=500, text="cancel failed"),
        HttpTransportError("cancel reset"),
    ],
    ids=["http-failure", "network-failure"],
)
def test_custom_cancel_failures_are_normalized(
    tmp_path: Path,
    cancel_response: FakeResponse | Exception,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response(), cancel_response)
    http.queue("get", _status("running", progress=35))
    cancelled = False

    def on_progress(_progress: int) -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http),
            tmp_path / "cancel-failed.mp4",
            on_progress=on_progress,
            is_cancelled=lambda: cancelled,
        )

    assert raised.value.code == "PROVIDER_CANCELLATION_FAILED"
    assert raised.value.provider == "custom"
    assert raised.value.retryable is True


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_custom_unsuccessful_terminal_states_are_redacted_provider_rejections(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    state: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _status(
            state,
            progress=70,
            error=f"provider failure containing {_SECRET}",
        ),
    )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "failed.mp4")

    error = raised.value
    assert error.code == "PROVIDER_REJECTED"
    assert error.provider == "custom"
    assert error.retryable is False
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "case",
    [
        "missing-state",
        "state-type",
        "unknown-state",
        "missing-progress",
        "progress-type",
        "progress-low",
        "progress-high",
        "missing-result",
        "result-type",
    ],
)
def test_custom_malformed_status_or_progress_is_normalized(
    tmp_path: Path,
    case: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    response = _status(
        "succeeded",
        progress=100,
        result_url=_SAME_ORIGIN_RESULT_URL,
    )
    if case == "missing-state":
        del response.json_payload["state"]
    elif case == "state-type":
        response.json_payload["state"] = {"unexpected": "object"}
    elif case == "unknown-state":
        response.json_payload["state"] = "unknown"
    elif case == "missing-progress":
        del response.json_payload["progress"]
    elif case == "progress-type":
        response.json_payload["progress"] = "50"
    elif case == "progress-low":
        response.json_payload["progress"] = -1
    elif case == "progress-high":
        response.json_payload["progress"] = 101
    elif case == "missing-result":
        del response.json_payload["result_url"]
    else:
        response.json_payload["result_url"] = [_SAME_ORIGIN_RESULT_URL]
    http.queue("get", response)

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "malformed.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "custom"
    assert raised.value.retryable is False
    assert (tmp_path / "malformed.mp4").exists() is False


@pytest.mark.parametrize(
    "result_url",
    [
        "http://video.example.com/result.mp4",
        "ftp://video.example.com/result.mp4",
        "file:///tmp/result.mp4",
        "https://user:password@video.example.com/result.mp4",
        "https://video.example.com/result.mp4#fragment",
    ],
)
def test_custom_rejects_unsafe_result_urls(
    tmp_path: Path,
    result_url: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _status("succeeded", progress=100, result_url=result_url),
    )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "unsafe-result.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "custom"
    assert len(http.calls) == 2


@pytest.mark.parametrize(
    ("case", "expected_code", "retryable"),
    [
        ("auth", "PROVIDER_AUTHENTICATION_FAILED", False),
        ("rejected", "PROVIDER_REJECTED", False),
        ("network", "PROVIDER_NETWORK_ERROR", True),
        ("timeout", "PROVIDER_TIMEOUT", True),
    ],
)
def test_custom_failures_are_normalized_without_credentials(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    case: str,
    expected_code: str,
    retryable: bool,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    max_wait = 5.0
    if case == "auth":
        http.queue(
            "post",
            FakeResponse(
                status_code=401,
                json_payload={"error": f"invalid key {_SECRET}"},
            ),
        )
    elif case == "rejected":
        http.queue(
            "post",
            FakeResponse(
                status_code=422,
                json_payload={"error": f"invalid request {_SECRET}"},
            ),
        )
    elif case == "network":
        http.queue("post", HttpTransportError(f"connection reset: {_SECRET}"))
    else:
        http.queue("post", _submit_response())
        max_wait = 0.0

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http, async_max_wait_s=max_wait),
            tmp_path / "failed.mp4",
        )

    error = raised.value
    assert error.code == expected_code
    assert error.provider == "custom"
    assert error.retryable is retryable
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "download_response",
    [
        FakeResponse(status_code=503, text=f"download failed {_SECRET}"),
        FakeResponse(status_code=200, content=b""),
        HttpTransportError(f"download reset {_SECRET}"),
    ],
    ids=["http-failure", "empty-output", "network-failure"],
)
def test_custom_download_failures_are_normalized_and_redacted(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    download_response: FakeResponse | Exception,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _status(
            "succeeded",
            progress=100,
            result_url=_SAME_ORIGIN_RESULT_URL,
        ),
        download_response,
    )
    output_path = tmp_path / "download-failed.mp4"

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), output_path)

    error = raised.value
    assert error.code == "PROVIDER_DOWNLOAD_FAILED"
    assert error.provider == "custom"
    assert error.retryable is True
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert output_path.exists() is False
