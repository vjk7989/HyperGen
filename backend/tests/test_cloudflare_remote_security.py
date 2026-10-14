"""Cloudflare exposure must preserve the remote app's pairing/auth boundary."""

from starlette.testclient import TestClient

from remote.app import create_remote_app


def test_cloudflare_transport_does_not_create_an_unauthenticated_api_path(test_state) -> None:
    app = create_remote_app(handler=test_state, remote_token="paired-session-token")

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/generations?feature=text-to-video").status_code == 401
        assert client.post("/api/pairing/exchange", json={"code": "wrong"}).status_code == 401

        authorized = client.get(
            "/api/generations?feature=text-to-video",
            headers={"Authorization": "Bearer paired-session-token"},
        )
        assert authorized.status_code == 200


def test_auth_short_circuit_errors_keep_remote_security_headers(test_state) -> None:
    app = create_remote_app(handler=test_state, remote_token="paired-session-token")

    with TestClient(app) as client:
        unauthorized = client.get("/api/generations?feature=text-to-video")
        forbidden = client.get("/api/assets/unknown/bytes?sig=invalid")

    assert unauthorized.status_code == 401
    assert forbidden.status_code == 403
    for response in (unauthorized, forbidden):
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
