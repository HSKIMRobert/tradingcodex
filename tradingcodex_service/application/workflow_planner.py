from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.application.agents import EXPECTED_SUBAGENTS, JUDGMENT_REVIEW_ROLE
from tradingcodex_service.application.common import _unique, append_jsonl, read_json, sanitize_id, stable_hash, write_json
from tradingcodex_service.application.harness import (
    build_subagent_starter_prompt,
    build_workflow_intake_summary,
)
from tradingcodex_service.application.artifact_quality import estimate_tokens
from tradingcodex_service.application.workflow_routing import (
    build_loop_policy,
    classify_structured_intent,
    classify_starter_request,
    is_connector_build_request,
    is_investment_workflow_request,
    is_secret_only_request,
    is_secret_warning_request,
    normalize_structured_intent,
    strip_negated_action_phrases,
)
from tradingcodex_service.application.workflow_contracts import (
    LANE_ALLOWED_ROLES,
    NON_DISPATCH_LANES,
    PLAN_FIELDS,
    STAGE_FIELDS,
    WorkflowLane,
    build_routing_envelope,
    intake_contract_hash,
    workflow_plan_hash,
)
from tradingcodex_service.application.workflow_state import initialize_workflow_state

MAINAGENT_ROOT = Path(".tradingcodex/mainagent")
WORKFLOW_ROOT = MAINAGENT_ROOT / "workflows"
LATEST_INTAKE_PATH = MAINAGENT_ROOT / "latest-workflow-intake.json"
LATEST_PLAN_PATH = MAINAGENT_ROOT / "latest-workflow-plan.json"
LATEST_LOOP_STATE_PATH = MAINAGENT_ROOT / "workflow-loop-state.json"


