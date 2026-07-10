from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import threading
import tomllib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import yaml

from apps.mcp.services import list_external_mcp_permission_requests
from tradingcodex_cli.generator import _generation_context, render_template, templates_dir
from tradingcodex_service.application.agents import (
    AGENT_SPECS,
    SKILL_SPECS,
    _render_core_extension_boundary,
    _render_role_skill_source_block,
    _replace_agent_model_policy,
    _replace_developer_instructions,
    _replace_tradingcodex_enabled_tools,
    build_projection_state,
    inspect_skill_projection,
    list_optional_role_skills,
    read_strategy_skill_records,
    resolve_agent_model_policy,
)
from tradingcodex_service.application.artifact_quality import evaluate_decision_quality
from tradingcodex_service.application.brokers import list_broker_connections
from tradingcodex_service.application.common import (
    atomic_write_text,
    append_jsonl,
    now_iso,
    read_json,
    safe_workspace_path,
    sanitize_id,
    stable_hash,
    workspace_launcher_command,
    write_json,
)
from tradingcodex_service.application.forecasting import calibration_report, list_forecasts
from tradingcodex_service.application.harness import build_workflow_intake_summary, list_recent_activity
from tradingcodex_service.application.investor_context import read_investor_context
from tradingcodex_service.application.markdown_preview import read_markdown_preview, render_markdown_preview
from tradingcodex_service.application.orders import list_order_tickets
from tradingcodex_service.application.portfolio import list_positions
from tradingcodex_service.application.research import get_research_artifact, list_research_artifacts
from tradingcodex_service.application.runtime import WORKSPACE_MANIFEST_REL, active_profile_for_workspace, tradingcodex_db_path, workspace_context_payload
from tradingcodex_service.application.workflow_planner import (
    INVESTOR_CONTEXT_SNAPSHOT_FILE,
    LATEST_INTAKE_PATH,
    LATEST_LOOP_STATE_PATH,
    LATEST_PLAN_PATH,
    STRATEGY_SNAPSHOT_FILE,
    build_workflow_intake,
    record_workflow_intake,
    seal_workflow_run_bindings,
    select_investor_context_binding,
    select_strategy_binding,
    validate_workflow_plan,
    workflow_intake_relpath,
    workflow_loop_relpath,
    workflow_plan_relpath,
)
from tradingcodex_service.application.workflow_routing import strip_negated_action_phrases
from tradingcodex_service.application.workflow_contracts import intake_contract_hash
from tradingcodex_service.application.workflow_state import read_workflow_state, replay_workflow_state
from tradingcodex_service.application.workspaces import workspace_options
from tradingcodex_service.log_safety import redact_log_text


WEB_RUN_FILE = "web-run.json"
WEB_EVENTS_FILE = "web-run-events.jsonl"
ANALYSIS_LANES = {
    "research_only",
    "thesis_review",
    "thesis_review_then_portfolio_risk_review",
    "portfolio_risk_review",
}
_SENSITIVE_ENV = re.compile(
    r"secret|token|password|passwd|credential|api[_-]?key|private[_-]?key|access[_-]?key|"
    r"(^|_)(?:key|auth|authorization|dsn|database_url|db_url|cookie|session|connection_string)(?:$|_)",
    re.I,
)
_DANGEROUS_FOLLOWUP = re.compile(r"\b(order|approve|approval|execute|execution|submit|cancel|broker|secret|api[_ -]?key|credential)\b", re.I)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:/-]{1,180}$")
_COMPUTER_ACTION = re.compile(
    r"\b(?:run|execute|invoke|launch|call|pipe|upload|post|send|transmit|exfiltrat\w*|read|copy|print|reveal)\b"
    r".{0,120}\b(?:curl|wget|scp|sftp|ssh|nc|netcat|bash|zsh|powershell|cmd(?:\.exe)?|shell|terminal|command|script|file|contents?)\b",
    re.I | re.S,
)
_SENSITIVE_PATH = re.compile(
    r"(?:~|/(?:Users|home)/[^/\s]+)/(?:\.ssh|\.aws|\.gnupg|\.config/(?:gcloud|gh|op))\b|"
    r"(?:^|[/\\])(?:id_rsa|id_ed25519|credentials(?:\.json)?|auth\.json|\.env)(?:$|[/\\\s])|"
    r"/etc/(?:shadow|passwd)\b",
    re.I,
)
_INTERACTIVE_ACTION = re.compile(
    r"(?:\b(?:click|type|fill|submit|log\s*in|sign\s*in|navigate|open|control|use)\b.{0,100}"
    r"\b(?:browser|web\s*page|website|app|computer)\b)|"
    r"(?:\b(?:browser|web\s*page|website|app|computer)\b.{0,100}"
    r"\b(?:click|type|fill|submit|log\s*in|sign\s*in|navigate|open|control)\b)",
    re.I | re.S,
)
_DISABLED_CODEX_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "in_app_browser",
    "unified_exec",
    "unified_exec_zsh_fork",
)
_CODEX_EVENT_TYPES = {"thread.started", "turn.started", "turn.completed", "turn.failed", "error", "item.started", "item.completed"}
_WORKBENCH_EVENT_TYPES = {"workbench.started", "workbench.follow_up_started", "workbench.launch_failed", "workbench.process_exited", "workbench.timed_out"}
_EVENT_STATUSES = {"starting", "started", "running", "completed", "failed", "ok", "error"}
_ITEM_TYPES = {"agent_message", "mcp_tool_call", "web_search", "command_execution", "tool_call"}
WORKBENCH_RUN_TIMEOUT_SECONDS = 1800
_ACTIVE_RUNS: dict[str, subprocess.Popen[str]] = {}
_ACTIVE_RUNS_LOCK = threading.Lock()


class WorkbenchConflict(RuntimeError):
    pass


def workbench_snapshot(root: Path | str) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    sections: dict[str, dict[str, Any]] = {
        "workspace": _section(lambda: {"context": workspace_context_payload(root), "profile": active_profile_for_workspace(root), "options": workspace_options(root)}),
        "investor_context": _section(lambda: _investor_context_status(root)),
        "skills": _section(lambda: skill_catalog(root)),
        "agents": _section(lambda: _agent_catalog(root)),
        "workflow": _section(lambda: _latest_workflow(root)),
        "runs": _section(lambda: list_recent_runs(root)),
        "activity": _section(lambda: _recent_activity(root)),
        "artifacts": _section(lambda: list_research_artifacts(root, {"limit": 100})["artifacts"]),
        "forecasts": _section(lambda: {"items": list_forecasts(root, {"limit": 100}), "calibration": calibration_report(root, {"minimum_sample": 20})}),
        "permissions": _section(lambda: list_external_mcp_permission_requests(root, {"status": "pending", "limit": 50})),
        "strategies": _section(lambda: read_strategy_skill_records(root)),
        "optional_skills": _section(lambda: list_optional_role_skills(root, include_archived=True)),
        "portfolio": _section(lambda: list_positions(root)),
        "orders": _section(lambda: list_order_tickets(root, {"limit": 50})),
        "brokers": _section(lambda: list_broker_connections(root)),
    }
    return _json_safe({"generated_at": now_iso(), "sections": sections})


