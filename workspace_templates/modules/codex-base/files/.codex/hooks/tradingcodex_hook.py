#!/usr/bin/env python3
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", str(ROOT))

from tradingcodex_service.application.agents import EXPECTED_SUBAGENTS  # noqa: E402
from tradingcodex_service.application.common import atomic_write_text, safe_workspace_path  # noqa: E402
from tradingcodex_service.application.workflow_planner import build_workflow_intake, compact_workflow_loop_state, explicit_strategy_invocation, read_workflow_intake, record_workflow_intake  # noqa: E402
from tradingcodex_service.application.workflow_state import transition_workflow_state  # noqa: E402
from tradingcodex_cli.startup_status import build_server_status, fallback_server_status  # noqa: E402

MAX_SESSION_EVENTS = 12
MAX_COMPLETED_RECORDS = 12
SESSION_RUNS_PATH = ROOT / ".tradingcodex" / "mainagent" / "session-workflow-runs.json"
WORKBENCH_RUN = os.environ.get("TRADINGCODEX_WORKBENCH_RUN") == "1"
WORKBENCH_BASH = {
    ("./tcx", "quality-check"),
}
WORKBENCH_MCP_ALLOWED = {
    "get_tradingcodex_status", "get_runtime_mode", "get_update_status", "record_workflow_plan",
    "record_artifact_supervisor_loop",
    "simulate_policy", "list_reconciliation_runs", "get_positions", "get_portfolio_snapshot",
    "list_workflow_artifacts", "create_research_artifact", "get_research_artifact",
    "list_research_artifacts", "search_research_artifacts", "append_research_artifact_version",
    "export_research_artifact_md", "record_source_snapshot", "create_research_spec",
    "get_research_spec", "list_research_specs", "create_replay_manifest", "record_experiment_run",
    "rebuild_research_index", "create_causal_equity_analysis", "record_blind_judgment_prior",
    "complete_judgment_review", "issue_forecast", "revise_forecast", "resolve_forecast",
    "score_forecast", "get_forecast", "list_forecasts", "get_forecast_calibration_report",
    "create_evaluation_corpus", "record_evaluation_run", "create_blind_review_assignment",
    "get_blind_review_packet", "record_blind_human_review", "compare_evaluation_runs",
    "record_audit_event",
}
HOOK_WRITE_ROOTS = (Path(".tradingcodex/mainagent"), Path("trading/audit"))


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if event == "session-start":
        session_start(payload)
    elif event == "user-prompt-submit":
        user_prompt_submit(payload)
    elif event in {"subagent-start", "subagent-stop"}:
        subagent_session_state(event, payload)
    elif event in {"pre-tool-use", "permission-request"}:
        policy_gate(event, payload)
    elif event == "post-tool-use":
        if WORKBENCH_RUN:
            append_hook_audit({"event": event, "workflow_run_id": resolve_workflow_run_id(payload), "tool_name": payload_tool_name(payload), "redacted": True})
        else:
            append_hook_audit({"event": event, "payload": payload})
    elif event == "stop":
        return


