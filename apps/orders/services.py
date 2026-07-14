from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.orders.models import ApprovalReceipt, BrokerOrder, ExecutionResult, OrderEvent, OrderTicket
from tradingcodex_service.application.audit import write_audit_event_required
from tradingcodex_service.application.common import stable_hash


@dataclass(frozen=True)
class ExecutionReservation:
    created: bool
    execution: ExecutionResult
    idempotency_key: str


def execution_idempotency_key(
    order: dict[str, Any],
    portfolio_id: str = "",
    account_id: str = "",
    strategy_id: str = "",
) -> str:
    explicit = order.get("idempotency_key")
    if explicit:
        return str(explicit)
    payload = {
        "ticket_id": order.get("ticket_id"),
        "portfolio_id": portfolio_id or order.get("portfolio_id", ""),
        "account_id": account_id or order.get("account_id", ""),
        "strategy_id": strategy_id or order.get("strategy_id", ""),
        "execution_boundary": "submit_approved_order",
    }
    return "submit:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def existing_execution_for_order(
    ticket_id: str,
    idempotency_key: str,
    portfolio_id: str,
    account_id: str,
    strategy_id: str,
) -> ExecutionResult | None:
    return (
        ExecutionResult.objects.filter(idempotency_key=idempotency_key).order_by("-created_at", "-id").first()
        or ExecutionResult.objects.filter(
            order_ticket_id=ticket_id,
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
        ).order_by("-created_at", "-id").first()
    )


def reserve_execution(
    *,
    order: dict[str, Any],
    receipt: dict[str, Any],
    adapter: str,
    portfolio_id: str,
    account_id: str,
    strategy_id: str,
    workspace_context: dict[str, Any],
    principal_id: str,
    mandate_metadata: dict[str, Any],
) -> ExecutionReservation:
    key = execution_idempotency_key(
        order,
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
    )
    payload = {
        "status": "pending",
        "intent_recorded_at": timezone.now().isoformat(),
        "ticket_id": order.get("ticket_id"),
        "approval_receipt_id": receipt.get("approval_receipt_id", ""),
        "principal_id": principal_id,
        "idempotency_key": key,
        "native_execution_mandate": dict(mandate_metadata),
    }
    try:
        with transaction.atomic():
            ticket = (
                OrderTicket.objects.select_for_update()
                .select_related("broker_connection", "broker_account")
                .get(ticket_id=order["ticket_id"])
            )
            stored_receipt = ApprovalReceipt.objects.select_for_update().get(
                approval_receipt_id=receipt["approval_receipt_id"],
                order_ticket=ticket,
            )
            existing = existing_execution_for_order(ticket.ticket_id, key, portfolio_id, account_id, strategy_id)
            if existing is not None:
                return ExecutionReservation(False, existing, key)
            now = timezone.now()
            expires_at = stored_receipt.valid_until or stored_receipt.expires_at
            if ticket.current_state != "APPROVED":
                raise ValueError(f"order ticket must be APPROVED before submission: {ticket.current_state}")
            if not stored_receipt.valid or stored_receipt.superseded_at is not None:
                raise ValueError("approval receipt is revoked or superseded")
            if expires_at <= now:
                raise ValueError("approval receipt is expired")
            if stored_receipt.consumed_at is not None:
                raise ValueError("approval receipt has already been consumed")
            from tradingcodex_service.application.orders import order_payload_from_ticket

            if stored_receipt.exact_order_hash != stable_hash(order_payload_from_ticket(ticket)):
                raise ValueError("approval receipt no longer matches the locked order ticket")
            execution = ExecutionResult.objects.create(
                order_ticket_id=order["ticket_id"],
                approval_receipt_id=receipt["approval_receipt_id"],
                adapter=adapter,
                status="pending",
                portfolio_id=portfolio_id,
                account_id=account_id,
                strategy_id=strategy_id,
                workspace_context=workspace_context,
                payload=payload,
                idempotency_key=key,
            )
            stored_receipt.consumed_at = now
            stored_receipt.save(update_fields=["consumed_at"])
            ticket.current_state = "RESERVED"
            ticket.status = "RESERVED"
            ticket.save(update_fields=["current_state", "status", "updated_at"])
            OrderEvent.objects.create(
                ticket=ticket,
                event_type="reserved",
                actor=principal_id,
                payload=payload,
                payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest(),
            )
            write_audit_event_required(
                workspace_context.get("path"),
                principal_id,
                "execution",
                {
                    "type": "execution.intent",
                    "resource": str(order.get("ticket_id") or ""),
                    "decision": "reserved",
                    "payload": payload,
                },
            )
    except IntegrityError:
        execution = existing_execution_for_order(str(order.get("ticket_id", "")), key, portfolio_id, account_id, strategy_id)
        if execution is None:
            raise
        return ExecutionReservation(False, execution, key)
    return ExecutionReservation(True, execution, key)


