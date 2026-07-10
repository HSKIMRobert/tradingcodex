from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from tradingcodex_service.application.runtime import (
    WORKSPACE_MANIFEST_REL,
    ensure_runtime_database,
    persist_workspace_context_if_available,
    workspace_context_payload,
)


WORKSPACE_SESSION_KEY = "tradingcodex_selected_workspace_id"
_BOUND_WORKSPACE_ROOT: ContextVar[Path | None] = ContextVar("tradingcodex_workspace_root", default=None)


def default_workspace_root() -> Path:
    return Path(os.environ.get("TRADINGCODEX_WORKSPACE_ROOT", os.getcwd())).expanduser().resolve()


def bind_workspace_root(root: Path | str) -> Path:
    resolved = Path(root).expanduser().resolve()
    _BOUND_WORKSPACE_ROOT.set(resolved)
    return resolved


def current_workspace_root() -> Path:
    return _BOUND_WORKSPACE_ROOT.get() or default_workspace_root()


def bind_request_workspace(request: Any) -> Path:
    fallback = default_workspace_root()
    if not hasattr(request, "session"):
        return bind_workspace_root(fallback)

    requested_id = str(getattr(request, "GET", {}).get("workspace") or "").strip()
    if requested_id:
        selected = workspace_option_by_id(requested_id)
        if selected:
            request.session[WORKSPACE_SESSION_KEY] = requested_id
            request.session.modified = True
            return bind_workspace_root(selected["path"])
        request.session.pop(WORKSPACE_SESSION_KEY, None)
        request.session.modified = True

    selected_id = request.session.get(WORKSPACE_SESSION_KEY)
    if isinstance(selected_id, str) and selected_id:
        selected = workspace_option_by_id(selected_id)
        if selected:
            return bind_workspace_root(selected["path"])
        request.session.pop(WORKSPACE_SESSION_KEY, None)
        request.session.modified = True
    return bind_workspace_root(fallback)


def workspace_options(selected_root: Path | str | None = None) -> list[dict[str, Any]]:
    root = Path(selected_root or current_workspace_root()).expanduser().resolve()
    selected_context = workspace_context_payload(root)
    options: list[dict[str, Any]] = []
    try:
        ensure_runtime_database(None)
        persist_workspace_context_if_available(root)
        from apps.harness.models import WorkspaceContext

        options = [_workspace_option_from_model(item) for item in WorkspaceContext.objects.order_by("-last_seen_at", "project_name", "id")[:20]]
    except Exception:
        pass
    selected = _workspace_option_from_context(selected_context)
    if not any(item["workspace_id"] == selected["workspace_id"] for item in options):
        options.insert(0, selected)
    for item in options:
        item["selected"] = item["workspace_id"] == selected_context["workspace_id"]
    return options[:20]


def workspace_option_by_id(workspace_id: str) -> dict[str, Any] | None:
    if not workspace_id:
        return None
    try:
        ensure_runtime_database(None)
        from apps.harness.models import WorkspaceContext

        workspace = WorkspaceContext.objects.filter(workspace_id=workspace_id).first()
        if workspace is None:
            return None
        option = _workspace_option_from_model(workspace)
        return option if option["exists"] and option["bootstrapped"] else None
    except Exception:
        return None


def _workspace_option_from_model(workspace: Any) -> dict[str, Any]:
    return _workspace_option({
        "workspace_id": workspace.workspace_id,
        "project_name": workspace.project_name,
        "path": workspace.path,
        "git_branch": workspace.git_branch,
        "active_profile": workspace.active_profile if isinstance(workspace.active_profile, dict) else {},
        "last_seen_at": workspace.last_seen_at,
    })


def _workspace_option_from_context(context: dict[str, Any]) -> dict[str, Any]:
    return _workspace_option({
        "workspace_id": context["workspace_id"],
        "project_name": context["project_name"],
        "path": context["path"],
        "git_branch": context.get("git_branch", ""),
        "active_profile": context.get("active_profile") if isinstance(context.get("active_profile"), dict) else {},
        "last_seen_at": None,
    })


def _workspace_option(values: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(values["path"])).expanduser()
    active_profile = values["active_profile"]
    exists = path.exists()
    bootstrapped = (path / WORKSPACE_MANIFEST_REL).exists()
    return {
        **values,
        "active_profile_label": str(active_profile.get("label") or active_profile.get("profile_id") or "default-paper"),
        "exists": exists,
        "bootstrapped": bootstrapped,
        "status_label": "Ready" if exists and bootstrapped else "Not attached" if exists else "Missing",
        "selected": False,
    }
