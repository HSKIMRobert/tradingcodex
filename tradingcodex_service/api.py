from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.http import Http404
from ninja import NinjaAPI, Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from tradingcodex_service import __version__
from tradingcodex_service.application.components import (
    count_harness_component_tags,
    get_harness_component,
    list_components_by_tag,
    list_harness_components,
)
from tradingcodex_service.application.common import local_or_staff_source
from tradingcodex_service.application.harness import (
    build_subagent_starter_prompt,
    build_workflow_intake_summary,
    evaluate_artifact_supervisor_loop,
)
from tradingcodex_service.application.health import liveness_payload, readiness_payload
from tradingcodex_service.application.workflow_planner import (
    build_deterministic_workflow_plan,
    compile_workflow_plan_draft,
    is_workflow_plan_draft,
    read_workflow_intake,
    record_workflow_intake,
    record_workflow_plan,
    validate_workflow_plan,
)
from tradingcodex_service.application.agents import (
    EXPECTED_SKILLS,
    EXPECTED_SUBAGENTS,
    FORECASTING_DISCIPLINE_ROLES,
    RESEARCH_ROLES,
    ROLE_SKILL_MAP,
    build_projection_state,
    create_or_update_optional_skill,
    create_or_update_strategy_skill,
    delete_optional_skill,
    delete_strategy_skill,
    get_optional_skill_record,
    get_strategy_skill_record,
    inspect_agent_configuration,
    list_optional_role_skills,
    list_user_visible_skills,
    read_strategy_skill_records,
    set_optional_skill_status,
    set_strategy_skill_status,
    skills_for_role,
)
from tradingcodex_service.application.brokers import (
    get_broker_connection_status,
    list_broker_connections,
    list_reconciliation_runs,
    sync_broker_account,
)
from tradingcodex_service.application.orders import (
    create_order_ticket,
    get_order_ticket,
    list_order_tickets,
    request_order_approval,
    run_order_checks,
)
from tradingcodex_service.application.policy import simulate_policy as simulate_policy_service
from tradingcodex_service.application.portfolio import list_positions
from tradingcodex_service.application.forecasting import (
    calibration_report,
    get_forecast,
    issue_forecast,
    list_forecasts,
    resolve_forecast,
    revise_forecast,
    score_forecast,
)
from tradingcodex_service.application.evaluation_lab import (
    compare_evaluation_runs,
    create_blind_review_assignment,
    create_evaluation_corpus,
    get_blind_review_packet,
    record_blind_human_review,
    record_evaluation_run,
)
from tradingcodex_service.application.investment_analysis import (
    complete_judgment_review,
    create_causal_equity_analysis,
    record_blind_judgment_prior,
)
from tradingcodex_service.application.research import (
    create_research_artifact,
    export_research_artifact_md,
    get_research_artifact,
    list_research_artifacts,
    list_workflow_artifacts,
    rebuild_research_index,
    record_source_snapshot,
    search_research_artifacts,
)
from tradingcodex_service.application.research_specs import (
    create_replay_manifest,
    create_research_spec,
    get_research_spec,
    list_research_specs,
    record_experiment_run,
)
from tradingcodex_service.application.runtime import (
    ensure_runtime_database,
    persist_workspace_context_if_available,
    tradingcodex_db_path,
    workspace_context_payload,
)
from tradingcodex_service.application.workspaces import bind_request_workspace, current_workspace_root
from tradingcodex_service.mcp_runtime import call_mcp_tool, list_mcp_tools, prepare_mcp_runtime
from tradingcodex_service.runtime_profile import LOCAL_PROFILE


def local_or_staff(request):
    source = local_or_staff_source(
        request,
        api_key=os.environ.get("TRADINGCODEX_API_KEY"),
        api_key_principal=os.environ.get("TRADINGCODEX_API_PRINCIPAL"),
        allow_local_readonly=settings.SERVICE_PROFILE == LOCAL_PROFILE,
    )
    if source:
        bind_request_workspace(request)
    return source


def mutation_principal(request) -> str:
    authenticated = str(getattr(request, "auth", "") or "")
    if not authenticated.startswith("principal:") or not authenticated.removeprefix("principal:"):
        raise HttpError(403, "an authenticated mutation principal is required")
    return authenticated.removeprefix("principal:")


def _principal_role(principal_id: str) -> str:
    from apps.policy.services import role_for_principal_id

    return role_for_principal_id(principal_id)


api = NinjaAPI(
    title="TradingCodex Service API",
    version=__version__,
    description="Typed control API for TradingCodex workspace, policy, portfolio, audit, and workflow state.",
    docs_decorator=staff_member_required,
    auth=local_or_staff,
)

