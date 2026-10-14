"""Own a Cloudflare Quick Tunnel process for Internet remote control."""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TextIO, cast
from urllib.parse import urlsplit

TunnelState = Literal["off", "starting", "ready", "error"]

logger = logging.getLogger(__name__)

_QUICK_TUNNEL_URL = re.compile(r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com", re.IGNORECASE)
_BEARER_TOKEN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)")
_ENV_TOKEN = re.compile(r"(?i)(TUNNEL_TOKEN\s*=\s*)([^\s,;]+)")
_CLI_TOKEN = re.compile(r"(?i)(--token(?:=|\s+))([^\s,;]+)")


class TunnelProcess(Protocol):
    stdout: TextIO | None

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


ProcessFactory = Callable[..., TunnelProcess]


class ParentLifetime(Protocol):
    def close(self) -> None: ...


class _WindowsFunction(Protocol):
    argtypes: object
    restype: object

    def __call__(self, *args: object) -> int | None: ...


class _Kernel32(Protocol):
    CreateJobObjectW: _WindowsFunction
    SetInformationJobObject: _WindowsFunction
    AssignProcessToJobObject: _WindowsFunction
    CloseHandle: _WindowsFunction


class _JobObjectLifetime:
    def __init__(self, handle: int, close_handle: Callable[[int], int]) -> None:
        self._handle = handle
        self._close_handle = close_handle

    def close(self) -> None:
        handle, self._handle = self._handle, 0
        if handle:
            self._close_handle(handle)


def attach_process_to_parent_lifetime(
    process: object, *, platform: str = sys.platform
) -> ParentLifetime | None:
    """On Windows, kill the child if this backend exits without cleanup."""
    if platform != "win32":
        return None
    process_handle = getattr(process, "_handle", None)
    if not isinstance(process_handle, int):
        return None

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    win_dll = cast(Callable[..., object], getattr(ctypes, "WinDLL"))
    win_error = cast(Callable[[int], OSError], getattr(ctypes, "WinError"))
    get_last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    kernel32 = cast(_Kernel32, win_dll("kernel32", use_last_error=True))
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    job_handle = kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        raise win_error(get_last_error())
    try:
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job_handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise win_error(get_last_error())
        if not kernel32.AssignProcessToJobObject(job_handle, process_handle):
            raise win_error(get_last_error())
    except BaseException:
        kernel32.CloseHandle(job_handle)
        raise
    return _JobObjectLifetime(
        job_handle, lambda handle: int(kernel32.CloseHandle(handle) or 0)
    )


@dataclass(frozen=True)
class CloudflareTunnelStatus:
    state: TunnelState
    public_url: str | None = None
    error: str | None = None


def parse_cloudflare_tunnel_url(line: str) -> str | None:
    """Return a validated HTTPS Quick Tunnel origin from one cloudflared line."""
    match = _QUICK_TUNNEL_URL.search(line)
    if match is None:
        return None
    candidate = match.group(0).rstrip("/.")
    parts = urlsplit(candidate)
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or not parts.hostname
        or not parts.hostname.endswith(".trycloudflare.com")
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://{parts.hostname.lower()}"


def redact_tunnel_error(message: str, extra_values: Iterable[str] = ()) -> str:
    """Keep diagnostics useful without surfacing credentials in status or logs."""
    redacted = _BEARER_TOKEN.sub(r"\1[REDACTED]", message)
    redacted = _ENV_TOKEN.sub(r"\1[REDACTED]", redacted)
    redacted = _CLI_TOKEN.sub(r"\1[REDACTED]", redacted)
    for value in extra_values:
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted.strip()[:500]


def resolve_cloudflared_executable() -> str:
    configured = os.environ.get("HYPERGEN_CLOUDFLARED_PATH", "").strip()
    if configured:
        return configured

    filename = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
    module_path = Path(__file__).resolve()
    executable_path = Path(sys.executable).resolve()
    candidates = [
        module_path.parents[2] / "resources" / "cloudflared" / filename,
        *(parent / "cloudflared" / filename for parent in executable_path.parents[:4]),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("cloudflared") or "cloudflared"


class CloudflareTunnel:
    def __init__(
        self,
        *,
        process_factory: ProcessFactory | None = None,
        executable: str | None = None,
        redacted_values: Iterable[str] = (),
    ) -> None:
        self._process_factory = process_factory or cast(ProcessFactory, subprocess.Popen)
        self._executable = executable or resolve_cloudflared_executable()
        self._redacted_values = tuple(redacted_values)
        self._lock = threading.Lock()
        self._process: TunnelProcess | None = None
        self._parent_lifetime: ParentLifetime | None = None
        self._origin_url: str | None = None
        self._status = CloudflareTunnelStatus(state="off")

    def start(self, origin_url: str) -> CloudflareTunnelStatus:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self._status
            if self._parent_lifetime is not None:
                self._parent_lifetime.close()
                self._parent_lifetime = None
            self._origin_url = origin_url
            starting = CloudflareTunnelStatus(state="starting")
            self._status = starting
            command = [
                self._executable,
                "tunnel",
                "--no-autoupdate",
                "--loglevel",
                "info",
                "--http-host-header",
                "localhost",
                "--url",
                origin_url,
            ]
            kwargs: dict[str, object] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            process: TunnelProcess | None = None
            try:
                process = self._process_factory(command, **kwargs)
                parent_lifetime = attach_process_to_parent_lifetime(process)
            except (OSError, ValueError) as exc:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5.0)
                self._status = CloudflareTunnelStatus(
                    state="error",
                    error=redact_tunnel_error(
                        f"Cloudflare Tunnel could not start: {exc}", self._redacted_values
                    ),
                )
                return self._status
            assert process is not None
            self._process = process
            self._parent_lifetime = parent_lifetime

        threading.Thread(
            target=self._read_output,
            args=(process,),
            name="hypergen-cloudflare-tunnel",
            daemon=True,
        ).start()
        return starting

    def status(self) -> CloudflareTunnelStatus:
        with self._lock:
            process = self._process
            if (
                process is not None
                and process.poll() is not None
                and self._status.state in ("starting", "ready")
            ):
                self._status = CloudflareTunnelStatus(
                    state="error",
                    error="Cloudflare Tunnel stopped unexpectedly. Turn Internet access off and on to retry.",
                )
            return self._status

    def stop(self) -> CloudflareTunnelStatus:
        with self._lock:
            process = self._process
            parent_lifetime = self._parent_lifetime
            self._process = None
            self._parent_lifetime = None
            self._origin_url = None
            self._status = CloudflareTunnelStatus(state="off")
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        if parent_lifetime is not None:
            parent_lifetime.close()
        return self.status()

    def _read_output(self, process: TunnelProcess) -> None:
        last_error = ""
        output = process.stdout
        if output is not None:
            for line in output:
                public_url = parse_cloudflare_tunnel_url(line)
                with self._lock:
                    if self._process is not process:
                        return
                    if public_url is not None:
                        self._status = CloudflareTunnelStatus(
                            state="ready", public_url=public_url
                        )
                        logger.info("Cloudflare Tunnel ready at %s", public_url)
                    elif "ERR" in line.upper() or "ERROR" in line.upper():
                        last_error = redact_tunnel_error(line, self._redacted_values)
        return_code = process.poll()
        if return_code is None:
            return
        with self._lock:
            if self._process is not process or self._status.state == "off":
                return
            detail = last_error or f"cloudflared exited with code {return_code}"
            self._status = CloudflareTunnelStatus(
                state="error",
                error=redact_tunnel_error(detail, self._redacted_values),
            )
