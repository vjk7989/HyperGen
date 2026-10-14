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
from services.video_providers.luma import LumaTextToVideoProvider
from tests.fakes.services import FakeHTTPClient, FakeResponse


_SECRET = "luma-secret-never-log"
_MODEL_ID = "ray-2"
_GENERATION_ID = "123e4567-e89b-12d3-a456-426614174000"
_GENERATION_URL = (
    "https://api.lumalabs.ai/dream-machine/v1/generations/"
    f"{_GENERATION_ID}"
)
_VIDEO_URL = "https://storage.cdn-luma.com/dream_machine/signed/video.mp4"


def _profile(*, model_id: str = _MODEL_ID) -> ProviderProfile:
    return ProviderProfile(
        provider_id="luma",
        base_url="https://api.lumalabs.ai/dream-machine/v1/",
        model_id=model_id,
        api_key=_SECRET,
    )


def _request(
    *,
    model_id: str = _MODEL_ID,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int | float | None = 5,
) -> ProviderTextToVideoRequest:
    return ProviderTextToVideoRequest(
        prompt="A fox crosses a snowy ridge",
        model_id=model_id,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration,
        fps=24,
        generate_audio=True,
        negative_prompt="compression artifacts",
        seed=123,
    )


def _provider(
    http: FakeHTTPClient,
    *,
    async_max_wait_s: float = 5.0,
) -> LumaTextToVideoProvider:
    return LumaTextToVideoProvider(
        http,
        poll_interval_s=0.0,
        async_max_wait_s=async_max_wait_s,
    )


def _generate(
    provider: LumaTextToVideoProvider,
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


def _submit_response(*, generation_id: object = _GENERATION_ID) -> FakeResponse:
    return FakeResponse(status_code=201, json_payload={"id": generation_id})


def _generation(
    state: object,
    *,
    video_url: object | None = None,
    failure_reason: str | None = None,
) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "id": _GENERATION_ID,
            "state": state,
            "failure_reason": failure_reason,
            "assets": {"video": video_url} if video_url is not None else None,
        },
    )


def _queue_immediate_success(http: FakeHTTPClient) -> None:
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _generation("completed", video_url=_VIDEO_URL),
        FakeResponse(status_code=200, content=b"video"),
    )


def test_luma_maps_request_polls_progress_and_downloads_signed_output(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _generation("queued"),
        _generation("dreaming"),
        _generation("completed", video_url=_VIDEO_URL),
        FakeResponse(status_code=200, content=b"downloaded-video"),
    )
    progress: list[int] = []
    output_path = tmp_path / "queue-output" / "result.mp4"

    _generate(_provider(http), output_path, on_progress=progress.append)

    assert output_path.read_bytes() == b"downloaded-video"
    assert len(progress) == 3
    assert all(left < right for left, right in pairwise(progress))
    assert progress[-1] == 100

    submit, queued, dreaming, completed, download = http.calls
    assert submit.method == "post"
    assert submit.url == (
        "https://api.lumalabs.ai/dream-machine/v1/generations/video"
    )
    assert submit.headers is not None
    assert submit.headers["Authorization"] == f"Bearer {_SECRET}"
    assert submit.headers["Content-Type"] == "application/json"
    assert submit.json_payload is not None
    assert {
        key: submit.json_payload[key]
        for key in ("prompt", "model", "aspect_ratio", "resolution", "duration")
    } == {
        "prompt": "A fox crosses a snowy ridge",
        "model": "ray-2",
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "duration": "5s",
    }
    assert set(submit.json_payload) <= {
        "prompt",
        "model",
        "aspect_ratio",
        "resolution",
        "duration",
        "generation_type",
    }
    assert submit.json_payload.get("generation_type", "video") == "video"
    assert "fps" not in submit.json_payload
    assert "audio" not in submit.json_payload
    assert "generate_audio" not in submit.json_payload
    assert "negative_prompt" not in submit.json_payload
    assert "seed" not in submit.json_payload
    assert [call.url for call in (queued, dreaming, completed)] == [
        _GENERATION_URL
    ] * 3
    assert all(
        call.headers is not None
        and call.headers["Authorization"] == f"Bearer {_SECRET}"
        for call in (queued, dreaming, completed)
    )
    assert download.url == _VIDEO_URL
    assert download.headers is None


@pytest.mark.parametrize(
    "aspect_ratio",
    ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"],
)
def test_luma_accepts_documented_aspect_ratios(
    tmp_path: Path,
    aspect_ratio: str,
) -> None:
    http = FakeHTTPClient()
    _queue_immediate_success(http)

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(aspect_ratio=aspect_ratio),
    )

    payload = http.calls[0].json_payload
    assert payload is not None
    assert payload["aspect_ratio"] == aspect_ratio


@pytest.mark.parametrize(
    ("duration", "resolution"),
    [(5, "540p"), (5, "720p"), (9, "1080p"), (9, "4k")],
)
def test_luma_serializes_supported_duration_and_resolution(
    tmp_path: Path,
    duration: int,
    resolution: str,
) -> None:
    http = FakeHTTPClient()
    _queue_immediate_success(http)

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(duration=duration, resolution=resolution),
    )

    payload = http.calls[0].json_payload
    assert payload is not None
    assert payload["duration"] == f"{duration}s"
    assert payload["resolution"] == resolution