def skill_catalog(root: Path | str) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    state = build_projection_state(root)
    records = []
    for skill_id, item in sorted(state.get("skills", {}).items()):
        path = _skill_path(root, skill_id, item)
        preview = read_markdown_preview(path, source_file=_display_path(root, path), source_label="skill")
        metadata = _read_yaml(path.parent / "agents" / "openai.yaml").get("interface", {})
        spec = SKILL_SPECS.get(skill_id)
        risk_tags = list(item.get("risk_tags") or (spec.risk_tags if spec else ()))
        source = str(item.get("source") or "core")
        active_strategy = source == "strategy" and str(item.get("status") or "active") == "active"
        active_optional = (
            source == "optional"
            and str(item.get("status") or "active") == "active"
            and str(item.get("validation_status") or "valid") == "valid"
        )
        startable = path.is_file() and not set(risk_tags).intersection({"order", "approval", "execution", "secret"}) and (
            skill_id in {"tcx-workflow", "decision-memory"} or active_strategy or active_optional or bool(spec and spec.scope != "mainagent")
        )
        records.append({
            "id": skill_id,
            "label": str(metadata.get("display_name") or item.get("label") or preview.heading or skill_id),
            "description": str(metadata.get("short_description") or preview.frontmatter.get("description") or item.get("description") or ""),
            "default_prompt": str(metadata.get("default_prompt") or ""),
            "owner_roles": list(item.get("owner_roles") or (spec.owner_roles if spec else ())),
            "risk_tags": risk_tags,
            "scope": str(item.get("scope") or (spec.scope if spec else "mainagent")),
            "source": source,
            "status": str(item.get("status") or "active"),
            "installed": path.is_file(),
            "user_visible": bool(item.get("user_visible")),
            "route_through_head_manager": bool(not spec or spec.scope != "mainagent"),
            "startable": startable,
        })
    return records


def get_skill_detail(root: Path | str, skill_id: str) -> dict[str, Any]:
    record = next((item for item in skill_catalog(root) if item["id"] == skill_id), None)
    if record is None:
        raise ValueError(f"unknown skill: {skill_id}")
    root = Path(root).resolve()
    state = build_projection_state(root)
    path = _skill_path(root, skill_id, state["skills"][skill_id])
    preview = read_markdown_preview(path, source_file=_display_path(root, path), source_label="skill")
    return _json_safe({**record, "preview": {"heading": preview.heading, "html": preview.html, "frontmatter": preview.frontmatter}})


def get_artifact_detail(root: Path | str, artifact_id: str) -> dict[str, Any]:
    artifact = get_research_artifact(root, {"artifact_id": artifact_id, "include_markdown": True})
    markdown = str(artifact.pop("markdown", ""))
    preview = render_markdown_preview(markdown, source_file=str(artifact.get("path") or ""), source_label="research artifact")
    return _json_safe({**artifact, "preview": {"heading": preview.heading, "html": preview.html}})


def preview_codex_run(
    root: Path | str,
    prompt: str,
    *,
    skill_id: str = "",
    strategy_id: str = "",
    use_investor_context: bool | None = None,
) -> dict[str, Any]:
    root = _validated_workspace(root)
    prompt = _validated_prompt(prompt)
    _require_safe_computer_use(prompt)
    strategy_binding, _ = select_strategy_binding(root, strategy_id)
    context_binding, _ = select_investor_context_binding(root, use_investor_context)
    runtime_prompt = _skill_prompt(root, skill_id, prompt, strategy_binding=strategy_binding, context_binding=context_binding)
    _require_analysis_request(runtime_prompt)
    return _json_safe({
        "intake_summary": build_workflow_intake_summary(
            runtime_prompt,
            root,
            context_binding=context_binding,
            strategy_binding=strategy_binding,
        ),
        "method_id": skill_id,
        "strategy_binding": _public_strategy_binding(strategy_binding),
        "investor_context_binding": _public_context_binding(context_binding),
        "preview_signature": _preview_signature(
            prompt,
            skill_id=skill_id,
            strategy_binding=strategy_binding,
            context_binding=context_binding,
            use_investor_context=use_investor_context,
        ),
    })


