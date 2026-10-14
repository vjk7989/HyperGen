from __future__ import annotations

import inspect
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
from services.video_providers.runway import RunwayTextToVideoProvider
from tests.fakes.services import FakeHTTPClient, FakeResponse


_SECRET = "runway-secret-never-log"
_MODEL_ID = "gen4.5"
_TASK_ID = "task_abc-123"
_TASK_URL = f"https://api.dev.runwayml.com/v1/tasks/{_TASK_ID}"
_VIDEO_URL = "https://dnznrvs05pmza.cloudfront.net/signed/result.mp4"


def _profile(*, model_id: str = _MODEL_ID) -> ProviderProfile:
    return ProviderProfile(
        provider_id="runway",
        base_url="https://api.dev.runwayml.com/v1/",
        model_id=model_id,
        api_key=_SECRET,
    )


def _request(
    *,
    model_id: str = _MODEL_ID,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    seed: int | None = 123,
) -> ProviderTextToVideoRequest:
    return ProviderTextToVideoRequest(
        prompt="A fox crosses a snowy ridge",
        model_id=model_id,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=5,
        fps=24,
        generate_audio=True,
        negative_prompt="compression artifacts",
        seed=seed,
    )


def _provider(
    http: FakeHTTPClient,
    *,
    async_max_wait_s: float = 5.0,
) -> RunwayTextToVideoProvider:
    return RunwayTextToVideoProvider(
        http,
        poll_interval_s=0.0,
        async_max_wait_s=async_max_wait_s,
    )


