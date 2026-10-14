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
from services.video_providers.google_veo import GoogleVeoTextToVideoProvider
from tests.fakes.services import FakeHTTPClient, FakeResponse


_SECRET = "google-secret-never-log"
_MODEL_ID = "veo-3.1-generate-preview"
_FAST_MODEL_ID = "veo-3.1-fast-generate-preview"
_LITE_MODEL_ID = "veo-3.1-lite-generate-preview"
_OPERATION_ID = "operation-abc_123"
_OPERATION_NAME = f"models/{_MODEL_ID}/operations/{_OPERATION_ID}"
_OPERATION_URL = (
    "https://generativelanguage.googleapis.com/v1beta/" f"{_OPERATION_NAME}"
)
_VIDEO_URL = "https://generativelanguage.googleapis.com/downloads/signed/video.mp4"


def _profile(*, model_id: str = _MODEL_ID) -> ProviderProfile:
    return ProviderProfile(
        provider_id="google_veo",
        base_url="https://generativelanguage.googleapis.com/v1beta/",
        model_id=model_id,
        api_key=_SECRET,
    )


def _request(
    *,
    model_id: str = _MODEL_ID,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    duration: int | float | None = 8,
    fps: int | float = 24,
    generate_audio: bool = True,
    seed: int | None = 123,
) -> ProviderTextToVideoRequest:
    return ProviderTextToVideoRequest(
        prompt="A fox crosses a snowy ridge",
        model_id=model_id,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration,
        fps=fps,
        generate_audio=generate_audio,
        negative_prompt="compression artifacts",
        seed=seed,
    )


def _provider(
    http: FakeHTTPClient,
    *,
    async_max_wait_s: float = 5.0,
) -> GoogleVeoTextToVideoProvider:
    return GoogleVeoTextToVideoProvider(
        http,
        poll_interval_s=0.0,
        async_max_wait_s=async_max_wait_s,
    )


def _generate(
    provider: GoogleVeoTextToVideoProvider,
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


def _submit_response(*, name: object = _OPERATION_NAME) -> FakeResponse:
    return FakeResponse(status_code=200, json_payload={"name": name})


def _running_operation(*, done: bool | None) -> FakeResponse:
    payload: dict[str, object] = {"name": _OPERATION_NAME}
    if done is not None:
        payload["done"] = done
    return FakeResponse(status_code=200, json_payload=payload)


def _completed_operation(*, video_uri: object = _VIDEO_URL) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "name": _OPERATION_NAME,
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [{"video": {"uri": video_uri}}]
                }
            },
        },
    )


def _queue_immediate_success(
    http: FakeHTTPClient,
    *,
    operation_name: str = _OPERATION_NAME,
) -> None:
    http.queue("post", _submit_response(name=operation_name))
    response = _completed_operation()
    response.json_payload["name"] = operation_name
    http.queue(
        "get",
        response,
        FakeResponse(status_code=200, content=b"video"),
    )


def test_google_veo_maps_request_polls_progress_and_downloads_with_api_key(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _running_operation(done=None),
        _running_operation(done=False),
        _completed_operation(),
        FakeResponse(status_code=200, content=b"downloaded-video"),
    )
    progress: list[int] = []
    output_path = tmp_path / "queue-output" / "result.mp4"

    _generate(_provider(http), output_path, on_progress=progress.append)

    assert output_path.read_bytes() == b"downloaded-video"
    assert len(progress) == 3
    assert all(left < right for left, right in pairwise(progress))
    assert progress[-1] == 100

    submit, missing_done, not_done, completed, download = http.calls
    assert submit.method == "post"
    assert submit.url == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_MODEL_ID}:predictLongRunning"
    )
    assert submit.headers is not None
    assert submit.headers["x-goog-api-key"] == _SECRET
    assert submit.headers["Content-Type"] == "application/json"
    assert submit.json_payload == {
        "instances": [{"prompt": "A fox crosses a snowy ridge"}],
        "parameters": {
            "aspectRatio": "16:9",
            "durationSeconds": "8",
            "resolution": "1080p",
            "seed": 123,
        },
    }
    assert [call.url for call in (missing_done, not_done, completed)] == [
        _OPERATION_URL
    ] * 3
    assert all(
        call.headers is not None and call.headers["x-goog-api-key"] == _SECRET
        for call in (missing_done, not_done, completed)
    )
    assert download.url == _VIDEO_URL
    assert download.headers is not None
    assert download.headers["x-goog-api-key"] == _SECRET


@pytest.mark.parametrize(
    ("aspect_ratio", "resolution", "duration"),
    [
        ("16:9", "720p", 4),
        ("9:16", "720p", 6),
        ("16:9", "720p", 8),
        ("9:16", "4k", 8),
    ],
)
def test_google_veo_accepts_and_serializes_supported_combinations(
    tmp_path: Path,
    aspect_ratio: str,
    resolution: str,
    duration: int,
) -> None:
    http = FakeHTTPClient()
    _queue_immediate_success(http)

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            seed=None,
        ),
    )

    payload = http.calls[0].json_payload
    assert payload is not None
    parameters = payload["parameters"]
    assert isinstance(parameters, dict)
    assert parameters == {
        "aspectRatio": aspect_ratio,
        "durationSeconds": str(duration),
        "resolution": resolution,
    }


