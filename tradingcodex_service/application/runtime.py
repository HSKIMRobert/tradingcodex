from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from tradingcodex_service.application.common import (
    _safe_read,
    atomic_write_text,
    canonical_path_identity,
    exclusive_file_lock,
    now_iso,
    sanitize_id,
)

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


class RuntimeHomeResolutionError(RuntimeError):
    """Raised when the global TradingCodex home cannot be selected safely."""


class RuntimeHomeConflictError(RuntimeHomeResolutionError):
    """Raised when both the legacy and platform homes contain local state."""


@dataclass(frozen=True)
class HomeResolution:
    home: Path | PurePath | None
    home_source: str | None
    platform_default: Path | PurePath
    legacy_home: Path | PurePath
    platform_default_populated: bool
    legacy_home_populated: bool
    conflict: bool
    diagnostic: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "home": str(self.home) if self.home is not None else None,
            "home_source": self.home_source,
            "home_conflict": self.conflict,
            "platform_default_home": str(self.platform_default),
            "platform_default_populated": self.platform_default_populated,
            "legacy_home": str(self.legacy_home),
            "legacy_home_populated": self.legacy_home_populated,
            "diagnostic": self.diagnostic,
            "automatic_home_migration": False,
        }


def default_active_profile() -> dict[str, Any]:
    return {
        "profile_id": DEFAULT_PROFILE_ID,
        "portfolio_id": DEFAULT_PROFILE_ID,
        "account_id": DEFAULT_ACCOUNT_ID,
        "strategy_id": DEFAULT_STRATEGY_ID,
        "base_currency": DEFAULT_BASE_CURRENCY,
        "label": "shared central paper account",
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
        "label": "isolated workspace paper account",
        "shared": False,
        "shared_explicitly_selected": False,
        "origin_workspace_id": workspace_id,
        "investor_profile": {},
    }