def session_start(payload: dict) -> None:
    try:
        server_status = build_server_status(ROOT)
    except Exception as exc:
        server_status = fallback_server_status(ROOT, exc)
        append_hook_audit({"event": "session-start", "warning": "server status check failed", "error": str(exc)})
    update_status = server_status["update_status"]
    service_detail = server_status.get("service_detail") or {}
    readiness = {
        "marker": "tradingcodex-session-context",
        "mode_status": server_status["mode_status"],
        "permission_status": server_status["permission_status"],
        "update_status": {
            "update_available": update_status["update_available"],
            "package_update_required": update_status["package_update_required"],
            "workspace_update_required": update_status["workspace_update_required"],
            "can_self_update": update_status["can_self_update"],
            "command": update_status["command"],
            "restart_required_after_update": update_status["restart_required_after_update"],
            "blocked_reason": update_status["head_manager_update_blocked_reason"],
        },
        "server_status": {
            "status_path": ".tradingcodex/mainagent/server-status.json",
            "dashboard_url": server_status["dashboard_url"],
            "service_status": server_status["service_status"],
            "service_issue": service_detail.get("issue", ""),
            "service_version": service_detail.get("version", ""),
            "package_version": service_detail.get("package_version", ""),
            "service_db_path": service_detail.get("db_path", ""),
            "expected_db_path": service_detail.get("expected_db_path", ""),
            "next_action": service_detail.get("next_action", ""),
            "startup_notice": server_status.get("startup_notice", ""),
            "restart_codex_required": server_status["restart_codex_required"],
            "recommended_action": server_status["recommended_action"],
        },
        "allowed_next_actions": server_status["allowed_next_actions"],
        "routing_status": {
            "lane": "startup",
            "selected_team": [],
            "blocked_actions": ["live_order", "raw secret", "direct broker API", "execution without approved artifacts"],
        },
    }
    write_json(ROOT / ".tradingcodex" / "mainagent" / "session-start.json", readiness)
    write_json(ROOT / ".tradingcodex" / "mainagent" / "server-status.json", server_status)
    append_hook_audit({"event": "session-start", "readiness": readiness})
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": json.dumps(readiness, ensure_ascii=False),
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def user_prompt_submit(payload: dict) -> None:
    prompt = payload.get("prompt") or payload.get("user_prompt") or payload.get("message") or ""
    if not prompt:
        return
    agent_type = payload.get("agent_type") or payload.get("subagent_type")
    if agent_type in EXPECTED_SUBAGENTS:
        return
    preallocated_run_id = str(os.environ.get("TRADINGCODEX_WORKFLOW_RUN_ID") or "").strip()
    followup = str(os.environ.get("TRADINGCODEX_WORKFLOW_FOLLOWUP") or "").lower() in {"1", "true", "yes", "on"}
    existing_intake = read_workflow_intake(ROOT, preallocated_run_id) if preallocated_run_id else {}
    if followup and preallocated_run_id:
        if not existing_intake:
            append_hook_audit({"event": "user-prompt-submit", "warning": "preallocated follow-up workflow intake is unavailable", "workflow_run_id": preallocated_run_id})
            return
        session_key = event_session_key(payload)
        if session_key:
            remember_session_run(session_key, preallocated_run_id)
        append_hook_audit({"event": "user-prompt-submit", "workflow_run_id": preallocated_run_id, "followup": True, "intake_hash": existing_intake.get("intake_hash", "")})
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": json.dumps({
            "marker": "tradingcodex-workflow-followup",
            "workflow_run_id": preallocated_run_id,
            "intake_path": existing_intake.get("intake_path", ""),
            "intake_hash": existing_intake.get("intake_hash", ""),
            "planning_instruction": "Continue the existing recorded TradingCodex workflow without replacing its original intake or widening its lane.",
        }, ensure_ascii=False)}}, ensure_ascii=False))
        return
    try:
        strategy_id = explicit_strategy_invocation(prompt)
        preview = build_workflow_intake(prompt, ROOT, workflow_run_id=preallocated_run_id)
    except Exception as exc:
        append_hook_audit({"event": "user-prompt-submit", "warning": "workflow intake failed", "error": str(exc)})
        workflow_binding_block(str(exc))
        return
    if not preview.get("requires_workflow_planning") and not preview.get("secret_warning"):
        return
    try:
        intake = existing_intake or record_workflow_intake(
            ROOT,
            prompt,
            workflow_run_id=preview["workflow_run_id"],
            strategy_id=strategy_id,
        )
    except Exception as exc:
        append_hook_audit({"event": "user-prompt-submit", "warning": "workflow binding failed", "error": str(exc)})
        workflow_binding_block(str(exc))
        return
    session_key = event_session_key(payload)
    if session_key:
        remember_session_run(session_key, intake["workflow_run_id"])
    append_hook_audit({
        "event": "user-prompt-submit",
        "workflow_run_id": intake["workflow_run_id"],
        "requires_workflow_planning": intake["requires_workflow_planning"],
        "investment_candidate": intake["investment_candidate"],
        "connector_build": intake["connector_build"],
        "secret_warning": intake["secret_warning"],
        "heuristic_lane": intake["heuristic_lane"],
        "heuristic_roles": intake["heuristic_roles"],
        "intake_hash": intake["intake_hash"],
        "prompt_sha256": intake["prompt_sha256"],
        "prompt_bytes": intake["prompt_bytes"],
    })
    additional_context = {
        "marker": intake["marker"],
        "workflow_run_id": intake["workflow_run_id"],
        "requires_workflow_planning": intake["requires_workflow_planning"],
        "intake_path": intake["intake_path"],
        "investment_candidate": intake["investment_candidate"],
        "connector_build": intake["connector_build"],
        "secret_warning": intake["secret_warning"],
        "explicit_negations": intake["explicit_negations"],
        "intake_hash": intake["intake_hash"],
        "heuristic_lane": intake["heuristic_lane"],
        "heuristic_roles": intake["heuristic_roles"],
        "blocked_actions": intake["blocked_actions"],
        "deterministic_hint": intake["deterministic_hint"],
        "planning_instruction": "Use $tcx-workflow to select the smallest sufficient candidate-role subset; submit workflow_run_id and selected_roles so the server compiles and records the staged plan before dispatch or investment analysis.",
    }
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": json.dumps(additional_context, ensure_ascii=False),
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def workflow_binding_block(message: str) -> None:
    context = {
        "marker": "tradingcodex-workflow-binding-blocked",
        "requires_workflow_planning": False,
        "blocked_actions": ["subagent dispatch", "investment analysis", "recommendation", "order drafting", "execution"],
        "planning_instruction": f"Workflow binding failed: {message[:500]}. Fix the workspace binding or select exactly one active $strategy-* skill, then submit a new request.",
    }
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": json.dumps(context, ensure_ascii=False)}}, ensure_ascii=False))


