from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def sanitize_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-") or "unknown"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")

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
