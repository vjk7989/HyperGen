from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from _routes._errors import HTTPError
from api_types import CreateTextToVideoRequest
from handlers.queued_generation_handler import QueuedGenerationHandler
from services.features.video import ProviderDispatchTextToVideoExecutor
from services.generation_queue.registry import ExecutorRegistry
from services.generation_queue.runner import QueueRunner
from services.sqlite_store import SqliteStore
from services.video_providers import ProviderError, ProviderProfile, ProviderRegistry
from services.video_providers.persistence import ProviderProfileStore
from tests.fakes.generation import FakeGenerationExecutor, FakeTextToVideoProvider


def _request(
    prompt: str,
    *,
    provider_id: str | None = None,
    model_id: str | None = None,
    params: dict[str, object] | None = None,
) -> CreateTextToVideoRequest:
    body: dict[str, object] = {
        "params": {
            "prompt": prompt,
            "model": "ltx-2.5-fast",
            **(params or {}),
        },
    }
    if provider_id is not None:
        assert model_id is not None
        body["contract_version"] = 2
        body["provider"] = {
            "providerId": provider_id,
            "modelId": model_id,
        }
    return CreateTextToVideoRequest.model_validate(body)


def _v2_spec(
    prompt: str,
    *,
    provider_id: str = "fal",
    model_id: str = "fal-ai/selected-model",
) -> dict[str, object]:
    return {
        "params": {"prompt": prompt, "model": "ltx-2.5-fast"},
        "inputs": {},
        "provider": {"providerId": provider_id, "modelId": model_id},
    }


def _dispatcher(
    tmp_path: Path,
    *,
    local: FakeGenerationExecutor,
    provider: FakeTextToVideoProvider,
    save_profile: bool = True,
    progress: list[int] | None = None,
) -> tuple[ProviderDispatchTextToVideoExecutor, ProviderProfileStore]:
    registry = ProviderRegistry()
    registry.register(provider)
    profiles = ProviderProfileStore(tmp_path / "video-providers.json")
    if save_profile:
        profiles.save_profile(
            ProviderProfile(
                provider_id=provider.provider_id,
                base_url=(
                    "https://api.ltx.io"
                    if provider.provider_id == "ltx"
                    else "https://queue.fal.run"
                ),
                model_id="fal-ai/profile-default",
                api_key="provider-secret",
            )
        )
    executor = ProviderDispatchTextToVideoExecutor(
        local_executor=local,
        providers=registry,
        profiles=profiles,
        progress_sink=(progress if progress is not None else []).append,
    )
    return executor, profiles


def _handler(
    db: SqliteStore,
    executor: ProviderDispatchTextToVideoExecutor,
) -> QueuedGenerationHandler:
    def unused_audio_derivation(*_args: object) -> None:
        raise AssertionError("text-to-video must not derive audio params")

    return QueuedGenerationHandler(
        db,
        ExecutorRegistry({"text-to-video": executor}),
        unused_audio_derivation,
    )


def _runner(test_state, db: SqliteStore, executor) -> QueueRunner:
    return QueueRunner(
        db=db,
        generation=test_state.generation,
        executors=ExecutorRegistry({"text-to-video": executor}),
    )