harness_router = Router()
subagents_router = Router()
policy_router = Router()
orders_router = Router()
approvals_router = Router()
executions_router = Router()
portfolio_router = Router()
brokers_router = Router()
audit_router = Router()
workflows_router = Router()
integrations_router = Router()
research_router = Router()
evaluations_router = Router()


class PolicyRequest(Schema):
    principal_id: str = "unknown"
    action: str = "unknown"
    resource: str | None = None
    order: dict[str, Any] | None = None
    approval_receipt: dict[str, Any] | None = None
    require_approval_check: bool = False


class ApprovalRequest(Schema):
    ticket_id: str = Field(min_length=1, max_length=160)
    expires_hours: int = Field(default=24, ge=1, le=168)


class SubmitApprovedRequest(Schema):
    ticket_id: str | None = None
    order_ticket_id: str | None = None
    approval_receipt_id: str | None = None
    live_confirmation: str | None = None


class CancelSubmittedRequest(Schema):
    ticket_id: str | None = None
    order_ticket_id: str | None = None
    broker_order_id: str | None = None
    approval_receipt_id: str | None = None
    live_confirmation: str | None = None


class BrokerSyncRequest(Schema):
    broker_id: str = "paper-trading"
    broker_account_id: str | None = None


class OrderTicketRequest(Schema):
    ticket_id: str | None = None
    natural_language: str | None = None
    source: str = "api"
    symbol: str | None = None
    side: str | None = None
    quantity: Decimal | None = None
    order_type: str = "limit"
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: str = "day"
    currency: str | None = None
    base_currency: str | None = None
    fx_rate: Decimal | None = None
    fx_source_snapshot_id: str | None = None
    fx_as_of: str | None = None
    broker_id: str = "paper-trading"
    broker_account_id: str | None = None
    portfolio_id: str | None = None
    account_id: str | None = None
    strategy_id: str | None = None


class OrderTicketActionRequest(Schema):
    ticket_id: str | None = None
    expires_hours: int = Field(default=24, ge=1, le=168)


class OrderTicketApprovalRequest(Schema):
    ticket_id: str | None = None
    expires_hours: int = Field(default=24, ge=1, le=168)


class WorkflowValidationRequest(Schema):
    original_request: str = ""
    plan: dict[str, Any] | None = None


class WorkflowRecordRequest(Schema):
    plan: dict[str, Any]


class WorkflowLoopRequest(Schema):
    workflow_run_id: str = ""
    original_request: str = ""
    artifact_paths: list[str]
    record: bool = False


class ResearchArtifactRequest(Schema):
    artifact_id: str | None = None
    artifact_type: str = "research_memo"
    universe: str = "public_equity"
    workflow_type: str = ""
    role: str | None = None
    symbol: str = ""
    title: str
    markdown: str
    metadata: dict[str, Any] | None = None
    source_as_of: str = ""
    readiness_label: str = ""
    context_summary: str = ""
    reader_summary: str = ""
    handoff_state: str = ""
    confidence: str = ""
    missing_evidence: list[Any] | None = None
    next_recipient: str = ""
    next_action: str = ""
    blocked_actions: list[Any] | None = None
    source_snapshot_ids: list[str] | None = None
    follow_up_requests: list[Any] | None = None
    improvements: list[Any] | None = None
    created_by: str = "head-manager"
    export_path: str | None = None


class ResearchSearchRequest(Schema):
    query: str
    universe: str | None = None
    artifact_type: str | None = None
    limit: int = 20


class SourceSnapshotRequest(Schema):
    provider: str
    source_category: str
    source_locator: str | None = None
    provider_query: dict[str, Any] | None = None
    as_of: str = ""
    observed_at: str = ""
    effective_at: str = ""
    published_at: str = ""
    retrieved_at: str | None = None
    known_at: str | None = None
    recorded_at: str | None = None
    revision: str = "not_applicable"
    vintage: str = "not_applicable"
    timezone: str = "UTC"
    schema_hash: str | None = None
    corporate_action_policy: str = "not_specified"
    price_adjustment_policy: str = "not_specified"
    universe_membership: dict[str, Any] | None = None
    delisting_policy: str = "not_specified"
    coverage_note: str = "coverage and licensing not specified"
    artifact_id: str = ""
    warnings: list[Any] | None = None
    payload: dict[str, Any] | None = None


