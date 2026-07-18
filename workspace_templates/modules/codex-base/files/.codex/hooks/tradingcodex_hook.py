#!/usr/bin/env python3
"""Keep native Codex work native; guard only TradingCodex safety boundaries."""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("TRADINGCODEX_WORKSPACE_ROOT", str(ROOT))

from tradingcodex_service.application.analysis_runs import (  # noqa: E402
    explicit_investment_brain_invocation,
    new_analysis_run_id,
    read_analysis_run,
)
from tradingcodex_service.application.common import atomic_write_text, safe_workspace_path  # noqa: E402
from tradingcodex_service.application.execution_gateway import (  # noqa: E402
    NativeExecutionInvocationError,
    OrderTurnInFlightError,
    execute_native_execution_mandate,
    issue_order_turn_grant,
    parse_native_execution_invocation,
    reserve_order_turn_grant,
    revoke_order_turn_grants,
)
from tradingcodex_service.application.skill_invocations import (  # noqa: E402
    SkillInvocationError,
    parse_first_meaningful_invocation,
)
from tradingcodex_cli.startup_status import build_server_status  # noqa: E402

SESSION_RUNS_PATH = ROOT / ".tradingcodex" / "mainagent" / "session-workflow-runs.json"
SUBAGENT_STATE_PATH = ROOT / ".tradingcodex" / "mainagent" / "subagent-session-state.json"
HOOK_WRITE_ROOTS = (Path(".tradingcodex/mainagent"), Path("trading/audit"))
ORDER_ALLOW_SKILL = "$tcx-order-allow"
ORDER_TURN_GRANT_TOOL = "use_order_turn_grant"
ORDER_TURN_GRANT_PROOF_FIELD = "_execution_turn_proof"
NATIVE_EXECUTION_MARKERS = frozenset({
    ORDER_ALLOW_SKILL,
    "$tcx-order-submit",
    "$tcx-order-cancel",
    "$execute-paper-order",
})
SECRET_PATH = re.compile(
    r"(?:^|[\\/])(?:\.env(?:\.|$)|\.netrc$|id_(?:rsa|ecdsa|ed25519)$|"
    r"credentials?(?:\.json)?$|secrets?(?:\.json)?$|\.aws[\\/])",
    re.I,
)
RAW_CREDENTIAL_ACCESS = re.compile(
    r"(?:^|[\s;&|])(?:cat|head|tail|less|more|sed|awk|grep|rg)\b[^\n]*"
    r"(?:\.env(?:\b|/|\\\\)|\.aws[/\\\\]credentials|\.netrc|\.ssh[/\\\\])|"
    r"\bprintenv\b|\bsecret\.read\b|\$(?:\{|\()?\w*(?:api[_-]?key|api[_-]?secret|"
    r"access[_-]?token|password|cookie)\w*",
    re.I,
)
DIRECT_ORDER_OR_BROKER = re.compile(
    r"(?:use_order_turn_grant|submit_approved_order|cancel_submitted_order|"
    r"raw_order_(?:submit|cancel)|order\.(?:submit|cancel)|broker\s+api)",
    re.I,
)
SERVICE_OWNED_PATH = re.compile(r"(?:^|[\\/])trading[\\/](?:audit|approvals|orders)(?:[\\/]|$)", re.I)


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    payload = read_payload(event)
    if payload is None:
        return
    if event == "session-start":
        session_start(payload)
    elif event == "user-prompt-submit":
        user_prompt_submit(payload)
    elif event in {"subagent-start", "subagent-stop"}:
        subagent_session_state(event, payload)
    elif event in {"pre-tool-use", "permission-request"}:
        policy_gate(event, payload)
    elif event == "stop":
        revoke_stopped_order_grant(payload)


def read_payload(event: str) -> dict | None:
    tool_event = event in {"pre-tool-use", "permission-request"}
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        if tool_event:
            block("TradingCodex safety hook requires a JSON object")
        return None
    if tool_event and (
        not isinstance(payload.get("tool_name"), str)
        or not payload["tool_name"].strip()
        or not isinstance(payload.get("tool_input"), dict)
    ):
        block("TradingCodex safety hook requires tool_name and object tool_input")
        return None
    return payload


