from __future__ import annotations

import os
from pathlib import Path

from django.test import Client

from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.brokers import (
    create_external_mcp_broker_connection,
    record_broker_mapping_review,
    sync_broker_account,
)
from tradingcodex_service.application.orders import order_payload_from_ticket, validate_approval_receipt
from tradingcodex_service.application.runtime import ensure_runtime_database
from tradingcodex_service.mcp_runtime import call_mcp_tool, handle_mcp_rpc


ROOT = Path(__file__).resolve().parents[1]


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    bootstrap_workspace(workspace, force=True)
    return workspace


def test_paper_broker_sync_creates_ledger_snapshot_and_reconciliation(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    result = sync_broker_account(workspace, {"broker_id": "paper-trading", "principal_id": "portfolio-manager"})

    assert result["status"] == "ok"
    assert result["accounts"][0]["broker_account_id"] == "local-paper"

    from apps.integrations.models import BrokerAccount, BrokerConnection
    from apps.portfolio.models import BrokerSyncRun, PortfolioLedgerEvent, PortfolioSnapshot, ReconciliationRun

    connection = BrokerConnection.objects.get(broker_id="paper-trading")
    assert connection.transport == "paper"
    assert connection.credential_ref == ""
    assert BrokerAccount.objects.filter(broker_connection=connection, broker_account_id="local-paper").exists()
    assert BrokerSyncRun.objects.filter(broker_connection=connection, status="ok").exists()
    assert PortfolioLedgerEvent.objects.filter(broker_connection=connection, event_type="cash").exists()
    assert PortfolioSnapshot.objects.filter(source="paper-trading", account_id="local-paper").exists()
    assert ReconciliationRun.objects.filter(broker_connection=connection, status="clean").exists()


def test_order_ticket_checks_approval_scope_submit_fill_and_duplicate_block(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    created = call_mcp_tool(
        workspace,
        "create_order_ticket",
        {
            "principal_id": "portfolio-manager",
            "ticket_id": "prd-ticket-1",
            "natural_language": "buy 1 MSFT limit 1000",
        },
    )
    assert created["ticket"]["current_state"] == "DRAFT"

    checks = call_mcp_tool(workspace, "run_order_checks", {"principal_id": "portfolio-manager", "ticket_id": "prd-ticket-1"})
    assert checks["approval_ready"] is True
    assert {check["check_type"] for check in checks["checks"]} >= {"schema", "policy", "cash", "broker_validate", "risk"}

    approval = call_mcp_tool(workspace, "request_order_approval", {"principal_id": "risk-manager", "ticket_id": "prd-ticket-1"})
    assert approval["status"] == "approved"
    receipt = approval["approval_receipt"]
    assert receipt["exact_order_hash"]
    assert receipt["order_ticket_id"] == "prd-ticket-1"
    assert receipt["broker_connection_id"] == "paper-trading"

    from apps.orders.models import Fill, OrderEvent, OrderTicket

    ticket = OrderTicket.objects.get(ticket_id="prd-ticket-1")
    mutated_order = {**order_payload_from_ticket(ticket), "quantity": 2}
    invalid = validate_approval_receipt(workspace, {"order": mutated_order, "approval_receipt": receipt})
    assert invalid["valid"] is False
    assert "exact_order_hash" in "\n".join(invalid["reasons"])

    submitted = call_mcp_tool(workspace, "submit_approved_order", {"principal_id": "execution-operator", "ticket_id": "prd-ticket-1"})
    assert submitted["status"] == "accepted"

    ticket.refresh_from_db()
    assert ticket.current_state == "FILLED"
    assert Fill.objects.filter(ticket=ticket).exists()
    assert OrderEvent.objects.filter(ticket=ticket, event_type__in={"acked", "fill"}).count() >= 2

    duplicate = call_mcp_tool(workspace, "submit_approved_order", {"principal_id": "execution-operator", "ticket_id": "prd-ticket-1"})
    assert duplicate["status"] == "rejected"
    assert "already has an execution result" in "\n".join(duplicate["reasons"])


def test_safe_home_mcp_exposes_only_broker_order_read_status_tools(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    previous = os.environ.get("TRADINGCODEX_MCP_SAFE_TOOLS")
    os.environ["TRADINGCODEX_MCP_SAFE_TOOLS"] = "1"
    try:
        tools = handle_mcp_rpc(workspace, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tool_names = {tool["name"] for tool in tools["result"]["tools"]}
    finally:
        if previous is None:
            os.environ.pop("TRADINGCODEX_MCP_SAFE_TOOLS", None)
        else:
            os.environ["TRADINGCODEX_MCP_SAFE_TOOLS"] = previous

    assert {"list_broker_connections", "get_broker_connection_status", "list_order_tickets", "get_order_ticket", "list_reconciliation_runs"}.issubset(tool_names)
    assert "sync_broker_account" not in tool_names
    assert "create_order_ticket" not in tool_names
    assert "request_order_approval" not in tool_names
    assert "submit_approved_order" not in tool_names


def test_external_mcp_broker_discovery_stays_read_only_until_review() -> None:
    ensure_runtime_database(ROOT)
    from apps.integrations.models import BrokerConnection
    from apps.mcp.models import McpExternalTool, McpRouter
    from apps.mcp.services import set_external_tool_policy

    BrokerConnection.objects.filter(broker_id="prd-mcp-broker").delete()
    McpRouter.objects.filter(name="prd-mcp-router").delete()

    imported = create_external_mcp_broker_connection(
        ROOT,
        broker_id="prd-mcp-broker",
        display_name="PRD MCP Broker",
        router_name="prd-mcp-router",
        discovery_payload={
            "tools": [
                {"name": "get_positions", "description": "Read account positions", "inputSchema": {"type": "object"}},
                {"name": "get_market_quote", "description": "Read market quote", "inputSchema": {"type": "object"}},
                {"name": "place_order", "description": "Submit broker order", "inputSchema": {"type": "object"}},
            ]
        },
        actor="test",
    )
    assert imported["imported"]["imported"] == 3
    connection = BrokerConnection.objects.get(broker_id="prd-mcp-broker")
    assert connection.status == "read_only"
    assert connection.enabled_trade_scopes == []
    assert connection.metadata["execution_enabled"] is False

    router = McpRouter.objects.get(name="prd-mcp-router")
    positions = McpExternalTool.objects.get(router=router, external_name="get_positions")
    order = McpExternalTool.objects.get(router=router, external_name="place_order")
    set_external_tool_policy(positions, enabled=True, review_status="reviewed", actor="test")
    reviewed = record_broker_mapping_review(ROOT, {"broker_id": "prd-mcp-broker", "principal_id": "risk-manager"})

    assert "account.positions.read" in connection.__class__.objects.get(pk=connection.pk).enabled_read_scopes
    assert reviewed["blocked_tools"]
    assert order.category == "execution"
    assert order.proxy_mode == "service_adapter"
    assert order.enabled is False


def test_broker_center_and_order_ticket_web_surfaces_render() -> None:
    ensure_runtime_database(ROOT)
    client = Client(REMOTE_ADDR="127.0.0.1")

    brokers = client.get("/brokers/")
    assert brokers.status_code == 200
    broker_body = brokers.content.decode()
    assert "Broker Center" in broker_body
    assert "Add paper broker" in broker_body
    assert "Import External MCP discovery" in broker_body
    assert "Live execution" in broker_body

    orders = client.get("/orders/")
    assert orders.status_code == 200
    order_body = orders.content.decode()
    assert "Create draft" in order_body
    assert "Run checks" in order_body or "No order tickets" in order_body
    assert "Submit approved order" in order_body
    assert "disabled" in order_body
