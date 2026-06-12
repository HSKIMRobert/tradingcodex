from __future__ import annotations

import json
import re
from typing import Any

from django.utils import timezone
from django.db.models import QuerySet

from apps.mcp.models import (
    McpExternalTool,
    McpExternalToolCall,
    McpExternalToolPermission,
    McpRouter,
    McpToolDefinition,
)
from apps.policy.services import role_for_principal_id
from tradingcodex_service.application.common import stable_hash
from tradingcodex_service.application.runtime import workspace_context_payload


READ_ONLY_PROXY_MODES = {"read_only", "summary_only"}
SERVICE_PROXY_MODES = {"service_adapter", "service_path"}
RESEARCH_ROLES = {
    "head-manager",
    "fundamental-analyst",
    "technical-analyst",
    "news-analyst",
    "macro-analyst",
    "instrument-analyst",
    "valuation-analyst",
}
ACCOUNT_READ_ROLES = {"head-manager", "portfolio-manager", "risk-manager", "execution-operator"}
PORTFOLIO_STATE_ROLES = {"portfolio-manager", "risk-manager"}


def set_mcp_tools_enabled(queryset: QuerySet[McpToolDefinition], enabled: bool, actor: str = "admin") -> int:
    count = queryset.update(enabled=enabled)
    _audit("mcp_tool.enabled" if enabled else "mcp_tool.disabled", {"count": count}, actor)
    return count


def sync_builtin_mcp_registry(actor: str = "admin") -> None:
    from tradingcodex_service.mcp_runtime import sync_mcp_tool_definitions

    sync_mcp_tool_definitions()
    _audit("mcp_tool_registry.synced", {"source": "builtin"}, actor)


def create_or_update_router(
    *,
    name: str,
    label: str = "",
    transport: str = "stdio",
    command: str = "",
    url: str = "",
    credential_ref: str = "",
    enabled: bool = False,
    actor: str = "web",
) -> McpRouter:
    if not name:
        raise ValueError("router name is required")
    router, created = McpRouter.objects.update_or_create(
        name=name,
        defaults={
            "label": label,
            "transport": transport or "stdio",
            "command": command,
            "url": url,
            "credential_ref": credential_ref,
            "enabled": bool(enabled),
        },
    )
    _audit("external_mcp_router.created" if created else "external_mcp_router.updated", {"router": router.name, "enabled": router.enabled}, actor)
    return router


def import_external_mcp_discovery(router: McpRouter, discovery_payload: str | dict[str, Any], actor: str = "web") -> dict[str, Any]:
    payload = _coerce_payload(discovery_payload)
    imported: list[McpExternalTool] = []
    for primitive, item in _iter_discovered_primitives(payload):
        imported.append(upsert_external_mcp_tool(router, primitive, item))
    router.last_status = "ok"
    router.last_error = ""
    router.last_checked_at = timezone.now()
    router.save(update_fields=["last_status", "last_error", "last_checked_at", "updated_at"])
    _audit("external_mcp.discovery_imported", {"router": router.name, "count": len(imported)}, actor)
    return {"router": router.name, "imported": len(imported), "tool_ids": [tool.id for tool in imported]}


def upsert_external_mcp_tool(router: McpRouter, primitive: str, item: dict[str, Any]) -> McpExternalTool:
    external_name = str(item.get("name") or item.get("uri") or item.get("id") or "").strip()
    if not external_name:
        raise ValueError("external MCP item is missing name, uri, or id")
    description = str(item.get("description") or item.get("title") or "")
    input_schema = item.get("inputSchema") or item.get("input_schema") or item.get("schema") or {}
    output_schema = item.get("outputSchema") or item.get("output_schema") or {}
    schema_hash = stable_hash({"primitive": primitive, "name": external_name, "description": description, "input_schema": input_schema, "output_schema": output_schema})
    classification = classify_external_mcp_item(external_name, description, input_schema, primitive=primitive)
    tool, created = McpExternalTool.objects.get_or_create(
        router=router,
        primitive=primitive,
        external_name=external_name,
        defaults={
            "description": description,
            "input_schema": input_schema if isinstance(input_schema, dict) else {},
            "output_schema": output_schema if isinstance(output_schema, dict) else {},
            "schema_hash": schema_hash,
            **classification,
            "last_seen_at": timezone.now(),
        },
    )
    if created:
        return tool
    changed = bool(tool.schema_hash and tool.schema_hash != schema_hash)
    tool.description = description
    tool.input_schema = input_schema if isinstance(input_schema, dict) else {}
    tool.output_schema = output_schema if isinstance(output_schema, dict) else {}
    tool.schema_hash = schema_hash
    tool.last_seen_at = timezone.now()
    if changed:
        tool.enabled = False
        tool.drift_detected = True
        tool.review_status = "schema_changed"
    else:
        for field, value in classification.items():
            if tool.review_status in {"review_required", "auto_classified"} or field in {"category", "risk_level", "sensitivity", "canonical_capability"}:
                setattr(tool, field, value)
    tool.save()
    return tool


