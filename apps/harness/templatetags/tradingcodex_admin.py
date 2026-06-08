from __future__ import annotations

from typing import Any

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from tradingcodex_service.domain import tradingcodex_db_path


register = template.Library()


def _count(model: Any, **filters: Any) -> int:
    try:
        return model.objects.filter(**filters).count() if filters else model.objects.count()
    except Exception:
        return 0


def _admin_url(name: str) -> str:
    try:
        return reverse(f"admin:{name}_changelist")
    except NoReverseMatch:
        return "#"


@register.simple_tag
def tc_admin_overview() -> dict[str, Any]:
    from apps.audit.models import AuditEvent
    from apps.harness.models import SkillProposal, WorkspaceContext
    from apps.integrations.models import AdapterDefinition
    from apps.mcp.models import McpToolCall, McpToolDefinition
    from apps.orders.models import ApprovalReceipt, ExecutionResult, OrderIntent
    from apps.policy.models import PolicyDecision, RestrictedSymbol
    from apps.portfolio.models import PortfolioSnapshot
    from apps.research.models import ResearchArtifact, SourceSnapshot

    latest_snapshot = PortfolioSnapshot.objects.order_by("-created_at", "-id").first()
    portfolio_payload = latest_snapshot.payload if latest_snapshot and isinstance(latest_snapshot.payload, dict) else {}
    positions = portfolio_payload.get("positions") if isinstance(portfolio_payload.get("positions"), dict) else {}
    cash_krw = portfolio_payload.get("cash_krw")
    if cash_krw is None:
        cash_krw = 0

    recent_calls = McpToolCall.objects.order_by("-created_at", "-id")[:6]
    recent_audit = AuditEvent.objects.order_by("-created_at", "-id")[:6]

    return {
        "generated_at": timezone.now(),
        "db_path": str(tradingcodex_db_path()),
        "workspace_count": _count(WorkspaceContext),
        "research_count": _count(ResearchArtifact),
        "source_snapshot_count": _count(SourceSnapshot),
        "pending_skill_proposals": _count(SkillProposal, status="proposed"),
        "draft_orders": _count(OrderIntent),
        "valid_approvals": _count(ApprovalReceipt, valid=True),
        "executions": _count(ExecutionResult),
        "policy_denies": _count(PolicyDecision, decision="deny"),
        "restricted_symbols": _count(RestrictedSymbol, active=True),
        "mcp_tools_enabled": _count(McpToolDefinition, enabled=True),
        "mcp_tools_total": _count(McpToolDefinition),
        "mcp_errors": _count(McpToolCall, status="error"),
        "adapters_enabled": _count(AdapterDefinition, enabled=True),
        "live_adapters_enabled": _count(AdapterDefinition, enabled=True, live=True),
        "cash_krw": cash_krw,
        "positions_count": len(positions),
        "latest_snapshot": latest_snapshot,
        "recent_calls": recent_calls,
        "recent_audit": recent_audit,
        "quick_links": [
            {"label": "Research Memory", "url": _admin_url("research_researchartifact"), "kind": "Research"},
            {"label": "Order Intents", "url": _admin_url("orders_orderintent"), "kind": "Orders"},
            {"label": "Approvals", "url": _admin_url("orders_approvalreceipt"), "kind": "Risk"},
            {"label": "Executions", "url": _admin_url("orders_executionresult"), "kind": "Execution"},
            {"label": "Paper Portfolio", "url": _admin_url("portfolio_portfoliosnapshot"), "kind": "Portfolio"},
            {"label": "MCP Calls", "url": _admin_url("mcp_mcptoolcall"), "kind": "MCP"},
            {"label": "Audit Events", "url": _admin_url("audit_auditevent"), "kind": "Audit"},
            {"label": "Workspace Contexts", "url": _admin_url("harness_workspacecontext"), "kind": "Harness"},
        ],
    }


@register.filter
def tc_app_purpose(app_label: str) -> str:
    return {
        "auth": "Admin users, groups, and staff access.",
        "harness": "Workspace provenance, role skills, and skill proposals.",
        "research": "DB-canonical markdown research, source snapshots, and evidence packs.",
        "orders": "Order intents, approval receipts, and paper/stub execution results.",
        "portfolio": "Central paper portfolio snapshots, cash, and positions.",
        "policy": "Principals, capability allowlists, restricted list, and policy decisions.",
        "mcp": "Tool registry and MCP call ledger.",
        "audit": "Append-only operational and policy event history.",
        "integrations": "Read-only data and execution adapter definitions.",
        "universes": "Enabled investment universe plugins and defaults.",
        "workflows": "Workflow runs, handoffs, readiness labels, and artifacts.",
    }.get(app_label, "Operational records and configuration.")


@register.filter
def tc_status_class(value: Any) -> str:
    text = str(value).lower()
    if text in {"ok", "allow", "accepted", "approved", "enabled", "filled", "valid", "true"}:
        return "tc-status-good"
    if text in {"deny", "denied", "rejected", "error", "blocked", "disabled", "false"}:
        return "tc-status-bad"
    if text in {"proposed", "pending", "recorded", "stubbed", "research-only"}:
        return "tc-status-warn"
    return "tc-status-neutral"
