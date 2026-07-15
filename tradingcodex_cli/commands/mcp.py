from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path
from typing import Any

from tradingcodex_service.application.customization import import_codex_mcp_server, replace_managed_block
from tradingcodex_service.application.common import atomic_write_text, workspace_launcher_command
from tradingcodex_service.application.operator_authority import (
    EXTERNAL_MCP_PERMISSION_APPROVE,
    EXTERNAL_MCP_PERMISSION_DENY,
    EXTERNAL_MCP_IMPORT_CODEX,
    _issue_operator_authority,
    external_mcp_codex_import_resource,
    external_mcp_permission_resource,
    external_mcp_operator_resource,
)
from tradingcodex_service.application.runtime import ensure_runtime_database, tradingcodex_db_path
from tradingcodex_service.mcp_runtime import SAFE_HOME_TOOL_NAMES, TOOL_REGISTRY, call_mcp_tool, default_principal_for_tool
from tradingcodex_cli.commands.utils import _list_option, _option_value, _validate_options, print_json
from tradingcodex_cli.generator import resolve_package_runner
from tradingcodex_cli.package_source import (
    EXECUTABLE_SOURCE_ENV,
    LOCAL_EXECUTABLE_SOURCE_KIND,
    PACKAGE_SOURCE_KIND_ENV,
    configured_executable_source,
)

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
    if argv and argv[0] == "ledger":
        mcp_ledger(root, argv[1:])
        return
    if argv and argv[0] == "external":
        mcp_external(root, argv[1:])
        return
    if argv and argv[0] == "permission":
        mcp_permission(root, argv[1:])
        return
    if argv and argv[0] == "install-global":
        install_global_mcp(argv[1:])
        return
    if not argv or argv[0] != "call":
        raise ValueError(
            "Usage: tcx mcp call <tool> [tool args] | tcx mcp external <action> [options] | "
            "tcx mcp permission <list|approve|deny> [options] | tcx mcp ledger [--tool name] | tcx mcp stdio"
        )
    tool = argv[1] if len(argv) > 1 else ""
    if tool == "promote_lesson":
        raise PermissionError(
            "lesson promotion is unavailable from generic CLI calls; use the role-scoped judgment-reviewer stdio MCP"
        )
    args = argv[2:]
    principal_id = _option_value(args, "--principal")
    payload: dict[str, Any] = {}
    payload.update({
        "ticket_id": _option_value(args, "--ticket-id"),
        "approval_receipt_id": _option_value(args, "--approval-receipt-id"),
        "natural_language": _option_value(args, "--natural-language"),
        "provider": _option_value(args, "--provider"),
        "provider_id": _option_value(args, "--provider-id"),
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
        "broker_id": _option_value(args, "--broker-id"),
        "broker_order_id": _option_value(args, "--broker-order-id"),
        "broker_account_id": _option_value(args, "--broker-account-id"),
        "portfolio_id": _option_value(args, "--portfolio-id"),
        "account_id": _option_value(args, "--account-id"),
        "strategy_id": _option_value(args, "--strategy-id"),
        "client_order_id": _option_value(args, "--client-order-id"),
        "conid": _option_value(args, "--conid"),
        "margin_mode": _option_value(args, "--margin-mode"),
        "position_side": _option_value(args, "--position-side"),
        "leverage": _float_option(args, "--leverage"),
        "artifact_id": _option_value(args, "--artifact-id"),
        "artifact_type": _option_value(args, "--artifact-type"),
        "universe": _option_value(args, "--universe"),
        "workflow_type": _option_value(args, "--workflow-type"),
        "workflow_run_id": _option_value(args, "--workflow-run-id"),
        "symbol": _option_value(args, "--symbol"),
        "role": _option_value(args, "--role"),
        "title": _option_value(args, "--title"),
        "markdown": _option_value(args, "--markdown"),
        "markdown_path": _option_value(args, "--markdown-file"),
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
        "query": _option_value(args, "--query"),
        "limit": _int_option(args, "--limit"),
        "source_category": _option_value(args, "--source-category"),
        "source_locator": _option_value(args, "--source-locator"),
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
    if action == "import-codex":
        parser = argparse.ArgumentParser(prog="tcx mcp external import-codex")
        parser.add_argument("--source", choices=["workspace", "global", "any"], default="workspace")
        parser.add_argument("--name", required=True)
        parsed = parser.parse_args(rest)
        subject = f"{parsed.source}:{parsed.name}"
        _require_operator_confirmation(action, subject)
        operator_authority = _issue_operator_authority(
            root,
            action=EXTERNAL_MCP_IMPORT_CODEX,
            resource=external_mcp_codex_import_resource(parsed.name, parsed.source),
        )
        print_json(
            import_codex_mcp_server(
                root,
                name=parsed.name,
                source=parsed.source,
                operator_authority=operator_authority,
            )
        )
        return
    _validate_options(
        rest,
        value_options={
            "--allowed-roles", "--args", "--capability", "--category", "--command",
            "--credential-ref", "--env", "--external-name", "--label", "--limit", "--name",
            "--primitive", "--proxy-mode", "--review-status", "--risk-level",
            "--sensitivity", "--timeout", "--tool-id", "--transport", "--url",
        },
        flag_options={"--disabled", "--enabled"},
    )
    payload: dict[str, Any] = {
        "name": _option_value(rest, "--name"),
        "label": _option_value(rest, "--label"),
        "transport": _option_value(rest, "--transport"),
        "command": _option_value(rest, "--command"),
        "url": _option_value(rest, "--url"),
        "credential_ref": _option_value(rest, "--credential-ref"),
        "timeout": _float_option(rest, "--timeout"),
        "tool_id": _int_option(rest, "--tool-id"),
        "external_name": _option_value(rest, "--external-name"),
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
        "review-tool": "review_external_mcp_tool",
    }
    tool = tool_by_action.get(action)
    if not tool:
        raise ValueError(f"unknown external MCP action: {action}")
    operator_authority = None
    if action != "list":
        subject = str(
            payload.get("name")
            or payload.get("external_name")
            or (f"tool-{payload['tool_id']}" if payload.get("tool_id") is not None else "external-mcp")
        )
        _require_operator_confirmation(action, subject)
        operator_authority = _issue_operator_authority(
            root,
            action=tool,
            resource=external_mcp_operator_resource(tool, payload),
        )
    result = call_mcp_tool(
        root,
        tool,
        payload,
        transport_principal="head-manager",
        operator_authority=operator_authority,
    )
    print_json(result)
    if result.get("status") in {"check_failed", "disabled", "rejected"}:
        sys.exit(1)


def mcp_permission(root: Path, args: list[str]) -> None:
    """Review external MCP consent requests from the explicit operator CLI."""

    if not args or args[0] in {"--help", "-h", "help"}:
        print_permission_help()
        return
    action = args[0]
    rest = args[1:]
    if action == "list":
        parser = argparse.ArgumentParser(prog="tcx mcp permission list")
        parser.add_argument("--status", default="pending")
        parser.add_argument("--limit", type=int, default=50)
        parsed = parser.parse_args(rest)
        ensure_runtime_database(root)
        from apps.mcp.services import list_external_mcp_permission_requests

        print_json(
            list_external_mcp_permission_requests(
                root,
                {"status": parsed.status, "limit": parsed.limit},
            )
        )
        return
    if action not in {"approve", "deny"}:
        raise ValueError("Usage: tcx mcp permission list|approve|deny")
    parser = argparse.ArgumentParser(prog=f"tcx mcp permission {action}")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--reason", default="")
    parsed = parser.parse_args(rest)
    payload = {
        "request_id": parsed.request_id,
        "reason": parsed.reason,
    }
    _require_operator_confirmation(action, parsed.request_id)
    operator_action = (
        EXTERNAL_MCP_PERMISSION_APPROVE
        if action == "approve"
        else EXTERNAL_MCP_PERMISSION_DENY
    )
    operator_authority = _issue_operator_authority(
        root,
        action=operator_action,
        resource=external_mcp_permission_resource(
            operator_action,
            parsed.request_id,
            parsed.reason,
        ),
    )
    ensure_runtime_database(root)
    from apps.mcp.services import (
        approve_external_mcp_permission_request,
        deny_external_mcp_permission_request,
    )

    if action == "approve":
        print_json(
            approve_external_mcp_permission_request(
                root,
                payload,
                operator_authority=operator_authority,
            )
        )
        return
    print_json(
        deny_external_mcp_permission_request(
            root,
            payload,
            operator_authority=operator_authority,
        )
    )


def _require_operator_confirmation(action: str, subject: str) -> None:
    """Require an explicit human terminal confirmation for operator-only state."""

    if not sys.stdin.isatty():
        raise PermissionError(
            "this operator action requires an interactive user terminal; it cannot run from an agent or automation"
        )
    expected = f"{action}:{subject}"
    entered = input(
        f"Operator-only action `{action}` for `{subject}`. Type `{expected}` to continue: "
    ).strip()
    if entered != expected:
        raise PermissionError("operator confirmation did not match; no change was made")


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
    if (
        not str(os.environ.get(EXECUTABLE_SOURCE_ENV) or "")
        and os.environ.get(PACKAGE_SOURCE_KIND_ENV) == LOCAL_EXECUTABLE_SOURCE_KIND
    ):
        package_runner = sys.executable
        rendered_args = '"-m", "tradingcodex_cli", "mcp", "stdio"'
    else:
        raw_package_spec = configured_executable_source(None)
        package_spec = json.dumps(raw_package_spec, ensure_ascii=False)
        package_runner, package_prefix = resolve_package_runner(raw_package_spec)
        rendered_prefix = ", ".join(json.dumps(item) for item in package_prefix)
        rendered_args = (
            f'{rendered_prefix}, {package_spec}, "python", "-m", '
            '"tradingcodex_cli", "mcp", "stdio"'
        )
    return f"""# BEGIN TradingCodex home MCP
[mcp_servers.tradingcodex-home]
command = {json.dumps(package_runner)}
args = [{rendered_args}]
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
  {launcher} mcp external <list|import-codex|register|check|discover|review-tool> [options]
  {launcher} mcp permission <list|approve|deny> [options]
  {launcher} mcp ledger [--tool <name>] [--principal <role>] [--status ok]
  {launcher} mcp install-global --safe
  {launcher} mcp stdio

Examples:
  {launcher} mcp call create_research_artifact --principal fundamental-analyst --artifact-id note-1 --title "Note" --markdown "# Note" --symbol MSFT
  {launcher} mcp call list_broker_adapter_providers --principal head-manager
  {launcher} mcp call preview_order_translation --principal head-manager --broker-id <broker-id> --symbol <symbol> --side buy --order-type market --quote-notional 25
  {launcher} mcp call create_order_ticket --principal portfolio-manager --natural-language "buy 5 AAPL limit 180"
  {launcher} mcp call run_order_checks --principal portfolio-manager --ticket-id ticket-id
  {launcher} mcp external import-codex --source workspace --name broker-mcp
  {launcher} mcp external register --name broker-mcp --transport stdio --command uvx --args '["broker-mcp"]' --env '{{"API_KEY":"env:BROKER_API_KEY"}}' --enabled
  {launcher} mcp external discover --name broker-mcp
  {launcher} mcp external review-tool --tool-id 1 --proxy-mode summary_only --allowed-roles head-manager --enabled
  {launcher} mcp permission list --status pending
  {launcher} mcp permission approve --request-id 1 --reason "Reviewed"
  {launcher} mcp ledger --tool create_research_artifact --status ok

Connector registration is Build-protected and intentionally unavailable from
generic `mcp call`. Start a root turn whose first meaningful line invokes
`$tcx-build` instead.
""")


def print_external_help() -> None:
    launcher = workspace_launcher_command()
    print(f"""TradingCodex External MCP Gate

Usage:
  {launcher} mcp external list [--name router]
  {launcher} mcp external import-codex --source workspace|global|any --name server
  {launcher} mcp external register --name router --transport stdio --command uvx --args '["broker-mcp"]' [--env '{{"TARGET":"env:SOURCE"}}'] [--credential-ref env:NAME] [--enabled]
  {launcher} mcp external register --name router --transport http --url http://127.0.0.1:9000/mcp [--enabled]
  {launcher} mcp external check --name router
  {launcher} mcp external discover --name router
  {launcher} mcp external review-tool --tool-id id --proxy-mode read_only --allowed-roles head-manager --enabled
  {launcher} mcp external review-tool --name router --external-name tool --proxy-mode read_only --allowed-roles head-manager --enabled

`import-codex`, `register`, `check`, `discover`, and `review-tool` are
operator-only. They require an interactive user terminal and an exact typed
confirmation; agents and Scheduled Tasks cannot perform them.
""")


def print_permission_help() -> None:
    launcher = workspace_launcher_command()
    print(f"""TradingCodex External MCP Permission

Usage:
  {launcher} mcp permission list [--status pending|approved|denied|expired|all] [--limit 50]
  {launcher} mcp permission approve --request-id <id> [--reason <text>]
  {launcher} mcp permission deny --request-id <id> [--reason <text>]

`approve` and `deny` require an interactive user terminal and an exact typed
confirmation. They cannot run from an agent or Scheduled Task.
""")
