from __future__ import annotations

import json
import tomllib
import uuid
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.orders import (
    create_order_ticket,
    request_order_approval,
    run_order_checks,
    submit_approved_order,
)
from tradingcodex_service.application.runtime import ensure_runtime_database
from tradingcodex_service.mcp_runtime import call_mcp_tool, handle_mcp_rpc


def approved_ticket(tmp_path: Path) -> tuple[Path, str, dict]:
    workspace = tmp_path / f"workspace-{uuid.uuid4().hex[:8]}"
    bootstrap_workspace(workspace, force=True)
    ensure_runtime_database(workspace)
    ticket_id = f"security-{uuid.uuid4().hex}"
    create_order_ticket(
        workspace,
        {
            "principal_id": "portfolio-manager",
            "ticket_id": ticket_id,
            "symbol": "MSFT",
            "side": "buy",
            "quantity": 1,
            "limit_price": 100,
        },
    )
    checks = run_order_checks(workspace, {"principal_id": "portfolio-manager", "ticket_id": ticket_id})
    assert checks["approval_ready"] is True
    approval = request_order_approval(workspace, {"principal_id": "risk-manager", "ticket_id": ticket_id})
    assert approval["status"] == "approved"
    return workspace, ticket_id, approval["approval_receipt"]


def test_submission_rejects_caller_supplied_receipt_before_adapter(monkeypatch, tmp_path: Path) -> None:
    workspace, ticket_id, receipt = approved_ticket(tmp_path)
    adapter_calls: list[dict] = []
    monkeypatch.setattr(
        "tradingcodex_service.application.orders.submit_with_adapter",
        lambda root, order: adapter_calls.append(order) or {},
    )

    result = submit_approved_order(
        workspace,
        {
            "principal_id": "execution-operator",
            "ticket_id": ticket_id,
            "approval_receipt": {**receipt, "exact_order_hash": "forged"},
        },
    )

    assert result["status"] == "rejected"
    assert "DB-canonical" in "\n".join(result["reasons"])
    assert adapter_calls == []


def test_mcp_transport_principal_cannot_be_spoofed_or_omitted(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "identity-workspace"
    bootstrap_workspace(workspace, force=True)
    monkeypatch.delenv("TRADINGCODEX_MCP_PRINCIPAL", raising=False)
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "submit_approved_order",
            "arguments": {"principal_id": "execution-operator", "ticket_id": "missing"},
        },
    }

    anonymous = handle_mcp_rpc(workspace, message)
    assert anonymous and "transport principal is required" in anonymous["error"]["message"]

    spoofed = handle_mcp_rpc(workspace, message, transport_principal="portfolio-manager")
    assert spoofed and "does not match" in spoofed["error"]["message"]


def test_mcp_registry_failure_exposes_only_static_safe_reads(monkeypatch, tmp_path: Path) -> None:
    import tradingcodex_service.mcp_runtime as runtime

    workspace = tmp_path / "registry-failure-workspace"
    bootstrap_workspace(workspace, force=True)
    monkeypatch.setattr(
        "tradingcodex_service.application.runtime.ensure_runtime_database",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("registry database unavailable")),
    )
    runtime._REGISTRY_SYNCED = False
    runtime._REGISTRY_SYNCED_DB = ""
    runtime._REGISTRY_ERROR = ""
    try:
        listed = handle_mcp_rpc(workspace, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert listed is not None
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names
        assert names <= runtime.REGISTRY_FAILURE_SAFE_READ_TOOLS
        denied = handle_mcp_rpc(
            workspace,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "create_order_ticket", "arguments": {"symbol": "MSFT"}},
            },
            transport_principal="portfolio-manager",
        )
        assert denied is not None
        assert "registry unavailable; fail-closed" in denied["error"]["message"]
    finally:
        runtime._REGISTRY_SYNCED = False
        runtime._REGISTRY_SYNCED_DB = ""
        runtime._REGISTRY_ERROR = ""


def test_anonymous_loopback_api_is_read_only(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "api-workspace"
    bootstrap_workspace(workspace, force=True)
    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(workspace))
    client = Client(REMOTE_ADDR="127.0.0.1")

    assert client.get("/api/harness/status").status_code == 200
    response = client.post(
        "/api/orders/tickets",
        data=json.dumps({"principal_id": "portfolio-manager", "symbol": "MSFT", "side": "buy", "quantity": 1, "limit_price": 100}),
        content_type="application/json",
    )
    assert response.status_code in {401, 403}