def subagent_session_state(event: str, payload: dict) -> None:
    state_path = ROOT / ".tradingcodex" / "mainagent" / "subagent-session-state.json"
    state = read_json(state_path, {
        "updated_at": None,
        "active": {},
        "completed": [],
        "events": [],
        "event_count_total": 0,
        "completed_count_total": 0,
    })
    run_id = resolve_workflow_run_id(payload)
    role = payload.get("agent_type") or payload.get("subagent_type") or payload.get("subagent") or payload.get("agent") or payload.get("task_name", "").split(" ")[0]
    event_count_total = int(state.get("event_count_total") or len(state.get("events", [])))
    completed_count_total = int(state.get("completed_count_total") or len(state.get("completed", [])))
    agent_session_id = subagent_session_id(payload, run_id, role)
    active_key = f"{run_id}:{role}:{agent_session_id}"
    existing_role_sessions = [
        item for item in state.get("active", {}).values()
        if item.get("run_id") == run_id and item.get("role") == role
    ] if isinstance(state.get("active"), dict) else []
    record = {
        "event": event,
        "role": role,
        "task_name": "" if WORKBENCH_RUN else payload.get("task_name"),
        "run_id": run_id,
        "agent_session_id": agent_session_id,
        "subagent_continuation": "continues_active_role_session" if event == "subagent-start" and existing_role_sessions else "new_or_reused_unknown",
        "ts": now(),
    }
    if event == "subagent-start":
        state.setdefault("active", {})[active_key] = record
    else:
        state.setdefault("active", {}).pop(active_key, None)
        for key, item in list(state.setdefault("active", {}).items()):
            if item.get("run_id") == run_id and item.get("role") == role and item.get("agent_session_id") == agent_session_id:
                state["active"].pop(key, None)
        state.setdefault("completed", []).append(record)
        state["completed"] = state["completed"][-MAX_COMPLETED_RECORDS:]
        state["completed_count_total"] = completed_count_total + 1
    state.setdefault("events", []).append(record)
    state["events"] = state["events"][-MAX_SESSION_EVENTS:]
    state["event_count_total"] = event_count_total + 1
    state["retention"] = {
        "events": f"last {MAX_SESSION_EVENTS}",
        "completed": f"last {MAX_COMPLETED_RECORDS}",
        "full_event_log": "trading/audit/subagent-session-events.jsonl",
    }
    state["updated_at"] = now()
    write_json(state_path, state)
    update_loop_state_for_subagent_event(event, role, record)
    append_jsonl(ROOT / "trading" / "audit" / "subagent-session-events.jsonl", record)


