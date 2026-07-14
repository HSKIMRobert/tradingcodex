from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import append_jsonl, now_iso, safe_workspace_path, stable_hash
from tradingcodex_service.application.runtime import ensure_runtime_database, workspace_context_payload
from tradingcodex_service.log_safety import redact_log_text


AUDIT_EVENT_FIELDS = frozenset({"type", "resource", "decision", "payload"})


def canonical_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("audit event must be an object")
    unknown = sorted(set(event) - AUDIT_EVENT_FIELDS)
    if unknown:
        raise ValueError("unsupported audit event field(s): " + ", ".join(unknown))
    event_type = event.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("audit event type is required")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("audit event payload must be an object")
    resource = event.get("resource", "")
    decision = event.get("decision", "recorded")
    if not isinstance(resource, str):
        raise ValueError("audit event resource must be a string")
    if not isinstance(decision, str) or not decision.strip():
        raise ValueError("audit event decision must be a non-empty string")
    return {
        "type": event_type.strip(),
        "resource": resource.strip(),
        "decision": decision.strip(),
        "payload": payload,
    }


def write_audit_event(workspace_root: Path | str, event: dict[str, Any], principal_id: str = "system", source: str = "service") -> dict[str, Any]:
    root = Path(workspace_root)
    safe_event = canonical_audit_event(_redact_audit_event(event))
    audit_event = write_audit_event_required(root, principal_id, source, safe_event)
    export_written = True
    try:
        path = safe_workspace_path(root, "trading/audit/tradingcodex-mcp.jsonl", allowed_roots=(Path("trading/audit"),))
        append_jsonl(path, {"ts": now_iso(), "event": safe_event})
    except Exception:
        export_written = False
    return {
        "written": True,
        "db_canonical": True,
        "audit_event_id": audit_event.pk,
        "export_written": export_written,
        "export_path": "trading/audit/tradingcodex-mcp.jsonl",
        "workspace_context": workspace_context_payload(root),
    }


def write_audit_event_required(
    workspace_root: Path | str | None,
    principal_id: str,
    source: str,
    event: dict[str, Any],
) -> Any:
    if workspace_root is not None:
        ensure_runtime_database(workspace_root)
    from apps.audit.models import AuditEvent

    event = canonical_audit_event(_redact_audit_event(event))
    return AuditEvent.objects.create(
        actor_principal=principal_id,
        source=source,
        action=event["type"],
        resource=event["resource"],
        decision=event["decision"],
        request_hash=stable_hash(event),
        result_hash=stable_hash(event["payload"]),
        workspace_context=workspace_context_payload(workspace_root),
        payload=event,
    )


def _redact_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    from apps.mcp.services import redact_sensitive_data

    return _redact_audit_strings(redact_sensitive_data(event))


def _redact_audit_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_audit_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_audit_strings(item) for item in value]
    return redact_log_text(value) if isinstance(value, str) else value


def write_audit_event_if_available(
    workspace_root: Path | str | None,
    principal_id: str,
    source: str,
    event: dict[str, Any],
) -> None:
    try:
        if workspace_root is not None:
            ensure_runtime_database(workspace_root)
        write_audit_event_required(workspace_root, principal_id, source, event)
    except Exception:
        return


def write_policy_decision_if_available(workspace_root: Path | str | None, result: dict[str, Any]) -> None:
    try:
        if workspace_root is not None:
            ensure_runtime_database(workspace_root)
        from apps.policy.models import PolicyDecision

        PolicyDecision.objects.create(
            principal_id=result["principal_id"],
            action=result["action"],
            resource=result.get("resource") or "",
            decision=result["decision"],
            reasons=result["reasons"],
            workspace_context=workspace_context_payload(workspace_root),
        )
    except Exception:
        return
