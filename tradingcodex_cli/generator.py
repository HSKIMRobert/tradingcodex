from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.version import TRADINGCODEX_VERSION
from tradingcodex_service.application.agents import project_agent_configuration
from tradingcodex_service.application.components import list_harness_components
from tradingcodex_service.application.common import atomic_write_text, exclusive_file_lock, paths_equivalent, workspace_launcher_command
from tradingcodex_service.application.runtime import (
    ensure_workspace_manifest,
    read_workspace_manifest,
    resolve_tradingcodex_home,
    tradingcodex_db_path,
)
from tradingcodex_cli.startup_status import write_server_status_snapshot

DEFAULT_MODULE_IDS = [
    "codex-base",
    "fixed-subagents",
    "repo-skills",
    "guidance-guardrails",
    "enforcement-guardrails",
    "information-barriers",
    "audit",
    "tradingcodex-mcp",
    "stub-execution",
    "paper-trading",
    "postmortem",
]


@dataclass(frozen=True)
class Module:
    id: str
    description: str
    dir: Path
    manifest: dict[str, Any]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def templates_dir() -> Path:
    return repo_root() / "workspace_templates"


def bootstrap_workspace(project_dir: Path | str, force: bool = False, dry_run: bool = False, module_ids: list[str] | None = None) -> dict[str, Any]:
    target = Path(project_dir).expanduser().resolve(strict=False)
    registry = load_module_registry(templates_dir())
    modules = resolve_module_graph(registry, module_ids or DEFAULT_MODULE_IDS)
    existing_manifest = read_workspace_manifest(target)
    workspace_id = str(existing_manifest.get("workspace_id") or f"tcxw_{uuid.uuid4().hex}")
    context = _generation_context(target, workspace_id)
    result = {
        "targetDir": str(target),
        "workspaceId": workspace_id,
        "modules": [module.id for module in modules],
        "capabilities": collect_capabilities(modules),
        "tradingcodexHome": context["TRADINGCODEX_HOME"],
        "homeSource": context["TRADINGCODEX_HOME_SOURCE"],
        "tradingcodexDbPath": context["TRADINGCODEX_DB_PATH"],
        "dbSource": context["TRADINGCODEX_DB_SOURCE"],
    }
    if dry_run:
        return result
    ensure_target_dir(target, force)
    bootstrap_lock = target / ".tradingcodex" / "generated" / "bootstrap"
    with exclusive_file_lock(bootstrap_lock, timeout_seconds=30):
        existing_manifest = read_workspace_manifest(target)
        workspace_id = str(existing_manifest.get("workspace_id") or workspace_id)
        context = _generation_context(target, workspace_id)
        result.update({
            "tradingcodexHome": context["TRADINGCODEX_HOME"],
            "homeSource": context["TRADINGCODEX_HOME_SOURCE"],
            "tradingcodexDbPath": context["TRADINGCODEX_DB_PATH"],
            "dbSource": context["TRADINGCODEX_DB_SOURCE"],
        })
        for module in modules:
            files_dir = module.dir / "files"
            if files_dir.exists():
                copy_template_tree(files_dir, target, context)
        ensure_workspace_manifest(target, project_name=context["PROJECT_NAME"], generated_at=context["GENERATED_AT"])
        project_agent_configuration(target, applied_by="bootstrap", generated_at=context["GENERATED_AT"])
        write_generated_indexes(target, modules, context)
        write_server_status_snapshot(target)
    result["workspaceId"] = workspace_id
    return result


def _generation_context(target: Path, workspace_id: str) -> dict[str, str]:
    resolution = _resolve_generation_home(target)
    if resolution.home is None or resolution.home_source is None:
        raise ValueError("TradingCodex global home is unresolved")
    db_override = bool(str(os.environ.get("TRADINGCODEX_DB_NAME") or "").strip())
    raw = {
        "PROJECT_NAME": sanitize_project_name(target.name or "tradingcodex-workspace"),
        "WORKSPACE_ID": workspace_id,
        "GENERATED_AT": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "TRADINGCODEX_VERSION": TRADINGCODEX_VERSION,
        "TRADINGCODEX_MCP_PACKAGE_SPEC": os.environ.get("TRADINGCODEX_MCP_PACKAGE_SPEC", "tradingcodex"),
        "TRADINGCODEX_HOME": str(resolution.home),
        "TRADINGCODEX_HOME_SOURCE": resolution.home_source,
        "TRADINGCODEX_DB_PATH": str(tradingcodex_db_path()),
        "TRADINGCODEX_DB_SOURCE": "environment_override" if db_override else "home_default",
        "TRADINGCODEX_SERVICE_ADDR": os.environ.get("TRADINGCODEX_SERVICE_ADDR", "127.0.0.1:48267"),
        "TRADINGCODEX_HOOK_COMMAND": f"{workspace_launcher_command()} __hook",
        "TRADINGCODEX_WORKSPACE_LAUNCHER": workspace_launcher_command(),
    }
    return serialized_template_context(raw)


