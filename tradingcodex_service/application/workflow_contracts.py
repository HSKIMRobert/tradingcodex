from __future__ import annotations

from enum import StrEnum
from typing import Any

from tradingcodex_service.application.agents import EXPECTED_SUBAGENTS, JUDGMENT_REVIEW_ROLE
from tradingcodex_service.application.common import stable_hash


class WorkflowLane(StrEnum):
    HEAD_MANAGER = "head_manager"
    SECRET_WARNING = "secret_warning"
    CONNECTOR_BUILD = "connector_build"
    CONNECTOR_OPERATIONS = "head_manager_connector_operations"
    STRATEGY_AUTHORING = "head_manager_strategy_authoring"
    RESEARCH_ONLY = "research_only"
    THESIS_REVIEW = "thesis_review"
    THESIS_PORTFOLIO_RISK = "thesis_review_then_portfolio_risk_review"
    PORTFOLIO_RISK = "portfolio_risk_review"
    ORDER_DRAFT = "order_ticket_draft_gate"
    APPROVED_ACTION = "order_ticket_approval_execution_gate"


ROUTING_POLICY_VERSION = "routing-envelope-v1"
NON_DISPATCH_LANES = {
    WorkflowLane.HEAD_MANAGER,
    WorkflowLane.SECRET_WARNING,
    WorkflowLane.CONNECTOR_BUILD,
    WorkflowLane.CONNECTOR_OPERATIONS,
    WorkflowLane.STRATEGY_AUTHORING,
}
RESEARCH_ROLES = {
    "fundamental-analyst",
    "technical-analyst",
    "news-analyst",
    "macro-analyst",
    "instrument-analyst",
}
DECISION_ROLES = RESEARCH_ROLES | {"valuation-analyst", JUDGMENT_REVIEW_ROLE}
PORTFOLIO_ROLES = DECISION_ROLES | {"portfolio-manager", "risk-manager"}
LANE_ALLOWED_ROLES = {
    WorkflowLane.HEAD_MANAGER: set(),
    WorkflowLane.SECRET_WARNING: set(),
    WorkflowLane.CONNECTOR_BUILD: set(),
    WorkflowLane.CONNECTOR_OPERATIONS: set(),
    WorkflowLane.STRATEGY_AUTHORING: set(),
    WorkflowLane.RESEARCH_ONLY: RESEARCH_ROLES | {JUDGMENT_REVIEW_ROLE},
    WorkflowLane.THESIS_REVIEW: DECISION_ROLES,
    WorkflowLane.THESIS_PORTFOLIO_RISK: PORTFOLIO_ROLES,
    WorkflowLane.PORTFOLIO_RISK: PORTFOLIO_ROLES,
    WorkflowLane.ORDER_DRAFT: PORTFOLIO_ROLES,
    WorkflowLane.APPROVED_ACTION: set(EXPECTED_SUBAGENTS) - {JUDGMENT_REVIEW_ROLE},
}
PLAN_FIELDS = {
    "schema_version",
    "workflow_run_id",
    "lane",
    "stages",
    "blocked_actions",
    "user_constraints",
    "decision_quality_flags",
    "profile_gaps",
    "artifact_requirements",
    "stop_condition",
    "planner_rationale",
    "deterministic_preview",
    "heuristic_roles",
    "routing_envelope",
    "routing_envelope_hash",
    "intake_hash",
    "plan_hash",
    "plan_version",
    "recorded_at",
    "validation",
}
STAGE_FIELDS = {"stage_id", "roles", "depends_on", "dispatch_mode", "purpose", "exit_criteria"}


def intake_contract_hash(intake: dict[str, Any]) -> str:
    return stable_hash({
        key: intake.get(key)
        for key in (
            "workflow_run_id",
            "requires_workflow_planning",
            "investment_candidate",
            "connector_build",
            "secret_warning",
            "secret_only",
            "explicit_negations",
            "normalized_intent",
            "requires_intent_confirmation",
            "context_metrics",
            "deterministic_hint",
            "prompt_sha256",
        )
    })


def build_routing_envelope(
    intake: dict[str, Any],
    *,
    lane: str,
    roles: list[str],
    blocked_actions: list[str],
    loop_policy: dict[str, Any],
    terminal_condition: str,
) -> dict[str, Any]:
    typed_lane = WorkflowLane(lane)
    selected = list(dict.fromkeys(role for role in roles if role in EXPECTED_SUBAGENTS))
    allowed = sorted(LANE_ALLOWED_ROLES[typed_lane])
    max_total_tasks = int(loop_policy.get("max_total_subagent_tasks") or len(selected))
    envelope = {
        "schema_version": 1,
        "routing_policy_version": ROUTING_POLICY_VERSION,
        "workflow_run_id": str(intake.get("workflow_run_id") or ""),
        "intake_hash": str(intake.get("intake_hash") or intake_contract_hash(intake)),
        "normalized_intent": dict(intake.get("normalized_intent") or intake.get("deterministic_hint") or {}),
        "requires_intent_confirmation": bool(intake.get("requires_intent_confirmation")),
        "explicit_negations": list(intake.get("explicit_negations") or []),
        "lane": typed_lane.value,
        "permitted_lane_transitions": [typed_lane.value],
        "eligible_roles": allowed,
        "required_roles": selected,
        "forbidden_roles": sorted(set(EXPECTED_SUBAGENTS) - set(allowed)),
        "follow_up_roles": selected,
        "escalation_only_roles": sorted(set(allowed) - set(selected)),
        "blocked_actions": list(dict.fromkeys(str(item) for item in blocked_actions)),
        "required_gates": _required_gates(typed_lane, selected),
        "budgets": {
            "max_stages": min(8, max(1, max_total_tasks)),
            "max_initial_tasks": max_total_tasks,
            "max_loop_tasks": int(loop_policy.get("max_loop_subagent_tasks") or 0),
            "max_supervisor_rounds": int(loop_policy.get("max_iterations") or 0),
            "max_followups_per_round": int(loop_policy.get("max_followups_per_iteration") or 0),
            "max_same_role_revisions": int(loop_policy.get("max_same_role_revisions") or 0),
            "max_concurrency": min(5, max(1, len(selected))) if selected else 0,
        },
        "terminal_conditions": [terminal_condition],
    }
    return {**envelope, "routing_envelope_hash": stable_hash(envelope)}


def workflow_plan_hash(plan: dict[str, Any]) -> str:
    excluded = {"plan_hash", "validation", "recorded_at"}
    return stable_hash({key: value for key, value in plan.items() if key not in excluded})


def _required_gates(lane: WorkflowLane, roles: list[str]) -> list[str]:
    gates = ["accepted_run_bound_artifacts"] if roles else []
    if JUDGMENT_REVIEW_ROLE in roles:
        gates.append("independent_judgment_review")
    if lane in {WorkflowLane.ORDER_DRAFT, WorkflowLane.APPROVED_ACTION}:
        gates.append("service_policy")
    if lane == WorkflowLane.APPROVED_ACTION:
        gates.extend(["matching_approval", "duplicate_request", "broker_connection", "audit"])
    return gates
