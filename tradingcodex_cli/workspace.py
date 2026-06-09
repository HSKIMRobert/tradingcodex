from __future__ import annotations

import json
import os
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.domain import (
    EXPECTED_SUBAGENTS,
    EXPECTED_SKILLS,
    ROLE_PERMISSION_PROFILES,
    ROLE_SKILL_MAP,
    USER_VISIBLE_SKILLS,
    build_subagent_starter_prompt,
    call_tool,
    create_approval_receipt,
    create_research_artifact,
    export_research_artifact_md,
    get_research_artifact,
    list_workflow_artifacts,
    list_research_artifacts,
    sanitize_id,
    search_research_artifacts,
    ensure_runtime_database,
    persist_workspace_context_if_available,
    validate_order_intent,
    tradingcodex_db_path,
    tradingcodex_home,
    write_audit_event,
    write_json,
)


def workspace_root() -> Path:
    return Path(os.environ.get("TRADINGCODEX_WORKSPACE_ROOT", os.getcwd())).resolve()


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_help()
        return
    command = argv.pop(0)
    root = workspace_root()
    try:
        if command == "doctor":
            doctor(root, _option_value(argv, "--layer") or "all")
        elif command == "subagents":
            subagents(root, argv)
        elif command == "skills":
            skills(root, argv)
        elif command == "policy":
            policy(root, argv)
        elif command == "mcp":
            mcp(root, argv)
        elif command == "db":
            db(root, argv)
        elif command == "validate":
            validate(root, argv)
        elif command == "risk-check":
            risk_check(root, argv)
        elif command == "approve":
            approve(root, argv)
        elif command == "quality-check":
            quality_check(root, argv)
        elif command == "audit":
            audit(root, argv)
        elif command == "postmortem":
            postmortem(root, argv)
        elif command == "research":
            research(root, argv)
        elif command == "explain-policy":
            print("TradingCodex policy model:")
            print("Principal -> Role -> Policy -> Action -> Resource -> Condition\n")
            print("Explicit deny wins. TradingCodex MCP is the only executable trading boundary.\n")
            print(_safe_read(root / ".tradingcodex" / "policies" / "access-policies.yaml"))
        else:
            raise ValueError(f"Unknown command: {command}")
    except Exception as exc:
        print(f"TradingCodex: {exc}", file=sys.stderr)
        sys.exit(1)


def doctor(root: Path, layer: str) -> None:
    allowed = {"all", "codex-native", "guidance", "enforcement", "information-barrier", "task-harness", "mcp", "service"}
    if layer not in allowed:
        raise ValueError(f'unknown layer "{layer}"')
    checks = []
    checks.extend(_central_service_checks(root))
    checks.extend(_guidance_checks(root))
    checks.extend(_enforcement_checks(root))
    checks.extend(_information_barrier_checks(root))
    checks.extend(_task_harness_checks(root))
    checks.extend(_mcp_checks(root))
    checks = [check for check in checks if layer == "all" or check["layer"] == layer or (layer == "codex-native" and check.get("codexNative"))]
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


