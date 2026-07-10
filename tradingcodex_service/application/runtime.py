from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import _safe_read, atomic_write_text, exclusive_file_lock, now_iso, sanitize_id

_RUNTIME_DB_READY = False
_RUNTIME_DB_NAME = ""
WORKSPACE_MANIFEST_REL = ".tradingcodex/workspace.json"
WORKSPACE_PROFILES_REL = ".tradingcodex/profiles.json"
DEFAULT_PROFILE_ID = "default-paper"
DEFAULT_ACCOUNT_ID = "local-paper"
DEFAULT_STRATEGY_ID = "default-strategy"
DEFAULT_BASE_CURRENCY = "USD"
# Compatibility only for manifests written before schema 2; new profiles use DEFAULT_BASE_CURRENCY.
LEGACY_BASE_CURRENCY = "KRW"
WORKSPACE_MANIFEST_SCHEMA_VERSION = 2
DEFAULT_EXECUTION_MODE = "non-live: paper/validation-only/broker-validation"
LEGACY_EXECUTION_MODES = {
    "non-live: paper/stub/broker-validation": DEFAULT_EXECUTION_MODE,
}


class RuntimeMigrationError(RuntimeError):
    """Raised when canonical runtime schema preparation cannot complete safely."""


def default_active_profile() -> dict[str, Any]:
    return {
        "profile_id": DEFAULT_PROFILE_ID,
        "portfolio_id": DEFAULT_PROFILE_ID,
        "account_id": DEFAULT_ACCOUNT_ID,
        "strategy_id": DEFAULT_STRATEGY_ID,
        "base_currency": DEFAULT_BASE_CURRENCY,
        "label": "shared central paper profile",
        "shared": True,
        "shared_explicitly_selected": True,
        "investor_profile": {},
    }


def isolated_profile_for_workspace(workspace_id: str) -> dict[str, Any]:
    suffix = sanitize_id(workspace_id)[-12:]
    profile_id = f"paper-{suffix}"
    return {
        "profile_id": profile_id,
        "portfolio_id": profile_id,
        "account_id": f"local-{suffix}",
        "strategy_id": DEFAULT_STRATEGY_ID,
        "base_currency": DEFAULT_BASE_CURRENCY,
        "label": "isolated workspace paper profile",
        "shared": False,
        "shared_explicitly_selected": False,
        "origin_workspace_id": workspace_id,
        "investor_profile": {},
    }


def tradingcodex_home() -> Path:
    return Path(os.environ.get("TRADINGCODEX_HOME", "~/.tradingcodex")).expanduser().resolve()


def tradingcodex_state_dir() -> Path:
    return tradingcodex_home() / "state"


def tradingcodex_db_path() -> Path:
    configured = os.environ.get("TRADINGCODEX_DB_NAME")
    if configured:
        return Path(configured).expanduser().resolve()
    return tradingcodex_state_dir() / "tradingcodex.sqlite3"


def workspace_manifest_path(workspace_root: Path | str) -> Path:
    return Path(workspace_root).expanduser().resolve() / WORKSPACE_MANIFEST_REL


def workspace_profiles_path(workspace_root: Path | str) -> Path:
    return Path(workspace_root).expanduser().resolve() / WORKSPACE_PROFILES_REL


