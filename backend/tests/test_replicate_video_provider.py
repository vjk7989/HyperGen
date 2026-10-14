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
from services.video_providers.replicate import ReplicateTextToVideoProvider
from tests.fakes.services import FakeHTTPClient, FakeResponse


_SECRET = "replicate-secret-never-log"
_MODEL_ID = "minimax/video-01"
_VERSION = "a" * 64
_POLL_URL = "https://api.replicate.com/v1/prediction-tickets/prediction-1"
_CANCEL_URL = (
    "https://api.replicate.com/v1/prediction-tickets/prediction-1/cancel"
)
_VIDEO_URL = "https://replicate.delivery/pbxt/result.mp4"


def _profile(*, model_id: str = _MODEL_ID) -> ProviderProfile:
    return ProviderProfile(
        provider_id="replicate",
        base_url="https://api.replicate.com/v1/",
        model_id=model_id,
        api_key=_SECRET,
    )


def _request(
    *,
    model_id: str = _MODEL_ID,
    seed: int | None = 123,
) -> ProviderTextToVideoRequest:
    return ProviderTextToVideoRequest(
        prompt="A fox crosses a snowy ridge",
        model_id=model_id,
        aspect_ratio="16:9",
        resolution="1080p",
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
) -> ReplicateTextToVideoProvider:
    return ReplicateTextToVideoProvider(
        http,
        poll_interval_s=0.0,
        async_max_wait_s=async_max_wait_s,
    )


