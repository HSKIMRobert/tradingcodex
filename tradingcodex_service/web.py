from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from tradingcodex_cli.generator import bootstrap_workspace
from tradingcodex_service.application.agents import (
    AGENT_SPECS,
    EXPECTED_SUBAGENTS,
    SKILL_SPECS,
    build_projection_state,
    create_or_update_optional_skill,
    create_or_update_strategy_skill,
    delete_optional_skill,
    delete_strategy_skill,
    diff_agent_configuration,
    read_strategy_skill_records,
    set_optional_skill_status,
    set_strategy_skill_status,
)
from tradingcodex_service.application.harness import (
    build_subagent_starter_prompt,
    get_harness_health,
    get_harness_topology,
    get_role_detail,
    list_policy_overview,
    list_recent_activity,
)
from tradingcodex_service.application.markdown_preview import (
    MarkdownPreview,
    read_markdown_preview,
    render_markdown_preview,
)
from tradingcodex_service.application.research import list_workspace_research_artifacts
from tradingcodex_service.application.portfolio import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_PORTFOLIO_ID,
    DEFAULT_STRATEGY_ID,
    default_paper_portfolio_state,
)
from tradingcodex_service.application.runtime import (
    WORKSPACE_MANIFEST_REL,
    ensure_runtime_database,
    persist_workspace_context_if_available,
    tradingcodex_db_path,
    workspace_context_payload,
)
from apps.mcp.services import (
    create_or_update_connector,
    evaluate_external_mcp_proxy_call,
    import_external_mcp_discovery,
    set_external_tool_policy,
)


PRODUCT_NAV = [
    {"label": "Agents", "href": "/harness/agents/", "key": "agents"},
    {"label": "Strategies", "href": "/harness/strategies/", "key": "strategies"},
    {"label": "Research", "href": "/research/", "key": "research"},
    {"label": "Connectors", "href": "/integrations/mcp/", "key": "connectors"},
]
WORKSPACE_SESSION_KEY = "tradingcodex_selected_workspace_id"
WORKSPACE_NOTICE_SESSION_KEY = "tradingcodex_workspace_notice"
WORKSPACE_ERROR_SESSION_KEY = "tradingcodex_workspace_error"
SKILL_TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "workspace_templates" / "modules" / "repo-skills" / "files" / ".agents" / "skills"
SUBAGENT_SKILL_TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "workspace_templates" / "modules" / "repo-skills" / "files" / ".tradingcodex" / "subagents" / "skills"