class ResearchSpecRequest(Schema):
    spec_id: str | None = None
    created_at: str | None = None
    knowledge_cutoff: str
    method_profile: Literal[
        "general_evidence_v1",
        "event_research_v1",
        "quant_signal_v1",
        "listed_equity_fcff_dcf_v1",
    ] | None = None
    hypothesis: str
    economic_mechanism: str
    research_type: str | None = None
    instrument: str | None = None
    universe: str
    universe_membership_rule: str
    target: str
    horizon: str
    benchmark: str | None = None
    holding_period: str | None = None
    rebalance_rule: str | None = None
    signal_definition: dict[str, Any] | None = None
    falsification_criteria: list[Any]
    validation_plan: dict[str, Any]
    parameter_trial_budget: int | None = Field(default=None, ge=1)
    cost_assumptions: dict[str, Any] | None = None
    capacity_assumptions: dict[str, Any] | None = None
    resolution_rule: str
    causal_analysis_required: bool | None = None
    driver_tree: dict[str, Any] | None = None
    base_rate_cohort: dict[str, Any] | None = None
    implied_expectations_plan: dict[str, Any] | None = None
    scenario_plan: dict[str, Any] | None = None
    method_reconciliation_plan: dict[str, Any] | None = None
    independent_review_plan: dict[str, Any] | None = None


class ReplayManifestRequest(Schema):
    manifest_id: str | None = None
    spec_id: str
    source_snapshot_ids: list[str]
    created_at: str | None = None


class ExperimentRunRequest(Schema):
    run_id: str | None = None
    spec_id: str
    replay_manifest_id: str
    created_at: str | None = None
    code_hash: str
    data_hash: str
    config_hash: str
    model: str = ""
    reasoning_effort: str = ""
    prompt_hash: str = ""
    tool_profile_hash: str = ""
    splits: dict[str, Any]
    trial_count: int = Field(default=1, ge=1)
    metrics: dict[str, Any]
    checks: dict[str, Any]
    conclusion: str
    source_limitations: list[Any] | None = None


class ForecastIssueRequest(Schema):
    forecast_id: str | None = None
    workflow_run_id: str = ""
    artifact_id: str
    role: str = ""
    instrument: str = ""
    universe: str = ""
    regime: str = "unclassified"
    forecast_target: str
    target_type: str = "binary"
    unit: str = ""
    benchmark: str = ""
    horizon: str
    issued_at: str | None = None
    knowledge_cutoff: str
    probability: float | None = None
    probability_range: list[float] | str | None = None
    probabilities: dict[str, float] | None = None
    prediction: float | None = None
    interval: dict[str, float] | None = None
    quantiles: dict[str, float] | None = None
    base_rate: dict[str, Any]
    evidence_ids: list[Any]
    contrary_evidence: list[Any]
    invalidation_conditions: list[Any]
    update_triggers: list[Any]
    resolution_rule: str
    resolution_source: str = ""
    review_date: str = ""
    model: str = ""
    reasoning_effort: str = ""
    prompt_hash: str = ""
    tool_profile_hash: str = ""
    config_hash: str = ""
    idempotency_key: str | None = None


class ForecastRevisionRequest(Schema):
    revision_reason: str
    revised_at: str | None = None
    knowledge_cutoff: str | None = None
    probability: float | None = None
    probability_range: list[float] | str | None = None
    probabilities: dict[str, float] | None = None
    prediction: float | None = None
    interval: dict[str, float] | None = None
    quantiles: dict[str, float] | None = None
    base_rate: dict[str, Any] | None = None
    evidence_ids: list[Any] | None = None
    contrary_evidence: list[Any] | None = None
    invalidation_conditions: list[Any] | None = None
    update_triggers: list[Any] | None = None
    regime: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    prompt_hash: str | None = None
    tool_profile_hash: str | None = None
    config_hash: str | None = None
    idempotency_key: str | None = None


class ForecastResolutionRequest(Schema):
    outcome: Any
    resolution_source_snapshot_id: str
    resolved_at: str | None = None
    observed_at: str | None = None
    resolution_note: str = ""
    dispute_state: str = "undisputed"
    resolve_dispute: bool = False
    idempotency_key: str | None = None


class CausalEquityAnalysisRequest(Schema):
    analysis_id: str | None = None
    spec_id: str
    replay_manifest_id: str
    analysis_input_snapshot_id: str
    prior_id: str


class BlindJudgmentPriorRequest(Schema):
    prior_id: str | None = None
    spec_id: str
    specification_view: str
    evidence_quality_view: str
    key_driver_view: list[Any]
    falsifiers: list[Any]


class JudgmentReviewRequest(Schema):
    review_id: str | None = None
    prior_id: str
    analysis_id: str
    conclusion: str
    changed_views: list[Any] | None = None
    remaining_disagreements: list[Any]
    acceptance: str = "revise"


class EvaluationCorpusRequest(Schema):
    corpus_id: str | None = None
    evaluation_profile: str = "core_investment_v1"
    required_case_tags: list[str] | None = None
    metric_dimensions: list[str] | None = None
    cases: list[dict[str, Any]]
    promotion_criteria: list[dict[str, Any]]
    minimum_blind_reviews: int = Field(default=2, ge=2)