def session_start(payload: dict) -> None:
    try:
        status = build_server_status(ROOT)
    except Exception as exc:
        append_hook_audit({"event": "session-start", "warning": "server_status_failed", "error": str(exc)[:180]})
        raise
    configured_run_id = str(os.environ.get("TRADINGCODEX_WORKFLOW_RUN_ID") or "").strip()
    bound_run = read_analysis_run(ROOT, configured_run_id) if configured_run_id else {}
    routing = {
        "workflow_run_id": str(bound_run.get("workflow_run_id") or configured_run_id),
        "run_status": "bound" if bound_run else "unbound",
        "run_start_tool": "begin_analysis_run" if not bound_run else "",
        "orchestration_owner": "codex-head-manager",
    }
    context = {
        "marker": "tradingcodex-session-context",
        "service_status": status.get("service_status", "unknown"),
        "dashboard_url": status.get("dashboard_url", ""),
        "restart_codex_required": bool(status.get("restart_codex_required")),
        "routing": routing,
        "planning_instruction": (
            "Answer narrow trusted facts and status requests directly. For investment analysis, begin one "
            "run only when needed and choose the smallest useful role set. Native Codex permissions govern "
            "ordinary workspace work; service calls govern TradingCodex state and final order effects."
        ),
    }
    write_json(ROOT / ".tradingcodex" / "mainagent" / "session-start.json", context)
    append_hook_audit({"event": "session-start", "service_status": context["service_status"], "redacted": True})
    output_context("SessionStart", context)


def user_prompt_submit(payload: dict) -> None:
    prompt = str(payload.get("prompt") or payload.get("user_prompt") or payload.get("message") or "")
    if not prompt:
        return
    marker = first_native_execution_marker(prompt)
    is_subagent = bool(payload.get("agent_type") or payload.get("subagent_type"))
    if not is_subagent and not revoke_prior_order_turn(payload, sensitive=bool(marker)):
        return
    if marker == ORDER_ALLOW_SKILL:
        grant_context = handle_order_allow_prompt(payload, prompt)
        if grant_context:
            context = analysis_prompt_context(payload, prompt)
            context["order_turn_grant"] = grant_context
            output_context("UserPromptSubmit", context)
        return
    if marker:
        handle_native_execution_prompt(payload, prompt)
        return
    if is_subagent:
        return
    analysis_context = analysis_prompt_context(payload, prompt)
    if analysis_context:
        output_context("UserPromptSubmit", analysis_context)


def first_native_execution_marker(prompt: str) -> str:
    try:
        invocation = parse_first_meaningful_invocation(prompt, NATIVE_EXECUTION_MARKERS, workspace_root=ROOT)
    except SkillInvocationError as exc:
        block(str(exc))
        return ""
    return invocation.marker if invocation is not None else ""


def revoke_prior_order_turn(payload: dict, *, sensitive: bool) -> bool:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return True
    try:
        revoke_order_turn_grants(ROOT, session_id, reason="new_user_turn", fail_if_authorizing=sensitive)
    except OrderTurnInFlightError:
        append_hook_audit({"event": "order-turn-grant-in-flight", "redacted": True})
        if sensitive:
            block("A prior TradingCodex order effect is still authorizing; inspect canonical order status first")
            return False
    except Exception:
        append_hook_audit({"event": "order-turn-grant-revoke-failed", "redacted": True})
        if sensitive:
            block("TradingCodex could not safely close prior order turn grants")
            return False
    return True


