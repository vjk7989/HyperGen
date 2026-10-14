from __future__ import annotations

import json
from typing import Any, cast

import pytest

from services.video_providers import PROVIDER_DESCRIPTORS, PROVIDER_IDS


CLOUD_PROVIDER_IDS = ("ltx", "fal", "replicate", "runway", "luma", "google_veo")


def _profiles_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_profiles = payload["profiles"]
    assert isinstance(raw_profiles, list)
    profiles = cast(list[dict[str, Any]], raw_profiles)
    return {profile["providerId"]: profile for profile in profiles}


def _assert_provider_error(response, *, status: int, code: str, provider: str) -> None:
    assert response.status_code == status
    assert response.json() == {
        "code": code,
        "provider": provider,
        "message": response.json()["message"],
        "retryable": False,
    }
    assert response.json()["message"]


def test_get_returns_descriptors_redacted_profiles_and_active_provider(
    client, test_state
) -> None:
    secret = "fal-secret-never-returned"
    saved = client.put(
        "/api/video-providers/fal",
        json={
            "baseUrl": "https://queue.fal.run",
            "modelId": "fal-ai/kling-video",
            "apiKey": secret,
        },
    )
    assert saved.status_code == 200
    assert secret not in saved.text

    response = client.get("/api/video-providers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["activeProvider"] == "local"
    assert tuple(provider["providerId"] for provider in payload["providers"]) == tuple(
        PROVIDER_IDS
    )

    profile = _profiles_by_id(payload)["fal"]
    assert profile == {
        "providerId": "fal",
        "baseUrl": "https://queue.fal.run",
        "modelId": "fal-ai/kling-video",
        "hasApiKey": True,
    }
    assert secret not in response.text
    assert "apiKey" not in profile

    general_settings = client.get("/api/settings")
    assert general_settings.status_code == 200
    assert secret not in general_settings.text
    settings_file = test_state.config.settings_file
    if settings_file.exists():
        assert secret not in settings_file.read_text(encoding="utf-8")

    provider_files = [
        path
        for path in test_state.config.app_data_dir.glob("*.json")
        if path != settings_file and secret in path.read_text(encoding="utf-8")
    ]
    assert len(provider_files) == 1


def test_put_trims_profile_and_omitted_key_preserves_existing_secret(client) -> None:
    secret = "keep-this-secret"
    created = client.put(
        "/api/video-providers/fal",
        json={
            "baseUrl": "  https://queue.fal.run/v1/  ",
            "modelId": "  fal-ai/first-model  ",
            "apiKey": f"  {secret}  ",
        },
    )
    assert created.status_code == 200
    assert created.json() == {
        "providerId": "fal",
        "baseUrl": "https://queue.fal.run/v1/",
        "modelId": "fal-ai/first-model",
        "hasApiKey": True,
    }
    assert secret not in created.text

    updated = client.put(
        "/api/video-providers/fal",
        json={
            "baseUrl": " https://queue.fal.run/v2 ",
            "modelId": " fal-ai/second-model ",
        },
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "providerId": "fal",
        "baseUrl": "https://queue.fal.run/v2",
        "modelId": "fal-ai/second-model",
        "hasApiKey": True,
    }
    assert secret not in updated.text


def test_ltx_provider_key_updates_legacy_settings_and_omission_preserves_it(
    client,
    test_state,
) -> None:
    secret = "shared-ltx-secret"
    test_state.state.app_settings.ltx_api_key = "old-legacy-key"

    saved = client.put(
        "/api/video-providers/ltx",
        json={"apiKey": f"  {secret}  "},
    )

    assert saved.status_code == 200
    assert saved.json()["hasApiKey"] is True
    assert secret not in saved.text
    assert "apiKey" not in saved.json()
    assert test_state.state.app_settings.ltx_api_key == secret

    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert settings.json()["hasLtxApiKey"] is True
    assert secret not in settings.text
    assert "ltxApiKey" not in settings.json()

    updated = client.put(
        "/api/video-providers/ltx",
        json={
            "baseUrl": "https://api.ltx.video/v2",
            "modelId": "ltx-video-v2",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["hasApiKey"] is True
    assert secret not in updated.text
    assert test_state.state.app_settings.ltx_api_key == secret
    refreshed_settings = client.get("/api/settings")
    assert refreshed_settings.json()["hasLtxApiKey"] is True
    assert secret not in refreshed_settings.text


@pytest.mark.parametrize("cleared_key", ["", " \t ", None])
def test_put_blank_or_null_key_clears_existing_credential(client, cleared_key) -> None:
    created = client.put(
        "/api/video-providers/fal",
        json={"apiKey": "temporary-secret"},
    )
    assert created.status_code == 200

    cleared = client.put(
        "/api/video-providers/fal",
        json={"apiKey": cleared_key},
    )
    assert cleared.status_code == 200
    assert cleared.json()["hasApiKey"] is False
    assert "temporary-secret" not in cleared.text
    assert (
        _profiles_by_id(client.get("/api/video-providers").json())["fal"]["hasApiKey"]
        is False
    )


@pytest.mark.parametrize("provider_id", CLOUD_PROVIDER_IDS)
def test_put_curated_provider_uses_its_endpoint_and_first_model_defaults(
    client, provider_id: str
) -> None:
    descriptor = PROVIDER_DESCRIPTORS[provider_id]
    response = client.put(
        f"/api/video-providers/{provider_id}",
        json={"apiKey": f"{provider_id}-key"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "providerId": provider_id,
        "baseUrl": descriptor.default_base_url,
        "modelId": descriptor.suggested_model_ids[0],
        "hasApiKey": True,
    }


def test_active_provider_can_be_selected_and_is_returned_by_get(client) -> None:
    assert (
        client.put("/api/video-providers/fal", json={"apiKey": "fal-key"}).status_code
        == 200
    )

    response = client.put("/api/video-providers/active", json={"providerId": "fal"})
    assert response.status_code == 200
    assert response.json() == {"activeProvider": "fal"}
    assert client.get("/api/video-providers").json()["activeProvider"] == "fal"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/api/video-providers/not-real", {}),
        ("put", "/api/video-providers/active", {"providerId": "not-real"}),
        ("post", "/api/video-providers/not-real/validate", None),
    ],
)
def test_invalid_provider_is_rejected(client, method: str, path: str, body) -> None:
    response = getattr(client, method)(path, json=body)
    _assert_provider_error(
        response,
        status=404,
        code="PROVIDER_NOT_FOUND",
        provider="not-real",
    )


def test_validation_is_local_or_configuration_only_and_never_billable(
    client, test_state
) -> None:
    assert (
        client.put("/api/video-providers/fal", json={"apiKey": "fal-key"}).status_code
        == 200
    )
    assert (
        client.put(
            "/api/video-providers/custom",
            json={
                "baseUrl": "http://127.0.0.1:8090/v1",
                "modelId": "self-hosted/video",
            },
        ).status_code
        == 200
    )

    assert client.post("/api/video-providers/local/validate").json() == {
        "providerId": "local",
        "valid": True,
        "validationMode": "local",
    }
    for provider_id in ("fal", "custom"):
        response = client.post(f"/api/video-providers/{provider_id}/validate")
        assert response.status_code == 200
        assert response.json() == {
            "providerId": provider_id,
            "valid": True,
            "validationMode": "configuration",
        }

    assert test_state.http.calls == []


def test_validation_route_accepts_camel_case_unsaved_candidate_without_persisting(
    client,
) -> None:
    response = client.post(
        "/api/video-providers/custom/validate",
        json={
            "baseUrl": "http://localhost:9080/v1",
            "modelId": "self-hosted/video-v2",
            "apiKey": "optional-candidate-key",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "providerId": "custom",
        "valid": True,
        "validationMode": "configuration",
    }
    assert "optional-candidate-key" not in response.text
    assert "custom" not in _profiles_by_id(client.get("/api/video-providers").json())


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8090/v1",
        "http://127.0.0.1:8090/v1",
        "http://10.0.0.42:8090/v1",
        "http://192.168.1.42:8090/v1",
        "https://video.example.com/v1",
    ],
)
def test_custom_provider_allows_local_private_http_and_public_https(
    client, base_url: str
) -> None:
    response = client.put(
        "/api/video-providers/custom",
        json={"baseUrl": base_url, "modelId": "self-hosted/video"},
    )
    assert response.status_code == 200
    assert response.json()["baseUrl"] == base_url
    assert response.json()["hasApiKey"] is False


@pytest.mark.parametrize(
    "base_url", ["http://example.com/v1", "http://8.8.8.8:8090/v1"]
)
def test_custom_provider_rejects_public_http(client, base_url: str) -> None:
    response = client.put(
        "/api/video-providers/custom",
        json={"baseUrl": base_url, "modelId": "self-hosted/video"},
    )
    _assert_provider_error(
        response,
        status=400,
        code="PROVIDER_URL_UNSAFE",
        provider="custom",
    )


@pytest.mark.parametrize("provider_id", CLOUD_PROVIDER_IDS)
def test_curated_cloud_validation_requires_a_credential(
    client, provider_id: str
) -> None:
    saved = client.put(f"/api/video-providers/{provider_id}", json={})
    assert saved.status_code == 200
    assert saved.json()["hasApiKey"] is False

    response = client.post(f"/api/video-providers/{provider_id}/validate")
    _assert_provider_error(
        response,
        status=400,
        code="PROVIDER_CREDENTIAL_REQUIRED",
        provider=provider_id,
    )


def test_activation_requires_cloud_credentials_but_not_custom_credentials(
    client,
) -> None:
    assert client.put("/api/video-providers/fal", json={}).status_code == 200
    missing = client.put("/api/video-providers/active", json={"providerId": "fal"})
    _assert_provider_error(
        missing,
        status=400,
        code="PROVIDER_CREDENTIAL_REQUIRED",
        provider="fal",
    )

    assert (
        client.put(
            "/api/video-providers/custom",
            json={
                "baseUrl": "http://localhost:8090/v1",
                "modelId": "self-hosted/video",
            },
        ).status_code
        == 200
    )
    selected = client.put("/api/video-providers/active", json={"providerId": "custom"})
    assert selected.status_code == 200
    assert selected.json() == {"activeProvider": "custom"}


def test_provider_responses_never_serialize_saved_secret(client) -> None:
    secret = "secret-to-scan-for"
    assert (
        client.put("/api/video-providers/fal", json={"apiKey": secret}).status_code
        == 200
    )

    responses = [
        client.get("/api/video-providers"),
        client.put("/api/video-providers/active", json={"providerId": "fal"}),
        client.post("/api/video-providers/fal/validate"),
    ]
    for response in responses:
        assert response.status_code == 200
        assert secret not in response.text
        assert secret not in json.dumps(response.json())