def test_mandatory_audit_failure_rolls_back_intent_before_provider(monkeypatch, tmp_path: Path) -> None:
    workspace, ticket_id, receipt = approved_ticket(tmp_path)
    adapter_calls: list[dict] = []
    monkeypatch.setattr(
        "tradingcodex_service.application.orders.submit_with_adapter",
        lambda root, order: adapter_calls.append(order) or {},
    )
    monkeypatch.setattr(
        "apps.orders.services.write_audit_event_required",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        submit_approved_order(workspace, {"principal_id": "execution-operator", "ticket_id": ticket_id})

    from apps.orders.models import ApprovalReceipt, ExecutionResult, OrderTicket

    assert adapter_calls == []
    assert not ExecutionResult.objects.filter(order_ticket_id=ticket_id).exists()
    assert OrderTicket.objects.get(ticket_id=ticket_id).current_state == "APPROVED"
    assert ApprovalReceipt.objects.get(receipt_id=receipt["id"]).consumed_at is None


def test_provider_exception_is_durable_needs_review(monkeypatch, tmp_path: Path) -> None:
    workspace, ticket_id, _ = approved_ticket(tmp_path)
    monkeypatch.setattr(
        "tradingcodex_service.application.orders.submit_with_adapter",
        lambda root, order: (_ for _ in ()).throw(RuntimeError("connection reset after send")),
    )

    result = submit_approved_order(workspace, {"principal_id": "execution-operator", "ticket_id": ticket_id})

    from apps.orders.models import BrokerOrder, ExecutionResult, OrderTicket

    assert result["status"] == "needs_review"
    execution = ExecutionResult.objects.get(order_ticket_id=ticket_id)
    assert execution.status == "needs_review"
    assert execution.provider_invoked_at is not None
    assert execution.payload["result"]["client_order_id"].startswith("tcx-")
    assert BrokerOrder.objects.filter(ticket__ticket_id=ticket_id, broker_status="unknown").exists()
    assert OrderTicket.objects.get(ticket_id=ticket_id).current_state == "NEEDS_REVIEW"


def test_draft_discard_is_distinct_from_submitted_cancel(tmp_path: Path) -> None:
    workspace = tmp_path / "discard-workspace"
    bootstrap_workspace(workspace, force=True)
    ticket_id = f"draft-{uuid.uuid4().hex}"
    create_order_ticket(
        workspace,
        {
            "principal_id": "portfolio-manager",
            "ticket_id": ticket_id,
            "symbol": "MSFT",
            "side": "buy",
            "quantity": 1,
            "limit_price": 100,
        },
    )

    cancel = call_mcp_tool(
        workspace,
        "cancel_submitted_order",
        {"principal_id": "execution-operator", "ticket_id": ticket_id},
    )
    assert cancel["status"] == "not_cancelable"
    assert "only submitted broker orders" in "\n".join(cancel["reasons"])

    discarded = call_mcp_tool(
        workspace,
        "discard_draft_order",
        {"principal_id": "portfolio-manager", "ticket_id": ticket_id},
    )
    assert discarded["status"] == "discarded"
    assert discarded["ticket"]["current_state"] == "CANCELED"


def test_revoked_approval_cannot_cancel_recorded_broker_order(tmp_path: Path) -> None:
    workspace, ticket_id, receipt = approved_ticket(tmp_path)
    from apps.orders.models import ApprovalReceipt, BrokerOrder, OrderTicket

    ticket = OrderTicket.objects.get(ticket_id=ticket_id)
    ticket.current_state = "ACKED"
    ticket.status = "ACKED"
    ticket.save(update_fields=["current_state", "status"])
    broker_order = BrokerOrder.objects.create(
        ticket=ticket,
        broker_order_id=f"broker-{ticket_id}",
        broker_status="submitted",
    )
    ApprovalReceipt.objects.filter(receipt_id=receipt["id"]).update(valid=False)

    result = call_mcp_tool(
        workspace,
        "cancel_submitted_order",
        {
            "principal_id": "execution-operator",
            "ticket_id": ticket_id,
            "broker_order_id": broker_order.broker_order_id,
        },
    )

    broker_order.refresh_from_db()
    ticket.refresh_from_db()
    assert result["status"] == "not_cancelable"
    assert "approval_receipt.valid must be true" in "\n".join(result["reasons"])
    assert broker_order.broker_status == "submitted"
    assert ticket.current_state == "ACKED"


def test_audit_events_are_append_only(tmp_path: Path) -> None:
    workspace = tmp_path / "audit-workspace"
    bootstrap_workspace(workspace, force=True)
    ensure_runtime_database(workspace)
    from apps.audit.models import AuditEvent

    event = AuditEvent.objects.create(action=f"security.test.{uuid.uuid4().hex}")
    event.action = "security.test.changed"
    with pytest.raises(ValidationError, match="append-only"):
        event.save()
    with pytest.raises(ValidationError, match="append-only"):
        event.delete()


def test_generated_roles_expose_only_their_cancel_operation(tmp_path: Path) -> None:
    workspace = tmp_path / "role-tools-workspace"
    bootstrap_workspace(workspace, force=True)
    portfolio = tomllib.loads((workspace / ".codex" / "agents" / "portfolio-manager.toml").read_text(encoding="utf-8"))
    execution = tomllib.loads((workspace / ".codex" / "agents" / "execution-operator.toml").read_text(encoding="utf-8"))

    portfolio_tools = set(portfolio["mcp_servers"]["tradingcodex"]["enabled_tools"])
    execution_tools = set(execution["mcp_servers"]["tradingcodex"]["enabled_tools"])
    assert "discard_draft_order" in portfolio_tools
    assert "cancel_submitted_order" not in portfolio_tools
    assert "cancel_submitted_order" in execution_tools
    assert portfolio["mcp_servers"]["tradingcodex"]["env"]["TRADINGCODEX_MCP_PRINCIPAL"] == "portfolio-manager"
    assert execution["mcp_servers"]["tradingcodex"]["env"]["TRADINGCODEX_MCP_PRINCIPAL"] == "execution-operator"
