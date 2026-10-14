from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import pytest

from handlers.video_provider_handler import (
    ProviderProfileUpdate,
    VideoProviderHandler,
)
from services.video_providers import (
    PROVIDER_DESCRIPTORS,
    PROVIDER_IDS,
    ProviderError,
    ProviderProfile,
    ProviderRegistry,
)
from services.video_providers.persistence import ProviderProfileStore


EXPECTED_PROVIDER_IDS = (
    "local",
    "ltx",
    "fal",
    "replicate",
    "runway",
    "luma",
    "google_veo",
    "custom",
)


@dataclass(frozen=True)
class FakeProvider:
    provider_id: str


def test_provider_ids_and_descriptor_order_are_stable() -> None:
    assert tuple(PROVIDER_IDS) == EXPECTED_PROVIDER_IDS
    assert tuple(PROVIDER_DESCRIPTORS) == EXPECTED_PROVIDER_IDS
    assert tuple(
        descriptor.provider_id for descriptor in PROVIDER_DESCRIPTORS.values()
    ) == EXPECTED_PROVIDER_IDS


def test_curated_descriptors_are_public_complete_and_model_ids_remain_editable() -> None:
    cloud_ids = {"ltx", "fal", "replicate", "runway", "luma", "google_veo"}

    for provider_id in EXPECTED_PROVIDER_IDS:
        descriptor = PROVIDER_DESCRIPTORS[provider_id]
        public = descriptor.model_dump(by_alias=True)

        assert descriptor.display_name.strip()
        assert descriptor.documentation_url
        assert descriptor.capabilities.text_to_video is True
        assert public["providerId"] == provider_id
        assert public["displayName"] == descriptor.display_name
        assert public["capabilities"]["textToVideo"] is True
        assert "apiKey" not in public
        assert "hasApiKey" not in public
        assert "credential" not in json.dumps(public).lower()
        assert len(descriptor.suggested_model_ids) == len(
            set(descriptor.suggested_model_ids)
        )
        assert all(
            model_id and model_id == model_id.strip()
            for model_id in descriptor.suggested_model_ids
        )

        if provider_id in cloud_ids:
            assert descriptor.default_base_url is not None
            assert descriptor.default_base_url.startswith("https://")
            assert descriptor.signup_url is not None
            assert descriptor.signup_url.startswith("https://")
            assert descriptor.documentation_url.startswith("https://")
            assert descriptor.suggested_model_ids

    local = PROVIDER_DESCRIPTORS["local"]
    assert local.default_base_url is None
    assert local.signup_url is None
    assert local.suggested_model_ids

    custom = PROVIDER_DESCRIPTORS["custom"]
    assert custom.default_base_url is None
    assert custom.signup_url is None
    assert tuple(custom.suggested_model_ids) == ()

    arbitrary_model = ProviderProfile(
        provider_id="fal",
        base_url="https://queue.fal.run",
        model_id="team/private-video-model",
    )
    assert arbitrary_model.model_id == "team/private-video-model"


def test_provider_profile_trims_values_and_redacts_credentials() -> None:
    secret = "provider-secret-that-must-not-leak"
    profile = ProviderProfile.model_validate(
        {
            "providerId": "fal",
            "baseUrl": "  https://queue.fal.run/  ",
            "modelId": "  fal-ai/kling-video  ",
            "apiKey": f"  {secret}  ",
        }
    )

    assert profile.base_url == "https://queue.fal.run/"
    assert profile.model_id == "fal-ai/kling-video"
    assert profile.api_key == secret

    public = profile.to_public()
    payload = public.model_dump(by_alias=True)
    assert payload["providerId"] == "fal"
    assert payload["baseUrl"] == "https://queue.fal.run/"
    assert payload["modelId"] == "fal-ai/kling-video"
    assert payload["hasApiKey"] is True
    assert "apiKey" not in payload
    assert secret not in json.dumps(payload)
    assert secret not in repr(public)

    blank = ProviderProfile(
        provider_id="custom",
        base_url="  ",
        model_id="\t",
        api_key=" \r\n ",
    )
    assert blank.base_url is None
    assert blank.model_id is None
    assert blank.api_key is None
    assert blank.to_public().has_api_key is False