def update_loop_state_for_subagent_event(event: str, role: str, record: dict) -> None:
    run_id = str(record.get("run_id") or "")
    if not run_id:
        return
    def reduce_process_state(state: dict) -> dict:
        if not state or state.get("workflow_run_id") != run_id:
            raise ValueError("recorded workflow state is required for subagent events")
        pending = state.get("pending_tasks") if isinstance(state.get("pending_tasks"), list) else []
        for task in pending:
            task_roles = task.get("roles") if isinstance(task.get("roles"), list) else [task.get("role")]
            if role not in task_roles or task.get("stage_gate") not in {"ready", "complete"}:
                continue
            active_roles = task.get("active_roles") if isinstance(task.get("active_roles"), list) else []
            stopped_roles = task.get("completed_roles") if isinstance(task.get("completed_roles"), list) else []
            process_by_role = task.get("process_by_role") if isinstance(task.get("process_by_role"), dict) else {}
            if event == "subagent-start":
                active_roles = unique([*active_roles, role])
                process_by_role[role] = "running"
                task["process_status"] = "running"
                if task.get("stage_gate") != "complete":
                    task["status"] = "active"
            else:
                active_roles = [item for item in active_roles if item != role]
                stopped_roles = unique([*stopped_roles, role])
                process_by_role[role] = "stopped"
                task["process_status"] = "running" if active_roles else ("stopped" if set(task_roles).issubset(set(stopped_roles)) else "queued")
                if task.get("stage_gate") != "complete":
                    task["status"] = "waiting_for_artifact"
            task["active_roles"] = active_roles
            task["completed_roles"] = stopped_roles
            task["process_by_role"] = process_by_role
            task["updated_at"] = record["ts"]
            break
        state["pending_tasks"] = pending
        state["process_event_count"] = int(state.get("process_event_count") or 0) + 1
        state["stop_reason"] = "waiting_for_artifact_gate"
        return state

    try:
        transition_workflow_state(
            ROOT,
            run_id,
            event_type=event,
            reason="subagent process state changed; artifact and stage gates are unchanged",
            event_id=f"{event}:{record.get('agent_session_id')}:{record.get('ts')}",
            reducer=reduce_process_state,
            latest_projection=compact_workflow_loop_state,
            event_payload={"role": role, "agent_session_id": record.get("agent_session_id")},
        )
    except ValueError as exc:
        append_hook_audit({"event": event, "warning": "workflow process transition skipped", "error": str(exc), "workflow_run_id": run_id})


def unique(items: list) -> list:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def event_session_key(payload: dict) -> str:
    for key in ("session_id", "codex_session_id", "conversation_id", "thread_id", "transcript_path"):
        value = payload.get(key)
        if value:
            return f"{key}:{value}"
    session = payload.get("session")
    if isinstance(session, dict) and session.get("id"):
        return f"session.id:{session['id']}"
    return ""


def remember_session_run(session_key: str, run_id: str) -> None:
    mapping = read_json(SESSION_RUNS_PATH, {})
    if not isinstance(mapping, dict):
        mapping = {}
    mapping[session_key] = run_id
    write_json(SESSION_RUNS_PATH, mapping)


def resolve_workflow_run_id(payload: dict) -> str:
    for key in ("workflow_run_id", "run_id", "parent_run_id"):
        if payload.get(key):
            return str(payload[key])
    session_key = event_session_key(payload)
    mapping = read_json(SESSION_RUNS_PATH, {})
    if session_key and isinstance(mapping, dict) and mapping.get(session_key):
        return str(mapping[session_key])
    return ""


