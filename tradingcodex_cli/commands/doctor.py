from __future__ import annotations

import json
import os
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
from typing import Any

from tradingcodex_service.application.agents import (
    AGENT_SPECS,
    EXPECTED_SKILLS,
    EXPECTED_SUBAGENTS,
    MODEL_POLICY_MANIFEST_PATH,
    ROLE_PERMISSION_PROFILES,
    SKILL_SPECS,
    build_projection_state,
    inspect_skill_projection,
    resolve_agent_model_policy,
)
from tradingcodex_service.application.runtime import (
    read_workspace_manifest,
    ensure_runtime_database,
    runtime_home_status,
    tradingcodex_db_path,
)
from tradingcodex_service.application.common import paths_equivalent, workspace_launcher_command
from tradingcodex_cli.commands.utils import (
    list_subagents,
    path_check,
    read_thread_policy,
    text_check,
)
from tradingcodex_service.version import TRADINGCODEX_VERSION

def doctor(root: Path, layer: str) -> None:
    allowed = {"all", "codex-native", "guidance", "enforcement", "information-barrier", "improvement", "mcp", "service"}
    if layer not in allowed:
        raise ValueError(f'unknown layer "{layer}"')
    checks = []
    checks.extend(_central_service_checks(root))
    checks.extend(_guidance_checks(root))
    checks.extend(_enforcement_checks(root))
    checks.extend(_information_barrier_checks(root))
    checks.extend(_improvement_checks(root))
    checks.extend(_mcp_checks(root))
    checks = [
        check
        for check in checks
        if layer == "all"
        or check["layer"] == layer
        or (layer == "codex-native" and check.get("codexNative"))
        or (check.get("globalPreflight") and not check["ok"])
    ]
    failed = 0
    print("TradingCodex Harness\n")
    for check in checks:
        status = "WARN" if check.get("warn") else "PASS" if check["ok"] else "FAIL"
        if not check["ok"] and not check.get("warn"):
            failed += 1
        print(f"{status.ljust(4)} {check['layer'].ljust(20)} {check['name']} - {check['detail']}")
    if failed:
        print(f"TradingCodex doctor failed: {failed} check(s) failed", file=sys.stderr)
        sys.exit(1)
    print("\nTradingCodex doctor passed")

def _guidance_checks(root: Path) -> list[dict[str, Any]]:
    thread_policy = read_thread_policy(root)
    roster_size = len(list_subagents(root))
    return [
        path_check(root, "guidance", "AGENTS.md installed", "AGENTS.md", True),
        text_check(root, "guidance", "head-manager model instructions file configured", ".codex/config.toml", 'model_instructions_file = "prompts/base_instructions/head-manager.md"', True),
        text_check(root, "guidance", "head-manager instructions installed", ".codex/prompts/base_instructions/head-manager.md", "You are the `head-manager` agent", True),
        *_launcher_checks(root),
        text_check(root, "guidance", "hooks configured", ".codex/hooks.json", "\"PreToolUse\"", True),
        text_check(root, "guidance", "session context configured", ".codex/hooks/tradingcodex_hook.py", "tradingcodex-session-context", True),
        text_check(root, "guidance", "three-plane routing configured", ".codex/prompts/base_instructions/head-manager.md", "TradingCodex has three planes", True),
        text_check(root, "guidance", "build gate configured", ".codex/prompts/base_instructions/head-manager.md", "Codex permission is full access", True),
        text_check(root, "guidance", "compact context discipline configured", ".codex/prompts/base_instructions/head-manager.md", "# Context Discipline", True),
        {"layer": "guidance", "name": "subagent scheduler ceiling is independent of roster", "ok": 1 < thread_policy["max_threads"] < roster_size, "codexNative": True, "detail": f"max_threads={thread_policy['max_threads']}, subagents={roster_size}"},
        {"layer": "guidance", "name": "subagent recursion remains disabled", "ok": thread_policy["max_depth"] == 1, "codexNative": True, "detail": f"max_depth={thread_policy['max_depth']}"},
        *_model_policy_checks(root),
    ]