def analysis_prompt_context(payload: dict, prompt: str) -> dict:
    try:
        brain_id = explicit_investment_brain_invocation(prompt, ROOT)
    except ValueError as exc:
        return {
            "marker": "tradingcodex-agentic-analysis",
            "run_status": "blocked",
            "planning_instruction": f"Do not begin analysis: {exc}",
        }
    configured_run_id = str(os.environ.get("TRADINGCODEX_WORKFLOW_RUN_ID") or "").strip()
    existing = read_analysis_run(ROOT, configured_run_id) if configured_run_id else {}
    run_id = str(existing.get("workflow_run_id") or configured_run_id or new_analysis_run_id())
    session_key = event_session_key(payload)
    if session_key:
        remember_session_run(session_key, run_id)
    prompt_bytes = prompt.encode("utf-8")
    append_hook_audit({
        "event": "user-prompt-submit",
        "workflow_run_id": run_id,
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "prompt_bytes": len(prompt_bytes),
        "redacted": True,
    })
    if existing:
        return {
            "marker": "tradingcodex-agentic-analysis",
            "workflow_run_id": run_id,
            "run_status": "bound",
            "orchestration_owner": "codex-head-manager",
            "planning_instruction": "Continue the bound analysis and use only the next useful expertise or review.",
        }
    return {
        "marker": "tradingcodex-agentic-analysis",
        "workflow_run_id": run_id,
        "run_status": "unbound",
        "orchestration_owner": "codex-head-manager",
        "run_start_tool": "begin_analysis_run",
        "investment_brain_id": brain_id or "",
        "planning_instruction": (
            "If this is investment analysis, begin one run and choose the smallest useful role set. "
            "A narrow answer may stay direct and need no run, child, or artifact."
        ),
    }


def handle_order_allow_prompt(payload: dict, prompt: str) -> dict | None:
    if payload.get("agent_type") or payload.get("subagent_type"):
        block("Order turn grants are accepted only from a root native Codex user turn")
        return None
    if permission_mode(payload) in {"plan", "planning"}:
        block("TradingCodex order execution is unavailable while Codex is in Plan mode")
        return None
    session_id = str(payload.get("session_id") or "").strip()
    turn_id = str(payload.get("turn_id") or "").strip()
    cwd = str(payload.get("cwd") or "").strip()
    if not session_id or not turn_id or not cwd:
        block("Order turn grants require Codex session_id, turn_id, and cwd bindings")
        return None
    try:
        grant = issue_order_turn_grant(ROOT, prompt, session_id=session_id, turn_id=turn_id, cwd=cwd, permission_mode=permission_mode(payload))
    except (NativeExecutionInvocationError, PermissionError, ValueError) as exc:
        append_hook_audit({"event": "order-turn-grant-blocked", "reason_code": "invalid_invocation", "redacted": True})
        block(str(exc))
        return None
    except Exception:
        append_hook_audit({"event": "order-turn-grant-blocked", "reason_code": "service_unavailable", "redacted": True})
        block("TradingCodex order turn grant service is unavailable")
        return None
    append_hook_audit({"event": "order-turn-grant-issued", "mode": str(grant.get("mode") or ""), "redacted": True})
    return {
        "marker": "tradingcodex-order-turn-grant",
        "mode": str(grant.get("mode") or ""),
        "expires_at": str(grant.get("expires_at") or ""),
        "single_use": True,
        "allowed_tool": ORDER_TURN_GRANT_TOOL,
        "planning_instruction": (
            "Use at most one final submit or cancel through use_order_turn_grant after the canonical ticket, "
            "policy, risk, approval, idempotency, and audit gates. Never pass this authority to a subagent."
        ),
    }


