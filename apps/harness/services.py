from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.harness.models import RoleSkillAssignment, SkillProposal


def set_role_skill_assignments_enabled(queryset: QuerySet[RoleSkillAssignment], enabled: bool, actor: str = "admin") -> int:
    count = queryset.update(enabled=enabled)
    _audit("role_skill_assignment.enabled" if enabled else "role_skill_assignment.disabled", {"count": count}, actor)
    return count


def approve_skill_proposals(queryset: QuerySet[SkillProposal], actor: str = "admin") -> int:
    count = queryset.update(status="approved", approved_by=actor)
    _audit("skill_proposal.approved", {"count": count}, actor)
    return count


def apply_skill_proposals(queryset: QuerySet[SkillProposal], actor: str = "admin") -> int:
    applied = 0
    for proposal in queryset.filter(status__in=["approved", "proposed"]):
        RoleSkillAssignment.objects.update_or_create(
            role=proposal.target,
            skill=proposal.skill,
            defaults={"enabled": True, "source": f"proposal:{proposal.proposal_id}"},
        )
        proposal.status = "applied"
        proposal.approved_by = proposal.approved_by or actor
        proposal.applied_at = timezone.now()
        proposal.save(update_fields=["status", "approved_by", "applied_at"])
        applied += 1
    _audit("skill_proposal.applied", {"count": applied}, actor)
    return applied


def reject_skill_proposals(queryset: QuerySet[SkillProposal], actor: str = "admin") -> int:
    count = queryset.update(status="rejected")
    _audit("skill_proposal.rejected", {"count": count}, actor)
    return count


def _audit(action: str, payload: dict[str, Any], actor: str) -> None:
    from tradingcodex_service.domain import write_audit_event_if_available

    write_audit_event_if_available(None, actor, "admin", {"type": action, "payload": payload})