def test_registry_resolves_fakes_and_rejects_unknown_or_duplicate_ids() -> None:
    registry = ProviderRegistry()
    provider = FakeProvider("fal")
    registry.register(cast(Any, provider))

    assert registry.resolve("fal") is provider

    with pytest.raises(ProviderError) as unknown:
        registry.resolve("runway")
    assert unknown.value.to_dict() == {
        "code": "PROVIDER_NOT_FOUND",
        "provider": "runway",
        "message": "Unknown video provider: runway",
        "retryable": False,
    }

    with pytest.raises(ProviderError) as duplicate:
        registry.register(cast(Any, FakeProvider("fal")))
    assert duplicate.value.to_dict() == {
        "code": "PROVIDER_ALREADY_REGISTERED",
        "provider": "fal",
        "message": "Video provider already registered: fal",
        "retryable": False,
    }


def test_provider_error_has_a_stable_credential_free_public_shape() -> None:
    secret = "provider-secret-that-must-not-leak"
    error = ProviderError(
        code="PROVIDER_AUTHENTICATION_FAILED",
        provider="fal",
        message="Provider authentication failed",
        retryable=False,
    )
    error.__cause__ = RuntimeError(f"upstream api_key={secret}")

    assert error.code == "PROVIDER_AUTHENTICATION_FAILED"
    assert error.provider == "fal"
    assert error.message == "Provider authentication failed"
    assert error.retryable is False
    assert str(error) == error.message
    assert error.to_dict() == {
        "code": "PROVIDER_AUTHENTICATION_FAILED",
        "provider": "fal",
        "message": "Provider authentication failed",
        "retryable": False,
    }
    assert secret not in repr(error)
    assert secret not in json.dumps(error.to_dict())


def test_validation_uses_an_unsaved_candidate_without_persisting_it(
    tmp_path,
) -> None:
    store = ProviderProfileStore(tmp_path / "video-providers.json")
    handler = VideoProviderHandler(store)
    candidate = ProviderProfileUpdate(
        base_url="http://localhost:9080/v1",
        model_id="self-hosted/video-v2",
    )

    response = handler.validate("custom", candidate)

    assert response.model_dump(by_alias=True) == {
        "providerId": "custom",
        "valid": True,
        "validationMode": "configuration",
    }
    assert store.get_profile("custom") is None
    assert not (tmp_path / "video-providers.json").exists()


def test_cloud_candidate_api_key_satisfies_validation_without_being_saved(
    tmp_path,
) -> None:
    store = ProviderProfileStore(tmp_path / "video-providers.json")
    handler = VideoProviderHandler(store)

    response = handler.validate(
        "fal",
        ProviderProfileUpdate(api_key="  unsaved-fal-key  "),
    )

    assert response.valid is True
    assert response.provider_id == "fal"
    assert store.get_profile("fal") is None
    assert not (tmp_path / "video-providers.json").exists()


def test_unsafe_custom_candidate_leaves_the_saved_profile_untouched(
    tmp_path,
) -> None:
    store = ProviderProfileStore(tmp_path / "video-providers.json")
    handler = VideoProviderHandler(store)
    handler.update_profile(
        "custom",
        ProviderProfileUpdate(
            base_url="http://127.0.0.1:8090/v1",
            model_id="working/video",
            api_key="saved-secret",
        ),
    )
    saved = store.get_profile("custom")

    with pytest.raises(ProviderError) as invalid:
        handler.validate(
            "custom",
            ProviderProfileUpdate(
                base_url="http://video.example.com/v1",
                model_id="unsafe/video",
                api_key="candidate-secret",
            ),
        )

    assert invalid.value.code == "PROVIDER_URL_UNSAFE"
    assert store.get_profile("custom") == saved
    assert store.get_profile("custom") == ProviderProfile(
        provider_id="custom",
        base_url="http://127.0.0.1:8090/v1",
        model_id="working/video",
        api_key="saved-secret",
    )
