from __future__ import annotations

import json
import os
from typing import Any, Callable

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from tradingcodex_service.application.common import local_or_staff_source
from tradingcodex_service.application.workbench import (
    WorkbenchConflict,
    follow_up_codex_run,
    get_artifact_detail,
    get_run_detail,
    get_skill_detail,
    preview_codex_run,
    start_codex_run,
    workbench_snapshot,
)
from tradingcodex_service.application.workspaces import WorkspaceSelectionError, bind_request_workspace
from tradingcodex_service.runtime_profile import LOCAL_PROFILE, is_loopback_host


def _read_allowed(view: Callable[..., JsonResponse]) -> Callable[..., JsonResponse]:
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        if not local_or_staff_source(
            request,
            api_key=os.environ.get("TRADINGCODEX_API_KEY"),
            api_key_principal=os.environ.get("TRADINGCODEX_API_PRINCIPAL"),
            allow_local_readonly=settings.SERVICE_PROFILE == LOCAL_PROFILE,
        ):
            return _error("forbidden", "TradingCodex workbench is local or staff only.", 403)
        try:
            root = bind_request_workspace(request)
        except WorkspaceSelectionError as exc:
            return _error("invalid_workspace", str(exc), 404)
        request.tradingcodex_workspace_root = root
        return view(request, *args, **kwargs)

    return wrapped


def _mutation_allowed(view: Callable[..., JsonResponse]) -> Callable[..., JsonResponse]:
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        user = getattr(request, "user", None)
        authenticated = local_or_staff_source(
            request,
            api_key=os.environ.get("TRADINGCODEX_API_KEY"),
            api_key_principal=os.environ.get("TRADINGCODEX_API_PRINCIPAL"),
            allow_local_readonly=settings.SERVICE_PROFILE == LOCAL_PROFILE,
        )
        loopback_local = settings.SERVICE_PROFILE == LOCAL_PROFILE and is_loopback_host(str(request.META.get("REMOTE_ADDR") or ""))
        if not ((authenticated or "").startswith("principal:") or loopback_local):
            return _error("forbidden", "Workbench mutations require staff or a loopback local request.", 403)
        try:
            root = bind_request_workspace(request)
        except WorkspaceSelectionError as exc:
            return _error("invalid_workspace", str(exc), 404)
        request.tradingcodex_workspace_root = root
        request.tradingcodex_actor = str((authenticated or "").removeprefix("principal:") or getattr(user, "username", "") or "local-user")
        return view(request, *args, **kwargs)

    return wrapped


@require_GET
@ensure_csrf_cookie
@_read_allowed
def snapshot(request: HttpRequest) -> JsonResponse:
    return JsonResponse(workbench_snapshot(request.tradingcodex_workspace_root))


@require_GET
@_read_allowed
def skill_detail(request: HttpRequest, skill_id: str) -> JsonResponse:
    return _read_response(lambda: get_skill_detail(request.tradingcodex_workspace_root, skill_id))


@require_GET
@_read_allowed
def artifact_detail(request: HttpRequest, artifact_id: str) -> JsonResponse:
    return _read_response(lambda: get_artifact_detail(request.tradingcodex_workspace_root, artifact_id))


@require_GET
@_read_allowed
def run_detail(request: HttpRequest, run_id: str) -> JsonResponse:
    return _read_response(lambda: get_run_detail(request.tradingcodex_workspace_root, run_id))


@require_POST
@csrf_protect
@_mutation_allowed
def run_preview(request: HttpRequest) -> JsonResponse:
    return _mutation_response(
        lambda body: preview_codex_run(
            request.tradingcodex_workspace_root,
            _prompt(body, {"prompt", "skill_id", "strategy_id", "use_investor_context"}),
            skill_id=_optional_string(body, "skill_id"),
            strategy_id=_optional_string(body, "strategy_id"),
            use_investor_context=_optional_boolean(body, "use_investor_context"),
        ),
        request,
        status=200,
    )


@require_POST
@csrf_protect
@_mutation_allowed
def run_start(request: HttpRequest) -> JsonResponse:
    return _mutation_response(
        lambda body: start_codex_run(
            request.tradingcodex_workspace_root,
            _prompt(body, {"prompt", "skill_id", "strategy_id", "use_investor_context", "preview_signature"}),
            skill_id=_optional_string(body, "skill_id"),
            strategy_id=_optional_string(body, "strategy_id"),
            use_investor_context=_optional_boolean(body, "use_investor_context"),
            preview_signature=_optional_string(body, "preview_signature"),
            actor=request.tradingcodex_actor,
        ),
        request,
    )


@require_POST
@csrf_protect
@_mutation_allowed
def run_follow_up(request: HttpRequest, run_id: str) -> JsonResponse:
    return _mutation_response(
        lambda body: follow_up_codex_run(
            request.tradingcodex_workspace_root,
            run_id,
            _prompt(body, {"prompt"}),
            actor=request.tradingcodex_actor,
        ),
        request,
    )


def _read_response(operation: Callable[[], dict[str, Any]]) -> JsonResponse:
    try:
        return JsonResponse(operation())
    except ValueError as exc:
        if any(marker in str(exc).lower() for marker in ("integrity", "workflow state", "symlink", "disagree")):
            return _error("unavailable", "Workbench state failed its integrity check.", 503)
        status = 404 if "not found" in str(exc) or "unknown" in str(exc) else 400
        return _error("not_found" if status == 404 else "invalid_request", str(exc), status)
    except Exception:
        return _error("unavailable", "Workbench data is temporarily unavailable.", 503)


def _mutation_response(operation: Callable[[dict[str, Any]], dict[str, Any]], request: HttpRequest, *, status: int = 202) -> JsonResponse:
    try:
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        return JsonResponse(operation(body), status=status)
    except json.JSONDecodeError:
        return _error("invalid_json", "Request body must be valid JSON.", 400)
    except WorkbenchConflict as exc:
        return _error("conflict", str(exc), 409)
    except ValueError as exc:
        return _error("blocked", str(exc), 400)
    except RuntimeError as exc:
        return _error("unavailable", str(exc), 503)
    except Exception:
        return _error("unavailable", "The workbench operation could not be completed.", 503)


def _optional_boolean(body: dict[str, Any], field: str) -> bool | None:
    if field not in body:
        return None
    value = body[field]
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _optional_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _prompt(body: dict[str, Any], allowed_fields: set[str]) -> str:
    unknown = sorted(set(body) - allowed_fields)
    if unknown:
        raise ValueError(f"unsupported workbench field(s): {', '.join(unknown)}")
    value = body.get("prompt")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("prompt is required")
    return value


def _error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)
