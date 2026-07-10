from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from typing import Any

from tradingcodex_service.application.customization import replace_managed_block
from tradingcodex_service.application.common import atomic_write_text, workspace_launcher_command
from tradingcodex_service.application.runtime import ensure_runtime_database, tradingcodex_db_path
from tradingcodex_service.mcp_runtime import SAFE_HOME_TOOL_NAMES, TOOL_REGISTRY, call_mcp_tool, default_principal_for_tool
from tradingcodex_cli.commands.utils import _list_option, _option_value, print_json

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
    if argv and argv[0] == "external":
        mcp_external(root, argv[1:])
        return
    if argv and argv[0] == "install-global":
        install_global_mcp(argv[1:])
        return
    if not argv or argv[0] != "call":
        raise ValueError("Usage: tcx mcp call <tool> [tool args] | tcx mcp external <action> [options] | tcx mcp ledger [--tool name] | tcx mcp stdio")
    tool = argv[1] if len(argv) > 1 else ""
    if tool == "promote_lesson":
        raise PermissionError(
            "lesson promotion is unavailable from generic CLI calls; use the role-scoped judgment-reviewer stdio MCP"
        )
    args = argv[2:]
    receipt_path = _option_value(args, "--approval-receipt")
    principal_id = _option_value(args, "--principal")
    payload: dict[str, Any] = {}
    payload.update({
        "order_id": _option_value(args, "--order-id"),
        "ticket_id": _option_value(args, "--ticket-id") or _option_value(args, "--order-ticket-id"),
        "natural_language": _option_value(args, "--natural-language") or _option_value(args, "--prompt"),
        "provider": _option_value(args, "--provider"),
        "provider_id": _option_value(args, "--provider-id") or _option_value(args, "--provider"),
        "template": _option_value(args, "--template") or _option_value(args, "--template-id"),
        "template_id": _option_value(args, "--template-id") or _option_value(args, "--template"),
        "label": _option_value(args, "--label"),
        "display_name": _option_value(args, "--display-name"),
        "credential_ref": _option_value(args, "--credential-ref"),
        "environment": _option_value(args, "--environment"),
        "region": _option_value(args, "--region"),
        "family": _option_value(args, "--family"),
        "asset_class": _option_value(args, "--asset-class"),
        "product_type": _option_value(args, "--product-type"),
        "instrument": _option_value(args, "--instrument"),
        "market": _option_value(args, "--market"),
        "venue_symbol": _option_value(args, "--venue-symbol"),
        "side": _option_value(args, "--side"),
        "quantity": _float_option(args, "--quantity"),
        "quantity_mode": _option_value(args, "--quantity-mode"),
        "quote_notional": _float_option(args, "--quote-notional"),
        "order_type": _option_value(args, "--order-type"),
        "limit_price": _float_option(args, "--limit-price"),
        "stop_price": _float_option(args, "--stop-price"),
        "time_in_force": _option_value(args, "--time-in-force"),
        "currency": _option_value(args, "--currency"),
        "broker_id": _option_value(args, "--broker-id") or _option_value(args, "--broker"),
        "broker_connection_id": _option_value(args, "--broker-connection-id"),
        "broker_account_id": _option_value(args, "--broker-account-id"),
        "portfolio_id": _option_value(args, "--portfolio-id"),
        "account_id": _option_value(args, "--account-id"),
        "strategy_id": _option_value(args, "--strategy-id"),
        "client_order_id": _option_value(args, "--client-order-id"),
        "conid": _option_value(args, "--conid"),
        "margin_mode": _option_value(args, "--margin-mode"),
        "position_side": _option_value(args, "--position-side"),
        "leverage": _float_option(args, "--leverage"),
        "artifact_id": _option_value(args, "--artifact-id") or _option_value(args, "--id"),
        "artifact_type": _option_value(args, "--artifact-type") or _option_value(args, "--type"),
        "universe": _option_value(args, "--universe"),
        "workflow_type": _option_value(args, "--workflow-type"),
        "symbol": _option_value(args, "--symbol"),
        "role": _option_value(args, "--role"),
        "title": _option_value(args, "--title"),
        "markdown": _option_value(args, "--markdown"),
        "markdown_path": _option_value(args, "--markdown-file") or _option_value(args, "--file"),
        "source_as_of": _option_value(args, "--source-as-of"),
        "readiness_label": _option_value(args, "--readiness"),
        "context_summary": _option_value(args, "--context-summary"),
        "reader_summary": _option_value(args, "--reader-summary"),
        "handoff_state": _option_value(args, "--handoff-state"),
        "confidence": _option_value(args, "--confidence"),
        "missing_evidence": _list_option(args, "--missing-evidence"),
        "next_recipient": _option_value(args, "--next-recipient"),
        "next_action": _option_value(args, "--next-action"),
        "blocked_actions": _list_option(args, "--blocked-actions"),
        "source_snapshot_ids": _list_option(args, "--source-snapshot-ids"),
        "follow_up_requests": _list_option(args, "--follow-up-requests"),
        "query": _option_value(args, "--query") or _option_value(args, "--q"),
        "limit": _int_option(args, "--limit"),
        "source_category": _option_value(args, "--source-category") or _option_value(args, "--category"),
        "source_locator": _option_value(args, "--source-locator") or _option_value(args, "--url"),
        "as_of": _option_value(args, "--as-of"),
        "observed_at": _option_value(args, "--observed-at"),
        "effective_at": _option_value(args, "--effective-at"),
        "published_at": _option_value(args, "--published-at"),
        "retrieved_at": _option_value(args, "--retrieved-at"),
        "known_at": _option_value(args, "--known-at"),
        "recorded_at": _option_value(args, "--recorded-at"),
        "revision": _option_value(args, "--revision"),
        "vintage": _option_value(args, "--vintage"),
        "timezone": _option_value(args, "--timezone"),
        "schema_hash": _option_value(args, "--schema-hash"),
        "corporate_action_policy": _option_value(args, "--corporate-action-policy"),
        "price_adjustment_policy": _option_value(args, "--price-adjustment-policy"),
        "delisting_policy": _option_value(args, "--delisting-policy"),
        "coverage_note": _option_value(args, "--coverage-note"),
        "live_confirmation": _option_value(args, "--live-confirmation"),
    })
    if "--reduce-only" in args:
        payload["reduce_only"] = True
    payload_json = _option_value(args, "--payload")
    if payload_json:
        parsed_payload = json.loads(payload_json)
        if not isinstance(parsed_payload, dict):
            raise ValueError("--payload must be a JSON object")
        payload["payload"] = parsed_payload
    warnings_json = _option_value(args, "--warnings")
    if warnings_json:
        parsed_warnings = json.loads(warnings_json)
        if not isinstance(parsed_warnings, list):
            raise ValueError("--warnings must be a JSON array")
        payload["warnings"] = parsed_warnings
    for option, field in (("--provider-query", "provider_query"), ("--universe-membership", "universe_membership")):
        raw_value = _option_value(args, option)
        if raw_value:
            parsed_value = json.loads(raw_value)
            if not isinstance(parsed_value, dict):
                raise ValueError(f"{option} must be a JSON object")
            payload[field] = parsed_value
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    option_value_indices = {
        index + 1
        for index, raw in enumerate(args[:-1])
        if raw.startswith("--") and raw not in {"--reduce-only"}
    }
    for index, raw in enumerate(args):
        if index in option_value_indices:
            continue
        if raw.startswith("{"):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("positional JSON MCP payload must be an object")
            payload.update(parsed)
    if receipt_path:
        payload["approval_receipt"] = json.loads((root / receipt_path).read_text(encoding="utf-8"))
    tool_spec = TOOL_REGISTRY.get(tool)
    if tool_spec is None:
        raise ValueError(f"Unknown TradingCodex tool: {tool}")
    if tool_spec.risk_level != "read" and not principal_id:
        raise ValueError(f"--principal is required for {tool_spec.risk_level} MCP tool: {tool}")
    result = call_mcp_tool(
        root,
        tool,
        payload,
        transport_principal=principal_id or default_principal_for_tool(tool_spec),
    )
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