def _resolve_generation_home(target: Path):
    """Preserve provenance from wrappers generated before home_source existed."""

    if not _uses_legacy_generated_home_projection(target):
        return resolve_tradingcodex_home()
    projected_env = dict(os.environ)
    projected_env["TRADINGCODEX_HOME_SOURCE"] = "legacy_fallback"
    resolution = resolve_tradingcodex_home(environ=projected_env)
    return resolution


def _uses_legacy_generated_home_projection(target: Path) -> bool:
    if str(os.environ.get("TRADINGCODEX_HOME_SOURCE") or "").strip():
        return False
    configured_home = str(os.environ.get("TRADINGCODEX_HOME") or "").strip()
    if not configured_home:
        return False
    try:
        lock = json.loads((target / ".tradingcodex" / "generated" / "module-lock.json").read_text(encoding="utf-8"))
    except Exception:
        return False
    if str(lock.get("home_source") or "").strip():
        return False
    locked_home = str(lock.get("tradingcodex_home") or "").strip()
    if not locked_home:
        return False
    probe = resolve_tradingcodex_home(strict=False)
    if probe.conflict:
        return False
    legacy_home = str(probe.legacy_home)
    configured_matches = paths_equivalent(configured_home, legacy_home, platform_name=os.sys.platform)
    locked_literal = locked_home.replace("\\", "/").rstrip("/") == "~/.tradingcodex"
    locked_matches = locked_literal or paths_equivalent(
        str(Path(locked_home).expanduser().resolve(strict=False)),
        legacy_home,
        platform_name=os.sys.platform,
    )
    return configured_matches and locked_matches


def serialized_template_context(raw: dict[str, str]) -> dict[str, str]:
    context = dict(raw)
    for key, value in raw.items():
        literal = json.dumps(str(value), ensure_ascii=False)
        context[f"{key}_JSON"] = literal
        context[f"{key}_JSON_INNER"] = literal[1:-1]
        context[f"{key}_PYTHON"] = literal
        context[f"{key}_TOML"] = literal
        context[f"{key}_YAML"] = literal
        context[f"{key}_SHELL"] = shlex.quote(str(value))
        cmd_value = _cmd_set_value(str(value))
        context[f"{key}_CMD_SET"] = cmd_value
        context[f"{key}_CMD"] = f'"{cmd_value}"'
    context["TRADINGCODEX_DB_ENV_TOML"] = (
        f", TRADINGCODEX_DB_NAME = {context['TRADINGCODEX_DB_PATH_TOML']}"
        if raw.get("TRADINGCODEX_DB_SOURCE") == "environment_override"
        else ""
    )
    context["TRADINGCODEX_DB_ENV_SHELL"] = (
        "if [ -z \"${TRADINGCODEX_DB_NAME:-}\" ]; then\n"
        f"  export TRADINGCODEX_DB_NAME={context['TRADINGCODEX_DB_PATH_SHELL']}\n"
        "fi"
        if raw.get("TRADINGCODEX_DB_SOURCE") == "environment_override"
        else ""
    )
    context["TRADINGCODEX_DB_ENV_CMD"] = (
        f'if not defined TRADINGCODEX_DB_NAME set "TRADINGCODEX_DB_NAME={context["TRADINGCODEX_DB_PATH_CMD_SET"]}"'
        if raw.get("TRADINGCODEX_DB_SOURCE") == "environment_override"
        else "rem TRADINGCODEX_DB_NAME uses the selected home"
    )
    return context


def _cmd_set_value(value: str) -> str:
    if any(character in value for character in ('"', "\r", "\n", "\0")):
        raise ValueError("generated CMD values must not contain quotes or control newlines")
    # Batch expands percent expressions while parsing the file. Doubling the
    # marker preserves it as data inside set "NAME=value" assignments.
    return value.replace("%", "%%")


def load_module_registry(base_templates_dir: Path) -> dict[str, Module]:
    modules_dir = base_templates_dir / "modules"
    registry: dict[str, Module] = {}
    for module_dir in sorted(path for path in modules_dir.iterdir() if path.is_dir()):
        manifest_path = module_dir / "module.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        module_id = manifest["id"]
        if module_id != module_dir.name:
            raise ValueError(f'Module id "{module_id}" does not match directory "{module_dir.name}"')
        registry[module_id] = Module(module_id, manifest.get("description", ""), module_dir, manifest)
    return registry


