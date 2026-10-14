"""Persistence and compatibility contracts for Internet remote exposure."""

from state.app_settings import AppSettings


def test_cloudflare_remote_exposure_round_trips_through_settings_api(
    client, test_state, monkeypatch
) -> None:
    monkeypatch.setenv("LTX_AUTH_TOKEN", "")

    response = client.post("/api/settings", json={"remoteExposure": "cloudflare"})

    assert response.status_code == 200
    assert test_state.state.app_settings.remote_exposure == "cloudflare"
    assert client.get("/api/settings").json()["remoteExposure"] == "cloudflare"


def test_remote_exposure_parser_preserves_supported_modes_and_fails_closed() -> None:
    assert AppSettings.model_validate({"remoteExposure": "off"}).remote_exposure == "off"
    assert AppSettings.model_validate({"remoteExposure": "lan"}).remote_exposure == "lan"
    assert (
        AppSettings.model_validate({"remoteExposure": "cloudflare"}).remote_exposure
        == "cloudflare"
    )
    assert AppSettings.model_validate({"remoteExposure": "public"}).remote_exposure == "off"
    assert AppSettings.model_validate({"remoteExposure": None}).remote_exposure == "off"