def _generate(
    provider: ReplicateTextToVideoProvider,
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


def _prediction(
    status: str,
    *,
    output: object | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> FakeResponse:
    return FakeResponse(
        status_code=status_code,
        json_payload={
            "id": "prediction-1",
            "status": status,
            "output": output,
            "error": error,
            "urls": {
                "get": _POLL_URL,
                "cancel": _CANCEL_URL,
            },
        },
    )


def test_replicate_maps_request_polls_progress_and_downloads_with_auth(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue("post", _prediction("starting", status_code=201))
    http.queue(
        "get",
        _prediction("processing"),
        _prediction("succeeded", output=_VIDEO_URL),
        FakeResponse(status_code=200, content=b"downloaded-video"),
    )
    progress: list[int] = []
    output_path = tmp_path / "queue-output" / "result.mp4"

    _generate(_provider(http), output_path, on_progress=progress.append)

    assert output_path.read_bytes() == b"downloaded-video"
    assert len(progress) == 3
    assert all(left < right for left, right in pairwise(progress))
    assert progress[-1] == 100

    submit, processing, succeeded, download = http.calls
    assert submit.method == "post"
    assert submit.url == "https://api.replicate.com/v1/predictions"
    assert submit.headers == {
        "Authorization": f"Bearer {_SECRET}",
        "Content-Type": "application/json",
    }
    assert submit.json_payload == {
        "version": _MODEL_ID,
        "input": {
            "prompt": "A fox crosses a snowy ridge",
            "duration": 5,
            "resolution": "1080p",
            "aspect_ratio": "16:9",
            "generate_audio": True,
            "seed": 123,
        },
    }
    assert submit.json_payload is not None
    submitted_input = submit.json_payload["input"]
    assert isinstance(submitted_input, dict)
    assert "fps" not in submitted_input
    assert "negative_prompt" not in submitted_input
    assert [call.url for call in (processing, succeeded)] == [_POLL_URL] * 2
    assert all(
        call.headers is not None
        and call.headers["Authorization"] == f"Bearer {_SECRET}"
        for call in (processing, succeeded)
    )
    assert download.url == _VIDEO_URL
    assert download.headers is not None
    assert download.headers["Authorization"] == f"Bearer {_SECRET}"


@pytest.mark.parametrize(
    "model_id",
    [
        f"owner/model:{_VERSION}",
        _VERSION,
    ],
    ids=["owner-name-version", "bare-version"],
)
def test_replicate_accepts_documented_version_identifiers(
    tmp_path: Path,
    model_id: str,
) -> None:
    http = FakeHTTPClient()
    http.queue(
        "post",
        _prediction("succeeded", output=_VIDEO_URL, status_code=201),
    )
    http.queue("get", FakeResponse(status_code=200, content=b"video"))

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(model_id=model_id),
        profile=_profile(model_id=model_id),
    )

    payload = http.calls[0].json_payload
    assert payload is not None
    assert payload["version"] == model_id


def test_replicate_omits_null_seed(tmp_path: Path) -> None:
    http = FakeHTTPClient()
    http.queue(
        "post",
        _prediction("succeeded", output=_VIDEO_URL, status_code=201),
    )
    http.queue("get", FakeResponse(status_code=200, content=b"video"))

    _generate(
        _provider(http),
        tmp_path / "result.mp4",
        request=_request(seed=None),
    )

    payload = http.calls[0].json_payload
    assert payload is not None
    submitted_input = payload["input"]
    assert isinstance(submitted_input, dict)
    assert "seed" not in submitted_input


@pytest.mark.parametrize(
    "model_id",
    [
        "owner-only",
        "owner/model:short-version",
        "owner//model",
        "../owner/model",
        "https://attacker.example/owner/model",
        "b" * 63,
    ],
)
def test_replicate_rejects_unsafe_or_malformed_model_identifiers(
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
    assert raised.value.provider == "replicate"
    assert http.calls == []


def test_replicate_local_cancellation_posts_to_returned_cancel_url(
    tmp_path: Path,
) -> None:
    http = FakeHTTPClient()
    http.queue(
        "post",
        _prediction("starting", status_code=201),
        _prediction("canceled"),
    )
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
        ("post", "https://api.replicate.com/v1/predictions"),
        ("post", _CANCEL_URL),
    ]
    cancel = http.calls[-1]
    assert cancel.headers is not None
    assert cancel.headers["Authorization"] == f"Bearer {_SECRET}"
    assert cancel.json_payload is None
    assert cancel.data is None
    assert output_path.exists() is False


@pytest.mark.parametrize("status", ["failed", "canceled", "aborted"])
def test_replicate_unsuccessful_terminal_statuses_are_provider_rejections(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    status: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    http = FakeHTTPClient()
    http.queue("post", _prediction("starting", status_code=201))
    http.queue(
        "get",
        _prediction(status, error=f"provider error containing {_SECRET}"),
    )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "failed.mp4")

    error = raised.value
    assert error.code == "PROVIDER_REJECTED"
    assert error.provider == "replicate"
    assert error.retryable is False
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "case",
    [
        "initial-status",
        "initial-get-url",
        "initial-cancel-url",
        "poll-status",
        "poll-get-url",
        "poll-cancel-url",
        "output-type",
        "output-url",
    ],
)
def test_replicate_malformed_prediction_envelopes_are_normalized(
    tmp_path: Path,
    case: str,
) -> None:
    http = FakeHTTPClient()
    initial = _prediction("starting", status_code=201)
    if case == "initial-status":
        del initial.json_payload["status"]
    elif case == "initial-get-url":
        initial.json_payload["urls"]["get"] = "http://api.replicate.com/prediction"
    elif case == "initial-cancel-url":
        initial.json_payload["urls"]["cancel"] = "not-an-https-url"

    if case.startswith("initial-"):
        http.queue("post", initial)
    elif case.startswith("poll-"):
        http.queue("post", initial)
        poll = _prediction("processing")
        if case == "poll-status":
            del poll.json_payload["status"]
        elif case == "poll-get-url":
            poll.json_payload["urls"]["get"] = "not-an-https-url"
        else:
            poll.json_payload["urls"]["cancel"] = "http://localhost/cancel"
        http.queue("get", poll)
    else:
        output: object = (
            [_VIDEO_URL] if case == "output-type" else "http://cdn/output.mp4"
        )
        http.queue(
            "post",
            _prediction("succeeded", output=output, status_code=201),
        )

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), tmp_path / "malformed.mp4")

    assert raised.value.code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.provider == "replicate"
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
def test_replicate_failures_are_normalized_without_credentials(
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
                json_payload={"detail": f"invalid token {_SECRET}"},
            ),
        )
    elif case == "rejected":
        http.queue(
            "post",
            FakeResponse(
                status_code=422,
                json_payload={"detail": f"invalid input {_SECRET}"},
            ),
        )
    elif case == "network":
        http.queue("post", HttpTransportError(f"connection reset: {_SECRET}"))
    else:
        http.queue("post", _prediction("starting", status_code=201))
        max_wait = 0.0

    with pytest.raises(ProviderError) as raised:
        _generate(
            _provider(http, async_max_wait_s=max_wait),
            tmp_path / "failed.mp4",
        )

    error = raised.value
    assert error.code == expected_code
    assert error.provider == "replicate"
    assert error.retryable is retryable
    assert _SECRET not in str(error)
    assert _SECRET not in repr(error)
    assert _SECRET not in json.dumps(error.to_dict())
    assert _SECRET not in caplog.text
    assert (tmp_path / "failed.mp4").exists() is False


@pytest.mark.parametrize(
    "download_response",
    [
        FakeResponse(status_code=503, text="download unavailable"),
        FakeResponse(status_code=200, content=b""),
        HttpTransportError("download connection reset"),
    ],
    ids=["http-failure", "empty-output", "network-failure"],
)
def test_replicate_download_failures_are_normalized_and_not_persisted(
    tmp_path: Path,
    download_response: FakeResponse | Exception,
) -> None:
    http = FakeHTTPClient()
    http.queue(
        "post",
        _prediction("succeeded", output=_VIDEO_URL, status_code=201),
    )
    http.queue("get", download_response)
    output_path = tmp_path / "download-failed.mp4"

    with pytest.raises(ProviderError) as raised:
        _generate(_provider(http), output_path)

    assert raised.value.code == "PROVIDER_DOWNLOAD_FAILED"
    assert raised.value.provider == "replicate"
    assert raised.value.retryable is True
    assert output_path.exists() is False