def _launcher_checks(root: Path) -> list[dict[str, Any]]:
    unix_launcher = root / "tcx"
    windows_launcher = root / "tcx.cmd"
    active = windows_launcher if os.name == "nt" else unix_launcher
    active_ok = active.is_file() and (os.name == "nt" or os.access(active, os.X_OK))
    return [
        {
            "layer": "guidance",
            "name": "native workspace launcher",
            "ok": active_ok,
            "codexNative": True,
            "detail": str(active),
        },
        {
            "layer": "guidance",
            "name": "cross-platform launcher pair",
            "ok": unix_launcher.is_file() and windows_launcher.is_file(),
            "codexNative": True,
            "detail": "tcx + tcx.cmd" if unix_launcher.is_file() and windows_launcher.is_file() else "missing tcx or tcx.cmd",
        },
    ]


def _model_policy_checks(root: Path) -> list[dict[str, Any]]:
    manifest_path = root / MODEL_POLICY_MANIFEST_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [{"layer": "guidance", "name": "runtime model policy manifest", "ok": False, "codexNative": True, "detail": str(exc)}]
    roles = manifest.get("roles") if isinstance(manifest.get("roles"), dict) else {}
    checks = [{
        "layer": "guidance",
        "name": "runtime model policy manifest",
        "ok": set(roles) == set(AGENT_SPECS),
        "codexNative": True,
        "detail": f"roles={len(roles)}, expected={len(AGENT_SPECS)}",
    }]
    comparison_refs = {
        str(policy.get("evaluation_comparison_ref") or "")
        for policy in roles.values()
        if isinstance(policy, dict)
    }
    comparison_ready = len(comparison_refs) == 1 and "" not in comparison_refs
    checks.append({
        "layer": "guidance",
        "name": "GPT-5.6 paired evaluation promotion",
        "ok": comparison_ready,
        "warn": not comparison_ready,
        "codexNative": True,
        "detail": next(iter(comparison_refs)) if comparison_ready else "active-but-unpromoted: no paired evaluation comparison reference",
    })
    for role in AGENT_SPECS:
        policy = roles.get(role) if isinstance(roles.get(role), dict) else resolve_agent_model_policy(role)
        config_path = root / (".codex/config.toml" if role == "head-manager" else f".codex/agents/{role}.toml")
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            checks.append({"layer": "guidance", "name": f"runtime model policy: {role}", "ok": False, "codexNative": True, "detail": str(exc)})
            continue
        ok = config.get("model") == policy["resolved_model"] and config.get("model_reasoning_effort") == policy["reasoning_effort"]
        checks.append({"layer": "guidance", "name": f"runtime model policy: {role}", "ok": ok, "codexNative": True, "detail": f"{config.get('model')}/{config.get('model_reasoning_effort')} ({policy['support_status']})"})
    return checks