class EvaluationRunRequest(Schema):
    run_id: str | None = None
    corpus_id: str
    arm: str
    model: str
    reasoning_effort: str
    prompt_hash: str
    config_hash: str
    tool_profile_hash: str
    deterministic_calculation_hash: str
    extension_profile_hash: str
    case_results: list[dict[str, Any]]
    metrics: dict[str, Any] | None = None
    operations: dict[str, Any]


class BlindReviewAssignmentRequest(Schema):
    assignment_id: str | None = None
    control_run_id: str
    candidate_run_id: str
    reviewer_principal: str


class BlindHumanReviewRequest(Schema):
    review_id: str | None = None
    assignment_id: str
    preference: str
    ratings: dict[str, Any]
    rationale: str


class EvaluationComparisonRequest(Schema):
    comparison_id: str | None = None
    control_run_id: str
    candidate_run_id: str


class StrategySkillRequest(Schema):
    name: str | None = None
    description: str = ""
    body: str = ""
    language: str = "unknown"
    status: str = "draft"
    actor: str = "api"


class OptionalSkillRequest(Schema):
    name: str | None = None
    description: str = ""
    body: str = ""
    status: str = "draft"
    actor: str = "api"


def workspace_root() -> Path:
    return current_workspace_root()


@api.get("/health", auth=None)
def health(request):
    payload = readiness_payload()
    return {**payload, "status": "ok" if payload["ready"] else "not_ready"}


@api.get("/health/live", auth=None)
def health_live(request):
    return liveness_payload()


@api.get("/health/ready", auth=None)
def health_ready(request):
    payload = readiness_payload()
    return api.create_response(request, payload, status=200 if payload["ready"] else 503)


@harness_router.get("/status")
def harness_status(request):
    root = workspace_root()
    prepare_mcp_runtime(root)
    optional_status = list_optional_role_skills(root, include_archived=False)
    return {
        "expected_count": len(EXPECTED_SUBAGENTS),
        "installed_count": len(EXPECTED_SUBAGENTS),
        "fixed_roster_ok": True,
        "skills_installed": len(EXPECTED_SKILLS),
        "core_skills_installed": len(EXPECTED_SKILLS),
        "optional_skills_active": len(optional_status["optional_skills"]),
        "user_visible_skills": list_user_visible_skills(root),
        "subagents": EXPECTED_SUBAGENTS,
        "components_total": len(list_harness_components()),
        "component_tag_counts": count_harness_component_tags(),
        "mcp_tools": [tool["name"] for tool in list_mcp_tools()],
        "db_path": str(tradingcodex_db_path()),
        "workspace_context": persist_workspace_context_if_available(root),
    }


@harness_router.get("/components")
def harness_components(request, tag: str | None = None):
    return {
        "components": list_components_by_tag(tag) if tag else list_harness_components(),
        "component_tag_counts": count_harness_component_tags(),
    }


@harness_router.get("/components/{component_id}")
def harness_component(request, component_id: str):
    component = get_harness_component(component_id)
    if component is None:
        raise Http404(f"Unknown harness component: {component_id}")
    return component


@harness_router.get("/skills")
def harness_skills(request, include_internal: bool = False):
    root = workspace_root()
    return {
        "scope": "all" if include_internal else "user-visible",
        "skills": sorted(build_projection_state(root)["skills"]) if include_internal else list_user_visible_skills(root),
    }


@harness_router.get("/optional-skills")
def harness_optional_skills(request, role: str | None = None, include_archived: bool = True):
    return list_optional_role_skills(workspace_root(), role=role, include_archived=include_archived)


@harness_router.get("/strategies")
def harness_strategies(request, active_only: bool = False):
    return {"strategies": read_strategy_skill_records(workspace_root(), active_only=active_only)}


@harness_router.post("/strategies")
def harness_strategy_create(request, payload: StrategySkillRequest):
    if not payload.name:
        raise ValueError("name is required")
    return create_or_update_strategy_skill(
        workspace_root(),
        payload.name,
        description=payload.description,
        body=payload.body,
        language=payload.language,
        status=payload.status,
        actor=mutation_principal(request),
    )


@harness_router.get("/strategies/{name}")
def harness_strategy_detail(request, name: str):
    return get_strategy_skill_record(workspace_root(), name)


@harness_router.patch("/strategies/{name}")
def harness_strategy_update(request, name: str, payload: StrategySkillRequest):
    return create_or_update_strategy_skill(
        workspace_root(),
        name,
        description=payload.description,
        body=payload.body,
        language=payload.language,
        status=payload.status,
        actor=mutation_principal(request),
    )


@harness_router.delete("/strategies/{name}")
def harness_strategy_delete(request, name: str, force: bool = False):
    return delete_strategy_skill(workspace_root(), name, force=force, actor=mutation_principal(request))


