from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any


MODE_FILE_RELATIVE_PATH = Path(".tradingcodex") / "runtime" / "mode.json"
MODE_FORMAT = "tradingcodex.runtime-mode"
MODE_SCHEMA_VERSION = 1
MODE_FIELDS = frozenset({
    "format",
    "schema_version",
    "mode",
    "reason",
    "updated_at",
    "expires_at",
    "ttl_hours",
})
DEFAULT_MODE = "operate"
BUILD_TTL_HOURS = 24
VALID_MODES = {"operate", "build"}

RETIRED_MODE_REASON = (
    "Persistent TradingCodex build mode is retired and grants no authority; "
    "start a writable root native Codex turn with the exact first line `$tcx-build`."
)


def get_runtime_mode_status(
    workspace_root: Path | str,
    *,
    full_access_detected: bool = False,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a fail-safe compatibility projection for the retired mode API.

    The legacy mode file is deliberately never opened, parsed, followed, or
    migrated. Its former contents, validity, and expiry cannot authorize a
    build action.
    """

    del checked_at
    root = Path(workspace_root).expanduser().resolve()
    path = root / MODE_FILE_RELATIVE_PATH
    legacy_present = os.path.lexists(path)
    return {
        "status": "retired",
        "authority": "none",
        "authorization_contract": "exact_tcx_build_turn",
        "exact_first_line": "$tcx-build",
        "mode": DEFAULT_MODE,
        "requested_mode": DEFAULT_MODE,
        "build_enabled": False,
        "build_blocked_reason": RETIRED_MODE_REASON,
        "tcx_build_mode_active": False,
        "full_access_required": False,
        "full_access_detected": bool(full_access_detected),
        "permission_is_advisory": True,
        "expires_at": "",
        "expired": False,
        "reason": "",
        "updated_at": "",
        "path": str(path),
        "legacy_mode_file_present": legacy_present,
        "legacy_mode_file_ignored": legacy_present,
    }


def set_runtime_mode(
    workspace_root: Path | str,
    mode: str,
    *,
    reason: str = "",
    ttl_hours: int = BUILD_TTL_HOURS,
) -> dict[str, Any]:
    """Reject the retired persistent-mode mutation without touching disk."""

    del workspace_root, mode, reason, ttl_hours
    raise ValueError(RETIRED_MODE_REASON)


def reset_runtime_mode(workspace_root: Path | str) -> dict[str, Any]:
    """Reject the retired reset operation without touching disk."""

    return set_runtime_mode(workspace_root, DEFAULT_MODE)