def resolve_module_graph(registry: dict[str, Module], requested_ids: list[str]) -> list[Module]:
    resolved: list[Module] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(module_id: str, parent_id: str | None = None) -> None:
        if module_id in seen:
            return
        if module_id in visiting:
            raise ValueError(f'Circular module dependency detected at "{module_id}"')
        if module_id not in registry:
            suffix = f' required by "{parent_id}"' if parent_id else ""
            raise ValueError(f'Unknown module "{module_id}"{suffix}')
        visiting.add(module_id)
        module = registry[module_id]
        for dependency in module.manifest.get("requires", {}).get("modules", []):
            visit(dependency, module_id)
        visiting.remove(module_id)
        seen.add(module_id)
        resolved.append(module)

    for module_id in requested_ids:
        visit(module_id)
    assert_no_conflicts(resolved)
    return resolved


def collect_capabilities(modules: list[Module]) -> list[str]:
    capabilities: set[str] = set()
    for module in modules:
        capabilities.update(module.manifest.get("provides", {}).get("capabilities", []))
    return sorted(capabilities)


def ensure_target_dir(target: Path, force: bool) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if not force and not target_has_only_bootstrap_files(target):
        raise ValueError(f"Target directory already has files: {target}. Use an empty directory, a git-initialized empty directory, or pass --overwrite to update matching generated workspace paths.")


def target_has_only_bootstrap_files(target: Path) -> bool:
    allowed_names = {".git", ".gitignore", ".gitattributes"}
    return all(child.name in allowed_names for child in target.iterdir())


def copy_template_tree(source: Path, target: Path, context: dict[str, str]) -> None:
    for item in source.iterdir():
        if item.name in {"__pycache__", ".DS_Store"} or item.suffix in {".pyc", ".pyo"}:
            continue
        destination = target / item.name
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            copy_template_tree(item, destination, context)
            continue
        if not item.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = item.read_text(encoding="utf-8")
        rendered = render_template(text, context)
        atomic_write_text(destination, rendered)
        if os.name != "nt":
            destination.chmod(0o755 if rendered.startswith("#!") else 0o644)


def write_generated_indexes(target: Path, modules: list[Module], context: dict[str, str]) -> None:
    generated_dir = target / ".tradingcodex" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    lock = {
        "generated_at": context["GENERATED_AT"],
        "tradingcodex_version": context["TRADINGCODEX_VERSION"],
        "tradingcodex_package_spec": context["TRADINGCODEX_MCP_PACKAGE_SPEC"],
        "tradingcodex_home": context["TRADINGCODEX_HOME"],
        "home_source": context["TRADINGCODEX_HOME_SOURCE"],
        "tradingcodex_db_path": context["TRADINGCODEX_DB_PATH"],
        "db_source": context["TRADINGCODEX_DB_SOURCE"],
        "modules": [
            {
                "id": module.id,
                "description": module.description,
                "capabilities": module.manifest.get("provides", {}).get("capabilities", []),
            }
            for module in modules
        ],
    }
    capability_index = {
        "generated_at": context["GENERATED_AT"],
        "capabilities": collect_capabilities(modules),
    }
    component_index = {
        "generated_at": context["GENERATED_AT"],
        "source": "tradingcodex_service.application.components",
        "components": list_harness_components(),
    }
    atomic_write_text(generated_dir / "capability-index.json", json.dumps(capability_index, indent=2) + "\n")
    atomic_write_text(generated_dir / "component-index.json", json.dumps(component_index, indent=2) + "\n")
    atomic_write_text(generated_dir / "module-lock.json", json.dumps(lock, indent=2) + "\n")


def assert_no_conflicts(modules: list[Module]) -> None:
    ids = {module.id for module in modules}
    for module in modules:
        for conflict in module.manifest.get("conflicts", []):
            if conflict in ids:
                raise ValueError(f'Module "{module.id}" conflicts with "{conflict}"')


def render_template(source: str, context: dict[str, str]) -> str:
    pattern = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
    requested = set(pattern.findall(source))
    missing = sorted(requested - context.keys())
    if missing:
        unresolved = ", ".join(f"{{{{{key}}}}}" for key in missing)
        raise ValueError(f"unresolved generated template values: {unresolved}")
    return pattern.sub(lambda match: context[match.group(1)], source)


def sanitize_project_name(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch in "._-" else "-" for ch in name)
    return cleaned.strip("-") or "tradingcodex-workspace"


def reset_tmp_generated_workspaces(repo: Path | None = None) -> None:
    tmp = (repo or repo_root()) / "tmp"
    for child in ["smoke", "dry-run-smoke", "non-empty-smoke", "scenario-quality", "external-data", "quality-scenarios-20"]:
        shutil.rmtree(tmp / child, ignore_errors=True)