def mcp_external(root: Path, args: list[str]) -> None:
    if not args or args[0] in {"--help", "-h", "help"}:
        print_external_help()
        return
    action = args[0]
    rest = args[1:]
    payload: dict[str, Any] = {
        "principal_id": _option_value(rest, "--principal") or "head-manager",
        "name": _option_value(rest, "--name") or _option_value(rest, "--router-name"),
        "router_name": _option_value(rest, "--router-name"),
        "router_id": _int_option(rest, "--router-id"),
        "label": _option_value(rest, "--label"),
        "transport": _option_value(rest, "--transport"),
        "command": _option_value(rest, "--command"),
        "url": _option_value(rest, "--url"),
        "credential_ref": _option_value(rest, "--credential-ref"),
        "timeout": _float_option(rest, "--timeout"),
        "tool_id": _int_option(rest, "--tool-id"),
        "external_tool_id": _int_option(rest, "--external-tool-id"),
        "external_name": _option_value(rest, "--external-name") or _option_value(rest, "--tool-name"),
        "primitive": _option_value(rest, "--primitive"),
        "category": _option_value(rest, "--category"),
        "risk_level": _option_value(rest, "--risk-level"),
        "sensitivity": _option_value(rest, "--sensitivity"),
        "canonical_capability": _option_value(rest, "--capability"),
        "proxy_mode": _option_value(rest, "--proxy-mode"),
        "review_status": _option_value(rest, "--review-status"),
        "limit": _int_option(rest, "--limit"),
    }
    if "--enabled" in rest:
        payload["enabled"] = True
    if "--disabled" in rest:
        payload["enabled"] = False
    args_value = _option_value(rest, "--args")
    if args_value:
        payload["args"] = _parse_json_or_split(args_value)
    env_value = _option_value(rest, "--env")
    if env_value:
        payload["env"] = json.loads(env_value)
    roles_value = _option_value(rest, "--allowed-roles")
    if roles_value:
        payload["allowed_roles"] = [item.strip() for item in roles_value.split(",") if item.strip()]
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    tool_by_action = {
        "list": "list_external_mcp_connections",
        "register": "register_external_mcp_connection",
        "check": "check_external_mcp_connection",
        "discover": "discover_external_mcp_connection",
        "review": "review_external_mcp_tool",
        "review-tool": "review_external_mcp_tool",
    }
    tool = tool_by_action.get(action)
    if not tool:
        raise ValueError(f"unknown external MCP action: {action}")
    transport_principal = str(payload.pop("principal_id"))
    result = call_mcp_tool(root, tool, payload, transport_principal=transport_principal)
    print_json(result)
    if result.get("status") in {"check_failed", "disabled", "rejected"}:
        sys.exit(1)