@pytest.mark.parametrize(
    ("provider_id", "unsupported"),
    [
        ("fal", {"resolution": "1080p", "fps": 50}),
        ("replicate", {"fps": 50}),
        ("runway", {"fps": 50, "audio": True}),
        ("luma", {"fps": 50, "audio": True}),
        ("google_veo", {"fps": 50, "audio": False}),
    ],
)
def test_invalid_provider_controls_are_rejected_before_queue_or_network(
    test_state,
    tmp_path: Path,
    provider_id: str,
    unsupported: dict[str, object],
) -> None:
    db = SqliteStore(test_state.config.app_data_dir)
    provider = FakeTextToVideoProvider(provider_id=provider_id)
    executor, _profiles = _dispatcher(
        tmp_path, local=FakeGenerationExecutor(), provider=provider
    )
    handler = _handler(db, executor)

    with pytest.raises(HTTPError) as exc_info:
        handler.create_text_to_video(
            _request(
                "unsupported provider controls",
                provider_id=provider_id,
                model_id="test/video-model",
                params=unsupported,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"
    assert db.list_generations("text-to-video") == []
    assert provider.calls == []


@pytest.mark.parametrize("provider_id", ["ltx", "custom"])
def test_ltx_and_custom_queue_all_shared_provider_controls(
    test_state,
    tmp_path: Path,
    provider_id: str,
) -> None:
    db = SqliteStore(test_state.config.app_data_dir)
    provider = FakeTextToVideoProvider(provider_id=provider_id)
    executor, _profiles = _dispatcher(
        tmp_path, local=FakeGenerationExecutor(), provider=provider
    )

    generation = _handler(db, executor).create_text_to_video(
        _request(
            "all provider controls",
            provider_id=provider_id,
            model_id="test/video-model",
            params={
                "aspectRatio": "9:16",
                "resolution": "1080p",
                "duration": 10,
                "fps": 50,
                "audio": True,
            },
        )
    )

    assert generation.status == "queued"
    assert len(db.list_generations("text-to-video")) == 1
    assert provider.calls == []


def _wait_for_status(db: SqliteStore, generation_id: str, status: str) -> bool:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        loaded = db.get_generation(generation_id)
        if loaded is not None and loaded.status == status:
            return True
        time.sleep(0.01)
    loaded = db.get_generation(generation_id)
    return loaded is not None and loaded.status == status


def test_contract_v1_without_provider_stays_on_local_executor(
    test_state, tmp_path: Path
) -> None:
    db = SqliteStore(test_state.config.app_data_dir)
    local_prompts: list[str] = []
    local = FakeGenerationExecutor(seen_prompts=local_prompts)
    provider = FakeTextToVideoProvider()
    executor, _profiles = _dispatcher(
        tmp_path, local=local, provider=provider, save_profile=False
    )
    generation = _handler(db, executor).create_text_to_video(_request("local fox"))
    runner = _runner(test_state, db, executor)

    runner.start()
    try:
        runner.wake()
        assert _wait_for_status(db, generation.id, "succeeded")
    finally:
        runner.stop()

    assert local_prompts == ["local fox"]
    assert provider.calls == []
    assert "provider" not in generation.spec


def test_contract_v2_dispatches_selected_model_without_persisting_profile_secrets(
    test_state, tmp_path: Path
) -> None:
    db = SqliteStore(test_state.config.app_data_dir)
    progress: list[int] = []
    local_prompts: list[str] = []
    local = FakeGenerationExecutor(seen_prompts=local_prompts)
    provider = FakeTextToVideoProvider(provider_id="ltx")
    executor, _profiles = _dispatcher(
        tmp_path,
        local=local,
        provider=provider,
        progress=progress,
    )
    generation = _handler(db, executor).create_text_to_video(
        _request(
            "cloud fox",
            provider_id="ltx",
            model_id="ltx-2-5-fast",
            params={"audio": True},
        )
    )

    serialized_spec = json.dumps(generation.spec)
    assert generation.contract_version == 2
    assert generation.spec["provider"] == {
        "providerId": "ltx",
        "modelId": "ltx-2-5-fast",
    }
    assert "provider-secret" not in serialized_spec
    assert "https://api.ltx.io" not in serialized_spec

    runner = _runner(test_state, db, executor)
    runner.start()
    try:
        runner.wake()
        assert _wait_for_status(db, generation.id, "succeeded")
    finally:
        runner.stop()

    loaded = db.get_generation(generation.id)
    assert loaded is not None
    assert local_prompts == []
    assert progress == [20, 65]
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call.profile.api_key == "provider-secret"
    assert call.profile.base_url == "https://api.ltx.io"
    assert getattr(call.request, "prompt") == "cloud fox"
    assert getattr(call.request, "model_id") == "ltx-2-5-fast"
    assert getattr(call.request, "generate_audio") is True
    finalized_output = Path(loaded.outputs[0].path)
    assert call.output_path.name == finalized_output.name
    assert call.output_path.parent.name == ".in-flight"
    assert call.output_path.exists() is False
    assert finalized_output.is_file()


def test_missing_provider_profile_maps_to_capability_failed(
    test_state, tmp_path: Path
) -> None:
    db = SqliteStore(test_state.config.app_data_dir)
    provider = FakeTextToVideoProvider()
    executor, _profiles = _dispatcher(
        tmp_path,
        local=FakeGenerationExecutor(),
        provider=provider,
        save_profile=False,
    )
    generation = db.insert_generation(
        "text-to-video",
        _v2_spec("profile deleted after queueing"),
        contract_version=2,
    )
    runner = _runner(test_state, db, executor)

    runner.start()
    try:
        runner.wake()
        assert _wait_for_status(db, generation.id, "failed")
    finally:
        runner.stop()

    loaded = db.get_generation(generation.id)
    assert loaded is not None
    assert loaded.error_code == "CAPABILITY_FAILED"
    assert provider.calls == []


def test_provider_rejection_maps_to_capability_failed_and_cleans_partial_output(
    test_state, tmp_path: Path
) -> None:
    db = SqliteStore(test_state.config.app_data_dir)
    provider = FakeTextToVideoProvider(
        error=ProviderError(
            code="PROVIDER_REJECTED",
            provider="fal",
            message="provider rejected this request",
        ),
        write_partial_before_error=True,
    )
    executor, _profiles = _dispatcher(
        tmp_path,
        local=FakeGenerationExecutor(),
        provider=provider,
    )
    generation = db.insert_generation(
        "text-to-video",
        _v2_spec("provider rejects"),
        contract_version=2,
    )
    runner = _runner(test_state, db, executor)

    runner.start()
    try:
        runner.wake()
        assert _wait_for_status(db, generation.id, "failed")
    finally:
        runner.stop()

    loaded = db.get_generation(generation.id)
    assert loaded is not None
    assert loaded.error_code == "CAPABILITY_FAILED"
    assert len(provider.calls) == 1
    assert provider.calls[0].output_path.exists() is False