def handle_native_execution_prompt(payload: dict, prompt: str) -> None:
    if payload.get("agent_type") or payload.get("subagent_type"):
        block("Native execution actions are accepted only from a root Codex user turn")
        return
    if permission_mode(payload) in {"plan", "planning"}:
        block("TradingCodex order execution is unavailable while Codex is in Plan mode")
        return
    try:
        mandate = parse_native_execution_invocation(prompt, ROOT)
    except NativeExecutionInvocationError as exc:
        block(str(exc))
        return
    if mandate is None:
        return
    if not append_hook_audit({"event": "native-execution-mandate", **mandate.audit_metadata()}):
        block("TradingCodex execution audit is unavailable; no action was attempted")
        return
    try:
        result = execute_native_execution_mandate(ROOT, mandate)
    except Exception:
        block("TradingCodex execution authorization failed; no action was attempted")
        return
    append_hook_audit({
        "event": "native-execution-result",
        "action": mandate.action,
        "ticket_id": mandate.ticket_id,
        "status": result.get("status", "error"),
        "redacted": True,
    })
    output_context("UserPromptSubmit", {
        "marker": "tradingcodex-native-execution-result",
        "result": result,
        "planning_instruction": "Report this service result only. Do not retry an uncertain action; inspect canonical order status.",
    })


def policy_gate(event: str, payload: dict) -> None:
    tool_name = payload_tool_name(payload)
    if is_native_spawn_tool(tool_name):
        append_hook_audit({
            "event": event,
            "workflow_run_id": resolve_workflow_run_id(payload),
            "tool_name": tool_name,
            "decision": "native_codex",
            **spawn_audit_metadata(payload),
            "redacted": True,
        })
        return
    if is_order_turn_grant_tool(tool_name):
        handle_order_turn_grant_tool(event, payload)
        return
    if tool_name.lower().startswith("mcp__tradingcodex__"):
        # Canonical services re-authorize every TradingCodex MCP operation.
        return
    reason = native_tool_block_reason(payload)
    if reason:
        append_hook_audit({
            "event": event,
            "workflow_run_id": resolve_workflow_run_id(payload),
            "tool_name": tool_name,
            "decision": "block",
            "reason": reason,
            "redacted": True,
        })
        block(reason)


def handle_order_turn_grant_tool(event: str, payload: dict) -> None:
    if payload.get("agent_type") or payload.get("subagent_type"):
        block("Only root Head Manager may use the current order turn grant")
        return
    if permission_mode(payload) in {"plan", "planning"}:
        block("TradingCodex order execution is unavailable while Codex is in Plan mode")
        return
    if event == "permission-request":
        return
    session_id = str(payload.get("session_id") or "").strip()
    turn_id = str(payload.get("turn_id") or "").strip()
    tool_use_id = str(payload.get("tool_use_id") or "").strip()
    tool_input = payload["tool_input"]
    if not session_id or not turn_id or not tool_use_id:
        block("Order execution requires current Codex session, turn, and tool-use bindings")
        return
    if ORDER_TURN_GRANT_PROOF_FIELD in tool_input:
        block("Order turn proof is hook-owned and cannot be supplied by the model")
        return
    try:
        proof = reserve_order_turn_grant(ROOT, session_id, turn_id, tool_use_id, tool_input, permission_mode=permission_mode(payload))
    except (PermissionError, ValueError) as exc:
        append_hook_audit({"event": event, "tool_name": ORDER_TURN_GRANT_TOOL, "decision": "block", "redacted": True})
        block(str(exc))
        return
    except Exception:
        append_hook_audit({"event": event, "tool_name": ORDER_TURN_GRANT_TOOL, "decision": "block", "reason_code": "service_unavailable", "redacted": True})
        block("TradingCodex order turn grant service is unavailable")
        return
    rewritten = dict(tool_input)
    rewritten[ORDER_TURN_GRANT_PROOF_FIELD] = proof
    append_hook_audit({"event": event, "tool_name": ORDER_TURN_GRANT_TOOL, "decision": "allow_once", "redacted": True})
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": rewritten}}))


def native_tool_block_reason(payload: dict) -> str:
    tool_name = payload_tool_name(payload).lower()
    tool_input = payload["tool_input"]
    serialized = json.dumps(tool_input, ensure_ascii=False)
    if any(SECRET_PATH.search(value) for value in string_values(tool_input)):
        return "TradingCodex native tools cannot read or write secret material"
    if any(SERVICE_OWNED_PATH.search(value) for value in string_values(tool_input)):
        return "TradingCodex order, approval, and audit records are service-owned"
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    if RAW_CREDENTIAL_ACCESS.search(command):
        return "TradingCodex native tools cannot read, print, or persist raw credential material"
    if DIRECT_ORDER_OR_BROKER.search(f"{tool_name} {serialized}"):
        return "Direct broker and order effects are blocked; use the canonical TradingCodex service gate"
    return ""