def _parse_json_or_split(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        if os.name == "nt":
            raise ValueError("on Windows, external MCP args must be a JSON array")
        return [item for item in value.split() if item]


def _int_option(args: list[str], name: str) -> int | None:
    value = _option_value(args, name)
    return int(value) if value not in (None, "") else None


def _float_option(args: list[str], name: str) -> float | None:
    value = _option_value(args, name)
    return float(value) if value not in (None, "") else None


def install_global_mcp(args: list[str]) -> None:
    if "--safe" not in args:
        raise ValueError("Usage: tcx mcp install-global --safe [--config <path>] [--print]")
    config_path = Path(_option_value(args, "--config") or Path.home() / ".codex" / "config.toml").expanduser().resolve()
    block = global_home_mcp_config_block()
    if "--print" in args:
        print(block)
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated = replace_managed_block(existing, block, "TradingCodex home MCP")
    atomic_write_text(config_path, updated)
    print_json({
        "status": "installed",
        "server_name": "tradingcodex-home",
        "config_path": str(config_path),
        "safe_tools": sorted(SAFE_HOME_TOOL_NAMES),
    })


def global_home_mcp_config_block() -> str:
    tools = ",\n  ".join(json.dumps(tool) for tool in sorted(SAFE_HOME_TOOL_NAMES))
    package_spec = json.dumps(os.environ.get("TRADINGCODEX_MCP_PACKAGE_SPEC", "tradingcodex"), ensure_ascii=False)
    return f"""# BEGIN TradingCodex home MCP
[mcp_servers.tradingcodex-home]
command = "uvx"
args = ["--refresh", "--from", {package_spec}, "python", "-m", "tradingcodex_cli", "mcp", "stdio"]
enabled = true
env = {{ TRADINGCODEX_MCP_SAFE_TOOLS = "1", TRADINGCODEX_MCP_SCOPE = "global-home" }}
enabled_tools = [
  {tools}
]
default_tools_approval_mode = "prompt"
startup_timeout_sec = 20
# END TradingCodex home MCP
"""


def print_mcp_help() -> None:
    launcher = workspace_launcher_command()
    print(f"""TradingCodex MCP

Usage:
  {launcher} mcp call <tool> [--principal <role>] [tool args]
  {launcher} mcp external <list|register|check|discover|review-tool> [options]
  {launcher} mcp ledger [--tool <name>] [--principal <role>] [--status ok]
  {launcher} mcp install-global --safe
  {launcher} mcp stdio

Examples:
  {launcher} mcp call create_research_artifact --principal fundamental-analyst --artifact-id note-1 --title "Note" --markdown "# Note" --symbol MSFT
  {launcher} mcp call list_broker_adapter_providers --principal head-manager
  {launcher} mcp call register_broker_connector --principal head-manager --provider <provider-id> --broker-id <broker-id> --credential-ref env:<BROKER_REF>
  {launcher} mcp call preview_order_translation --principal head-manager --broker-id <broker-id> --symbol <symbol> --side buy --order-type market --quote-notional 25
  {launcher} mcp call create_order_ticket --principal portfolio-manager --natural-language "buy 5 AAPL limit 180"
  {launcher} mcp call run_order_checks --principal portfolio-manager --ticket-id ticket-id
  {launcher} mcp call submit_approved_order --principal execution-operator --ticket-id approved-ticket-id
  {launcher} mcp external register --name broker-mcp --transport stdio --command uvx --args '["broker-mcp"]' --env '{{"API_KEY":"env:BROKER_API_KEY"}}' --enabled
  {launcher} mcp external discover --name broker-mcp
  {launcher} mcp external review-tool --tool-id 1 --proxy-mode summary_only --allowed-roles head-manager --enabled
  {launcher} mcp ledger --tool create_research_artifact --status ok
""")


def print_external_help() -> None:
    launcher = workspace_launcher_command()
    print(f"""TradingCodex External MCP Gate

Usage:
  {launcher} mcp external list [--name router]
  {launcher} mcp external register --name router --transport stdio --command uvx --args '["broker-mcp"]' [--env '{{"TARGET":"env:SOURCE"}}'] [--credential-ref env:NAME] [--enabled]
  {launcher} mcp external register --name router --transport http --url http://127.0.0.1:9000/mcp [--enabled]
  {launcher} mcp external check --name router
  {launcher} mcp external discover --name router
  {launcher} mcp external review-tool --tool-id id --proxy-mode read_only --allowed-roles head-manager --enabled
""")
