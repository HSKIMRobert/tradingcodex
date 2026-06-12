from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from apps.integrations.models import AdapterDefinition


def enable_non_live_adapters(queryset: QuerySet[AdapterDefinition], actor: str = "admin") -> int:
    count = queryset.filter(live=False).update(enabled=True)
    _audit("adapter.enabled_non_live", {"count": count}, actor)
    return count


def disable_adapters(queryset: QuerySet[AdapterDefinition], actor: str = "admin") -> int:
    count = queryset.update(enabled=False)
    _audit("adapter.disabled", {"count": count}, actor)
    return count


def disable_live_adapters(queryset: QuerySet[AdapterDefinition], actor: str = "admin") -> int:
    count = queryset.filter(live=True).update(enabled=False)
    _audit("adapter.live_disabled", {"count": count}, actor)
    return count


def _audit(action: str, payload: dict[str, Any], actor: str) -> None:
    from tradingcodex_service.application.audit import write_audit_event_if_available

    write_audit_event_if_available(None, actor, "admin", {"type": action, "payload": payload})
