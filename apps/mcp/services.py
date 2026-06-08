from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from apps.mcp.models import McpToolDefinition


def set_mcp_tools_enabled(queryset: QuerySet[McpToolDefinition], enabled: bool, actor: str = "admin") -> int:
    count = queryset.update(enabled=enabled)
    _audit("mcp_tool.enabled" if enabled else "mcp_tool.disabled", {"count": count}, actor)
    return count


def sync_builtin_mcp_registry(actor: str = "admin") -> None:
    from tradingcodex_service.mcp_runtime import sync_mcp_tool_definitions

    sync_mcp_tool_definitions()
    _audit("mcp_tool_registry.synced", {"source": "builtin"}, actor)


def _audit(action: str, payload: dict[str, Any], actor: str) -> None:
    from tradingcodex_service.domain import write_audit_event_if_available

    write_audit_event_if_available(None, actor, "admin", {"type": action, "payload": payload})