def mark_provider_invoked(execution: ExecutionResult) -> None:
    execution.provider_invoked_at = timezone.now()
    execution.save(update_fields=["provider_invoked_at"])


def finalize_execution_reservation(
    execution: ExecutionResult,
    result: dict[str, Any],
    *,
    principal_id: str = "system",
) -> None:
    if not isinstance(result, dict):
        raise ValueError("execution result must be an object")
    status = result.get("status")
    if not isinstance(status, str) or not status.strip():
        raise ValueError("execution result status is required")
    with transaction.atomic():
        execution = ExecutionResult.objects.select_for_update().get(pk=execution.pk)
        execution.status = status
        execution.adapter = str(result.get("adapter") or execution.adapter)
        execution.payload = result
        execution.finalized_at = timezone.now()
        execution.save(update_fields=["status", "adapter", "payload", "finalized_at"])
        write_audit_event_required(
            (execution.workspace_context or {}).get("path"),
            principal_id,
            "execution",
            {
                "type": "execution.finalized",
                "resource": execution.order_ticket_id,
                "decision": status,
                "payload": result,
            },
        )


def recover_uncertain_execution(
    execution: ExecutionResult,
    result: dict[str, Any],
    *,
    principal_id: str = "system",
) -> None:
    """Atomically persist post-provider uncertainty, ticket state, event, and audit."""
    if not isinstance(result, dict):
        raise ValueError("uncertain execution result must be an object")
    payload = dict(result)
    payload["status"] = "needs_review"
    payload["needs_review"] = True
    with transaction.atomic():
        locked_execution = (
            ExecutionResult.objects.select_for_update()
            .select_related("order_ticket")
            .get(pk=execution.pk)
        )
        ticket = OrderTicket.objects.select_for_update().get(ticket_id=locked_execution.order_ticket_id)
        locked_execution.status = "needs_review"
        locked_execution.payload = payload
        locked_execution.finalized_at = timezone.now()
        locked_execution.save(update_fields=["status", "payload", "finalized_at"])
        provider_result = payload.get("result")
        broker_order_id = provider_result.get("broker_order_id") if isinstance(provider_result, dict) else None
        if isinstance(broker_order_id, str) and broker_order_id.strip() == broker_order_id and broker_order_id:
            observed_at = timezone.now()
            BrokerOrder.objects.update_or_create(
                ticket=ticket,
                broker_order_id=broker_order_id,
                defaults={
                    "broker_status": "unknown",
                    "submitted_at": observed_at,
                    "last_seen_at": observed_at,
                    "raw_status_payload_hash": stable_hash(provider_result),
                    "metadata": provider_result,
                },
            )
        _mark_ticket_needs_review(
            ticket,
            principal_id=principal_id,
            reason=_review_reason(payload),
            payload=payload,
        )
        write_audit_event_required(
            (locked_execution.workspace_context or {}).get("path"),
            principal_id,
            "execution",
            {
                "type": "execution.needs_review",
                "resource": locked_execution.order_ticket_id,
                "decision": "needs_review",
                "payload": payload,
            },
        )


def mark_ticket_needs_review(
    ticket: OrderTicket,
    *,
    principal_id: str,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Force an explicit review state after a provider boundary was crossed."""
    if not reason.strip():
        raise ValueError("needs-review reason is required")
    with transaction.atomic():
        locked_ticket = OrderTicket.objects.select_for_update().get(pk=ticket.pk)
        _mark_ticket_needs_review(
            locked_ticket,
            principal_id=principal_id,
            reason=reason,
            payload=payload or {},
        )


def _mark_ticket_needs_review(
    ticket: OrderTicket,
    *,
    principal_id: str,
    reason: str,
    payload: dict[str, Any],
) -> None:
    previous_state = ticket.current_state
    review_payload = {
        **payload,
        "ticket_id": ticket.ticket_id,
        "from": previous_state,
        "to": "NEEDS_REVIEW",
        "reason": reason,
    }
    ticket.current_state = "NEEDS_REVIEW"
    ticket.status = "NEEDS_REVIEW"
    ticket.save(update_fields=["current_state", "status", "updated_at"])
    OrderEvent.objects.create(
        ticket=ticket,
        event_type="needs_review",
        actor=principal_id,
        payload=review_payload,
        payload_hash=stable_hash(review_payload),
    )
    write_audit_event_required(
        (ticket.workspace_context or {}).get("path"),
        principal_id,
        "service",
        {
            "type": "order_ticket.needs_review",
            "resource": ticket.ticket_id,
            "decision": "needs_review",
            "payload": review_payload,
        },
    )


def _review_reason(payload: dict[str, Any]) -> str:
    reasons = payload.get("reasons")
    if isinstance(reasons, list) and reasons and isinstance(reasons[0], str) and reasons[0].strip():
        return reasons[0].strip()
    return "provider outcome requires manual review"
