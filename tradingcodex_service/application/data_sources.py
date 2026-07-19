"""Minimal optional OpenBB MCP projection; never runs or configures OpenBB."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import atomic_write_text


OPENBB_STATE_PATH = Path(".tradingcodex/openbb.json")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def get_openbb_status(workspace_root: Path | str) -> dict[str, Any]:
    state = _read_state(workspace_root)
    return {
        "enabled": state["enabled"],
        "env_vars": state["env_vars"],
        "restart_required": state["enabled"],
        "note": "OpenBB is started directly by Codex on first use; TradingCodex does not install, run, proxy, or validate it.",
    }


def enable_openbb(workspace_root: Path | str, env_vars: list[str] | None = None) -> dict[str, Any]:
    state = _read_state(workspace_root)
    state["enabled"] = True
    state["env_vars"] = _env_vars([*state["env_vars"], *(env_vars or [])])
    _write_state(workspace_root, state)
    return get_openbb_status(workspace_root)


def disable_openbb(workspace_root: Path | str) -> dict[str, Any]:
    state = _read_state(workspace_root)
    state["enabled"] = False
    _write_state(workspace_root, state)
    return get_openbb_status(workspace_root)


def add_openbb_env_var(workspace_root: Path | str, name: str) -> dict[str, Any]:
    state = _read_state(workspace_root)
    state["env_vars"] = _env_vars([*state["env_vars"], name])
    _write_state(workspace_root, state)
    return get_openbb_status(workspace_root)


def remove_openbb_env_var(workspace_root: Path | str, name: str) -> dict[str, Any]:
    validated = _env_vars([name])[0]
    state = _read_state(workspace_root)
    state["env_vars"] = [item for item in state["env_vars"] if item != validated]
    _write_state(workspace_root, state)
    return get_openbb_status(workspace_root)


def openbb_projection_template_values(workspace_root: Path | str) -> dict[str, str]:
    state = _read_state(workspace_root)
    return {
        "OPENBB_MCP_ENABLED_TOML": "true" if state["enabled"] else "false",
        "OPENBB_MCP_ENV_VARS_TOML": json.dumps(state["env_vars"]),
    }


def _read_state(workspace_root: Path | str) -> dict[str, Any]:
    path = _state_path(workspace_root)
    if not path.exists():
        return {"enabled": True, "env_vars": []}
    if path.is_symlink() or not path.is_file():
        raise ValueError("OpenBB configuration must be a regular workspace file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("OpenBB configuration is invalid") from exc
    if not isinstance(raw, dict) or type(raw.get("enabled")) is not bool:
        raise ValueError("OpenBB configuration is invalid")
    return {"enabled": raw["enabled"], "env_vars": _env_vars(raw.get("env_vars", []))}


def _write_state(workspace_root: Path | str, state: dict[str, Any]) -> None:
    path = _state_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _state_path(workspace_root: Path | str) -> Path:
    root = Path(workspace_root).expanduser().resolve(strict=False)
    parent = root / OPENBB_STATE_PATH.parent
    if parent.is_symlink():
        raise ValueError("OpenBB configuration must not traverse a symlink")
    return parent / OPENBB_STATE_PATH.name


def _env_vars(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("OpenBB env_vars must be a list of environment variable names")
    names = []
    for value in values:
        name = str(value).strip()
        if not _ENV_NAME.fullmatch(name):
            raise ValueError("OpenBB environment variable names must be shell identifiers")
        names.append(name)
    return sorted(set(names))
