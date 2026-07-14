from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingcodex_service.application.runtime import ensure_runtime_database, workspace_context_payload


def list_recent_activity(workspace_root: Path | str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    """Return durable service activity without modeling Codex orchestration state."""
    ensure_runtime_database(workspace_root)
    context = workspace_context_payload(workspace_root)
    items: list[dict[str, Any]] = []

    from apps.mcp.models import McpToolCall

    for call in _workspace_rows(McpToolCall.objects, context).order_by("-created_at", "-id")[:limit]:
        items.append({
            "kind": "MCP",
            "title": call.tool_name,
            "subtitle": call.principal_id,
            "status": call.status,
            "status_class": _status_class(call.status),
            "created_at": call.created_at,
        })

    from apps.audit.models import AuditEvent

    for event in _workspace_rows(AuditEvent.objects, context).order_by("-created_at", "-id")[:limit]:
        items.append({
            "kind": "Audit",
            "title": event.action,
            "subtitle": event.actor_principal,
            "status": event.decision,
            "status_class": _status_class(event.decision),
            "created_at": event.created_at,
        })
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:limit]


def _workspace_rows(queryset: Any, context: dict[str, Any]) -> Any:
    workspace_id = str(context.get("workspace_id") or "")
    return queryset.filter(workspace_context__workspace_id=workspace_id) if workspace_id else queryset.none()


def _status_class(status: str) -> str:
    value = str(status or "").lower()
    if value in {"ok", "allow", "allowed", "completed", "recorded", "accepted"}:
        return "good"
    if value in {"error", "deny", "denied", "failed", "blocked", "rejected"}:
        return "bad"
    if value in {"pending", "waiting", "running", "starting"}:
        return "warn"
    return "neutral"