def classify_external_mcp_item(name: str, description: str = "", schema: dict[str, Any] | None = None, *, primitive: str = "tool") -> dict[str, Any]:
    text = " ".join([name, description, json.dumps(schema or {}, sort_keys=True, default=str)]).lower()
    if primitive != "tool":
        return {
            "category": "market_data" if primitive == "resource" else "workflow_prompt",
            "risk_level": "read",
            "sensitivity": "public",
            "canonical_capability": "market_data.read" if primitive == "resource" else "workflow.prompt.read",
            "proxy_mode": "read_only",
            "allowed_roles": sorted(RESEARCH_ROLES),
            "conditions": {"as_of_required": primitive == "resource"},
            "review_status": "auto_classified",
        }
    if _matches(text, r"secret|credential|password|api[_\s-]?key|token|\.env"):
        return _classification("secret", "blocked", "secret", "secret.read", "blocked", [])
    if _matches(text, r"transfer|withdraw|wire|ach|deposit"):
        return _classification("execution", "execution", "private", "cash.transfer", "service_path", [])
    if _matches(text, r"place[_\s-]?order|submit[_\s-]?order|create[_\s-]?order|replace[_\s-]?order|cancel[_\s-]?order|trade|execute"):
        capability = "order.cancel" if "cancel" in text else "order.submit"
        return _classification("execution", "execution", "private", capability, "service_adapter", [])
    if _matches(text, r"policy|permission|principal|capability|allowlist|admin|enable[_\s-]?tool|disable[_\s-]?tool"):
        return _classification("policy_admin", "write", "canonical_state", "policy.config.write", "blocked", [])
    if _matches(text, r"position|positions|balance|balances|account|buying[_\s-]?power|portfolio|orders|fills|holdings"):
        return _classification("account_read", "read", "private", "account.positions.read", "summary_only", sorted(ACCOUNT_READ_ROLES))
    if _matches(text, r"quote|quotes|candles|bars|ohlcv|price|market[_\s-]?data|ticker|tickers|news|filing|fundamental|financial|earnings"):
        return _classification("market_data", "read", "public", "market_data.read", "read_only", sorted(RESEARCH_ROLES | PORTFOLIO_STATE_ROLES))
    if _matches(text, r"snapshot|source|artifact|research|dataset|import"):
        return _classification("research_write", "write", "research", "research.snapshot.write", "service_path", sorted(RESEARCH_ROLES))
    return _classification("unknown", "unknown", "unknown", "mcp.external.unknown", "blocked", [])


def set_external_tool_policy(
    tool: McpExternalTool,
    *,
    category: str | None = None,
    risk_level: str | None = None,
    sensitivity: str | None = None,
    canonical_capability: str | None = None,
    proxy_mode: str | None = None,
    allowed_roles: list[str] | None = None,
    enabled: bool | None = None,
    review_status: str = "reviewed",
    actor: str = "web",
) -> McpExternalTool:
    if category is not None:
        tool.category = category or "unknown"
    if risk_level is not None:
        tool.risk_level = risk_level or "unknown"
    if sensitivity is not None:
        tool.sensitivity = sensitivity or "unknown"
    if canonical_capability is not None:
        tool.canonical_capability = canonical_capability
    if proxy_mode is not None:
        tool.proxy_mode = proxy_mode or "blocked"
    if allowed_roles is not None:
        tool.allowed_roles = [role for role in allowed_roles if role]
    if enabled is not None:
        if enabled:
            _validate_external_tool_can_enable(tool)
        tool.enabled = bool(enabled)
    tool.review_status = review_status or "reviewed"
    if tool.review_status == "reviewed":
        tool.drift_detected = False
    tool.save()
    _audit("external_mcp_tool.policy_updated", {"tool": str(tool), "enabled": tool.enabled, "proxy_mode": tool.proxy_mode}, actor)
    return tool


