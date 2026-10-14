"""Focused contracts for Cloudflare Quick Tunnel discovery and lifecycle."""

from __future__ import annotations

import io
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

import pytest

import remote.cloudflare_tunnel as cloudflare_tunnel
from remote.cloudflare_tunnel import (
    CloudflareTunnel,
    CloudflareTunnelStatus,
    parse_cloudflare_tunnel_url,
    redact_tunnel_error,
    resolve_cloudflared_executable,
)


class _FakeProcess:
    def __init__(self, output: str, *, returncode: int | None = None) -> None:
        self.stdout: TextIO | None = io.StringIO(output)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _ProcessFactory:
    def __init__(self, process: _FakeProcess) -> None:
        self.process = process
        self.command: list[str] | None = None
        self.kwargs: dict[str, object] | None = None

    def __call__(self, command: list[str], **kwargs: object) -> _FakeProcess:
        self.command = command
        self.kwargs = kwargs
        return self.process


def _wait_for(
    tunnel: CloudflareTunnel,
    predicate: Callable[[CloudflareTunnelStatus], bool],
    *,
    timeout: float = 1.0,
) -> CloudflareTunnelStatus:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = tunnel.status()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"Cloudflare tunnel state did not settle: {tunnel.status()!r}")


def test_parser_accepts_only_cloudflare_https_quick_tunnel_urls() -> None:
    log_line = (
        "2026-10-14T11:02:03Z INF +--------------------------------------+\n"
        "2026-10-14T11:02:03Z INF | https://violet-river.trycloudflare.com |"
    )
    assert parse_cloudflare_tunnel_url(log_line) == "https://violet-river.trycloudflare.com"

    assert parse_cloudflare_tunnel_url("http://violet-river.trycloudflare.com") is None
    assert parse_cloudflare_tunnel_url("https://trycloudflare.com.evil.example") is None
    assert parse_cloudflare_tunnel_url("https://example.com") is None


def test_start_reaches_ready_and_stop_terminates_the_child() -> None:
    process = _FakeProcess(
        "INF Your quick Tunnel has been created! Visit it at\n"
        "INF https://quiet-sun.trycloudflare.com\n"
    )
    factory = _ProcessFactory(process)
    tunnel = CloudflareTunnel(process_factory=factory)

    starting = tunnel.start("http://127.0.0.1:41955")
    assert starting.state == "starting"
    assert starting.public_url is None

    ready = _wait_for(tunnel, lambda value: value.state == "ready")
    assert ready.public_url == "https://quiet-sun.trycloudflare.com"
    assert ready.error is None
    assert factory.command is not None
    assert factory.command[-1] == "http://127.0.0.1:41955"
    assert "--no-autoupdate" in factory.command

    stopped = tunnel.stop()
    assert stopped.state == "off"
    assert stopped.public_url is None
    assert process.terminated is True


def test_process_exit_becomes_redacted_retryable_error() -> None:
    secret = "cf-secret-value"
    process = _FakeProcess(
        f"ERR Authentication failed for token {secret}\n",
        returncode=1,
    )
    tunnel = CloudflareTunnel(
        process_factory=_ProcessFactory(process),
        redacted_values=(secret,),
    )

    tunnel.start("http://127.0.0.1:41955")
    failed = _wait_for(tunnel, lambda value: value.state == "error")

    assert failed.public_url is None
    assert failed.error is not None
    assert secret not in failed.error
    assert "[REDACTED]" in failed.error


def test_redaction_handles_bearer_and_named_tunnel_tokens() -> None:
    message = (
        "Authorization: Bearer abc.def.ghi "
        "TUNNEL_TOKEN=super-secret --token command-secret"
    )
    redacted = redact_tunnel_error(message)

    assert "abc.def.ghi" not in redacted
    assert "super-secret" not in redacted
    assert "command-secret" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_repeated_start_is_idempotent_and_does_not_spawn_another_process() -> None:
    process = _FakeProcess("INF https://soft-forest.trycloudflare.com\n")
    calls = 0

    def factory(command: list[str], **kwargs: object) -> _FakeProcess:
        nonlocal calls
        del command, kwargs
        calls += 1
        return process

    tunnel = CloudflareTunnel(process_factory=factory)
    tunnel.start("http://127.0.0.1:41955")
    tunnel.start("http://127.0.0.1:41955")

    assert calls == 1
    tunnel.stop()


@pytest.mark.parametrize(
    ("platform", "python_relative", "binary_name"),
    [
        ("win32", Path("python") / "python.exe", "cloudflared.exe"),
        ("linux", Path("python") / "bin" / "python", "cloudflared"),
    ],
)
def test_resolver_finds_packaged_sibling_from_each_python_layout(
    tmp_path: Path,
    monkeypatch,
    platform: str,
    python_relative: Path,
    binary_name: str,
) -> None:
    resources = tmp_path / "resources"
    python_executable = resources / python_relative
    cloudflared = resources / "cloudflared" / binary_name
    python_executable.parent.mkdir(parents=True)
    python_executable.touch()
    cloudflared.parent.mkdir(parents=True)
    cloudflared.touch()

    monkeypatch.delenv("HYPERGEN_CLOUDFLARED_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "executable", str(python_executable))
    monkeypatch.setattr(
        cloudflare_tunnel,
        "__file__",
        str(tmp_path / "source" / "backend" / "remote" / "cloudflare_tunnel.py"),
    )
    monkeypatch.setattr(cloudflare_tunnel.shutil, "which", lambda _name: None)

    assert resolve_cloudflared_executable() == str(cloudflared)
