from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def file_hash(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sanitize_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-") or "unknown"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


@contextmanager
def exclusive_file_lock(path: Path, *, timeout_seconds: float = 5.0):
    """Small cross-process lock for workspace-file state."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            break
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > max(60.0, timeout_seconds * 4)
            except FileNotFoundError:
                continue
            if stale:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for file lock: {path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False) + "\n"
    with exclusive_file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

def _status_class(value: Any) -> str:
    text = str(value).lower()
    if text in {"ok", "allow", "accepted", "approved", "enabled", "filled", "valid", "read", "true", "open"}:
        return "good"
    if text in {"deny", "denied", "rejected", "error", "blocked", "disabled", "false", "execution"}:
        return "bad"
    if text in {"proposed", "pending", "recorded", "stubbed", "write", "approval", "research-only"}:
        return "warn"
    return "neutral"


def _resolve_path(root: Path, raw: str) -> Path:
    return safe_workspace_path(root, raw)


def safe_workspace_path(root: Path | str, raw: str | Path, *, allowed_roots: tuple[Path | str, ...] = ()) -> Path:
    text = str(raw).strip()
    if not text:
        raise ValueError("workspace path is required")
    if "\x00" in text:
        raise ValueError("workspace path contains a NUL byte")
    if "\\" in text:
        raise ValueError("workspace path must use forward-slash relative paths")
    if re.match(r"^[A-Za-z]:", text):
        raise ValueError("workspace path must be relative")
    raw_path = Path(text)
    if raw_path.is_absolute():
        raise ValueError("workspace path must be relative")
    if any(part == ".." for part in raw_path.parts):
        raise ValueError("workspace path must not contain '..'")

    workspace_root = Path(root).expanduser().resolve(strict=False)
    candidate = (workspace_root / raw_path).resolve(strict=False)
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("workspace path escapes the workspace root") from exc

    if allowed_roots:
        allowed = False
        for allowed_root in allowed_roots:
            allowed_path = Path(allowed_root)
            if allowed_path.is_absolute():
                raise ValueError("allowed workspace roots must be relative")
            allowed_abs = (workspace_root / allowed_path).resolve(strict=False)
            try:
                candidate.relative_to(allowed_abs)
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            allowed_text = ", ".join(Path(item).as_posix() for item in allowed_roots)
            raise ValueError(f"workspace path must stay under: {allowed_text}")
    return candidate


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def local_or_staff_source(
    request: Any,
    *,
    api_key: str | None = None,
    api_key_principal: str | None = None,
    api_key_header: str = "X-TradingCodex-Key",
) -> str | None:
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_staff", False):
        return f"principal:{getattr(user, 'username', '')}"
    headers = getattr(request, "headers", {})
    if api_key and api_key_principal and headers.get(api_key_header) == api_key:
        return f"principal:{api_key_principal}"
    remote_addr = getattr(request, "META", {}).get("REMOTE_ADDR", "")
    method = str(getattr(request, "method", "GET")).upper()
    if remote_addr in {"127.0.0.1", "::1", ""} and method in {"GET", "HEAD", "OPTIONS"}:
        return "local-readonly"
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _validate_positive(value: Any, field: str, reasons: list[str]) -> None:
    if value in (None, ""):
        return
    number = _number(value)
    if number is None or number <= 0:
        reasons.append(f"{field} must be a positive number")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
