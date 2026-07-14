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
from tradingcodex_service.application.analysis_runs import (
    ANALYSIS_RUNS_ROOT,
    begin_analysis_run,
    explicit_investment_brain_invocation,
    new_analysis_run_id,
    read_analysis_run,
    select_investor_context_binding,
    select_strategy_binding,
)
from tradingcodex_service.application.artifact_bindings import verify_authenticated_artifact_binding
from tradingcodex_service.application.artifact_quality import evaluate_decision_quality
from tradingcodex_service.application.brokers import list_broker_connections
from tradingcodex_service.application.build_gateway import BuildInvocationError, parse_build_invocation
from tradingcodex_service.application.common import (
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
from tradingcodex_service.application.execution_gateway import reserved_native_execution_token
from tradingcodex_service.application.harness import list_recent_activity
from tradingcodex_service.application.investor_context import read_investor_context
from tradingcodex_service.application.markdown_preview import read_markdown_preview, render_markdown_preview
from tradingcodex_service.application.orders import list_order_tickets
from tradingcodex_service.application.portfolio import list_positions
from tradingcodex_service.application.research import get_research_artifact, list_research_artifacts
from tradingcodex_service.application.runtime import WORKSPACE_MANIFEST_REL, active_profile_for_workspace, tradingcodex_db_path, workspace_context_payload
from tradingcodex_service.application.workspaces import workspace_options
from tradingcodex_service.log_safety import redact_log_text


WEB_RUN_FILE = "web-run.json"
WEB_EVENTS_FILE = "web-run-events.jsonl"
_SENSITIVE_ENV = re.compile(
    r"secret|token|password|passwd|credential|api[_-]?key|private[_-]?key|access[_-]?key|"
    r"(^|_)(?:key|auth|authorization|dsn|database_url|db_url|cookie|session|connection_string)(?:$|_)",
    re.I,
)
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
_STORED_EVENT_FIELDS = {"type", "status", "ts", "thread_id", "item_type", "tool_name", "message_available", "attempt", "return_code"}
_THREAD_AUTHORITY_FIELDS = {"schema_version", "workflow_run_id", "thread_id", "updated_at"}
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
        if skill_id.startswith("investment-brain-"):
            continue
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
            skill_id in {"tcx-workflow", "tcx-memory"} or active_strategy or active_optional or bool(spec and spec.scope != "mainagent")
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
        "scope_review": {
            "orchestration": "codex_native",
            "team_selection": "head_manager_dynamic",
            "service_scope": "persistence_policy_execution",
            "analysis_only": True,
        },
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
    strategy_binding, _ = select_strategy_binding(root, strategy_id)
    context_binding, _ = select_investor_context_binding(root, use_investor_context)
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
    run_id = new_analysis_run_id()
    run_dir = _run_dir(root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    run_record = begin_analysis_run(
        root,
        runtime_prompt,
        run_id=run_id,
        strategy_binding=strategy_binding,
        context_binding=context_binding,
    )
    strategy_binding = run_record["strategy_binding"]
    context_binding = run_record["investor_context_binding"]
    runtime_prompt = _skill_prompt(root, skill_id, prompt, strategy_binding=strategy_binding, context_binding=context_binding)
    prompt_sha256 = hashlib.sha256(runtime_prompt.encode("utf-8")).hexdigest()
    runtime_prompt = _bound_workflow_prompt(runtime_prompt, run_id)
    metadata = {
        "schema_version": 1,
        "workflow_run_id": run_id,
        "status": "starting",
        "actor": actor,
        "skill_id": skill_id,
        "strategy_binding": strategy_binding,
        "investor_context_binding": context_binding,
        "preview_signature": preview_signature,
        "prompt_sha256": prompt_sha256,
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
        "-c",
        _trusted_project_config_arg(root),
        "-c",
        'mcp_servers.tradingcodex.required=true',
        *_head_manager_model_args(),
        *_codex_feature_args(),
        "-C",
        str(root),
        "--skip-git-repo-check",
        "--json",
        "-s",
        "read-only",
        "-c",
        'approval_policy="never"',
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
    _require_safe_followup(prompt)
    run_dir = _existing_run_dir(root, run_id)
    metadata = _run_metadata(run_dir)
    current = get_run_detail(root, run_id)
    if current["status"] in {"starting", "running"}:
        raise WorkbenchConflict("workflow run already has an active Codex process")
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
        "-c",
        _trusted_project_config_arg(root),
        "-c",
        'mcp_servers.tradingcodex.required=true',
        *_head_manager_model_args(),
        *_codex_feature_args(),
        "--skip-git-repo-check",
        "--json",
        "-c",
        'sandbox_mode="read-only"',
        "-c",
        'approval_policy="never"',
        "--dangerously-bypass-hook-trust",
        thread_id,
        "-",
    ]
    return _launch(root, run_id, argv, metadata, prompt, followup=True)


def get_run_detail(root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(root).resolve()
    run_dir = _existing_run_dir(root, run_id)
    metadata = _run_metadata(run_dir)
    run_record = read_analysis_run(root, run_id)
    if not run_record:
        raise ValueError("analysis run record is unavailable")
    events = _read_normalized_events(_safe_run_file(run_dir, WEB_EVENTS_FILE, required=False))
    public_events = [{key: value for key, value in event.items() if key != "thread_id"} for event in events]
    key = _run_key(root, run_id)
    with _ACTIVE_RUNS_LOCK:
        process = _ACTIVE_RUNS.get(key)
    metadata_status = str(metadata.get("status") or "waiting")
    persisted_pid = int(metadata.get("pid") or 0)
    active = bool(process and process.poll() is None) or (
        metadata_status in {"starting", "running"} and _process_alive(persisted_pid)
    )
    process_status = "running" if active else metadata_status
    if process_status in {"starting", "running"} and not active:
        process_status = "failed"

    artifacts = list_research_artifacts(root, {"workflow_run_id": run_id, "limit": 200})["artifacts"]
    forecasts = list_forecasts(root, {"workflow_run_id": run_id, "limit": 200}).get("forecasts", [])[:100]
    final_output, synthesis_reason = _accepted_synthesis(root, artifacts, run_id)
    status = process_status
    incomplete_reason = ""
    if not active and process_status == "completed":
        if final_output:
            status = "completed"
        else:
            status = "waiting"
            incomplete_reason = synthesis_reason or "Codex finished without a run-local synthesis artifact"

    current_attempt = int(metadata.get("attempt") or 0)
    timed_out = any(
        event.get("type") == "workbench.timed_out" and event.get("attempt") == current_attempt
        for event in public_events
    )
    error = None
    if process_status == "failed":
        error = {
            "code": "process_timeout" if timed_out else "process_interrupted",
            "message": "Codex process exceeded the 30-minute workbench limit." if timed_out else "Codex process ended without a successful terminal event.",
        }
    return _json_safe({
        "workflow_run_id": run_id,
        "original_request": redact_log_text(str(metadata.get("original_request") or ""))[:500],
        "status": status,
        "process_status": process_status,
        "pid": int(metadata.get("pid") or 0),
        "attempt": current_attempt,
        "orchestration": "codex_native",
        "method_id": str(metadata.get("skill_id") or ""),
        "strategy_binding": _public_strategy_binding(run_record.get("strategy_binding")),
        "investor_context_binding": _public_context_binding(run_record.get("investor_context_binding")),
        "run": {
            "created_at": _public_text(run_record.get("created_at"), limit=80),
            "request_sha256": _public_text(run_record.get("request_sha256"), limit=80),
            "record_hash": _public_text(run_record.get("record_hash"), limit=80),
            "orchestration_owner": "codex-head-manager",
        },
        "agents": _run_agents_from_session(root, run_id),
        "activity": public_events[-200:],
        "artifacts": artifacts,
        "forecasts": forecasts,
        "final_output": final_output,
        "blocked_actions": [],
        "stop_reason": "web_run_timeout" if timed_out else incomplete_reason or ("service_process_interrupted" if process_status == "failed" else ""),
        "error": error,
    })



def _launch(root: Path, run_id: str, argv: list[str], metadata: dict[str, Any], prompt: str, *, followup: bool) -> dict[str, Any]:
    env = _codex_environment(root, run_id, followup=followup, metadata=metadata)
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
    except json.JSONDecodeError as exc:
        raise ValueError("Codex emitted invalid JSON event output") from exc
    if not isinstance(raw, dict):
        raise ValueError("Codex event output must be an object")
    event_type = raw.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("Codex event output must have a string type")
    if event_type not in _CODEX_EVENT_TYPES:
        return None
    raw_status = raw.get("status")
    if raw_status is not None and (not isinstance(raw_status, str) or raw_status not in _EVENT_STATUSES):
        raise ValueError("Codex event status is invalid")
    event: dict[str, Any] = {
        "type": event_type,
        "ts": now_iso(),
    }
    if raw_status is not None:
        event["status"] = raw_status
    thread_id = raw.get("thread_id")
    if thread_id is not None:
        if not isinstance(thread_id, str) or thread_id.startswith("-") or not _SAFE_NAME.match(thread_id):
            raise ValueError("Codex event thread_id is invalid")
        event["thread_id"] = thread_id
    if event_type.startswith("item.") and not isinstance(raw.get("item"), dict):
        raise ValueError("Codex item event must include an item object")
    item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
    item_type = item.get("type")
    if item_type is not None and not isinstance(item_type, str):
        raise ValueError("Codex item type is invalid")
    item_type = item_type or ""
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
    _require_safe_computer_use(prompt)


def _require_safe_followup(prompt: str) -> None:
    _require_safe_computer_use(prompt)


def _require_safe_computer_use(prompt: str) -> None:
    if reserved_native_execution_token(prompt):
        raise ValueError(
            "native execution actions are unavailable in Workbench; use a root native Codex workspace session"
        )
    try:
        build_requested = bool(parse_build_invocation(prompt))
    except BuildInvocationError:
        build_requested = str(prompt).lstrip().startswith("$tcx-build")
    if build_requested:
        raise ValueError(
            "native build turns are unavailable in Workbench; use an exact $tcx-build root Codex workspace turn"
        )
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
    context = _generation_context(
        root,
        str(manifest.get("workspace_id") or "workbench-verification"),
        provision_runtime=False,
    )
    for relative in (Path("tcx"), Path("tcx.cmd"), Path(".tradingcodex/cli.py")):
        expected = render_template((template_root / relative).read_text(encoding="utf-8"), context).encode()
        if _read_verified_runtime_file(root, relative) != expected:
            raise ValueError(f"generated TradingCodex launcher does not match the installed package: {relative.as_posix()}")
    try:
        config = tomllib.loads(_read_verified_runtime_file(root, ".codex/config.toml").decode())
    except Exception as exc:
        raise ValueError("TradingCodex project config is unavailable") from exc
    if config.get("sandbox_mode") != "read-only":
        raise ValueError("TradingCodex project config must use read-only sandboxing")
    servers = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}
    if set(servers) != {"tradingcodex"}:
        raise ValueError("TradingCodex project config must contain only the canonical tradingcodex MCP server")
    server = servers["tradingcodex"] if isinstance(servers.get("tradingcodex"), dict) else {}
    args = server.get("args") if isinstance(server.get("args"), list) else []
    expected_args = ["-m", "tradingcodex_cli", "mcp", "stdio"]
    expected_env = {
        "TRADINGCODEX_HOME": context["TRADINGCODEX_HOME"],
        "TRADINGCODEX_HOME_SOURCE": context["TRADINGCODEX_HOME_SOURCE"],
        "TRADINGCODEX_MCP_AUTOSTART_SERVICE": "1",
        "_TRADINGCODEX_EXECUTABLE_SOURCE_KIND": context[
            "TRADINGCODEX_PACKAGE_SOURCE_KIND"
        ],
        "TRADINGCODEX_MCP_PRINCIPAL": "head-manager",
        "TRADINGCODEX_SERVICE_ADDR": context["TRADINGCODEX_SERVICE_ADDR"],
        "TRADINGCODEX_WORKSPACE_ROOT": context["TRADINGCODEX_WORKSPACE_ROOT"],
    }
    if context["TRADINGCODEX_MCP_PACKAGE_SPEC"]:
        expected_env["TRADINGCODEX_MCP_PACKAGE_SPEC"] = context[
            "TRADINGCODEX_MCP_PACKAGE_SPEC"
        ]
    if context["TRADINGCODEX_DB_SOURCE"] == "environment_override":
        expected_env["TRADINGCODEX_DB_NAME"] = context["TRADINGCODEX_DB_PATH"]
    if context["TRADINGCODEX_MCP_PYTHONPATH"]:
        expected_env["PYTHONPATH"] = context["TRADINGCODEX_MCP_PYTHONPATH"]
    if (
        server.get("command") != context["TRADINGCODEX_PYTHON"]
        or server.get("enabled") is not True
        or server.get("cwd") != context["TRADINGCODEX_WORKSPACE_ROOT"]
        or server.get("env") != expected_env
        or server.get("enabled_tools") != list(AGENT_SPECS["head-manager"].mcp_allowlist)
        or server.get("default_tools_approval_mode") != "approve"
        or args != expected_args
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
        if key == "skills":
            continue
        if config.get(key) != expected_root.get(key):
            raise ValueError(f"TradingCodex project config does not match the generated runtime: {key}")

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


def _trusted_project_config_arg(root: Path) -> str:
    return f"projects={{{json.dumps(str(root), ensure_ascii=False)}={{trust_level=\"trusted\"}}}}"


def _codex_environment(
    root: Path,
    run_id: str,
    *,
    followup: bool,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not _SENSITIVE_ENV.search(key)}
    env.update({
        "TRADINGCODEX_WORKSPACE_ROOT": str(root),
        "TRADINGCODEX_WORKFLOW_RUN_ID": run_id,
        "TRADINGCODEX_WORKFLOW_FOLLOWUP": "1" if followup else "0",
        "TRADINGCODEX_WORKBENCH_RUN": "1",
    })
    metadata = metadata if isinstance(metadata, dict) else {}
    strategy = metadata.get("strategy_binding") if isinstance(metadata.get("strategy_binding"), dict) else {}
    context = metadata.get("investor_context_binding") if isinstance(metadata.get("investor_context_binding"), dict) else {}
    env["TRADINGCODEX_WORKFLOW_STRATEGY_ID"] = str(strategy.get("strategy_id") or "")
    env["TRADINGCODEX_WORKFLOW_APPLY_INVESTOR_CONTEXT"] = "1" if context.get("applied") else "0"
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
        elif skill_id == "tcx-memory":
            instructions.append("Apply $tcx-memory as the user-selected review and replay procedure.")
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


def _bound_workflow_prompt(prompt: str, workflow_run_id: str) -> str:
    return (
        f"Workbench has already created lightweight analysis run `{workflow_run_id}` without classifying the request or selecting roles. "
        "Do not call begin_analysis_run again. Interpret the request directly and orchestrate the fixed-role team dynamically through $tcx-workflow. "
        "Do not use a Django plan, lane, DAG, or latest pointer as authority.\n\n"
        + prompt
    )


def list_recent_runs(root: Path | str, *, limit: int = 30) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    base = root / ANALYSIS_RUNS_ROOT
    max_records = max(1, min(int(limit), 100))
    candidates = []
    for path in base.glob(f"*/{WEB_RUN_FILE}") if base.exists() else []:
        safe = _safe_workflow_path(root, path.relative_to(root), required=True)
        item = _run_metadata(safe.parent)
        run_id = item["workflow_run_id"]
        candidates.append({
            "workflow_run_id": run_id,
            "started_at": _public_text(item.get("started_at"), limit=80),
            "updated_at": _public_text(item.get("updated_at"), limit=80),
        })
    candidates.sort(key=lambda item: item["updated_at"] or item["started_at"], reverse=True)

    records = []
    for candidate in candidates:
        detail = get_run_detail(root, candidate["workflow_run_id"])
        records.append({
            **candidate,
            "status": detail["status"],
            "original_request": detail["original_request"],
            "skill_id": detail["method_id"],
            "attempt": detail["attempt"],
        })
        if len(records) == max_records:
            break
    return records


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
    try:
        selected_brain = explicit_investment_brain_invocation(value)
    except ValueError as exc:
        raise ValueError(
            "Workbench does not support Investment Brain selection; start a native Codex task with exactly one active $investment-brain-* skill"
        ) from exc
    if selected_brain:
        raise ValueError(
            "Investment Brain analysis is available only from a native Codex task with one active $investment-brain-* skill"
        )
    return value


def _safe_workflow_path(root: Path, relative: Path | str, *, required: bool) -> Path:
    root = root.expanduser().resolve()
    raw = Path(relative)
    if raw.is_absolute():
        raw = raw.relative_to(root)
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


def _safe_run_file(run_dir: Path, name: str, *, required: bool) -> Path:
    marker = next((parent for parent in run_dir.parents if parent.name == ".tradingcodex"), None)
    if marker is None:
        raise ValueError("workflow run directory is outside the attached workspace")
    root = marker.parent
    return _safe_workflow_path(root, (run_dir / name).relative_to(root), required=required)


def _public_text(value: Any, *, limit: int = 1000) -> str:
    return redact_log_text(str(value or ""))[:limit]


def _accepted_synthesis(
    root: Path,
    artifacts: list[dict[str, Any]],
    run_id: str,
) -> tuple[dict[str, Any] | None, str]:
    run_artifacts = {
        str(item.get("artifact_id") or ""): item
        for item in artifacts
        if str(item.get("workflow_run_id") or "") == run_id
    }
    quality_failed = False
    for item in artifacts:
        if (
            item.get("artifact_type") != "synthesis_report"
            or item.get("handoff_state") != "accepted"
            or item.get("producer_role") != "head-manager"
            or str(item.get("workflow_run_id") or "") != run_id
        ):
            continue
        artifact = get_research_artifact(
            root,
            {"artifact_id": str(item.get("artifact_id") or ""), "include_markdown": True},
        )
        markdown = str(artifact.pop("markdown", ""))
        if artifact.get("content_hash") != hashlib.sha256(markdown.encode("utf-8")).hexdigest():
            continue
        try:
            verify_authenticated_artifact_binding(root, artifact)
        except ValueError:
            continue
        input_hashes = artifact.get("input_artifact_hashes")
        if not isinstance(input_hashes, dict) or not input_hashes:
            continue
        lineage_ok = True
        for artifact_id, content_hash in input_hashes.items():
            source_artifact = run_artifacts.get(artifact_id)
            if not source_artifact or source_artifact.get("content_hash") != content_hash:
                lineage_ok = False
                break
            try:
                verify_authenticated_artifact_binding(root, source_artifact)
            except ValueError:
                lineage_ok = False
                break
        if not lineage_ok:
            continue
        quality = evaluate_decision_quality(
            root,
            str(artifact.get("path") or ""),
            strict=True,
        )
        if quality.get("status") != "pass":
            quality_failed = True
            continue
        preview = render_markdown_preview(
            markdown,
            source_file=str(artifact.get("path") or ""),
            source_label="research artifact",
        )
        return _json_safe({**artifact, "preview": {"heading": preview.heading, "html": preview.html}}), ""
    reason = "synthesis artifact failed its quality gate" if quality_failed else "run-local synthesis artifact is not ready"
    return None, reason


def _run_agents_from_session(root: Path, run_id: str) -> list[dict[str, Any]]:
    state = read_json(root / ".tradingcodex/mainagent/subagent-session-state.json", {})
    events = state.get("events") if isinstance(state, dict) and isinstance(state.get("events"), list) else []
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("run_id") != run_id:
            continue
        role = str(event.get("role") or "")
        session_id = str(event.get("agent_session_id") or "")
        if role and session_id:
            latest[(role, session_id)] = event
    return [
        {
            "role": role,
            "agent_session_id": session_id,
            "status": "running" if event.get("event") == "subagent-start" else "completed",
            "updated_at": _public_text(event.get("ts"), limit=80),
        }
        for (role, session_id), event in sorted(latest.items())
    ]


def _run_dir(root: Path, run_id: str) -> Path:
    if sanitize_id(run_id) != run_id:
        raise ValueError("invalid workflow run id")
    return _safe_workflow_path(root, ANALYSIS_RUNS_ROOT / run_id, required=False)


def _existing_run_dir(root: Path, run_id: str) -> Path:
    path = _run_dir(root, run_id)
    if not path.is_dir():
        raise ValueError(f"workflow run not found: {run_id}")
    return path


def _run_metadata(run_dir: Path) -> dict[str, Any]:
    path = _safe_run_file(run_dir, WEB_RUN_FILE, required=True)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"workbench run metadata is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"workbench run metadata must be an object: {path}")
    run_id = value.get("workflow_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"workbench run metadata has no workflow_run_id: {path}")
    if run_id != run_dir.name:
        raise ValueError(f"workbench run metadata identity does not match its directory: {path}")
    return value


def _update_run_metadata(run_dir: Path, **updates: Any) -> None:
    metadata = _run_metadata(run_dir)
    metadata.update(updates)
    metadata["updated_at"] = now_iso()
    write_json(_safe_run_file(run_dir, WEB_RUN_FILE, required=False), metadata)


def _append_web_event(run_dir: Path, event: dict[str, Any]) -> None:
    stored = _validated_stored_event({"ts": event.get("ts") or now_iso(), **event})
    append_jsonl(_safe_run_file(run_dir, WEB_EVENTS_FILE, required=False), stored)


def _read_normalized_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"workbench event log has an empty record at line {line_number}: {path}")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"workbench event log is invalid at line {line_number}: {path}") from exc
        events.append(_validated_stored_event(raw))
    return events[-500:]


def _validated_stored_event(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("workbench event must be an object")
    unexpected = set(raw) - _STORED_EVENT_FIELDS
    if unexpected:
        raise ValueError(f"unsupported workbench event fields: {', '.join(sorted(unexpected))}")
    event_type = raw.get("type")
    if not isinstance(event_type, str):
        raise ValueError("workbench event type must be a string")
    if event_type not in _CODEX_EVENT_TYPES | _WORKBENCH_EVENT_TYPES:
        raise ValueError(f"unsupported workbench event type: {event_type}")
    event: dict[str, Any] = {"type": event_type}
    status = raw.get("status")
    if status is not None:
        if not isinstance(status, str) or status not in _EVENT_STATUSES:
            raise ValueError("workbench event status is invalid")
        event["status"] = status
    if event_type in _WORKBENCH_EVENT_TYPES and status is None:
        raise ValueError("workbench lifecycle event status is required")
    timestamp = raw.get("ts")
    if not isinstance(timestamp, str) or not timestamp or len(timestamp) > 64:
        raise ValueError("workbench event timestamp is invalid")
    _validate_iso_timestamp(timestamp, "workbench event timestamp")
    event["ts"] = timestamp
    thread_id = raw.get("thread_id")
    if thread_id is not None:
        if not isinstance(thread_id, str) or thread_id.startswith("-") or not _SAFE_NAME.match(thread_id):
            raise ValueError("workbench event thread_id is invalid")
        event["thread_id"] = thread_id
    item_type = raw.get("item_type")
    if event_type.startswith("item.") and item_type not in _ITEM_TYPES:
        raise ValueError("workbench item event item_type is invalid")
    if item_type is not None:
        if not isinstance(item_type, str) or item_type not in _ITEM_TYPES:
            raise ValueError("workbench event item_type is invalid")
        event["item_type"] = item_type
    tool_name = raw.get("tool_name")
    if tool_name is not None:
        if not isinstance(tool_name, str) or tool_name.startswith("-") or not _SAFE_NAME.match(tool_name):
            raise ValueError("workbench event tool_name is invalid")
        event["tool_name"] = tool_name
    message_available = raw.get("message_available")
    if message_available is not None:
        if message_available is not True:
            raise ValueError("workbench event message_available must be true when present")
        event["message_available"] = True
    attempt = raw.get("attempt")
    if event_type in _WORKBENCH_EVENT_TYPES and (
        not isinstance(attempt, int) or isinstance(attempt, bool) or not 0 < attempt <= 10000
    ):
        raise ValueError("workbench lifecycle event attempt is invalid")
    if attempt is not None:
        if not isinstance(attempt, int) or isinstance(attempt, bool) or not 0 < attempt <= 10000:
            raise ValueError("workbench event attempt is invalid")
        event["attempt"] = attempt
    return_code = raw.get("return_code")
    if return_code is not None:
        if not isinstance(return_code, int) or isinstance(return_code, bool) or not -255 <= return_code <= 255:
            raise ValueError("workbench event return_code is invalid")
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
        raise ValueError("invalid Codex thread authority")
    write_json(_thread_authority_path(root, run_id), {
        "schema_version": 1,
        "workflow_run_id": run_id,
        "thread_id": thread_id,
        "updated_at": now_iso(),
    })


def _service_thread_id(root: Path, run_id: str) -> str:
    path = _thread_authority_path(root, run_id)
    if not path.exists():
        return ""
    value = read_json(path)
    if not isinstance(value, dict) or set(value) != _THREAD_AUTHORITY_FIELDS:
        raise ValueError("Codex thread authority is invalid")
    if value.get("schema_version") != 1 or value.get("workflow_run_id") != run_id:
        raise ValueError("Codex thread authority identity is invalid")
    thread_id = value.get("thread_id")
    if not isinstance(thread_id, str) or thread_id.startswith("-") or not _SAFE_NAME.match(thread_id):
        raise ValueError("Codex thread authority thread_id is invalid")
    updated_at = value.get("updated_at")
    if not isinstance(updated_at, str):
        raise ValueError("Codex thread authority updated_at is invalid")
    _validate_iso_timestamp(updated_at, "Codex thread authority updated_at")
    return thread_id


def _validate_iso_timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")


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


def _latest_workflow(root: Path) -> dict[str, Any]:
    recent = list_recent_runs(root, limit=1)
    return recent[0] if recent else {}


def _agent_catalog(root: Path) -> list[dict[str, Any]]:
    state = build_projection_state(root)
    return [{
        "role": role,
        "label": item.get("label") or role,
        "group": item.get("group") or "",
        "purpose": item.get("purpose") or "",
        "skills": item.get("effective_skills") or [],
        "validation_errors": item.get("validation_errors") or [],
    } for role, item in state.get("agents", {}).items()]


def _recent_activity(root: Path) -> dict[str, Any]:
    items = list_recent_activity(root, limit=50)
    return {"items": items, "tool_names": list(dict.fromkeys(item["title"] for item in items if item.get("kind") == "MCP"))}


def _skill_path(root: Path, skill_id: str, item: dict[str, Any]) -> Path:
    raw = str(item.get("resolved_source_file") or "")
    if not raw:
        raise ValueError(f"projected skill has no source file: {skill_id}")
    candidate = Path(raw).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    resolved_root = root.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"projected skill source escapes the workspace: {skill_id}") from exc
    if not resolved_candidate.is_file():
        raise ValueError(f"projected skill source is missing: {skill_id}")
    return resolved_candidate


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"skill metadata is unavailable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"skill metadata must be an object: {path}")
    return value


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