def require_local_or_staff(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        remote_addr = request.META.get("REMOTE_ADDR", "")
        if remote_addr in {"127.0.0.1", "::1", ""}:
            return view(request, *args, **kwargs)
        if getattr(request, "user", None) and request.user.is_staff:
            return view(request, *args, **kwargs)
        return HttpResponseForbidden("TradingCodex web is local or staff only.")

    return wrapped


def default_workspace_root() -> Path:
    return Path(os.environ.get("TRADINGCODEX_WORKSPACE_ROOT", os.getcwd())).expanduser().resolve()


def workspace_root(request: HttpRequest | None = None) -> Path:
    fallback = default_workspace_root()
    if request is None or not hasattr(request, "session"):
        return fallback

    query_workspace_id = str(request.GET.get("workspace") or "").strip()
    if query_workspace_id:
        selected = _workspace_option_by_id(query_workspace_id)
        if selected:
            request.session[WORKSPACE_SESSION_KEY] = selected["workspace_id"]
            request.session.modified = True
            return Path(selected["path"]).expanduser().resolve()
        request.session.pop(WORKSPACE_SESSION_KEY, None)
        request.session.modified = True
        return fallback

    session_workspace_id = request.session.get(WORKSPACE_SESSION_KEY)
    if isinstance(session_workspace_id, str) and session_workspace_id:
        selected = _workspace_option_by_id(session_workspace_id)
        if selected:
            return Path(selected["path"]).expanduser().resolve()
        request.session.pop(WORKSPACE_SESSION_KEY, None)
        request.session.modified = True

    return fallback


def base_context(request: HttpRequest, active: str) -> dict[str, Any]:
    root = workspace_root(request)
    context = workspace_context_payload(root)
    options = workspace_options(root)
    return {
        "active": active,
        "nav_items": PRODUCT_NAV,
        "db_path": str(tradingcodex_db_path()),
        "workspace_context": context,
        "workspace_options": options,
        "selected_workspace_id": context["workspace_id"],
        "workspace_notice": _pop_session_message(request, WORKSPACE_NOTICE_SESSION_KEY),
        "workspace_error": _pop_session_message(request, WORKSPACE_ERROR_SESSION_KEY),
    }


@require_GET
@require_local_or_staff
def dashboard(request: HttpRequest) -> HttpResponse:
    return redirect("web-agents")


@require_GET
@require_local_or_staff
def harness(request: HttpRequest) -> HttpResponse:
    return redirect("web-agents")


@require_GET
@require_local_or_staff
def role_inspector(request: HttpRequest, role: str) -> HttpResponse:
    return render(
        request,
        "web/fragments/role_inspector.html",
        {"selected_role": get_role_detail(role, workspace_root(request))},
    )


@require_GET
@require_local_or_staff
def agents_index(request: HttpRequest) -> HttpResponse:
    return _render_agents(request)


@require_GET
@require_local_or_staff
def agent_skills(request: HttpRequest, role: str) -> HttpResponse:
    return _render_agents(request, selected_role=role)


@require_GET
@require_local_or_staff
def strategies_index(request: HttpRequest) -> HttpResponse:
    root = workspace_root(request)
    strategies = read_strategy_skill_records(root)
    selected_id = request.GET.get("strategy") or (strategies[0]["id"] if strategies else "")
    state = build_projection_state(root)
    preview = _skill_markdown_preview(root, state, selected_id) if selected_id else render_markdown_preview("_No strategy selected._")
    return render(
        request,
        "web/strategies.html",
        {
            **base_context(request, "strategies"),
            "strategies": strategies,
            "selected_strategy_id": selected_id,
            "strategy_preview": preview,
        },
    )


@require_POST
@require_local_or_staff
def strategy_create(request: HttpRequest) -> HttpResponse:
    return _mutating_redirect(request, "/harness/strategies/", lambda root: create_or_update_strategy_skill(root, _post(request, "strategy_id"), title=_post(request, "title"), description=_post(request, "description"), body=_post(request, "body"), language=_post(request, "language") or "unknown", status=_post(request, "status") or "draft", actor="web"))


@require_POST
@require_local_or_staff
def strategy_update(request: HttpRequest, strategy_id: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/strategies/?strategy={strategy_id}", lambda root: create_or_update_strategy_skill(root, strategy_id, title=_post(request, "title"), description=_post(request, "description"), body=_post(request, "body"), language=_post(request, "language") or "unknown", status=_post(request, "status") or "draft", actor="web"))


@require_POST
@require_local_or_staff
def strategy_activate(request: HttpRequest, strategy_id: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/strategies/?strategy={strategy_id}", lambda root: set_strategy_skill_status(root, strategy_id, "active", actor="web"))


@require_POST
@require_local_or_staff
def strategy_archive(request: HttpRequest, strategy_id: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/strategies/?strategy={strategy_id}", lambda root: set_strategy_skill_status(root, strategy_id, "archived", actor="web"))


@require_POST
@require_local_or_staff
def strategy_delete(request: HttpRequest, strategy_id: str) -> HttpResponse:
    return _mutating_redirect(request, "/harness/strategies/", lambda root: delete_strategy_skill(root, strategy_id, force=_post(request, "force") == "true", actor="web"))


@require_POST
@require_local_or_staff
def optional_skill_create(request: HttpRequest, role: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/agents/{role}/skills/", lambda root: create_or_update_optional_skill(root, role, _post(request, "skill_id"), title=_post(request, "title"), description=_post(request, "description"), body=_post(request, "body"), status=_post(request, "status") or "draft", actor="web"))


@require_POST
@require_local_or_staff
def optional_skill_update(request: HttpRequest, role: str, skill_id: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/agents/{role}/skills/?skill={skill_id}", lambda root: create_or_update_optional_skill(root, role, skill_id, title=_post(request, "title"), description=_post(request, "description"), body=_post(request, "body"), status=_post(request, "status") or "draft", actor="web"))


@require_POST
@require_local_or_staff
def optional_skill_activate(request: HttpRequest, role: str, skill_id: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/agents/{role}/skills/?skill={skill_id}", lambda root: set_optional_skill_status(root, role, skill_id, "active", actor="web"))


@require_POST
@require_local_or_staff
def optional_skill_archive(request: HttpRequest, role: str, skill_id: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/agents/{role}/skills/?skill={skill_id}", lambda root: set_optional_skill_status(root, role, skill_id, "archived", actor="web"))


@require_POST
@require_local_or_staff
def optional_skill_delete(request: HttpRequest, role: str, skill_id: str) -> HttpResponse:
    return _mutating_redirect(request, f"/harness/agents/{role}/skills/", lambda root: delete_optional_skill(root, role, skill_id, force=_post(request, "force") == "true", actor="web"))


@require_POST
@require_local_or_staff
def workspace_open(request: HttpRequest) -> HttpResponse:
    next_url = _safe_next_url(str(request.POST.get("next") or request.META.get("HTTP_REFERER") or "/research/"))
    raw_path = str(request.POST.get("workspace_path") or request.POST.get("path") or "").strip()
    if not raw_path:
        request.session[WORKSPACE_ERROR_SESSION_KEY] = "Workspace path is required."
        request.session.modified = True
        return redirect(next_url)
    return _open_workspace_path(request, Path(raw_path).expanduser().resolve(), next_url)


@require_POST
@require_local_or_staff
def workspace_browse(request: HttpRequest) -> HttpResponse:
    next_url = _safe_next_url(str(request.POST.get("next") or request.META.get("HTTP_REFERER") or "/research/"))
    try:
        target = _choose_workspace_directory()
    except Exception as exc:
        request.session[WORKSPACE_ERROR_SESSION_KEY] = f"Could not choose workspace folder: {exc}"
        request.session.modified = True
        return redirect(next_url)
    return _open_workspace_path(request, target, next_url)


@require_POST
@require_local_or_staff
def workspace_remove(request: HttpRequest, workspace_id: str) -> HttpResponse:
    next_url = _safe_next_url(str(request.POST.get("next") or request.META.get("HTTP_REFERER") or "/research/"))
    try:
        ensure_runtime_database(None)
        from apps.harness.models import WorkspaceContext

        WorkspaceContext.objects.filter(workspace_id=workspace_id).delete()
        if request.session.get(WORKSPACE_SESSION_KEY) == workspace_id:
            request.session.pop(WORKSPACE_SESSION_KEY, None)
        request.session[WORKSPACE_NOTICE_SESSION_KEY] = "Workspace reference removed. Files were not touched."
        request.session.modified = True
    except Exception as exc:
        request.session[WORKSPACE_ERROR_SESSION_KEY] = f"Could not remove workspace reference: {exc}"
        request.session.modified = True
    return redirect(_url_without_workspace(next_url))


def _open_workspace_path(request: HttpRequest, target: Path, next_url: str) -> HttpResponse:
    try:
        bootstrapped = not (target / WORKSPACE_MANIFEST_REL).exists()
        if bootstrapped:
            bootstrap_workspace(target, force=True)
        ensure_runtime_database(target)
        context = persist_workspace_context_if_available(target)
        request.session[WORKSPACE_SESSION_KEY] = context["workspace_id"]
        request.session[WORKSPACE_NOTICE_SESSION_KEY] = "Workspace bootstrapped and opened." if bootstrapped else "Workspace opened."
        request.session.modified = True
        return redirect(_url_with_workspace(next_url, context["workspace_id"]))
    except Exception as exc:
        request.session[WORKSPACE_ERROR_SESSION_KEY] = f"Could not open workspace: {exc}"
        request.session.modified = True
        return redirect(next_url)


def _choose_workspace_directory() -> Path:
    if os.name != "posix":
        raise RuntimeError("native folder picker is only available on this local desktop platform")
    script = 'POSIX path of (choose folder with prompt "Open TradingCodex workspace")'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "folder selection cancelled"
        raise RuntimeError(message)
    selected = result.stdout.strip()
    if not selected:
        raise RuntimeError("folder selection cancelled")
    return Path(selected).expanduser().resolve()


def _render_agents(request: HttpRequest, selected_role: str | None = None) -> HttpResponse:
    root = workspace_root(request)
    state = build_projection_state(root)
    role = selected_role or request.GET.get("role") or "head-manager"
    if role not in state["agents"]:
        role = "head-manager"
    agent = state["agents"].get(role)
    if not agent:
        return HttpResponse("Unknown agent role.", status=404)
    required_skills = [_skill_preview_item(root, state, skill_id, "required") for skill_id in agent.get("builtin_skills", [])]
    optional_skills = [
        _skill_preview_item(root, state, str(record.get("skill_id") or ""), "optional", record=record)
        for record in agent.get("optional_skills", [])
        if record.get("status") == "active"
    ]
    if role == "head-manager":
        optional_skills.extend(
            _skill_preview_item(root, state, skill_id, "strategy")
            for skill_id, skill in sorted(state.get("skills", {}).items())
            if skill.get("source") == "strategy" and skill.get("active")
        )
    skill_id = request.GET.get("skill") or (required_skills[0]["id"] if required_skills else optional_skills[0]["id"] if optional_skills else "")
    skill_preview = _skill_markdown_preview(root, state, skill_id) if skill_id else render_markdown_preview("_No skill selected._")
    for item in [*required_skills, *optional_skills]:
        item["selected"] = item["id"] == skill_id
    context = {
        **base_context(request, "agents"),
        "state": state,
        "head_manager": state["agents"]["head-manager"],
        "agents": [state["agents"][agent_role] for agent_role in EXPECTED_SUBAGENTS],
        "role_cards": [state["agents"]["head-manager"], *[state["agents"][agent_role] for agent_role in EXPECTED_SUBAGENTS]],
        "selected_agent": agent,
        "required_skills": required_skills,
        "optional_skills": optional_skills,
        "selected_skill_id": skill_id,
        "skill_preview": skill_preview,
        "projection_manifest": state["projection_manifest"],
        "agent": agent,
        "diff": diff_agent_configuration(root, role),
    }
    return render(request, "web/agents.html", context)


@require_GET
@require_local_or_staff
def research(request: HttpRequest) -> HttpResponse:
    root = workspace_root(request)
    artifacts = list_workspace_research_artifacts(root)
    selected_artifact_id = request.GET.get("artifact") or (artifacts[0].get("artifact_id") if artifacts else "")
    selected_artifact: dict[str, Any] | None = None
    artifact_preview: MarkdownPreview | None = None
    if selected_artifact_id:
        selected_artifact = next((artifact for artifact in artifacts if artifact.get("artifact_id") == selected_artifact_id or artifact.get("path") == selected_artifact_id), None)
        if selected_artifact:
            artifact_preview = read_markdown_preview(
                root / str(selected_artifact["path"]),
                source_file=str(selected_artifact["path"]),
                source_label="workspace research file",
            )
        else:
            artifact_preview = render_markdown_preview("_Research file is unavailable._", source_label="workspace research file")
    context = {
        **base_context(request, "research"),
        "artifacts": artifacts,
        "selected_artifact": selected_artifact,
        "selected_artifact_id": selected_artifact_id,
        "artifact_preview": artifact_preview,
        "research": research_overview(root),
    }
    return render(request, "web/research.html", context)


@require_GET
@require_local_or_staff
def portfolio(request: HttpRequest) -> HttpResponse:
    context = {**base_context(request, "portfolio"), "portfolio": portfolio_overview()}
    return render(request, "web/portfolio.html", context)


@require_GET
@require_local_or_staff
def orders(request: HttpRequest) -> HttpResponse:
    context = {**base_context(request, "orders"), **orders_overview()}
    return render(request, "web/orders.html", context)


@require_GET
@require_local_or_staff
def policy(request: HttpRequest) -> HttpResponse:
    context = {**base_context(request, "policy"), "policy": list_policy_overview(workspace_root(request))}
    return render(request, "web/policy.html", context)


@require_GET
@require_local_or_staff
def activity(request: HttpRequest) -> HttpResponse:
    context = {**base_context(request, "activity"), "activity": list_recent_activity(workspace_root(request), limit=50)}
    return render(request, "web/activity.html", context)


@require_GET
@require_local_or_staff
def mcp_connectors(request: HttpRequest) -> HttpResponse:
    context = {**base_context(request, "connectors"), **mcp_connectors_overview()}
    return render(request, "web/mcp_connectors.html", context)


@require_POST
@require_local_or_staff
def mcp_connector_create(request: HttpRequest) -> HttpResponse:
    return _service_redirect(
        request,
        "/integrations/mcp/",
        lambda: create_or_update_connector(
            name=_post(request, "name"),
            label=_post(request, "label"),
            transport=_post(request, "transport") or "stdio",
            command=_post(request, "command"),
            url=_post(request, "url"),
            credential_ref=_post(request, "credential_ref"),
            enabled=_post(request, "enabled") == "true",
            actor="web",
        ),
    )


@require_POST
@require_local_or_staff
def mcp_connector_import(request: HttpRequest, connector_id: int) -> HttpResponse:
    def operation() -> Any:
        from apps.mcp.models import McpConnector

        connector = McpConnector.objects.get(pk=connector_id)
        return import_external_mcp_discovery(connector, _post(request, "discovery_payload"), actor="web")

    return _service_redirect(request, f"/integrations/mcp/#connector-{connector_id}", operation)


@require_POST
@require_local_or_staff
def mcp_external_tool_update(request: HttpRequest, tool_id: int) -> HttpResponse:
    def operation() -> Any:
        from apps.mcp.models import McpExternalTool

        tool = McpExternalTool.objects.get(pk=tool_id)
        return set_external_tool_policy(
            tool,
            category=_post(request, "category"),
            risk_level=_post(request, "risk_level"),
            sensitivity=_post(request, "sensitivity"),
            canonical_capability=_post(request, "canonical_capability"),
            proxy_mode=_post(request, "proxy_mode"),
            allowed_roles=_split_csv(_post(request, "allowed_roles")),
            enabled=_post(request, "enabled") == "true",
            review_status="reviewed",
            actor="web",
        )

    return _service_redirect(request, f"/integrations/mcp/#tool-{tool_id}", operation)


@require_POST
@require_local_or_staff
def mcp_external_tool_check(request: HttpRequest, tool_id: int) -> HttpResponse:
    def operation() -> Any:
        from apps.mcp.models import McpExternalTool

        tool = McpExternalTool.objects.get(pk=tool_id)
        raw_arguments = _post(request, "arguments")
        arguments = json.loads(raw_arguments) if raw_arguments else {}
        return evaluate_external_mcp_proxy_call(
            workspace_root(request),
            tool,
            principal_id=_post(request, "principal_id") or "head-manager",
            arguments=arguments if isinstance(arguments, dict) else {},
            actor="web",
        )

    return _service_redirect(request, f"/integrations/mcp/#tool-{tool_id}", operation)


@require_GET
@require_local_or_staff
def starter_prompt(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    context = {
        **base_context(request, "workflow"),
        "query": query,
        "starter_prompt": build_subagent_starter_prompt(query) if query.strip() else "",
    }
    return render(request, "web/starter_prompt.html", context)


@require_GET
@require_local_or_staff
def starter_prompt_fragment(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    return render(
        request,
        "web/fragments/starter_prompt.html",
        {"query": query, "starter_prompt": build_subagent_starter_prompt(query) if query.strip() else ""},
    )


def _post(request: HttpRequest, name: str) -> str:
    return str(request.POST.get(name) or "").strip()


def _mutating_redirect(request: HttpRequest, fallback_url: str, operation: Callable[[Path], Any]) -> HttpResponse:
    next_url = _safe_next_url(str(request.POST.get("next") or fallback_url))
    try:
        operation(workspace_root(request))
        request.session[WORKSPACE_NOTICE_SESSION_KEY] = "Workspace files updated."
    except Exception as exc:
        request.session[WORKSPACE_ERROR_SESSION_KEY] = f"Could not update workspace files: {exc}"
    request.session.modified = True
    return redirect(next_url)


def _service_redirect(request: HttpRequest, fallback_url: str, operation: Callable[[], Any]) -> HttpResponse:
    next_url = _safe_next_url(str(request.POST.get("next") or fallback_url))
    try:
        operation()
        request.session[WORKSPACE_NOTICE_SESSION_KEY] = "MCP settings updated."
    except Exception as exc:
        request.session[WORKSPACE_ERROR_SESSION_KEY] = f"Could not update MCP settings: {exc}"
    request.session.modified = True
    return redirect(next_url)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def research_overview(root: Path) -> dict[str, Any]:
    artifacts = list_workspace_research_artifacts(root)[:5]
    universes = sorted({artifact.get("universe") for artifact in artifacts if artifact.get("universe")})
    return {"count": len(artifacts), "recent": artifacts, "universes": universes}


def _skill_preview_item(
    root: Path,
    state: dict[str, Any],
    skill_id: str,
    kind: str,
    *,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    skill = state.get("skills", {}).get(skill_id, {})
    spec = SKILL_SPECS.get(skill_id)
    source_file, source_label = _skill_source(root, skill_id, skill=skill, record=record)
    return {
        "id": skill_id,
        "label": str((record or {}).get("title") or skill.get("label") or (spec.label if spec else "") or skill_id.replace("-", " ").title()),
        "kind": kind,
        "status": str((record or {}).get("status") or skill.get("status") or "active"),
        "validation_status": str((record or {}).get("validation_status") or skill.get("validation_status") or "valid"),
        "risk_tags": list((record or {}).get("risk_tags") or skill.get("risk_tags") or []),
        "source_file": source_file,
        "source_label": source_label,
        "selected": False,
    }


def _skill_markdown_preview(root: Path, state: dict[str, Any], skill_id: str) -> MarkdownPreview:
    skill = state.get("skills", {}).get(skill_id, {})
    source_file, source_label = _skill_source(root, skill_id, skill=skill)
    path = _skill_markdown_path(root, skill_id, skill=skill)
    return read_markdown_preview(path, source_file=source_file, source_label=source_label)


def _skill_source(
    root: Path,
    skill_id: str,
    *,
    skill: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> tuple[str, str]:
    path = _skill_markdown_path(root, skill_id, skill=skill, record=record)
    try:
        return path.relative_to(root).as_posix(), "workspace skill"
    except ValueError:
        try:
            return path.relative_to(Path(__file__).resolve().parents[1]).as_posix(), "repo template"
        except ValueError:
            return str(path), "markdown file"


def _skill_markdown_path(
    root: Path,
    skill_id: str,
    *,
    skill: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> Path:
    for raw in [record.get("source_file") if record else "", skill.get("source_file") if skill else ""]:
        if raw:
            candidate = Path(raw)
            path = candidate if candidate.is_absolute() else root / candidate
            if path.exists():
                return path
    workspace_path = root / ".agents" / "skills" / skill_id / "SKILL.md"
    if workspace_path.exists():
        return workspace_path
    spec = SKILL_SPECS.get(skill_id)
    if spec and spec.scope == "subagent_shared":
        return SUBAGENT_SKILL_TEMPLATE_ROOT / "shared" / skill_id / "SKILL.md"
    if spec and spec.scope == "subagent_role":
        role = spec.owner_roles[0] if spec.owner_roles else ""
        return SUBAGENT_SKILL_TEMPLATE_ROOT / role / skill_id / "SKILL.md"
    return SKILL_TEMPLATE_ROOT / skill_id / "SKILL.md"


def workspace_options(selected_root: Path) -> list[dict[str, Any]]:
    selected_context = workspace_context_payload(selected_root)
    options: list[dict[str, Any]] = []
    try:
        ensure_runtime_database(None)
        persist_workspace_context_if_available(selected_root)
        from apps.harness.models import WorkspaceContext

        for workspace in WorkspaceContext.objects.order_by("-last_seen_at", "project_name", "id")[:20]:
            options.append(_workspace_option_from_model(workspace))
    except Exception:
        options = []

    selected_option = _workspace_option_from_context(selected_context)
    if not any(option["workspace_id"] == selected_option["workspace_id"] for option in options):
        options.insert(0, selected_option)
    for option in options:
        option["selected"] = option["workspace_id"] == selected_context["workspace_id"]
    return options[:20]


def _workspace_option_by_id(workspace_id: str) -> dict[str, Any] | None:
    if not workspace_id:
        return None
    try:
        ensure_runtime_database(None)
        from apps.harness.models import WorkspaceContext

        workspace = WorkspaceContext.objects.filter(workspace_id=workspace_id).first()
        if not workspace:
            return None
        option = _workspace_option_from_model(workspace)
        if not Path(option["path"]).expanduser().exists():
            return None
        return option
    except Exception:
        return None


def _workspace_option_from_model(workspace: Any) -> dict[str, Any]:
    active_profile = workspace.active_profile if isinstance(workspace.active_profile, dict) else {}
    path = Path(workspace.path).expanduser()
    exists = path.exists()
    bootstrapped = (path / WORKSPACE_MANIFEST_REL).exists()
    return {
        "workspace_id": workspace.workspace_id,
        "project_name": workspace.project_name,
        "path": workspace.path,
        "git_branch": workspace.git_branch,
        "active_profile": active_profile,
        "active_profile_label": str(active_profile.get("label") or active_profile.get("profile_id") or "default-paper"),
        "last_seen_at": workspace.last_seen_at,
        "exists": exists,
        "bootstrapped": bootstrapped,
        "status_label": "Ready" if exists and bootstrapped else "Needs bootstrap" if exists else "Missing",
        "selected": False,
    }


def _workspace_option_from_context(context: dict[str, Any]) -> dict[str, Any]:
    active_profile = context.get("active_profile") if isinstance(context.get("active_profile"), dict) else {}
    path = Path(str(context["path"])).expanduser()
    exists = path.exists()
    bootstrapped = (path / WORKSPACE_MANIFEST_REL).exists()
    return {
        "workspace_id": context["workspace_id"],
        "project_name": context["project_name"],
        "path": context["path"],
        "git_branch": context.get("git_branch", ""),
        "active_profile": active_profile,
        "active_profile_label": str(active_profile.get("label") or active_profile.get("profile_id") or "default-paper"),
        "last_seen_at": None,
        "exists": exists,
        "bootstrapped": bootstrapped,
        "status_label": "Ready" if exists and bootstrapped else "Needs bootstrap" if exists else "Missing",
        "selected": False,
    }


def _pop_session_message(request: HttpRequest, key: str) -> str:
    if not hasattr(request, "session"):
        return ""
    value = request.session.pop(key, "")
    if value:
        request.session.modified = True
    return str(value)


def _safe_next_url(raw_url: str) -> str:
    if not raw_url.startswith("/") or raw_url.startswith("//"):
        return "/research/"
    return raw_url


def _url_with_workspace(raw_url: str, workspace_id: str) -> str:
    split = urlsplit(_safe_next_url(raw_url))
    query = [(key, value) for key, value in parse_qsl(split.query, keep_blank_values=True) if key != "workspace"]
    query.insert(0, ("workspace", workspace_id))
    return urlunsplit((split.scheme, split.netloc, split.path or "/research/", urlencode(query), split.fragment))


def _url_without_workspace(raw_url: str) -> str:
    split = urlsplit(_safe_next_url(raw_url))
    query = [(key, value) for key, value in parse_qsl(split.query, keep_blank_values=True) if key != "workspace"]
    return urlunsplit((split.scheme, split.netloc, split.path or "/research/", urlencode(query), split.fragment))


def portfolio_overview() -> dict[str, Any]:
    try:
        from apps.portfolio.models import PortfolioSnapshot

        latest = PortfolioSnapshot.objects.order_by("-created_at", "-id").first()
        if latest and isinstance(latest.payload, dict):
            state = dict(latest.payload)
            state.setdefault("updated_at", latest.created_at.isoformat())
        else:
            state = default_paper_portfolio_state(DEFAULT_PORTFOLIO_ID, DEFAULT_ACCOUNT_ID, DEFAULT_STRATEGY_ID)
        positions = state.get("positions") if isinstance(state.get("positions"), dict) else {}
        return {
            "cash_krw": state.get("cash_krw", 0),
            "positions": sorted(
                [
                    {
                        "symbol": symbol,
                        "quantity": position.get("quantity", 0),
                        "average_price": position.get("average_price", 0),
                        "currency": position.get("currency", "KRW"),
                    }
                    for symbol, position in positions.items()
                ],
                key=lambda item: item["symbol"],
            ),
            "positions_count": len(positions),
            "updated_at": state.get("updated_at", ""),
            "portfolio_id": state.get("portfolio_id", DEFAULT_PORTFOLIO_ID),
            "account_id": state.get("account_id", DEFAULT_ACCOUNT_ID),
            "strategy_id": state.get("strategy_id", DEFAULT_STRATEGY_ID),
        }
    except Exception:
        state = default_paper_portfolio_state(DEFAULT_PORTFOLIO_ID, DEFAULT_ACCOUNT_ID, DEFAULT_STRATEGY_ID)
        return {
            "cash_krw": state["cash_krw"],
            "positions": [],
            "positions_count": 0,
            "updated_at": state["updated_at"],
            "portfolio_id": DEFAULT_PORTFOLIO_ID,
            "account_id": DEFAULT_ACCOUNT_ID,
            "strategy_id": DEFAULT_STRATEGY_ID,
        }


def orders_overview() -> dict[str, Any]:
    try:
        from apps.orders.models import ApprovalReceipt, ExecutionResult, OrderIntent

        return {
            "order_intents": OrderIntent.objects.order_by("-created_at", "-id")[:30],
            "approval_receipts": ApprovalReceipt.objects.order_by("-created_at", "-id")[:30],
            "execution_results": ExecutionResult.objects.order_by("-created_at", "-id")[:30],
            "order_count": OrderIntent.objects.count(),
            "approval_count": ApprovalReceipt.objects.count(),
            "execution_count": ExecutionResult.objects.count(),
        }
    except Exception:
        return {
            "order_intents": [],
            "approval_receipts": [],
            "execution_results": [],
            "order_count": 0,
            "approval_count": 0,
            "execution_count": 0,
        }


def mcp_connectors_overview() -> dict[str, Any]:
    try:
        ensure_runtime_database(None)
        from apps.mcp.models import McpConnector, McpExternalTool, McpExternalToolCall

        connectors = list(McpConnector.objects.prefetch_related("external_tools").all())
        tools = list(McpExternalTool.objects.select_related("connector").all())
        return {
            "connectors": connectors,
            "external_tools": tools,
            "recent_external_calls": McpExternalToolCall.objects.select_related("external_tool")[:15],
            "connector_count": len(connectors),
            "external_tool_count": len(tools),
            "enabled_external_tool_count": sum(1 for tool in tools if tool.enabled),
            "review_required_count": sum(1 for tool in tools if tool.review_status != "reviewed" or tool.drift_detected),
            "category_options": ["market_data", "account_read", "research_write", "portfolio_state", "policy_admin", "execution", "secret", "workflow_prompt", "unknown"],
            "risk_options": ["read", "write", "approval", "execution", "blocked", "unknown"],
            "sensitivity_options": ["public", "private", "research", "canonical_state", "secret", "unknown"],
            "proxy_mode_options": ["blocked", "read_only", "summary_only", "service_path", "service_adapter"],
        }
    except Exception:
        return {
            "connectors": [],
            "external_tools": [],
            "recent_external_calls": [],
            "connector_count": 0,
            "external_tool_count": 0,
            "enabled_external_tool_count": 0,
            "review_required_count": 0,
            "category_options": [],
            "risk_options": [],
            "sensitivity_options": [],
            "proxy_mode_options": [],
        }
