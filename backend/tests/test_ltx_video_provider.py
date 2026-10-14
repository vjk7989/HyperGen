from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import pytest

from services.generation_interrupt import GenerationCancelledError
from services.http_client.http_client import HttpTransportError
from services.video_providers import (
    ProviderError,
    ProviderProfile,
    ProviderTextToVideoRequest,
)
from services.video_providers.ltx import LTXTextToVideoProvider
from tests.fakes.services import FakeHTTPClient, FakeResponse


_SECRET = "ltx-secret-never-log"


def _profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id="ltx",
        base_url="https://api.ltx.video",
        model_id="ltx-2-5-fast",
        api_key=_SECRET,
    )


def _request() -> ProviderTextToVideoRequest:
    return ProviderTextToVideoRequest(
        prompt="A fox crosses a snowy ridge",
        model_id="ltx-2-5-fast",
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
) -> LTXTextToVideoProvider:
    return LTXTextToVideoProvider(
        http,
        poll_interval_s=0.0,
        async_max_wait_s=async_max_wait_s,
    )


def _generate(
    provider: LTXTextToVideoProvider,
    output_path: Path,
    *,
    on_progress: Callable[[int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    provider.generate(
        _request(),
        _profile(),
        output_path,
        on_progress=on_progress or (lambda _progress: None),
        is_cancelled=is_cancelled or (lambda: False),
    )


def test_ltx_v2_maps_shared_request_polls_progress_and_downloads_to_output(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=202, json_payload={"id": "job-1"}))
    http.queue(
        "get",
        FakeResponse(status_code=200, json_payload={"status": "pending"}),
        FakeResponse(status_code=200, json_payload={"status": "processing"}),
        FakeResponse(
            status_code=200,
            json_payload={
                "status": "completed",
                "result": {"video_url": "https://cdn.example.com/result.mp4"},
            },
        ),
        FakeResponse(status_code=200, content=b"downloaded-video"),
    )
    progress: list[int] = []
    output_path = tmp_path / "queue-output" / "result.mp4"

    _generate(_provider(http), output_path, on_progress=progress.append)

    assert output_path.read_bytes() == b"downloaded-video"
    assert len(progress) == 3
    assert progress[0] < progress[1] < progress[2] == 100

    submit, pending, processing, completed, download = http.calls
    assert submit.method == "post"
    assert submit.url == "https://api.ltx.video/v2/text-to-video"
    assert submit.headers == {
        "Authorization": f"Bearer {_SECRET}",
        "Content-Type": "application/json",
    }
    assert submit.json_payload == {
        "prompt": "A fox crosses a snowy ridge",
        "model": "ltx-2-5-fast",
        "duration": 5,
        "resolution": "1920x1080",
        "fps": 24,
        "generate_audio": True,
    }
    assert [call.url for call in (pending, processing, completed)] == [
        "https://api.ltx.video/v2/text-to-video/job-1"
    ] * 3
    assert all(
        call.headers == {"Authorization": f"Bearer {_SECRET}"}
        for call in (pending, processing, completed)
    )
    assert download.url == "https://cdn.example.com/result.mp4"
    assert download.headers is None


def test_ltx_cancellation_aborts_polling_without_inventing_a_remote_cancel_call(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=202, json_payload={"id": "job-1"}))
    http.queue(
        "get",
        FakeResponse(status_code=200, json_payload={"status": "pending"}),
    )
    cancelled = False

    def on_progress(_progress: int) -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(GenerationCancelledError):
        _generate(
            _provider(http),
            tmp_path / "cancelled.mp4",
            on_progress=on_progress,
            is_cancelled=lambda: cancelled,
        )

    assert [(call.method, call.url) for call in http.calls] == [
        ("post", "https://api.ltx.video/v2/text-to-video"),
        ("get", "https://api.ltx.video/v2/text-to-video/job-1"),
    ]
    assert (tmp_path / "cancelled.mp4").exists() is False


@pytest.mark.parametrize(
    ("queue_responses", "max_wait", "expected_code", "retryable"),
    [
        (
            {
                "post": [
                    FakeResponse(
                        status_code=401,
                        json_payload={"error": {"message": "unauthorized"}},
                    )
                ]
            },
            5.0,
            "PROVIDER_AUTHENTICATION_FAILED",
            False,
        ),
        (
            {
                "post": [FakeResponse(status_code=202, json_payload={"id": "job-1"})],
                "get": [
                    FakeResponse(
                        status_code=200,
                        json_payload={
                            "status": "failed",
                            "error": {
                                "type": "provider_rejected",
                                "message": "request rejected",
                            },
                        },
                    )
                ],
            },
            5.0,
            "PROVIDER_REJECTED",
            False,
        ),
        (
            {"post": [FakeResponse(status_code=202, json_payload={"id": "job-1"})]},
            0.0,
            "PROVIDER_TIMEOUT",
            True,
        ),
        (
            {
                "post": [FakeResponse(status_code=202, json_payload={"id": "job-1"})],
                "get": [
                    FakeResponse(
                        status_code=200,
                        json_payload={"status": {"unexpected": "object"}},
                    )
                ],
            },
            5.0,
            "PROVIDER_RESPONSE_INVALID",
            False,
        ),
        (
            {"post": [HttpTransportError("connection reset")]},
            5.0,
            "PROVIDER_NETWORK_ERROR",
            True,
        ),
        (
            {
                "post": [FakeResponse(status_code=202, json_payload={"id": "job-1"})],
                "get": [
                    FakeResponse(
                        status_code=200,
                        json_payload={
                            "status": "completed",
                            "result": {
                                "video_url": "https://cdn.example.com/result.mp4"
                            },
                        },
                    ),
                    FakeResponse(status_code=503, text="cdn unavailable"),
                ],
            },
            5.0,
            "PROVIDER_DOWNLOAD_FAILED",
            True,
        ),
    ],
    ids=["auth", "rejected", "timeout", "malformed", "network", "download"],
)
def test_ltx_failures_are_normalized_without_credentials(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    queue_responses: dict[str, list[FakeResponse | Exception]],
    max_wait: float,
    expected_code: str,
    retryable: bool,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    for method, responses in queue_responses.items():
        http.queue(method, *responses)

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http, async_max_wait_s=max_wait),
            tmp_path / "failed.mp4",
        )

    error = raised.value
    assert error.code == expected_code
    assert error.provider == "ltx"
    assert error.retryable is retryable
    serialized = json.dumps(error.to_dict())
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in serialized
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


def test_ltx_empty_download_is_a_retryable_download_failure(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=202, json_payload={"id": "job-1"}))
    http.queue(
        "get",
        FakeResponse(
            status_code=200,
            json_payload={
                "status": "completed",
                "result": {"video_url": "https://cdn.example.com/result.mp4"},
            },
        ),
        FakeResponse(status_code=200, content=b""),
    )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "empty.mp4")

    assert raised.value.code == "PROVIDER_DOWNLOAD_FAILED"
    assert raised.value.retryable is True
    assert (tmp_path / "empty.mp4").exists() is False