@harness_router.post("/strategies/{name}/activate")
def harness_strategy_activate(request, name: str):
    return set_strategy_skill_status(workspace_root(), name, "active", actor=mutation_principal(request))


@harness_router.post("/strategies/{name}/archive")
def harness_strategy_archive(request, name: str):
    return set_strategy_skill_status(workspace_root(), name, "archived", actor=mutation_principal(request))


def _subagent_records(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": role,
            "skills": skills_for_role(root, role),
            "builtin_skills": ROLE_SKILL_MAP[role],
        }
        for role in EXPECTED_SUBAGENTS
    ]


@subagents_router.get("")
def subagents_index(request):
    root = workspace_root()
    return _subagent_records(root)


@subagents_router.get("/{role}/skills")
def subagent_skills(request, role: str):
    root = workspace_root()
    config = inspect_agent_configuration(root, role)
    return {
        "agent": role,
        "skills": skills_for_role(root, role),
        "core_skills": config.get("builtin_skills", []),
        "optional_skills": config.get("optional_skills", []),
        "projected_skills": config.get("projected_skills", []),
        "config": config,
    }


@subagents_router.get("/{role}/optional-skills")
def subagent_optional_skills(request, role: str, include_archived: bool = True):
    return list_optional_role_skills(workspace_root(), role=role, include_archived=include_archived)


@subagents_router.post("/{role}/optional-skills")
def subagent_optional_skill_create(request, role: str, payload: OptionalSkillRequest):
    if not payload.name:
        raise ValueError("name is required")
    return create_or_update_optional_skill(
        workspace_root(),
        role,
        payload.name,
        description=payload.description,
        body=payload.body,
        status=payload.status,
        actor=mutation_principal(request),
    )


@subagents_router.get("/{role}/optional-skills/{name}")
def subagent_optional_skill_detail(request, role: str, name: str):
    return get_optional_skill_record(workspace_root(), role, name)


@subagents_router.patch("/{role}/optional-skills/{name}")
def subagent_optional_skill_update(request, role: str, name: str, payload: OptionalSkillRequest):
    return create_or_update_optional_skill(
        workspace_root(),
        role,
        name,
        description=payload.description,
        body=payload.body,
        status=payload.status,
        actor=mutation_principal(request),
    )


@subagents_router.delete("/{role}/optional-skills/{name}")
def subagent_optional_skill_delete(request, role: str, name: str, force: bool = False):
    return delete_optional_skill(workspace_root(), role, name, force=force, actor=mutation_principal(request))


@subagents_router.post("/{role}/optional-skills/{name}/activate")
def subagent_optional_skill_activate(request, role: str, name: str):
    return set_optional_skill_status(workspace_root(), role, name, "active", actor=mutation_principal(request))


@subagents_router.post("/{role}/optional-skills/{name}/archive")
def subagent_optional_skill_archive(request, role: str, name: str):
    return set_optional_skill_status(workspace_root(), role, name, "archived", actor=mutation_principal(request))


@harness_router.get("/subagents/prompt")
def subagent_prompt(request, q: str):
    root = workspace_root()
    return {"prompt": build_subagent_starter_prompt(q, root), "intake_summary": build_workflow_intake_summary(q, root)}


@harness_router.post("/subagents/loop")
def subagent_loop(request, payload: WorkflowLoopRequest):
    mutation_principal(request)
    return evaluate_artifact_supervisor_loop(
        workspace_root(),
        payload.original_request,
        payload.artifact_paths,
        record=payload.record,
        workflow_run_id=payload.workflow_run_id,
    )


@policy_router.post("/simulate")
def simulate_policy(request, payload: PolicyRequest):
    mutation_principal(request)
    return simulate_policy_service(workspace_root(), payload.dict())


@orders_router.get("/tickets")
def order_tickets(request, limit: int = 30):
    return list_order_tickets(workspace_root(), {"limit": limit})


@orders_router.post("/tickets")
def order_ticket_create(request, payload: OrderTicketRequest):
    return create_order_ticket(workspace_root(), {**payload.dict(), "principal_id": mutation_principal(request)})


@orders_router.get("/tickets/{ticket_id}")
def order_ticket_detail(request, ticket_id: str):
    return get_order_ticket(workspace_root(), {"ticket_id": ticket_id})


@orders_router.post("/tickets/{ticket_id}/checks")
def order_ticket_checks(request, ticket_id: str, payload: OrderTicketActionRequest):
    return run_order_checks(workspace_root(), {**payload.dict(), "ticket_id": ticket_id, "principal_id": mutation_principal(request)})


@orders_router.post("/tickets/{ticket_id}/approval-request")
def order_ticket_approval_request(request, ticket_id: str, payload: OrderTicketApprovalRequest):
    data = payload.dict()
    principal_id = mutation_principal(request)
    return request_order_approval(workspace_root(), {**data, "ticket_id": ticket_id, "principal_id": principal_id, "approved_by": principal_id})


