from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.orders.models import ApprovalReceipt, ExecutionResult, OrderEvent, OrderTicket
from tradingcodex_service.application.audit import write_audit_event_required
from tradingcodex_service.application.common import stable_hash


@dataclass(frozen=True)
class ExecutionReservation:
    created: bool
    execution: ExecutionResult
    idempotency_key: str


def execution_idempotency_key(
    order: dict[str, Any],
    receipt: dict[str, Any] | None = None,
    portfolio_id: str = "",
    account_id: str = "",
    strategy_id: str = "",
) -> str:
    explicit = order.get("idempotency_key") or (receipt or {}).get("idempotency_key")
    if explicit:
        return str(explicit)
    payload = {
        "order_ticket_id": order.get("id"),
        "portfolio_id": portfolio_id or order.get("portfolio_id", ""),
        "account_id": account_id or order.get("account_id", ""),
        "strategy_id": strategy_id or order.get("strategy_id", ""),
        "execution_boundary": "submit_approved_order",
    }
    return "submit:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def existing_execution_for_order(
    order_id: str,
    idempotency_key: str,
    portfolio_id: str,
    account_id: str,
    strategy_id: str,
) -> ExecutionResult | None:
    return (
        ExecutionResult.objects.filter(idempotency_key=idempotency_key).order_by("-created_at", "-id").first()
        or ExecutionResult.objects.filter(
            order_ticket_id=order_id,
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
) -> ExecutionReservation:
    key = execution_idempotency_key(order, receipt, portfolio_id, account_id, strategy_id)
    payload = {
        "status": "pending",
        "intent_recorded_at": timezone.now().isoformat(),
        "order_ticket_id": order.get("id"),
        "approval_receipt_id": receipt.get("id", ""),
        "principal_id": principal_id,
        "idempotency_key": key,
    }
    try:
        with transaction.atomic():
            ticket = (
                OrderTicket.objects.select_for_update()
                .select_related("broker_connection", "broker_account")
                .get(ticket_id=order["id"])
            )
            stored_receipt = ApprovalReceipt.objects.select_for_update().get(receipt_id=receipt["id"], ticket=ticket)
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
                order_ticket_id=order["id"],
                approval_receipt_id=receipt.get("id", ""),
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
                {"type": "execution.intent", "payload": payload},
            )
    except IntegrityError:
        execution = existing_execution_for_order(str(order.get("id", "")), key, portfolio_id, account_id, strategy_id)
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
    with transaction.atomic():
        execution = ExecutionResult.objects.select_for_update().get(pk=execution.pk)
        execution.status = str(result.get("status") or "recorded")
        execution.adapter = str(result.get("adapter") or execution.adapter)
        execution.payload = result
        execution.finalized_at = timezone.now()
        execution.save(update_fields=["status", "adapter", "payload", "finalized_at"])
        write_audit_event_required(
            (execution.workspace_context or {}).get("path"),
            principal_id,
            "execution",
            {"type": "execution.finalized", "payload": result},
        )


def recover_uncertain_execution(
    execution: ExecutionResult,
    result: dict[str, Any],
) -> None:
    """Persist provider correlation data even when a post-provider projection fails."""
    payload = dict(result)
    payload["status"] = "needs_review"
    payload["needs_review"] = True
    ExecutionResult.objects.filter(pk=execution.pk).update(
        status="needs_review",
        payload=payload,
        finalized_at=timezone.now(),
    )