def test_luma_uses_an_editable_safe_model_id(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    _queue_immediate_success(http)
    model_id = "ray-flash-2"

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(model_id=model_id),
        profile=_profile(model_id=model_id),
    )

    payload = http.calls[0].json_payload
    assert payload is not None
    assert payload["model"] == model_id


@pytest.mark.parametrize(
    "model_id",
    ["", "../ray-2", "ray-2/other", "https://attacker.example/model", "ray 2"],
)
def test_luma_rejects_unsafe_or_malformed_model_ids_before_submission(
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
    assert raised.value.provider == "luma"
    assert http.calls == []


@pytest.mark.parametrize(
    ("aspect_ratio", "resolution", "duration"),
    [
        ("2:1", "720p", 5),
        ("16:9", "480p", 5),
        ("16:9", "720p", 6),
        ("16:9", "720p", 10),
        ("16:9", "720p", None),
    ],
)
def test_luma_rejects_unsupported_options_before_submission(
    tmp_path: Path,
    aspect_ratio: str,
    resolution: str,
    duration: int | None,
) -> None:
    http = FakeHTTPClient()

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http),
            tmp_path / "unsupported.mp4",
            request=_request(
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration=duration,
            ),
        )

    assert raised.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"
    assert raised.value.provider == "luma"
    assert http.calls == []


@pytest.mark.parametrize(
    "generation_id",
    [None, "", "not-a-uuid", "../escape"],
)
def test_luma_rejects_missing_or_invalid_generation_uuid(
    tmp_path: Path,
    generation_id: object,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response(generation_id=generation_id))

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "invalid-id.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "luma"
    assert len(http.calls) == 1


def test_luma_local_cancellation_deletes_active_generation(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue("get", _generation("queued"))
    http.queue("delete", FakeResponse(status_code=204, content=b""))
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
        (
            "post",
            "https://api.lumalabs.ai/dream-machine/v1/generations/video",
        ),
        ("get", _GENERATION_URL),
        ("delete", _GENERATION_URL),
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
def test_luma_cancel_failures_are_normalized(
    tmp_path: Path,
    cancel_response: FakeResponse | Exception,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue("get", _generation("queued"))
    http.queue("delete", cancel_response)
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
    assert raised.value.provider == "luma"
    assert raised.value.retryable is True


def test_luma_failed_generation_is_a_redacted_provider_rejection(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _generation("failed", failure_reason=f"request rejected for {_SECRET}"),
    )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "failed.mp4")

    error = raised.value
    assert error.code == "PROVIDER_REJECTED"
    assert error.provider == "luma"
    assert error.retryable is False
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "case",
    [
        "poll-id",
        "missing-state",
        "state-type",
        "unknown-state",
        "assets-type",
        "assets-missing-video",
        "output-type",
        "output-url",
    ],
)
def test_luma_malformed_poll_response_is_normalized(
    tmp_path: Path,
    case: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    response = _generation("completed", video_url=_VIDEO_URL)
    if case == "poll-id":
        response.json_payload["id"] = "not-a-uuid"
    elif case == "missing-state":
        del response.json_payload["state"]
    elif case == "state-type":
        response.json_payload["state"] = {"unexpected": "object"}
    elif case == "unknown-state":
        response.json_payload["state"] = "unknown"
    elif case == "assets-type":
        response.json_payload["assets"] = "not-an-object"
    elif case == "assets-missing-video":
        response.json_payload["assets"] = {}
    elif case == "output-type":
        response.json_payload["assets"] = {"video": [_VIDEO_URL]}
    else:
        response.json_payload["assets"] = {"video": "http://cdn/output.mp4"}
    http.queue("get", response)

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "malformed.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "luma"
    assert raised.value.retryable is False
    assert (tmp_path / "malformed.mp4").exists() is False


@pytest.mark.parametrize(
    ("case", "expected_code", "retryable"),
    [
        ("auth", "PROVIDER_AUTHENTICATION_FAILED", False),
        ("rejected", "PROVIDER_REJECTED", False),
        ("network", "PROVIDER_NETWORK_ERROR", True),
        ("timeout", "PROVIDER_TIMEOUT", True),
    ],
)
def test_luma_failures_are_normalized_without_credentials(
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
    elif case == "rejected":
        http.queue(
            "post",
            FakeResponse(
                status_code=422,
                json_payload={"detail": f"invalid request {_SECRET}"},
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
    assert error.provider == "luma"
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
def test_luma_download_failures_are_normalized_and_redacted(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    download_response: FakeResponse | Exception,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _generation("completed", video_url=_VIDEO_URL),
        download_response,
    )
    output_path = tmp_path / "download-failed.mp4"

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), output_path)

    error = raised.value
    assert error.code == "PROVIDER_DOWNLOAD_FAILED"
    assert error.provider == "luma"
    assert error.retryable is True
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert output_path.exists() is False