@orders_router.post("/tickets/{ticket_id}/discard")
def order_ticket_discard(request, ticket_id: str):
    principal_id = mutation_principal(request)
    return call_mcp_tool(
        workspace_root(),
        "discard_draft_order",
        {"ticket_id": ticket_id},
        transport_principal=principal_id,
    )


@approvals_router.post("")
def create_approval(request, payload: ApprovalRequest):
    data = payload.dict()
    principal_id = mutation_principal(request)
    return request_order_approval(workspace_root(), {**data, "principal_id": principal_id, "approved_by": principal_id})


@executions_router.post("/submit-approved")
def submit_approved(request, payload: SubmitApprovedRequest):
    return call_mcp_tool(
        workspace_root(),
        "submit_approved_order",
        payload.dict(exclude_none=True),
        transport_principal=mutation_principal(request),
    )


@executions_router.post("/cancel-submitted")
def cancel_submitted(request, payload: CancelSubmittedRequest):
    return call_mcp_tool(
        workspace_root(),
        "cancel_submitted_order",
        payload.dict(exclude_none=True),
        transport_principal=mutation_principal(request),
    )


@portfolio_router.get("/snapshot")
def portfolio_snapshot(request):
    return list_positions(workspace_root())


@portfolio_router.get("/reconciliations")
def portfolio_reconciliations(request, limit: int = 20):
    return list_reconciliation_runs(workspace_root(), {"limit": limit})


@brokers_router.get("")
def brokers_index(request):
    return list_broker_connections(workspace_root())


@brokers_router.get("/{broker_id}")
def broker_detail(request, broker_id: str):
    return get_broker_connection_status(workspace_root(), {"broker_id": broker_id})


@brokers_router.post("/{broker_id}/sync")
def broker_sync(request, broker_id: str, payload: BrokerSyncRequest):
    return sync_broker_account(workspace_root(), {**payload.dict(), "broker_id": broker_id, "principal_id": mutation_principal(request)})


@audit_router.get("/events")
def audit_events(request):
    try:
        root = workspace_root()
        ensure_runtime_database(root)
        context = workspace_context_payload(root)
        from apps.audit.models import AuditEvent

        return [
            {
                "created_at": event.created_at.isoformat(),
                "actor_principal": event.actor_principal,
                "source": event.source,
                "action": event.action,
                "decision": event.decision,
                "resource": event.resource,
                "workspace_context": event.workspace_context,
            }
            for event in AuditEvent.objects.filter(workspace_context__workspace_id=context["workspace_id"]).order_by("-created_at", "-id")[:100]
        ]
    except Exception:
        return []


@workflows_router.post("/intake")
def workflow_intake(request, payload: WorkflowValidationRequest):
    mutation_principal(request)
    return record_workflow_intake(workspace_root(), payload.original_request)


@workflows_router.post("/record")
def workflow_record(request, payload: WorkflowRecordRequest):
    mutation_principal(request)
    plan = payload.plan
    intake = read_workflow_intake(workspace_root(), str(plan.get("workflow_run_id") or ""))
    return record_workflow_plan(workspace_root(), plan, intake=intake)


@workflows_router.get("/{workflow_id}")
def workflow_detail(request, workflow_id: str):
    return {"workflow_id": workflow_id, "artifacts": list_workflow_artifacts(workspace_root())["artifacts"]}


@workflows_router.post("/{workflow_id}/validate")
def workflow_validate(request, workflow_id: str, payload: WorkflowValidationRequest):
    mutation_principal(request)
    if payload.plan:
        plan = payload.plan
        plan_run_id = str(plan.get("workflow_run_id") or "")
        if plan_run_id != workflow_id:
            return {"ok": False, "errors": ["workflow_run_id must match the workflow URL"], "workflow_run_id": plan_run_id}
        intake = read_workflow_intake(workspace_root(), workflow_id)
        if not intake:
            return {"ok": False, "errors": ["recorded workflow intake is required"], "workflow_run_id": plan_run_id}
        if is_workflow_plan_draft(plan):
            try:
                plan = compile_workflow_plan_draft(plan, intake=intake)
            except ValueError as exc:
                return {"ok": False, "errors": [str(exc)], "workflow_run_id": plan_run_id}
        return validate_workflow_plan(plan, intake=intake)
    return {
        "workflow_id": workflow_id,
        "starter_prompt": build_subagent_starter_prompt(payload.original_request, workspace_root()),
        "intake_summary": build_workflow_intake_summary(payload.original_request, workspace_root()),
        "deterministic_preview": build_deterministic_workflow_plan(workspace_root(), payload.original_request, workflow_run_id=workflow_id),
    }