def start_codex_run(
    root: Path | str,
    prompt: str,
    *,
    skill_id: str = "",
    strategy_id: str = "",
    use_investor_context: bool | None = None,
    preview_signature: str = "",
    actor: str = "local-user",
) -> dict[str, Any]:
    root = _validated_workspace(root)
    prompt = _validated_prompt(prompt)
    _require_safe_computer_use(prompt)
    strategy_binding, strategy_content = select_strategy_binding(root, strategy_id)
    context_binding, context_content = select_investor_context_binding(root, use_investor_context)
    expected_signature = _preview_signature(
        prompt,
        skill_id=skill_id,
        strategy_binding=strategy_binding,
        context_binding=context_binding,
        use_investor_context=use_investor_context,
    )
    if not preview_signature:
        raise ValueError("preview_signature is required; review scope again")
    if preview_signature != expected_signature:
        raise WorkbenchConflict("workbench inputs changed after preview; review scope again")
    runtime_prompt = _skill_prompt(root, skill_id, prompt, strategy_binding=strategy_binding, context_binding=context_binding)
    _require_analysis_request(runtime_prompt)
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Codex CLI is unavailable")
    _verify_generated_runtime(root)
    provisional = build_workflow_intake(
        runtime_prompt,
        root,
        strategy_binding=strategy_binding,
        context_binding=context_binding,
    )
    run_id = str(provisional["workflow_run_id"])
    run_dir = _run_dir(root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    strategy_binding, context_binding = seal_workflow_run_bindings(
        root,
        run_id,
        strategy_binding=strategy_binding,
        strategy_content=strategy_content,
        context_binding=context_binding,
        context_content=context_content,
    )
    runtime_prompt = _skill_prompt(root, skill_id, prompt, strategy_binding=strategy_binding, context_binding=context_binding)
    intake = record_workflow_intake(
        root,
        runtime_prompt,
        workflow_run_id=run_id,
        strategy_binding=strategy_binding,
        context_binding=context_binding,
    )
    metadata = {
        "schema_version": 1,
        "workflow_run_id": run_id,
        "status": "starting",
        "actor": actor,
        "skill_id": skill_id,
        "strategy_binding": strategy_binding,
        "investor_context_binding": context_binding,
        "preview_signature": preview_signature,
        "prompt_sha256": intake["prompt_sha256"],
        "original_request": redact_log_text(prompt)[:500],
        "thread_id": "",
        "pid": 0,
        "attempt": 1,
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "events_path": (run_dir / WEB_EVENTS_FILE).relative_to(root).as_posix(),
    }
    _clear_thread_authority(root, run_id)
    argv = [
        codex,
        "exec",
        "--ignore-user-config",
        *_head_manager_model_args(),
        *_codex_feature_args(),
        "-C",
        str(root),
        "--skip-git-repo-check",
        "--json",
        "-s",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        "-c",
        "sandbox_workspace_write.network_access=false",
        "--dangerously-bypass-hook-trust",
        "-",
    ]
    launched = _launch(root, run_id, argv, metadata, runtime_prompt, followup=False)
    return _json_safe({
        **launched,
        "skill_id": skill_id,
        "strategy_binding": _public_strategy_binding(strategy_binding),
        "investor_context_binding": _public_context_binding(context_binding),
        "preview_signature": preview_signature,
    })


def follow_up_codex_run(root: Path | str, run_id: str, prompt: str, *, actor: str = "local-user") -> dict[str, Any]:
    root = _validated_workspace(root)
    prompt = _validated_prompt(prompt)
    run_dir = _existing_run_dir(root, run_id)
    metadata = _run_metadata(run_dir)
    current = get_run_detail(root, run_id)
    if current["status"] in {"starting", "running"}:
        raise WorkbenchConflict("workflow run already has an active Codex process")
    if str(current.get("workflow_lane") or "") not in ANALYSIS_LANES:
        raise ValueError("web follow-up is available for analysis workflows only")
    _require_safe_followup(prompt)
    thread_id = _service_thread_id(root, run_id)
    if not thread_id or thread_id.startswith("-") or not _SAFE_NAME.match(thread_id):
        raise ValueError("workflow run has no resumable Codex thread")
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Codex CLI is unavailable")
    _verify_generated_runtime(root)
    attempt = int(metadata.get("attempt") or 1) + 1
    metadata.update({"status": "starting", "actor": actor, "pid": 0, "attempt": attempt, "updated_at": now_iso()})
    argv = [
        codex,
        "exec",
        "resume",
        "--ignore-user-config",
        *_head_manager_model_args(),
        *_codex_feature_args(),
        "--skip-git-repo-check",
        "--json",
        "-c",
        'sandbox_mode="workspace-write"',
        "-c",
        'approval_policy="never"',
        "-c",
        "sandbox_workspace_write.network_access=false",
        "--dangerously-bypass-hook-trust",
        thread_id,
        "-",
    ]
    return _launch(root, run_id, argv, metadata, prompt, followup=True)


def get_run_detail(root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(root).resolve()
    run_dir = _existing_run_dir(root, run_id)
    metadata = _run_metadata(run_dir)
    events = _read_normalized_events(_safe_run_file(run_dir, WEB_EVENTS_FILE, required=False))
    public_events = [{key: value for key, value in event.items() if key != "thread_id"} for event in events]
    key = _run_key(root, run_id)
    with _ACTIVE_RUNS_LOCK:
        process = _ACTIVE_RUNS.get(key)
    metadata_status = str(metadata.get("status") or "waiting")
    persisted_pid = int(metadata.get("pid") or 0)
    active = bool(process and process.poll() is None) or (metadata_status in {"starting", "running"} and _process_alive(persisted_pid))
    process_status = "running" if active else str(metadata.get("status") or "waiting")
    if process_status in {"starting", "running"} and not active:
        process_status = "failed"
    intake_raw = _read_workflow_record(root, workflow_intake_relpath(run_id))
    if intake_raw and intake_raw.get("intake_hash") != intake_contract_hash(intake_raw):
        raise ValueError("workflow intake integrity check failed")
    plan_raw = _read_workflow_record(root, workflow_plan_relpath(run_id), required=False)
    _safe_workflow_path(root, Path(workflow_loop_relpath(run_id)).parent / "events.jsonl", required=False)
    state_raw = read_workflow_state(root, run_id) if _safe_workflow_path(root, workflow_loop_relpath(run_id), required=False).exists() else {}
    if state_raw and replay_workflow_state(root, run_id) != state_raw:
        raise ValueError("canonical workflow state disagrees with its durable event log")
    if state_raw and not plan_raw:
        raise ValueError("workflow state has no validated recorded plan")
    if plan_raw:
        validation = validate_workflow_plan(plan_raw, intake=intake_raw)
        if not validation.get("ok"):
            raise ValueError("recorded workflow plan integrity check failed")
        if state_raw and str(state_raw.get("plan_hash") or "") != str(validation.get("plan_hash") or ""):
            raise ValueError("workflow plan and state disagree")
    intake = _public_intake(intake_raw)
    plan = _public_plan(plan_raw)
    state = _public_state(state_raw)
    outcome = str(state_raw.get("terminal_action") or "")
    artifacts = [
        item
        for item in list_research_artifacts(root, {"limit": 200})["artifacts"]
        if str(item.get("workflow_run_id") or "") == run_id
    ]
    forecasts = [
        item
        for item in list_forecasts(root, {"limit": 200}).get("forecasts", [])
        if str(item.get("workflow_run_id") or "") == run_id
    ][:100]
    final_output, synthesis_reason = _accepted_synthesis(root, artifacts, state_raw)
    status = process_status
    incomplete_reason = ""
    if not active and process_status != "failed":
        if outcome in {"waiting", "revise", "blocked", "lane_escalation_proposal"}:
            status = outcome
        elif outcome == "synthesize" and final_output:
            status = "completed"
        elif outcome == "synthesize":
            status = "waiting"
            incomplete_reason = synthesis_reason or "accepted synthesis artifact is not ready"
        elif process_status == "completed":
            status = "failed"
            incomplete_reason = "Codex exited before recording a terminal workflow state"
    error = None
    current_attempt = int(metadata.get("attempt") or 0)
    timed_out = any(
        event.get("type") == "workbench.timed_out" and event.get("attempt") == current_attempt
        for event in public_events
    )
    if process_status == "failed":
        error = {
            "code": "process_timeout" if timed_out else "process_interrupted",
            "message": "Codex process exceeded the 30-minute workbench limit." if timed_out else "Codex process ended without a successful terminal event.",
        }
    elif status == "failed":
        error = {"code": "incomplete_workflow", "message": incomplete_reason}
    return _json_safe({
        "workflow_run_id": run_id,
        "original_request": redact_log_text(str(metadata.get("original_request") or ""))[:500],
        "status": status,
        "process_status": process_status,
        "pid": int(metadata.get("pid") or 0),
        "attempt": current_attempt,
        "workflow_lane": str(plan.get("lane") or state.get("lane") or intake.get("heuristic_lane") or ""),
        "method_id": str(metadata.get("skill_id") or ""),
        "strategy_binding": _public_strategy_binding(intake_raw.get("strategy_binding") or metadata.get("strategy_binding")),
        "investor_context_binding": _public_context_binding(intake_raw.get("investor_context_binding") or metadata.get("investor_context_binding")),
        "intake": intake,
        "plan": plan,
        "state": state,
        "agents": _run_agents(state),
        "activity": public_events[-200:],
        "artifacts": artifacts,
        "forecasts": forecasts,
        "final_output": final_output,
        "blocked_actions": state.get("blocked_actions") or plan.get("blocked_actions") or intake.get("blocked_actions") or [],
        "stop_reason": "web_run_timeout" if timed_out else incomplete_reason or state.get("stop_reason") or ("service_process_interrupted" if process_status == "failed" else ""),
        "error": error,
    })


def _launch(root: Path, run_id: str, argv: list[str], metadata: dict[str, Any], prompt: str, *, followup: bool) -> dict[str, Any]:
    env = _codex_environment(root, run_id, followup=followup)
    key = _run_key(root, run_id)
    run_dir = _run_dir(root, run_id)
    run_lock = _claim_run(root, run_id)
    try:
        with _ACTIVE_RUNS_LOCK:
            existing = _ACTIVE_RUNS.get(key)
            if existing is not None and existing.poll() is None:
                raise WorkbenchConflict("workflow run already has an active Codex process")
            metadata.update({"status": "starting", "pid": 0, "updated_at": now_iso()})
            write_json(run_dir / WEB_RUN_FILE, metadata)
            _append_web_event(run_dir, {
                "type": "workbench.follow_up_started" if followup else "workbench.started",
                "status": "starting",
                "attempt": int(metadata.get("attempt") or 1),
            })
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=root,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                    close_fds=True,
                    shell=False,
                )
            except OSError as exc:
                _append_web_event(run_dir, {
                    "type": "workbench.launch_failed",
                    "status": "failed",
                    "attempt": int(metadata.get("attempt") or 1),
                })
                _update_run_metadata(run_dir, status="failed", pid=0, completed_at=now_iso())
                raise RuntimeError("Codex process could not be started.") from exc
            try:
                if process.stdin is None:
                    raise OSError("Codex prompt pipe is unavailable")
                process.stdin.write(prompt)
                process.stdin.flush()
                process.stdin.close()
                metadata.update({"status": "running", "pid": process.pid, "updated_at": now_iso()})
                write_json(run_dir / WEB_RUN_FILE, metadata)
                attempt = int(metadata.get("attempt") or 1)
                timeout_signal = threading.Event()
                watchdog = threading.Timer(WORKBENCH_RUN_TIMEOUT_SECONDS, _timeout_codex_process, args=(process, timeout_signal))
                watchdog.daemon = True
                consumer = threading.Thread(
                    target=_consume_codex_events,
                    args=(root, run_id, process, run_lock, watchdog, timeout_signal, attempt),
                    daemon=True,
                    name=f"tcx-web-{sanitize_id(run_id)}",
                )
                _ACTIVE_RUNS[key] = process
                consumer.start()
                watchdog.start()
            except Exception as exc:
                _ACTIVE_RUNS.pop(key, None)
                _terminate_and_reap(process)
                try:
                    _append_web_event(run_dir, {
                        "type": "workbench.launch_failed",
                        "status": "failed",
                        "attempt": int(metadata.get("attempt") or 1),
                    })
                    _update_run_metadata(run_dir, status="failed", pid=0, completed_at=now_iso())
                except Exception:
                    pass
                raise RuntimeError("Codex process could not be started.") from exc
    except Exception:
        _release_run_lock(run_lock)
        raise
    return {"workflow_run_id": run_id, "status": "running", "pid": process.pid}


def _consume_codex_events(
    root: Path,
    run_id: str,
    process: subprocess.Popen[str],
    run_lock: Path,
    watchdog: threading.Timer | None = None,
    timeout_signal: threading.Event | None = None,
    attempt: int = 1,
) -> None:
    run_dir = _run_dir(root, run_id)
    completed_terminal = False
    failed_terminal = False
    consume_failed = False
    return_code: int | None = None
    timeout_signal = timeout_signal or threading.Event()
    try:
        if process.stdout is not None:
            for line in process.stdout:
                event = _normalize_codex_event(line)
                if not event:
                    continue
                _append_web_event(run_dir, event)
                completed_terminal = completed_terminal or event["type"] == "turn.completed"
                failed_terminal = failed_terminal or event["type"] in {"turn.failed", "error"}
                if event.get("thread_id"):
                    _store_thread_authority(root, run_id, str(event["thread_id"]))
                    _update_run_metadata(run_dir, thread_id=event["thread_id"])
        return_code = process.wait()
    except Exception:
        consume_failed = True
        _terminate_and_reap(process)
        polled = process.poll()
        return_code = polled if isinstance(polled, int) else None
    finally:
        timed_out = timeout_signal.is_set()
        status = "completed" if not consume_failed and not timed_out and return_code == 0 and completed_terminal and not failed_terminal else "failed"
        try:
            if timed_out:
                _append_web_event(run_dir, {"type": "workbench.timed_out", "status": "failed", "attempt": attempt})
            process_exit_event: dict[str, Any] = {
                "type": "workbench.process_exited",
                "status": status,
                "attempt": attempt,
            }
            if return_code is not None:
                process_exit_event["return_code"] = return_code
            _append_web_event(run_dir, process_exit_event)
        except Exception:
            pass
        try:
            _update_run_metadata(run_dir, status=status, pid=0, completed_at=now_iso())
        except Exception:
            pass
        if watchdog is not None:
            watchdog.cancel()
        with _ACTIVE_RUNS_LOCK:
            key = _run_key(root, run_id)
            if _ACTIVE_RUNS.get(key) is process:
                _ACTIVE_RUNS.pop(key, None)
        _release_run_lock(run_lock)


def _timeout_codex_process(process: subprocess.Popen[str], timeout_signal: threading.Event) -> None:
    if process.poll() is not None:
        return
    timeout_signal.set()
    _terminate_and_reap(process)


def _normalize_codex_event(line: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(line)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    event_type = str(raw.get("type") or "")
    if event_type not in _CODEX_EVENT_TYPES:
        return None
    raw_status = str(raw.get("status") or "")
    event: dict[str, Any] = {
        "type": event_type,
        "status": raw_status if raw_status in _EVENT_STATUSES else "",
        "ts": now_iso(),
    }
    thread_id = raw.get("thread_id")
    if isinstance(thread_id, str) and not thread_id.startswith("-") and _SAFE_NAME.match(thread_id):
        event["thread_id"] = thread_id
    item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
    item_type = str(item.get("type") or "")
    if item_type in {"reasoning", "user_message", "input_text"}:
        return None
    if event_type.startswith("item.") and item_type not in _ITEM_TYPES:
        return None
    if item_type:
        event["item_type"] = item_type[:64]
    if item_type == "agent_message":
        event["message_available"] = True
    if item_type in {"mcp_tool_call", "web_search", "command_execution", "tool_call"}:
        name = redact_log_text(str(item.get("tool_name") or item.get("name") or ("shell" if item_type == "command_execution" else item_type)))
        if isinstance(name, str) and _SAFE_NAME.match(name):
            event["tool_name"] = name
    return event


def _require_analysis_request(prompt: str) -> None:
    intake = build_workflow_intake(prompt)
    lane = str((intake.get("deterministic_hint") or {}).get("lane") or "")
    if lane not in ANALYSIS_LANES or intake.get("secret_warning") or intake.get("connector_build"):
        raise ValueError("web-started Codex runs are analysis-only; order, approval, execution, broker, connector, and secret operations are blocked")


def _require_safe_followup(prompt: str) -> None:
    _require_safe_computer_use(prompt)
    intake = build_workflow_intake(prompt)
    lane = str((intake.get("deterministic_hint") or {}).get("lane") or "")
    if lane in {"order_ticket_draft_gate", "order_ticket_approval_execution_gate", "connector_build", "secret_warning"} or intake.get("secret_warning") or intake.get("connector_build"):
        raise ValueError("web follow-up is analysis-only; order, approval, execution, cancellation, broker, and secret operations are blocked")
    action_text = strip_negated_action_phrases(prompt)
    if _DANGEROUS_FOLLOWUP.search(action_text):
        raise ValueError("web follow-up is analysis-only; order, approval, execution, cancellation, broker, and secret operations are blocked")


def _require_safe_computer_use(prompt: str) -> None:
    if _SENSITIVE_PATH.search(prompt) or _COMPUTER_ACTION.search(prompt) or _INTERACTIVE_ACTION.search(prompt):
        raise ValueError("web-started Codex runs cannot perform shell, file-access, credential, or network-transfer requests")


def _verify_generated_runtime(root: Path) -> None:
    template_root = templates_dir() / "modules" / "codex-base" / "files"
    files = template_root / ".codex"
    hook_template = files / "hooks" / "tradingcodex_hook.py"
    hooks_template = files / "hooks.json"
    command = json.dumps(f"{workspace_launcher_command()} __hook", ensure_ascii=False)[1:-1]
    expected_hooks = render_template(hooks_template.read_text(encoding="utf-8"), {"TRADINGCODEX_HOOK_COMMAND_JSON_INNER": command}).encode()
    if _read_verified_runtime_file(root, ".codex/hooks/tradingcodex_hook.py") != hook_template.read_bytes() or _read_verified_runtime_file(root, ".codex/hooks.json") != expected_hooks:
        raise ValueError("generated TradingCodex hooks do not match the installed package")
    try:
        manifest = json.loads(_read_verified_runtime_file(root, WORKSPACE_MANIFEST_REL))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("generated TradingCodex workspace manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("generated TradingCodex workspace manifest is invalid")
    context = _generation_context(root, str(manifest.get("workspace_id") or "workbench-verification"))
    for relative in (Path("tcx"), Path("tcx.cmd"), Path(".tradingcodex/cli.py")):
        expected = render_template((template_root / relative).read_text(encoding="utf-8"), context).encode()
        if _read_verified_runtime_file(root, relative) != expected:
            raise ValueError(f"generated TradingCodex launcher does not match the installed package: {relative.as_posix()}")
    try:
        config = tomllib.loads(_read_verified_runtime_file(root, ".codex/config.toml").decode())
    except Exception as exc:
        raise ValueError("TradingCodex project config is unavailable") from exc
    if config.get("sandbox_mode") != "workspace-write":
        raise ValueError("TradingCodex project config must use workspace-write sandboxing")
    servers = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}
    if set(servers) != {"tradingcodex"}:
        raise ValueError("TradingCodex project config must contain only the canonical tradingcodex MCP server")
    server = servers["tradingcodex"] if isinstance(servers.get("tradingcodex"), dict) else {}
    args = server.get("args") if isinstance(server.get("args"), list) else []
    package_spec = context["TRADINGCODEX_MCP_PACKAGE_SPEC"]
    expected_env = {
        "TRADINGCODEX_HOME": context["TRADINGCODEX_HOME"],
        "TRADINGCODEX_HOME_SOURCE": context["TRADINGCODEX_HOME_SOURCE"],
        "TRADINGCODEX_MCP_AUTOSTART_SERVICE": "1",
        "TRADINGCODEX_MCP_PRINCIPAL": "head-manager",
        "TRADINGCODEX_SERVICE_ADDR": context["TRADINGCODEX_SERVICE_ADDR"],
        "TRADINGCODEX_WORKSPACE_ROOT": ".",
    }
    if context["TRADINGCODEX_DB_SOURCE"] == "environment_override":
        expected_env["TRADINGCODEX_DB_NAME"] = context["TRADINGCODEX_DB_PATH"]
    if (
        server.get("command") != "uvx"
        or server.get("enabled") is not True
        or server.get("cwd") != "."
        or server.get("env") != expected_env
        or server.get("enabled_tools") != list(AGENT_SPECS["head-manager"].mcp_allowlist)
        or server.get("default_tools_approval_mode") != "approve"
        or len(args) != 8
        or args[:2] != ["--refresh", "--from"]
        or args[2] != package_spec
        or args[3:] != ["python", "-m", "tradingcodex_cli", "mcp", "stdio"]
        or "tradingcodex" not in package_spec.lower()
    ):
        raise ValueError("canonical TradingCodex MCP server configuration is required")
    _verify_projected_codex_runtime(root, template_root, context, config)


def _verify_projected_codex_runtime(root: Path, template_root: Path, context: dict[str, str], config: dict[str, Any]) -> None:
    expected_root_text = render_template((template_root / ".codex/config.toml").read_text(encoding="utf-8"), context)
    expected_root_text = _replace_agent_model_policy(expected_root_text, resolve_agent_model_policy("head-manager"))
    expected_root_text = _replace_tradingcodex_enabled_tools(expected_root_text, AGENT_SPECS["head-manager"].mcp_allowlist)
    expected_root = tomllib.loads(expected_root_text)
    if set(config) != set(expected_root):
        raise ValueError("TradingCodex project config contains unsupported overrides")
    for key in expected_root:
        if key in {"permissions", "skills"}:
            continue
        if config.get(key) != expected_root.get(key):
            raise ValueError(f"TradingCodex project config does not match the generated runtime: {key}")
    if not _permissions_preserve_generated_denies(config.get("permissions"), expected_root.get("permissions")):
        raise ValueError("TradingCodex project permission profiles do not match the generated runtime")

    state = build_projection_state(root)
    if any(agent.get("validation_errors") for agent in state.get("agents", {}).values()):
        raise ValueError("TradingCodex agent projection contains validation errors")
    _verify_skill_projection(root, Path(".codex/config.toml"), config, "head-manager", state)

    prompt_relative = Path(".codex/prompts/base_instructions/head-manager.md")
    prompt_template = render_template((template_root / prompt_relative).read_text(encoding="utf-8"), context).rstrip()
    expected_prompt = (prompt_template + "\n\n" + _render_core_extension_boundary().rstrip() + "\n").encode()
    if _read_verified_runtime_file(root, prompt_relative) != expected_prompt:
        raise ValueError("generated TradingCodex head-manager instructions do not match the installed package")

    agent_templates = templates_dir() / "modules" / "fixed-subagents" / "files" / ".codex" / "agents"
    for role in AGENT_SPECS:
        if role == "head-manager":
            continue
        relative = Path(".codex/agents") / f"{role}.toml"
        try:
            actual = tomllib.loads(_read_verified_runtime_file(root, relative).decode())
        except Exception as exc:
            raise ValueError(f"generated TradingCodex role config is unavailable: {role}") from exc
        expected_text = render_template((agent_templates / f"{role}.toml").read_text(encoding="utf-8"), context)
        expected_text = _replace_agent_model_policy(expected_text, resolve_agent_model_policy(role))
        expected_text = _replace_developer_instructions(
            expected_text,
            "",
            _render_role_skill_source_block(root, role, state["agents"][role]["effective_skills"]),
        )
        expected_text = _replace_tradingcodex_enabled_tools(expected_text, AGENT_SPECS[role].mcp_allowlist)
        expected = tomllib.loads(expected_text)
        _verify_skill_projection(root, relative, actual, role, state)
        actual_without_skills = {key: value for key, value in actual.items() if key != "skills"}
        if actual_without_skills != expected:
            raise ValueError(f"generated TradingCodex role config does not match the installed package: {role}")

    skill_template_root = templates_dir() / "modules" / "repo-skills" / "files"
    for skill_id, spec in SKILL_SPECS.items():
        if spec.scope == "mainagent":
            relative = Path(".agents/skills") / skill_id / "SKILL.md"
        elif spec.scope == "subagent_shared":
            relative = Path(".tradingcodex/subagents/skills/shared") / skill_id / "SKILL.md"
        else:
            relative = Path(".tradingcodex/subagents/skills") / (spec.owner_roles[0] if spec.owner_roles else "") / skill_id / "SKILL.md"
        template = skill_template_root / relative
        expected = render_template(template.read_text(encoding="utf-8"), context).encode()
        if _read_verified_runtime_file(root, relative) != expected:
            raise ValueError(f"generated TradingCodex core skill does not match the installed package: {skill_id}")


def _verify_skill_projection(root: Path, config_relative: Path, config: dict[str, Any], role: str, state: dict[str, Any]) -> None:
    projection = inspect_skill_projection(root, role, state)
    if not projection.get("ok") or projection.get("unregistered_paths"):
        raise ValueError(f"TradingCodex skill projection does not match the managed runtime: {role}")
    skills = config.get("skills") if isinstance(config.get("skills"), dict) else {}
    blocks = skills.get("config") if isinstance(skills.get("config"), list) else []
    if len(blocks) != len(projection.get("expected_paths") or []):
        raise ValueError(f"TradingCodex skill projection count does not match the managed runtime: {role}")
    for block in blocks:
        if not isinstance(block, dict) or set(block) != {"path", "enabled"} or block.get("enabled") is not True:
            raise ValueError(f"TradingCodex skill projection contains an unsupported entry: {role}")
        raw = str(block.get("path") or "")
        normalized = Path(posixpath.normpath((config_relative.parent / raw).as_posix()))
        if normalized.is_absolute() or not normalized.parts or normalized.parts[0] == "..":
            raise ValueError(f"TradingCodex skill projection path escapes the workspace: {role}")
        _read_verified_runtime_file(root, normalized)


def _permissions_preserve_generated_denies(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for key, value in expected.items():
            if key not in actual or not _permissions_preserve_generated_denies(actual[key], value):
                return False
        return all(key in expected or value == "deny" for key, value in actual.items())
    return actual == expected


def _read_verified_runtime_file(root: Path, relative: str | Path) -> bytes:
    workspace_root = root.expanduser().resolve(strict=True)
    relative_path = Path(relative)
    if relative_path.is_absolute() or not relative_path.parts or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise ValueError("generated TradingCodex runtime path is invalid")
    candidate = workspace_root / relative_path

    def verify_components() -> os.stat_result:
        current = workspace_root
        for index, part in enumerate(relative_path.parts):
            current /= part
            try:
                entry = current.lstat()
            except OSError as exc:
                raise ValueError(f"generated TradingCodex runtime file is unavailable: {relative_path.as_posix()}") from exc
            if stat.S_ISLNK(entry.st_mode):
                raise ValueError(f"generated TradingCodex runtime paths must not contain symlinks: {relative_path.as_posix()}")
            if index < len(relative_path.parts) - 1 and not stat.S_ISDIR(entry.st_mode):
                raise ValueError(f"generated TradingCodex runtime parent is not a directory: {relative_path.as_posix()}")
        if not stat.S_ISREG(entry.st_mode):
            raise ValueError(f"generated TradingCodex runtime path is not a regular file: {relative_path.as_posix()}")
        return entry

    before = verify_components()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ValueError(f"generated TradingCodex runtime file cannot be opened safely: {relative_path.as_posix()}") from exc
    try:
        opened = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read()
    finally:
        os.close(descriptor)
    after = verify_components()
    if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
        raise ValueError(f"generated TradingCodex runtime file changed during verification: {relative_path.as_posix()}")
    return content


def _codex_feature_args() -> list[str]:
    return ["--enable", "hooks", *[part for feature in _DISABLED_CODEX_FEATURES for part in ("--disable", feature)]]


def _head_manager_model_args() -> list[str]:
    policy = resolve_agent_model_policy("head-manager")
    return ["-m", str(policy["resolved_model"]), "-c", f'model_reasoning_effort="{policy["reasoning_effort"]}"']


def _codex_environment(root: Path, run_id: str, *, followup: bool) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not _SENSITIVE_ENV.search(key)}
    env.update({
        "TRADINGCODEX_WORKSPACE_ROOT": str(root),
        "TRADINGCODEX_WORKFLOW_RUN_ID": run_id,
        "TRADINGCODEX_WORKFLOW_FOLLOWUP": "1" if followup else "0",
        "TRADINGCODEX_WORKBENCH_RUN": "1",
    })
    return env


def _investor_context_status(root: Path) -> dict[str, Any]:
    context = read_investor_context(root)
    return {
        "configured": bool(context.get("configured")),
        "enabled_by_default": bool(context.get("enabled_by_default", True)),
        "source": str(context.get("source") or "none"),
        "path": str(context.get("path") or ""),
        "content_hash": str(context.get("content_hash") or ""),
        "field_count": len(context.get("fields") or {}),
        "updated_at": str(context.get("updated_at") or ""),
    }


def _preview_signature(
    prompt: str,
    *,
    skill_id: str,
    strategy_binding: dict[str, Any],
    context_binding: dict[str, Any],
    use_investor_context: bool | None,
) -> str:
    context_requested = (
        bool(context_binding.get("enabled_by_default", True))
        if use_investor_context is None
        else bool(use_investor_context)
    )
    return stable_hash({
        "request": prompt,
        "method_id": skill_id,
        "strategy": _public_strategy_binding(strategy_binding),
        "use_investor_context": context_requested,
        "investor_context": _public_context_binding(context_binding),
    })


def _public_strategy_binding(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "strategy_id": _public_text(raw.get("strategy_id"), limit=128),
        "source_file": _public_text(raw.get("source_file"), limit=500),
        "content_hash": _public_text(raw.get("content_hash"), limit=80),
        "snapshot_path": _public_text(raw.get("snapshot_path"), limit=500),
    }


def _public_context_binding(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "applied": bool(raw.get("applied")),
        "configured": bool(raw.get("configured")),
        "enabled_by_default": bool(raw.get("enabled_by_default", True)),
        "source": _public_text(raw.get("source"), limit=80),
        "path": _public_text(raw.get("path"), limit=500),
        "content_hash": _public_text(raw.get("content_hash"), limit=80),
        "snapshot_path": _public_text(raw.get("snapshot_path"), limit=500),
    }


def _skill_prompt(
    root: Path,
    skill_id: str,
    prompt: str,
    *,
    strategy_binding: dict[str, Any] | None = None,
    context_binding: dict[str, Any] | None = None,
) -> str:
    instructions = ["Use $tcx-workflow."]
    if skill_id:
        detail = get_skill_detail(root, skill_id)
        if not detail.get("startable"):
            raise ValueError(f"skill cannot start a web analysis run: {skill_id}")
        if detail.get("source") == "strategy":
            raise ValueError("select strategies with strategy_id, separately from the work method")
        if detail.get("source") == "optional":
            roles = ", ".join(str(role) for role in detail.get("owner_roles") or [])
            instructions.append(f"Route the relevant recorded stage through {roles or 'the owning role'} and require that role to apply ${skill_id} as the user-selected optional skill.")
        elif skill_id == "decision-memory":
            instructions.append("Apply $decision-memory as the user-selected review and replay procedure.")
        instructions.append(f"Requested task focus: {detail['label']} ({skill_id}).")
    strategy = strategy_binding if isinstance(strategy_binding, dict) else {}
    if strategy.get("strategy_id"):
        source = strategy.get("snapshot_path") or strategy.get("source_file")
        instructions.append(f"Apply ${strategy['strategy_id']} as fixed strategy context from {source} with SHA-256 {strategy.get('content_hash')}; do not substitute a newer strategy file.")
    context = context_binding if isinstance(context_binding, dict) else {}
    if context.get("applied"):
        source = context.get("snapshot_path") or context.get("path")
        instructions.append(f"Apply the fixed workspace investor context from {source} with content hash {context.get('content_hash')}.")
    elif context.get("configured"):
        instructions.append("Workspace investor context is disabled for this run; do not use it for personalized recommendation or sizing.")
    instructions.append("Preserve role and safety boundaries.")
    return " ".join(instructions) + f"\n\n{prompt}"


def list_recent_runs(root: Path | str, *, limit: int = 30) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    base = root / ".tradingcodex/mainagent/workflows"
    records = []
    for path in base.glob(f"*/{WEB_RUN_FILE}") if base.exists() else []:
        try:
            safe = _safe_workflow_path(root, path.relative_to(root), required=True)
            item = json.loads(safe.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        records.append({
            "workflow_run_id": str(item.get("workflow_run_id") or path.parent.name),
            "status": str(item.get("status") or "unknown"),
            "original_request": str(item.get("original_request") or ""),
            "skill_id": str(item.get("skill_id") or ""),
            "attempt": int(item.get("attempt") or 0),
            "started_at": str(item.get("started_at") or ""),
            "updated_at": str(item.get("updated_at") or ""),
        })
    records.sort(key=lambda item: item["updated_at"] or item["started_at"], reverse=True)
    return records[: max(1, min(int(limit), 100))]


def _validated_workspace(root: Path | str) -> Path:
    path = Path(root).expanduser().resolve()
    if not path.is_dir() or not (path / WORKSPACE_MANIFEST_REL).is_file():
        raise ValueError("an attached TradingCodex workspace is required")
    return path


def _validated_prompt(prompt: str) -> str:
    value = str(prompt or "").strip()
    if not value:
        raise ValueError("prompt is required")
    if len(value) > 20000:
        raise ValueError("prompt is too long")
    return value


def _safe_workflow_path(root: Path, relative: Path | str, *, required: bool) -> Path:
    root = root.expanduser().resolve()
    raw = Path(relative)
    if raw.is_absolute():
        raw = raw.relative_to(root)
    lexical = root / raw
    current = root
    for part in raw.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("workflow state paths must not contain symlinks")
    path = safe_workspace_path(
        root,
        raw.as_posix(),
        allowed_roots=(Path(".tradingcodex/mainagent"),),
    )
    if required and not path.is_file():
        raise ValueError(f"workflow state is unavailable: {raw.as_posix()}")
    return path


def _read_workflow_record(root: Path, relative: Path | str, *, required: bool = True) -> dict[str, Any]:
    path = _safe_workflow_path(root, relative, required=required)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"workflow state is unavailable: {Path(relative).as_posix()}") from exc
    if not isinstance(value, dict):
        raise ValueError("workflow state must be a JSON object")
    return value


def _safe_run_file(run_dir: Path, name: str, *, required: bool) -> Path:
    marker = next((parent for parent in run_dir.parents if parent.name == ".tradingcodex"), None)
    if marker is None:
        raise ValueError("workflow run directory is outside the attached workspace")
    root = marker.parent
    return _safe_workflow_path(root, (run_dir / name).relative_to(root), required=required)


def _public_text(value: Any, *, limit: int = 1000) -> str:
    return redact_log_text(str(value or ""))[:limit]


def _public_strings(value: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_public_text(item, limit=500) for item in value[:limit] if isinstance(item, (str, int, float, bool))]


def _public_intake(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    deterministic = value.get("deterministic_hint") if isinstance(value.get("deterministic_hint"), dict) else {}
    normalized = value.get("normalized_intent") if isinstance(value.get("normalized_intent"), dict) else {}
    return {
        "schema_version": int(value.get("schema_version") or 1),
        "workflow_run_id": _public_text(value.get("workflow_run_id"), limit=180),
        "created_at": _public_text(value.get("created_at"), limit=80),
        "requires_workflow_planning": bool(value.get("requires_workflow_planning")),
        "investment_candidate": bool(value.get("investment_candidate")),
        "explicit_negations": _public_strings(value.get("explicit_negations")),
        "normalized_intent": {
            "requested_actions": _public_strings(normalized.get("requested_actions")),
            "forbidden_actions": _public_strings(normalized.get("forbidden_actions")),
            "unresolved_actions": _public_strings(normalized.get("unresolved_actions")),
            "language": _public_text(normalized.get("language"), limit=40),
            "confidence": normalized.get("confidence") if isinstance(normalized.get("confidence"), (int, float)) else None,
            "requires_confirmation": bool(normalized.get("requires_confirmation")),
        },
        "deterministic_hint": {
            "lane": _public_text(deterministic.get("lane"), limit=120),
            "roles": _public_strings(deterministic.get("roles")),
            "blocked_actions": _public_strings(deterministic.get("blocked_actions")),
        },
        "heuristic_lane": _public_text(value.get("heuristic_lane"), limit=120),
        "heuristic_roles": _public_strings(value.get("heuristic_roles")),
        "blocked_actions": _public_strings(value.get("blocked_actions")),
        "strategy_binding": _public_strategy_binding(value.get("strategy_binding")),
        "investor_context_binding": _public_context_binding(value.get("investor_context_binding")),
        "intake_hash": _public_text(value.get("intake_hash"), limit=80),
    }


def _public_plan(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    stages = []
    for raw in value.get("stages") or []:
        if not isinstance(raw, dict):
            continue
        stages.append({
            "stage_id": _public_text(raw.get("stage_id"), limit=120),
            "roles": _public_strings(raw.get("roles")),
            "depends_on": _public_strings(raw.get("depends_on")),
            "dispatch_mode": _public_text(raw.get("dispatch_mode"), limit=40),
            "purpose": _public_text(raw.get("purpose"), limit=1000),
            "exit_criteria": _public_strings(raw.get("exit_criteria")),
        })
    validation = value.get("validation") if isinstance(value.get("validation"), dict) else {}
    return {
        "schema_version": int(value.get("schema_version") or 1),
        "workflow_run_id": _public_text(value.get("workflow_run_id"), limit=180),
        "lane": _public_text(value.get("lane"), limit=120),
        "stages": stages[:30],
        "blocked_actions": _public_strings(value.get("blocked_actions")),
        "user_constraints": _public_strings(value.get("user_constraints")),
        "profile_gaps": _public_strings(value.get("profile_gaps")),
        "strategy_binding": _public_strategy_binding(value.get("strategy_binding")),
        "investor_context_binding": _public_context_binding(value.get("investor_context_binding")),
        "stop_condition": _public_text(value.get("stop_condition"), limit=1000),
        "planner_rationale": _public_text(value.get("planner_rationale"), limit=1000),
        "plan_hash": _public_text(value.get("plan_hash"), limit=80),
        "recorded_at": _public_text(value.get("recorded_at"), limit=80),
        "validation": {
            "ok": validation.get("ok") is True,
            "errors": _public_strings(validation.get("errors")),
            "warnings": _public_strings(validation.get("warnings")),
            "roles": _public_strings(validation.get("roles")),
        },
    }


def _public_state(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    tasks = []
    for raw in value.get("pending_tasks") or []:
        if not isinstance(raw, dict):
            continue
        process_by_role = raw.get("process_by_role") if isinstance(raw.get("process_by_role"), dict) else {}
        tasks.append({
            "task_id": _public_text(raw.get("task_id"), limit=180),
            "stage_id": _public_text(raw.get("stage_id"), limit=120),
            "roles": _public_strings(raw.get("roles")),
            "role": _public_text(raw.get("role"), limit=120),
            "depends_on": _public_strings(raw.get("depends_on")),
            "status": _public_text(raw.get("status"), limit=80),
            "stage_gate": _public_text(raw.get("stage_gate"), limit=80),
            "process_status": _public_text(raw.get("process_status"), limit=80),
            "process_by_role": {
                _public_text(role, limit=120): _public_text(status, limit=80)
                for role, status in list(process_by_role.items())[:30]
                if isinstance(role, str) and isinstance(status, str)
            },
            "active_roles": _public_strings(raw.get("active_roles")),
            "completed_roles": _public_strings(raw.get("completed_roles")),
        })
    return {
        "workflow_run_id": _public_text(value.get("workflow_run_id"), limit=180),
        "lane": _public_text(value.get("lane") or value.get("workflow_lane"), limit=120),
        "plan_hash": _public_text(value.get("plan_hash"), limit=80),
        "state_revision": int(value.get("state_revision") or 0),
        "supervisor_round": int(value.get("supervisor_round") or 0),
        "selected_team": _public_strings(value.get("selected_team")),
        "pending_tasks": tasks[:100],
        "blocked_actions": _public_strings(value.get("blocked_actions")),
        "terminal_action": _public_text(value.get("terminal_action"), limit=80),
        "stop_reason": _public_text(value.get("stop_reason"), limit=500),
        "updated_at": _public_text(value.get("updated_at"), limit=80),
    }


def _accepted_synthesis(root: Path, artifacts: list[dict[str, Any]], state: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if str(state.get("terminal_action") or "") != "synthesize":
        return None, ""
    plan_hash = str(state.get("plan_hash") or "")
    accepted_hashes = {
        str(reference.get("content_hash"))
        for task in state.get("pending_tasks") or []
        if isinstance(task, dict)
        for reference in (task.get("accepted_artifacts_by_role") or {}).values()
        if isinstance(reference, dict) and reference.get("content_hash")
    }
    if not plan_hash or not accepted_hashes:
        return None, "accepted synthesis artifact is not ready"
    quality_failed = False
    for item in artifacts:
        if (
            item.get("artifact_type") != "synthesis_report"
            or item.get("handoff_state") != "accepted"
            or item.get("producer_role") != "head-manager"
            or item.get("plan_hash") != plan_hash
        ):
            continue
        artifact = get_research_artifact(root, {"artifact_id": str(item.get("artifact_id") or ""), "include_markdown": True})
        markdown = str(artifact.pop("markdown", ""))
        actual_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        supplied_hashes = {
            str(candidate)
            for candidate in (artifact.get("input_artifact_hashes") or {}).values()
            if candidate
        }
        if artifact.get("content_hash") != actual_hash or supplied_hashes != accepted_hashes:
            continue
        quality = evaluate_decision_quality(
            root,
            str(artifact.get("path") or ""),
            workflow_lane=str(state.get("lane") or ""),
            strict=True,
        )
        if quality.get("status") != "pass":
            quality_failed = True
            continue
        preview = render_markdown_preview(markdown, source_file=str(artifact.get("path") or ""), source_label="research artifact")
        return _json_safe({**artifact, "preview": {"heading": preview.heading, "html": preview.html}}), ""
    reason = "accepted synthesis artifact failed its quality gate" if quality_failed else "accepted synthesis artifact is not ready"
    return None, reason


def _run_dir(root: Path, run_id: str) -> Path:
    if sanitize_id(run_id) != run_id:
        raise ValueError("invalid workflow run id")
    return _safe_workflow_path(root, Path(workflow_loop_relpath(run_id)).parent, required=False)


def _existing_run_dir(root: Path, run_id: str) -> Path:
    path = _run_dir(root, run_id)
    if not path.is_dir():
        raise ValueError(f"workflow run not found: {run_id}")
    return path


def _run_metadata(run_dir: Path) -> dict[str, Any]:
    value = read_json(_safe_run_file(run_dir, WEB_RUN_FILE, required=False), {})
    return value if isinstance(value, dict) else {}


def _update_run_metadata(run_dir: Path, **updates: Any) -> None:
    metadata = _run_metadata(run_dir)
    metadata.update(updates)
    metadata["updated_at"] = now_iso()
    write_json(_safe_run_file(run_dir, WEB_RUN_FILE, required=False), metadata)


def _append_web_event(run_dir: Path, event: dict[str, Any]) -> None:
    append_jsonl(_safe_run_file(run_dir, WEB_EVENTS_FILE, required=False), {"ts": event.get("ts") or now_iso(), **event})


def _read_normalized_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines()[-500:]:
        try:
            raw = json.loads(line)
        except Exception:
            continue
        event = _validated_stored_event(raw)
        if event:
            events.append(event)
    return events


def _validated_stored_event(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    event_type = str(raw.get("type") or "")
    if event_type not in _CODEX_EVENT_TYPES | _WORKBENCH_EVENT_TYPES:
        return None
    event: dict[str, Any] = {"type": event_type}
    status = str(raw.get("status") or "")
    if status in _EVENT_STATUSES:
        event["status"] = status
    timestamp = str(raw.get("ts") or "")
    if timestamp:
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            event["ts"] = timestamp[:64]
    thread_id = raw.get("thread_id")
    if isinstance(thread_id, str) and not thread_id.startswith("-") and _SAFE_NAME.match(thread_id):
        event["thread_id"] = thread_id
    item_type = str(raw.get("item_type") or "")
    if item_type in _ITEM_TYPES:
        event["item_type"] = item_type
    tool_name = str(raw.get("tool_name") or "")
    if tool_name and not tool_name.startswith("-") and _SAFE_NAME.match(tool_name):
        event["tool_name"] = tool_name
    if raw.get("message_available") is True:
        event["message_available"] = True
    attempt = raw.get("attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and 0 < attempt <= 10000:
        event["attempt"] = attempt
    return_code = raw.get("return_code")
    if isinstance(return_code, int) and not isinstance(return_code, bool) and -255 <= return_code <= 255:
        event["return_code"] = return_code
    return event


def _thread_id(events: list[dict[str, Any]]) -> str:
    return next((str(event["thread_id"]) for event in reversed(events) if event.get("thread_id")), "")


def _run_key(root: Path, run_id: str) -> str:
    return f"{root}:{run_id}"


def _run_lock_path(root: Path, run_id: str) -> Path:
    directory = _run_state_dir()
    digest = _run_state_key(root, run_id)
    return directory / f"{digest}.lock"


def _run_state_dir() -> Path:
    directory = tradingcodex_db_path().parent / "workbench-locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _run_state_key(root: Path, run_id: str) -> str:
    return hashlib.sha256(f"{root.resolve()}:{run_id}".encode()).hexdigest()


def _thread_authority_path(root: Path, run_id: str) -> Path:
    return _run_state_dir() / f"{_run_state_key(root, run_id)}.thread.json"


def _store_thread_authority(root: Path, run_id: str, thread_id: str) -> None:
    if thread_id.startswith("-") or not _SAFE_NAME.match(thread_id):
        return
    write_json(_thread_authority_path(root, run_id), {"thread_id": thread_id, "updated_at": now_iso()})


def _service_thread_id(root: Path, run_id: str) -> str:
    value = read_json(_thread_authority_path(root, run_id), {})
    thread_id = str(value.get("thread_id") or "") if isinstance(value, dict) else ""
    return thread_id if thread_id and not thread_id.startswith("-") and _SAFE_NAME.match(thread_id) else ""


def _clear_thread_authority(root: Path, run_id: str) -> None:
    try:
        _thread_authority_path(root, run_id).unlink()
    except FileNotFoundError:
        pass


def _claim_run(root: Path, run_id: str) -> Path:
    path = _run_lock_path(root, run_id)
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                owner_pid = int(path.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                owner_pid = 0
            metadata = _run_metadata(_run_dir(root, run_id))
            child_pid = int(metadata.get("pid") or 0)
            if _process_alive(owner_pid) or (str(metadata.get("status") or "") in {"starting", "running"} and _process_alive(child_pid)):
                raise WorkbenchConflict("workflow run already has an active Codex process")
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return path
    raise WorkbenchConflict("workflow run already has an active Codex process")


def _release_run_lock(path: Path) -> None:
    try:
        owner_pid = int(path.read_text(encoding="utf-8").strip() or 0)
        if owner_pid == os.getpid():
            path.unlink()
    except (FileNotFoundError, OSError, ValueError):
        pass


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _terminate_and_reap(process: subprocess.Popen[str]) -> None:
    try:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass


def _run_agents(state: dict[str, Any]) -> list[dict[str, Any]]:
    by_role: dict[str, str] = {}
    for task in state.get("pending_tasks") or []:
        if not isinstance(task, dict):
            continue
        process_by_role = task.get("process_by_role") if isinstance(task.get("process_by_role"), dict) else {}
        for role in task.get("roles") or ([task.get("role")] if task.get("role") else []):
            by_role[str(role)] = str(process_by_role.get(role) or task.get("status") or "queued")
    return [{"role": role, "label": AGENT_SPECS[role].label if role in AGENT_SPECS else role, "status": status} for role, status in by_role.items()]


def _latest_workflow(root: Path) -> dict[str, Any]:
    intake = _read_workflow_record(root, LATEST_INTAKE_PATH, required=False)
    plan = _read_workflow_record(root, LATEST_PLAN_PATH, required=False)
    state = _read_workflow_record(root, LATEST_LOOP_STATE_PATH, required=False)
    return {
        "intake": _public_intake(intake),
        "plan": _public_plan(plan),
        "state": _public_state(state),
    }


def _agent_catalog(root: Path) -> list[dict[str, Any]]:
    state = build_projection_state(root)
    return [{
        "role": role,
        "label": item.get("label") or role,
        "group": item.get("group") or "",
        "purpose": item.get("purpose") or "",
        "skills": item.get("effective_skills") or item.get("builtin_skills") or [],
        "permission_profile": item.get("permission_profile") or "",
        "validation_errors": item.get("validation_errors") or [],
    } for role, item in state.get("agents", {}).items()]


def _recent_activity(root: Path) -> dict[str, Any]:
    items = list_recent_activity(root, limit=50)
    return {"items": items, "tool_names": list(dict.fromkeys(item["title"] for item in items if item.get("kind") == "MCP"))}


def _skill_path(root: Path, skill_id: str, item: dict[str, Any]) -> Path:
    raw = str(item.get("resolved_source_file") or item.get("source_file") or "")
    candidate = Path(raw).expanduser() if raw else Path()
    candidate = candidate if candidate.is_absolute() else root / candidate
    if raw:
        resolved_root = root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError:
            pass
        else:
            if resolved_candidate.is_file():
                return resolved_candidate
    spec = SKILL_SPECS.get(skill_id)
    base = templates_dir() / "modules" / "repo-skills" / "files"
    if spec and spec.scope == "subagent_shared":
        return base / ".tradingcodex/subagents/skills/shared" / skill_id / "SKILL.md"
    if spec and spec.scope == "subagent_role":
        return base / ".tradingcodex/subagents/skills" / (spec.owner_roles[0] if spec.owner_roles else "") / skill_id / "SKILL.md"
    return base / ".agents/skills" / skill_id / "SKILL.md"


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _section(loader: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"ok": True, "data": _json_safe(loader())}
    except Exception as exc:
        return {"ok": False, "error": {"code": type(exc).__name__, "message": redact_log_text(str(exc))[:500]}}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Path, Decimal)):
        return str(value)
    return value
