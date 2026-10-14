from __future__ import annotations

from pathlib import Path

import pytest

import services.video_providers.persistence as persistence
from services.video_providers import ProviderProfile


def _profile(provider_id: str, *, model_id: str, api_key: str) -> ProviderProfile:
    return ProviderProfile(
        provider_id=provider_id,
        base_url=f"https://{provider_id}.example.test/v1",
        model_id=model_id,
        api_key=api_key,
    )


def test_profiles_and_active_provider_round_trip_in_a_separate_store(
    tmp_path: Path,
) -> None:
    path = tmp_path / "video-providers.json"
    store = persistence.ProviderProfileStore(path)
    fal = _profile("fal", model_id="fal/model", api_key="fal-secret")
    runway = _profile("runway", model_id="runway/model", api_key="runway-secret")

    store.save_profile(fal)
    store.save_profile(runway)
    store.set_active_provider("runway")

    reloaded = persistence.ProviderProfileStore(path)
    assert reloaded.get_profile("fal") == fal
    assert reloaded.get_profile("runway") == runway
    assert tuple(profile.provider_id for profile in reloaded.list_profiles()) == (
        "fal",
        "runway",
    )
    assert reloaded.active_provider == "runway"


def test_failed_atomic_replace_preserves_last_known_good_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "video-providers.json"
    store = persistence.ProviderProfileStore(path)
    original = _profile("fal", model_id="fal/original", api_key="original-secret")
    store.save_profile(original)
    original_bytes = path.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(persistence.os, "replace", fail_replace)
    updated = _profile("fal", model_id="fal/updated", api_key="updated-secret")

    with pytest.raises(OSError, match="simulated atomic replace failure"):
        store.save_profile(updated)

    assert path.read_bytes() == original_bytes
    assert persistence.ProviderProfileStore(path).get_profile("fal") == original
    assert store.get_profile("fal") == original
