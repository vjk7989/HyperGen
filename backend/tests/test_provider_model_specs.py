from __future__ import annotations

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from api_types import CreateTextToVideoRequest
from remote.app import create_remote_app
from services.video_providers import PROVIDER_DESCRIPTORS


def _configure_profile(client: TestClient, provider_id: str, model_id: str) -> None:
    body: dict[str, str] = {"modelId": model_id}
    if provider_id != "custom":
        body["apiKey"] = f"{provider_id}-secret"
    else:
        body["baseUrl"] = "http://localhost:8090/v1"
    response = client.put(f"/api/video-providers/{provider_id}", json=body)
    assert response.status_code == 200


def test_only_active_cloud_provider_offerings_are_qualified_and_include_option_matrices(
    client: TestClient, create_fake_model_files
) -> None:
    create_fake_model_files(model_id="ltx-2.3-22b-distilled-1.1")
    before = client.get("/api/generate/models-specs").json()

    configured_model = "team/opaque-video@2026.10"
    _configure_profile(client, "fal", configured_model)
    _configure_profile(client, "replicate", "inactive/private-video")
    _configure_profile(client, "custom", "self-hosted/video")
    selected = client.put(
        "/api/video-providers/active", json={"providerId": "fal"}
    )
    assert selected.status_code == 200

    response = client.get("/api/generate/models-specs")
    assert response.status_code == 200
    payload = response.json()

    assert payload["local_models"] == before["local_models"]
    assert payload["api_models"] == before["api_models"]
    assert payload["downloaded_local_models"] == before["downloaded_local_models"]
    assert [item["model"] for item in payload["downloaded_local_models"]] == [
        "ltx-2.3-fast"
    ]

    offerings = payload["providerOfferings"]
    assert all(
        set(offering)
        == {
            "providerId",
            "modelId",
            "offeringId",
            "displayName",
            "capabilities",
            "controls",
            "optionMatrix",
        }
        for offering in offerings
    )
    assert {item["providerId"] for item in offerings} == {"fal"}
    pairs = [(item["providerId"], item["modelId"]) for item in offerings]
    assert len(pairs) == len(set(pairs))

    fal_models = [
        item["modelId"] for item in offerings if item["providerId"] == "fal"
    ]
    assert fal_models == [
        configured_model,
        *PROVIDER_DESCRIPTORS["fal"].suggested_model_ids,
    ]
    assert not any(item["providerId"] == "replicate" for item in offerings)
    assert not any(item["providerId"] == "custom" for item in offerings)
    assert payload["active_offering"] == f"fal:{configured_model}"

    for offering in offerings:
        assert offering["offeringId"] == (
            f'{offering["providerId"]}:{offering["modelId"]}'
        )
        assert offering["displayName"]
        assert offering["capabilities"] == {"textToVideo": True}
        assert offering["optionMatrix"]
        for cell in offering["optionMatrix"].values():
            assert cell["aspectRatios"]
            assert cell["fpsToDurations"]

    with pytest.raises(ValidationError):
        CreateTextToVideoRequest.model_validate(
            {"params": {"prompt": "fox", "model": configured_model}}
        )


def test_active_local_preserves_downloaded_local_offering_behavior(
    client: TestClient, create_fake_model_files
) -> None:
    create_fake_model_files(model_id="ltx-2.3-22b-distilled-1.1")
    _configure_profile(client, "fal", "inactive/private-video")
    selected = client.put(
        "/api/video-providers/active", json={"providerId": "local"}
    )
    assert selected.status_code == 200

    response = client.get("/api/generate/models-specs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providerOfferings"] == []
    assert [item["model"] for item in payload["downloaded_local_models"]] == [
        "ltx-2.3-fast"
    ]
    assert payload["active_offering"] == "ltx-2.3-fast"


@pytest.mark.parametrize(
    ("provider_id", "expected_controls"),
    [
        (
            "fal",
            {
                "aspectRatio": "editable",
                "resolution": "unsupported",
                "duration": "editable",
                "fps": "unsupported",
                "audio": "optional",
            },
        ),
        (
            "replicate",
            {
                "aspectRatio": "editable",
                "resolution": "editable",
                "duration": "editable",
                "fps": "unsupported",
                "audio": "optional",
            },
        ),
        (
            "runway",
            {
                "aspectRatio": "editable",
                "resolution": "editable",
                "duration": "editable",
                "fps": "unsupported",
                "audio": "unsupported",
            },
        ),
        (
            "luma",
            {
                "aspectRatio": "editable",
                "resolution": "editable",
                "duration": "editable",
                "fps": "unsupported",
                "audio": "unsupported",
            },
        ),
        (
            "google_veo",
            {
                "aspectRatio": "editable",
                "resolution": "editable",
                "duration": "editable",
                "fps": "fixed",
                "audio": "required",
            },
        ),
        (
            "ltx",
            {
                "aspectRatio": "editable",
                "resolution": "editable",
                "duration": "editable",
                "fps": "editable",
                "audio": "optional",
            },
        ),
        (
            "custom",
            {
                "aspectRatio": "editable",
                "resolution": "editable",
                "duration": "editable",
                "fps": "editable",
                "audio": "optional",
            },
        ),
    ],
)
def test_active_provider_offerings_publish_shared_control_capabilities(
    client: TestClient,
    provider_id: str,
    expected_controls: dict[str, str],
) -> None:
    _configure_profile(client, provider_id, "test/video-model")
    selected = client.put(
        "/api/video-providers/active", json={"providerId": provider_id}
    )
    assert selected.status_code == 200

    response = client.get("/api/generate/models-specs")

    assert response.status_code == 200
    offerings = response.json()["providerOfferings"]
    assert offerings
    assert {offering["providerId"] for offering in offerings} == {provider_id}
    assert all(offering["controls"] == expected_controls for offering in offerings)


def test_desktop_and_remote_serialize_the_same_provider_offerings(
    client: TestClient, test_state
) -> None:
    _configure_profile(client, "luma", "ray-custom")
    desktop = client.get("/api/generate/models-specs")
    assert desktop.status_code == 200

    remote_app = create_remote_app(handler=test_state, remote_token="pair-token")
    with TestClient(remote_app) as remote_client:
        remote = remote_client.get(
            "/api/generate/models-specs",
            headers={"Authorization": "Bearer pair-token"},
        )

    assert remote.status_code == 200
    assert remote.json()["providerOfferings"] == desktop.json()["providerOfferings"]
