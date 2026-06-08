from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from tradingcodex_service.domain import tradingcodex_file_lock, tradingcodex_state_dir


DEFAULT_SERVICE_ADDR = "127.0.0.1:8000"


def maybe_autostart_service(workspace_root: Path, source_root: Path | None = None) -> bool:
    if os.environ.get("TRADINGCODEX_MCP_AUTOSTART_SERVICE", "").lower() not in {"1", "true", "yes", "on"}:
        return False
    addr = os.environ.get("TRADINGCODEX_SERVICE_ADDR", DEFAULT_SERVICE_ADDR)
    timeout = float(os.environ.get("TRADINGCODEX_MCP_AUTOSTART_TIMEOUT", "8"))
    return ensure_service_up(workspace_root, addr=addr, source_root=source_root, timeout=timeout)


def ensure_service_up(workspace_root: Path, addr: str = DEFAULT_SERVICE_ADDR, source_root: Path | None = None, timeout: float = 8.0) -> bool:
    host, port = _parse_addr(addr)
    if _tcp_open(host, port):
        return False
    with tradingcodex_file_lock(f"service-{host}-{port}"):
        if _tcp_open(host, port):
            return False
        _start_service(workspace_root, addr, source_root)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _tcp_open(host, port):
                return True
            time.sleep(0.2)
    return False


def _start_service(workspace_root: Path, addr: str, source_root: Path | None) -> None:
    run_dir = tradingcodex_state_dir() / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "service.log"
    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
    env.setdefault("TRADINGCODEX_WORKSPACE_ROOT", str(workspace_root.resolve()))
    if source_root:
        current = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(source_root.resolve()) + (f":{current}" if current else "")
    with log_path.open("ab") as log_handle:
        subprocess.Popen(
            [sys.executable, "-m", "tradingcodex_cli", "service", "runserver", addr, "--noreload"],
            cwd=workspace_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )


def _parse_addr(addr: str) -> tuple[str, int]:
    if ":" in addr:
        host, port_text = addr.rsplit(":", 1)
        return host or "127.0.0.1", int(port_text)
    return "127.0.0.1", int(addr)


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False
