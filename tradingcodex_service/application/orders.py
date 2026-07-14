from __future__ import annotations

import json
import re
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone as django_timezone

from tradingcodex_service.application.audit import (
    write_audit_event,
    write_audit_event_if_available,
    write_audit_event_required,
)
from tradingcodex_service.application.common import (
    _parse_datetime,
    safe_workspace_path,
    _validate_positive,
    now_iso,
    read_json,
    safe_provider_error,
    sanitize_id,
    stable_hash,
)
from tradingcodex_service.application.policy import evaluate_policy
from tradingcodex_service.application.portfolio import (
    portfolio_keys,
    quantize_money,
    submit_paper_order,
)
from tradingcodex_service.application.runtime import (
    DEFAULT_BASE_CURRENCY,
    base_currency_for_workspace,
    ensure_runtime_database,
    normalize_currency_code,
    workspace_context_payload,
)

ORDER_TICKET_CREATOR_ROLE = "portfolio-manager"
ORDER_TICKET_STATES = {
    "DRAFT",
    "PRECHECKED",
    "READY_FOR_APPROVAL",
    "APPROVED",
    "RESERVED",
    "SUBMITTED",
    "ACKED",
    "PARTIALLY_FILLED",
    "FILLED",
    "REJECTED",
    "CANCELED",
    "EXPIRED",
    "FAILED",
    "NEEDS_REVIEW",
}
ORDER_TICKET_TRANSITIONS = {
    "DRAFT": {"PRECHECKED", "READY_FOR_APPROVAL", "NEEDS_REVIEW", "REJECTED", "CANCELED"},
    "PRECHECKED": {"READY_FOR_APPROVAL", "NEEDS_REVIEW", "APPROVED", "REJECTED", "CANCELED"},
    "READY_FOR_APPROVAL": {"APPROVED", "NEEDS_REVIEW", "REJECTED", "CANCELED"},
    "APPROVED": {"RESERVED", "EXPIRED", "CANCELED", "NEEDS_REVIEW"},
    "RESERVED": {"SUBMITTED", "FAILED", "NEEDS_REVIEW"},
    "SUBMITTED": {"ACKED", "FILLED", "PARTIALLY_FILLED", "CANCELED", "REJECTED", "EXPIRED", "FAILED", "NEEDS_REVIEW"},
    "ACKED": {"PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "EXPIRED", "FAILED", "NEEDS_REVIEW"},
    "PARTIALLY_FILLED": {"FILLED", "CANCELED", "EXPIRED", "FAILED", "NEEDS_REVIEW"},
    "NEEDS_REVIEW": {"DRAFT", "PRECHECKED", "REJECTED", "CANCELED"},
}
ORDER_RESOLUTION_ERROR_FIELD = "_order_resolution_error"
ADAPTER_ORDER_STATE_TARGETS = {
    "submitted": "ACKED",
    "acked": "ACKED",
    "validated": "ACKED",
    "partially_filled": "PARTIALLY_FILLED",
    "filled": "FILLED",
    "canceled": "CANCELED",
    "rejected": "REJECTED",
    "expired": "EXPIRED",
    "failed": "FAILED",
    "unknown": "NEEDS_REVIEW",
}


def validate_order_ticket_payload(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    order = resolve_order_ticket_payload(Path(workspace_root), args)
    reasons = _schema_reasons(order)
    conflict = order_ticket_payload_conflict(Path(workspace_root), order)
    if conflict:
        reasons.append(conflict)
    policy = evaluate_policy(workspace_root, {**args, "action": args.get("action") or "order_ticket.check", "order": order})
    all_reasons = list(dict.fromkeys(reasons + policy["reasons"]))
    result = {"valid": not all_reasons and policy["decision"] == "allow", "reasons": all_reasons, "policy": policy, "db_canonical": True, "workspace_context": workspace_context_payload(workspace_root)}
    return result


def validate_approval_receipt(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    if not args.get("approval_receipt_id"):
        raise ValueError("approval_receipt_id is required")
    order = resolve_order_ticket_payload(root, args)
    receipt = resolve_canonical_approval_receipt(root, args, order)
    return _validate_approval_receipt_payload(root, order, receipt)


def _validate_approval_receipt_payload(
    workspace_root: Path | str,
    order: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    for field in [
        "approval_receipt_id",
        "ticket_id",
        "approved_by",
        "valid",
        "created_at",
        "expires_at",
        "exact_order_hash",
        "broker_id",
        "broker_account_id",
        "max_notional",
        "max_price",
        "approved_order_type",
        "approved_time_in_force",
        "valid_until",
        "policy_decision",
    ]:
        if receipt.get(field) in (None, ""):
            reasons.append(f"missing {field}")
    if "quote_as_of_requirement" not in receipt:
        reasons.append("missing quote_as_of_requirement")
    if not isinstance(receipt.get("policy_decision"), dict) or not receipt["policy_decision"]:
        reasons.append("approval_receipt.policy_decision must be an object")
    if receipt.get("valid") is not True:
        reasons.append("approval_receipt.valid must be true")
    if order.get("ticket_id") and receipt.get("ticket_id") != order["ticket_id"]:
        reasons.append("approval_receipt.ticket_id does not match order ticket id")
    if order.get("created_by") and receipt.get("approved_by") == order["created_by"]:
        reasons.append("order creator cannot approve the same order")
    expires_at = _parse_datetime(receipt.get("expires_at"))
    if receipt.get("expires_at") and expires_at is None:
        reasons.append("approval_receipt.expires_at is not a valid date")
    if expires_at and expires_at <= datetime.now(timezone.utc):
        reasons.append("approval receipt is expired")
    valid_until = _parse_datetime(receipt.get("valid_until"))
    if receipt.get("valid_until") and valid_until is None:
        reasons.append("approval_receipt.valid_until is not a valid date")
    if valid_until and valid_until <= datetime.now(timezone.utc):
        reasons.append("approval valid_until is expired")
    if receipt.get("exact_order_hash") and stable_hash(order) != receipt.get("exact_order_hash"):
        reasons.append("approval exact_order_hash does not match order ticket payload")
    if receipt.get("broker_id") != order.get("broker_id"):
        reasons.append("approval broker_id does not match order")
    if receipt.get("broker_account_id") != order.get("broker_account_id"):
        reasons.append("approval broker_account_id does not match order")
    max_notional = _number_or_none(receipt.get("max_notional"))
    order_notional = _number_or_none(order.get("estimated_notional"))
    if max_notional is not None and order_notional is not None and order_notional > max_notional:
        reasons.append("order notional exceeds approval scope")
    max_price = _number_or_none(receipt.get("max_price"))
    order_price = _number_or_none(order.get("limit_price"))
    if max_price is not None and order_price is not None and order_price > max_price:
        reasons.append("order price exceeds approval scope")
    if receipt.get("approved_order_type") != (order.get("order_type") or "limit"):
        reasons.append("order type differs from approval scope")
    if receipt.get("approved_time_in_force") != (order.get("time_in_force") or "day"):
        reasons.append("time in force differs from approval scope")
    return {"valid": not reasons, "reasons": reasons, "db_canonical": True, "workspace_context": workspace_context_payload(workspace_root)}


def _create_order_approval_receipt(workspace_root: Path | str, order: dict[str, Any], approved_by: str = "risk-manager", expires_hours: int = 24) -> dict[str, Any]:
    root = Path(workspace_root)
    ticket = get_order_ticket_model(root, {"ticket_id": order.get("ticket_id")})
    order = order_payload_from_ticket(ticket)
    validation = validate_order_ticket_payload(root, {"principal_id": approved_by, "order": order})
    if not validation["valid"]:
        rejected = {"status": "rejected", "ticket_id": order.get("ticket_id"), "reasons": validation["reasons"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
        write_audit_event(
            root,
            {"type": "approval.rejected", "resource": str(order.get("ticket_id") or ""), "decision": "rejected", "payload": rejected},
            principal_id=approved_by,
            source="service",
        )
        return rejected
    approval_policy = evaluate_policy(root, {"principal_id": approved_by, "action": "approval_receipt.create", "order": order})
    if approval_policy["decision"] != "allow":
        rejected = {"status": "rejected", "ticket_id": order.get("ticket_id"), "reasons": approval_policy["reasons"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
        write_audit_event(
            root,
            {"type": "approval.rejected", "resource": str(order.get("ticket_id") or ""), "decision": "rejected", "payload": rejected},
            principal_id=approved_by,
            source="service",
        )
        return rejected
    if approved_by == order.get("created_by"):
        raise ValueError("order creator cannot approve the same order")
    created = datetime.now(timezone.utc)
    receipt = {
        "approval_receipt_id": f"approval-{sanitize_id(order['ticket_id'])}-{created.strftime('%Y%m%dT%H%M%S%fZ')}",
        "approved_by": approved_by,
        "valid": True,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "expires_at": (created + timedelta(hours=expires_hours)).isoformat().replace("+00:00", "Z"),
        "exact_order_hash": stable_hash(order),
        "ticket_id": order["ticket_id"],
        "broker_id": order["broker_id"],
        "broker_account_id": order["broker_account_id"],
        "max_notional": order.get("estimated_notional"),
        "max_price": order.get("limit_price"),
        "max_slippage_bps": order.get("max_slippage_bps", 0),
        "approved_order_type": order.get("order_type") or "limit",
        "approved_time_in_force": order.get("time_in_force") or "day",
        "valid_until": (created + timedelta(hours=expires_hours)).isoformat().replace("+00:00", "Z"),
        "quote_as_of_requirement": order.get("quote_as_of_requirement", ""),
        "policy_decision": validation["policy"],
    }
    receipt_validation = _validate_approval_receipt_payload(root, order, receipt)
    if not receipt_validation["valid"]:
        return {"status": "rejected", "ticket_id": order.get("ticket_id"), "reasons": receipt_validation["reasons"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
    persist_approval_receipt(root, receipt)
    if ticket.current_state in {"DRAFT", "PRECHECKED", "NEEDS_REVIEW"}:
        transition_order_ticket(ticket, "READY_FOR_APPROVAL", approved_by, {"approval_receipt_id": receipt["approval_receipt_id"]})
    if ticket.current_state == "READY_FOR_APPROVAL":
        transition_order_ticket(ticket, "APPROVED", approved_by, {"approval_receipt_id": receipt["approval_receipt_id"]})
    result = {
        "status": "approved",
        "ticket_id": order["ticket_id"],
        "approval_receipt": receipt,
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    write_audit_event(
        root,
        {"type": "approval.accepted", "resource": order["ticket_id"], "decision": "approved", "payload": result},
        principal_id=approved_by,
        source="service",
    )
    return result


def submit_approved_order(
    workspace_root: Path | str,
    args: dict[str, Any],
    *,
    native_mandate: Any = None,
) -> dict[str, Any]:
    root = Path(workspace_root)
    from tradingcodex_service.application.execution_gateway import (
        NATIVE_SUBMIT_ACTION,
        NATIVE_USER_PRINCIPAL_ID,
        authorize_native_execution,
    )

    args = authorize_native_execution(root, args, native_mandate, NATIVE_SUBMIT_ACTION)
    mandate_metadata = native_mandate.audit_metadata()
    unsupported = sorted({"approval_receipt", "approval_receipt_path"}.intersection(args))
    if unsupported:
        raise ValueError("approval receipts must be referenced by approval_receipt_id")
    if not args.get("approval_receipt_id"):
        raise ValueError("approval_receipt_id is required")
    order = resolve_order_ticket_payload(root, args)
    principal_id = NATIVE_USER_PRINCIPAL_ID
    receipt = resolve_canonical_approval_receipt(root, args, order)
    order_reasons = _schema_reasons(order)
    order_validation = {"valid": not order_reasons, "reasons": order_reasons}
    receipt_validation = _validate_approval_receipt_payload(root, order, receipt)
    policy = evaluate_policy(root, {
        "principal_id": principal_id,
        "action": NATIVE_SUBMIT_ACTION,
        "order": order,
        "approval_receipt_id": receipt["approval_receipt_id"],
        "require_approval_check": True,
    })
    if not order_validation["valid"] or not receipt_validation["valid"] or policy["decision"] != "allow":
        return _submission_rejected(
            root,
            order,
            principal_id,
            order_validation["reasons"] + receipt_validation["reasons"] + policy["reasons"],
        )
    from apps.orders.services import execution_idempotency_key, existing_execution_for_order

    portfolio_id, account_id, strategy_id = portfolio_keys(order, root)
    idempotency_key = execution_idempotency_key(
        order,
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
    )
    existing_execution = existing_execution_for_order(
        str(order.get("ticket_id") or ""),
        idempotency_key,
        portfolio_id,
        account_id,
        strategy_id,
    )
    if existing_execution is not None:
        if existing_execution.status == "pending" and existing_execution.provider_invoked_at is not None:
            from apps.orders.services import recover_uncertain_execution

            needs_review = {
                "status": "needs_review",
                "ticket_id": order.get("ticket_id"),
                "adapter": existing_execution.adapter,
                "idempotency_key": existing_execution.idempotency_key,
                "reasons": ["a prior provider submission may have been invoked; automatic retry is blocked"],
                "native_execution_mandate": mandate_metadata,
                "db_canonical": True,
                "workspace_context": workspace_context_payload(root),
            }
            recover_uncertain_execution(existing_execution, needs_review, principal_id=principal_id)
            return needs_review
        return _submission_rejected(
            root,
            order,
            principal_id,
            [f"order already has an execution result: {existing_execution.status}"],
        )
    try:
        ticket = get_order_ticket_model(root, {**args, "ticket_id": order.get("ticket_id")})
    except ValueError as exc:
        return _submission_rejected(root, order, principal_id, [str(exc)])
    if ticket.current_state != "APPROVED":
        return _submission_rejected(
            root,
            order,
            principal_id,
            [f"order ticket must be APPROVED before submission: {ticket.current_state}"],
        )
    adapter_reasons = _adapter_preflight_reasons(root, order, args)
    if adapter_reasons:
        rejected = {
            "status": "rejected",
            "ticket_id": order.get("ticket_id"),
            "adapter": order.get("broker_id"),
            "reasons": adapter_reasons,
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {
                "type": "submit_approved_order.adapter_preflight_rejected",
                "resource": str(order.get("ticket_id") or ""),
                "decision": "rejected",
                "payload": rejected,
            },
            principal_id=principal_id,
            source="service",
        )
        return rejected
    ensure_runtime_database(root)
    from apps.orders.services import (
        finalize_execution_reservation,
        mark_provider_invoked,
        recover_uncertain_execution,
        reserve_execution,
    )

    reservation = reserve_execution(
        order=order,
        receipt=receipt,
        adapter=order.get("broker_id", ""),
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
        workspace_context=workspace_context_payload(root),
        principal_id=principal_id,
        mandate_metadata=mandate_metadata,
    )
    if not reservation.created:
        rejected = {
            "status": "rejected",
            "ticket_id": order.get("ticket_id"),
            "idempotency_key": reservation.idempotency_key,
            "reasons": [f"order already has an execution result: {reservation.execution.status}"],
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {
                "type": "submit_approved_order.duplicate",
                "resource": str(order.get("ticket_id") or ""),
                "decision": "rejected",
                "payload": rejected,
            },
            principal_id=principal_id,
            source="service",
        )
        return rejected
    mark_provider_invoked(reservation.execution)
    raw_adapter_result: Any = None
    try:
        raw_adapter_result = submit_with_adapter(root, order)
        adapter_result = _canonical_adapter_order_result(
            raw_adapter_result,
            operation="order submission",
        )
    except Exception as exc:
        returned_broker_order_id = (
            raw_adapter_result.get("broker_order_id")
            if isinstance(raw_adapter_result, dict)
            else ""
        )
        broker_order_id = _safe_provider_identifier(
            getattr(exc, "broker_order_id", "") or returned_broker_order_id
        )
        uncertain_result = {
            "adapter": order.get("broker_id"),
            "broker_order_id": broker_order_id,
            "client_order_id": order.get("client_order_id") or _deterministic_client_order_id(order),
            "status": "unknown",
            "submitted_at": now_iso(),
            "needs_review": True,
            **safe_provider_error("submission_uncertain", exc),
        }
        reasons = ["provider submission result is uncertain; inspect canonical broker status before retry"]
        needs_review = {
            "status": "needs_review",
            "ticket_id": order.get("ticket_id"),
            "adapter": order.get("broker_id"),
            "idempotency_key": reservation.idempotency_key,
            "reasons": reasons,
            "result": uncertain_result,
            "native_execution_mandate": mandate_metadata,
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        recover_uncertain_execution(reservation.execution, needs_review, principal_id=principal_id)
        return needs_review
    accepted = {
        "status": "accepted",
        "ticket_id": order["ticket_id"],
        "adapter": order["broker_id"],
        "idempotency_key": reservation.idempotency_key,
        "result": adapter_result,
        "native_execution_mandate": mandate_metadata,
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    try:
        projection = _record_ticket_submit_result(root, order, adapter_result, principal_id)
        if projection["fill_recorded"]:
            accepted["account_sync"] = _sync_ticket_account(root, projection["ticket"], principal_id)
        finalize_execution_reservation(reservation.execution, accepted, principal_id=principal_id)
        return accepted
    except Exception as exc:
        stored_result = adapter_result if isinstance(adapter_result, dict) else {
            "invalid_adapter_result_type": type(adapter_result).__name__,
        }
        needs_review = {
            **accepted,
            "status": "needs_review",
            "reasons": ["provider returned but local finalization failed; inspect canonical broker status before retry"],
            "result": {
                **stored_result,
                "needs_review": True,
                **safe_provider_error("local_finalization_failed", exc),
            },
        }
        recover_uncertain_execution(reservation.execution, needs_review, principal_id=principal_id)
        return needs_review


def _submission_rejected(
    root: Path,
    order: dict[str, Any],
    principal_id: str,
    reasons: list[str],
) -> dict[str, Any]:
    rejected = {
        "status": "rejected",
        "ticket_id": order.get("ticket_id"),
        "reasons": list(dict.fromkeys(reasons)),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    write_audit_event(
        root,
        {
            "type": "submit_approved_order.rejected",
            "resource": str(order.get("ticket_id") or ""),
            "decision": "rejected",
            "payload": rejected,
        },
        principal_id=principal_id,
        source="service",
    )
    return rejected


def create_order_ticket(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ensure_runtime_database(root)
    from apps.orders.models import OrderTicket

    principal_id = str(args.get("principal_id") or ORDER_TICKET_CREATOR_ROLE)
    if principal_id != ORDER_TICKET_CREATOR_ROLE:
        raise PermissionError(f"only {ORDER_TICKET_CREATOR_ROLE} can create order tickets")

    fields = normalize_order_ticket_fields(root, args)
    fields["created_by"] = principal_id
    connection = _resolve_ticket_broker_connection(root, fields)
    broker_account = _resolve_ticket_broker_account(connection, fields)
    portfolio_id, account_id, strategy_id = portfolio_keys(
        {
            "portfolio_id": fields.get("portfolio_id"),
            "account_id": fields.get("account_id"),
            "strategy_id": fields.get("strategy_id"),
        },
        root,
    )
    ticket_id = str(fields.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ValueError("ticket_id is required")
    existing_ticket = OrderTicket.objects.filter(ticket_id=ticket_id).first()
    if existing_ticket is not None and "created_at" not in args and isinstance(existing_ticket.payload, dict):
        stored_order = existing_ticket.payload.get("order")
        if isinstance(stored_order, dict) and stored_order.get("created_at"):
            fields["created_at"] = stored_order["created_at"]
    money = _money_contract_from_fields(root, fields)
    estimated_notional = money["base_notional"]
    order_payload = canonical_order_from_fields(
        {
            **fields,
            "ticket_id": ticket_id,
            "portfolio_id": portfolio_id,
            "account_id": account_id,
            "strategy_id": strategy_id,
            "broker_id": connection.broker_id,
            "broker_account_id": broker_account.broker_account_id if broker_account else "",
            "estimated_notional": str(estimated_notional),
            "native_notional": str(money["native_notional"]),
            "base_currency": money["base_currency"],
            "fx_rate": str(money["fx_rate"]),
            "fx_source_snapshot_id": money["fx_source_snapshot_id"],
            "fx_as_of": money["fx_as_of"].isoformat(),
            "money": {
                key: value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, Decimal) else value
                for key, value in money.items()
            },
        }
    )
    payload_hash = stable_hash(order_payload)
    ticket, created = OrderTicket.objects.get_or_create(
        ticket_id=ticket_id,
        defaults={
            "source": fields.get("source") or "web",
            "portfolio_id": portfolio_id,
            "account_id": account_id,
            "strategy_id": strategy_id,
            "broker_connection": connection,
            "broker_account": broker_account,
            "instrument_id": fields.get("instrument_id") or fields["symbol"],
            "symbol": fields["symbol"],
            "side": fields["side"],
            "quantity": fields["quantity"],
            "order_type": fields.get("order_type") or "limit",
            "limit_price": fields["limit_price"],
            "stop_price": fields.get("stop_price"),
            "time_in_force": fields.get("time_in_force") or "day",
            "estimated_notional": estimated_notional,
            "native_notional": money["native_notional"],
            "currency": fields["currency"],
            "base_currency": money["base_currency"],
            "fx_rate": money["fx_rate"],
            "fx_source_snapshot_id": money["fx_source_snapshot_id"],
            "fx_as_of": money["fx_as_of"],
            "status": "DRAFT",
            "current_state": "DRAFT",
            "payload_hash": payload_hash,
            "user_visible_summary": fields.get("user_visible_summary") or _ticket_summary(order_payload),
            "created_by": principal_id,
            "natural_language_source": fields.get("natural_language") or "",
            "workspace_context": workspace_context_payload(root),
            "payload": {
                "order": order_payload,
                "canonical_order": order_payload.get("canonical_order", {}),
                "money": order_payload.get("money", {}),
                "raw": json.loads(json.dumps(args, default=str)),
            },
        },
    )
    if not created and (ticket.portfolio_id, ticket.account_id, ticket.strategy_id) != (portfolio_id, account_id, strategy_id):
        raise ValueError("order ticket id already exists for another paper account scope")
    if not created:
        stored_order = dict(ticket.payload.get("order") or {}) if isinstance(ticket.payload, dict) else {}
        comparable_order = dict(order_payload)
        if stored_order and "created_at" not in args:
            comparable_order["created_at"] = stored_order.get("created_at", "")
        if stored_order and fields["currency"] == fields["base_currency"] and "fx_as_of" not in args:
            comparable_order["fx_as_of"] = stored_order.get("fx_as_of", "")
        if not stored_order or stable_hash(comparable_order) != stable_hash(stored_order):
            raise ValueError("order ticket id already exists with a different payload")
    event_type = "created" if created else "reused"
    record_order_event(ticket, event_type, args.get("principal_id") or ticket.created_by, {"payload_hash": payload_hash})
    result = serialize_order_ticket(ticket)
    write_audit_event(
        root,
        {"type": f"order_ticket.{event_type}", "resource": ticket.ticket_id, "decision": event_type, "payload": result},
        args.get("principal_id") or ticket.created_by,
        "service",
    )
    return {"status": "created" if created else "existing", "ticket": result, "db_canonical": True, "workspace_context": workspace_context_payload(root)}


def run_order_checks(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ensure_runtime_database(root)
    from apps.orders.models import OrderCheckRun
    from tradingcodex_service.application.brokers import adapter_for_connection

    ticket = get_order_ticket_model(root, args)
    order = order_payload_from_ticket(ticket)
    principal_id = str(args.get("principal_id") or "portfolio-manager")
    checks: list[dict[str, Any]] = []

    schema_reasons = _schema_reasons(order)
    checks.append(_check_result("schema", not schema_reasons, schema_reasons))

    policy = evaluate_policy(root, {**args, "principal_id": principal_id, "action": "order_ticket.check", "order": order})
    policy_reasons = [reason for reason in policy["reasons"] if "symbol is restricted" not in reason]
    restricted_reasons = [reason for reason in policy["reasons"] if "symbol is restricted" in reason]
    checks.append(_check_result("policy", not policy_reasons, policy_reasons, {"policy": policy}))
    checks.append(_check_result("restricted", not restricted_reasons, restricted_reasons))

    adapter = adapter_for_connection(ticket.broker_connection, root) if ticket.broker_connection else None
    if adapter is not None:
        adapter_validation = adapter.validate_order_translation(order)
        adapter_reasons = list(adapter_validation.reasons)
    else:
        adapter_reasons = ["broker adapter is not configured"]
    cash_position_reasons = [reason for reason in adapter_reasons if "cash" in reason or "position" in reason]
    broker_reasons = [reason for reason in adapter_reasons if reason not in cash_position_reasons]
    checks.append(_check_result("cash" if order.get("side") == "buy" else "position", not cash_position_reasons, cash_position_reasons))
    checks.append(_check_result("broker_validate", not broker_reasons, broker_reasons))
    checks.append(_check_result("market", True, ["market quote freshness is not configured for paper broker"], decision="warn"))
    checks.append(_check_result("risk", not [item for item in checks if item["decision"] == "fail"], [], {"review": "risk-manager review required before approval"}))

    OrderCheckRun.objects.filter(ticket=ticket).delete()
    for check in checks:
        OrderCheckRun.objects.create(
            ticket=ticket,
            check_type=check["check_type"],
            decision=check["decision"],
            reasons=check["reasons"],
            quote_as_of=check.get("quote_as_of", ""),
            source_snapshot_ref=check.get("source_snapshot_ref", ""),
            payload=check.get("payload", {}),
        )
    failed = [check for check in checks if check["decision"] == "fail"]
    next_state = "NEEDS_REVIEW" if failed else "READY_FOR_APPROVAL"
    transition_order_ticket(ticket, next_state, principal_id, {"checks": checks})
    result = {
        "status": "checked",
        "ticket_id": ticket.ticket_id,
        "approval_ready": not failed,
        "checks": checks,
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    write_audit_event(
        root,
        {
            "type": "order_ticket.checked",
            "resource": ticket.ticket_id,
            "decision": "approved" if result["approval_ready"] else "needs_review",
            "payload": result,
        },
        principal_id,
        "service",
    )
    return result


def request_order_approval(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ticket = get_order_ticket_model(root, args)
    principal_id = str(args.get("principal_id") or "risk-manager")
    latest_checks = list(ticket.check_runs.all())
    if not latest_checks:
        checks = run_order_checks(root, {"ticket_id": ticket.ticket_id, "principal_id": principal_id})
        if not checks["approval_ready"]:
            return {"status": "rejected", "ticket_id": ticket.ticket_id, "reasons": ["order checks failed"], "checks": checks["checks"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
    elif any(check.decision == "fail" for check in latest_checks):
        return {"status": "rejected", "ticket_id": ticket.ticket_id, "reasons": ["fail check prevents approval"], "db_canonical": True, "workspace_context": workspace_context_payload(root)}
    order = order_payload_from_ticket(ticket)
    result = _create_order_approval_receipt(root, order, principal_id, int(args.get("expires_hours") or 24))
    if result.get("status") == "approved":
        ticket.refresh_from_db()
        if ticket.current_state != "APPROVED":
            transition_order_ticket(ticket, "APPROVED", principal_id, result)
    return {**result, "ticket_id": ticket.ticket_id}


def list_order_tickets(workspace_root: Path | str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.orders.models import OrderTicket

    args = args or {}
    limit = max(1, min(int(args.get("limit") or 30), 200))
    portfolio_id, account_id, strategy_id = portfolio_keys(args, workspace_root)
    queryset = OrderTicket.objects.select_related("broker_connection", "broker_account").prefetch_related("check_runs", "events")
    queryset = queryset.filter(portfolio_id=portfolio_id, account_id=account_id, strategy_id=strategy_id)
    state = args.get("state")
    if state:
        queryset = queryset.filter(current_state=state)
    return {
        "tickets": [serialize_order_ticket(ticket) for ticket in queryset[:limit]],
        "db_canonical": True,
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def get_order_ticket(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticket": serialize_order_ticket(get_order_ticket_model(workspace_root, args), include_related=True),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def _refresh_broker_order_status_for_reconciliation(
    workspace_root: Path | str,
    args: dict[str, Any],
) -> dict[str, Any]:
    root = Path(workspace_root)
    ensure_runtime_database(root)
    from tradingcodex_service.application.brokers import adapter_for_connection, broker_connection_provider_review_reasons

    principal_id = str(args.get("principal_id") or "system")
    ticket = get_order_ticket_model(root, args)
    broker_order_id = str(args.get("broker_order_id") or "")
    if not broker_order_id:
        raise ValueError("broker_order_id is required")
    broker_order = ticket.broker_orders.filter(broker_order_id=broker_order_id).first()
    if broker_order is None:
        result = {
            "status": "no_broker_order",
            "ticket_id": ticket.ticket_id,
            "reasons": ["ticket has no broker order recorded yet"],
            "ticket": serialize_order_ticket(ticket, include_related=True),
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {"type": "broker_order_status.not_found", "resource": ticket.ticket_id, "decision": "not_found", "payload": result},
            principal_id,
            "service",
        )
        return result
    source_reasons = broker_connection_provider_review_reasons(ticket.broker_connection, root)
    if source_reasons:
        result = {
            "status": "blocked",
            "ticket_id": ticket.ticket_id,
            "broker_order_id": broker_order.broker_order_id,
            "reasons": source_reasons,
            "ticket": serialize_order_ticket(ticket, include_related=True),
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {"type": "broker_order_status.blocked", "resource": ticket.ticket_id, "decision": "blocked", "payload": result},
            principal_id,
            "service",
        )
        return result

    try:
        adapter_status = _canonical_adapter_order_result(
            adapter_for_connection(ticket.broker_connection, root).get_order_status(broker_order.broker_order_id),
            operation="broker status refresh",
            expected_broker_order_id=broker_order.broker_order_id,
        )
        projection = _record_ticket_submit_result(root, order_payload_from_ticket(ticket), adapter_status, principal_id)
        ticket = projection["ticket"]
        broker_status = adapter_status["status"].lower()
        record_order_event(
            ticket,
            "status_refreshed",
            principal_id,
            {
                "broker_order_id": broker_order.broker_order_id,
                "broker_status": broker_status,
                "adapter_status": adapter_status,
            },
        )
        account_sync = _sync_ticket_account(root, ticket, principal_id) if projection["fill_recorded"] else None
    except Exception as exc:
        from apps.orders.services import mark_ticket_needs_review

        reason = "broker status refresh requires review; provider diagnostics were withheld"
        safe_error = safe_provider_error("status_refresh_failed", exc)
        mark_ticket_needs_review(
            ticket,
            principal_id=principal_id,
            reason=reason,
            payload={
                "operation": "broker_status_refresh",
                "broker_order_id": broker_order.broker_order_id,
            },
        )
        ticket.refresh_from_db()
        result = {
            "status": "needs_review",
            "ticket_id": ticket.ticket_id,
            "broker_order_id": broker_order.broker_order_id,
            "reasons": [reason],
            **safe_error,
            "ticket": serialize_order_ticket(ticket, include_related=True),
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {"type": "broker_order_status.needs_review", "resource": ticket.ticket_id, "decision": "needs_review", "payload": result},
            principal_id,
            "service",
        )
        return result
    ticket.refresh_from_db()
    result = {
        "status": "refreshed",
        "ticket_id": ticket.ticket_id,
        "broker_order_id": broker_order.broker_order_id,
        "broker_status": broker_status,
        "adapter_status": adapter_status,
        "ticket": serialize_order_ticket(ticket, include_related=True),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    if account_sync is not None:
        result["account_sync"] = account_sync
    write_audit_event(
        root,
        {"type": "broker_order_status.refreshed", "resource": ticket.ticket_id, "decision": "refreshed", "payload": result},
        principal_id,
        "service",
    )
    return result


def get_order_status(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ensure_runtime_database(root)
    ticket_id = str(args.get("ticket_id") or "")
    broker_order_id = str(args.get("broker_order_id") or "")
    if ticket_id:
        ticket = get_order_ticket_model(root, args)
        return {
            "status": ticket.current_state,
            "ticket_id": ticket.ticket_id,
            "ticket": serialize_order_ticket(ticket, include_related=True),
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
    if not broker_order_id:
        raise ValueError("ticket_id or broker_order_id is required")
    broker_order = _find_broker_order_for_active_profile(root, args, broker_order_id)
    if broker_order is None:
        return {
            "status": "unknown",
            "broker_order_id": broker_order_id,
            "reasons": ["no broker order matched"],
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
    return {
        "status": broker_order.broker_status,
        "ticket_id": broker_order.ticket.ticket_id,
        "broker_order_id": broker_order.broker_order_id,
        "ticket": serialize_order_ticket(broker_order.ticket, include_related=True),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }


def discard_draft_order(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ensure_runtime_database(root)
    principal_id = str(args.get("principal_id") or "")
    if principal_id != "portfolio-manager":
        raise PermissionError("only portfolio-manager can discard draft orders")
    ticket = get_order_ticket_model(root, args)
    reasons: list[str] = []
    if ticket.current_state not in {"DRAFT", "PRECHECKED"}:
        reasons.append(f"only DRAFT or PRECHECKED tickets can be discarded: {ticket.current_state}")
    if ticket.broker_orders.exists():
        reasons.append("a ticket with a broker order cannot be discarded")
    policy = evaluate_policy(
        root,
        {
            "principal_id": principal_id,
            "action": "mcp.tradingcodex.discard_draft_order",
            "order": order_payload_from_ticket(ticket),
        },
    )
    reasons.extend(policy["reasons"])
    if reasons:
        result = {
            "status": "not_discardable",
            "ticket_id": ticket.ticket_id,
            "reasons": list(dict.fromkeys(reasons)),
            "ticket": serialize_order_ticket(ticket, include_related=True),
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {"type": "order_ticket.discard.rejected", "resource": ticket.ticket_id, "decision": "rejected", "payload": result},
            principal_id,
            "service",
        )
        return result
    transition_order_ticket(ticket, "CANCELED", principal_id, {"mode": "draft_discard"})
    ticket.refresh_from_db()
    result = {
        "status": "discarded",
        "ticket_id": ticket.ticket_id,
        "ticket": serialize_order_ticket(ticket, include_related=True),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    write_audit_event(
        root,
        {"type": "order_ticket.discard.accepted", "resource": ticket.ticket_id, "decision": "accepted", "payload": result},
        principal_id,
        "service",
    )
    return result


def cancel_submitted_order(
    workspace_root: Path | str,
    args: dict[str, Any],
    *,
    native_mandate: Any = None,
) -> dict[str, Any]:
    root = Path(workspace_root)
    ensure_runtime_database(root)
    from tradingcodex_service.application.execution_gateway import (
        NATIVE_CANCEL_ACTION,
        NATIVE_USER_PRINCIPAL_ID,
        authorize_native_execution,
    )

    args = authorize_native_execution(root, args, native_mandate, NATIVE_CANCEL_ACTION)
    mandate_metadata = native_mandate.audit_metadata()
    principal_id = NATIVE_USER_PRINCIPAL_ID
    if not args.get("approval_receipt_id"):
        raise ValueError("approval_receipt_id is required")
    ticket = get_order_ticket_model(root, args)
    broker_order_id = str(args.get("broker_order_id") or "")
    if not broker_order_id:
        raise ValueError("broker_order_id is required")
    broker_order = ticket.broker_orders.filter(broker_order_id=broker_order_id).first()
    order = order_payload_from_ticket(ticket)
    receipt = resolve_canonical_approval_receipt(root, args, order)
    receipt_validation = _validate_approval_receipt_payload(root, order, receipt)
    policy = evaluate_policy(
        root,
        {
            "principal_id": principal_id,
            "action": NATIVE_CANCEL_ACTION,
            "order": order,
            "approval_receipt_id": receipt["approval_receipt_id"],
            "require_approval_check": True,
        },
    )
    reasons = list(receipt_validation["reasons"]) + list(policy["reasons"])
    if ticket.current_state not in {"SUBMITTED", "ACKED", "PARTIALLY_FILLED"}:
        reasons.append(f"only submitted broker orders can be canceled: {ticket.current_state}")
    if broker_order is None:
        reasons.append("submitted cancel requires a known broker_order_id")
    if reasons:
        result = {
            "status": "not_cancelable",
            "ticket_id": ticket.ticket_id,
            "reasons": list(dict.fromkeys(reasons)),
            "ticket": serialize_order_ticket(ticket, include_related=True),
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {"type": "order_ticket.cancel.rejected", "resource": ticket.ticket_id, "decision": "rejected", "payload": result},
            principal_id,
            "service",
        )
        return result
    cancel_idempotency_key = "cancel:" + stable_hash({
        "ticket_id": ticket.ticket_id,
        "broker_order_id": broker_order.broker_order_id,
        "approval_receipt_id": receipt.get("approval_receipt_id"),
        "approval_hash": receipt.get("exact_order_hash"),
    })
    cancel_payload: dict[str, Any] = {
        "broker_order_id": broker_order.broker_order_id,
        "mode": "local_non_live",
        "idempotency_key": cancel_idempotency_key,
        "native_execution_mandate": mandate_metadata,
    }
    if ticket.broker_connection is not None:
        connection = ticket.broker_connection
        metadata = connection.metadata if isinstance(connection.metadata, dict) else {}
        profile = metadata.get("capability_profile") if isinstance(metadata.get("capability_profile"), dict) else {}
        if profile.get("execution_posture") == "live_broker":
            reasons = []
            from tradingcodex_service.application.brokers import broker_connection_provider_review_reasons

            reasons.extend(broker_connection_provider_review_reasons(connection, root))
            if connection.status != "trading_enabled":
                reasons.append(f"broker connection is not trading_enabled: {connection.broker_id}")
            if "order.cancel.live" not in set(connection.enabled_trade_scopes or []):
                reasons.append(f"broker connection lacks order.cancel.live scope: {connection.broker_id}")
            expected_confirmation = _expected_live_cancel_confirmation(ticket, broker_order)
            if str(args.get("live_confirmation") or "") != expected_confirmation:
                reasons.append(f"live cancel confirmation required: {expected_confirmation}")
            if reasons:
                result = {
                    "status": "not_cancelable",
                    "ticket_id": ticket.ticket_id,
                    "reasons": reasons,
                    "ticket": serialize_order_ticket(ticket, include_related=True),
                    "db_canonical": True,
                    "workspace_context": workspace_context_payload(root),
                }
                write_audit_event(
                    root,
                    {"type": "order_ticket.cancel.rejected", "resource": ticket.ticket_id, "decision": "rejected", "payload": result},
                    principal_id,
                    "service",
                )
                return result
            from apps.orders.models import BrokerOrder, OrderTicket

            with transaction.atomic():
                locked_broker_order = BrokerOrder.objects.select_for_update().select_related("ticket").get(pk=broker_order.pk)
                locked_ticket = OrderTicket.objects.select_for_update().get(pk=ticket.pk)
                locked_metadata = dict(locked_broker_order.metadata or {})
                prior_intent = locked_metadata.get("cancel_intent") if isinstance(locked_metadata.get("cancel_intent"), dict) else {}
                if prior_intent.get("idempotency_key") == cancel_idempotency_key:
                    prior_status = str(prior_intent.get("status") or "")
                    if prior_status == "canceled":
                        return {
                            "status": "canceled",
                            "ticket_id": locked_ticket.ticket_id,
                            "broker_order_id": locked_broker_order.broker_order_id,
                            "broker_status": locked_broker_order.broker_status,
                            "idempotency_key": cancel_idempotency_key,
                            "ticket": serialize_order_ticket(locked_ticket, include_related=True),
                            "db_canonical": True,
                            "workspace_context": workspace_context_payload(root),
                        }
                    if prior_status in {"pending", "needs_review"}:
                        prior_intent["status"] = "needs_review"
                        prior_intent.setdefault("reason", "a prior provider cancel may have been invoked; automatic retry is blocked")
                        locked_metadata["cancel_intent"] = prior_intent
                        locked_broker_order.metadata = locked_metadata
                        locked_broker_order.save(update_fields=["metadata"])
                        from apps.orders.services import mark_ticket_needs_review

                        mark_ticket_needs_review(
                            locked_ticket,
                            principal_id=principal_id,
                            reason=prior_intent["reason"],
                            payload={
                                "operation": "provider_cancel",
                                "broker_order_id": locked_broker_order.broker_order_id,
                                "idempotency_key": cancel_idempotency_key,
                            },
                        )
                        locked_ticket.refresh_from_db()
                        return {
                            "status": "needs_review",
                            "ticket_id": locked_ticket.ticket_id,
                            "broker_order_id": locked_broker_order.broker_order_id,
                            "idempotency_key": cancel_idempotency_key,
                            "reasons": [prior_intent["reason"]],
                            "ticket": serialize_order_ticket(locked_ticket, include_related=True),
                            "db_canonical": True,
                            "workspace_context": workspace_context_payload(root),
                        }
                cancel_intent = {
                    "idempotency_key": cancel_idempotency_key,
                    "status": "pending",
                    "reserved_at": now_iso(),
                    "principal_id": principal_id,
                    "approval_receipt_id": receipt.get("approval_receipt_id"),
                    "native_execution_mandate": mandate_metadata,
                }
                locked_metadata["cancel_intent"] = cancel_intent
                locked_broker_order.metadata = locked_metadata
                locked_broker_order.save(update_fields=["metadata"])
                write_audit_event_required(
                    root,
                    principal_id,
                    "execution",
                    {
                        "type": "order_ticket.cancel.intent",
                        "resource": locked_ticket.ticket_id,
                        "decision": "pending",
                        "payload": {
                            "status": "pending",
                            "ticket_id": locked_ticket.ticket_id,
                            "broker_order_id": locked_broker_order.broker_order_id,
                            "idempotency_key": cancel_idempotency_key,
                        },
                    },
                )
                broker_order = locked_broker_order
                ticket = locked_ticket
            from tradingcodex_service.application.brokers import adapter_for_connection

            try:
                adapter_status = _canonical_adapter_cancel_result(
                    adapter_for_connection(connection, root).cancel_order(broker_order.broker_order_id),
                    broker_order.broker_order_id,
                )
            except Exception as exc:
                with transaction.atomic():
                    locked_broker_order = BrokerOrder.objects.select_for_update().get(pk=broker_order.pk)
                    locked_metadata = dict(locked_broker_order.metadata or {})
                    intent = dict(locked_metadata.get("cancel_intent") or {})
                    safe_error = safe_provider_error("cancel_uncertain", exc)
                    intent.update({"status": "needs_review", "failed_at": now_iso(), **safe_error})
                    locked_metadata["cancel_intent"] = intent
                    locked_broker_order.metadata = locked_metadata
                    locked_broker_order.broker_status = "unknown"
                    locked_broker_order.save(update_fields=["metadata", "broker_status"])
                    from apps.orders.services import mark_ticket_needs_review

                    mark_ticket_needs_review(
                        ticket,
                        principal_id=principal_id,
                        reason="provider cancel result is uncertain; inspect canonical broker status before retry",
                        payload={
                            "operation": "provider_cancel",
                            "broker_order_id": broker_order.broker_order_id,
                            "idempotency_key": cancel_idempotency_key,
                        },
                    )
                    ticket.refresh_from_db()
                result = {
                    "status": "needs_review",
                    "ticket_id": ticket.ticket_id,
                    "broker_order_id": broker_order.broker_order_id,
                    "idempotency_key": cancel_idempotency_key,
                    "reasons": ["provider cancel result is uncertain; inspect canonical broker status before retry"],
                    **safe_error,
                    "db_canonical": True,
                    "workspace_context": workspace_context_payload(root),
                }
                write_audit_event_required(
                    root,
                    principal_id,
                    "service",
                    {"type": "order_ticket.cancel.needs_review", "resource": ticket.ticket_id, "decision": "needs_review", "payload": result},
                )
                return result
            broker_status = adapter_status["status"].lower()
            cancel_payload = {
                "broker_order_id": broker_order.broker_order_id,
                "mode": "provider_live",
                "broker_status": broker_status,
                "adapter_status": adapter_status,
                "idempotency_key": cancel_idempotency_key,
                "native_execution_mandate": mandate_metadata,
            }
    try:
        if cancel_payload.get("mode") == "provider_live":
            from apps.orders.models import BrokerOrder, OrderTicket

            with transaction.atomic():
                broker_order = BrokerOrder.objects.select_for_update().get(pk=broker_order.pk)
                ticket = OrderTicket.objects.select_for_update().get(pk=ticket.pk)
                metadata = dict(broker_order.metadata or {})
                intent = dict(metadata.get("cancel_intent") or {})
                intent.update({"status": "canceled", "finalized_at": now_iso()})
                metadata["cancel_intent"] = intent
                metadata["provider_cancel"] = {
                    "canceled_by": principal_id,
                    "canceled_at": now_iso(),
                    "adapter_status": cancel_payload["adapter_status"],
                }
                broker_order.broker_status = cancel_payload["broker_status"]
                broker_order.last_seen_at = datetime.now(timezone.utc)
                broker_order.raw_status_payload_hash = stable_hash(cancel_payload["adapter_status"])
                broker_order.metadata = metadata
                broker_order.save(update_fields=["broker_status", "last_seen_at", "raw_status_payload_hash", "metadata"])
                transition_order_ticket(ticket, "CANCELED", principal_id, cancel_payload)
                write_audit_event_required(
                    root,
                    principal_id,
                    "execution",
                    {
                        "type": "order_ticket.cancel.finalized",
                        "resource": ticket.ticket_id,
                        "decision": "canceled",
                        "payload": {"status": "canceled", "ticket_id": ticket.ticket_id, **cancel_payload},
                    },
                )
        else:
            from apps.orders.models import BrokerOrder, OrderTicket

            with transaction.atomic():
                broker_order = BrokerOrder.objects.select_for_update().get(pk=broker_order.pk)
                ticket = OrderTicket.objects.select_for_update().get(pk=ticket.pk)
                write_audit_event_required(
                    root,
                    principal_id,
                    "execution",
                    {
                        "type": "order_ticket.cancel.intent",
                        "resource": ticket.ticket_id,
                        "decision": "pending",
                        "payload": {
                            "status": "pending",
                            "ticket_id": ticket.ticket_id,
                            "broker_order_id": broker_order.broker_order_id,
                            "idempotency_key": cancel_idempotency_key,
                            "mode": "local_non_live",
                        },
                    },
                )
                metadata = dict(broker_order.metadata or {})
                metadata["local_cancel"] = {
                    "canceled_by": principal_id,
                    "canceled_at": now_iso(),
                    "native_execution_mandate": mandate_metadata,
                }
                broker_order.broker_status = "canceled"
                broker_order.last_seen_at = datetime.now(timezone.utc)
                broker_order.raw_status_payload_hash = stable_hash(metadata)
                broker_order.metadata = metadata
                broker_order.save(update_fields=["broker_status", "last_seen_at", "raw_status_payload_hash", "metadata"])
                transition_order_ticket(ticket, "CANCELED", principal_id, cancel_payload)
                write_audit_event_required(
                    root,
                    principal_id,
                    "execution",
                    {
                        "type": "order_ticket.cancel.finalized",
                        "resource": ticket.ticket_id,
                        "decision": "canceled",
                        "payload": {
                            "status": "canceled",
                            "ticket_id": ticket.ticket_id,
                            "broker_order_id": broker_order.broker_order_id,
                            "idempotency_key": cancel_idempotency_key,
                            "mode": "local_non_live",
                        },
                    },
                )
    except Exception as exc:
        if cancel_payload.get("mode") == "provider_live":
            from apps.orders.models import BrokerOrder, OrderTicket

            with transaction.atomic():
                locked_broker_order = BrokerOrder.objects.select_for_update().get(pk=broker_order.pk)
                metadata = dict(locked_broker_order.metadata or {})
                intent = dict(metadata.get("cancel_intent") or {})
                safe_error = safe_provider_error("cancel_finalization_failed", exc)
                intent.update({"status": "needs_review", "failed_at": now_iso(), **safe_error})
                metadata["cancel_intent"] = intent
                metadata["provider_cancel"] = {
                    "canceled_by": principal_id,
                    "canceled_at": now_iso(),
                    "adapter_status": cancel_payload.get("adapter_status", {}),
                }
                locked_broker_order.metadata = metadata
                locked_broker_order.broker_status = "unknown"
                locked_broker_order.save(update_fields=["metadata", "broker_status"])
                from apps.orders.services import mark_ticket_needs_review

                mark_ticket_needs_review(
                    ticket,
                    principal_id=principal_id,
                    reason="provider returned but cancel finalization failed; inspect canonical broker status before retry",
                    payload={
                        "operation": "provider_cancel_finalization",
                        "broker_order_id": broker_order.broker_order_id,
                        "idempotency_key": cancel_payload.get("idempotency_key", ""),
                    },
                )
                ticket.refresh_from_db()
            result = {
                "status": "needs_review",
                "ticket_id": ticket.ticket_id,
                "broker_order_id": broker_order.broker_order_id,
                "idempotency_key": cancel_payload.get("idempotency_key", ""),
                "reasons": ["provider returned but cancel finalization failed; inspect canonical broker status before retry"],
                **safe_error,
                "ticket": serialize_order_ticket(ticket, include_related=True),
                "db_canonical": True,
                "workspace_context": workspace_context_payload(root),
            }
            write_audit_event_required(
                root,
                principal_id,
                "service",
                {"type": "order_ticket.cancel.needs_review", "resource": ticket.ticket_id, "decision": "needs_review", "payload": result},
            )
            return result
        result = {
            "status": "not_cancelable",
            "ticket_id": ticket.ticket_id,
            "reasons": ["local cancellation could not be committed; no retry was attempted"],
            **safe_provider_error("local_cancel_failed", exc),
            "ticket": serialize_order_ticket(ticket, include_related=True),
            "db_canonical": True,
            "workspace_context": workspace_context_payload(root),
        }
        write_audit_event(
            root,
            {"type": "order_ticket.cancel.rejected", "resource": ticket.ticket_id, "decision": "rejected", "payload": result},
            principal_id,
            "service",
        )
        return result
    ticket.refresh_from_db()
    result = {
        "status": "canceled",
        "ticket_id": ticket.ticket_id,
        "broker_order_id": broker_order.broker_order_id if broker_order else "",
        "broker_status": broker_order.broker_status if broker_order else "local_only",
        "native_execution_mandate": mandate_metadata,
        "ticket": serialize_order_ticket(ticket, include_related=True),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(root),
    }
    write_audit_event_if_available(
        root,
        principal_id,
        "service",
        {"type": "order_ticket.cancel.accepted", "resource": ticket.ticket_id, "decision": "accepted", "payload": result},
    )
    return result


def get_order_ticket_model(workspace_root: Path | str, args: dict[str, Any]) -> Any:
    ensure_runtime_database(workspace_root)
    from apps.orders.models import OrderTicket

    ticket_id = args.get("ticket_id")
    if not ticket_id:
        raise ValueError("ticket_id is required")
    portfolio_id, account_id, strategy_id = portfolio_keys(args, workspace_root)
    ticket = (
        OrderTicket.objects.select_related("broker_connection", "broker_account")
        .prefetch_related("check_runs", "events", "fills", "broker_orders")
        .filter(
            ticket_id=ticket_id,
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
        )
        .first()
    )
    if ticket is None:
        raise ValueError(f"unknown order ticket for paper account scope: {ticket_id}")
    return ticket


def _find_broker_order_for_active_profile(workspace_root: Path | str, args: dict[str, Any], broker_order_id: str) -> Any:
    ensure_runtime_database(workspace_root)
    from apps.orders.models import BrokerOrder

    portfolio_id, account_id, strategy_id = portfolio_keys(args, workspace_root)
    return (
        BrokerOrder.objects.select_related("ticket__broker_connection", "ticket__broker_account")
        .filter(
            broker_order_id=broker_order_id,
            ticket__portfolio_id=portfolio_id,
            ticket__account_id=account_id,
            ticket__strategy_id=strategy_id,
        )
        .first()
    )


def transition_order_ticket(ticket: Any, target_state: str, actor: str, payload: dict[str, Any] | None = None) -> None:
    if target_state not in ORDER_TICKET_STATES:
        raise ValueError(f"unknown order ticket state: {target_state}")
    from apps.orders.models import OrderTicket

    with transaction.atomic():
        locked_ticket = OrderTicket.objects.select_for_update().get(pk=ticket.pk)
        current = locked_ticket.current_state
        if target_state != current and target_state not in ORDER_TICKET_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid order ticket transition: {current} -> {target_state}")
        locked_ticket.current_state = target_state
        locked_ticket.status = target_state
        locked_ticket.save(update_fields=["current_state", "status", "updated_at"])
        record_order_event(locked_ticket, target_state.lower(), actor, payload or {})
        ticket_context = locked_ticket.workspace_context if isinstance(locked_ticket.workspace_context, dict) else {}
        write_audit_event_required(
            ticket_context.get("path"),
            actor,
            "service",
            {
                "type": "order_ticket.transition",
                "resource": locked_ticket.ticket_id,
                "decision": target_state,
                "payload": {"ticket_id": locked_ticket.ticket_id, "from": current, "to": target_state, **(payload or {})},
            },
        )
    ticket.current_state = target_state
    ticket.status = target_state


def record_order_event(ticket: Any, event_type: str, actor: str, payload: dict[str, Any] | None = None) -> Any:
    from apps.orders.models import OrderEvent

    payload = payload or {}
    return OrderEvent.objects.create(
        ticket=ticket,
        event_type=event_type,
        actor=actor,
        payload=payload,
        payload_hash=stable_hash(payload),
    )


def order_payload_from_ticket(ticket: Any) -> dict[str, Any]:
    stored_payload = ticket.payload if isinstance(ticket.payload, dict) else {}
    payload = dict(stored_payload.get("order") or {})
    canonical_order = stored_payload.get("canonical_order")
    if canonical_order:
        payload["canonical_order"] = canonical_order
    payload.update({
        "ticket_id": ticket.ticket_id,
        "symbol": ticket.symbol,
        "side": ticket.side,
        "quantity": str(ticket.quantity),
        "limit_price": str(ticket.limit_price or 0),
        "currency": ticket.currency,
        "broker_id": ticket.broker_connection.broker_id,
        "estimated_notional": str(ticket.estimated_notional or 0),
        "native_notional": str(ticket.native_notional or 0),
        "base_currency": ticket.base_currency,
        "fx_rate": str(ticket.fx_rate or 0),
        "fx_source_snapshot_id": ticket.fx_source_snapshot_id,
        "fx_as_of": ticket.fx_as_of.isoformat() if ticket.fx_as_of else "",
        "created_by": ticket.created_by,
        "portfolio_id": ticket.portfolio_id,
        "account_id": ticket.account_id,
        "strategy_id": ticket.strategy_id,
        "broker_account_id": ticket.broker_account.broker_account_id,
        "order_type": ticket.order_type,
        "time_in_force": ticket.time_in_force,
    })
    payload.setdefault("created_at", ticket.created_at.isoformat())
    return payload


def serialize_order_ticket(ticket: Any, include_related: bool = False) -> dict[str, Any]:
    record = {
        "ticket_id": ticket.ticket_id,
        "source": ticket.source,
        "portfolio_id": ticket.portfolio_id,
        "account_id": ticket.account_id,
        "strategy_id": ticket.strategy_id,
        "broker_id": ticket.broker_connection.broker_id,
        "broker_account_id": ticket.broker_account.broker_account_id,
        "symbol": ticket.symbol,
        "side": ticket.side,
        "quantity": str(ticket.quantity),
        "order_type": ticket.order_type,
        "limit_price": str(ticket.limit_price or 0),
        "stop_price": str(ticket.stop_price or 0) if ticket.stop_price is not None else None,
        "time_in_force": ticket.time_in_force,
        "estimated_notional": str(ticket.estimated_notional or 0),
        "native_notional": str(ticket.native_notional or 0),
        "currency": ticket.currency,
        "base_currency": ticket.base_currency,
        "fx_rate": str(ticket.fx_rate or 0),
        "fx_source_snapshot_id": ticket.fx_source_snapshot_id,
        "fx_as_of": ticket.fx_as_of.isoformat() if ticket.fx_as_of else "",
        "status": ticket.status,
        "current_state": ticket.current_state,
        "payload_hash": ticket.payload_hash,
        "user_visible_summary": ticket.user_visible_summary,
        "created_by": ticket.created_by,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "canonical_order": (ticket.payload or {}).get("canonical_order", {}) if isinstance(ticket.payload, dict) else {},
        "checks": [
            {"check_type": check.check_type, "decision": check.decision, "reasons": check.reasons, "created_at": check.created_at.isoformat()}
            for check in ticket.check_runs.all()
        ],
    }
    if include_related:
        record.update(
            {
                "events": [
                    {
                        "event_type": event.event_type,
                        "actor": event.actor,
                        "payload": _public_order_event_payload(event.payload),
                        "created_at": event.created_at.isoformat(),
                    }
                    for event in ticket.events.all()
                ],
                "fills": [
                    {"fill_id": fill.fill_id, "broker_order_id": fill.broker_order_id, "quantity": float(fill.quantity), "price": float(fill.price), "currency": fill.currency, "filled_at": fill.filled_at.isoformat()}
                    for fill in ticket.fills.all()
                ],
                "broker_orders": [
                    {"broker_order_id": broker_order.broker_order_id, "broker_status": broker_order.broker_status, "last_seen_at": broker_order.last_seen_at.isoformat() if broker_order.last_seen_at else ""}
                    for broker_order in ticket.broker_orders.all()
                ],
            }
        )
    return record


def normalize_order_ticket_fields(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_natural_language_order(str(args.get("natural_language") or ""))
    fields = {**parsed, **{key: value for key, value in args.items() if value not in (None, "")}}
    if fields.pop("currency_ambiguous", False) and args.get("currency") in (None, ""):
        raise ValueError("currency symbols are ambiguous; provide a three-letter currency code")
    missing = [field for field in ["symbol", "side", "quantity", "limit_price"] if fields.get(field) in (None, "")]
    if missing:
        raise ValueError(f"order ticket requires: {', '.join(missing)}")
    fields["symbol"] = str(fields["symbol"]).upper()
    fields["side"] = str(fields["side"]).lower()
    fields["quantity"] = Decimal(str(fields["quantity"]))
    fields["limit_price"] = Decimal(str(fields["limit_price"]))
    if fields["side"] not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if fields["quantity"] <= 0:
        raise ValueError("quantity must be positive")
    if fields["limit_price"] <= 0:
        raise ValueError("limit_price must be positive")
    fields["currency"] = normalize_currency_code(fields.get("currency") or base_currency_for_workspace(root))
    fields["base_currency"] = normalize_currency_code(
        fields.get("base_currency") or base_currency_for_workspace(root),
        "base_currency",
    )
    fields.setdefault("order_type", "limit")
    fields.setdefault("time_in_force", "day")
    fields.setdefault("created_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    fields.setdefault("created_by", args.get("principal_id") or "portfolio-manager")
    return fields


def _money_contract_from_fields(root: Path, fields: dict[str, Any]) -> dict[str, Any]:
    currency = normalize_currency_code(fields.get("currency"))
    base_currency = normalize_currency_code(fields.get("base_currency"), "base_currency")
    configured_base_currency = base_currency_for_workspace(root)
    if base_currency != configured_base_currency:
        raise ValueError(f"base_currency must match the paper account scope ({configured_base_currency})")
    native_notional = (Decimal(str(fields["quantity"])) * Decimal(str(fields["limit_price"]))).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_EVEN,
    )
    created_at = _parse_datetime(fields.get("created_at")) or datetime.now(timezone.utc)
    if currency == base_currency:
        fx_rate = Decimal("1")
        fx_source_snapshot_id = f"native-{base_currency}"
        fx_as_of = created_at
    else:
        try:
            fx_rate = Decimal(str(fields.get("fx_rate")))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("foreign-currency orders require a positive fx_rate") from exc
        if not fx_rate.is_finite() or fx_rate <= 0:
            raise ValueError("foreign-currency orders require a positive fx_rate")
        fx_source_snapshot_id = str(fields.get("fx_source_snapshot_id") or "").strip()
        fx_as_of = _parse_datetime(fields.get("fx_as_of"))
        if not fx_source_snapshot_id or fx_as_of is None or not _has_explicit_timezone(fields.get("fx_as_of")):
            raise ValueError("foreign-currency orders require fx_source_snapshot_id and timezone-aware fx_as_of")
        snapshot_path = safe_workspace_path(
            root,
            Path("trading/research/source-snapshots") / f"{sanitize_id(fx_source_snapshot_id)}.json",
            allowed_roots=(Path("trading/research/source-snapshots"),),
        )
        snapshot = read_json(snapshot_path, {})
        if not snapshot_path.exists() or not isinstance(snapshot, dict) or not snapshot:
            raise ValueError(f"FX source snapshot not found: {fx_source_snapshot_id}")
        if str(snapshot.get("snapshot_id") or fx_source_snapshot_id) != fx_source_snapshot_id:
            raise ValueError("FX source snapshot identity mismatch")
        known_at = _parse_datetime(snapshot.get("known_at"))
        if known_at is None or not _has_explicit_timezone(snapshot.get("known_at")) or known_at > fx_as_of:
            raise ValueError("FX source snapshot known_at is missing or after fx_as_of")
        max_age = int(os.environ.get("TRADINGCODEX_MAX_FX_AGE_SECONDS", "86400"))
        age_seconds = (created_at - fx_as_of).total_seconds()
        if age_seconds < -300 or age_seconds > max_age:
            raise ValueError("FX quote is future-dated or stale")
    base_notional = quantize_money(native_notional * fx_rate, base_currency)
    if base_notional <= 0:
        raise ValueError("base-currency notional must be positive")
    return {
        "native_currency": currency,
        "native_notional": native_notional,
        "base_currency": base_currency,
        "base_notional": base_notional,
        "fx_rate": fx_rate,
        "fx_source_snapshot_id": fx_source_snapshot_id,
        "fx_as_of": fx_as_of,
    }


def _has_explicit_timezone(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", text))


def parse_natural_language_order(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    normalized = text.replace(",", " ")
    side = ""
    if re.search(r"\bbuy\b", normalized, flags=re.I):
        side = "buy"
    elif re.search(r"\bsell\b", normalized, flags=re.I):
        side = "sell"
    symbol = ""
    symbol_match = re.search(r"\b([A-Z]{1,6}(?:\.[A-Z]{1,3})?|\d{5,6})\b", normalized)
    if symbol_match:
        symbol = symbol_match.group(1).upper()
    quantity = ""
    quantity_match = re.search(r"(\d+(?:\.\d+)?)\s*shares?", normalized, flags=re.I)
    if not quantity_match:
        quantity_match = re.search(r"(?:buy|sell)\s+(\d+(?:\.\d+)?)", normalized, flags=re.I)
    if quantity_match:
        quantity = quantity_match.group(1)
    limit_price = ""
    price_match = re.search(r"(?:limit|@|at|price)\s*\$?\s*(\d+(?:\.\d+)?)", normalized, flags=re.I)
    if not price_match:
        price_match = re.search(r"(\d+(?:\.\d+)?)\s*[A-Z]{3}\b", normalized, flags=re.I)
    if price_match:
        limit_price = price_match.group(1)
    currency_match = re.search(r"\d+(?:\.\d+)?\s*([A-Z]{3})\b", normalized, flags=re.I)
    currency = currency_match.group(1).upper() if currency_match else ""
    return {
        key: value
        for key, value in {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "limit_price": limit_price,
            "currency": currency,
            "currency_ambiguous": not currency and any(symbol in normalized for symbol in "$€£"),
            "natural_language": text,
        }.items()
        if value
    }


def canonical_order_from_fields(fields: dict[str, Any]) -> dict[str, Any]:
    created_at = str(fields.get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    order = {
        "ticket_id": str(fields["ticket_id"]),
        "symbol": str(fields["symbol"]).upper(),
        "side": str(fields["side"]).lower(),
        "quantity": str(fields["quantity"]),
        "limit_price": str(fields["limit_price"]),
        "currency": normalize_currency_code(fields.get("currency")),
        "broker_id": str(fields["broker_id"]),
        "estimated_notional": str(fields.get("estimated_notional") or (Decimal(str(fields["quantity"])) * Decimal(str(fields["limit_price"])))),
        "native_notional": str(fields.get("native_notional") or (Decimal(str(fields["quantity"])) * Decimal(str(fields["limit_price"])))),
        "base_currency": normalize_currency_code(fields.get("base_currency") or DEFAULT_BASE_CURRENCY, "base_currency"),
        "fx_rate": str(fields.get("fx_rate") or ("1" if normalize_currency_code(fields.get("currency")) == normalize_currency_code(fields.get("base_currency") or DEFAULT_BASE_CURRENCY) else "")),
        "fx_source_snapshot_id": str(fields.get("fx_source_snapshot_id") or ""),
        "fx_as_of": str(fields.get("fx_as_of") or ""),
        "created_by": str(fields.get("created_by") or "portfolio-manager"),
        "created_at": created_at,
        "portfolio_id": str(fields["portfolio_id"]),
        "account_id": str(fields["account_id"]),
        "strategy_id": str(fields["strategy_id"]),
        "broker_account_id": str(fields["broker_account_id"]),
        "order_type": str(fields.get("order_type") or "limit"),
        "time_in_force": str(fields.get("time_in_force") or "day"),
        "money": dict(fields.get("money") or {}),
    }
    from tradingcodex_service.application.brokers import canonical_order_from_order

    order["canonical_order"] = canonical_order_from_order({**fields, **order})
    return order


def _resolve_ticket_broker_connection(root: Path, fields: dict[str, Any]) -> Any:
    from apps.integrations.models import BrokerConnection
    from tradingcodex_service.application.brokers import ensure_paper_broker_connection

    broker_id = fields.get("broker_id") or "paper-trading"
    if broker_id == "paper-trading":
        return ensure_paper_broker_connection(root)
    connection = BrokerConnection.objects.filter(broker_id=broker_id).first()
    if connection is None:
        raise ValueError(f"unknown broker connection: {broker_id}")
    return connection


def _resolve_ticket_broker_account(connection: Any, fields: dict[str, Any]) -> Any:
    account_id = fields.get("broker_account_id")
    if account_id:
        account = connection.accounts.filter(broker_account_id=account_id).first()
    else:
        account = connection.accounts.order_by("broker_account_id").first()
    if account is None:
        raise ValueError(f"broker connection has no discovered account: {connection.broker_id}")
    return account


def _ticket_summary(order: dict[str, Any]) -> str:
    return f"{order['side'].upper()} {order['quantity']} {order['symbol']} @ {order['limit_price']} {order['currency']}"


def _schema_reasons(order: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if order.get(ORDER_RESOLUTION_ERROR_FIELD):
        reasons.append(str(order[ORDER_RESOLUTION_ERROR_FIELD]))
    for field in [
        "ticket_id",
        "symbol",
        "side",
        "quantity",
        "limit_price",
        "currency",
        "broker_id",
        "broker_account_id",
        "estimated_notional",
        "native_notional",
        "base_currency",
        "fx_rate",
        "fx_source_snapshot_id",
        "fx_as_of",
        "portfolio_id",
        "account_id",
        "strategy_id",
        "order_type",
        "time_in_force",
        "created_by",
        "created_at",
    ]:
        if order.get(field) in (None, ""):
            reasons.append(f"missing {field}")
    for field in ("canonical_order", "money"):
        if not isinstance(order.get(field), dict) or not order[field]:
            reasons.append(f"missing {field}")
    if order.get("side") not in {"buy", "sell"}:
        reasons.append("side must be buy or sell")
    _validate_positive(order.get("quantity"), "quantity", reasons)
    _validate_positive(order.get("limit_price"), "limit_price", reasons)
    _validate_positive(order.get("estimated_notional"), "estimated_notional", reasons)
    return reasons


def _check_result(check_type: str, passed: bool, reasons: list[str], payload: dict[str, Any] | None = None, decision: str | None = None) -> dict[str, Any]:
    if decision is None:
        decision = "pass" if passed else "fail"
    return {"check_type": check_type, "decision": decision, "reasons": reasons, "payload": payload or {}}


def _record_ticket_submit_result(
    root: Path,
    order: dict[str, Any],
    adapter_result: dict[str, Any],
    principal_id: str,
) -> dict[str, Any]:
    ensure_runtime_database(root)
    parsed = _validate_adapter_order_result(adapter_result, operation="order submission")
    adapter_result = _adapter_order_result_projection(adapter_result, parsed)
    from apps.orders.models import BrokerOrder, Fill, OrderTicket
    from apps.portfolio.models import PortfolioLedgerEvent
    broker_order_id = adapter_result["broker_order_id"]
    submitted_at = parsed["submitted_at"]
    filled_quantity = parsed["filled_quantity"]
    fill_price = parsed["average_price"]
    with transaction.atomic():
        ticket = get_order_ticket_model(root, {"ticket_id": order.get("ticket_id")})
        ticket = OrderTicket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.current_state == "RESERVED":
            transition_order_ticket(ticket, "SUBMITTED", principal_id, adapter_result)
        elif ticket.current_state not in {
            "SUBMITTED",
            "ACKED",
            "PARTIALLY_FILLED",
            "FILLED",
            "REJECTED",
            "CANCELED",
            "EXPIRED",
            "FAILED",
            "NEEDS_REVIEW",
        }:
            raise ValueError(f"broker result cannot finalize order ticket in state: {ticket.current_state}")
        existing = BrokerOrder.objects.filter(ticket=ticket, broker_order_id=broker_order_id).first()
        metadata = {**(existing.metadata if existing and isinstance(existing.metadata, dict) else {}), **adapter_result}
        broker_order, _ = BrokerOrder.objects.update_or_create(
            ticket=ticket,
            broker_order_id=broker_order_id,
            defaults={
                "broker_status": adapter_result["status"],
                "submitted_at": submitted_at,
                "last_seen_at": django_timezone.now(),
                "raw_status_payload_hash": stable_hash(adapter_result),
                "metadata": metadata,
            },
        )
        fill = None
        if filled_quantity is not None and fill_price is not None:
            raw_fill = {
                "broker_order_id": broker_order_id,
                "quantity": str(filled_quantity),
                "price": str(fill_price),
                "adapter_result": adapter_result,
            }
            fill, created = Fill.objects.get_or_create(
                ticket=ticket,
                broker_order_id=broker_order_id,
                fill_id=adapter_result.get("fill_id") or stable_hash(raw_fill)[:24],
                defaults={
                    "quantity": filled_quantity,
                    "price": fill_price,
                    "fee": parsed["fee"],
                    "currency": normalize_currency_code(order.get("currency", DEFAULT_BASE_CURRENCY)),
                    "filled_at": submitted_at,
                    "raw_payload_hash": stable_hash(raw_fill),
                },
            )
            if created:
                record_order_event(ticket, "fill", principal_id, {"fill_id": fill.fill_id, "quantity": str(filled_quantity), "price": str(fill_price)})
                PortfolioLedgerEvent.objects.create(
                    event_type="fill",
                    broker_connection=ticket.broker_connection,
                    broker_account=ticket.broker_account,
                    portfolio_id=ticket.portfolio_id,
                    account_id=ticket.account_id,
                    strategy_id=ticket.strategy_id,
                    instrument_id=ticket.instrument_id or ticket.symbol,
                    symbol=ticket.symbol,
                    quantity=filled_quantity,
                    amount=filled_quantity * fill_price,
                    price=fill_price,
                    currency=normalize_currency_code(order.get("currency", DEFAULT_BASE_CURRENCY)),
                    event_at=submitted_at,
                    source_payload_hash=stable_hash(raw_fill),
                    raw_payload_ref=f"fill:{fill.fill_id}",
                    metadata=raw_fill,
                )
        target_state = ADAPTER_ORDER_STATE_TARGETS[adapter_result["status"].lower()]
        if ticket.current_state == "SUBMITTED" and target_state in {"ACKED", "PARTIALLY_FILLED", "FILLED"}:
            transition_order_ticket(
                ticket,
                "ACKED",
                principal_id,
                {"broker_order_id": broker_order_id, "broker_status": adapter_result["status"]},
            )
        if ticket.current_state != target_state:
            transition_order_ticket(
                ticket,
                target_state,
                principal_id,
                {
                    "broker_order_id": broker_order_id,
                    "broker_status": adapter_result["status"],
                    **({"fill_id": fill.fill_id} if fill is not None else {}),
                },
            )
        ticket.refresh_from_db()
    return {
        "ticket": ticket,
        "broker_order": broker_order,
        "fill_recorded": filled_quantity is not None,
    }


def _validate_adapter_order_result(
    value: Any,
    *,
    operation: str,
    expected_broker_order_id: str = "",
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{operation} result must be an object")
    broker_order_id = value.get("broker_order_id")
    if not isinstance(broker_order_id, str) or not broker_order_id.strip() or broker_order_id != broker_order_id.strip():
        raise ValueError(f"{operation} broker_order_id must be a non-empty string")
    if expected_broker_order_id and broker_order_id != expected_broker_order_id:
        raise ValueError(f"{operation} broker_order_id does not match the requested order")
    status = value.get("status")
    if not isinstance(status, str) or status != status.strip().lower() or status not in ADAPTER_ORDER_STATE_TARGETS:
        raise ValueError(f"{operation} status is not a canonical v1 broker status")
    if status == "unknown":
        raise ValueError(f"{operation} returned an uncertain broker status")
    submitted_at = _adapter_timestamp(value.get("submitted_at"), f"{operation} submitted_at")
    filled_quantity = _adapter_decimal(value.get("filled_quantity"), f"{operation} filled_quantity", optional=True)
    average_price = _adapter_decimal(value.get("average_price"), f"{operation} average_price", optional=True)
    if (filled_quantity is None) != (average_price is None):
        raise ValueError(f"{operation} filled_quantity and average_price must be provided together")
    if status in {"filled", "partially_filled"} and filled_quantity is None:
        raise ValueError(f"{operation} {status} status requires fill quantity and price")
    if status not in {"filled", "partially_filled"} and filled_quantity is not None:
        raise ValueError(f"{operation} fill quantity is incompatible with status {status}")
    fill_id = value.get("fill_id")
    if fill_id is not None and (not isinstance(fill_id, str) or not fill_id.strip() or fill_id != fill_id.strip()):
        raise ValueError(f"{operation} fill_id must be a non-empty string")
    return {
        "submitted_at": submitted_at,
        "filled_quantity": filled_quantity,
        "average_price": average_price,
        "fee": _adapter_decimal(value.get("fee", 0), f"{operation} fee", positive=False),
    }


def _canonical_adapter_order_result(
    value: Any,
    *,
    operation: str,
    expected_broker_order_id: str = "",
) -> dict[str, Any]:
    parsed = _validate_adapter_order_result(
        value,
        operation=operation,
        expected_broker_order_id=expected_broker_order_id,
    )
    return _adapter_order_result_projection(value, parsed)


def _adapter_order_result_projection(value: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "broker_order_id": _safe_provider_identifier(value["broker_order_id"], required=True),
        "status": value["status"],
        "submitted_at": parsed["submitted_at"].isoformat().replace("+00:00", "Z"),
        "fee": str(parsed["fee"]),
    }
    if parsed["filled_quantity"] is not None:
        projection["filled_quantity"] = str(parsed["filled_quantity"])
        projection["average_price"] = str(parsed["average_price"])
    fill_id = value.get("fill_id")
    if fill_id is not None:
        projection["fill_id"] = _safe_provider_identifier(fill_id, required=True)
    return projection


def _canonical_adapter_cancel_result(value: Any, expected_broker_order_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("broker cancel result must be an object")
    if value.get("broker_order_id") != expected_broker_order_id:
        raise ValueError("broker cancel result broker_order_id does not match the requested order")
    if value.get("status") != "canceled":
        raise ValueError("broker cancel result status must be canceled")
    canceled_at = _adapter_timestamp(value.get("canceled_at"), "broker cancel canceled_at")
    return {
        "broker_order_id": _safe_provider_identifier(expected_broker_order_id, required=True),
        "status": "canceled",
        "canceled_at": canceled_at.isoformat().replace("+00:00", "Z"),
    }


def _safe_provider_identifier(value: Any, *, required: bool = False) -> str:
    identifier = str(value or "")
    valid = (
        bool(identifier)
        and identifier == identifier.strip()
        and len(identifier) <= 160
        and not any(character.isspace() or unicodedata.category(character).startswith("C") for character in identifier)
    )
    if not valid:
        if required:
            raise ValueError("provider identifier must be one printable token of at most 160 characters")
        return ""
    return identifier


def _public_order_event_payload(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    allowed = {
        "approval_receipt_id",
        "broker_order_id",
        "broker_status",
        "fill_id",
        "from",
        "idempotency_key",
        "mode",
        "operation",
        "payload_hash",
        "quantity",
        "price",
        "status",
        "ticket_id",
        "to",
    }
    projected: dict[str, Any] = {}
    for key in sorted(allowed.intersection(payload)):
        item = payload[key]
        if isinstance(item, bool) or item is None:
            projected[key] = item
        elif isinstance(item, (str, int, float, Decimal)):
            projected[key] = str(item)[:500]
    return projected


def _adapter_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be an ISO-8601 string with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 string with timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _adapter_decimal(value: Any, field: str, *, optional: bool = False, positive: bool = True) -> Decimal | None:
    if value in (None, ""):
        if optional:
            return None
        raise ValueError(f"{field} is required")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        comparison = "positive" if positive else "non-negative"
        raise ValueError(f"{field} must be {comparison}")
    return number


def _sync_ticket_account(root: Path, ticket: Any, principal_id: str) -> dict[str, Any]:
    from tradingcodex_service.application.brokers import sync_broker_account

    return sync_broker_account(
        root,
        {
            "broker_id": ticket.broker_connection.broker_id,
            "broker_account_id": ticket.broker_account.broker_account_id,
            "principal_id": principal_id,
        },
    )


def _number_or_none(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def submit_with_adapter(root: Path, order: dict[str, Any]) -> dict[str, Any]:
    broker_id = order.get("broker_id")
    if broker_id == "paper-trading":
        return submit_paper_order(root, order)
    ensure_runtime_database(root)
    from apps.integrations.models import BrokerConnection
    from tradingcodex_service.application.brokers import adapter_for_connection, broker_connection_provider_review_reasons

    connection = BrokerConnection.objects.filter(broker_id=broker_id).first()
    if connection is None:
        raise ValueError(f"Adapter is not enabled: {broker_id}")
    if connection.status != "trading_enabled":
        raise ValueError(f"broker connection is not trading_enabled: {broker_id}")
    source_reasons = broker_connection_provider_review_reasons(connection, root)
    if source_reasons:
        raise ValueError(source_reasons[0])
    order = dict(order)
    order.setdefault("client_order_id", _deterministic_client_order_id(order))
    return adapter_for_connection(connection, root).submit_order(order)


def _adapter_preflight_reasons(root: Path, order: dict[str, Any], args: dict[str, Any] | None = None) -> list[str]:
    args = args or {}
    broker_id = order.get("broker_id")
    if broker_id == "paper-trading":
        return []
    ensure_runtime_database(root)
    from apps.integrations.models import BrokerConnection
    from tradingcodex_service.application.brokers import (
        _reconcile_validation_execution_status,
        adapter_for_connection,
        broker_adapter_health,
        broker_connection_provider_review_reasons,
    )

    connection = BrokerConnection.objects.filter(broker_id=broker_id).first()
    if connection is None:
        return [f"Adapter is not enabled: {broker_id}"]
    if connection.status != "trading_enabled":
        return [f"broker connection is not trading_enabled: {broker_id}"]
    source_reasons = broker_connection_provider_review_reasons(connection, root)
    if source_reasons:
        return source_reasons
    metadata = connection.metadata if isinstance(connection.metadata, dict) else {}
    profile = metadata.get("capability_profile") if isinstance(metadata.get("capability_profile"), dict) else {}
    if profile.get("execution_posture") == "live_broker":
        reasons: list[str] = []
        if os.environ.get("TRADINGCODEX_ENABLE_LIVE_EXECUTION", "").lower() not in {"1", "true", "yes", "on"}:
            reasons.append("TRADINGCODEX_ENABLE_LIVE_EXECUTION=1 is required for live broker submission")
        expected = _expected_live_confirmation(order)
        if str(args.get("live_confirmation") or "") != expected:
            reasons.append(f"live confirmation required: {expected}")
        if "order.submit.live" not in set(connection.enabled_trade_scopes or []):
            reasons.append(f"broker connection lacks order.submit.live scope: {broker_id}")
        if reasons:
            return reasons
    health = broker_adapter_health(adapter_for_connection(connection, root))
    _reconcile_validation_execution_status(connection, health, root)
    if health.status != "ok":
        message = f": {health.message}" if health.message else ""
        return [f"broker health is {health.status}{message}"]
    return []


def _deterministic_client_order_id(order: dict[str, Any]) -> str:
    source = {
        "ticket_id": order.get("ticket_id"),
        "broker_id": order.get("broker_id"),
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "quantity": str(order.get("quantity")),
    }
    return ("tcx-" + stable_hash(source)[:28])[:32]


def _expected_live_confirmation(order: dict[str, Any]) -> str:
    return "LIVE:{ticket}:{broker}:{symbol}:{side}:{quantity}".format(
        ticket=order.get("ticket_id") or "",
        broker=order.get("broker_id") or "",
        symbol=order.get("symbol") or "",
        side=order.get("side") or "",
        quantity=order.get("quantity") or "",
    )


def _expected_live_cancel_confirmation(ticket: Any, broker_order: Any) -> str:
    broker_id = ticket.broker_connection.broker_id if ticket.broker_connection else ""
    return f"CANCEL:{ticket.ticket_id}:{broker_id}:{broker_order.broker_order_id}"


def resolve_order_ticket_payload(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    if isinstance(args.get("order"), dict):
        return args["order"]
    ticket_id = args.get("ticket_id")
    if ticket_id:
        try:
            return order_payload_from_ticket(get_order_ticket_model(root, {**args, "ticket_id": str(ticket_id)}))
        except ValueError as exc:
            return {"ticket_id": str(ticket_id), ORDER_RESOLUTION_ERROR_FIELD: str(exc)}
    return {}


def resolve_canonical_approval_receipt(
    root: Path,
    args: dict[str, Any],
    order: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_runtime_database(root)
    from apps.orders.models import ApprovalReceipt

    queryset = ApprovalReceipt.objects.select_related("order_ticket")
    receipt_id = args.get("approval_receipt_id")
    if not receipt_id:
        return {}
    stored = queryset.filter(approval_receipt_id=str(receipt_id)).first()
    if stored is None or stored.order_ticket.ticket_id != stored.order_ticket_id:
        return {}
    return approval_receipt_from_model(stored)


def approval_receipt_from_model(stored: Any) -> dict[str, Any]:
    payload = stored.payload if isinstance(stored.payload, dict) else {}
    return {
        "approval_receipt_id": stored.approval_receipt_id,
        "ticket_id": stored.order_ticket_id,
        "approved_by": stored.approved_by,
        "valid": stored.valid and stored.superseded_at is None,
        "created_at": stored.created_at.isoformat(),
        "expires_at": stored.expires_at.isoformat(),
        "exact_order_hash": stored.exact_order_hash,
        "broker_id": stored.broker_id,
        "broker_account_id": stored.broker_account_id,
        "max_notional": str(stored.max_notional) if stored.max_notional is not None else None,
        "max_price": str(stored.max_price) if stored.max_price is not None else None,
        "max_slippage_bps": stored.max_slippage_bps,
        "approved_order_type": stored.approved_order_type,
        "approved_time_in_force": stored.approved_time_in_force,
        "valid_until": stored.valid_until.isoformat() if stored.valid_until else None,
        "quote_as_of_requirement": stored.quote_as_of_requirement,
        "consumed_at": stored.consumed_at.isoformat() if stored.consumed_at else None,
        "superseded_at": stored.superseded_at.isoformat() if stored.superseded_at else None,
        "policy_decision": payload.get("policy_decision", {}),
    }


def order_ticket_payload_conflict(root: Path, order: dict[str, Any]) -> str:
    ticket_id = order.get("ticket_id")
    if not ticket_id:
        return ""
    try:
        ensure_runtime_database(root)
        from apps.orders.models import OrderTicket

        ticket = OrderTicket.objects.select_related("broker_connection", "broker_account").filter(ticket_id=ticket_id).first()
        if ticket is None:
            return ""
        stored_order = order_payload_from_ticket(ticket)
        if stable_hash(_order_conflict_payload(stored_order)) != stable_hash(_order_conflict_payload(order)):
            return "order ticket id already exists with a different payload"
    except Exception as exc:
        return f"order ticket DB conflict check unavailable: {exc}"
    return ""


def _order_conflict_payload(order: dict[str, Any]) -> dict[str, Any]:
    quantity = _number_or_none(order.get("quantity"))
    limit_price = _number_or_none(order.get("limit_price"))
    notional = _number_or_none(order.get("estimated_notional"))
    return {
        "ticket_id": str(order.get("ticket_id") or ""),
        "symbol": str(order.get("symbol") or "").upper(),
        "side": str(order.get("side") or "").lower(),
        "quantity": str(quantity) if quantity is not None else "",
        "limit_price": str(limit_price) if limit_price is not None else "",
        "currency": normalize_currency_code(order.get("currency")),
        "broker_id": str(order.get("broker_id") or ""),
        "estimated_notional": str(notional) if notional is not None else "",
        "portfolio_id": str(order.get("portfolio_id") or ""),
        "account_id": str(order.get("account_id") or ""),
        "strategy_id": str(order.get("strategy_id") or ""),
        "order_type": str(order.get("order_type") or "limit"),
        "time_in_force": str(order.get("time_in_force") or "day"),
    }


def persist_approval_receipt(root: Path, receipt: dict[str, Any]) -> None:
    required = [
        "approval_receipt_id",
        "ticket_id",
        "approved_by",
        "valid",
        "expires_at",
        "exact_order_hash",
        "broker_id",
        "broker_account_id",
        "max_notional",
        "max_price",
        "approved_order_type",
        "approved_time_in_force",
        "valid_until",
    ]
    missing = [field for field in required if receipt.get(field) in (None, "")]
    if missing:
        raise ValueError(f"approval receipt requires: {', '.join(missing)}")
    ensure_runtime_database(root)
    from apps.orders.models import ApprovalReceipt, OrderTicket

    with transaction.atomic():
        ticket = OrderTicket.objects.select_for_update().get(ticket_id=receipt["ticket_id"])
        existing = ApprovalReceipt.objects.filter(approval_receipt_id=receipt["approval_receipt_id"]).first()
        if existing is not None:
            if approval_receipt_from_model(existing)["exact_order_hash"] != receipt["exact_order_hash"]:
                raise ValueError("approval receipt id already exists with different approval content")
            return
        now = django_timezone.now()
        ApprovalReceipt.objects.filter(order_ticket=ticket, valid=True, consumed_at__isnull=True).update(
            valid=False,
            superseded_at=now,
        )
        ApprovalReceipt.objects.create(
            approval_receipt_id=receipt["approval_receipt_id"],
            order_ticket=ticket,
            approved_by=receipt["approved_by"],
            valid=bool(receipt["valid"]),
            expires_at=_parse_datetime(receipt["expires_at"]) or datetime.now(timezone.utc),
            exact_order_hash=receipt.get("exact_order_hash", ""),
            broker_id=receipt["broker_id"],
            broker_account_id=receipt.get("broker_account_id", ""),
            max_notional=receipt.get("max_notional") or None,
            max_price=receipt.get("max_price") or None,
            max_slippage_bps=receipt.get("max_slippage_bps") or None,
            approved_order_type=receipt.get("approved_order_type", ""),
            approved_time_in_force=receipt.get("approved_time_in_force", ""),
            valid_until=_parse_datetime(receipt.get("valid_until")) if receipt.get("valid_until") else None,
            quote_as_of_requirement=receipt.get("quote_as_of_requirement", ""),
            workspace_context=workspace_context_payload(root),
            payload=receipt,
        )
