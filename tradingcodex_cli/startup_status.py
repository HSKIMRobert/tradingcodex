from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_cli.service_autostart import DEFAULT_SERVICE_ADDR, service_http_url
from tradingcodex_service.application.runtime import tradingcodex_db_path, tradingcodex_home
from tradingcodex_service.version import TRADINGCODEX_VERSION


UPDATE_PREFERENCES_REL = "preferences/update.json"
PYPI_JSON_URL = "https://pypi.org/pypi/tradingcodex/json"


def build_server_status(workspace_root: Path | str, addr: str | None = None) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    service_addr = addr or os.environ.get("TRADINGCODEX_SERVICE_ADDR", DEFAULT_SERVICE_ADDR)
    dashboard_url = _safe_service_http_url(service_addr)
    health_url = f"{dashboard_url.rstrip('/')}/api/health"
    update_status = build_update_status(root)
    health = _read_health(health_url)
    service_status = "not_running_or_unreachable"
    if health:
        service_status = "ok" if _is_compatible_health(health) else "incompatible"
    mcp_config_present = _is_project_mcp_config_present(root)
    restart_codex_required = not mcp_config_present
    if restart_codex_required:
        recommended_action = "Run ./tcx update or ./tcx attach ., then fully quit and restart Codex and start a new thread."
    elif service_status == "ok":
        recommended_action = f"Open TradingCodex dashboard at {dashboard_url}"
    elif service_status == "incompatible":
        recommended_action = "Resolve the TradingCodex service version or central DB mismatch before using the dashboard."
    else:
        recommended_action = "./tcx service ensure"
    return {
        "checked_at": now(),
        "service_addr": service_addr,
        "dashboard_url": dashboard_url,
        "health_url": health_url,
        "service_status": service_status,
        "service_health": health,
        "mcp_config_present": mcp_config_present,
        "restart_codex_required": restart_codex_required,
        "update_status": update_status,
        "recommended_action": recommended_action,
    }


def fallback_server_status(workspace_root: Path | str, exc: Exception, addr: str | None = None) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    service_addr = addr or os.environ.get("TRADINGCODEX_SERVICE_ADDR", DEFAULT_SERVICE_ADDR)
    dashboard_url = _safe_service_http_url(service_addr)
    return {
        "checked_at": now(),
        "service_addr": service_addr,
        "dashboard_url": dashboard_url,
        "health_url": f"{dashboard_url.rstrip('/')}/api/health",
        "service_status": "unknown",
        "service_health": {},
        "mcp_config_present": _is_project_mcp_config_present(root),
        "restart_codex_required": False,
        "update_status": fallback_update_status(),
        "recommended_action": "./tcx doctor --layer service",
        "warning": f"server status check failed: {exc}",
    }


