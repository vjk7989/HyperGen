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
from services.video_providers.fal import FalTextToVideoProvider
from tests.fakes.services import FakeHTTPClient, FakeResponse


_SECRET = "fal-secret-never-log"
_MODEL_ID = "fal-ai/kling-video/v3/4k/text-to-video"
_STATUS_URL = "https://queue.fal.run/status-tickets/request-1"
_RESPONSE_URL = "https://queue.fal.run/response-tickets/request-1"
_CANCEL_URL = "https://queue.fal.run/cancel-tickets/request-1"
_VIDEO_URL = "https://v3.fal.media/files/result.mp4"


def _profile(*, model_id: str = _MODEL_ID) -> ProviderProfile:
    return ProviderProfile(
        provider_id="fal",
        base_url="https://queue.fal.run/",
        model_id=model_id,
        api_key=_SECRET,
    )


def _request(*, model_id: str = _MODEL_ID) -> ProviderTextToVideoRequest:
    return ProviderTextToVideoRequest(
        prompt="A fox crosses a snowy ridge",
        model_id=model_id,
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
) -> FalTextToVideoProvider:
    return FalTextToVideoProvider(
        http,
        poll_interval_s=0.0,
        async_max_wait_s=async_max_wait_s,
    )


def _generate(
    provider: FalTextToVideoProvider,
    output_path: Path,
    *,
    request: ProviderTextToVideoRequest | None = None,
    profile: ProviderProfile | None = None,
    on_progress: Callable[[int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    provider.generate(
        request or _request(),
        profile or _profile(),
        output_path,
        on_progress=on_progress or (lambda _progress: None),
        is_cancelled=is_cancelled or (lambda: False),
    )


def _submit_response() -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "request_id": "request-1",
            "status_url": _STATUS_URL,
            "response_url": _RESPONSE_URL,
            "cancel_url": _CANCEL_URL,
        },
    )


def test_fal_maps_kling_request_polls_and_downloads_to_queue_path(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        FakeResponse(status_code=200, json_payload={"status": "IN_QUEUE"}),
        FakeResponse(status_code=200, json_payload={"status": "IN_PROGRESS"}),
        FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}),
        FakeResponse(
            status_code=200,
            json_payload={"video": {"url": _VIDEO_URL}},
        ),
        FakeResponse(status_code=200, content=b"downloaded-video"),
    )
    progress: list[int] = []
    output_path = tmp_path / "queue-output" / "result.mp4"

    _generate(_provider(http), output_path, on_progress=progress.append)

    assert output_path.read_bytes() == b"downloaded-video"
    assert len(progress) == 3
    assert all(left < right for left, right in pairwise(progress))
    assert progress[-1] == 100

    submit, queued, running, completed, result, download = http.calls
    assert submit.method == "post"
    assert submit.url == f"https://queue.fal.run/{_MODEL_ID}"
    assert submit.headers == {
        "Authorization": f"Key {_SECRET}",
        "Content-Type": "application/json",
    }
    assert submit.json_payload == {
        "prompt": "A fox crosses a snowy ridge",
        "duration": "5",
        "aspect_ratio": "16:9",
        "generate_audio": True,
        "negative_prompt": "compression artifacts",
    }
    assert "resolution" not in submit.json_payload
    assert "fps" not in submit.json_payload
    assert "seed" not in submit.json_payload
    assert [call.url for call in (queued, running, completed)] == [_STATUS_URL] * 3
    assert all(
        call.headers is not None
        and call.headers["Authorization"] == f"Key {_SECRET}"
        for call in (queued, running, completed, result)
    )
    assert result.url == _RESPONSE_URL
    assert download.url == _VIDEO_URL
    assert download.headers is None


@pytest.mark.parametrize(
    "cancel_response",
    [
        FakeResponse(status_code=202),
        FakeResponse(
            status_code=400,
            json_payload={"status": "ALREADY_COMPLETED"},
        ),
    ],
    ids=["accepted", "already-completed-race"],
)
def test_fal_local_cancellation_uses_returned_cancel_url_and_stops_safely(
    tmp_path: Path,
    cancel_response: FakeResponse,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        FakeResponse(status_code=200, json_payload={"status": "IN_QUEUE"}),
    )
    http.queue("put", cancel_response)
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
        ("post", f"https://queue.fal.run/{_MODEL_ID}"),
        ("get", _STATUS_URL),
        ("put", _CANCEL_URL),
    ]
    cancel = http.calls[-1]
    assert cancel.headers is not None
    assert cancel.headers["Authorization"] == f"Key {_SECRET}"
    assert cancel.data is None
    assert output_path.exists() is False


