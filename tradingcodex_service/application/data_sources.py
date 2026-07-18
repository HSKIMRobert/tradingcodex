from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from tradingcodex_service.application.common import (
    atomic_write_text,
    exclusive_file_lock,
    now_iso,
    read_json,
    stable_hash,
    workspace_launcher_command,
)
from tradingcodex_service.application.runtime import read_workspace_manifest, tradingcodex_home
from tradingcodex_service.log_safety import redact_log_text
from tradingcodex_service.version import TRADINGCODEX_VERSION


DATA_SOURCE_FORMAT = "tradingcodex.data-sources"
DATA_SOURCE_SCHEMA_VERSION = 1
CREDENTIAL_FORMAT = "tradingcodex.data-source-credential-references"
CREDENTIAL_SCHEMA_VERSION = 1
COMPATIBILITY_FORMAT = "tradingcodex.openbb-compatibility-receipt"
COMPATIBILITY_SCHEMA_VERSION = 1
PROJECTION_FORMAT = "tradingcodex.openbb-projection"
PROJECTION_SCHEMA_VERSION = 1
WORKSPACE_DATA_SOURCE_PATH = Path(".tradingcodex/user/data-sources.json")
OPENBB_PROJECTION_PATH = Path(".tradingcodex/generated/openbb-projection.json")
OPENBB_CREDENTIAL_PATH = Path("preferences/data-source-credentials.json")
OPENBB_RUNTIME_PATH = Path("integrations/openbb")

OPENBB_EVIDENCE_ROLES = frozenset(
    {
        "fundamental-analyst",
        "instrument-analyst",
        "macro-analyst",
        "news-analyst",
        "technical-analyst",
        "valuation-analyst",
    }
)
DECLARED_ACCESS_VALUES = frozenset({"keyless", "free", "paid", "unknown"})
AUTO_USE_VALUES = frozenset({"allow", "ask", "deny"})
SECONDARY_PROVIDER_IDS = frozenset({"alpha-vantage", "alpha_vantage", "yfinance"})
DATA_KINDS = frozenset(
    {
        "bond_price",
        "commodity_price",
        "corporate_action",
        "crypto_price",
        "energy",
        "equity_price",
        "etf_price",
        "filing",
        "fundamentals",
        "futures_price",
        "fx_reference",
        "labor",
        "macro",
        "news",
        "options_price",
        "positioning",
        "reference",
        "yield_curve",
    }
)

_PROVIDER_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_SLOT_RE = re.compile(
    r"[a-z][a-z0-9_]{0,63}_(?:api_key|token|client_id|client_secret|username|password)"
)
_ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,127}")
_PROTECTED_CHILD_ENV = frozenset(
    {
        "HOME",
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "TRADINGCODEX_HOME",
        "TRADINGCODEX_DB_NAME",
        "TRADINGCODEX_WORKSPACE_ROOT",
        "UV_CACHE_DIR",
        "UV_CONFIG_FILE",
        "UV_NO_CONFIG",
        "VIRTUAL_ENV",
    }
)
_BASE_ENV_ALLOWLIST = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PATHEXT",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SystemRoot",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "WINDIR",
    }
)
_PROTECTED_ENV_PREFIXES = (
    "CODEX_",
    "DYLD_",
    "GIT_",
    "LD_",
    "OPENBB_",
    "PYTHON",
    "SSH_",
    "SSL_",
    "TCX_",
    "TRADINGCODEX_",
    "UV_",
)
_OPENBB_ADMIN_TOOLS = frozenset({"available_tools", "activate_tools"})
_OPENBB_CLIENT_METHODS = frozenset(
    {
        "initialize",
        "notifications/cancelled",
        "notifications/initialized",
        "ping",
        "tools/call",
        "tools/list",
    }
)
_OPENBB_SERVER_NOTIFICATIONS = frozenset({"notifications/tools/list_changed"})
_BLOCKED_TOOL_TOKENS = frozenset(
    {
        "account",
        "broker",
        "cancel",
        "connect",
        "create",
        "delete",
        "disable",
        "download",
        "enable",
        "execute",
        "execute_prompt",
        "export",
        "import",
        "install",
        "login",
        "logout",
        "modify",
        "move",
        "mutate",
        "order",
        "patch",
        "place",
        "portfolio",
        "post",
        "publish",
        "put",
        "remove",
        "rename",
        "save",
        "set",
        "submit",
        "transfer",
        "trade",
        "update",
        "upload",
        "upsert",
        "withdraw",
        "write",
    }
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|headers?|api[_-]?key|client[_-]?secret|password|secret|token)",
    re.I,
)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(bearer\s+|basic\s+)[^\s,;]+|"
    r"((?:api[_-]?key|client[_-]?secret|password|secret|token|authorization|cookie|set-cookie)\s*[:=]\s*)[^\r\n,;&]+"
)
OPENBB_RESPONSE_CHAR_LIMIT = 20_000
_OPENBB_ROW_LIMIT_KEYS = (
    "limit",
    "max_results",
    "max_rows",
    "page_size",
    "pageSize",
    "row_limit",
    "count",
)
_OPENBB_CHART_KEYS = ("chart", "include_chart")


def _default_state() -> dict[str, Any]:
    return {
        "format": DATA_SOURCE_FORMAT,
        "schema_version": DATA_SOURCE_SCHEMA_VERSION,
        "revision": 0,
        "updated_at": "",
        "openbb": {"providers": {}},
    }


def _default_credentials() -> dict[str, Any]:
    return {
        "format": CREDENTIAL_FORMAT,
        "schema_version": CREDENTIAL_SCHEMA_VERSION,
        "updated_at": "",
        "providers": {},
    }


def _state_path(workspace_root: Path | str) -> Path:
    root = Path(workspace_root).expanduser().resolve(strict=False)
    return root / WORKSPACE_DATA_SOURCE_PATH


def _credential_path() -> Path:
    return tradingcodex_home() / OPENBB_CREDENTIAL_PATH


def _runtime_root() -> Path:
    return tradingcodex_home() / OPENBB_RUNTIME_PATH


def _validate_provider_id(value: Any) -> str:
    provider = str(value or "").strip().lower()
    if _PROVIDER_RE.fullmatch(provider) is None:
        raise ValueError("provider must match [a-z][a-z0-9_-]{0,63}")
    return provider


def _validate_slot(value: Any) -> str:
    slot = str(value or "").strip().lower()
    if _SLOT_RE.fullmatch(slot) is None:
        raise ValueError(
            "credential slot must be provider-prefixed and end with "
            "_api_key, _token, _client_id, _client_secret, _username, or _password"
        )
    child_name = slot.upper()
    if (
        child_name in _PROTECTED_CHILD_ENV
        or child_name in _BASE_ENV_ALLOWLIST
        or child_name.startswith(_PROTECTED_ENV_PREFIXES)
    ):
        raise ValueError("credential slot conflicts with a protected runtime variable")
    return slot


def _validate_provider_slot(provider: str, value: Any) -> str:
    slot = _validate_slot(value)
    expected_prefix = f"{provider.replace('-', '_')}_"
    if not slot.startswith(expected_prefix):
        raise ValueError(f"credential slot must start with {expected_prefix}")
    return slot


def validate_credential_ref(value: Any) -> str:
    reference = str(value or "").strip()
    if not reference.startswith("env:") or reference.count(":") != 1:
        raise ValueError("credential references must use exact env:NAME syntax; raw secrets are rejected")
    env_name = reference[4:]
    if _ENV_RE.fullmatch(env_name) is None:
        raise ValueError("credential reference environment name is invalid")
    if (
        env_name in _PROTECTED_CHILD_ENV
        or env_name in _BASE_ENV_ALLOWLIST
        or env_name.startswith(_PROTECTED_ENV_PREFIXES)
    ):
        raise ValueError("credential reference conflicts with a protected runtime variable")
    return f"env:{env_name}"


def parse_credential_assignment(value: Any) -> tuple[str, str]:
    assignment = str(value or "").strip()
    if assignment.count("=") != 1:
        raise ValueError("credential reference must use <provider-slot>=env:<ENV_NAME>")
    slot, reference = assignment.split("=", 1)
    return _validate_slot(slot), validate_credential_ref(reference)


def _read_state(workspace_root: Path | str) -> dict[str, Any]:
    payload = read_json(_state_path(workspace_root), None)
    if payload is None:
        return _default_state()
    if (
        not isinstance(payload, dict)
        or payload.get("format") != DATA_SOURCE_FORMAT
        or payload.get("schema_version") != DATA_SOURCE_SCHEMA_VERSION
        or not isinstance(payload.get("revision"), int)
        or not isinstance(payload.get("openbb"), dict)
        or not isinstance(payload["openbb"].get("providers"), dict)
    ):
        raise ValueError("TradingCodex data-source preferences are invalid")
    providers: dict[str, Any] = payload["openbb"]["providers"]
    for provider_id, record in providers.items():
        _validate_provider_id(provider_id)
        if not isinstance(record, dict):
            raise ValueError("TradingCodex OpenBB provider preference is invalid")
        if str(record.get("declared_access") or "") not in DECLARED_ACCESS_VALUES:
            raise ValueError("TradingCodex OpenBB declared access is invalid")
        if str(record.get("auto_use") or "") not in AUTO_USE_VALUES:
            raise ValueError("TradingCodex OpenBB auto-use policy is invalid")
        kinds = record.get("data_kinds")
        if not isinstance(kinds, list) or any(str(item) not in DATA_KINDS for item in kinds):
            raise ValueError("TradingCodex OpenBB data-kind preference is invalid")
    return payload


def _read_credentials() -> dict[str, Any]:
    payload = read_json(_credential_path(), None)
    if payload is None:
        return _default_credentials()
    if (
        not isinstance(payload, dict)
        or payload.get("format") != CREDENTIAL_FORMAT
        or payload.get("schema_version") != CREDENTIAL_SCHEMA_VERSION
        or not isinstance(payload.get("providers"), dict)
    ):
        raise ValueError("TradingCodex data-source credential references are invalid")
    for provider_id, record in payload["providers"].items():
        _validate_provider_id(provider_id)
        references = record.get("credential_refs") if isinstance(record, dict) else None
        if not isinstance(references, dict):
            raise ValueError("TradingCodex provider credential references are invalid")
        for slot, reference in references.items():
            _validate_provider_slot(provider_id, slot)
            validate_credential_ref(reference)
    return payload