@integrations_router.get("/mcp-tools")
def mcp_tools(request):
    prepare_mcp_runtime(workspace_root())
    return {"tools": list_mcp_tools()}


@research_router.post("/artifacts")
def create_research(request, payload: ResearchArtifactRequest):
    return create_research_artifact(workspace_root(), {**payload.dict(), "created_by": mutation_principal(request)})


@research_router.get("/artifacts")
def list_research(request, artifact_type: str | None = None, universe: str | None = None, symbol: str | None = None, limit: int = 50):
    return list_research_artifacts(workspace_root(), {"artifact_type": artifact_type, "universe": universe, "symbol": symbol, "limit": limit})


@research_router.get("/artifacts/{artifact_id}")
def get_research(request, artifact_id: str):
    return get_research_artifact(workspace_root(), {"artifact_id": artifact_id})


@research_router.post("/artifacts/{artifact_id}/export")
def export_research(request, artifact_id: str, export_path: str | None = None):
    mutation_principal(request)
    return export_research_artifact_md(workspace_root(), {"artifact_id": artifact_id, "export_path": export_path})


@research_router.post("/search")
def search_research(request, payload: ResearchSearchRequest):
    mutation_principal(request)
    return search_research_artifacts(workspace_root(), payload.dict())


@research_router.post("/source-snapshots")
def create_source_snapshot(request, payload: SourceSnapshotRequest):
    return record_source_snapshot(workspace_root(), {**payload.dict(), "principal_id": mutation_principal(request)})


@research_router.post("/specs")
def create_spec(request, payload: ResearchSpecRequest):
    principal = mutation_principal(request)
    if principal not in {*RESEARCH_ROLES, "head-manager"}:
        raise HttpError(403, "ResearchSpec creation requires a research role or head-manager")
    return create_research_spec(workspace_root(), {**payload.dict(exclude_none=True), "created_by": principal})


@research_router.get("/specs")
def list_specs(request):
    return list_research_specs(workspace_root())


@research_router.get("/specs/{spec_id}")
def get_spec(request, spec_id: str):
    return get_research_spec(workspace_root(), {"spec_id": spec_id})


@research_router.post("/replay-manifests")
def create_replay(request, payload: ReplayManifestRequest):
    principal = mutation_principal(request)
    if principal not in {*RESEARCH_ROLES, "head-manager"}:
        raise HttpError(403, "replay manifest creation requires a research role or head-manager")
    return create_replay_manifest(workspace_root(), {**payload.dict(exclude_none=True), "created_by": principal})


@research_router.post("/experiments")
def create_experiment(request, payload: ExperimentRunRequest):
    principal = mutation_principal(request)
    if principal not in {*RESEARCH_ROLES, "head-manager"}:
        raise HttpError(403, "experiment recording requires a research role or head-manager")
    return record_experiment_run(workspace_root(), {**payload.dict(exclude_none=True), "created_by": principal})


@research_router.post("/causal-equity-analyses")
def create_causal_analysis(request, payload: CausalEquityAnalysisRequest):
    principal = mutation_principal(request)
    if principal != "valuation-analyst":
        raise HttpError(403, "causal equity analysis requires valuation-analyst")
    return create_causal_equity_analysis(workspace_root(), {**payload.dict(exclude_none=True), "created_by": principal})


@research_router.post("/judgment-priors")
def create_judgment_prior(request, payload: BlindJudgmentPriorRequest):
    principal = mutation_principal(request)
    if principal != "judgment-reviewer":
        raise HttpError(403, "blind judgment prior requires judgment-reviewer")
    return record_blind_judgment_prior(workspace_root(), {**payload.dict(exclude_none=True), "reviewer": principal})


@research_router.post("/judgment-reviews")
def create_judgment_review(request, payload: JudgmentReviewRequest):
    principal = mutation_principal(request)
    if principal != "judgment-reviewer":
        raise HttpError(403, "judgment review requires judgment-reviewer")
    return complete_judgment_review(workspace_root(), {**payload.dict(exclude_none=True), "reviewer": principal})


@research_router.post("/index/rebuild")
def rebuild_index(request):
    if mutation_principal(request) != "head-manager":
        raise HttpError(403, "research index rebuild requires head-manager")
    return rebuild_research_index(workspace_root())


@research_router.post("/forecasts")
def create_forecast(request, payload: ForecastIssueRequest):
    principal = mutation_principal(request)
    if principal not in FORECASTING_DISCIPLINE_ROLES:
        raise HttpError(403, "forecast issuance requires a forecast-author role")
    return issue_forecast(workspace_root(), {**payload.dict(exclude_none=True), "author": principal, "role": principal})


@research_router.get("/forecasts")
def forecast_list(request, status: str | None = None, role: str | None = None, limit: int = 100):
    return list_forecasts(workspace_root(), {"status": status, "role": role, "limit": limit})