def subagent_session_state(event: str, payload: dict) -> None:
    role = str(payload.get("agent_type") or payload.get("subagent_type") or "generic").strip()[:80] or "generic"
    run_id = resolve_workflow_run_id(payload)
    session_id = subagent_session_id(payload, run_id, role)
    record = {
        "event": event,
        "role": role,
        "task_name": str(payload.get("task_name") or "")[:80],
        "run_id": run_id,
        "agent_session_id": session_id,
        "ts": now(),
    }
    state = read_json(SUBAGENT_STATE_PATH, {"active": {}, "events": []})
    active = state.setdefault("active", {})
    key = f"{run_id}:{session_id}"
    if event == "subagent-start":
        active[key] = record
    else:
        active.pop(key, None)
    events = state.setdefault("events", [])
    events.append(record)
    state["events"] = events[-12:]
    state["updated_at"] = now()
    write_json(SUBAGENT_STATE_PATH, state)
    append_jsonl(ROOT / "trading" / "audit" / "subagent-session-events.jsonl", record)


def revoke_stopped_order_grant(payload: dict) -> None:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return
    try:
        revoked = revoke_order_turn_grants(ROOT, session_id, turn_id=str(payload.get("turn_id") or "") or None, reason="turn_stopped")
    except Exception:
        append_hook_audit({"event": "order-turn-grant-revoke-failed", "redacted": True})
        return
    if revoked:
        append_hook_audit({"event": "order-turn-grant-revoked", "count": revoked, "redacted": True})


def payload_tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or "")[:180]


def is_order_turn_grant_tool(tool_name: str) -> bool:
    return tool_name.lower() in {ORDER_TURN_GRANT_TOOL, f"mcp__tradingcodex__{ORDER_TURN_GRANT_TOOL}"}


def is_native_spawn_tool(tool_name: str) -> bool:
    return tool_name.lower() in {"spawn_agent", "agentsspawn_agent"}


def spawn_audit_metadata(payload: dict) -> dict:
    tool_input = payload["tool_input"]
    message = str(tool_input.get("message") or "").encode("utf-8")
    return {
        "agent_type": str(tool_input.get("agent_type") or "")[:80],
        "task_name": str(tool_input.get("task_name") or "")[:80],
        "message_sha256": hashlib.sha256(message).hexdigest() if message else "",
        "message_bytes": len(message),
    }


def permission_mode(payload: dict) -> str:
    return str(payload.get("permission_mode") or payload.get("permissionMode") or "").strip().lower().replace("_", "-")


def event_session_key(payload: dict) -> str:
    for key in ("session_id", "codex_session_id", "conversation_id", "thread_id", "transcript_path"):
        if payload.get(key):
            return f"{key}:{payload[key]}"
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
    mapping = read_json(SESSION_RUNS_PATH, {})
    session_key = event_session_key(payload)
    if session_key and isinstance(mapping, dict) and mapping.get(session_key):
        return str(mapping[session_key])
    return ""


def subagent_session_id(payload: dict, run_id: str, role: str) -> str:
    for key in ("agent_session_id", "subagent_session_id", "subagent_id", "agent_id", "thread_id", "conversation_id"):
        if payload.get(key):
            return str(payload[key])[:160]
    return f"{run_id}:{role}"


def string_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in string_values(child)]
    return []


def output_context(event_name: str, context: dict) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": json.dumps(context, ensure_ascii=False)}}, ensure_ascii=False))


def block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))


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
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


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
    try:
        main()
    except Exception:
        if len(sys.argv) > 1 and sys.argv[1] in {"pre-tool-use", "permission-request", "user-prompt-submit"}:
            block("TradingCodex safety hook could not evaluate this request")
        else:
            raise