def test_google_veo_uses_an_editable_safe_model_id(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    model_id = _FAST_MODEL_ID
    operation_name = f"models/{model_id}/operations/{_OPERATION_ID}"
    _queue_immediate_success(http, operation_name=operation_name)

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(
            model_id=model_id,
            resolution="720p",
            duration=4,
        ),
        profile=_profile(model_id=model_id),
    )

    assert http.calls[0].url.endswith(f"/models/{model_id}:predictLongRunning")
    assert http.calls[1].url.endswith(f"/{operation_name}")


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        "../veo-3.1",
        "models/veo-3.1",
        "https://attacker.example/model",
        "veo 3.1",
    ],
)
def test_google_veo_rejects_unsafe_or_malformed_model_ids_before_submission(
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
    assert raised.value.provider == "google_veo"
    assert http.calls == []


@pytest.mark.parametrize(
    "operation_name",
    [
        "",
        "operations/operation-1",
        f"models/other-model/operations/{_OPERATION_ID}",
        f"models/{_MODEL_ID}/operations/../escape",
        "https://attacker.example/operation",
    ],
)
def test_google_veo_rejects_unsafe_or_mismatched_operation_names(
    tmp_path: Path,
    operation_name: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response(name=operation_name))

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "unsafe-operation.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "google_veo"
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    ("video_request", "profile"),
    [
        (_request(aspect_ratio="1:1"), _profile()),
        (_request(duration=5), _profile()),
        (_request(resolution="540p"), _profile()),
        (_request(resolution="1080p", duration=6), _profile()),
        (_request(resolution="4k", duration=4), _profile()),
        (_request(fps=30), _profile()),
        (_request(generate_audio=False), _profile()),
        (
            _request(model_id=_LITE_MODEL_ID, resolution="4k", duration=8),
            _profile(model_id=_LITE_MODEL_ID),
        ),
    ],
    ids=[
        "ratio",
        "duration",
        "resolution",
        "1080p-duration",
        "4k-duration",
        "fps",
        "audio",
        "lite-4k",
    ],
)
def test_google_veo_rejects_unsupported_options_before_submission(
    tmp_path: Path,
    video_request: ProviderTextToVideoRequest,
    profile: ProviderProfile,
) -> None:
    http = FakeHTTPClient()

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http),
            tmp_path / "unsupported.mp4",
            request=video_request,
            profile=profile,
        )

    assert raised.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"
    assert raised.value.provider == "google_veo"
    assert http.calls == []


def test_google_veo_local_cancellation_stops_without_remote_cancel_request(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue("get", _running_operation(done=False))
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
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{_MODEL_ID}:predictLongRunning",
        ),
        ("get", _OPERATION_URL),
    ]
    assert output_path.exists() is False


def test_google_veo_operation_error_is_a_redacted_provider_rejection(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        FakeResponse(
            status_code=200,
            json_payload={
                "name": _OPERATION_NAME,
                "done": True,
                "error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": f"request rejected for {_SECRET}",
                },
            },
        ),
    )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "failed.mp4")

    error = raised.value
    assert error.code == "PROVIDER_REJECTED"
    assert error.provider == "google_veo"
    assert error.retryable is False
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "case",
    [
        "operation-name",
        "done-type",
        "terminal-empty",
        "response",
        "samples-empty",
        "video",
        "uri-type",
        "uri-url",
    ],
)
def test_google_veo_malformed_operation_or_result_is_normalized(
    tmp_path: Path,
    case: str,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    response = _completed_operation()
    if case == "operation-name":
        response.json_payload["name"] = (
            f"models/{_MODEL_ID}/operations/different-operation"
        )
    elif case == "done-type":
        response.json_payload["done"] = "true"
    elif case == "terminal-empty":
        del response.json_payload["response"]
    elif case == "response":
        response.json_payload["response"] = {"unexpected": "object"}
    elif case == "samples-empty":
        response.json_payload["response"]["generateVideoResponse"][
            "generatedSamples"
        ] = []
    elif case == "video":
        response.json_payload["response"]["generateVideoResponse"][
            "generatedSamples"
        ] = [{}]
    elif case == "uri-type":
        response.json_payload["response"]["generateVideoResponse"][
            "generatedSamples"
        ][0]["video"]["uri"] = [_VIDEO_URL]
    else:
        response.json_payload["response"]["generateVideoResponse"][
            "generatedSamples"
        ][0]["video"]["uri"] = "http://cdn/output.mp4"
    http.queue("get", response)

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "malformed.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "google_veo"
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
def test_google_veo_failures_are_normalized_without_credentials(
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
                json_payload={"error": {"message": f"invalid key {_SECRET}"}},
            ),
        )
    elif case == "rejected":
        http.queue(
            "post",
            FakeResponse(
                status_code=400,
                json_payload={"error": {"message": f"invalid request {_SECRET}"}},
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
    assert error.provider == "google_veo"
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
def test_google_veo_download_failures_are_normalized_and_redacted(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    download_response: FakeResponse | Exception,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", _submit_response())
    http.queue(
        "get",
        _completed_operation(),
        download_response,
    )
    output_path = tmp_path / "download-failed.mp4"

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), output_path)

    error = raised.value
    assert error.code == "PROVIDER_DOWNLOAD_FAILED"
    assert error.provider == "google_veo"
    assert error.retryable is True
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert output_path.exists() is False