def write_server_status_snapshot(workspace_root: Path | str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    try:
        status = build_server_status(root)
    except Exception as exc:
        status = fallback_server_status(root, exc)
    path = root / ".tradingcodex" / "mainagent" / "server-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return status


def build_update_status(workspace_root: Path | str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    module_lock = _read_json(root / ".tradingcodex" / "generated" / "module-lock.json", {})
    preference_path = tradingcodex_home() / UPDATE_PREFERENCES_REL
    preferences = _read_json(preference_path, {})
    workspace_version = str(module_lock.get("tradingcodex_version") or "unknown")
    installed_version = TRADINGCODEX_VERSION
    suppressed = bool(preferences.get("suppress_update_recommendation"))
    versions_match = workspace_version == installed_version
    workspace_update_available = workspace_version not in {"", "unknown"} and not versions_match
    if workspace_update_available:
        latest = latest_release_info()
    else:
        latest = {
            "latest_release_version": "not_checked",
            "latest_release_status": "not_needed",
            "latest_release_source": "versions_match" if versions_match else "workspace_version_unavailable",
        }
    latest_version = latest["latest_release_version"]
    latest_status = latest["latest_release_status"]
    installed_release_is_stale = latest_status == "ok" and version_less_than(installed_version, latest_version)
    package_update_required_first = workspace_update_available and installed_release_is_stale
    workspace_update_allowed = workspace_update_available and not package_update_required_first
    workspace_update_recommended = workspace_update_allowed and not suppressed
    blocked_reason = "installed tcx is older than the latest release; update the package before refreshing this workspace" if package_update_required_first else ""
    if package_update_required_first:
        recommended_action = "uvx --refresh --from tradingcodex tcx update ."
    elif workspace_update_recommended:
        recommended_action = "./tcx update"
    else:
        recommended_action = ""
    return {
        "checked_at": now(),
        "workspace_version": workspace_version,
        "installed_version": installed_version,
        "package_version": installed_version,
        "latest_release_version": latest_version,
        "latest_release_status": latest_status,
        "latest_release_source": latest["latest_release_source"],
        "versions_match": versions_match,
        "workspace_update_available": workspace_update_available,
        "workspace_update_allowed": workspace_update_allowed,
        "workspace_update_recommended": workspace_update_recommended,
        "package_update_required_first": package_update_required_first,
        "installed_is_latest_release": latest_status == "ok" and installed_version == latest_version,
        "installed_release_is_stale": installed_release_is_stale,
        "update_recommendation_suppressed": suppressed,
        "preference_path": str(preference_path),
        "recommended_action": recommended_action,
        "blocked_reason": blocked_reason,
    }


def fallback_update_status() -> dict[str, Any]:
    return {
        "checked_at": now(),
        "workspace_version": "unknown",
        "installed_version": TRADINGCODEX_VERSION,
        "package_version": TRADINGCODEX_VERSION,
        "latest_release_version": "unknown",
        "latest_release_status": "unknown",
        "latest_release_source": "fallback",
        "versions_match": False,
        "workspace_update_available": False,
        "workspace_update_allowed": False,
        "workspace_update_recommended": False,
        "package_update_required_first": False,
        "installed_is_latest_release": False,
        "installed_release_is_stale": False,
        "update_recommendation_suppressed": False,
        "preference_path": str(tradingcodex_home() / UPDATE_PREFERENCES_REL),
        "recommended_action": "",
        "blocked_reason": "",
    }


def latest_release_info() -> dict[str, str]:
    override = os.environ.get("TRADINGCODEX_LATEST_RELEASE_VERSION", "").strip()
    if override:
        return {
            "latest_release_version": override,
            "latest_release_status": "ok",
            "latest_release_source": "env",
        }
    if os.environ.get("TRADINGCODEX_DISABLE_LATEST_RELEASE_CHECK", "").lower() in {"1", "true", "yes", "on"}:
        return {
            "latest_release_version": "unknown",
            "latest_release_status": "unknown",
            "latest_release_source": "disabled",
        }
    try:
        timeout = float(os.environ.get("TRADINGCODEX_LATEST_RELEASE_TIMEOUT", "0.75"))
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
        data = json.loads(payload)
        version = str((data.get("info") or {}).get("version") or "").strip()
        if version:
            return {
                "latest_release_version": version,
                "latest_release_status": "ok",
                "latest_release_source": "pypi",
            }
    except Exception:
        pass
    return {
        "latest_release_version": "unknown",
        "latest_release_status": "unknown",
        "latest_release_source": "unavailable",
    }


def version_less_than(left: str, right: str) -> bool:
    left_key = _release_version_key(left)
    right_key = _release_version_key(right)
    if not left_key or not right_key:
        return False
    length = max(len(left_key), len(right_key))
    return left_key + (0,) * (length - len(left_key)) < right_key + (0,) * (length - len(right_key))


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _release_version_key(version: str) -> tuple[int, ...]:
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", version)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _safe_service_http_url(addr: str) -> str:
    try:
        return service_http_url(addr)
    except Exception:
        return service_http_url(DEFAULT_SERVICE_ADDR)


def _is_project_mcp_config_present(root: Path) -> bool:
    config_path = root / ".codex" / "config.toml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except Exception:
        return False
    return "[mcp_servers.tradingcodex]" in text and "TRADINGCODEX_MCP_AUTOSTART_SERVICE" in text


def _read_health(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            payload = response.read().decode("utf-8")
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_compatible_health(health: dict[str, Any]) -> bool:
    return (
        health.get("service") == "tradingcodex"
        and health.get("version") == TRADINGCODEX_VERSION
        and str(health.get("db_path") or "") == str(tradingcodex_db_path())
    )


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