def evaluate_external_mcp_proxy_call(
    workspace_root: Any,
    tool: McpExternalTool,
    *,
    principal_id: str,
    arguments: dict[str, Any] | None = None,
    actor: str = "mcp-proxy",
) -> dict[str, Any]:
    reasons = external_tool_denial_reasons(tool, principal_id)
    decision = "allow" if not reasons else "deny"
    result = {
        "decision": decision,
        "reasons": reasons,
        "router": tool.router.name,
        "external_name": tool.external_name,
        "proxy_mode": tool.proxy_mode,
        "category": tool.category,
        "risk_level": tool.risk_level,
        "canonical_capability": tool.canonical_capability,
        "adapter_call_allowed": decision == "allow" and tool.proxy_mode in SERVICE_PROXY_MODES,
        "direct_proxy_allowed": decision == "allow" and tool.proxy_mode in READ_ONLY_PROXY_MODES,
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }
    McpExternalToolCall.objects.create(
        external_tool=tool,
        router_name=tool.router.name,
        external_name=tool.external_name,
        principal_id=principal_id,
        proxy_mode=tool.proxy_mode,
        decision=decision,
        reasons=reasons,
        request=arguments or {},
        response=result,
        request_hash=stable_hash(arguments or {}),
        result_hash=stable_hash(result),
        workspace_context=result["workspace_context"],
    )
    _audit("external_mcp.proxy_allowed" if decision == "allow" else "external_mcp.proxy_denied", {"tool": str(tool), "reasons": reasons}, actor)
    return result


def external_tool_denial_reasons(tool: McpExternalTool, principal_id: str) -> list[str]:
    reasons: list[str] = []
    role = role_for_principal_id(principal_id)
    if not tool.router.enabled:
        reasons.append(f"router is disabled: {tool.router.name}")
    if not tool.enabled:
        reasons.append(f"external tool is disabled: {tool.external_name}")
    if tool.drift_detected:
        reasons.append("schema drift requires review")
    if tool.review_status not in {"reviewed", "approved"}:
        reasons.append(f"tool review is not complete: {tool.review_status}")
    if tool.category in {"secret", "policy_admin"}:
        reasons.append(f"category is not proxyable: {tool.category}")
    if tool.category == "execution" and tool.proxy_mode not in SERVICE_PROXY_MODES:
        reasons.append("execution tools must map to a TradingCodex service adapter path")
    if tool.category == "unknown":
        reasons.append("unknown tools require classification before proxy")
    allowed = set(tool.allowed_roles or [])
    if not _permission_allows(tool, principal_id, role, allowed):
        reasons.append(f"principal is not allowed for external tool: {principal_id}")
    return list(dict.fromkeys(reasons))


def _validate_external_tool_can_enable(tool: McpExternalTool) -> None:
    if tool.drift_detected:
        raise ValueError("schema drift requires review before enabling")
    if tool.proxy_mode == "direct":
        raise ValueError("direct raw proxy mode is not allowed")
    if tool.category in {"secret", "policy_admin", "unknown"}:
        raise ValueError(f"{tool.category} tools cannot be enabled for proxy")
    if tool.category == "execution" and tool.proxy_mode not in SERVICE_PROXY_MODES:
        raise ValueError("execution tools must use service_adapter or service_path proxy mode")


def _permission_allows(tool: McpExternalTool, principal_id: str, role: str, allowed_roles: set[str]) -> bool:
    if principal_id in allowed_roles or role in allowed_roles:
        return True
    permissions = McpExternalToolPermission.objects.filter(external_tool=tool, enabled=True)
    if permissions.filter(decision="deny", principal_or_role__in={principal_id, role}).exists():
        return False
    return permissions.filter(decision="allow", principal_or_role__in={principal_id, role}).exists()


def _classification(category: str, risk_level: str, sensitivity: str, capability: str, proxy_mode: str, roles: list[str]) -> dict[str, Any]:
    return {
        "category": category,
        "risk_level": risk_level,
        "sensitivity": sensitivity,
        "canonical_capability": capability,
        "proxy_mode": proxy_mode,
        "allowed_roles": roles,
        "conditions": {},
        "review_status": "auto_classified",
    }


def _matches(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, flags=re.I))


def _coerce_payload(payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not str(payload).strip():
        return {}
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("MCP discovery payload must be a JSON object")
    return parsed


def _iter_discovered_primitives(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    body = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    primitives: list[tuple[str, dict[str, Any]]] = []
    for key, primitive in [("tools", "tool"), ("resources", "resource"), ("prompts", "prompt")]:
        items = body.get(key) if isinstance(body, dict) else None
        if isinstance(items, list):
            primitives.extend((primitive, item) for item in items if isinstance(item, dict))
    return primitives


def _audit(action: str, payload: dict[str, Any], actor: str) -> None:
    from tradingcodex_service.application.audit import write_audit_event_if_available

    write_audit_event_if_available(None, actor, "admin", {"type": action, "payload": payload})