def resolve_tradingcodex_home(
    *,
    environ: dict[str, str] | os._Environ[str] | None = None,
    platform_name: str | None = None,
    user_home: str | Path | PurePath | None = None,
    populated: Callable[[Path | PurePath], bool] | None = None,
    strict: bool = True,
) -> HomeResolution:
    """Resolve one global home without creating or moving any local state."""

    env = os.environ if environ is None else environ
    platform_value = platform_name or sys.platform
    family = _platform_family(platform_value)
    home_dir = _user_home_path(env, family, platform_value, user_home)
    legacy_home = _canonical_home_candidate(home_dir / ".tradingcodex", family, platform_value)
    population_check = populated or _home_is_populated

    explicit = str(env.get("TRADINGCODEX_HOME") or "").strip()
    explicit_home = _expand_home_candidate(explicit, home_dir, family, platform_value) if explicit else None
    try:
        platform_default = _platform_default_home(env, family, platform_value, home_dir)
    except RuntimeHomeResolutionError:
        if explicit_home is None or family != "windows":
            raise
        platform_default = PureWindowsPath("%LOCALAPPDATA%") / "TradingCodex"
        return HomeResolution(
            home=explicit_home,
            home_source="environment_override",
            platform_default=platform_default,
            legacy_home=legacy_home,
            platform_default_populated=False,
            legacy_home_populated=False,
            conflict=False,
            diagnostic="TRADINGCODEX_HOME explicitly selects the global home; LOCALAPPDATA is unavailable for default-path diagnostics.",
        )
    source_hint = str(env.get("TRADINGCODEX_HOME_SOURCE") or "").strip()
    hinted_source = _validated_home_source_hint(explicit_home, source_hint, platform_default, legacy_home, family)
    allowed_sources = {"platform_default", "legacy_fallback", "environment_override"}
    invalid_hint = bool(
        source_hint
        and (
            source_hint not in allowed_sources
            or explicit_home is None
            or (source_hint in {"platform_default", "legacy_fallback"} and hinted_source is None)
        )
    )

    if explicit_home is not None and not invalid_hint and hinted_source in {None, "environment_override"}:
        return HomeResolution(
            home=explicit_home,
            home_source="environment_override",
            platform_default=platform_default,
            legacy_home=legacy_home,
            platform_default_populated=False,
            legacy_home_populated=False,
            conflict=False,
            diagnostic="TRADINGCODEX_HOME explicitly selects the global home.",
        )

    try:
        platform_populated = bool(population_check(platform_default))
        legacy_populated = bool(population_check(legacy_home))
    except OSError as exc:
        raise RuntimeHomeResolutionError(f"could not inspect TradingCodex home candidates: {exc}") from exc

    same_home = _path_identity(platform_default, family) == _path_identity(legacy_home, family)
    conflict = platform_populated and legacy_populated and not same_home
    if conflict:
        resolution = HomeResolution(
            home=None,
            home_source=None,
            platform_default=platform_default,
            legacy_home=legacy_home,
            platform_default_populated=True,
            legacy_home_populated=True,
            conflict=True,
            diagnostic=(
                "Both the platform-default and legacy TradingCodex homes contain data. "
                "No path was selected; set TRADINGCODEX_HOME explicitly after reviewing both ledgers."
            ),
        )
        if strict:
            raise RuntimeHomeConflictError(resolution.diagnostic)
        return resolution

    if invalid_hint:
        resolution = HomeResolution(
            home=None,
            home_source=None,
            platform_default=platform_default,
            legacy_home=legacy_home,
            platform_default_populated=platform_populated,
            legacy_home_populated=legacy_populated,
            conflict=True,
            diagnostic=(
                f"TRADINGCODEX_HOME_SOURCE={source_hint!r} does not match the projected home for this platform. "
                "Refusing to reinterpret a generated projection as an environment override; run tcx home status outside the workspace and update the workspace."
            ),
        )
        if strict:
            raise RuntimeHomeConflictError(resolution.diagnostic)
        return resolution

    stale_projection = (
        hinted_source == "platform_default" and legacy_populated and not platform_populated and not same_home
    ) or (
        hinted_source == "legacy_fallback"
        and not same_home
        and not (legacy_populated and not platform_populated)
    )
    if stale_projection:
        resolution = HomeResolution(
            home=None,
            home_source=None,
            platform_default=platform_default,
            legacy_home=legacy_home,
            platform_default_populated=platform_populated,
            legacy_home_populated=legacy_populated,
            conflict=True,
            diagnostic=(
                f"Generated TradingCodex home projection ({hinted_source}) no longer matches populated home state. "
                "Refusing to create a second ledger; run tcx home status outside the workspace and update the workspace from the selected home."
            ),
        )
        if strict:
            raise RuntimeHomeConflictError(resolution.diagnostic)
        return resolution

    if hinted_source == "platform_default" and explicit_home is not None:
        selected = explicit_home
        source = "platform_default"
    elif hinted_source == "legacy_fallback" and explicit_home is not None:
        selected = explicit_home
        source = "legacy_fallback"
    elif legacy_populated and not platform_populated:
        selected = legacy_home
        source = "legacy_fallback"
    else:
        selected = platform_default
        source = "platform_default"
    diagnostic = (
        "Using populated legacy ~/.tradingcodex state; no data was moved automatically."
        if source == "legacy_fallback"
        else "Using the platform-default TradingCodex home."
    )
    return HomeResolution(
        home=selected,
        home_source=source,
        platform_default=platform_default,
        legacy_home=legacy_home,
        platform_default_populated=platform_populated,
        legacy_home_populated=legacy_populated,
        conflict=False,
        diagnostic=diagnostic,
    )


def tradingcodex_home() -> Path:
    resolution = resolve_tradingcodex_home()
    if not isinstance(resolution.home, Path):
        raise RuntimeHomeResolutionError("TradingCodex home did not resolve to a native filesystem path")
    return resolution.home


def tradingcodex_state_dir() -> Path:
    return tradingcodex_home() / "state"