def build_workflow_intake(
    prompt: str,
    workspace_root: Path | str | None = None,
    *,
    workflow_run_id: str = "",
    structured_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = prompt or ""
    if not prompt.strip():
        raise ValueError("prompt is required")
    secret_warning = is_secret_warning_request(prompt)
    secret_only = is_secret_only_request(prompt)
    connector_build = is_connector_build_request(prompt)
    normalized_intent = normalize_structured_intent(prompt, structured_intent)
    if structured_intent is not None:
        investment_candidate = bool(normalized_intent.requested_actions) and not secret_only
    else:
        investment_candidate = is_investment_workflow_request(prompt) and not secret_only
    if investment_candidate or connector_build:
        hint = classify_structured_intent(normalized_intent) if structured_intent is not None else classify_starter_request(prompt)
    else:
        hint = {"lane": "secret_warning" if secret_warning else "head_manager", "subagents": [], "blockedActions": _default_blocked_actions(secret_warning)}
    run_id = workflow_run_id or _new_workflow_run_id()
    starter_prompt = build_subagent_starter_prompt(prompt, workspace_root)
    context_metrics = {
        "starter_prompt_sha256": hashlib.sha256(starter_prompt.encode("utf-8")).hexdigest(),
        "starter_prompt_bytes": len(starter_prompt.encode("utf-8")),
        "starter_prompt_estimated_tokens": estimate_tokens(starter_prompt),
        "selected_role_count": len(hint.get("subagents") or []),
    }
    intake = {
        "schema_version": 1,
        "marker": "tradingcodex-workflow-intake",
        "workflow_run_id": run_id,
        "created_at": _now(),
        "requires_workflow_planning": bool(investment_candidate or connector_build),
        "investment_candidate": bool(investment_candidate),
        "connector_build": bool(connector_build),
        "secret_warning": bool(secret_warning),
        "secret_only": bool(secret_only),
        "explicit_negations": _unique([*_explicit_negations(prompt), *normalized_intent.forbidden_actions]),
        "normalized_intent": normalized_intent.as_dict(),
        "requires_intent_confirmation": normalized_intent.requires_confirmation,
        "context_metrics": context_metrics,
        "deterministic_hint": {
            "lane": hint.get("lane", ""),
            "roles": list(hint.get("subagents") or []),
            "blocked_actions": list(hint.get("blockedActions") or []),
            "quality_flags": _quality_flags(hint.get("routingFlags") or {}),
        },
        "heuristic_lane": hint.get("lane", ""),
        "heuristic_roles": list(hint.get("subagents") or []),
        "blocked_actions": list(hint.get("blockedActions") or []),
        "intake_path": workflow_intake_relpath(run_id),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_bytes": len(prompt.encode("utf-8")),
    }
    return {**intake, "intake_hash": intake_contract_hash(intake)}


def record_workflow_intake(
    workspace_root: Path | str,
    prompt: str,
    *,
    workflow_run_id: str = "",
    structured_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root)
    intake = build_workflow_intake(
        prompt,
        root,
        workflow_run_id=workflow_run_id,
        structured_intent=structured_intent,
    )
    run_id = str(intake["workflow_run_id"])
    write_json(root / workflow_intake_relpath(run_id), intake)
    write_json(root / LATEST_INTAKE_PATH, intake)
    append_jsonl(root / MAINAGENT_ROOT / "workflow-intake-history.jsonl", {
        "ts": _now(),
        **{key: intake[key] for key in (
            "workflow_run_id",
            "requires_workflow_planning",
            "investment_candidate",
            "connector_build",
            "secret_warning",
            "secret_only",
            "heuristic_lane",
            "heuristic_roles",
            "blocked_actions",
            "intake_hash",
            "prompt_sha256",
            "prompt_bytes",
            "requires_intent_confirmation",
            "context_metrics",
        )},
    })
    return intake


def build_deterministic_workflow_plan(workspace_root: Path | str, prompt: str, *, workflow_run_id: str = "") -> dict[str, Any]:
    """Compatibility preview, not the final agent-authored dynamic plan."""
    intake = build_workflow_intake(prompt, workspace_root, workflow_run_id=workflow_run_id)
    summary = build_workflow_intake_summary(prompt, workspace_root)
    roles = [item["role"] for item in summary.get("subagents") or []]
    plan = {
        "schema_version": 1,
        "workflow_run_id": intake["workflow_run_id"],
        "lane": summary["workflow_lane"],
        "stages": _stages_from_summary(summary),
        "blocked_actions": summary.get("blocked_actions") or [],
        "user_constraints": intake["explicit_negations"],
        "decision_quality_flags": summary.get("routing_flags") or {},
        "profile_gaps": summary.get("investor_profile_inputs") or [],
        "artifact_requirements": {
            "handoff_states": summary.get("artifact_handoff_states") or [],
            "context_summary_required": True,
            "source_as_of_required": True,
        },
        "stop_condition": _stop_condition(summary["workflow_lane"], summary.get("blocked_actions") or []),
        "planner_rationale": "Deterministic compatibility preview; head-manager may author a richer staged plan and validate it before dispatch.",
        "deterministic_preview": True,
        "heuristic_roles": roles,
    }
    loop_policy = build_loop_policy(str(plan["lane"]))
    envelope = build_routing_envelope(
        intake,
        lane=str(plan["lane"]),
        roles=roles,
        blocked_actions=list(plan["blocked_actions"]),
        loop_policy=loop_policy,
        terminal_condition=str(plan["stop_condition"]),
    )
    compiled = {
        **plan,
        "plan_version": 1,
        "intake_hash": intake["intake_hash"],
        "routing_envelope": envelope,
        "routing_envelope_hash": envelope["routing_envelope_hash"],
    }
    return {**compiled, "plan_hash": workflow_plan_hash(compiled)}


def validate_workflow_plan(plan: dict[str, Any], *, intake: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    run_id = str(plan.get("workflow_run_id") or "")
    lane = str(plan.get("lane") or "")
    stages = plan.get("stages")
    blocked_actions = [str(item).lower() for item in plan.get("blocked_actions") or []]
    unknown_plan_fields = sorted(set(plan) - PLAN_FIELDS)
    if unknown_plan_fields:
        errors.append(f"unknown plan field(s): {', '.join(unknown_plan_fields)}")
    if not run_id:
        errors.append("workflow_run_id is required")
    try:
        typed_lane = WorkflowLane(lane)
    except ValueError:
        typed_lane = None
        errors.append(f"unknown lane: {lane or '<missing>'}")
    if not isinstance(stages, list):
        errors.append("stages must be a list")
        stages = []
    stage_ids: set[str] = set()
    all_roles: list[str] = []
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            errors.append(f"stage {index} must be an object")
            continue
        unknown_stage_fields = sorted(set(stage) - STAGE_FIELDS)
        if unknown_stage_fields:
            errors.append(f"unknown stage field(s) in {stage.get('stage_id') or index}: {', '.join(unknown_stage_fields)}")
        stage_id = str(stage.get("stage_id") or "")
        if not stage_id:
            errors.append(f"stage {index} missing stage_id")
        elif stage_id in stage_ids:
            errors.append(f"duplicate stage_id: {stage_id}")
        stage_ids.add(stage_id)
        raw_roles = stage.get("roles") or []
        if not isinstance(raw_roles, list):
            errors.append(f"stage {stage_id or index} roles must be a list")
            raw_roles = []
        roles = _role_names(raw_roles)
        unknown = [role for role in roles if role not in EXPECTED_SUBAGENTS]
        if unknown:
            errors.append(f"unknown role(s) in {stage_id or index}: {', '.join(unknown)}")
        all_roles.extend(roles)
        raw_dependencies = stage.get("depends_on") or []
        if not isinstance(raw_dependencies, list):
            errors.append(f"stage {stage_id or index} depends_on must be a list")
            raw_dependencies = []
        for dep in raw_dependencies:
            if str(dep) == stage_id or str(dep) not in stage_ids:
                errors.append(f"stage {stage_id or index} depends on unknown or later stage: {dep}")
        if str(stage.get("dispatch_mode") or "") not in {"parallel", "sequential", "none"}:
            errors.append(f"stage {stage_id or index} dispatch_mode must be parallel, sequential, or none")
        for field in ("purpose", "exit_criteria"):
            if field not in stage:
                warnings.append(f"stage {stage_id or index} missing {field}")
    duplicate_roles = sorted({role for role in all_roles if all_roles.count(role) > 1})
    if duplicate_roles:
        errors.append(f"roles may appear in only one initial stage: {', '.join(duplicate_roles)}")

    envelope = plan.get("routing_envelope") if isinstance(plan.get("routing_envelope"), dict) else {}
    envelope_hash = str(plan.get("routing_envelope_hash") or "")
    embedded_envelope_hash = str(envelope.get("routing_envelope_hash") or "")
    envelope_body = {key: value for key, value in envelope.items() if key != "routing_envelope_hash"}
    actual_envelope_hash = stable_hash(envelope_body) if envelope else ""
    if not envelope:
        errors.append("routing_envelope is required")
    elif envelope_hash != actual_envelope_hash or embedded_envelope_hash != actual_envelope_hash:
        errors.append("routing envelope hash mismatch")
    elif envelope.get("workflow_run_id") != run_id:
        errors.append("routing envelope workflow_run_id mismatch")
    elif envelope.get("lane") != lane or lane not in (envelope.get("permitted_lane_transitions") or []):
        errors.append("plan lane is outside the routing envelope")
    if envelope:
        eligible_roles = set(envelope.get("eligible_roles") or [])
        required_roles = set(envelope.get("required_roles") or [])
        if not set(all_roles).issubset(eligible_roles):
            errors.append("plan includes roles outside the routing envelope")
        if not required_roles.issubset(set(all_roles)):
            errors.append("plan omits required routing-envelope roles")
        envelope_blocks = {str(item).lower() for item in envelope.get("blocked_actions") or []}
        if not envelope_blocks.issubset(set(blocked_actions)):
            errors.append("blocked actions are monotonic within a plan version")
        budgets = envelope.get("budgets") if isinstance(envelope.get("budgets"), dict) else {}
        if len(stages) > int(budgets.get("max_stages") or 0):
            errors.append("stage budget exceeded")
        if len(_unique(all_roles)) > int(budgets.get("max_initial_tasks") or 0):
            errors.append("initial task budget exceeded")
        max_concurrency = int(budgets.get("max_concurrency") or 0)
        if any(stage.get("dispatch_mode") == "parallel" and len(_role_names(stage.get("roles") or [])) > max_concurrency for stage in stages if isinstance(stage, dict)):
            errors.append("stage concurrency budget exceeded")

    expected_plan_hash = workflow_plan_hash(plan)
    if plan.get("plan_hash") and str(plan.get("plan_hash")) != expected_plan_hash:
        errors.append("plan_hash does not bind the compiled plan")
    if intake:
        if str(intake.get("workflow_run_id") or "") != run_id:
            errors.append("workflow_run_id does not match recorded intake")
        expected_intake_hash = str(intake.get("intake_hash") or intake_contract_hash(intake))
        if str(plan.get("intake_hash") or "") != expected_intake_hash:
            errors.append("plan intake_hash does not match recorded intake")
        hint = intake.get("deterministic_hint") if isinstance(intake.get("deterministic_hint"), dict) else {}
        hint_lane = str(hint.get("lane") or "")
        hint_roles = set(str(role) for role in hint.get("roles") or [])
        if hint_lane and lane != hint_lane:
            errors.append("plan lane widens or replaces the recorded intake lane")
        if hint_roles != set(all_roles):
            errors.append("plan roles must match the recorded intake routing envelope")
        intake_blocks = {str(item).lower() for item in hint.get("blocked_actions") or []}
        if not intake_blocks.issubset(set(blocked_actions)):
            errors.append("plan removed blocked actions from recorded intake")
        if intake.get("secret_only") and all_roles:
            errors.append("secret-only intake must not dispatch investment roles")
        if intake.get("connector_build") and all_roles:
            errors.append("connector build intake must not dispatch investment roles")
        if intake.get("requires_intent_confirmation"):
            if typed_lane != WorkflowLane.RESEARCH_ONLY:
                errors.append("unresolved or low-confidence intent must remain research_only")
            if all_roles:
                errors.append("unresolved or low-confidence intent must not dispatch roles before confirmation")
        negations = set(intake.get("explicit_negations") or [])
        if "valuation" in negations and "valuation-analyst" in all_roles:
            errors.append("negated valuation scope cannot include valuation-analyst")
        if "technical" in negations and "technical-analyst" in all_roles:
            errors.append("negated technical scope cannot include technical-analyst")
        if "news" in negations and "news-analyst" in all_roles:
            errors.append("negated news scope cannot include news-analyst")
        if "portfolio" in negations and "portfolio-manager" in all_roles:
            errors.append("negated portfolio scope cannot include portfolio-manager")
        if "risk" in negations and "risk-manager" in all_roles:
            errors.append("negated risk scope cannot include risk-manager")
        if {"order", "trading", "execution"} & negations and "execution-operator" in all_roles:
            errors.append("negated order/trading/execution scope cannot include execution-operator")
    if typed_lane in NON_DISPATCH_LANES and all_roles:
        errors.append(f"{lane} lane must not dispatch investment roles")
    if typed_lane and not set(all_roles).issubset(LANE_ALLOWED_ROLES[typed_lane]):
        errors.append(f"{lane} contains a role outside its canonical lane policy")
    judgment_required_lanes = {
        WorkflowLane.THESIS_REVIEW,
        WorkflowLane.THESIS_PORTFOLIO_RISK,
        WorkflowLane.PORTFOLIO_RISK,
        WorkflowLane.ORDER_DRAFT,
    }
    if typed_lane in judgment_required_lanes and all_roles and JUDGMENT_REVIEW_ROLE not in all_roles:
        errors.append(f"{lane} requires judgment-reviewer")
    if "execution-operator" in all_roles and lane != "order_ticket_approval_execution_gate":
        errors.append("execution-operator is only valid in order_ticket_approval_execution_gate")
    if lane == "order_ticket_approval_execution_gate" and JUDGMENT_REVIEW_ROLE in all_roles:
        errors.append("order_ticket_approval_execution_gate must not dispatch judgment-reviewer")
    if "execution-operator" in all_roles and not any("execution" in item for item in blocked_actions):
        errors.append("execution role requires explicit execution blocked/precondition language in blocked_actions")
    if any(role in all_roles for role in ("portfolio-manager", "risk-manager", "execution-operator")) and lane == "research_only":
        errors.append("research_only lane cannot include portfolio, risk, or execution roles")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "workflow_run_id": run_id,
        "lane": lane,
        "roles": _unique(all_roles),
        "intake_hash": str(plan.get("intake_hash") or ""),
        "routing_envelope_hash": envelope_hash,
        "plan_hash": expected_plan_hash,
    }


def record_workflow_plan(workspace_root: Path | str, plan: dict[str, Any], *, intake: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(workspace_root)
    if intake is None and plan.get("workflow_run_id"):
        stored_intake = read_json(root / workflow_intake_relpath(str(plan["workflow_run_id"])), {})
        intake = stored_intake if isinstance(stored_intake, dict) and stored_intake else None
    validation = validate_workflow_plan(plan, intake=intake)
    if not validation["ok"]:
        return {"status": "invalid", "validation": validation}
    run_id = validation["workflow_run_id"]
    existing_state = read_json(root / workflow_loop_relpath(run_id), {})
    if isinstance(existing_state, dict) and existing_state:
        if existing_state.get("plan_hash") == validation["plan_hash"]:
            return {
                "status": "already_recorded",
                "workflow_run_id": run_id,
                "plan_path": workflow_plan_relpath(run_id),
                "loop_state_path": workflow_loop_relpath(run_id),
                "validation": validation,
                "plan_hash": validation["plan_hash"],
                "routing_envelope_hash": validation["routing_envelope_hash"],
            }
        return {"status": "invalid", "validation": {**validation, "ok": False, "errors": [*validation["errors"], "workflow_run_id is already bound to another plan"]}}
    plan = {**plan, "schema_version": int(plan.get("schema_version") or 1), "plan_hash": validation["plan_hash"], "recorded_at": _now(), "validation": validation}
    plan_path = workflow_plan_relpath(run_id)
    write_json(root / plan_path, plan)
    write_json(root / LATEST_PLAN_PATH, plan)
    loop_state = _initial_loop_state(plan, intake)
    loop_state = initialize_workflow_state(root, loop_state, latest_projection=compact_workflow_loop_state)
    append_jsonl(root / "trading" / "audit" / "workflow-plan-events.jsonl", {
        "ts": _now(),
        "event": "workflow-plan-recorded",
        "workflow_run_id": run_id,
        "plan_hash": validation["plan_hash"],
        "routing_envelope_hash": validation["routing_envelope_hash"],
        "lane": validation["lane"],
        "roles": validation["roles"],
    })
    return {
        "status": "recorded",
        "workflow_run_id": run_id,
        "plan_path": plan_path,
        "latest_plan_path": LATEST_PLAN_PATH.as_posix(),
        "loop_state_path": workflow_loop_relpath(run_id),
        "latest_loop_state_path": LATEST_LOOP_STATE_PATH.as_posix(),
        "validation": validation,
        "plan_hash": validation["plan_hash"],
        "routing_envelope_hash": validation["routing_envelope_hash"],
    }


def read_workflow_intake(workspace_root: Path | str, workflow_run_id: str = "") -> dict[str, Any]:
    root = Path(workspace_root)
    path = root / (workflow_intake_relpath(workflow_run_id) if workflow_run_id else LATEST_INTAKE_PATH)
    value = read_json(path, {})
    return value if isinstance(value, dict) else {}


def workflow_intake_relpath(workflow_run_id: str) -> str:
    return f"{WORKFLOW_ROOT.as_posix()}/{sanitize_id(workflow_run_id)}/intake.json"


def workflow_plan_relpath(workflow_run_id: str) -> str:
    return f"{WORKFLOW_ROOT.as_posix()}/{sanitize_id(workflow_run_id)}/workflow-plan.json"


def workflow_loop_relpath(workflow_run_id: str) -> str:
    return f"{WORKFLOW_ROOT.as_posix()}/{sanitize_id(workflow_run_id)}/loop-state.json"


def _new_workflow_run_id() -> str:
    return f"workflow-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_blocked_actions(secret_warning: bool) -> list[str]:
    if secret_warning:
        return ["secret storage", "secret echo", "raw credential handling"]
    return []


def _quality_flags(flags: dict[str, Any]) -> dict[str, bool]:
    return {
        key: bool(flags.get(key))
        for key in (
            "decision_quality_required",
            "forecast_contract_required",
            "profile_gate_required",
            "anti_overfit_required",
            "deep_thesis_default",
        )
        if flags.get(key)
    }


def _explicit_negations(prompt: str) -> list[str]:
    lower = prompt.lower()
    negations: list[str] = []
    checks = {
        "valuation": ("no valuation", "without valuation", "do not value", "no fair value", "no target price"),
        "technical": ("no technical", "without technical", "no technical analysis", "without technical analysis", "do not do technical analysis", "no chart", "without chart"),
        "news": ("no news", "without news", "no news analysis", "without news analysis", "no headline", "without headline", "no event review"),
        "order": ("no order", "without order", "do not order", "no order ticket"),
        "trading": ("no trading", "without trading", "do not trade", "do not place trades"),
        "execution": ("no execution", "without execution", "do not execute"),
        "approval": ("no approval", "without approval", "do not approve"),
        "recommendation": ("no recommendation", "without recommendation", "do not recommend"),
        "portfolio": ("no portfolio", "without portfolio review", "no portfolio review"),
        "risk": ("no risk", "without risk review", "no risk review"),
    }
    stripped = strip_negated_action_phrases(lower)
    for label, terms in checks.items():
        if any(term in lower for term in terms) or (label in lower and label not in stripped):
            negations.append(label)
    return _unique(negations)


def _stages_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    previous_ids: list[str] = []
    for stage in summary.get("workflow_stages") or []:
        roles: list[str] = []
        raw_roles = stage.get("roles") or []
        for item in raw_roles:
            role = item.get("role") if isinstance(item, dict) else item
            if role in EXPECTED_SUBAGENTS:
                roles.append(role)
        if not roles:
            continue
        stage_id = sanitize_id(stage.get("key") or stage.get("label") or f"stage-{len(stages) + 1}")
        stages.append({
            "stage_id": stage_id,
            "roles": _unique(roles),
            "depends_on": list(previous_ids),
            "dispatch_mode": "parallel" if len(roles) > 1 else "sequential",
            "purpose": stage.get("summary") or stage.get("label") or stage_id,
            "exit_criteria": stage.get("exit_criteria") or [],
        })
        previous_ids = [stage_id]
    return stages


def _stop_condition(lane: str, blocked_actions: list[str]) -> str:
    if "execution" in blocked_actions:
        return "stop before execution unless service-layer approval and execution gates pass"
    if lane == "research_only":
        return "stop after selected research artifacts are accepted or blocked"
    return "stop at synthesize, blocked, waiting, or lane_escalation_proposal"


def _initial_loop_state(plan: dict[str, Any], intake: dict[str, Any] | None) -> dict[str, Any]:
    run_id = str(plan["workflow_run_id"])
    pending_tasks = [
        {
            "task_id": f"{run_id}:{stage['stage_id']}",
            "stage_id": stage["stage_id"],
            "roles": _role_names(stage.get("roles") or []),
            "task_type": "stage_dispatch",
            "status": "pending" if not stage.get("depends_on") else "blocked_by_dependency",
            "process_status": "queued",
            "process_by_role": {role: "queued" for role in _role_names(stage.get("roles") or [])},
            "artifact_quality": "missing",
            "artifact_quality_by_role": {},
            "handoff_state": "waiting",
            "handoff_by_role": {},
            "stage_gate": "ready" if not stage.get("depends_on") else "waiting",
            "accepted_artifacts_by_role": {},
            "active_roles": [],
            "completed_roles": [],
            "depends_on": stage.get("depends_on") or [],
            "planner_action": "dispatch_ready_stage",
            "delta_brief": stage.get("purpose", ""),
        }
        for stage in plan.get("stages") or []
    ]
    return {
        "workflow_run_id": run_id,
        "lane": plan.get("lane", ""),
        "plan_version": int(plan.get("plan_version") or 1),
        "plan_hash": str(plan.get("plan_hash") or ""),
        "routing_envelope_hash": str(plan.get("routing_envelope_hash") or ""),
        "intake_hash": str(plan.get("intake_hash") or ""),
        "routing_envelope": plan.get("routing_envelope") or {},
        "state_path": workflow_loop_relpath(run_id),
        "latest_state_path": LATEST_LOOP_STATE_PATH.as_posix(),
        "intake_path": (intake or {}).get("intake_path", ""),
        "plan_path": workflow_plan_relpath(run_id),
        "iteration": 0,
        "supervisor_round": 0,
        "process_event_count": 0,
        "state_revision": 0,
        "loop_policy": build_loop_policy(str(plan.get("lane") or "research_only")),
        "selected_team": _unique([role for stage in plan.get("stages") or [] for role in _role_names(stage.get("roles") or [])]),
        "allowed_followup_team": _unique([role for stage in plan.get("stages") or [] for role in _role_names(stage.get("roles") or [])]),
        "escalation_team": [],
        "stages": plan.get("stages") or [],
        "pending_tasks": pending_tasks,
        "completed_artifacts": [],
        "loop_decisions": [{
            "ts": _now(),
            "planner_action": "waiting" if pending_tasks else "synthesize",
            "reason": "Validated dynamic workflow plan recorded; hooks did not choose the final team.",
        }],
        "escalation_proposals": [],
        "blocked_actions": plan.get("blocked_actions") or [],
        "stop_reason": "waiting_for_validated_plan_dispatch" if pending_tasks else "head_manager_lane",
        "state_mode": "validated_dynamic_workflow_plan",
        "auto_spawn": False,
        "recursive_hook_dispatch": False,
        "updated_at": _now(),
    }


def compact_workflow_loop_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_run_id": state.get("workflow_run_id", ""),
        "lane": state.get("lane", ""),
        "state_path": state.get("state_path", ""),
        "plan_path": state.get("plan_path", ""),
        "plan_version": state.get("plan_version", 1),
        "plan_hash": state.get("plan_hash", ""),
        "routing_envelope_hash": state.get("routing_envelope_hash", ""),
        "state_revision": state.get("state_revision", 0),
        "iteration": state.get("iteration", 0),
        "supervisor_round": state.get("supervisor_round", 0),
        "process_event_count": state.get("process_event_count", 0),
        "selected_team": state.get("selected_team", []),
        "allowed_followup_team": state.get("allowed_followup_team", []),
        "escalation_team": state.get("escalation_team", []),
        "pending_tasks": state.get("pending_tasks", [])[:12],
        "completed_artifacts": state.get("completed_artifacts", [])[-12:],
        "loop_decisions": state.get("loop_decisions", [])[-12:],
        "blocked_actions": state.get("blocked_actions", []),
        "stop_reason": state.get("stop_reason", ""),
        "state_mode": state.get("state_mode", "validated_dynamic_workflow_plan"),
        "auto_spawn": False,
        "recursive_hook_dispatch": False,
        "updated_at": state.get("updated_at", ""),
    }


def _role_names(raw_roles: list[Any]) -> list[str]:
    roles: list[str] = []
    for item in raw_roles:
        role = item.get("role") if isinstance(item, dict) else item
        if role:
            roles.append(str(role))
    return roles