@pytest.mark.parametrize(
    "model_id",
    [
        "https://attacker.example/model",
        "//attacker.example/model",
        "../outside-base",
    ],
)
def test_fal_rejects_model_ids_that_can_escape_the_configured_base_url(
    tmp_path: Path,
    model_id: str,
) -> None:
    http = FakeHTTPClient()

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http),
            tmp_path / "unsafe.mp4",
            request=_request(model_id=model_id),
            profile=_profile(model_id=model_id),
        )

    assert raised.value.code == "PROVIDER_CONFIGURATION_INVALID"
    assert raised.value.provider == "fal"
    assert http.calls == []


@pytest.mark.parametrize(
    "case",
    [
        "submit-request-id",
        "submit-status-url",
        "submit-response-url",
        "submit-cancel-url",
        "status",
        "result",
    ],
)
def test_fal_malformed_queue_responses_are_normalized(
    tmp_path: Path,
    case: str,
) -> None:
    http = FakeHTTPClient()
    submit = _submit_response()
    if case == "submit-request-id":
        del submit.json_payload["request_id"]
    elif case.startswith("submit-"):
        field = case.removeprefix("submit-").replace("-", "_")
        submit.json_payload[field] = "not-an-absolute-url"
    http.queue("post", submit)
    if case == "status":
        http.queue(
            "get",
            FakeResponse(status_code=200, json_payload={"status": "UNKNOWN"}),
        )
    elif case == "result":
        http.queue(
            "get",
            FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}),
            FakeResponse(status_code=200, json_payload={"video": {}}),
        )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "malformed.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "fal"
    assert raised.value.retryable is False
    assert (tmp_path / "malformed.mp4").exists() is False


@pytest.mark.parametrize(
    ("case", "expected_code", "retryable"),
    [
        ("auth", "PROVIDER_AUTHENTICATION_FAILED", False),
        ("queue-error", "PROVIDER_REJECTED", False),
        ("timeout", "PROVIDER_TIMEOUT", True),
        ("network", "PROVIDER_NETWORK_ERROR", True),
    ],
)
def test_fal_failures_are_normalized_without_credentials(
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
                json_payload={"detail": f"invalid key {_SECRET}"},
            ),
        )
    elif case == "queue-error":
        http.queue("post", _submit_response())
        http.queue(
            "get",
            FakeResponse(
                status_code=200,
                json_payload={
                    "status": "COMPLETED",
                    "error": f"request rejected for {_SECRET}",
                    "error_type": "CONTENT_POLICY",
                },
            ),
        )
    elif case == "timeout":
        http.queue("post", _submit_response())
        max_wait = 0.0
    else:
        http.queue("post", HttpTransportError(f"connection reset: {_SECRET}"))

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http, async_max_wait_s=max_wait),
            tmp_path / "failed.mp4",
        )

    error = raised.value
    assert error.code == expected_code
    assert error.provider == "fal"
    assert error.retryable is retryable
    serialized = json.dumps(error.to_dict())
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in serialized
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "download_response",
    [
        FakeResponse(status_code=503, text="download unavailable"),
        FakeResponse(status_code=200, content=b""),
    ],
    ids=["http-failure", "empty-output"],
)
def test_fal_failed_or_empty_download_is_normalized_and_not_persisted(
    tmp_path: Path,
    download_response: FakeResponse,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}),
        FakeResponse(
            status_code=200,
            json_payload={"video": {"url": _VIDEO_URL}},
        ),
        download_response,
    )
    output_path = tmp_path / "download-failed.mp4"

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), output_path)

    assert raised.value.code == "PROVIDER_DOWNLOAD_FAILED"
    assert raised.value.provider == "fal"
    assert raised.value.retryable is True
    assert output_path.exists() is False