@research_router.get("/forecasts/calibration")
def forecast_calibration(request, minimum_sample: int = 20):
    return calibration_report(workspace_root(), {"minimum_sample": minimum_sample})


@research_router.get("/forecasts/{forecast_id}")
def forecast_detail(request, forecast_id: str, include_history: bool = True):
    return get_forecast(workspace_root(), {"forecast_id": forecast_id, "include_history": include_history})


@research_router.post("/forecasts/{forecast_id}/revisions")
def forecast_revision(request, forecast_id: str, payload: ForecastRevisionRequest):
    principal = mutation_principal(request)
    if principal not in FORECASTING_DISCIPLINE_ROLES:
        raise HttpError(403, "forecast revision requires a forecast-author role")
    return revise_forecast(workspace_root(), {
        **payload.dict(exclude_none=True),
        "forecast_id": forecast_id,
        "author": principal,
    })


@research_router.post("/forecasts/{forecast_id}/resolution")
def forecast_resolution(request, forecast_id: str, payload: ForecastResolutionRequest):
    principal = mutation_principal(request)
    if principal != "judgment-reviewer":
        raise HttpError(403, "forecast resolution requires judgment-reviewer")
    return resolve_forecast(workspace_root(), {
        **payload.dict(exclude_none=True),
        "forecast_id": forecast_id,
        "resolver": principal,
    })


@research_router.post("/forecasts/{forecast_id}/score")
def forecast_score(request, forecast_id: str, idempotency_key: str | None = None):
    if mutation_principal(request) not in {"head-manager", "judgment-reviewer"}:
        raise HttpError(403, "forecast scoring requires head-manager or judgment-reviewer")
    return score_forecast(workspace_root(), {"forecast_id": forecast_id, "idempotency_key": idempotency_key})


@evaluations_router.post("/corpora")
def create_evaluation_corpus_api(request, payload: EvaluationCorpusRequest):
    principal = mutation_principal(request)
    if _principal_role(principal) != "head-manager":
        raise HttpError(403, "evaluation corpus creation requires head-manager")
    return create_evaluation_corpus(workspace_root(), {**payload.dict(exclude_none=True), "created_by": principal})


@evaluations_router.post("/runs")
def create_evaluation_run_api(request, payload: EvaluationRunRequest):
    principal = mutation_principal(request)
    if _principal_role(principal) != "head-manager":
        raise HttpError(403, "evaluation run recording requires head-manager")
    return record_evaluation_run(workspace_root(), {**payload.dict(exclude_none=True), "created_by": principal})


@evaluations_router.post("/blind-review-assignments")
def create_blind_review_assignment_api(request, payload: BlindReviewAssignmentRequest):
    principal = mutation_principal(request)
    if _principal_role(principal) != "head-manager":
        raise HttpError(403, "blind evaluation assignment requires head-manager")
    return create_blind_review_assignment(
        workspace_root(),
        {**payload.dict(exclude_none=True), "assigned_by": principal},
    )


@evaluations_router.get("/blind-review-assignments/{assignment_id}")
def get_blind_review_packet_api(request, assignment_id: str):
    principal = mutation_principal(request)
    if _principal_role(principal) != "judgment-reviewer":
        raise HttpError(403, "blind evaluation packet requires judgment-reviewer")
    return get_blind_review_packet(workspace_root(), {"assignment_id": assignment_id, "reviewer": principal})


@evaluations_router.post("/blind-reviews")
def create_blind_human_review_api(request, payload: BlindHumanReviewRequest):
    principal = mutation_principal(request)
    if _principal_role(principal) != "judgment-reviewer":
        raise HttpError(403, "blind evaluation review requires judgment-reviewer")
    return record_blind_human_review(workspace_root(), {**payload.dict(exclude_none=True), "reviewer": principal})


@evaluations_router.post("/comparisons")
def create_evaluation_comparison_api(request, payload: EvaluationComparisonRequest):
    principal = mutation_principal(request)
    if _principal_role(principal) not in {"head-manager", "judgment-reviewer"}:
        raise HttpError(403, "evaluation comparison requires head-manager or judgment-reviewer")
    return compare_evaluation_runs(workspace_root(), payload.dict(exclude_none=True))


api.add_router("/harness", harness_router)
api.add_router("/subagents", subagents_router)
api.add_router("/policy", policy_router)
api.add_router("/orders", orders_router)
api.add_router("/approvals", approvals_router)
api.add_router("/executions", executions_router)
api.add_router("/portfolio", portfolio_router)
api.add_router("/brokers", brokers_router)
api.add_router("/audit", audit_router)
api.add_router("/workflows", workflows_router)
api.add_router("/integrations", integrations_router)
api.add_router("/research", research_router)
api.add_router("/evaluations", evaluations_router)