def _write_state(workspace_root: Path | str, state: dict[str, Any]) -> None:
    path = _state_path(workspace_root)
    _assert_no_symlink_path(path, stop=Path(workspace_root).resolve(strict=False))
    atomic_write_text(path, json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _write_credentials(credentials: dict[str, Any]) -> None:
    path = _credential_path()
    _assert_no_symlink_path(path, stop=tradingcodex_home())
    atomic_write_text(path, json.dumps(credentials, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    if os.name != "nt":
        path.chmod(0o600)


def _assert_no_symlink_path(path: Path, *, stop: Path) -> None:
    stop = stop.resolve(strict=False)
    candidate = path
    while candidate != stop:
        if candidate.is_symlink():
            raise ValueError(f"TradingCodex state path must not traverse a symlink: {candidate}")
        if candidate.parent == candidate:
            raise ValueError("TradingCodex state path escapes its ownership root")
        candidate = candidate.parent


def _bump_state(state: dict[str, Any]) -> None:
    state["revision"] = int(state.get("revision") or 0) + 1
    state["updated_at"] = now_iso()


def _default_auto_use(access: str, *, observed_access: str = "unprobed") -> str:
    if access == "free":
        return "allow"
    if access == "keyless" and observed_access == "callable":
        return "allow"
    return "ask"


def configure_openbb_provider(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    provider = _validate_provider_id(args.get("provider"))
    access = str(args.get("access") or "").strip().lower()
    if access not in DECLARED_ACCESS_VALUES:
        raise ValueError(f"access must be one of: {', '.join(sorted(DECLARED_ACCESS_VALUES))}")
    assignments = args.get("credential_refs") or []
    parsed = dict(parse_credential_assignment(item) for item in assignments)
    for slot in parsed:
        _validate_provider_slot(provider, slot)
    if access == "keyless" and parsed:
        raise ValueError("keyless providers must not declare credential references")
    state_path = _state_path(workspace_root)
    credential_path = _credential_path()
    with exclusive_file_lock(state_path, timeout_seconds=10), exclusive_file_lock(credential_path, timeout_seconds=10):
        state = _read_state(workspace_root)
        credentials = _read_credentials()
        providers = state["openbb"]["providers"]
        current = dict(providers.get(provider) or {})
        previous_access = str(current.get("declared_access") or "")
        access_changed = bool(previous_access and previous_access != access)
        credentials_changed = bool(parsed)
        observed_access = (
            "unprobed"
            if access_changed or credentials_changed
            else str(current.get("observed_access") or "unprobed")
        )
        previous_auto_use = str(current.get("auto_use") or "")
        if not current:
            auto_use = _default_auto_use(access, observed_access=observed_access)
        elif access_changed and access in {"paid", "unknown", "keyless"}:
            # Changing the declared cost/access class must never carry an old
            # automatic-use grant into a more restrictive or unverified class.
            auto_use = "deny" if previous_auto_use == "deny" else "ask"
        elif access == "keyless" and observed_access != "callable" and previous_auto_use == "allow":
            auto_use = "ask"
        else:
            auto_use = previous_auto_use or _default_auto_use(access, observed_access=observed_access)
        current.update(
            {
                "declared_access": access,
                "data_kinds": sorted(set(current.get("data_kinds") or [])),
                "auto_use": auto_use,
                "secondary_consent": bool(current.get("secondary_consent", False)),
                "enabled": bool(current.get("enabled", False)),
                "observed_access": observed_access,
                "updated_at": now_iso(),
            }
        )
        providers[provider] = current
        credential_record = dict(credentials["providers"].get(provider) or {})
        references = dict(credential_record.get("credential_refs") or {})
        if access == "keyless" and references:
            raise ValueError(
                "clear configured credential references before declaring a provider keyless"
            )
        references.update(parsed)
        credentials["providers"][provider] = {
            "credential_refs": dict(sorted(references.items())),
            "updated_at": now_iso(),
        }
        credentials["updated_at"] = now_iso()
        _bump_state(state)
        _write_credentials(credentials)
        _write_state(workspace_root, state)
    return get_data_source_status(workspace_root, {"provider": provider})


def enable_openbb_provider(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    provider = _validate_provider_id(args.get("provider"))
    kinds = args.get("data_kinds") or []
    normalized_kinds = sorted({str(item).strip().lower().replace("-", "_") for item in kinds})
    if not normalized_kinds or any(item not in DATA_KINDS for item in normalized_kinds):
        raise ValueError(f"data-kind must be one of: {', '.join(sorted(DATA_KINDS))}")
    state_path = _state_path(workspace_root)
    with exclusive_file_lock(state_path, timeout_seconds=10):
        state = _read_state(workspace_root)
        providers = state["openbb"]["providers"]
        if provider not in providers:
            raise ValueError(f"configure OpenBB provider before enabling it: {provider}")
        record = providers[provider]
        auto_use = str(args.get("auto_use") or "").strip().lower()
        if not auto_use:
            auto_use = _default_auto_use(
                str(record["declared_access"]),
                observed_access=str(record.get("observed_access") or "unprobed"),
            )
        if auto_use not in AUTO_USE_VALUES:
            raise ValueError(f"auto-use must be one of: {', '.join(sorted(AUTO_USE_VALUES))}")
        if (
            auto_use == "allow"
            and record["declared_access"] == "keyless"
            and str(record.get("observed_access") or "unprobed") != "callable"
        ):
            raise PermissionError(
                "keyless OpenBB providers require a successful probe before --auto-use allow"
            )
        secondary_consent = bool(args.get("secondary_consent", False) or record.get("secondary_consent", False))
        if provider in SECONDARY_PROVIDER_IDS and not secondary_consent:
            raise PermissionError(f"{provider} requires explicit --secondary-consent")
        record.update(
            {
                "auto_use": auto_use,
                "data_kinds": sorted(set(record.get("data_kinds") or []).union(normalized_kinds)),
                "enabled": True,
                "secondary_consent": secondary_consent,
                "updated_at": now_iso(),
            }
        )
        _bump_state(state)
        _write_state(workspace_root, state)
    return get_data_source_status(workspace_root, {"provider": provider})


def disable_openbb_provider(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    provider_value = str(args.get("provider") or "").strip()
    disable_all = bool(args.get("all"))
    if not disable_all and not provider_value:
        raise ValueError("provider or --all is required")
    provider = _validate_provider_id(provider_value) if provider_value else ""
    state_path = _state_path(workspace_root)
    with exclusive_file_lock(state_path, timeout_seconds=10):
        state = _read_state(workspace_root)
        providers = state["openbb"]["providers"]
        targets = sorted(providers) if disable_all else [provider]
        if not disable_all and provider not in providers:
            raise ValueError(f"OpenBB provider is not configured: {provider}")
        for target in targets:
            providers[target]["enabled"] = False
            providers[target]["updated_at"] = now_iso()
        _bump_state(state)
        _write_state(workspace_root, state)
    return get_data_source_status(workspace_root, {})


def clear_openbb_credential_ref(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    provider = _validate_provider_id(args.get("provider"))
    slot = _validate_provider_slot(provider, args.get("slot"))
    state_path = _state_path(workspace_root)
    credential_path = _credential_path()
    with exclusive_file_lock(state_path, timeout_seconds=10), exclusive_file_lock(credential_path, timeout_seconds=10):
        state = _read_state(workspace_root)
        credentials = _read_credentials()
        record = credentials["providers"].get(provider)
        if not isinstance(record, dict) or slot not in (record.get("credential_refs") or {}):
            raise ValueError(f"credential reference is not configured: {provider}/{slot}")
        references = record["credential_refs"]
        del references[slot]
        if references:
            record["updated_at"] = now_iso()
        else:
            credentials["providers"].pop(provider, None)
        credentials["updated_at"] = now_iso()
        _bump_state(state)
        _write_credentials(credentials)
        _write_state(workspace_root, state)
    return get_data_source_status(workspace_root, {"provider": provider})


def _enabled_providers(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        provider: record
        for provider, record in state["openbb"]["providers"].items()
        if bool(record.get("enabled"))
    }


def _credential_env_names(state: dict[str, Any], credentials: dict[str, Any]) -> list[str]:
    result: set[str] = set()
    for provider in _enabled_providers(state):
        references = (credentials["providers"].get(provider) or {}).get("credential_refs") or {}
        for reference in references.values():
            validated = validate_credential_ref(reference)
            result.add(validated[4:])
    return sorted(result)


def openbb_projection_template_values(workspace_root: Path | str) -> dict[str, str]:
    state = _read_state(workspace_root)
    credentials = _read_credentials()
    enabled = bool(_enabled_providers(state))
    return {
        "OPENBB_MCP_COMMAND_TOML": json.dumps(str(Path(sys.executable).absolute()), ensure_ascii=False),
        "OPENBB_MCP_ENABLED_TOML": "true" if enabled else "false",
        "OPENBB_MCP_ENV_VARS_TOML": json.dumps(_credential_env_names(state, credentials), ensure_ascii=False),
        "OPENBB_MCP_ARGS_TOML": json.dumps(
            ["-m", "tradingcodex_cli", "data-sources", "openbb", "serve"],
            ensure_ascii=False,
        ),
    }


def write_openbb_projection_receipt(
    workspace_root: Path | str,
    *,
    generated_at: str,
    command: str,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve(strict=False)
    state = _read_state(root)
    credentials = _read_credentials()
    enabled = bool(_enabled_providers(state))
    payload = {
        "format": PROJECTION_FORMAT,
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "generated_at": generated_at,
        "enabled": enabled,
        "configuration_revision": state["revision"],
        "configuration_digest": _configuration_digest(state, credentials),
        "credential_env_names": _credential_env_names(state, credentials),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
    }
    path = root / OPENBB_PROJECTION_PATH
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return payload


def _compatibility_path() -> Path:
    return _runtime_root() / "compatibility-receipt.json"


def _loaded_path(workspace_root: Path | str) -> Path:
    manifest = read_workspace_manifest(Path(workspace_root).resolve(strict=False))
    workspace_id = str(manifest.get("workspace_id") or stable_hash(str(Path(workspace_root).resolve()))[:24])
    return _runtime_root() / "loaded" / f"{workspace_id}.json"


def _read_receipt(path: Path) -> dict[str, Any]:
    payload = read_json(path, {}) or {}
    return payload if isinstance(payload, dict) else {}


def _runtime_status() -> tuple[str, dict[str, Any]]:
    receipt = _read_receipt(_compatibility_path())
    if not receipt:
        return "missing", {}
    if receipt.get("format") != COMPATIBILITY_FORMAT or receipt.get("schema_version") != COMPATIBILITY_SCHEMA_VERSION:
        return "drifted", receipt
    if receipt.get("status") != "compatible":
        return "incompatible", receipt
    metadata = receipt.get("package_metadata")
    resolved_versions = dict(receipt.get("resolved_versions") or {})
    route_map = receipt.get("route_map")
    required_digests = ("package_metadata_digest", "tool_digest", "schema_digest", "route_digest")
    if (
        receipt.get("receipt_hash")
        != stable_hash({key: value for key, value in receipt.items() if key != "receipt_hash"})
        or not receipt.get("license_verified")
        or not isinstance(metadata, list)
        or any(not isinstance(item, dict) for item in metadata)
        or {str(item.get("name") or "") for item in metadata if isinstance(item, dict)}
        != {"openbb", "openbb-mcp-server"}
        or any(str(item.get("license") or "").upper() != "AGPL-3.0-ONLY" for item in metadata)
        or any(
            re.fullmatch(r"[0-9a-f]{64}", str(item.get(field) or "")) is None
            for item in metadata
            if isinstance(item, dict)
            for field in ("metadata_sha256", "record_sha256", "installed_files_sha256")
        )
        or any(re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(field) or "")) is None for field in required_digests)
        or stable_hash(metadata) != receipt.get("package_metadata_digest")
        or resolved_versions
        != {
            str(item.get("name") or ""): str(item.get("version") or "")
            for item in metadata
            if isinstance(item, dict)
        }
        or not isinstance(route_map, list)
        or stable_hash(route_map)
        != (receipt.get("route_map_digest") or receipt.get("route_digest"))
        or str((receipt.get("server_info") or {}).get("version") or "")
        != str(resolved_versions.get("openbb-mcp-server") or "")
    ):
        return "drifted", receipt
    return "ready", receipt


def validate_openbb_compatibility_receipt_hash(
    workspace_root: Path | str,
    receipt_hash: Any,
) -> dict[str, Any]:
    # Keep the workspace argument in the public contract even though the
    # compatibility runtime is checkout-home scoped. Callers must not validate
    # a receipt without an explicit workspace authority boundary.
    _ = Path(workspace_root).resolve(strict=False)
    expected_hash = str(receipt_hash or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise ValueError("OpenBB compatibility receipt hash must be a SHA-256 digest")
    runtime, receipt = _runtime_status()
    if runtime != "ready":
        raise ValueError("OpenBB compatibility receipt is not ready and validated")
    if str(receipt.get("receipt_hash") or "") != expected_hash:
        raise ValueError("OpenBB compatibility receipt hash does not match the validated runtime")
    return {
        "status": "ready",
        "receipt_hash": expected_hash,
        "resolved_versions": dict(receipt.get("resolved_versions") or {}),
        "package_metadata_digest": str(receipt.get("package_metadata_digest") or ""),
        "tool_digest": str(receipt.get("tool_digest") or ""),
        "schema_digest": str(receipt.get("schema_digest") or ""),
        "route_digest": str(receipt.get("route_digest") or ""),
    }


def _process_is_alive(process_id: Any) -> bool:
    try:
        pid = int(process_id)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                handle,
                ctypes.byref(exit_code),
            ):
                return False
            return int(exit_code.value) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _loaded_processes(workspace_root: Path | str) -> list[dict[str, Any]]:
    loaded = _read_receipt(_loaded_path(workspace_root))
    records = loaded.get("processes")
    if isinstance(records, list):
        candidates = [record for record in records if isinstance(record, dict)]
    elif loaded.get("process_id"):
        candidates = [loaded]
    else:
        candidates = []
    return [record for record in candidates if _process_is_alive(record.get("process_id"))]


def _projection_status(workspace_root: Path | str, state: dict[str, Any], credentials: dict[str, Any]) -> str:
    desired_enabled = bool(_enabled_providers(state))
    projection = _read_receipt(Path(workspace_root).resolve(strict=False) / OPENBB_PROJECTION_PATH)
    desired_digest = _configuration_digest(state, credentials)
    live_processes = _loaded_processes(workspace_root)
    if not projection and not desired_enabled:
        return "restart_required" if live_processes else "absent"
    projection_matches = not (
        projection.get("format") != PROJECTION_FORMAT
        or projection.get("schema_version") != PROJECTION_SCHEMA_VERSION
        or bool(projection.get("enabled")) != desired_enabled
        or int(projection.get("configuration_revision", -1)) != int(state["revision"])
        or str(projection.get("configuration_digest") or "") != desired_digest
        or projection.get("credential_env_names") != _credential_env_names(state, credentials)
    )
    if not projection_matches:
        return "restart_required"
    if not desired_enabled:
        return "restart_required" if live_processes else "absent"
    if any(str(record.get("configuration_digest") or "") != desired_digest for record in live_processes):
        return "restart_required"
    return "current" if live_processes else "restart_required"


def _configuration_digest(state: dict[str, Any], credentials: dict[str, Any]) -> str:
    enabled = _enabled_providers(state)
    material_providers = {
        provider: {
            "declared_access": str(record.get("declared_access") or ""),
            "data_kinds": sorted(record.get("data_kinds") or []),
            "auto_use": str(record.get("auto_use") or "deny"),
            "secondary_consent": bool(record.get("secondary_consent")),
            "enabled": True,
        }
        for provider, record in sorted(enabled.items())
    }
    references = {
        provider: dict(sorted(((credentials["providers"].get(provider) or {}).get("credential_refs") or {}).items()))
        for provider in sorted(enabled)
    }
    return stable_hash({"providers": material_providers, "credential_refs": references})


def _credential_status(provider: str, record: dict[str, Any], credentials: dict[str, Any]) -> tuple[str, dict[str, str]]:
    references = dict(((credentials["providers"].get(provider) or {}).get("credential_refs") or {}))
    if record.get("declared_access") == "keyless":
        return "not_required", {}
    if not references:
        return "ref_missing", {}
    states = {
        slot: ("available" if os.environ.get(validate_credential_ref(reference)[4:]) else "env_missing")
        for slot, reference in sorted(references.items())
    }
    return ("available" if all(value == "available" for value in states.values()) else "env_missing"), states


def get_data_source_status(workspace_root: Path | str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    request = args or {}
    provider_filter = str(request.get("provider") or "").strip().lower()
    if provider_filter:
        provider_filter = _validate_provider_id(provider_filter)
    data_kind_filter = str(request.get("data_kind") or "").strip().lower().replace("-", "_")
    if data_kind_filter and data_kind_filter not in DATA_KINDS:
        raise ValueError(f"data_kind must be one of: {', '.join(sorted(DATA_KINDS))}")
    state = _read_state(workspace_root)
    credentials = _read_credentials()
    runtime, receipt = _runtime_status()
    projection = _projection_status(workspace_root, state, credentials)
    providers: list[dict[str, Any]] = []
    for provider, record in sorted(state["openbb"]["providers"].items()):
        if provider_filter and provider != provider_filter:
            continue
        credential_state, credential_slots = _credential_status(provider, record, credentials)
        references = dict(((credentials["providers"].get(provider) or {}).get("credential_refs") or {}))
        if record.get("declared_access") == "keyless":
            credential_slot_hints: list[str] = []
            credential_slot_hint_source = "not_required"
        elif references:
            credential_slot_hints = sorted(references)
            credential_slot_hint_source = "configured"
        else:
            credential_slot_hints = [f"{provider.replace('-', '_')}_api_key"]
            credential_slot_hint_source = "provider_name_convention_unverified"
        providers.append(
            {
                "provider": provider,
                "enabled": bool(record.get("enabled")),
                "declared_access": record.get("declared_access"),
                "credentials": credential_state,
                "credential_slots": credential_slots,
                "credential_slot_hints": credential_slot_hints,
                "credential_slot_hint_source": credential_slot_hint_source,
                "credential_refs": {slot: validate_credential_ref(ref) for slot, ref in sorted(references.items())},
                "data_kinds": list(record.get("data_kinds") or []),
                "auto_use": record.get("auto_use"),
                "secondary_consent": bool(record.get("secondary_consent")),
                "runtime": runtime,
                "projection": projection,
                "observed_access": record.get("observed_access") or "unprobed",
                "last_probe": dict(record.get("last_probe") or {}),
            }
        )
    try:
        from tradingcodex_service.application.official_sources import get_official_source_plan, official_source_catalog

        official_catalog = official_source_catalog()
        official_summary = {
            "available": True,
            "catalog_digest": official_catalog["catalog_digest"],
            "source_count": len(official_catalog["sources"]),
            "data_kinds": official_catalog["data_kinds"],
        }
        if data_kind_filter:
            official_plan = get_official_source_plan(workspace_root, {"data_kind": data_kind_filter})
            official_summary["matching_source_ids"] = list(official_plan.get("fallback_order") or [])
            official_summary["coverage_gap"] = str(official_plan.get("coverage_gap") or "")
    except (ImportError, ValueError, KeyError, TypeError):
        official_summary = {"available": False, "catalog_digest": "", "source_count": 0, "data_kinds": []}
    all_routes = (
        [route for route in (receipt.get("route_map") or []) if isinstance(route, dict)]
        if runtime == "ready"
        else []
    )
    matching_routes = [
        route
        for route in all_routes
        if not data_kind_filter or data_kind_filter in (route.get("data_kinds") or [])
    ]
    route_limit = 20 if data_kind_filter else 10
    safe_receipt = {
        "status": receipt.get("status") or "absent",
        "validation_status": runtime,
        "failure_code": str(receipt.get("failure_code") or ""),
        "checked_at": receipt.get("checked_at") or "",
        "requested_packages": list(receipt.get("requested_packages") or []),
        "resolved_versions": dict(receipt.get("resolved_versions") or {}),
        "server_info": dict(receipt.get("server_info") or {}),
        "license_declaration": receipt.get("license_declaration") or "",
        "license_verified": bool(receipt.get("license_verified", False)),
        "package_metadata": list(receipt.get("package_metadata") or []) if runtime == "ready" else [],
        "package_metadata_digest": receipt.get("package_metadata_digest") or "",
        "tool_digest": receipt.get("tool_digest") or "",
        "schema_digest": receipt.get("schema_digest") or "",
        "route_digest": receipt.get("route_digest") or "",
        "route_map_digest": receipt.get("route_map_digest") or "",
        "route_categories": list(receipt.get("route_categories") or []),
        "version_drift": bool(receipt.get("version_drift", False)),
        "route_map": matching_routes[:route_limit],
        "route_map_truncated": bool(receipt.get("route_map_truncated", False)) or len(matching_routes) > route_limit,
        "route_map_requires_data_kind_for_full_view": not bool(data_kind_filter) and len(all_routes) > route_limit,
        "receipt_hash": str(receipt.get("receipt_hash") or "") if runtime == "ready" else "",
        "package_metadata_drift": bool(receipt.get("package_metadata_drift", False)),
        "tool_drift": bool(receipt.get("tool_drift", False)),
        "schema_drift": bool(receipt.get("schema_drift", False)),
        "route_drift": bool(receipt.get("route_drift", False)),
    }
    launcher = workspace_launcher_command()
    enabled = bool(_enabled_providers(state))
    actions: list[str] = []
    if runtime == "missing" and enabled:
        actions.append(f"{launcher} data-sources openbb provision")
    if projection == "restart_required":
        actions.extend(
            [
                f"{launcher} update --skip-refresh --no-doctor",
                "Fully quit and restart Codex, then start a new task; restarting the Django service does not reload OpenBB credentials.",
            ]
        )
    return {
        "schema_version": 1,
        "integration": "openbb",
        "data_kind": data_kind_filter,
        "opt_in": True,
        "enabled": enabled,
        "configuration_revision": state["revision"],
        "runtime": runtime,
        "projection": projection,
        "providers": providers,
        "compatibility_receipt": safe_receipt,
        "official_sources": official_summary,
        "recommended_actions": actions,
        "secret_policy": "credential references and environment-variable names only; raw values are never returned",
    }


def _openbb_runtime_environment(*, include_credentials: bool, workspace_root: Path | str | None = None) -> dict[str, str]:
    root = _runtime_root()
    isolated_home = root / "isolated-home"
    cache = root / "uv-cache"
    for path in (root, isolated_home, cache, root / "loaded"):
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("OpenBB runtime directories must not be symlinks")
    environment = {key: value for key in _BASE_ENV_ALLOWLIST if (value := os.environ.get(key))}
    environment.update(
        {
            "HOME": str(isolated_home),
            "UV_CACHE_DIR": str(cache),
            "UV_NO_CONFIG": "1",
            "XDG_CACHE_HOME": str(isolated_home / ".cache"),
            "XDG_CONFIG_HOME": str(isolated_home / ".config"),
            "XDG_DATA_HOME": str(isolated_home / ".local" / "share"),
        }
    )
    if os.name == "nt":
        environment["USERPROFILE"] = str(isolated_home)
    if include_credentials:
        if workspace_root is None:
            raise ValueError("workspace root is required for OpenBB credential projection")
        state = _read_state(workspace_root)
        credentials = _read_credentials()
        projected: dict[str, str] = {}
        for provider in _enabled_providers(state):
            references = ((credentials["providers"].get(provider) or {}).get("credential_refs") or {})
            for slot, reference in references.items():
                child_name = _validate_provider_slot(provider, slot).upper()
                source_name = validate_credential_ref(reference)[4:]
                value = os.environ.get(source_name)
                if not value:
                    continue
                if child_name in projected and projected[child_name] != value:
                    raise ValueError(f"conflicting OpenBB credential slot: {slot}")
                projected[child_name] = value
        environment.update(projected)
    return environment


def _uvx_path() -> str:
    executable = shutil.which("uvx")
    if not executable:
        raise ValueError("uvx is required; install uv before provisioning the optional OpenBB integration")
    return str(Path(executable).absolute())


def _compatibility_command(*, refresh: bool) -> list[str]:
    return [
        _uvx_path(),
        *(["--refresh"] if refresh else []),
        "--from",
        "openbb-mcp-server",
        "--with",
        "openbb",
        "openbb-mcp",
        "--help",
    ]


def _write_compatibility_receipt(payload: dict[str, Any]) -> None:
    path = _compatibility_path()
    body = {key: value for key, value in payload.items() if key != "receipt_hash"}
    body["receipt_hash"] = stable_hash(body)
    atomic_write_text(path, json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    if os.name != "nt":
        path.chmod(0o600)


def _quarantine_compatibility_receipt(existing: dict[str, Any], failure_code: str) -> None:
    resolved = dict(existing.get("resolved_versions") or {})
    safe_versions = {
        name: str(resolved.get(name) or "")[:80]
        for name in ("openbb", "openbb-mcp-server")
        if str(resolved.get(name) or "")
    }
    _write_compatibility_receipt(
        {
            "format": COMPATIBILITY_FORMAT,
            "schema_version": COMPATIBILITY_SCHEMA_VERSION,
            "status": "quarantined",
            "checked_at": now_iso(),
            "refresh_session_sha256": _refresh_session_hash(),
            "requested_packages": ["openbb-mcp-server@latest", "openbb@latest"],
            "resolved_versions": safe_versions,
            "failure_code": failure_code,
        }
    )


def _refresh_session_hash() -> str:
    session_key = next(
        (
            value
            for name in ("CODEX_SESSION_ID", "CODEX_THREAD_ID", "CODEX_TASK_ID", "CODEX_CONVERSATION_ID")
            if (value := str(os.environ.get(name) or "").strip())
        ),
        f"parent-process:{os.getppid()}",
    )
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()


def _package_metadata() -> list[dict[str, Any]]:
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv metadata inspection is unavailable")
    script = """import hashlib
import importlib.metadata as metadata
import json

result = []
for name in ("openbb-mcp-server", "openbb"):
    distribution = metadata.distribution(name)
    record_entries = sorted(
        (str(item), str(getattr(item, "hash", "") or ""), str(getattr(item, "size", "") or ""))
        for item in (distribution.files or ())
    )
    installed_entries = []
    for item in (distribution.files or ()):
        if ".." in item.parts:
            continue
        path = distribution.locate_file(item)
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        installed_entries.append((str(item), digest.hexdigest(), path.stat().st_size))
    result.append({
        "name": name,
        "version": distribution.version,
        "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "",
        "origin": distribution.metadata.get("Home-page") or next(iter(distribution.metadata.get_all("Project-URL") or []), ""),
        "metadata_sha256": hashlib.sha256(str(sorted(distribution.metadata.items())).encode()).hexdigest(),
        "record_sha256": hashlib.sha256(json.dumps(record_entries, separators=(",", ":")).encode()).hexdigest(),
        "installed_files_sha256": hashlib.sha256(json.dumps(sorted(installed_entries), separators=(",", ":")).encode()).hexdigest(),
    })
print(json.dumps(result, separators=(",", ":")))
"""
    result = subprocess.run(
        [
            str(Path(uv).absolute()),
            "run",
            "--no-project",
            "--isolated",
            "--with",
            "openbb-mcp-server",
            "--with",
            "openbb",
            "python",
            "-c",
            script,
        ],
        cwd=_runtime_root(),
        env=_openbb_runtime_environment(include_credentials=False),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("OpenBB package metadata inspection failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenBB package metadata inspection returned invalid data") from exc
    if not isinstance(payload, list) or {item.get("name") for item in payload if isinstance(item, dict)} != {
        "openbb-mcp-server",
        "openbb",
    }:
        raise ValueError("OpenBB package metadata inspection is incomplete")
    sanitized: list[dict[str, Any]] = []
    for item in payload:
        license_value = str(item.get("license") or "").strip()
        if license_value.upper() != "AGPL-3.0-ONLY":
            raise ValueError("OpenBB package license metadata is incompatible")
        package_name = str(item.get("name") or "")
        origin = f"https://pypi.org/project/{package_name}/"
        sanitized.append(
            {
                "name": package_name,
                "version": str(item.get("version") or "")[:80],
                "license": license_value[:120],
                "origin": origin,
                "metadata_sha256": str(item.get("metadata_sha256") or "")[:64],
                "record_sha256": str(item.get("record_sha256") or "")[:64],
                "installed_files_sha256": str(item.get("installed_files_sha256") or "")[:64],
            }
        )
        if any(
            re.fullmatch(r"[0-9a-f]{64}", sanitized[-1][field]) is None
            for field in ("metadata_sha256", "record_sha256", "installed_files_sha256")
        ):
            raise ValueError("OpenBB installed-distribution RECORD digest is invalid")
    return sorted(sanitized, key=lambda item: item["name"])


def _inspect_openbb_protocol(
    workspace_root: Path | str,
    resolved_versions: dict[str, str],
) -> dict[str, Any]:
    process = subprocess.Popen(
        _openbb_server_command(workspace_root, resolved_versions=resolved_versions),
        cwd=_runtime_root(),
        env=_openbb_runtime_environment(include_credentials=False),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        session = _RpcSession(process)
        initialized = session.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "tradingcodex-openbb-compat", "version": TRADINGCODEX_VERSION},
            },
            timeout=45,
        )
        if initialized.get("error") or not isinstance(initialized.get("result"), dict):
            raise ValueError("OpenBB MCP initialize failed")
        session.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        listed = session.request("tools/list", {}, timeout=45)
        tools = ((listed.get("result") or {}).get("tools") or []) if isinstance(listed.get("result"), dict) else []
        filtered_tools = [
            tool
            for tool in tools
            if isinstance(tool, dict)
            and _tool_name_allowed(str(tool.get("name") or ""), set(_allowed_categories(_read_state(workspace_root))))
        ]
        names = sorted(str(tool.get("name") or "") for tool in filtered_tools)
        if not set(_OPENBB_ADMIN_TOOLS).issubset(names):
            raise ValueError("OpenBB MCP read-only discovery tools are unavailable")
        route_receipts: list[dict[str, Any]] = []
        for category in _allowed_categories(_read_state(workspace_root)):
            if category == "admin":
                continue
            response = session.request(
                "tools/call",
                {"name": "available_tools", "arguments": {"category": category}},
                timeout=45,
            )
            if response.get("error"):
                raise ValueError("OpenBB MCP route discovery failed")
            route_receipts.append({"category": category, "result": response.get("result")})
        init_result = initialized["result"]
        server_info = init_result.get("serverInfo") if isinstance(init_result.get("serverInfo"), dict) else {}
        package_server_version = str(resolved_versions.get("openbb-mcp-server") or "")
        protocol_server_version = str(server_info.get("version") or "")
        if not protocol_server_version or protocol_server_version != package_server_version:
            raise ValueError("OpenBB MCP protocol server version differs from the inspected package")
        full_route_map, _ = _build_route_map(
            route_receipts,
            _read_state(workspace_root),
            max_routes=None,
        )
        route_map = full_route_map[:120]
        route_map_truncated = len(full_route_map) > len(route_map)
        return {
            "server_info": {
                "name": str(server_info.get("name") or "")[:120],
                "version": str(server_info.get("version") or "")[:80],
                "protocol_version": str(init_result.get("protocolVersion") or "")[:80],
            },
            "tool_digest": stable_hash(names),
            "schema_digest": stable_hash(
                [
                    {"name": tool.get("name"), "inputSchema": tool.get("inputSchema")}
                    for tool in sorted(filtered_tools, key=lambda item: str(item.get("name") or ""))
                ]
            ),
            "route_digest": stable_hash(full_route_map),
            "route_map_digest": stable_hash(route_map),
            "route_categories": [item["category"] for item in route_receipts],
            "route_map": route_map,
            "route_map_truncated": route_map_truncated,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _compatibility_scope_digest(state: dict[str, Any]) -> str:
    return stable_hash(
        {
            "categories": _allowed_categories(state),
            "enabled_provider_data_kinds": {
                provider: sorted(record.get("data_kinds") or [])
                for provider, record in sorted(_enabled_providers(state).items())
            },
        }
    )


def _ensure_openbb_compatibility(workspace_root: Path | str, *, force_refresh: bool) -> dict[str, Any]:
    runtime_root = _runtime_root()
    runtime_root.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(runtime_root / "refresh", timeout_seconds=600):
        existing = _read_receipt(_compatibility_path())
        session_hash = _refresh_session_hash()
        validated_existing: dict[str, Any] = {}
        if existing:
            runtime_state, runtime_receipt = _runtime_status()
            if runtime_state == "ready":
                validated_existing = runtime_receipt
        if existing and not force_refresh:
            if existing.get("status") == "compatible" and runtime_state != "ready":
                _quarantine_compatibility_receipt(existing, "receipt_integrity_drift")
                raise ValueError(
                    "OpenBB compatibility receipt drifted; the integration is quarantined until explicit reprovisioning"
                )
            if existing.get("status") != "compatible":
                raise ValueError(
                    "OpenBB integration is quarantined; run explicit provision to retry latest-version compatibility"
                )
            if validated_existing.get("refresh_session_sha256") == session_hash:
                return validated_existing
        checked_at = now_iso()
        base = {
            "format": COMPATIBILITY_FORMAT,
            "schema_version": COMPATIBILITY_SCHEMA_VERSION,
            "checked_at": checked_at,
            "checked_epoch": time.time(),
            "refresh_session_sha256": session_hash,
            "requested_packages": ["openbb-mcp-server@latest", "openbb@latest"],
            "resolved_versions": {},
            "transport": "stdio",
            "tool_discovery": True,
            "default_categories": ["admin"],
            "license_declaration": "AGPL-3.0-only",
            "license_verified": False,
        }
        try:
            result = subprocess.run(
                _compatibility_command(refresh=True),
                cwd=runtime_root,
                env=_openbb_runtime_environment(include_credentials=False),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            payload = {**base, "status": "quarantined", "failure_code": type(exc).__name__}
            _write_compatibility_receipt(payload)
            raise ValueError("OpenBB latest-version compatibility check failed; the integration is quarantined") from None
        help_text = result.stdout or ""
        required_flags = ("--transport", "--allowed-categories", "--default-categories", "--no-tool-discovery")
        if result.returncode != 0 or any(flag not in help_text for flag in required_flags):
            payload = {**base, "status": "quarantined", "failure_code": "incompatible_cli"}
            _write_compatibility_receipt(payload)
            raise ValueError("OpenBB latest version is incompatible; the integration is quarantined without downgrade")
        try:
            package_metadata = _package_metadata()
            resolved_versions = {item["name"]: item["version"] for item in package_metadata}
            protocol = _inspect_openbb_protocol(workspace_root, resolved_versions)
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError, queue.Empty) as exc:
            payload = {**base, "status": "quarantined", "failure_code": type(exc).__name__}
            _write_compatibility_receipt(payload)
            raise ValueError("OpenBB runtime metadata or protocol compatibility check failed; the integration is quarantined") from None
        previous_versions = dict(validated_existing.get("resolved_versions") or {})
        configuration_scope_digest = _compatibility_scope_digest(_read_state(workspace_root))
        package_metadata_digest = stable_hash(package_metadata)
        package_metadata_drift = bool(
            validated_existing.get("package_metadata_digest")
            and validated_existing.get("package_metadata_digest") != package_metadata_digest
        )
        tool_drift = bool(
            validated_existing.get("tool_digest")
            and validated_existing.get("tool_digest") != protocol["tool_digest"]
        )
        schema_drift = bool(
            validated_existing.get("schema_digest")
            and validated_existing.get("schema_digest") != protocol["schema_digest"]
        )
        route_drift = bool(
            validated_existing.get("route_digest")
            and validated_existing.get("route_digest") != protocol["route_digest"]
        )
        version_drift = bool(previous_versions and previous_versions != resolved_versions)
        same_scope = bool(
            validated_existing.get("configuration_scope_digest")
            and validated_existing.get("configuration_scope_digest") == configuration_scope_digest
        )
        if (
            validated_existing.get("status") == "compatible"
            and previous_versions
            and not version_drift
            and (
                package_metadata_drift
                or tool_drift
                or schema_drift
                or (same_scope and route_drift)
            )
        ):
            _quarantine_compatibility_receipt(existing, "same_version_compatibility_drift")
            raise ValueError(
                "OpenBB package or route schema drifted without a version/configuration change; the integration is quarantined"
            )
        payload = {
            **base,
            "status": "compatible",
            "help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
            "required_flags": list(required_flags),
            "package_metadata": package_metadata,
            "package_metadata_digest": package_metadata_digest,
            "resolved_versions": resolved_versions,
            "previous_versions": previous_versions,
            "version_drift": version_drift,
            "configuration_scope_digest": configuration_scope_digest,
            "package_metadata_drift": package_metadata_drift,
            "tool_drift": tool_drift,
            "schema_drift": schema_drift,
            "route_drift": route_drift,
            "license_verified": True,
            **protocol,
        }
        _write_compatibility_receipt(payload)
        return _read_receipt(_compatibility_path())


def provision_openbb(workspace_root: Path | str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    del args
    _ensure_openbb_compatibility(workspace_root, force_refresh=True)
    return get_data_source_status(workspace_root, {})


def _allowed_categories(state: dict[str, Any]) -> list[str]:
    mapping = {
        "bond_price": "fixedincome",
        "commodity_price": "commodity",
        "corporate_action": "equity",
        "crypto_price": "crypto",
        "energy": "economy",
        "equity_price": "equity",
        "etf_price": "equity",
        "filing": "equity",
        "fundamentals": "equity",
        "futures_price": "derivatives",
        "fx_reference": "currency",
        "labor": "economy",
        "macro": "economy",
        "news": "news",
        "options_price": "derivatives",
        "positioning": "regulators",
        "reference": "index",
        "yield_curve": "fixedincome",
    }
    categories = {"admin"}
    for record in _enabled_providers(state).values():
        categories.update(mapping[kind] for kind in record.get("data_kinds") or [] if kind in mapping)
    return sorted(categories)


def _category_for_data_kind(data_kind: str) -> str:
    mapping = {
        "bond_price": "fixedincome",
        "commodity_price": "commodity",
        "corporate_action": "equity",
        "crypto_price": "crypto",
        "energy": "economy",
        "equity_price": "equity",
        "etf_price": "equity",
        "filing": "equity",
        "fundamentals": "equity",
        "futures_price": "derivatives",
        "fx_reference": "currency",
        "labor": "economy",
        "macro": "economy",
        "news": "news",
        "options_price": "derivatives",
        "positioning": "regulators",
        "reference": "index",
        "yield_curve": "fixedincome",
    }
    return mapping[data_kind]


def _openbb_server_command(
    workspace_root: Path | str,
    *,
    resolved_versions: dict[str, str] | None = None,
) -> list[str]:
    categories = ",".join(_allowed_categories(_read_state(workspace_root)))
    versions = dict(resolved_versions or (_read_receipt(_compatibility_path()).get("resolved_versions") or {}))
    mcp_version = str(versions.get("openbb-mcp-server") or "")
    openbb_version = str(versions.get("openbb") or "")
    if not mcp_version or not openbb_version:
        raise ValueError("OpenBB compatible package versions are unavailable; provision or refresh first")
    return [
        _uvx_path(),
        "--from",
        f"openbb-mcp-server=={mcp_version}",
        "--with",
        f"openbb=={openbb_version}",
        "openbb-mcp",
        "--transport",
        "stdio",
        "--allowed-categories",
        categories,
        "--default-categories",
        "admin",
    ]


def _write_loaded_receipt(workspace_root: Path | str, principal: str) -> None:
    state = _read_state(workspace_root)
    credentials = _read_credentials()
    configuration_digest = _configuration_digest(state, credentials)
    path = _loaded_path(workspace_root)
    with exclusive_file_lock(path, timeout_seconds=10):
        existing = _read_receipt(path)
        records = existing.get("processes")
        live_processes = (
            [record for record in records if isinstance(record, dict) and _process_is_alive(record.get("process_id"))]
            if isinstance(records, list)
            else []
        )
        live_processes = [
            record
            for record in live_processes
            if int(record.get("process_id") or -1) != os.getpid()
        ]
        live_processes.append(
            {
                "loaded_at": now_iso(),
                "principal": principal,
                "process_id": os.getpid(),
                "configuration_revision": state["revision"],
                "configuration_digest": configuration_digest,
            }
        )
        live_processes.sort(key=lambda item: (str(item.get("principal") or ""), int(item.get("process_id") or 0)))
        payload = {
            "format": "tradingcodex.openbb-loaded-state",
            "schema_version": 2,
            "updated_at": now_iso(),
            "credential_env_names": _credential_env_names(state, credentials),
            "processes": live_processes,
        }
        atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        if os.name != "nt":
            path.chmod(0o600)


def _tool_name_allowed(name: str, categories: set[str]) -> bool:
    lowered = name.strip().lower()
    if lowered in _OPENBB_ADMIN_TOOLS:
        return True
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", lowered)))
    if tokens.intersection(_BLOCKED_TOOL_TOKENS):
        return False
    return any(lowered.startswith(f"{category}_") for category in categories if category != "admin")


def _tool_category(name: str, categories: set[str]) -> str:
    lowered = name.strip().lower()
    matches = [
        category
        for category in categories
        if category != "admin" and lowered.startswith(f"{category}_")
    ]
    return max(matches, key=len) if matches else ""


def _activation_names(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("tool_names")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _openbb_coordinate_values(value: Any, *, sort_items: bool = False) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    normalized = [str(item).strip().casefold() for item in raw if str(item).strip()]
    return sorted(normalized) if sort_items else normalized


def _openbb_coordinate_scalar(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text.casefold()
    date_only = len(text) == 10 and text[4:5] == "-" and text[7:8] == "-"
    if parsed.tzinfo is None:
        if date_only or parsed.time() == datetime.min.time():
            return parsed.date().isoformat()
        return parsed.isoformat().casefold()
    utc_value = parsed.astimezone(timezone.utc)
    if date_only or utc_value.time() == datetime.min.time():
        return utc_value.date().isoformat()
    return utc_value.isoformat().casefold()


def _openbb_semantic_frequency(value: Any) -> str:
    normalized = re.sub(r"[\s_-]+", "", str(value or "").strip().casefold())
    aliases = {
        "d": "1d",
        "1d": "1d",
        "1day": "1d",
        "day": "1d",
        "daily": "1d",
        "eod": "1d",
        "h": "1h",
        "1h": "1h",
        "1hour": "1h",
        "hour": "1h",
        "hourly": "1h",
        "1min": "1min",
        "minute": "1min",
        "minutely": "1min",
        "w": "1w",
        "1w": "1w",
        "1wk": "1w",
        "1week": "1w",
        "week": "1w",
        "weekly": "1w",
        "1mo": "1mo",
        "1month": "1mo",
        "month": "1mo",
        "monthly": "1mo",
        "3mo": "1q",
        "quarter": "1q",
        "quarterly": "1q",
        "1y": "1y",
        "1yr": "1y",
        "annual": "1y",
        "annually": "1y",
        "year": "1y",
        "yearly": "1y",
    }
    return aliases.get(normalized, normalized)


def _openbb_semantic_adjustment(value: Any) -> str:
    if value is True:
        return "adjusted"
    if value is False:
        return "unadjusted"
    normalized = re.sub(r"[\s_-]+", "", str(value or "").strip().casefold())
    return {
        "adjust": "adjusted",
        "adjusted": "adjusted",
        "true": "adjusted",
        "none": "unadjusted",
        "false": "unadjusted",
        "raw": "unadjusted",
        "unadjusted": "unadjusted",
    }.get(normalized, normalized)


def _openbb_semantic_call_key(tool_name: str, arguments: dict[str, Any]) -> str:
    def first(names: tuple[str, ...]) -> Any:
        return next((arguments[name] for name in names if name in arguments), "")

    material = {
        "tool": tool_name.strip().lower(),
        "provider": _openbb_coordinate_scalar(first(("provider", "provider_name"))),
        "identifiers": _openbb_coordinate_values(
            first(
                (
                    "identifiers",
                    "identifier",
                    "symbols",
                    "symbol",
                    "tickers",
                    "ticker",
                    "isin",
                    "cik",
                    "series_id",
                    "contract",
                )
            ),
            sort_items=True,
        ),
        "fields": _openbb_coordinate_values(
            first(("fields", "columns")), sort_items=True
        ),
        "start": _openbb_coordinate_scalar(
            first(("start_date", "start", "date_from"))
        ),
        "end": _openbb_coordinate_scalar(first(("end_date", "end", "date_to"))),
        "as_of": _openbb_coordinate_scalar(first(("as_of", "asof", "date"))),
        "interval": _openbb_semantic_frequency(
            first(("interval", "frequency", "period"))
        ),
        "adjustment": _openbb_semantic_adjustment(
            first(("adjustment", "adjusted"))
        ),
    }
    return stable_hash(material)


def _openbb_admin_scopes(
    tool_name: str,
    arguments: dict[str, Any],
    categories: set[str],
) -> set[tuple[str, str]]:
    """Return admin scopes within this workflow/role-session proxy instance."""

    category = str(arguments.get("category") or "").strip().lower()
    subcategory = str(
        arguments.get("subcategory") or arguments.get("sub_category") or ""
    ).strip().lower()
    if subcategory and not category:
        return set()
    if category:
        if category == "admin" or category not in categories:
            return set()
        if subcategory and _PROVIDER_RE.fullmatch(subcategory) is None:
            return set()
        if tool_name == "activate_tools":
            derived_scopes: set[tuple[str, str]] = set()
            for name in _activation_names(arguments):
                normalized = name.strip().lower()
                if _tool_category(normalized, categories) != category:
                    return set()
                if subcategory:
                    remainder = normalized.removeprefix(f"{category}_")
                    derived = next(
                        (item for item in remainder.split("_") if item), "*"
                    )
                    if derived != subcategory:
                        return set()
                else:
                    remainder = normalized.removeprefix(f"{category}_")
                    derived = next(
                        (item for item in remainder.split("_") if item), "*"
                    )
                derived_scopes.add((category, derived))
            return {(category, subcategory)} if subcategory else derived_scopes
        return {(category, subcategory or "*")}
    if tool_name != "activate_tools":
        return set()
    scopes: set[tuple[str, str]] = set()
    for name in _activation_names(arguments):
        normalized = name.strip().lower()
        scoped_category = _tool_category(normalized, categories)
        if not scoped_category:
            return set()
        remainder = normalized.removeprefix(f"{scoped_category}_")
        scoped_subcategory = next(
            (item for item in remainder.split("_") if item), "*"
        )
        scopes.add((scoped_category, scoped_subcategory))
    return scopes


def _redact_external_payload(value: Any, *, key: str = "", secret_values: tuple[str, ...] = ()) -> Any:
    if key and _SENSITIVE_KEY_RE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_external_payload(child, key=str(child_key), secret_values=secret_values)
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_external_payload(child, secret_values=secret_values) for child in value]
    if isinstance(value, tuple):
        return [_redact_external_payload(child, secret_values=secret_values) for child in value]
    if isinstance(value, str):
        safe = redact_log_text(value)
        for secret in secret_values:
            safe = safe.replace(secret, "<redacted>")
        return _SENSITIVE_VALUE_RE.sub(lambda match: f"{match.group(1) or match.group(2)}[redacted]", safe)
    return value


def _maximum_external_collection_length(value: Any) -> int:
    maximum = 0

    def visit(item: Any) -> None:
        nonlocal maximum
        if isinstance(item, str):
            stripped = item.strip()
            if stripped.startswith(("[", "{")):
                try:
                    visit(json.loads(stripped))
                except json.JSONDecodeError:
                    pass
            return
        if isinstance(item, list):
            maximum = max(maximum, len(item))
            for child in item:
                visit(child)
            return
        if isinstance(item, dict):
            for child in item.values():
                visit(child)

    visit(value)
    return maximum


def _typed_openbb_error_result(reason_code: str) -> dict[str, Any]:
    text = json.dumps(
        {"status": "terminal_gap", "reason_code": reason_code},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {"content": [{"type": "text", "text": text}], "isError": True}


class _OpenBBProxy:
    def __init__(self, workspace_root: Path, principal: str) -> None:
        self.workspace_root = workspace_root
        self.principal = principal
        state = _read_state(workspace_root)
        self.state = state
        self.categories = set(_allowed_categories(state))
        self.provider_records = _enabled_providers(state)
        self.providers = set(self.provider_records)
        self.provider_data_kinds = {
            provider: set(record.get("data_kinds") or [])
            for provider, record in self.provider_records.items()
        }
        self.provider_categories = {
            provider: {_category_for_data_kind(kind) for kind in data_kinds}
            for provider, data_kinds in self.provider_data_kinds.items()
        }
        credentials = _read_credentials()
        self.secret_values = tuple(
            sorted(
                {
                    value
                    for provider in self.providers
                    for reference in ((credentials["providers"].get(provider) or {}).get("credential_refs") or {}).values()
                    if (value := os.environ.get(validate_credential_ref(reference)[4:]))
                },
                key=len,
                reverse=True,
            )
        )
        self.pending: dict[str, str] = {}
        self.output_lock = threading.Lock()
        # One proxy instance is one workflow-bound evidence-role session. Keep
        # reservations per category/subcategory so distinct assigned scopes do
        # not consume one another's discovery or activation allowance.
        self.available_tools_scopes: set[tuple[str, str]] = set()
        self.activate_tools_scopes: set[tuple[str, str]] = set()
        self.available_tools_calls = 0
        self.activate_tools_calls = 0
        compatibility = _read_receipt(_compatibility_path())
        approved_routes = [
            route
            for route in (compatibility.get("route_map") or [])
            if isinstance(route, dict)
            and str(route.get("category") or "") in self.categories
            and _tool_name_allowed(str(route.get("tool_name") or ""), self.categories)
        ]
        self.discovered_tools: set[str] = {
            str(route.get("tool_name") or "") for route in approved_routes
        }
        self.route_parameters: dict[str, set[str]] = {
            str(route.get("tool_name") or ""): {
                str(item) for item in (route.get("parameter_names") or [])
            }
            for route in approved_routes
        }
        self.route_data_kinds: dict[str, set[str]] = {
            str(route.get("tool_name") or ""): {
                str(item) for item in (route.get("data_kinds") or [])
            }
            for route in approved_routes
        }
        self.activated_tools: set[str] = set()
        self.pending_activation_tools: dict[str, set[str]] = {}
        self.pending_discovery_categories: dict[str, str] = {}
        self.semantic_calls: set[str] = set()

    def run(self) -> int:
        child = subprocess.Popen(
            _openbb_server_command(self.workspace_root),
            cwd=_runtime_root(),
            env=_openbb_runtime_environment(include_credentials=True, workspace_root=self.workspace_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if child.stdin is None or child.stdout is None:
            child.kill()
            raise ValueError("OpenBB stdio process could not be initialized")
        reader = threading.Thread(target=self._copy_child_output, args=(child.stdout,), daemon=True)
        reader.start()
        try:
            for line in sys.stdin.buffer:
                forward, local_responses = self._filter_client_line(line)
                for response in local_responses:
                    self._write_output(response)
                if forward:
                    child.stdin.write(forward)
                    child.stdin.flush()
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        return int(child.returncode or 0)

    def _filter_client_line(self, line: bytes) -> tuple[bytes, list[bytes]]:
        try:
            payload = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return b"", []
        messages = payload if isinstance(payload, list) else [payload]
        forwarded: list[dict[str, Any]] = []
        responses: list[bytes] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            error = self._request_error(message)
            if error is not None:
                if "id" in message:
                    responses.append(self._encode({"jsonrpc": "2.0", "id": message.get("id"), "error": error}))
                continue
            if "id" in message and message.get("method"):
                pending_method = str(message["method"])
                if pending_method == "tools/call":
                    params = message.get("params") if isinstance(message.get("params"), dict) else {}
                    pending_method = f"tools/call:{str(params.get('name') or '')}"
                self.pending[str(message["id"])] = pending_method
            forwarded.append(message)
        if not forwarded:
            return b"", responses
        rendered: Any = forwarded if isinstance(payload, list) else forwarded[0]
        return self._encode(rendered), responses

    def _request_error(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = str(message.get("method") or "")
        if method not in _OPENBB_CLIENT_METHODS:
            return {"code": -32601, "message": "TradingCodex blocked an unsupported OpenBB MCP method"}
        if method != "tools/call":
            return None
        if message.get("id") is None:
            return {"code": -32600, "message": "TradingCodex requires request ids for OpenBB tool calls"}
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not _tool_name_allowed(name, self.categories):
            return {"code": -32001, "message": "TradingCodex blocked a non-read-only or unapproved OpenBB tool"}
        if name == "activate_tools":
            names = _activation_names(arguments)
            if (
                not 1 <= len(names) <= 3
                or any(not _tool_name_allowed(item, self.categories) for item in names)
                or any(item not in self.discovered_tools for item in names)
            ):
                return {"code": -32602, "message": "OpenBB activation is limited to one through three approved read-only tools"}
            scopes = _openbb_admin_scopes(name, arguments, self.categories)
            if not scopes:
                return {"code": -32602, "message": "OpenBB activation requires one bounded category/subcategory scope"}
            if scopes & self.activate_tools_scopes:
                return {
                    "code": -32002,
                    "message": "OpenBB tool activation is limited to one call per workflow, role session, and category/subcategory",
                }
            self.activate_tools_scopes.update(scopes)
            self.activate_tools_calls += 1
            self.pending_activation_tools[str(message["id"])] = set(names)
            return None
        if name == "available_tools":
            category = str(arguments.get("category") or "").strip().lower()
            if not category or category == "admin" or category not in self.categories:
                return {"code": -32602, "message": "OpenBB discovery requires one configured evidence category"}
            scopes = _openbb_admin_scopes(name, arguments, self.categories)
            if not scopes:
                return {"code": -32602, "message": "OpenBB discovery requires one bounded category/subcategory scope"}
            if scopes & self.available_tools_scopes:
                return {
                    "code": -32002,
                    "message": "OpenBB tool discovery is limited to one call per workflow, role session, and category/subcategory",
                }
            self.available_tools_scopes.update(scopes)
            self.available_tools_calls += 1
            self.pending_discovery_categories[str(message["id"])] = category
            return None
        if name in _OPENBB_ADMIN_TOOLS:
            return None
        if name not in self.discovered_tools or name not in self.activated_tools:
            return {
                "code": -32001,
                "message": "OpenBB data tools must be discovered from the validated route map and successfully activated",
            }
        provider = str(arguments.get("provider") or "").strip().lower()
        if not provider:
            return {"code": -32602, "message": "TradingCodex requires an explicit OpenBB provider"}
        if provider not in self.providers:
            return {"code": -32602, "message": "OpenBB provider is not configured and enabled for this workspace"}
        provider_record = self.provider_records[provider]
        if str(provider_record.get("auto_use") or "deny") != "allow":
            return {
                "code": -32003,
                "message": "OpenBB provider requires explicit user approval before automatic use",
            }
        if (
            provider_record.get("declared_access") == "keyless"
            and str(provider_record.get("observed_access") or "unprobed") != "callable"
        ):
            return {"code": -32003, "message": "Keyless OpenBB providers must be successfully probed before automatic use"}
        if provider in SECONDARY_PROVIDER_IDS and not bool(provider_record.get("secondary_consent")):
            return {"code": -32003, "message": "OpenBB secondary provider consent is required"}
        category = _tool_category(name, self.categories)
        if not category or category not in self.provider_categories.get(provider, set()):
            return {"code": -32602, "message": "OpenBB provider is not enabled for this tool category"}
        route_kinds = self.route_data_kinds.get(name, set())
        if not route_kinds or not route_kinds.intersection(self.provider_data_kinds.get(provider, set())):
            return {"code": -32602, "message": "OpenBB provider is not enabled for this route data kind"}
        if any(_SENSITIVE_KEY_RE.search(str(key)) for key in arguments):
            return {"code": -32602, "message": "OpenBB data calls must not carry credentials or headers"}
        if any(
            str(key).strip().lower()
            in {"destination", "file", "file_name", "filename", "filepath", "output_file", "path"}
            for key in arguments
        ):
            return {"code": -32602, "message": "OpenBB filesystem arguments are not permitted"}
        http_method = str(arguments.get("http_method") or arguments.get("method") or "GET").upper()
        if http_method not in {"GET", "HEAD"}:
            return {"code": -32602, "message": "OpenBB non-read HTTP methods are not permitted"}
        route_parameters = self.route_parameters.get(name, set())
        route_limit_keys = [key for key in _OPENBB_ROW_LIMIT_KEYS if key in route_parameters]
        all_supplied_limit_keys = [key for key in _OPENBB_ROW_LIMIT_KEYS if key in arguments]
        if any(key not in route_parameters for key in all_supplied_limit_keys):
            return {"code": -32602, "message": "OpenBB row-limit argument is not present in the validated route schema"}
        supplied_limit_keys = [key for key in route_limit_keys if key in arguments]
        if not route_limit_keys or not supplied_limit_keys:
            return {"code": -32602, "message": "OpenBB data calls require an explicit schema-supported row limit"}
        for key in supplied_limit_keys:
            value = arguments[key]
            if isinstance(value, bool):
                return {"code": -32602, "message": "OpenBB result limit must be an integer from 1 through 120"}
            try:
                normalized_limit = int(value)
            except (TypeError, ValueError):
                return {"code": -32602, "message": "OpenBB result limit must be an integer from 1 through 120"}
            if normalized_limit < 1 or normalized_limit > 120:
                return {"code": -32602, "message": "OpenBB result limit must be from 1 through 120 rows"}
        supplied_chart_keys = [key for key in _OPENBB_CHART_KEYS if key in arguments]
        if any(key not in route_parameters for key in supplied_chart_keys):
            return {"code": -32602, "message": "OpenBB chart argument is not present in the validated route schema"}
        for chart_key in (key for key in _OPENBB_CHART_KEYS if key in route_parameters):
            if chart_key not in arguments or arguments[chart_key] not in (False, "false", "False", 0):
                return {"code": -32602, "message": "OpenBB chart output must be explicitly disabled"}
        semantic_key = _openbb_semantic_call_key(name, arguments)
        if semantic_key in self.semantic_calls:
            return {
                "code": -32006,
                "message": "TradingCodex blocked a repeated OpenBB semantic data call; reuse the prior Dataset or receipt",
            }
        self.semantic_calls.add(semantic_key)
        return None

    def _copy_child_output(self, source: BinaryIO) -> None:
        for line in source:
            try:
                payload = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            filtered = self._filter_server_payload(payload)
            if filtered is not None:
                self._write_output(self._encode(filtered))

    def _filter_server_payload(self, payload: Any) -> Any:
        messages = payload if isinstance(payload, list) else [payload]
        result: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            method = self.pending.pop(str(request_id), "") if request_id is not None else ""
            activation_tools = (
                self.pending_activation_tools.pop(str(request_id), set())
                if request_id is not None
                else set()
            )
            discovery_category = (
                self.pending_discovery_categories.pop(str(request_id), "")
                if request_id is not None
                else ""
            )
            if request_id is not None and not method:
                continue
            if request_id is None:
                server_method = str(message.get("method") or "")
                if server_method not in _OPENBB_SERVER_NOTIFICATIONS:
                    continue
                message = {"jsonrpc": "2.0", "method": server_method}
            if method == "tools/list":
                response = message.get("result")
                tools = response.get("tools") if isinstance(response, dict) else None
                if isinstance(tools, list):
                    response["tools"] = [
                        tool
                        for tool in tools
                        if isinstance(tool, dict) and _tool_name_allowed(str(tool.get("name") or ""), self.categories)
                    ]
                    rendered_tools = json.dumps(response["tools"], ensure_ascii=False, separators=(",", ":"))
                    if len(response["tools"]) > 5 or len(rendered_tools) > OPENBB_RESPONSE_CHAR_LIMIT:
                        message = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32005,
                                "message": "OpenBB tool catalog exceeds the bounded TradingCodex surface",
                            },
                        }
            if method == "initialize":
                runtime_error = self._validate_server_info(message)
                if runtime_error is not None:
                    message = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": runtime_error,
                    }
            if method.startswith("tools/call:"):
                message = self._sanitize_tool_response(message)
            if method == "tools/call:available_tools":
                sanitized_result = message.get("result") if isinstance(message, dict) else None
                if not (isinstance(sanitized_result, dict) and sanitized_result.get("isError")):
                    for record in _extract_tool_records(sanitized_result):
                        tool_name = record["name"]
                        if not _tool_name_allowed(tool_name, self.categories):
                            continue
                        schema = record["inputSchema"]
                        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
                        self.discovered_tools.add(tool_name)
                        self.route_parameters[tool_name] = {str(item) for item in properties}
                        self.route_data_kinds[tool_name] = set(
                            _route_data_kinds(discovery_category, tool_name, self.state)
                        )
            if method == "tools/call:activate_tools":
                sanitized_result = message.get("result") if isinstance(message, dict) else None
                if not (isinstance(sanitized_result, dict) and sanitized_result.get("isError")):
                    self.activated_tools.update(activation_tools)
            result.append(message)
        if not result:
            return None
        return result if isinstance(payload, list) else result[0]

    def _sanitize_tool_response(self, message: dict[str, Any]) -> dict[str, Any]:
        if message.get("error") is not None:
            observed = _classify_probe_response(message)
            reason = observed if observed != "unprobed" else "openbb_provider_error"
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": _typed_openbb_error_result(reason)}
        result = message.get("result")
        if isinstance(result, dict) and result.get("isError"):
            observed = _classify_probe_response(message)
            reason = observed if observed != "unprobed" else "openbb_provider_error"
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": _typed_openbb_error_result(reason)}
        sanitized = _redact_external_payload(result, secret_values=self.secret_values)
        rendered = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"), default=str)
        if _maximum_external_collection_length(sanitized) > 120:
            sanitized = _typed_openbb_error_result("external_result_exceeds_row_limit")
        elif len(rendered) > OPENBB_RESPONSE_CHAR_LIMIT:
            sanitized = _typed_openbb_error_result("external_result_exceeds_context_limit")
        return {**message, "result": sanitized}

    def _validate_server_info(self, message: dict[str, Any]) -> dict[str, Any] | None:
        result = message.get("result") if isinstance(message.get("result"), dict) else {}
        server_info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
        runtime_state, receipt = _runtime_status()
        if runtime_state != "ready":
            _quarantine_compatibility_receipt(receipt, "receipt_integrity_drift")
            return {"code": -32004, "message": "OpenBB compatibility receipt is not usable"}
        expected_version = str((receipt.get("resolved_versions") or {}).get("openbb-mcp-server") or "")
        expected_protocol = str((receipt.get("server_info") or {}).get("protocol_version") or "")
        actual_version = str(server_info.get("version") or "")
        actual_protocol = str(result.get("protocolVersion") or "")
        if (
            not expected_version
            or actual_version != expected_version
            or (expected_protocol and actual_protocol != expected_protocol)
        ):
            quarantined = {
                **receipt,
                "status": "quarantined",
                "failure_code": "runtime_protocol_drift",
                "runtime_observation": {
                    "server_version_sha256": hashlib.sha256(actual_version.encode()).hexdigest(),
                    "protocol_version_sha256": hashlib.sha256(actual_protocol.encode()).hexdigest(),
                },
            }
            _write_compatibility_receipt(quarantined)
            return {"code": -32004, "message": "OpenBB runtime drifted from its compatibility receipt"}
        return None

    def _write_output(self, payload: bytes) -> None:
        with self.output_lock:
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()

    @staticmethod
    def _encode(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def serve_openbb(workspace_root: Path | str, args: dict[str, Any]) -> int:
    root = Path(workspace_root).resolve(strict=False)
    principal = str(args.get("principal") or "").strip()
    if principal not in OPENBB_EVIDENCE_ROLES:
        raise PermissionError("OpenBB MCP is available only to the six TradingCodex evidence roles")
    state = _read_state(root)
    if not _enabled_providers(state):
        raise PermissionError("OpenBB integration is disabled; configure and enable a provider first")
    _ensure_openbb_compatibility(root, force_refresh=False)
    _write_loaded_receipt(root, principal)
    return _OpenBBProxy(root, principal).run()


class _RpcSession:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.next_id = 1
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        if self.process.stdout is None:
            return
        for line in self.process.stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self.messages.put(payload)

    def send(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise ValueError("OpenBB probe stdio is unavailable")
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any], *, timeout: float = 20) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("OpenBB probe timed out")
            message = self.messages.get(timeout=remaining)
            if message.get("id") == request_id:
                return message


def _extract_tool_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped.startswith(("{", "[")):
                try:
                    visit(json.loads(stripped))
                except json.JSONDecodeError:
                    pass
            return
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        schema = item.get("inputSchema") or item.get("input_schema")
        if item.get("name") and isinstance(schema, dict):
            records.append({"name": str(item["name"]), "inputSchema": schema})
        for child in item.values():
            visit(child)

    visit(value)
    unique: dict[str, dict[str, Any]] = {record["name"]: record for record in records}
    return [unique[name] for name in sorted(unique)]


def _route_data_kinds(category: str, tool_name: str, state: dict[str, Any]) -> list[str]:
    configured = sorted(
        {
            kind
            for record in _enabled_providers(state).values()
            for kind in (record.get("data_kinds") or [])
            if _category_for_data_kind(kind) == category
        }
    )
    name = tool_name.lower()
    token_map = {
        "corporate_action": ("calendar", "dividend", "split"),
        "filing": ("filing", "sec"),
        "fundamentals": ("fundamental", "balance", "income", "cash"),
        "equity_price": ("price", "quote", "historical"),
        "etf_price": ("price", "quote", "historical"),
        "futures_price": ("future",),
        "options_price": ("option", "chain"),
        "labor": ("labor", "employment"),
        "energy": ("energy", "petroleum", "natural_gas"),
        "macro": ("gdp", "economic", "calendar", "inflation"),
        "yield_curve": ("yield", "curve", "rate"),
        "bond_price": ("bond", "price", "historical"),
        "positioning": ("position", "cot"),
    }
    matched = [kind for kind in configured if any(token in name for token in token_map.get(kind, (kind.split("_")[0],)))]
    return matched or configured


def _build_route_map(
    route_receipts: list[dict[str, Any]],
    state: dict[str, Any],
    *,
    max_routes: int | None = 120,
) -> tuple[list[dict[str, Any]], bool]:
    routes: list[dict[str, Any]] = []
    categories = set(_allowed_categories(state))
    for receipt in route_receipts:
        category = str(receipt.get("category") or "")
        for record in _extract_tool_records(receipt.get("result")):
            name = record["name"]
            if not _tool_name_allowed(name, categories):
                continue
            schema = record["inputSchema"]
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            parameter_names = sorted(str(item) for item in properties)
            if any(_SENSITIVE_KEY_RE.search(item) for item in parameter_names):
                continue
            routes.append(
                {
                    "category": category,
                    "data_kinds": _route_data_kinds(category, name, state),
                    "tool_name": name,
                    "required_arguments": sorted(str(item) for item in (schema.get("required") or [])),
                    "parameter_names": parameter_names,
                    "schema_sha256": stable_hash(schema),
                }
            )
    routes.sort(key=lambda item: (item["category"], item["tool_name"]))
    if max_routes is None:
        return routes, False
    return routes[:max_routes], len(routes) > max_routes


def _probe_route(
    records: list[dict[str, Any]],
    *,
    data_kind: str,
    provider: str,
    symbol: str,
    category: str,
) -> tuple[str, dict[str, Any]] | None:
    keywords = {
        "bond_price": ("price", "historical", "quote"),
        "commodity_price": ("price", "historical", "quote"),
        "corporate_action": ("calendar", "dividend", "split"),
        "crypto_price": ("price", "historical", "quote"),
        "energy": ("energy",),
        "equity_price": ("price", "historical", "quote"),
        "etf_price": ("price", "historical", "quote"),
        "filing": ("filing", "sec"),
        "fundamentals": ("fundamental", "balance", "income", "cash"),
        "futures_price": ("future", "price", "historical"),
        "fx_reference": ("currency", "exchange", "price"),
        "labor": ("labor", "employment"),
        "macro": ("gdp", "economic", "calendar"),
        "news": ("news",),
        "options_price": ("option", "chain", "price"),
        "positioning": ("position", "cot"),
        "reference": ("index", "reference"),
        "yield_curve": ("yield", "curve", "rate"),
    }[data_kind]
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for record in records:
        name = record["name"].lower()
        if not _tool_name_allowed(name, {"admin", category}):
            continue
        schema = record["inputSchema"]
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(item) for item in (schema.get("required") or [])}
        if "provider" not in properties or any(_SENSITIVE_KEY_RE.search(str(item)) for item in properties):
            continue
        limit_key = next((key for key in _OPENBB_ROW_LIMIT_KEYS if key in properties), "")
        if not limit_key:
            continue
        supported_required = {"provider", limit_key}
        arguments: dict[str, Any] = {"provider": provider}
        if "symbol" in properties and symbol:
            arguments["symbol"] = symbol
            supported_required.add("symbol")
        arguments[limit_key] = 1
        for chart_key in (key for key in _OPENBB_CHART_KEYS if key in properties):
            arguments[chart_key] = False
            supported_required.add(chart_key)
        if required - supported_required:
            continue
        score = sum(1 for keyword in keywords if keyword in name)
        candidates.append((-score, name, arguments))
    if not candidates:
        return None
    _, name, arguments = sorted(candidates)[0]
    return name, arguments


def _classify_probe_response(response: dict[str, Any]) -> str:
    error_value: Any = response.get("error")
    result = response.get("result")
    if isinstance(result, dict) and result.get("isError"):
        error_value = result
    if error_value is None:
        return "callable"
    lowered = json.dumps(error_value, ensure_ascii=False, default=str).lower()
    if any(token in lowered for token in ("rate limit", "rate_limit", "too many requests", "429")):
        return "rate_limited"
    if any(token in lowered for token in ("entitlement", "subscription", "forbidden", "plan required", "403")):
        return "entitlement_failed"
    if any(token in lowered for token in ("api key", "api_key", "auth", "unauthorized", "credential", "401")):
        return "auth_failed"
    return "unprobed"


def _validate_probe_initialization(initialized: dict[str, Any]) -> None:
    runtime_state, receipt = _runtime_status()
    result = initialized.get("result") if isinstance(initialized.get("result"), dict) else {}
    server_info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
    expected_version = str((receipt.get("resolved_versions") or {}).get("openbb-mcp-server") or "")
    expected_protocol = str((receipt.get("server_info") or {}).get("protocol_version") or "")
    if (
        runtime_state != "ready"
        or not expected_version
        or str(server_info.get("version") or "") != expected_version
        or (expected_protocol and str(result.get("protocolVersion") or "") != expected_protocol)
    ):
        _quarantine_compatibility_receipt(receipt, "probe_runtime_protocol_drift")
        raise ValueError("OpenBB probe runtime drifted from its validated compatibility receipt")


def probe_openbb_provider(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).resolve(strict=False)
    provider = _validate_provider_id(args.get("provider"))
    data_kind = str(args.get("data_kind") or "").strip().lower().replace("-", "_")
    if data_kind not in DATA_KINDS:
        raise ValueError(f"data-kind must be one of: {', '.join(sorted(DATA_KINDS))}")
    state = _read_state(root)
    record = state["openbb"]["providers"].get(provider)
    if not record or not record.get("enabled"):
        raise ValueError(f"OpenBB provider is not enabled: {provider}")
    if data_kind not in (record.get("data_kinds") or []):
        raise ValueError(f"OpenBB provider is not enabled for data kind {data_kind}: {provider}")
    credentials = _read_credentials()
    credential_state, _ = _credential_status(provider, record, credentials)
    if credential_state in {"ref_missing", "env_missing"}:
        return {
            "provider": provider,
            "data_kind": data_kind,
            "probe_status": "not_run",
            "transport": "not_started",
            "observed_access": "unprobed",
            "reason_code": credential_state,
            "provider_call_executed": False,
        }
    _ensure_openbb_compatibility(root, force_refresh=False)
    process = subprocess.Popen(
        _openbb_server_command(root),
        cwd=_runtime_root(),
        env=_openbb_runtime_environment(include_credentials=True, workspace_root=root),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    probe_status = "failed"
    observed_access = "unprobed"
    provider_call_executed = False
    route = ""
    reason_code = ""
    try:
        session = _RpcSession(process)
        initialized = session.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "tradingcodex-openbb-probe", "version": TRADINGCODEX_VERSION},
            },
            timeout=30,
        )
        if initialized.get("error"):
            raise ValueError("OpenBB initialize failed")
        _validate_probe_initialization(initialized)
        session.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        tools = session.request("tools/list", {}, timeout=30)
        tool_list = ((tools.get("result") or {}).get("tools") or []) if isinstance(tools.get("result"), dict) else []
        if not any(isinstance(tool, dict) and tool.get("name") == "available_tools" for tool in tool_list):
            raise ValueError("OpenBB discovery tools are unavailable")
        category = _category_for_data_kind(data_kind)
        discovery = session.request(
            "tools/call",
            {"name": "available_tools", "arguments": {"category": category}},
            timeout=45,
        )
        if discovery.get("error"):
            raise ValueError("OpenBB route discovery failed")
        selected = _probe_route(
            _extract_tool_records(discovery.get("result")),
            data_kind=data_kind,
            provider=provider,
            symbol=str(args.get("symbol") or "").strip(),
            category=category,
        )
        if selected is None:
            probe_status = "no_compatible_probe_route"
            reason_code = "required_arguments_unavailable_or_schema_unsupported"
        else:
            route, route_arguments = selected
            activated = session.request(
                "tools/call",
                {"name": "activate_tools", "arguments": {"tool_names": route}},
                timeout=45,
            )
            if activated.get("error"):
                raise ValueError("OpenBB probe route activation failed")
            provider_call_executed = True
            response = session.request(
                "tools/call",
                {"name": route, "arguments": route_arguments},
                timeout=60,
            )
            observed_access = _classify_probe_response(response)
            probe_status = "provider_call_complete" if observed_access == "callable" else observed_access
    except (OSError, TimeoutError, ValueError, queue.Empty):
        probe_status = "failed"
        reason_code = "transport_or_protocol_failure"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    with exclusive_file_lock(_state_path(root), timeout_seconds=10):
        state = _read_state(root)
        current = state["openbb"]["providers"].get(provider)
        if current is not None:
            current["last_probe"] = {
                "checked_at": now_iso(),
                "data_kind": data_kind,
                "status": probe_status,
                "scope": "mcp_transport_and_configuration",
                "provider_call_executed": provider_call_executed,
                "route": route,
                "reason_code": reason_code,
            }
            if provider_call_executed:
                current["observed_access"] = observed_access
            _write_state(root, state)
    return {
        "provider": provider,
        "data_kind": data_kind,
        "symbol": str(args.get("symbol") or ""),
        "probe_status": probe_status,
        "transport": "callable" if probe_status not in {"failed"} else "failed",
        "observed_access": observed_access,
        "provider_call_executed": provider_call_executed,
        "route": route,
        "reason_code": reason_code,
        "scope": "one schema-compatible provider route at limit=1; no route is guessed when required arguments are unavailable",
    }