def tradingcodex_db_path() -> Path:
    configured = str(os.environ.get("TRADINGCODEX_DB_NAME") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return tradingcodex_state_dir() / "tradingcodex.sqlite3"


def runtime_home_status() -> dict[str, Any]:
    resolution = resolve_tradingcodex_home(strict=False)
    payload = resolution.as_dict()
    configured_db = str(os.environ.get("TRADINGCODEX_DB_NAME") or "").strip()
    if configured_db:
        payload.update({
            "db_path": str(Path(configured_db).expanduser().resolve(strict=False)),
            "db_source": "environment_override",
        })
    elif resolution.home is not None:
        payload.update({
            "db_path": str(resolution.home / "state" / "tradingcodex.sqlite3"),
            "db_source": "home_default",
        })
    else:
        payload.update({"db_path": None, "db_source": None})
    payload["status"] = "conflict" if resolution.conflict else "ok"
    payload["offline_home_migration_available"] = False
    return payload


def _platform_family(platform_name: str) -> str:
    lowered = platform_name.lower()
    if lowered.startswith("win") or lowered == "nt":
        return "windows"
    if lowered == "darwin":
        return "macos"
    return "linux"


def _native_family() -> str:
    return _platform_family(sys.platform)


def _user_home_path(
    env: dict[str, str] | os._Environ[str],
    family: str,
    platform_name: str,
    supplied: str | Path | PurePath | None,
) -> Path | PurePath:
    if supplied is not None:
        return _canonical_home_candidate(supplied, family, platform_name)
    if family == "windows":
        raw = str(env.get("USERPROFILE") or "").strip()
        if not raw:
            raw = f"{env.get('HOMEDRIVE', '')}{env.get('HOMEPATH', '')}".strip()
        if not raw and family != _native_family():
            raise RuntimeHomeResolutionError("USERPROFILE is required when resolving a simulated Windows home")
    else:
        raw = str(env.get("HOME") or "").strip()
    raw = raw or str(Path.home())
    return _canonical_home_candidate(raw, family, platform_name)


def _platform_default_home(
    env: dict[str, str] | os._Environ[str],
    family: str,
    platform_name: str,
    home_dir: Path | PurePath,
) -> Path | PurePath:
    if family == "macos":
        candidate = home_dir / "Library" / "Application Support" / "TradingCodex"
    elif family == "windows":
        local_app_data = str(env.get("LOCALAPPDATA") or "").strip()
        if not local_app_data:
            raise RuntimeHomeResolutionError("LOCALAPPDATA is required for the native Windows TradingCodex home")
        candidate = _expand_home_candidate(local_app_data, home_dir, family, platform_name) / "TradingCodex"
    else:
        xdg_data_home = str(env.get("XDG_DATA_HOME") or "").strip()
        candidate = (
            _expand_home_candidate(xdg_data_home, home_dir, family, platform_name) / "tradingcodex"
            if xdg_data_home
            else home_dir / ".local" / "share" / "tradingcodex"
        )
    return _canonical_home_candidate(candidate, family, platform_name)


def _expand_home_candidate(
    raw: str,
    home_dir: Path | PurePath,
    family: str,
    platform_name: str,
) -> Path | PurePath:
    if raw == "~":
        return home_dir
    if raw.startswith("~/") or raw.startswith("~\\"):
        return _canonical_home_candidate(home_dir / raw[2:], family, platform_name)
    return _canonical_home_candidate(raw, family, platform_name)


def _canonical_home_candidate(value: str | Path | PurePath, family: str, platform_name: str) -> Path | PurePath:
    if (family == "windows") != (_native_family() == "windows"):
        pure_type = PureWindowsPath if family == "windows" else PurePosixPath
        return pure_type(str(value))
    return Path(value).expanduser().resolve(strict=False)


def _home_is_populated(path: Path | PurePath) -> bool:
    if not isinstance(path, Path):
        return False
    if not path.exists():
        return False
    if not path.is_dir():
        raise RuntimeHomeResolutionError(f"TradingCodex home candidate is not a directory: {path}")
    for child in path.iterdir():
        if child.name == ".DS_Store":
            continue
        if child.is_file() or child.is_symlink():
            return True
        if child.is_dir() and any(item.is_file() or item.is_symlink() for item in child.rglob("*")):
            return True
    return False


def _path_identity(path: Path | PurePath, family: str) -> str:
    text = str(path)
    return ntpath.normcase(ntpath.normpath(text)) if family == "windows" else text


def _validated_home_source_hint(
    explicit_home: Path | PurePath | None,
    hint: str,
    platform_default: Path | PurePath,
    legacy_home: Path | PurePath,
    family: str,
) -> str | None:
    if explicit_home is None or hint not in {"platform_default", "legacy_fallback", "environment_override"}:
        return None
    if hint == "environment_override":
        return hint
    expected = platform_default if hint == "platform_default" else legacy_home
    return hint if _path_identity(explicit_home, family) == _path_identity(expected, family) else None


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
    path_hash = hashlib.sha256(canonical_path_identity(root).encode("utf-8")).hexdigest()
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
