"""Controller contracts unique to Cloudflare Internet exposure."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from remote.cloudflare_tunnel import CloudflareTunnelStatus
from remote.controller import RemoteExposureController, _Running
from state.app_settings import RemoteExposure

if TYPE_CHECKING:
    import uvicorn


class _StartedServer:
    started = True
    should_exit = False


class _LiveThread:
    def is_alive(self) -> bool:
        return True


@dataclass
class _Tunnel:
    snapshot: CloudflareTunnelStatus

    def status(self) -> CloudflareTunnelStatus:
        return self.snapshot

    def stop(self) -> CloudflareTunnelStatus:
        self.snapshot = CloudflareTunnelStatus(state="off")
        return self.snapshot


def _cloudflare_controller(test_state, snapshot: CloudflareTunnelStatus):
    controller = RemoteExposureController(test_state)
    controller._ownership = _Running(
        server=cast("uvicorn.Server", _StartedServer()),
        thread=cast(threading.Thread, _LiveThread()),
        port=41955,
    )
    controller._exposure = "cloudflare"
    controller._tunnel = _Tunnel(snapshot)  # type: ignore[assignment]
    return controller


def test_ready_status_advertises_public_pairing_url_without_lan_url(
    test_state, monkeypatch
) -> None:
    monkeypatch.setenv("LTX_AUTH_TOKEN", "desktop-secret")
    controller = _cloudflare_controller(
        test_state,
        CloudflareTunnelStatus(
            state="ready",
            public_url="https://quiet-sun.trycloudflare.com",
        ),
    )

    payload = controller.status()

    assert payload.permitted is True
    assert payload.serving is True
    assert payload.mode == "cloudflare"
    assert payload.tunnelState == "ready"
    assert payload.publicUrl is not None
    assert payload.publicUrl.startswith(
        "https://quiet-sun.trycloudflare.com/pairing?t="
    )
    assert payload.url == payload.publicUrl
    assert payload.lanUrl is None
    assert payload.localUrl is not None
    assert payload.localUrl.startswith("http://127.0.0.1:41955/pairing?t=")


@pytest.mark.parametrize(
    ("snapshot", "expected_reason"),
    [
        (CloudflareTunnelStatus(state="starting"), "starting Cloudflare Tunnel"),
        (
            CloudflareTunnelStatus(state="error", error="cloudflared unavailable"),
            "cloudflared unavailable",
        ),
    ],
)
def test_cloudflare_status_is_not_serving_until_public_url_is_ready(
    test_state,
    monkeypatch,
    snapshot: CloudflareTunnelStatus,
    expected_reason: str,
) -> None:
    monkeypatch.setenv("LTX_AUTH_TOKEN", "desktop-secret")
    payload = _cloudflare_controller(test_state, snapshot).status()

    assert payload.serving is False
    assert payload.url is None
    assert payload.publicUrl is None
    assert payload.tunnelState == snapshot.state
    assert payload.reason == expected_reason


class _RecordedThread:
    def __init__(self, *, target, args=(), **_kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        return None

    def is_alive(self) -> bool:
        return True


class _UnstartedServer:
    def __init__(self, config) -> None:
        self.config = config
        self.started = False
        self.should_exit = False

    def run(self) -> None:
        return None


@pytest.mark.parametrize(
    ("exposure", "expected_host"),
    [("cloudflare", "127.0.0.1"), ("lan", "0.0.0.0")],
)
def test_bind_host_limits_cloudflare_to_loopback_and_keeps_lan_unchanged(
    test_state,
    monkeypatch,
    exposure: RemoteExposure,
    expected_host: str,
) -> None:
    import uvicorn

    test_state.state.app_settings.remote_exposure = exposure
    monkeypatch.setattr("remote.controller.threading.Thread", _RecordedThread)
    monkeypatch.setattr(uvicorn, "Server", _UnstartedServer)
    controller = RemoteExposureController(test_state)

    controller._start_locked()

    assert isinstance(controller._ownership, _Running)
    assert controller._ownership.server.config.host == expected_host