def read_workspace_manifest(workspace_root: Path | str | None = None) -> dict[str, Any]:
    raw_root = workspace_root or os.environ.get("TRADINGCODEX_WORKSPACE_ROOT") or os.getcwd()
    path = workspace_manifest_path(raw_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def normalize_execution_mode(value: Any = None) -> str:
    mode = str(value or DEFAULT_EXECUTION_MODE)
    return LEGACY_EXECUTION_MODES.get(mode, mode)


def ensure_workspace_manifest(workspace_root: Path | str, project_name: str | None = None, generated_at: str | None = None) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    existing = read_workspace_manifest(root)
    created_at = str(existing.get("created_at") or generated_at or now_iso())
    workspace_id = str(existing.get("workspace_id") or f"tcxw_{uuid.uuid4().hex}")
    is_new_workspace = not isinstance(existing.get("active_profile"), dict)
    active_profile = (
        existing.get("active_profile")
        if not is_new_workspace
        else isolated_profile_for_workspace(workspace_id)
    )
    if (
        isinstance(active_profile, dict)
        and "base_currency" not in active_profile
        and int(existing.get("schema_version") or 1) < WORKSPACE_MANIFEST_SCHEMA_VERSION
    ):
        active_profile = {**active_profile, "base_currency": LEGACY_BASE_CURRENCY}
    manifest = {
        "schema_version": WORKSPACE_MANIFEST_SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "project_name": project_name or existing.get("project_name") or root.name or "tradingcodex-workspace",
        "created_at": created_at,
        "updated_at": now_iso(),
        "active_profile": normalize_active_profile(active_profile),
        "mcp_scope": "project-scoped",
        "execution_mode": normalize_execution_mode(existing.get("execution_mode")),
    }
    path = workspace_manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    if is_new_workspace:
        write_workspace_profiles(root, {manifest["active_profile"]["profile_id"]: manifest["active_profile"]})
    return manifest


def normalize_active_profile(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    base = default_active_profile()
    if isinstance(profile, dict):
        base.update({key: value for key, value in profile.items() if value not in (None, "")})
    base["profile_id"] = sanitize_id(base.get("profile_id") or base.get("portfolio_id") or DEFAULT_PROFILE_ID)
    base["portfolio_id"] = sanitize_id(base.get("portfolio_id") or base["profile_id"])
    base["account_id"] = sanitize_id(base.get("account_id") or DEFAULT_ACCOUNT_ID)
    base["strategy_id"] = sanitize_id(base.get("strategy_id") or DEFAULT_STRATEGY_ID)
    base["base_currency"] = normalize_currency_code(base.get("base_currency"))
    base["label"] = str(base.get("label") or base["profile_id"])
    base["shared"] = bool(base.get("shared"))
    investor_profile = base.get("investor_profile")
    base["investor_profile"] = investor_profile if isinstance(investor_profile, dict) else {}
    return base


def normalize_currency_code(value: Any, field: str = "currency") -> str:
    code = str(value or DEFAULT_BASE_CURRENCY).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError(f"{field} must be a three-letter currency code")
    return code


def base_currency_for_workspace(workspace_root: Path | str | None = None) -> str:
    return str(active_profile_for_workspace(workspace_root)["base_currency"])


def active_profile_for_workspace(workspace_root: Path | str | None = None) -> dict[str, Any]:
    manifest = read_workspace_manifest(workspace_root)
    profile = manifest.get("active_profile") if isinstance(manifest.get("active_profile"), dict) else None
    if (
        isinstance(profile, dict)
        and "base_currency" not in profile
        and int(manifest.get("schema_version") or 1) < WORKSPACE_MANIFEST_SCHEMA_VERSION
    ):
        profile = {**profile, "base_currency": LEGACY_BASE_CURRENCY}
    return normalize_active_profile(profile)


def set_active_profile_for_workspace(workspace_root: Path | str, profile: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    manifest = ensure_workspace_manifest(root)
    manifest["active_profile"] = normalize_active_profile(profile)
    manifest["updated_at"] = now_iso()
    path = workspace_manifest_path(root)
    atomic_write_text(path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def read_workspace_profiles(workspace_root: Path | str) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(workspace_profiles_path(workspace_root).read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    profiles = raw.get("profiles") if isinstance(raw, dict) else {}
    result: dict[str, dict[str, Any]] = {}
    if isinstance(profiles, dict):
        for key, value in profiles.items():
            if isinstance(value, dict):
                normalized = normalize_active_profile(value)
                result[normalized["profile_id"] or sanitize_id(key)] = normalized
    return result


def write_workspace_profiles(workspace_root: Path | str, profiles: dict[str, dict[str, Any]]) -> None:
    path = workspace_profiles_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {sanitize_id(key): normalize_active_profile(value) for key, value in profiles.items()}
    atomic_write_text(path, json.dumps({"profiles": normalized}, indent=2, ensure_ascii=False) + "\n")


def save_active_profile_for_workspace(workspace_root: Path | str, profile: dict[str, Any]) -> dict[str, Any]:
    manifest = set_active_profile_for_workspace(workspace_root, profile)
    registry = read_workspace_profiles(workspace_root)
    active = manifest["active_profile"]
    registry[active["profile_id"]] = active
    write_workspace_profiles(workspace_root, registry)
    return manifest


def configure_tradingcodex_database(workspace_root: Path | str | None = None) -> None:
    global _RUNTIME_DB_READY, _RUNTIME_DB_NAME
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
    db_path = tradingcodex_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_name = str(db_path)
    if os.environ.get("TRADINGCODEX_DB_NAME") == db_name and _RUNTIME_DB_NAME == db_name:
        return
    os.environ["TRADINGCODEX_DB_NAME"] = db_name
    if _RUNTIME_DB_NAME and _RUNTIME_DB_NAME != db_name:
        _RUNTIME_DB_READY = False
    try:
        from django.conf import settings
        from django.db import connections

        if settings.configured:
            current_name = settings.DATABASES["default"].get("NAME")
            settings.DATABASES["default"]["NAME"] = db_name
            settings.DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = int(os.environ.get("TRADINGCODEX_SQLITE_TIMEOUT", "30"))
            connections["default"].settings_dict["NAME"] = db_name
            connections["default"].settings_dict.setdefault("OPTIONS", {})["timeout"] = int(os.environ.get("TRADINGCODEX_SQLITE_TIMEOUT", "30"))
            if current_name != db_name:
                connections.close_all()
                _RUNTIME_DB_READY = False
    except Exception:
        pass
    _RUNTIME_DB_NAME = db_name


def configure_workspace_database(workspace_root: Path | str | None = None) -> None:
    configure_tradingcodex_database(workspace_root)


def workspace_context_payload(workspace_root: Path | str | None = None) -> dict[str, Any]:
    raw_root = workspace_root or os.environ.get("TRADINGCODEX_WORKSPACE_ROOT") or os.getcwd()
    root = Path(raw_root).expanduser().resolve()
    manifest = read_workspace_manifest(root)
    path_hash = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    workspace_id = str(manifest.get("workspace_id") or f"tcxw_{path_hash[:24]}")
    return {
        "workspace_id": workspace_id,
        "path_hash": path_hash,
        "project_name": root.name or "tradingcodex-workspace",
        "path": str(root),
        "git_remote": _git_remote(root),
        "git_branch": _git_branch(root),
        "db_path": str(tradingcodex_db_path()),
        "active_profile": active_profile_for_workspace(root),
        "mcp_scope": str(manifest.get("mcp_scope") or "project-scoped"),
        "execution_mode": normalize_execution_mode(manifest.get("execution_mode")),
    }


def persist_workspace_context_if_available(workspace_root: Path | str | None = None) -> dict[str, Any]:
    context = workspace_context_payload(workspace_root)
    try:
        ensure_runtime_database(None)
        from apps.harness.models import WorkspaceContext

        existing = (
            WorkspaceContext.objects.filter(workspace_id=context["workspace_id"]).first()
            or WorkspaceContext.objects.filter(path_hash=context["path_hash"]).first()
        )
        defaults = {
            "workspace_id": context["workspace_id"],
            "path_hash": context["path_hash"],
            "project_name": context["project_name"],
            "path": context["path"],
            "git_remote": context["git_remote"],
            "git_branch": context["git_branch"],
            "active_profile": context["active_profile"],
            "metadata": {
                "db_path": context["db_path"],
                "mcp_scope": context["mcp_scope"],
                "execution_mode": context["execution_mode"],
            },
        }
        if existing:
            for key, value in defaults.items():
                setattr(existing, key, value)
            existing.save(update_fields=[*defaults.keys(), "last_seen_at"])
        else:
            WorkspaceContext.objects.create(**defaults)
    except Exception:
        pass
    return context


def ensure_runtime_database(workspace_root: Path | str | None = None) -> None:
    global _RUNTIME_DB_READY
    configure_tradingcodex_database(workspace_root)
    import django
    from django.apps import apps
    from django.core.management import call_command

    if not apps.ready:
        django.setup()
    if _RUNTIME_DB_READY or os.environ.get("TRADINGCODEX_AUTO_MIGRATE", "1") == "0":
        return
    try:
        with tradingcodex_file_lock("migrate"):
            call_command("migrate", interactive=False, verbosity=0, fake_initial=True)
            if not _runtime_model_tables_present():
                raise RuntimeMigrationError(
                    "runtime schema is incomplete after Django migrations; run `python manage.py migrate` and retry"
                )
            _RUNTIME_DB_READY = True
    except RuntimeMigrationError:
        raise
    except Exception as exc:
        raise RuntimeMigrationError(
            "runtime database migration failed; inspect the database and run `python manage.py migrate`"
        ) from exc


@contextmanager
def workspace_file_lock(workspace_root: Path | str, name: str):
    with tradingcodex_file_lock(name):
        yield


@contextmanager
def tradingcodex_file_lock(name: str):
    lock_path = tradingcodex_state_dir() / f"tradingcodex.{sanitize_id(name)}.lock"
    with exclusive_file_lock(lock_path, timeout_seconds=30):
        yield


def _runtime_model_tables_present() -> bool:
    try:
        from django.apps import apps
        from django.db import connection

        existing = set(connection.introspection.table_names())
        required = {
            model._meta.db_table
            for model in apps.get_models()
            if model._meta.managed and not model._meta.proxy
        }
        if not bool(required) or not required.issubset(existing):
            return False
        for model in apps.get_models():
            if not model._meta.managed or model._meta.proxy:
                continue
            columns = {
                column.name
                for column in connection.introspection.get_table_description(connection.cursor(), model._meta.db_table)
            }
            expected = {field.column for field in model._meta.local_concrete_fields}
            if not expected.issubset(columns):
                return False
        return True
    except Exception:
        return False


def _git_dir(root: Path) -> Path | None:
    dotgit = root / ".git"
    if dotgit.is_dir():
        return dotgit
    if dotgit.is_file():
        text = _safe_read(dotgit).strip()
        match = re.match(r"gitdir:\s*(.+)", text)
        if match:
            gitdir = Path(match.group(1))
            return gitdir if gitdir.is_absolute() else (root / gitdir).resolve()
    return None


def _git_branch(root: Path) -> str:
    gitdir = _git_dir(root)
    if not gitdir:
        return ""
    head = _safe_read(gitdir / "HEAD").strip()
    match = re.match(r"ref:\s+refs/heads/(.+)", head)
    return match.group(1) if match else head[:12]


def _git_remote(root: Path) -> str:
    gitdir = _git_dir(root)
    config = _safe_read(gitdir / "config") if gitdir else _safe_read(root / ".git" / "config")
    match = re.search(r'\[remote "origin"\][^\[]*?\n\s*url\s*=\s*(.+)', config)
    return match.group(1).strip() if match else ""
