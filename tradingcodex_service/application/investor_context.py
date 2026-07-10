from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tradingcodex_service.application.common import atomic_write_text, file_hash, now_iso, safe_workspace_path, stable_hash
from tradingcodex_service.application.markdown_preview import split_markdown_frontmatter


INVESTOR_CONTEXT_PATH = Path(".tradingcodex/user/investor-context.md")
INVESTOR_CONTEXT_ROOT = INVESTOR_CONTEXT_PATH.parent
INVESTOR_CONTEXT_FIELDS = (
    "investment_objective",
    "time_horizon",
    "risk_tolerance_and_loss_capacity",
    "liquidity_needs",
    "current_holdings_and_concentrations",
    "constraints",
)
def read_investor_context(workspace_root: Path | str, *, legacy_fallback: bool = True) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    path = _path(root)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        document = split_markdown_frontmatter(text)
        if not document.frontmatter or int(document.frontmatter.get("schema_version") or 0) != 1:
            raise ValueError("investor context must have valid schema_version 1 frontmatter")
        fields = _validated_fields(document.frontmatter)
        notes = _notes(document.body)
        return _payload(
            root,
            fields,
            notes=notes,
            enabled_by_default=_boolean(document.frontmatter.get("enabled_by_default"), default=True),
            source="workspace_file",
            updated_at=str(document.frontmatter.get("updated_at") or ""),
            updated_by=str(document.frontmatter.get("updated_by") or ""),
            content_hash=str(file_hash(path) or ""),
        )
    if legacy_fallback:
        legacy = _legacy_fields(root)
        if legacy:
            return _payload(
                root,
                legacy,
                notes="",
                enabled_by_default=True,
                source="legacy_active_profile",
                updated_at="",
                updated_by="",
                content_hash=stable_hash(legacy),
            )
    return _payload(
        root,
        {},
        notes="",
        enabled_by_default=True,
        source="none",
        updated_at="",
        updated_by="",
        content_hash="",
    )


def investor_context_binding(
    workspace_root: Path | str,
    *,
    apply: bool | None = None,
    legacy_fallback: bool = True,
) -> dict[str, Any]:
    context = read_investor_context(workspace_root, legacy_fallback=legacy_fallback)
    applied = context["enabled_by_default"] if apply is None else bool(apply)
    return {
        "schema_version": 1,
        "applied": bool(applied and context["configured"]),
        "configured": context["configured"],
        "enabled_by_default": context["enabled_by_default"],
        "source": context["source"],
        "path": context["path"],
        "content_hash": context["content_hash"],
        "fields": dict(context["fields"]) if applied else {},
    }


def update_investor_context(
    workspace_root: Path | str,
    updates: dict[str, Any],
    *,
    actor: str = "user",
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    current = read_investor_context(root)
    unknown = sorted(set(updates) - {*INVESTOR_CONTEXT_FIELDS, "notes", "enabled_by_default"})
    if unknown:
        raise ValueError(f"unknown investor context field(s): {', '.join(unknown)}")
    fields = dict(current["fields"])
    for field in INVESTOR_CONTEXT_FIELDS:
        if field not in updates:
            continue
        value = updates[field]
        if value in (None, "", []):
            fields.pop(field, None)
        else:
            fields[field] = _field_value(field, value)
    notes = current["notes"] if "notes" not in updates else _optional_text(updates.get("notes"), "notes", limit=8000)
    enabled = current["enabled_by_default"] if "enabled_by_default" not in updates else _boolean(updates.get("enabled_by_default"))
    _write_context(root, fields, notes=notes, enabled=enabled, actor=actor)
    return read_investor_context(root, legacy_fallback=False)


def set_investor_context_enabled(workspace_root: Path | str, enabled: bool, *, actor: str = "user") -> dict[str, Any]:
    return update_investor_context(workspace_root, {"enabled_by_default": bool(enabled)}, actor=actor)


def clear_investor_context(workspace_root: Path | str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    _write_context(root, {}, notes="", enabled=True, actor="user")
    cleared = read_investor_context(root, legacy_fallback=False)
    return {"status": "cleared", **cleared}


def _write_context(root: Path, fields: dict[str, Any], *, notes: str, enabled: bool, actor: str) -> None:
    frontmatter: dict[str, Any] = {
        "schema_version": 1,
        "scope": "workspace",
        "enabled_by_default": enabled,
        "updated_at": now_iso(),
        "updated_by": _text(actor, "actor", limit=120),
        **fields,
    }
    body = "# Investor Context\n" + (f"\n{notes.strip()}\n" if notes else "")
    rendered = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n\n" + body
    atomic_write_text(_path(root), rendered)


def _payload(
    root: Path,
    fields: dict[str, Any],
    *,
    notes: str,
    enabled_by_default: bool,
    source: str,
    updated_at: str,
    updated_by: str,
    content_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "configured": bool(fields or notes),
        "enabled_by_default": enabled_by_default,
        "source": source,
        "path": INVESTOR_CONTEXT_PATH.as_posix(),
        "content_hash": content_hash,
        "fields": fields,
        "notes": notes,
        "updated_at": updated_at,
        "updated_by": updated_by,
        "workspace_root": str(root),
    }


def _path(root: Path) -> Path:
    return safe_workspace_path(root, INVESTOR_CONTEXT_PATH, allowed_roots=(INVESTOR_CONTEXT_ROOT,))


def _legacy_fields(root: Path) -> dict[str, Any]:
    from tradingcodex_service.application.runtime import active_profile_for_workspace

    profile = active_profile_for_workspace(root)
    raw = profile.get("investor_profile") if isinstance(profile.get("investor_profile"), dict) else {}
    return _validated_fields(raw)


def _validated_fields(raw: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for field in INVESTOR_CONTEXT_FIELDS:
        value = raw.get(field)
        if value not in (None, "", []):
            fields[field] = _field_value(field, value)
    return fields


def _field_value(field: str, value: Any) -> Any:
    if field == "constraints" and isinstance(value, list):
        if len(value) > 20:
            raise ValueError("constraints may contain at most 20 items")
        return [_text(item, "constraints item", limit=500) for item in value]
    return _text(value, field, limit=2000)


def _text(value: Any, field: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if "\x00" in text or len(text) > limit:
        raise ValueError(f"{field} is invalid or exceeds {limit} characters")
    return text


def _optional_text(value: Any, field: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if "\x00" in text or len(text) > limit:
        raise ValueError(f"{field} is invalid or exceeds {limit} characters")
    return text


def _boolean(value: Any, *, default: bool | None = None) -> bool:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    raise ValueError("enabled_by_default must be a boolean")


def _notes(body: str) -> str:
    lines = (body or "").splitlines()
    if lines and lines[0].strip().lower() == "# investor context":
        lines = lines[1:]
    return "\n".join(lines).strip()