def subagents(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "list":
        for agent in list_subagents(root):
            print(f"{agent['name']}\t{agent['description']}")
        return
    if sub == "prompt":
        request = " ".join(args).strip()
        if not request:
            raise ValueError("Usage: tcx subagents prompt <investment request>")
        print(build_subagent_starter_prompt(request))
        return
    if sub == "status":
        agents = list_subagents(root)
        print_json({
            "expected_count": len(EXPECTED_SUBAGENTS),
            "installed_count": len(agents),
            "fixed_roster_ok": len(agents) == len(EXPECTED_SUBAGENTS),
            "skills_installed": len(list_skills(root)),
            "thread_policy": read_thread_policy(root),
            "agents": agents,
        })
        return
    if sub == "state":
        print_json(read_subagent_state(root, _option_value(args, "--run")))
        return
    if sub == "plan":
        installed = list_subagents(root)
        requested = [agent["name"] for agent in installed] if "--all" in args else _parse_agent_list(args)
        if not requested:
            raise ValueError("Usage: tcx subagents plan <agent...>|--all")
        installed_names = {agent["name"] for agent in installed}
        unknown = [agent for agent in requested if agent not in installed_names]
        thread_policy = read_thread_policy(root)
        size = max(1, int(thread_policy["max_parallel_subagents"]))
        batches = [{"batch": i + 1, "agents": requested[i:i + size]} for i in range(0, len(requested), size)]
        print_json({
            "requested_count": len(requested),
            "requested_agents": requested,
            "all_fixed_roster": "--all" in args,
            "unknown_agents": unknown,
            "thread_policy": thread_policy,
            "parallel_spawn_ok": not unknown and len(batches) == 1,
            "required_batches": len(batches),
            "batches": batches,
            "recommendation": "spawn requested subagents in one batch" if len(batches) == 1 else "spawn each batch sequentially and hand off artifacts before starting the next batch",
        })
        if unknown:
            sys.exit(1)
        return
    if sub == "skills":
        role = args[0] if args else ""
        if role not in ROLE_SKILL_MAP:
            raise ValueError(f"Unknown subagent or role: {role}")
        print_json({"agent": role, "skills": skills_for_role(root, role)})
        return
    raise ValueError(f"Unknown subagents command: {sub}")


def skills(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "list":
        for skill in list_skills(root, include_internal="--all" in args):
            print(skill)
        return
    if sub == "inspect":
        name = args[0] if args else ""
        skill_path = root / ".agents" / "skills" / name / "SKILL.md"
        if not skill_path.exists():
            raise ValueError(f"Unknown skill: {name}")
        print(skill_path.read_text(encoding="utf-8"))
        return
    if sub in {"propose-add", "propose-update"}:
        target = _option_value(args, "--to")
        skill = _option_value(args, "--skill")
        if not target or not skill:
            raise ValueError(f"Usage: tcx skills {sub} --to <agent> --skill <skill>")
        print_json(write_skill_proposal(root, sub.replace("propose-", ""), target, skill))
        return
    if sub == "apply-proposal":
        proposal_path = Path(args[0]) if args else None
        if not proposal_path:
            raise ValueError("Usage: tcx skills apply-proposal <proposal.yaml> [--approved-by <principal>]")
        apply_skill_proposal(root, proposal_path if proposal_path.is_absolute() else root / proposal_path, _option_value(args, "--approved-by"))
        return
    raise ValueError(f"Unknown skills command: {sub}")


def policy(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] != "simulate":
        raise ValueError("Usage: tcx policy simulate --principal <id> --action <action> --resource <resource>")
    args = argv[1:]
    result = call_tool(root, "simulate_policy", {
        "principal_id": _option_value(args, "--principal") or "unknown",
        "action": _option_value(args, "--action") or "unknown",
        "resource": _option_value(args, "--resource") or "*",
        "require_approval_check": (_option_value(args, "--action") == "mcp.tradingcodex.submit_approved_order"),
    })
    print_json(result)
    if result.get("decision") != "allow":
        sys.exit(1)


def mcp(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print_mcp_help()
        return
    if argv and argv[0] == "stdio":
        from tradingcodex_cli.mcp_stdio import run_stdio
        from tradingcodex_cli.service_autostart import maybe_autostart_service

        maybe_autostart_service(root)
        run_stdio(root)
        return
    if argv and argv[0] in {"ledger", "calls"}:
        mcp_ledger(root, argv[1:])
        return
    if not argv or argv[0] != "call":
        raise ValueError("Usage: tcx mcp call <tool> [--order-intent file] [--approval-receipt file] [--order-id id] | tcx mcp ledger [--tool name] | tcx mcp stdio")
    tool = argv[1] if len(argv) > 1 else ""
    args = argv[2:]
    order_path = _option_value(args, "--order-intent")
    receipt_path = _option_value(args, "--approval-receipt")
    principal_id = _option_value(args, "--principal")
    payload: dict[str, Any] = {}
    if principal_id:
        payload["principal_id"] = principal_id
    payload.update({
        "order_intent_id": _option_value(args, "--order-intent-id"),
        "order_id": _option_value(args, "--order-id"),
        "artifact_id": _option_value(args, "--artifact-id") or _option_value(args, "--id"),
        "artifact_type": _option_value(args, "--type"),
        "universe": _option_value(args, "--universe"),
        "workflow_type": _option_value(args, "--workflow-type"),
        "symbol": _option_value(args, "--symbol"),
        "title": _option_value(args, "--title"),
        "markdown": _option_value(args, "--markdown"),
        "markdown_path": _option_value(args, "--markdown-file") or _option_value(args, "--file"),
        "source_as_of": _option_value(args, "--source-as-of"),
        "readiness_label": _option_value(args, "--readiness"),
        "query": _option_value(args, "--query") or _option_value(args, "--q"),
        "limit": _option_value(args, "--limit"),
    })
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    for raw in args:
        if raw.startswith("{"):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("positional JSON MCP payload must be an object")
            payload.update(parsed)
    if order_path:
        payload["order_intent"] = json.loads((root / order_path).read_text(encoding="utf-8"))
    if receipt_path:
        payload["approval_receipt"] = json.loads((root / receipt_path).read_text(encoding="utf-8"))
    result = call_tool(root, tool, payload)
    print_json(result)
    if result.get("status") in {"rejected", "not_supported"} or result.get("decision") == "deny" or result.get("valid") is False:
        sys.exit(1)


def mcp_ledger(root: Path, args: list[str]) -> None:
    ensure_runtime_database(root)
    from apps.mcp.models import McpToolCall

    queryset = McpToolCall.objects.all()
    tool = _option_value(args, "--tool")
    principal = _option_value(args, "--principal")
    status = _option_value(args, "--status")
    if tool:
        queryset = queryset.filter(tool_name=tool)
    if principal:
        queryset = queryset.filter(principal_id=principal)
    if status:
        queryset = queryset.filter(status=status)
    limit = max(1, min(int(_option_value(args, "--limit") or 20), 200))
    print_json({
        "count": queryset.count(),
        "db_path": str(tradingcodex_db_path()),
        "central_ledger": True,
        "calls": [
            {
                "created_at": call.created_at.isoformat(),
                "tool_name": call.tool_name,
                "principal_id": call.principal_id,
                "status": call.status,
                "workspace_context": call.workspace_context,
                "request_hash": call.request_hash,
                "result_hash": call.result_hash,
                "error": call.error,
                "duration_ms": call.duration_ms,
            }
            for call in queryset[:limit]
        ],
    })


def print_mcp_help() -> None:
    print("""TradingCodex MCP

Usage:
  ./tcx mcp call <tool> [--principal <role>] [tool args]
  ./tcx mcp ledger [--tool <name>] [--principal <role>] [--status ok]
  ./tcx mcp stdio

Examples:
  ./tcx mcp call create_research_artifact --principal fundamental-analyst --artifact-id note-1 --title "Note" --markdown "# Note" --symbol MSFT
  ./tcx mcp call submit_approved_order --order-intent-id approved-order-id
  ./tcx mcp ledger --tool create_research_artifact --status ok
""")


def db(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "status"
    if sub == "path":
        print(str(tradingcodex_db_path()))
        return
    if sub == "migrate":
        ensure_runtime_database(root)
        print_json({"status": "migrated", "db_path": str(tradingcodex_db_path()), "db_canonical": True, "workspace_context": persist_workspace_context_if_available(root)})
        return
    if sub == "status":
        ensure_runtime_database(root)
        db_path = tradingcodex_db_path()
        print_json({
            "status": "ok",
            "home": str(tradingcodex_home()),
            "db_path": str(db_path),
            "db_exists": db_path.exists(),
            "workspace_root": str(root),
            "workspace_is_provenance_only": True,
            "db_canonical": True,
            "workspace_context": persist_workspace_context_if_available(root),
        })
        return
    raise ValueError("Usage: tcx db status|path|migrate")


def validate(root: Path, argv: list[str]) -> None:
    if len(argv) < 2 or argv[0] != "order":
        raise ValueError("Usage: tcx validate order <order-intent.json>")
    order = json.loads((root / argv[1]).read_text(encoding="utf-8"))
    result = validate_order_intent(root, {"principal_id": "portfolio-manager", "order_intent": order})
    write_audit_event(root, {"type": "order_intent.validated" if result["valid"] else "order_intent.validation_failed", "payload": result}, "portfolio-manager", "cli")
    print_json(result)
    if not result["valid"]:
        sys.exit(1)


def risk_check(root: Path, argv: list[str]) -> None:
    file_path = argv[0] if argv else _option_value(argv, "--order-intent")
    if not file_path:
        raise ValueError("Usage: tcx risk-check <order-intent.json>")
    order = json.loads((root / file_path).read_text(encoding="utf-8"))
    validation = validate_order_intent(root, {"principal_id": "risk-manager", "order_intent": order})
    result = {"decision": "go" if validation["valid"] else "revise", "order_intent_id": order.get("id"), "reasons": validation["reasons"], "checks": {"schema": not any(reason.startswith("missing ") for reason in validation["reasons"]), "policy": validation["policy"]["decision"]}}
    write_audit_event(root, {"type": "risk_check", "payload": result}, "risk-manager", "cli")
    print_json(result)
    if result["decision"] != "go":
        sys.exit(1)


def approve(root: Path, argv: list[str]) -> None:
    file_path = argv[0] if argv else _option_value(argv, "--order-intent")
    if not file_path:
        raise ValueError("Usage: tcx approve <draft-order-intent.json> [--approved-by risk-manager]")
    order = json.loads((root / file_path).read_text(encoding="utf-8"))
    result = create_approval_receipt(root, order, _option_value(argv, "--approved-by") or "risk-manager", int(_option_value(argv, "--expires-hours") or 24))
    print_json(result)
    if result.get("status") == "rejected":
        sys.exit(1)


def quality_check(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print("Canonical research paths: trading/research/*.evidence.md; trading/reports/<role>/*")
        return
    path = root / argv[0]
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(root).as_posix()
    result = {"path": rel, "exists": True, "bytes": len(text.encode()), "non_empty": bool(text), "artifact_type": classify_artifact_path(rel), "json_valid": None, "required_fields_missing": [], "warnings": []}
    if rel.endswith(".json"):
        try:
            data = json.loads(text)
            result["json_valid"] = True
            if "order_intent" in rel:
                result["required_fields_missing"] = [field for field in ["id", "symbol", "side", "quantity", "broker", "created_by"] if data.get(field) in (None, "")]
        except Exception:
            result["json_valid"] = False
    result["status"] = "fail" if not result["non_empty"] or result["json_valid"] is False or result["required_fields_missing"] else "pass"
    print_json(result)
    if result["status"] != "pass":
        sys.exit(1)


def audit(root: Path, argv: list[str]) -> None:
    tail = int(_option_value(argv, "--tail") or 20)
    entries = []
    for path in sorted((root / "trading" / "audit").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append((path.name, line))
    for file, line in entries[-tail:]:
        print(f"{file}\t{line}")


def postmortem(root: Path, argv: list[str]) -> None:
    if not argv or argv[0] != "create":
        raise ValueError("Usage: tcx postmortem create --trigger <trigger> [--tail n]")
    trigger = _option_value(argv, "--trigger") or "manual"
    report = {"id": f"postmortem-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}", "created_by": _option_value(argv, "--created-by") or "head-manager", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "trigger": trigger, "findings": [{"category": "audit-summary", "summary": "Reviewed recent audit events.", "evidence_count": 0}], "next_actions": ["Review rejected or adapter_error events before the next execution-sensitive workflow."]}
    path = root / "trading" / "reports" / "postmortem" / f"{sanitize_id(report['id'])}.postmortem_report.json"
    write_json(path, report)
    write_audit_event(root, {"type": "postmortem.created", "payload": {"id": report["id"], "path": path.relative_to(root).as_posix()}}, "head-manager", "cli")
    print_json({"status": "created", "id": report["id"], "path": path.relative_to(root).as_posix()})


def research(root: Path, argv: list[str]) -> None:
    sub = argv[0] if argv else "list"
    args = argv[1:]
    if sub == "create":
        markdown_file = _option_value(args, "--markdown-file") or _option_value(args, "--file")
        if not markdown_file:
            raise ValueError("Usage: tcx research create --markdown-file <file.md> [--id <id>] [--title <title>]")
        payload = {
            "artifact_id": _option_value(args, "--id"),
            "artifact_type": _option_value(args, "--type") or "research_memo",
            "universe": _option_value(args, "--universe") or "public_equity",
            "workflow_type": _option_value(args, "--workflow-type") or "",
            "symbol": _option_value(args, "--symbol") or "",
            "title": _option_value(args, "--title") or Path(markdown_file).stem,
            "markdown_path": markdown_file,
            "readiness_label": _option_value(args, "--readiness") or "",
            "created_by": _option_value(args, "--created-by") or "head-manager",
            "export_path": _option_value(args, "--export-path"),
        }
        print_json(create_research_artifact(root, payload))
        return
    if sub == "get":
        artifact_id = args[0] if args and not args[0].startswith("--") else _option_value(args, "--id")
        if not artifact_id:
            raise ValueError("Usage: tcx research get <artifact-id>")
        print_json(get_research_artifact(root, {"artifact_id": artifact_id}))
        return
    if sub == "list":
        print_json(list_research_artifacts(root, {
            "artifact_type": _option_value(args, "--type"),
            "universe": _option_value(args, "--universe"),
            "symbol": _option_value(args, "--symbol"),
            "limit": _option_value(args, "--limit") or 50,
        }))
        return
    if sub == "search":
        query = " ".join(args).strip()
        if not query:
            raise ValueError("Usage: tcx research search <query>")
        print_json(search_research_artifacts(root, {"query": query}))
        return
    if sub == "export":
        artifact_id = args[0] if args and not args[0].startswith("--") else _option_value(args, "--id")
        if not artifact_id:
            raise ValueError("Usage: tcx research export <artifact-id> [--export-path <file.md>]")
        print_json(export_research_artifact_md(root, {"artifact_id": artifact_id, "export_path": _option_value(args, "--export-path")}))
        return
    raise ValueError(f"Unknown research command: {sub}")


def list_subagents(root: Path) -> list[dict[str, str]]:
    agents = []
    for path in sorted((root / ".codex" / "agents").glob("*.toml")):
        text = path.read_text(encoding="utf-8")
        name = _toml_string(text, "name") or path.stem
        agents.append({"name": name, "runtime_label": name, "description": _toml_string(text, "description") or ""})
    return agents


def list_skills(root: Path, include_internal: bool = True) -> list[str]:
    skill_dir = root / ".agents" / "skills"
    if not skill_dir.exists():
        return []
    installed = {path.name for path in skill_dir.iterdir() if path.is_dir()}
    if include_internal:
        return sorted(installed)
    return [skill for skill in USER_VISIBLE_SKILLS if skill in installed]


def read_thread_policy(root: Path) -> dict[str, Any]:
    config = _safe_read(root / ".codex" / "config.toml")
    tc_config = _safe_read(root / ".tradingcodex" / "config.yaml")
    max_threads = int(_regex(config, r"^max_threads\s*=\s*(\d+)", "1"))
    max_depth = int(_regex(config, r"^max_depth\s*=\s*(\d+)", "1"))
    reserved = int(_regex(tc_config, r"^\s*reserved_threads:\s*(\d+)", "0"))
    return {"max_threads": max_threads, "max_depth": max_depth, "reserved_threads": reserved, "max_parallel_subagents": max(1, max_threads - reserved), "overflow_strategy": _regex(tc_config, r"^\s*overflow_strategy:\s*([A-Za-z0-9_-]+)", "batch_queue")}


def read_subagent_state(root: Path, run_id: str | None) -> dict[str, Any]:
    state = _read_json(root / ".tradingcodex" / "mainagent" / "subagent-session-state.json", {"updated_at": None, "active": {}, "completed": [], "events": []})
    if not run_id:
        return {"run_filter": None, **state}
    return {
        "run_filter": run_id,
        "updated_at": state.get("updated_at"),
        "active": {role: record for role, record in state.get("active", {}).items() if record.get("run_id") == run_id},
        "completed": [record for record in state.get("completed", []) if record.get("run_id") == run_id],
        "events": [record for record in state.get("events", []) if record.get("run_id") == run_id],
    }


def skills_for_role(root: Path, role: str) -> list[str]:
    applied = []
    for line in _safe_read(root / ".tradingcodex" / "mainagent" / "applied-skill-changes.jsonl").splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        if record.get("target") == role and record.get("skill"):
            applied.append(record["skill"])
    return [skill for skill in dict.fromkeys(ROLE_SKILL_MAP.get(role, []) + applied) if (root / ".agents" / "skills" / skill / "SKILL.md").exists()]


def write_skill_proposal(root: Path, type_: str, target: str, skill: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    proposal_id = f"skill-{type_}-{target}-{skill}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
    path = root / ".tradingcodex" / "mainagent" / "skill-change-proposals" / f"{sanitize_id(proposal_id)}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([f"id: {proposal_id}", f"type: {type_}", f"target: {target}", f"skill: {skill}", f"created_at: {now.isoformat().replace('+00:00', 'Z')}", "requires_validation: true", "requires_audit: true", "status: proposed", ""]), encoding="utf-8")
    write_audit_event(root, {"type": "skill_change.proposed", "payload": {"id": proposal_id, "type": type_, "target": target, "skill": skill, "path": path.relative_to(root).as_posix()}}, "head-manager", "cli")
    return {"status": "proposed", "id": proposal_id, "path": path.relative_to(root).as_posix()}


def apply_skill_proposal(root: Path, proposal_path: Path, approved_by: str | None) -> None:
    text = proposal_path.read_text(encoding="utf-8")
    type_ = _yaml_value(text, "type") or "update"
    target = _yaml_value(text, "target")
    skill = _yaml_value(text, "skill")
    if not target or not skill:
        raise ValueError("Invalid skill proposal")
    execution_sensitive = target == "execution-operator" or "execute" in skill or "order" in skill
    if execution_sensitive and not approved_by:
        raise ValueError("execution-sensitive skill changes require --approved-by <principal>")
    record = {"applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "proposal_path": proposal_path.relative_to(root).as_posix(), "type": type_, "target": target, "skill": skill, "approved_by": approved_by, "execution_sensitive": execution_sensitive}
    with (root / ".tradingcodex" / "mainagent" / "applied-skill-changes.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_audit_event(root, {"type": "skill_change.applied", "payload": record}, approved_by or "head-manager", "cli")
    print_json({"status": "applied", **record})


def _guidance_checks(root: Path) -> list[dict[str, Any]]:
    return [
        path_check(root, "guidance", "AGENTS.md installed", "AGENTS.md", True),
        text_check(root, "guidance", "head-manager developer_instructions configured", ".codex/config.toml", "You are `head-manager`", True),
        path_check(root, "guidance", "local CLI wrapper installed", "tcx", False),
        text_check(root, "guidance", "hooks configured", ".codex/hooks.json", "\"PreToolUse\"", True),
        text_check(root, "guidance", "scenario quality gates configured", ".codex/config.toml", "scenario-quality-gates", True),
        text_check(root, "guidance", "investment workflow map configured", ".codex/config.toml", "investment-workflow-map", True),
        {"layer": "guidance", "name": "subagent max_threads matches roster", "ok": read_thread_policy(root)["max_threads"] == len(list_subagents(root)), "codexNative": True, "detail": f"max_threads={read_thread_policy(root)['max_threads']}, subagents={len(list_subagents(root))}"},
    ]


def _central_service_checks(root: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
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
        from apps.mcp.models import McpToolCall

        McpToolCall.objects.count()
        checks.append({"layer": "service", "name": "central MCP ledger reachable", "ok": True, "codexNative": False, "detail": "McpToolCall table available"})
    except Exception as exc:
        checks.append({"layer": "service", "name": "central DB reachable", "ok": False, "codexNative": False, "detail": str(exc)})
    export_dirs = ["trading/research", "trading/reports", "trading/audit", "trading/orders", "trading/approvals"]
    for rel in export_dirs:
        path = root / rel
        checks.append({"layer": "service", "name": f"workspace export/cache writable: {rel}", "ok": path.exists() and os.access(path, os.W_OK), "codexNative": False, "detail": "writable" if path.exists() and os.access(path, os.W_OK) else "missing or not writable"})
    return checks


def _enforcement_checks(root: Path) -> list[dict[str, Any]]:
    schemas = ["evidence_pack.schema.json", "fundamental_report.schema.json", "technical_report.schema.json", "news_report.schema.json", "thesis.schema.json", "valuation.schema.json", "portfolio_review.schema.json", "risk_report.schema.json", "order_intent.schema.json", "approval_receipt.schema.json", "execution_result.schema.json", "postmortem_report.schema.json", "audit_event.schema.json"]
    return [
        text_check(root, "enforcement", "command rules configured", ".codex/rules/tradingcodex.rules", "prefix_rule(", True),
        *_codex_mcp_config_checks(root),
        path_check(root, "enforcement", "TradingCodex MCP installed", ".tradingcodex/mcp/server.py", False),
        {"layer": "enforcement", "name": "live broker disabled by default", "ok": not (root / ".tradingcodex" / "mcp" / "adapters" / "live.py").exists(), "detail": "live.py adapter absent"},
        *[path_check(root, "enforcement", f"schema installed: {schema}", f".tradingcodex/schemas/{schema}", False) for schema in schemas],
    ]


def _codex_mcp_config_checks(root: Path) -> list[dict[str, Any]]:
    root_mcp = _read_codex_mcp_config(root / ".codex" / "config.toml")
    execution_mcp = _read_codex_mcp_config(root / ".codex" / "agents" / "execution-operator.toml")
    risk_mcp = _read_codex_mcp_config(root / ".codex" / "agents" / "risk-manager.toml")
    root_tools = set(root_mcp.get("enabled_tools") or [])
    execution_tools = set(execution_mcp.get("enabled_tools") or [])
    risk_tools = set(risk_mcp.get("enabled_tools") or [])
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
            "name": "head-manager MCP execution submit excluded",
            "ok": "submit_approved_order" not in root_tools,
            "codexNative": True,
            "detail": "root allowlist excludes submit_approved_order" if "submit_approved_order" not in root_tools else "root allowlist includes submit_approved_order",
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
            "name": "risk-manager MCP approval allowlist configured",
            "ok": "create_approval_receipt" in risk_tools and "submit_approved_order" not in risk_tools,
            "codexNative": True,
            "detail": "risk-manager can approve but not submit" if "create_approval_receipt" in risk_tools and "submit_approved_order" not in risk_tools else "risk-manager approval/submit allowlist mismatch",
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
        path_check(root, "information-barrier", "restricted list installed", ".tradingcodex/policies/restricted-list.yaml", False),
        path_check(root, "information-barrier", "approvals directory installed", "trading/approvals", False),
    ]


def _task_harness_checks(root: Path) -> list[dict[str, Any]]:
    checks = []
    for subagent in EXPECTED_SUBAGENTS:
        checks.append(path_check(root, "task-harness", f"subagent installed: {subagent}", f".codex/agents/{subagent}.toml", True))
        checks.append(text_check(root, "task-harness", f"subagent permissions profile: {subagent}", f".codex/agents/{subagent}.toml", f'default_permissions = "{ROLE_PERMISSION_PROFILES[subagent]}"', True))
    for skill in EXPECTED_SKILLS:
        checks.append(path_check(root, "task-harness", f"skill installed: {skill}", f".agents/skills/{skill}/SKILL.md", False))
    checks.append(path_check(root, "task-harness", "head-manager interview profile installed", ".tradingcodex/mainagent/head-manager-interview.md", False))
    checks.append(path_check(root, "task-harness", "postmortem workflow installed", ".tradingcodex/workflows/postmortem.yaml", False))
    return checks


def _mcp_checks(root: Path) -> list[dict[str, Any]]:
    return [
        path_check(root, "mcp", "stub execution adapter installed", ".tradingcodex/mcp/adapters/stub-execution.py", False),
        path_check(root, "mcp", "paper trading adapter installed", ".tradingcodex/mcp/adapters/paper-trading.py", False),
        path_check(root, "mcp", "live adapter contract installed", ".tradingcodex/mcp/adapters/live-adapter.contract.md", False),
        text_check(root, "mcp", "MCP server instructions installed", ".tradingcodex/mcp/server.py", "approved action gateway", False),
    ]


def path_check(root: Path, layer: str, name: str, rel: str, codex_native: bool) -> dict[str, Any]:
    ok = (root / rel).exists()
    return {"layer": layer, "name": name, "ok": ok, "codexNative": codex_native, "detail": "found" if ok else "missing"}


def text_check(root: Path, layer: str, name: str, rel: str, pattern: str, codex_native: bool) -> dict[str, Any]:
    ok = pattern in _safe_read(root / rel)
    return {"layer": layer, "name": name, "ok": ok, "codexNative": codex_native, "detail": f"contains {pattern}" if ok else f"missing {pattern}"}


def classify_artifact_path(rel: str) -> str:
    if rel.startswith("trading/research/"):
        return "evidence_pack"
    if "order_intent" in rel:
        return "order_intent"
    if "approval_receipt" in rel:
        return "approval_receipt"
    if rel.startswith("trading/reports/"):
        return "report"
    return "artifact"


def print_help() -> None:
    print("""TradingCodex

Usage:
  tcx doctor [--layer service|guidance|enforcement|information-barrier|task-harness|mcp|codex-native]
  tcx subagents list|status|state|plan|skills|prompt
  tcx skills list [--all]|inspect|propose-add|propose-update|apply-proposal
  tcx policy simulate --principal <id> --action <action> --resource <resource>
  tcx db status|path|migrate
  tcx mcp call <tool>
  tcx mcp ledger [--tool <name>] [--principal <id>] [--status ok]
  tcx mcp stdio
  tcx research create|get|list|search|export
  tcx quality-check <artifact>
""")


def _option_value(args: list[str], name: str) -> str | None:
    try:
        return args[args.index(name) + 1]
    except Exception:
        return None


def _parse_agent_list(args: list[str]) -> list[str]:
    return [item.strip() for arg in args for item in arg.split(",") if item.strip()]


def _toml_string(text: str, key: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{key} = "):
            return line.split('"')[1]
    return None


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _regex(text: str, pattern: str, default: str) -> str:
    import re

    match = re.search(pattern, text, flags=re.M)
    return match.group(1) if match else default


def _yaml_value(text: str, key: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return None


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