def _central_service_checks(root: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = _version_checks(root)
    home_status = runtime_home_status()
    home_conflict = bool(home_status["home_conflict"])
    legacy_fallback = home_status["home_source"] == "legacy_fallback"
    checks.append({
        "layer": "service",
        "name": "global home selection",
        "ok": not home_conflict,
        "warn": legacy_fallback and not home_conflict,
        "codexNative": False,
        "globalPreflight": True,
        "detail": (
            f"{home_status['diagnostic']} platform={home_status['platform_default_home']} legacy={home_status['legacy_home']}"
            if home_conflict
            else f"{home_status['home']} ({home_status['home_source']})"
        ),
    })
    if home_conflict:
        return checks
    try:
        module_lock = json.loads((root / ".tradingcodex" / "generated" / "module-lock.json").read_text(encoding="utf-8"))
        projected_home = str(module_lock.get("tradingcodex_home") or "")
        projected_source = str(module_lock.get("home_source") or "")
        projected_db = str(module_lock.get("tradingcodex_db_path") or "")
        projected_db_source = str(module_lock.get("db_source") or "")
        home_source_ok = projected_source == home_status["home_source"] or home_status["home_source"] == "environment_override"
        db_source_ok = projected_db_source == home_status["db_source"] or home_status["db_source"] == "environment_override"
        projection_ok = (
            paths_equivalent(projected_home, str(home_status["home"]))
            and home_source_ok
            and paths_equivalent(projected_db, str(home_status["db_path"]))
            and db_source_ok
        )
        projection_detail = (
            f"home={projected_home or 'missing'} ({projected_source or 'missing'}), "
            f"db={projected_db or 'missing'} ({projected_db_source or 'missing'})"
        )
    except Exception as exc:
        projection_ok = False
        projection_detail = str(exc)
    checks.append({
        "layer": "service",
        "name": "generated home/DB projection matches runtime",
        "ok": projection_ok,
        "codexNative": True,
        "globalPreflight": True,
        "detail": projection_detail,
    })
    if not projection_ok:
        return checks
    try:
        ensure_runtime_database(root)
        db_path = tradingcodex_db_path()
        checks.append({"layer": "service", "name": "central DB reachable", "ok": db_path.exists(), "codexNative": False, "detail": str(db_path)})
        checks.append({
            "layer": "service",
            "name": "workspace root is provenance only",
            "ok": db_path != (root / ".tradingcodex" / "state" / "tradingcodex.sqlite3").resolve(),
            "codexNative": False,
            "detail": f"workspace={root}",
        })
        manifest = read_workspace_manifest(root)
        has_workspace_id = bool(str(manifest.get("workspace_id", "")).startswith("tcxw_"))
        checks.append({
            "layer": "service",
            "name": "workspace identity manifest installed",
            "ok": has_workspace_id,
            "warn": not has_workspace_id,
            "codexNative": False,
            "detail": str(manifest.get("workspace_id") or "missing .tradingcodex/workspace.json"),
        })
        has_profile = bool((manifest.get("active_profile") or {}).get("portfolio_id"))
        checks.append({
            "layer": "service",
            "name": "active profile configured",
            "ok": has_profile,
            "warn": not has_profile,
            "codexNative": False,
            "detail": (manifest.get("active_profile") or {}).get("label", "missing active profile"),
        })
        from apps.mcp.models import McpToolCall
        from tradingcodex_service.application.health import readiness_payload

        McpToolCall.objects.count()
        checks.append({"layer": "service", "name": "central MCP ledger reachable", "ok": True, "codexNative": False, "detail": "McpToolCall table available"})
        readiness = readiness_payload()
        checks.append({
            "layer": "service",
            "name": "service readiness contract",
            "ok": readiness["ready"],
            "codexNative": False,
            "detail": "ready" if readiness["ready"] else ", ".join(readiness["reason_codes"]),
        })
    except Exception as exc:
        checks.append({"layer": "service", "name": "central DB reachable", "ok": False, "codexNative": False, "detail": str(exc)})
    export_dirs = ["trading/research", "trading/reports", "trading/audit", "trading/orders", "trading/approvals"]
    for rel in export_dirs:
        path = root / rel
        checks.append({"layer": "service", "name": f"workspace export/cache writable: {rel}", "ok": path.exists() and os.access(path, os.W_OK), "codexNative": False, "detail": "writable" if path.exists() and os.access(path, os.W_OK) else "missing or not writable"})
    return checks


def _version_checks(root: Path) -> list[dict[str, Any]]:
    try:
        package_version = distribution_version("tradingcodex")
    except PackageNotFoundError:
        package_version = TRADINGCODEX_VERSION
    try:
        module_lock = json.loads((root / ".tradingcodex" / "generated" / "module-lock.json").read_text(encoding="utf-8"))
        workspace_version = str(module_lock.get("tradingcodex_version") or "")
    except Exception:
        workspace_version = ""
    return [
        {
            "layer": "service",
            "name": "package and runtime versions match",
            "ok": package_version == TRADINGCODEX_VERSION,
            "codexNative": False,
            "detail": f"package={package_version}, runtime={TRADINGCODEX_VERSION}",
        },
        {
            "layer": "service",
            "name": "workspace and runtime versions match",
            "ok": workspace_version == TRADINGCODEX_VERSION,
            "codexNative": False,
            "detail": f"workspace={workspace_version or 'missing'}, runtime={TRADINGCODEX_VERSION}",
        },
    ]


def _enforcement_checks(root: Path) -> list[dict[str, Any]]:
    schemas = ["research_artifact.schema.json", "evidence_pack.schema.json", "fundamental_report.schema.json", "technical_report.schema.json", "news_report.schema.json", "thesis.schema.json", "valuation.schema.json", "portfolio_review.schema.json", "risk_report.schema.json", "order_ticket.schema.json", "approval_receipt.schema.json", "execution_result.schema.json", "postmortem_report.schema.json", "audit_event.schema.json"]
    return [
        text_check(root, "enforcement", "command rules configured", ".codex/rules/tradingcodex.rules", "prefix_rule(", True),
        *_codex_mcp_config_checks(root),
        path_check(root, "enforcement", "TradingCodex MCP installed", ".tradingcodex/mcp/server.py", False),
        {"layer": "enforcement", "name": "live broker disabled by default", "ok": not (root / ".tradingcodex" / "mcp" / "adapters" / "live.py").exists(), "detail": "no generated live adapter override; live provider gates remain service-controlled"},
        *[path_check(root, "enforcement", f"schema installed: {schema}", f".tradingcodex/schemas/{schema}", False) for schema in schemas],
    ]


def _codex_mcp_config_checks(root: Path) -> list[dict[str, Any]]:
    root_mcp = _read_codex_mcp_config(root / ".codex" / "config.toml")
    execution_mcp = _read_codex_mcp_config(root / ".codex" / "agents" / "execution-operator.toml")
    risk_mcp = _read_codex_mcp_config(root / ".codex" / "agents" / "risk-manager.toml")
    root_tools = set(root_mcp.get("enabled_tools") or [])
    execution_tools = set(execution_mcp.get("enabled_tools") or [])
    risk_tools = set(risk_mcp.get("enabled_tools") or [])
    sensitive_execution_tools = {"submit_approved_order", "cancel_approved_order"}
    non_execution_exposure = []
    for agent_path in sorted((root / ".codex" / "agents").glob("*.toml")):
        if agent_path.stem == "execution-operator":
            continue
        enabled = set((_read_codex_mcp_config(agent_path).get("enabled_tools") or []))
        exposed = sensitive_execution_tools & enabled
        if exposed:
            non_execution_exposure.append(f"{agent_path.stem}: {', '.join(sorted(exposed))}")
    raw_broker_tools = {"place_order", "replace_order", "cancel_order", "withdraw", "transfer"}
    broker_connector_tools = {
        "list_broker_adapter_providers",
        "scaffold_broker_connector",
        "register_broker_connector",
        "validate_broker_connector_build",
        "get_broker_capability_profile",
        "get_broker_instrument_constraints",
        "preview_order_translation",
    }
    return [
        {
            "layer": "enforcement",
            "name": "TradingCodex MCP root server configured",
            "ok": bool(root_mcp.get("enabled") is True and root_mcp.get("command") and root_mcp.get("args")),
            "codexNative": True,
            "detail": "enabled with command/args" if root_mcp else "missing mcp_servers.tradingcodex",
        },
        {
            "layer": "enforcement",
            "name": "TradingCodex MCP autostarts local service",
            "ok": root_mcp.get("env", {}).get("TRADINGCODEX_MCP_AUTOSTART_SERVICE") == "1",
            "codexNative": True,
            "detail": "MCP env enables dashboard/service autostart" if root_mcp.get("env", {}).get("TRADINGCODEX_MCP_AUTOSTART_SERVICE") == "1" else "missing TRADINGCODEX_MCP_AUTOSTART_SERVICE=1",
        },
        {
            "layer": "enforcement",
            "name": "TradingCodex MCP safe tools auto-approved",
            "ok": root_mcp.get("default_tools_approval_mode") == "approve",
            "codexNative": True,
            "detail": "default tool approval is approve" if root_mcp.get("default_tools_approval_mode") == "approve" else "default tool approval should be approve",
        },
        {
            "layer": "enforcement",
            "name": "head-manager MCP execution submit excluded",
            "ok": "submit_approved_order" not in root_tools,
            "codexNative": True,
            "detail": "root allowlist excludes submit_approved_order" if "submit_approved_order" not in root_tools else "root allowlist includes submit_approved_order",
        },
        {
            "layer": "enforcement",
            "name": "head-manager External MCP Gate tools configured",
            "ok": {"list_external_mcp_connections", "discover_external_mcp_connection", "review_external_mcp_tool"}.issubset(root_tools),
            "codexNative": True,
            "detail": "root allowlist includes External MCP Gate lifecycle tools" if {"list_external_mcp_connections", "discover_external_mcp_connection", "review_external_mcp_tool"}.issubset(root_tools) else "missing External MCP Gate lifecycle tools",
        },
        {
            "layer": "enforcement",
            "name": "head-manager broker connector tools configured",
            "ok": broker_connector_tools.issubset(root_tools),
            "codexNative": True,
            "detail": "root allowlist includes native connector management tools" if broker_connector_tools.issubset(root_tools) else "missing native connector management tools",
        },
        {
            "layer": "enforcement",
            "name": "execution-operator MCP execution allowlist configured",
            "ok": "submit_approved_order" in execution_tools,
            "codexNative": True,
            "detail": "execution-operator allowlist includes submit_approved_order" if "submit_approved_order" in execution_tools else "missing submit_approved_order",
        },
        {
            "layer": "enforcement",
            "name": "non-execution roles block execution MCP tools",
            "ok": not non_execution_exposure,
            "codexNative": True,
            "detail": "submit/cancel disabled outside execution-operator" if not non_execution_exposure else "; ".join(non_execution_exposure),
        },
        {
            "layer": "enforcement",
            "name": "execution-operator raw broker MCP tools excluded",
            "ok": raw_broker_tools.isdisjoint(execution_tools),
            "codexNative": True,
            "detail": "execution-operator uses TradingCodex execution tools only" if raw_broker_tools.isdisjoint(execution_tools) else f"raw broker tools exposed: {', '.join(sorted(raw_broker_tools & execution_tools))}",
        },
        {
            "layer": "enforcement",
            "name": "risk-manager MCP approval allowlist configured",
            "ok": "request_order_approval" in risk_tools and "submit_approved_order" not in risk_tools,
            "codexNative": True,
            "detail": "risk-manager can approve but not submit" if "request_order_approval" in risk_tools and "submit_approved_order" not in risk_tools else "risk-manager approval/submit allowlist mismatch",
        },
    ]


def _read_codex_mcp_config(path: Path) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed.get("mcp_servers", {}).get("tradingcodex", {})


def _information_barrier_checks(root: Path) -> list[dict[str, Any]]:
    return [
        path_check(root, "information-barrier", "capabilities installed", ".tradingcodex/capabilities.yaml", False),
        path_check(root, "information-barrier", "information barriers installed", ".tradingcodex/policies/information-barriers.yaml", False),
        text_check(root, "information-barrier", "information barrier ownership contract installed", ".tradingcodex/policies/information-barriers.yaml", "future_role_change_requires", False),
        path_check(root, "information-barrier", "restricted list installed", ".tradingcodex/policies/restricted-list.yaml", False),
        path_check(root, "information-barrier", "approvals directory installed", "trading/approvals", False),
    ]


def _improvement_checks(root: Path) -> list[dict[str, Any]]:
    checks = _skill_projection_checks(root)
    for subagent in EXPECTED_SUBAGENTS:
        checks.append(path_check(root, "improvement", f"subagent installed: {subagent}", f".codex/agents/{subagent}.toml", True))
        checks.append(text_check(root, "improvement", f"subagent permissions profile: {subagent}", f".codex/agents/{subagent}.toml", f'default_permissions = "{ROLE_PERMISSION_PROFILES[subagent]}"', True))
    for skill in EXPECTED_SKILLS:
        checks.append(path_check(root, "improvement", f"skill installed: {skill}", _skill_check_path(skill), False))
    checks.append(path_check(root, "improvement", "agent index projected", ".tradingcodex/generated/agent-index.json", False))
    checks.append(path_check(root, "improvement", "skill index projected", ".tradingcodex/generated/skill-index.json", False))
    checks.append(path_check(root, "improvement", "projection manifest projected", ".tradingcodex/generated/projection-manifest.json", False))
    checks.append(text_check(root, "improvement", "no-overlap handoff contract installed", ".codex/prompts/base_instructions/head-manager.md", "Only accepted role artifacts move downstream", False))
    checks.append(text_check(root, "improvement", "decision quality spine installed", ".codex/prompts/base_instructions/head-manager.md", "Decision Quality Spine", False))
    checks.append(text_check(root, "improvement", "method profile routing installed", ".codex/prompts/base_instructions/head-manager.md", "listed-equity FCFF DCF", False))
    checks.append(text_check(root, "improvement", "workflow skill installed", ".agents/skills/tcx-workflow/SKILL.md", "validated workflow plan", False))
    checks.append(text_check(root, "improvement", "artifact supervisor loop skill installed", ".agents/skills/tcx-workflow/SKILL.md", "Artifact Supervisor Loop", False))
    checks.append(text_check(root, "improvement", "workflow intake hook installed", ".codex/hooks/tradingcodex_hook.py", "record_workflow_intake", True))
    checks.append(text_check(root, "improvement", "run-specific workflow session map installed", ".codex/hooks/tradingcodex_hook.py", "session-workflow-runs.json", True))
    checks.append(text_check(root, "improvement", "artifact follow-up contract schema installed", ".tradingcodex/schemas/research_artifact.schema.json", "follow_up_requests", False))
    checks.append(text_check(root, "improvement", "artifact improve schema installed", ".tradingcodex/schemas/research_artifact.schema.json", "improvements", False))
    checks.append({
        "layer": "improvement",
        "name": "loop state file current or not yet started",
        "ok": True,
        "warn": not (root / ".tradingcodex" / "mainagent" / "workflow-loop-state.json").exists(),
        "codexNative": True,
        "detail": "found .tradingcodex/mainagent/workflow-loop-state.json" if (root / ".tradingcodex" / "mainagent" / "workflow-loop-state.json").exists() else "no workflow-loop-state.json until a validated workflow plan is recorded",
    })
    improve_ledger = root / ".tradingcodex" / "mainagent" / "improve.jsonl"
    improve_index = root / ".tradingcodex" / "mainagent" / "improve-index.json"
    checks.append({
        "layer": "improvement",
        "name": "improve index current or not yet started",
        "ok": not improve_ledger.exists() or improve_index.exists(),
        "warn": not improve_ledger.exists(),
        "codexNative": True,
        "detail": "found .tradingcodex/mainagent/improve-index.json" if improve_index.exists() else "no improve ledger until records are captured" if not improve_ledger.exists() else f"missing improve-index.json; run {workspace_launcher_command()} workflow improve to rebuild",
    })
    checks.append(path_check(root, "improvement", "forecast ledger directory installed", "trading/forecasts", False))
    checks.append(text_check(root, "improvement", "build skill installed", ".agents/skills/tcx-build/SKILL.md", "Build mode may create live-capable providers", False))
    checks.append(text_check(root, "improvement", "strategy root skill config installed", ".codex/config.toml", "# BEGIN TradingCodex strategy skills", True))
    checks.append(path_check(root, "improvement", "postmortem workflow installed", ".tradingcodex/workflows/postmortem.yaml", False))
    return checks


def _skill_projection_checks(root: Path) -> list[dict[str, Any]]:
    try:
        state = build_projection_state(root)
    except Exception as exc:
        return [{"layer": "improvement", "name": "skill projection inventory", "ok": False, "codexNative": True, "detail": str(exc)}]
    checks: list[dict[str, Any]] = []
    for role in AGENT_SPECS:
        name = "head-manager projected skills current" if role == "head-manager" else f"subagent projected skills current: {role}"
        try:
            projection = inspect_skill_projection(root, role, state)
            if projection["ok"]:
                detail = "enabled skill paths exactly match managed projection"
            else:
                detail = "; ".join(
                    f"{label}={projection[key]}"
                    for label, key in (
                        ("missing", "missing_paths"),
                        ("extra", "extra_paths"),
                        ("unregistered", "unregistered_paths"),
                        ("duplicates", "duplicate_paths"),
                    )
                    if projection[key]
                )
            checks.append({"layer": "improvement", "name": name, "ok": projection["ok"], "codexNative": True, "detail": detail})
        except Exception as exc:
            checks.append({"layer": "improvement", "name": name, "ok": False, "codexNative": True, "detail": str(exc)})
    collisions = state["host_global_skill_collisions"]
    checks.append({
        "layer": "improvement",
        "name": "host-global skill name collisions",
        "ok": not collisions,
        "codexNative": True,
        "detail": "no managed skill name collisions" if not collisions else "; ".join(f"{item['id']}: {item['resolved_source_file']}" for item in collisions),
    })
    return checks


def _skill_check_path(skill: str) -> str:
    spec = SKILL_SPECS[skill]
    if spec.scope == "subagent_shared":
        return f".tradingcodex/subagents/skills/shared/{skill}/SKILL.md"
    if spec.scope == "subagent_role":
        role = spec.owner_roles[0]
        return f".tradingcodex/subagents/skills/{role}/{skill}/SKILL.md"
    return f".agents/skills/{skill}/SKILL.md"


def _mcp_checks(root: Path) -> list[dict[str, Any]]:
    return [
        text_check(root, "mcp", "MCP server instructions installed", ".tradingcodex/mcp/server.py", "approved action gateway", False),
    ]