def _generate(
    provider: RunwayTextToVideoProvider,
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


def _task(
    status: str,
    *,
    progress: object | None = None,
    output: object | None = None,
    error: str | None = None,
) -> FakeResponse:
    payload: dict[str, object | None] = {
        "status": status,
        "output": output,
        "error": error,
    }
    if progress is not None:
        payload["progress"] = progress
    return FakeResponse(status_code=200, json_payload=payload)


def test_runway_maps_gen45_request_polls_progress_and_downloads_signed_output(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
    http.queue(
        "get",
        _task("PENDING"),
        _task("THROTTLED"),
        _task("RUNNING", progress=0.65),
        _task("SUCCEEDED", output=[_VIDEO_URL, "https://ignored.example/video.mp4"]),
        FakeResponse(status_code=200, content=b"downloaded-video"),
    )
    progress: list[int] = []
    output_path = tmp_path / "queue-output" / "result.mp4"

    _generate(_provider(http), output_path, on_progress=progress.append)

    assert output_path.read_bytes() == b"downloaded-video"
    assert len(progress) == 4
    assert all(left < right for left, right in pairwise(progress))
    assert progress[-1] == 100

    submit, pending, throttled, running, succeeded, download = http.calls
    assert submit.method == "post"
    assert submit.url == "https://api.dev.runwayml.com/v1/text_to_video"
    assert submit.headers == {
        "Authorization": f"Bearer {_SECRET}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }
    assert submit.json_payload == {
        "model": "gen4.5",
        "promptText": "A fox crosses a snowy ridge",
        "duration": 5,
        "ratio": "1280:720",
        "seed": 123,
    }
    assert submit.json_payload is not None
    assert "generate_audio" not in submit.json_payload
    assert "fps" not in submit.json_payload
    assert "negativePrompt" not in submit.json_payload
    assert "resolution" not in submit.json_payload
    assert [call.url for call in (pending, throttled, running, succeeded)] == [
        _TASK_URL
    ] * 4
    assert all(
        call.headers
        == {
            "Authorization": f"Bearer {_SECRET}",
            "X-Runway-Version": "2024-11-06",
        }
        for call in (pending, throttled, running, succeeded)
    )
    assert download.url == _VIDEO_URL
    assert download.headers is None


def test_runway_production_polling_default_is_five_seconds() -> None:
    parameter = inspect.signature(RunwayTextToVideoProvider.__init__).parameters[
        "poll_interval_s"
    ]

    assert parameter.default == 5.0


def test_runway_maps_vertical_ratio_and_omits_null_seed(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
    http.queue(
        "get",
        _task("SUCCEEDED", output=[_VIDEO_URL]),
        FakeResponse(status_code=200, content=b"video"),
    )

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(aspect_ratio="9:16", seed=None),
    )

    payload = http.calls[0].json_payload
    assert payload is not None
    assert payload["ratio"] == "720:1280"
    assert "seed" not in payload


@pytest.mark.parametrize(
    "model_id",
    ["", "../gen4.5", "gen4.5/other", "https://attacker.example/model", "gen 4.5"],
)
def test_runway_rejects_unsafe_or_malformed_model_ids_before_submission(
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
    assert raised.value.provider == "runway"
    assert http.calls == []


@pytest.mark.parametrize(
    ("aspect_ratio", "resolution"),
    [
        ("1:1", "720p"),
        ("16:9", "1080p"),
        ("9:16", "4k"),
    ],
)
def test_runway_rejects_unsupported_ratio_or_resolution_before_submission(
    tmp_path: Path,
    aspect_ratio: str,
    resolution: str,
) -> None:
    http = FakeHTTPClient()

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http),
            tmp_path / "unsupported.mp4",
            request=_request(aspect_ratio=aspect_ratio, resolution=resolution),
        )

    assert raised.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"
    assert raised.value.provider == "runway"
    assert http.calls == []


@pytest.mark.parametrize(
    "task_id",
    ["", "../escape", "task/escape", "https://attacker.example/task", "task id"],
)
def test_runway_rejects_unsafe_or_malformed_task_ids(
    tmp_path: Path,
    task_id: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": task_id}))

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "unsafe-task.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "runway"
    assert len(http.calls) == 1


def test_runway_local_cancellation_deletes_active_task(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
    http.queue("get", _task("PENDING"))
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
        ("post", "https://api.dev.runwayml.com/v1/text_to_video"),
        ("get", _TASK_URL),
        ("delete", _TASK_URL),
    ]
    cancel = http.calls[-1]
    assert cancel.headers == {
        "Authorization": f"Bearer {_SECRET}",
        "X-Runway-Version": "2024-11-06",
    }
    assert output_path.exists() is False


@pytest.mark.parametrize(
    ("cancel_response", "expected_code"),
    [
        (
            FakeResponse(status_code=500, text="cancel failed"),
            "PROVIDER_CANCELLATION_FAILED",
        ),
        (HttpTransportError("cancel reset"), "PROVIDER_CANCELLATION_FAILED"),
    ],
    ids=["http-failure", "network-failure"],
)
def test_runway_cancel_failures_are_normalized(
    tmp_path: Path,
    cancel_response: FakeResponse | Exception,
    expected_code: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
    http.queue("get", _task("PENDING"))
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

    assert raised.value.code == expected_code
    assert raised.value.provider == "runway"
    assert raised.value.retryable is True


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_runway_unsuccessful_terminal_states_are_provider_rejections(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    status: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
    http.queue("get", _task(status, error=f"provider error containing {_SECRET}"))

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "failed.mp4")

    error = raised.value
    assert error.code == "PROVIDER_REJECTED"
    assert error.provider == "runway"
    assert error.retryable is False
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "case",
    [
        "missing-status",
        "unknown-status",
        "running-progress-type",
        "running-progress-range",
        "output-type",
        "output-empty",
        "output-url",
    ],
)
def test_runway_malformed_status_or_output_is_normalized(
    tmp_path: Path,
    case: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
    if case == "missing-status":
        http.queue("get", FakeResponse(status_code=200, json_payload={}))
    elif case == "unknown-status":
        http.queue("get", _task("UNKNOWN"))
    elif case == "running-progress-type":
        http.queue("get", _task("RUNNING", progress="0.5"))
    elif case == "running-progress-range":
        http.queue("get", _task("RUNNING", progress=1.5))
    elif case == "output-type":
        http.queue("get", _task("SUCCEEDED", output=_VIDEO_URL))
    elif case == "output-empty":
        http.queue("get", _task("SUCCEEDED", output=[]))
    else:
        http.queue("get", _task("SUCCEEDED", output=["http://cdn/output.mp4"]))

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "malformed.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "runway"
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
def test_runway_failures_are_normalized_without_credentials(
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
        http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
        max_wait = 0.0

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http, async_max_wait_s=max_wait),
            tmp_path / "failed.mp4",
        )

    error = raised.value
    assert error.code == expected_code
    assert error.provider == "runway"
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
def test_runway_download_failures_are_normalized_and_redacted(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    download_response: FakeResponse | Exception,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", FakeResponse(status_code=200, json_payload={"id": _TASK_ID}))
    http.queue(
        "get",
        _task("SUCCEEDED", output=[_VIDEO_URL]),
        download_response,
    )
    output_path = tmp_path / "download-failed.mp4"

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), output_path)

    error = raised.value
    assert error.code == "PROVIDER_DOWNLOAD_FAILED"
    assert error.provider == "runway"
    assert error.retryable is True
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert output_path.exists() is False
