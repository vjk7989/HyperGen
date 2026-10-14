"""The Cloudflare child must not outlive an abruptly terminated backend."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from remote.cloudflare_tunnel import attach_process_to_parent_lifetime


def test_parent_lifetime_attachment_is_a_noop_for_fake_processes() -> None:
    assert attach_process_to_parent_lifetime(object(), platform="win32") is None


def test_parent_lifetime_attachment_is_a_noop_outside_windows() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert attach_process_to_parent_lifetime(process, platform="linux") is None
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object contract")
def test_windows_child_exits_when_backend_parent_closes_abruptly(tmp_path: Path) -> None:
    """KILL_ON_JOB_CLOSE must work even when Python cannot run finally/atexit."""
    harness = tmp_path / "abrupt_parent.py"
    harness.write_text(
        textwrap.dedent(
            """
            import os
            import subprocess
            import sys

            from remote.cloudflare_tunnel import attach_process_to_parent_lifetime

            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            lifetime = attach_process_to_parent_lifetime(child, platform="win32")
            if lifetime is None:
                raise RuntimeError("Windows child was not attached to parent lifetime")
            print(child.pid, flush=True)
            os._exit(0)
            """
        ),
        encoding="utf-8",
    )
    backend_root = Path(__file__).resolve().parents[1]
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = str(backend_root)
    if existing_pythonpath:
        pythonpath = f"{pythonpath}{os.pathsep}{existing_pythonpath}"
    parent = subprocess.Popen(
        [sys.executable, str(harness)],
        cwd=backend_root,
        env={**os.environ, "PYTHONPATH": pythonpath},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid: int | None = None
    try:
        stdout, stderr = parent.communicate(timeout=10)
        assert parent.returncode == 0, stderr
        child_pid = int(stdout.strip())
        assert _wait_for_windows_process_exit(child_pid, timeout_ms=5000), (
            "child process survived abrupt parent exit; cloudflared would remain running"
        )
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if child_pid is not None and not _wait_for_windows_process_exit(child_pid, timeout_ms=0):
            subprocess.run(
                ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )


def _wait_for_windows_process_exit(pid: int, *, timeout_ms: int) -> bool:
    synchronize = 0x00100000
    wait_object_0 = 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True
    try:
        return kernel32.WaitForSingleObject(handle, timeout_ms) == wait_object_0
    finally:
        kernel32.CloseHandle(handle)