def subagent_session_id(payload: dict, run_id: str, role: str) -> str:
    for key in ("agent_session_id", "subagent_session_id", "subagent_id", "agent_id", "thread_id", "conversation_id"):
        if payload.get(key):
            return str(payload[key])
    return f"{run_id}:{role}"


def policy_gate(event: str, payload: dict) -> None:
    if event == "pre-tool-use" and WORKBENCH_RUN:
        try:
            reason = workbench_tool_block_reason(payload)
        except Exception:
            print(json.dumps({"decision": "block", "reason": "TradingCodex web tool policy could not be evaluated"}))
            return
        audited = append_hook_audit({
            "event": event,
            "workflow_run_id": resolve_workflow_run_id(payload),
            "tool_name": payload_tool_name(payload),
            "decision": "block" if reason else "allow",
            "redacted": True,
        })
        if not audited:
            print(json.dumps({"decision": "block", "reason": "TradingCodex web tool policy audit is unavailable"}))
            return
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
        return
    text = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = ["broker api", "api_key", "secret.read", "cash.withdraw", "policy.write"]
    if is_workflow_plan_command(payload) or payload_tool_name(payload).lower() in {
        "record_workflow_plan",
        "mcp__tradingcodex__record_workflow_plan",
    }:
        forbidden.remove("broker api")
    if any(item in text for item in forbidden):
        print(json.dumps({"decision": "block", "reason": "TradingCodex policy gate blocked sensitive request"}))


def payload_tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("tool") or payload.get("name") or "")[:180]


def workbench_tool_block_reason(payload: dict) -> str:
    tool_name = payload_tool_name(payload)
    lowered = tool_name.lower()
    if lowered in {"apply_patch", "edit", "write"}:
        return "TradingCodex web analysis blocks direct file-edit tools"
    if lowered == "bash":
        command = str((payload.get("tool_input") or payload.get("input") or {}).get("command") or "")
        if not workbench_bash_allowed(command):
            return "TradingCodex web analysis allows only artifact quality-check commands; record plans and supervisor-loop transitions through structured TradingCodex MCP tools"
    if lowered.startswith("mcp__tradingcodex__"):
        identifier = lowered.rsplit("__", 1)[-1]
        if identifier not in WORKBENCH_MCP_ALLOWED:
            return "TradingCodex web analysis blocks MCP tools outside the explicit analysis allowlist"
    elif lowered.startswith("mcp__"):
        return "TradingCodex web analysis blocks direct external MCP tools"
    return ""


def workbench_bash_allowed(command: str) -> bool:
    if not command or not re.fullmatch(r"[A-Za-z0-9_./:=+ -]+", command):
        return False
    try:
        argv = tuple(shlex.split(command))
    except ValueError:
        return False
    return any(argv[:len(prefix)] == prefix for prefix in WORKBENCH_BASH)


def is_workflow_plan_command(payload: dict) -> bool:
    command = json.dumps(payload.get("tool_input") or payload.get("input") or payload, ensure_ascii=False).lower()
    return (
        ".tradingcodex/mainagent/workflows/" in command
        and ".json" in command
        and "--plan" in command
        and ("tcx workflow validate" in command or "tcx workflow record" in command)
    )


def append_hook_audit(record: dict) -> bool:
    try:
        append_jsonl(ROOT / "trading" / "audit" / "codex-hooks.jsonl", {"ts": now(), **record})
    except Exception:
        return False
    return True


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value) -> None:
    target = safe_hook_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, value) -> None:
    target = safe_hook_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def safe_hook_path(path: Path) -> Path:
    lexical = path if path.is_absolute() else ROOT / path
    relative = lexical.relative_to(ROOT)
    current = ROOT
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("TradingCodex hook state path must not contain symlinks")
    return safe_workspace_path(ROOT, relative.as_posix(), allowed_roots=HOOK_WRITE_ROOTS)


if __name__ == "__main__":
    main()
