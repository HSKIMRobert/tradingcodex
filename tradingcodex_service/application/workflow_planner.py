from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tradingcodex_service.application.agents import EXPECTED_SUBAGENTS, JUDGMENT_REVIEW_ROLE, get_strategy_skill_record
from tradingcodex_service.application.common import (
    _unique,
    append_jsonl,
    atomic_write_text,
    exclusive_file_lock,
    file_hash,
    read_json,
    safe_workspace_path,
    sanitize_id,
    stable_hash,
    write_json,
)
from tradingcodex_service.application.harness import (
    RESEARCH_STAGE_ROLES,
    build_subagent_starter_prompt,
    build_workflow_intake_summary,
    build_workflow_stages,
)
from tradingcodex_service.application.artifact_quality import estimate_tokens
from tradingcodex_service.application.investor_context import INVESTOR_CONTEXT_ROOT, investor_context_binding, read_investor_context
from tradingcodex_service.application.markdown_preview import split_markdown_frontmatter
from tradingcodex_service.application.workflow_routing import (
    HANDOFF_STATES,
    NEGATED_SCOPE_PATTERNS,
    build_loop_policy,
    classify_structured_intent,
    classify_starter_request,
    is_connector_build_request,
    is_investment_workflow_request,
    is_secret_only_request,
    is_secret_warning_request,
    normalize_structured_intent,
    negates_scope,
)
from tradingcodex_service.application.workflow_contracts import (
    LANE_ALLOWED_ROLES,
    NON_DISPATCH_LANES,
    PLAN_FIELDS,
    STAGE_FIELDS,
    WorkflowLane,
    build_routing_envelope,
    intake_contract_hash,
    workflow_plan_hash,
)
from tradingcodex_service.application.workflow_state import initialize_workflow_state

MAINAGENT_ROOT = Path(".tradingcodex/mainagent")
WORKFLOW_ROOT = MAINAGENT_ROOT / "workflows"
LATEST_INTAKE_PATH = MAINAGENT_ROOT / "latest-workflow-intake.json"
LATEST_PLAN_PATH = MAINAGENT_ROOT / "latest-workflow-plan.json"
LATEST_LOOP_STATE_PATH = MAINAGENT_ROOT / "workflow-loop-state.json"
STRATEGY_SNAPSHOT_FILE = "strategy-snapshot.md"
INVESTOR_CONTEXT_SNAPSHOT_FILE = "investor-context-snapshot.md"
EXPLICIT_STRATEGY_INVOCATION = re.compile(
    r"(?<![A-Za-z0-9_-])\$(strategy-[a-z0-9]+(?:-[a-z0-9]+)*)(?![A-Za-z0-9_-])"
)
PLAN_DRAFT_FIELDS = {
    "schema_version",
    "workflow_run_id",
    "selected_roles",
    "planner_rationale",
}
COMPILED_PLAN_MARKERS = {
    "routing_envelope",
    "routing_envelope_hash",
    "plan_hash",
}


def explicit_strategy_invocation(prompt: str) -> str:
    names = list(dict.fromkeys(EXPLICIT_STRATEGY_INVOCATION.findall(prompt or "")))
    if len(names) > 1:
        raise ValueError("select exactly one explicit $strategy-* skill for a workflow")
    return names[0] if names else ""


def select_strategy_binding(workspace_root: Path | str, strategy_id: str) -> tuple[dict[str, Any], str]:
    root = Path(workspace_root).expanduser().resolve()
    if not strategy_id:
        return _strategy_binding(None), ""
    if not re.fullmatch(r"strategy-[a-z0-9]+(?:-[a-z0-9]+)*", strategy_id):
        raise ValueError("strategy selection must use an exact strategy-* skill id")
    record = get_strategy_skill_record(root, strategy_id)
    if record.get("status") != "active" or record.get("validation_status") != "valid":
        raise ValueError(f"strategy is not active and valid: {strategy_id}")
    source_file = str(record.get("source_file") or "")
    source = safe_workspace_path(root, source_file, allowed_roots=(Path(".agents/skills"),))
    try:
        source_bytes = source.read_bytes()
        content = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"strategy source is unavailable: {strategy_id}") from exc
    content_hash = hashlib.sha256(source_bytes).hexdigest()
    recorded_hash = str(record.get("source_file_hash") or "")
    if recorded_hash and recorded_hash != content_hash:
        raise ValueError("strategy changed while it was being bound")
    return {
        "strategy_id": str(record.get("name") or strategy_id),
        "source_file": source_file,
        "content_hash": content_hash,
        "snapshot_path": "",
    }, content


def select_investor_context_binding(
    workspace_root: Path | str,
    apply: bool | None = None,
) -> tuple[dict[str, Any], str]:
    root = Path(workspace_root).expanduser().resolve()
    binding = investor_context_binding(root, apply=apply)
    if not binding.get("applied"):
        return binding, ""
    context = read_investor_context(root)
    if context.get("source") == "workspace_file":
        source = safe_workspace_path(root, str(context.get("path") or ""), allowed_roots=(INVESTOR_CONTEXT_ROOT,))
        try:
            source_bytes = source.read_bytes()
            content = source_bytes.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("workspace investor context is unavailable") from exc
        if hashlib.sha256(source_bytes).hexdigest() != binding.get("content_hash"):
            raise ValueError("investor context changed while it was being bound")
        return binding, content
    frontmatter = {
        "schema_version": 1,
        "source": str(context.get("source") or "legacy_active_profile"),
        "source_content_hash": str(binding.get("content_hash") or ""),
        **dict(binding.get("fields") or {}),
    }
    content = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n\n# Investor Context Snapshot\n"
    notes = str(context.get("notes") or "").strip()
    if notes:
        content += f"\n{notes}\n"
    return binding, content


def seal_workflow_run_bindings(
    workspace_root: Path | str,
    workflow_run_id: str,
    *,
    strategy_binding: dict[str, Any] | None,
    context_binding: dict[str, Any] | None,
    strategy_content: str = "",
    context_content: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(workspace_root).expanduser().resolve()
    if not workflow_run_id or sanitize_id(workflow_run_id) != workflow_run_id:
        raise ValueError("invalid workflow run id")
    run_dir = _mainagent_path(root, WORKFLOW_ROOT / workflow_run_id)
    sealed_strategy = _strategy_binding(strategy_binding)
    sealed_context = _context_binding(context_binding)

    strategy_id = sealed_strategy["strategy_id"]
    if strategy_id:
        snapshot_path = sealed_strategy.get("snapshot_path") or ""
        if snapshot_path:
            path = _existing_run_snapshot(root, run_dir, snapshot_path, STRATEGY_SNAPSHOT_FILE)
            if file_hash(path) != sealed_strategy.get("content_hash"):
                raise ValueError("sealed strategy snapshot hash mismatch")
        else:
            if not strategy_content:
                selected, strategy_content = select_strategy_binding(root, strategy_id)
                _require_same_binding(sealed_strategy, selected, ("strategy_id", "source_file", "content_hash"), "strategy")
                sealed_strategy = selected
            if hashlib.sha256(strategy_content.encode("utf-8")).hexdigest() != sealed_strategy.get("content_hash"):
                raise ValueError("strategy content hash does not match its binding")
            path = run_dir / STRATEGY_SNAPSHOT_FILE
            with exclusive_file_lock(path):
                if path.exists():
                    if not path.is_file() or file_hash(path) != sealed_strategy.get("content_hash"):
                        raise ValueError("protected strategy snapshot already exists with different content")
                else:
                    atomic_write_text(path, strategy_content)
            sealed_strategy["snapshot_path"] = path.relative_to(root).as_posix()
    elif any(sealed_strategy.get(field) for field in ("source_file", "content_hash", "snapshot_path")):
        raise ValueError("no-strategy binding must not contain strategy provenance")

    if sealed_context.get("applied"):
        snapshot_path = sealed_context.get("snapshot_path") or ""
        if snapshot_path:
            path = _existing_run_snapshot(root, run_dir, snapshot_path, INVESTOR_CONTEXT_SNAPSHOT_FILE)
            _verify_context_snapshot(path, sealed_context)
        else:
            if not context_content:
                selected, context_content = select_investor_context_binding(root, True)
                _require_same_binding(
                    sealed_context,
                    selected,
                    ("applied", "configured", "enabled_by_default", "source", "path", "content_hash", "fields"),
                    "investor context",
                )
                sealed_context = _context_binding(selected)
            path = run_dir / INVESTOR_CONTEXT_SNAPSHOT_FILE
            with exclusive_file_lock(path):
                if path.exists():
                    if not path.is_file():
                        raise ValueError("protected investor context snapshot is not a file")
                    _verify_context_snapshot(path, sealed_context)
                else:
                    atomic_write_text(path, context_content)
                    _verify_context_snapshot(path, sealed_context)
            sealed_context["snapshot_path"] = path.relative_to(root).as_posix()
    elif sealed_context.get("snapshot_path"):
        raise ValueError("disabled investor context must not contain a run snapshot")
    return sealed_strategy, sealed_context


def _existing_run_snapshot(root: Path, run_dir: Path, raw_path: str, expected_name: str) -> Path:
    path = _mainagent_path(root, raw_path)
    expected = run_dir / expected_name
    if path != expected or not path.is_file():
        raise ValueError(f"sealed binding snapshot must be the current run's {expected_name}")
    return path


def _require_same_binding(
    recorded: dict[str, Any],
    current: dict[str, Any],
    fields: tuple[str, ...],
    label: str,
) -> None:
    if any(recorded.get(field) != current.get(field) for field in fields):
        raise ValueError(f"{label} changed while it was being bound")


def _verify_context_snapshot(path: Path, binding: dict[str, Any]) -> None:
    if binding.get("source") == "workspace_file":
        if file_hash(path) != binding.get("content_hash"):
            raise ValueError("sealed investor context snapshot hash mismatch")
        return
    frontmatter = split_markdown_frontmatter(path.read_text(encoding="utf-8")).frontmatter
    if str(frontmatter.get("source_content_hash") or "") != binding.get("content_hash"):
        raise ValueError("sealed investor context provenance hash mismatch")
    if any(frontmatter.get(key) != value for key, value in (binding.get("fields") or {}).items()):
        raise ValueError("sealed investor context fields mismatch")


def build_workflow_intake(
    prompt: str,
    workspace_root: Path | str | None = None,
    *,
    workflow_run_id: str = "",
    structured_intent: dict[str, Any] | None = None,
    strategy_binding: dict[str, Any] | None = None,
    context_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = prompt or ""
    if not prompt.strip():
        raise ValueError("prompt is required")
    secret_warning = is_secret_warning_request(prompt)
    secret_only = is_secret_only_request(prompt)
    connector_build = is_connector_build_request(prompt)
    normalized_intent = normalize_structured_intent(prompt, structured_intent)
    if structured_intent is not None:
        investment_candidate = bool(normalized_intent.requested_actions) and not secret_only
    else:
        investment_candidate = is_investment_workflow_request(prompt) and not secret_only
    if investment_candidate or connector_build:
        hint = classify_structured_intent(normalized_intent) if structured_intent is not None else classify_starter_request(prompt)
    else:
        hint = {"lane": "secret_warning" if secret_warning else "head_manager", "subagents": [], "blockedActions": _default_blocked_actions(secret_warning)}
    run_id = workflow_run_id or _new_workflow_run_id()
    normalized_strategy_binding = _strategy_binding(strategy_binding)
    normalized_context_binding = _context_binding(
        context_binding
        or (investor_context_binding(workspace_root) if workspace_root is not None else None)
    )
    starter_prompt = build_subagent_starter_prompt(
        prompt,
        workspace_root,
        context_binding=normalized_context_binding,
        strategy_binding=normalized_strategy_binding,
    )
    context_metrics = {
        "starter_prompt_sha256": hashlib.sha256(starter_prompt.encode("utf-8")).hexdigest(),
        "starter_prompt_bytes": len(starter_prompt.encode("utf-8")),
        "starter_prompt_estimated_tokens": estimate_tokens(starter_prompt),
        "selected_role_count": len(hint.get("subagents") or []),
    }
    intake = {
        "schema_version": 1,
        "marker": "tradingcodex-workflow-intake",
        "workflow_run_id": run_id,
        "created_at": _now(),
        "requires_workflow_planning": bool(investment_candidate or connector_build),
        "investment_candidate": bool(investment_candidate),
        "connector_build": bool(connector_build),
        "secret_warning": bool(secret_warning),
        "secret_only": bool(secret_only),
        "explicit_negations": _unique([*_explicit_negations(prompt), *normalized_intent.forbidden_actions]),
        "normalized_intent": normalized_intent.as_dict(),
        "requires_intent_confirmation": normalized_intent.requires_confirmation,
        "context_metrics": context_metrics,
        "deterministic_hint": {
            "lane": hint.get("lane", ""),
            "roles": list(hint.get("subagents") or []),
            "blocked_actions": list(hint.get("blockedActions") or []),
            "quality_flags": _quality_flags(hint.get("routingFlags") or {}),
        },
        "strategy_binding": normalized_strategy_binding,
        "investor_context_binding": normalized_context_binding,
        "heuristic_lane": hint.get("lane", ""),
        "heuristic_roles": list(hint.get("subagents") or []),
        "blocked_actions": list(hint.get("blockedActions") or []),
        "intake_path": workflow_intake_relpath(run_id),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_bytes": len(prompt.encode("utf-8")),
    }
    return {**intake, "intake_hash": intake_contract_hash(intake)}


def record_workflow_intake(
    workspace_root: Path | str,
    prompt: str,
    *,
    workflow_run_id: str = "",
    structured_intent: dict[str, Any] | None = None,
    strategy_id: str = "",
    apply_investor_context: bool | None = None,
    strategy_binding: dict[str, Any] | None = None,
    context_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    run_id = workflow_run_id or _new_workflow_run_id()
    strategy_content = ""
    context_content = ""
    if strategy_binding is None:
        strategy_binding, strategy_content = select_strategy_binding(root, strategy_id)
    elif strategy_id and str(strategy_binding.get("strategy_id") or "") != strategy_id:
        raise ValueError("explicit strategy selection does not match the supplied binding")
    if context_binding is None:
        context_binding, context_content = select_investor_context_binding(root, apply_investor_context)
    strategy_binding, context_binding = seal_workflow_run_bindings(
        root,
        run_id,
        strategy_binding=strategy_binding,
        strategy_content=strategy_content,
        context_binding=context_binding,
        context_content=context_content,
    )
    intake = build_workflow_intake(
        prompt,
        root,
        workflow_run_id=run_id,
        structured_intent=structured_intent,
        strategy_binding=strategy_binding,
        context_binding=context_binding,
    )
    write_json(_mainagent_path(root, workflow_intake_relpath(run_id)), intake)
    write_json(_mainagent_path(root, LATEST_INTAKE_PATH), intake)
    append_jsonl(_mainagent_path(root, MAINAGENT_ROOT / "workflow-intake-history.jsonl"), {
        "ts": _now(),
        **{key: intake[key] for key in (
            "workflow_run_id",
            "requires_workflow_planning",
            "investment_candidate",
            "connector_build",
            "secret_warning",
            "secret_only",
            "heuristic_lane",
            "heuristic_roles",
            "blocked_actions",
            "intake_hash",
            "prompt_sha256",
            "prompt_bytes",
            "requires_intent_confirmation",
            "context_metrics",
            "strategy_binding",
            "investor_context_binding",
        )},
    })
    return intake


def build_deterministic_workflow_plan(workspace_root: Path | str, prompt: str, *, workflow_run_id: str = "") -> dict[str, Any]:
    """Compatibility preview, not the final server-compiled plan."""
    intake = build_workflow_intake(prompt, workspace_root, workflow_run_id=workflow_run_id)
    summary = build_workflow_intake_summary(
        prompt,
        workspace_root,
        context_binding=intake.get("investor_context_binding"),
        strategy_binding=intake.get("strategy_binding"),
    )
    roles = [item["role"] for item in summary.get("subagents") or []]
    plan = {
        "schema_version": 1,
        "workflow_run_id": intake["workflow_run_id"],
        "lane": summary["workflow_lane"],
        "stages": _stages_from_summary(summary),
        "blocked_actions": summary.get("blocked_actions") or [],
        "user_constraints": intake["explicit_negations"],
        "decision_quality_flags": summary.get("routing_flags") or {},
        "profile_gaps": summary.get("investor_profile_inputs") or [],
        "strategy_binding": intake.get("strategy_binding") or _strategy_binding(None),
        "investor_context_binding": intake.get("investor_context_binding") or _context_binding(None),
        "artifact_requirements": {
            "handoff_states": summary.get("artifact_handoff_states") or [],
            "context_summary_required": True,
            "source_as_of_required": True,
        },
        "stop_condition": _stop_condition(summary["workflow_lane"], summary.get("blocked_actions") or []),
        "planner_rationale": "Deterministic compatibility preview; the recorded plan is compiled from the Head Manager's bounded team selection.",
        "deterministic_preview": True,
        "heuristic_roles": roles,
    }
    loop_policy = build_loop_policy(str(plan["lane"]))
    envelope = build_routing_envelope(
        intake,
        lane=str(plan["lane"]),
        roles=roles,
        blocked_actions=list(plan["blocked_actions"]),
        loop_policy=loop_policy,
        terminal_condition=str(plan["stop_condition"]),
    )
    compiled = {
        **plan,
        "plan_version": 1,
        "intake_hash": intake["intake_hash"],
        "routing_envelope": envelope,
        "routing_envelope_hash": envelope["routing_envelope_hash"],
    }
    return {**compiled, "plan_hash": workflow_plan_hash(compiled)}


def is_workflow_plan_draft(plan: dict[str, Any]) -> bool:
    return not any(field in plan for field in COMPILED_PLAN_MARKERS)


def compile_workflow_plan_draft(draft: dict[str, Any], *, intake: dict[str, Any]) -> dict[str, Any]:
    """Compile an agent-selected team against the recorded server policy."""
    unknown = sorted(set(draft) - PLAN_DRAFT_FIELDS)
    missing = sorted({"workflow_run_id", "selected_roles"} - set(draft))
    if unknown:
        raise ValueError(f"unknown workflow plan draft field(s): {', '.join(unknown)}")
    if missing:
        raise ValueError(f"missing workflow plan draft field(s): {', '.join(missing)}")
    if "schema_version" in draft and (type(draft["schema_version"]) is not int or draft["schema_version"] != 1):
        raise ValueError("workflow plan draft schema_version must be 1")
    if str(draft.get("workflow_run_id") or "") != str(intake.get("workflow_run_id") or ""):
        raise ValueError("workflow_run_id does not match recorded intake")
    selected_roles = _string_list(draft.get("selected_roles"), "workflow plan draft selected_roles")
    policy = _canonical_plan_policy(intake, selected_roles=selected_roles)
    stages = _stages_from_summary({"workflow_stages": build_workflow_stages({"lane": policy["lane"], "subagents": policy["roles"]})})
    compiled = {
        "schema_version": 1,
        "plan_version": 1,
        "workflow_run_id": str(draft["workflow_run_id"]),
        "lane": policy["lane"],
        "stages": stages,
        "blocked_actions": policy["blocked_actions"],
        "user_constraints": policy["explicit_negations"],
        "decision_quality_flags": policy["decision_quality_flags"],
        "strategy_binding": intake.get("strategy_binding") or _strategy_binding(None),
        "investor_context_binding": intake.get("investor_context_binding") or _context_binding(None),
        "artifact_requirements": {
            "handoff_states": list(HANDOFF_STATES),
            "context_summary_required": True,
            "source_as_of_required": True,
        },
        "stop_condition": policy["stop_condition"],
        "planner_rationale": str(draft.get("planner_rationale") or "Head-manager team selection compiled against recorded intake policy."),
        "intake_hash": policy["intake_hash"],
        "routing_envelope": policy["routing_envelope"],
        "routing_envelope_hash": policy["routing_envelope"]["routing_envelope_hash"],
    }
    return {**compiled, "plan_hash": workflow_plan_hash(compiled)}


def validate_workflow_plan(plan: dict[str, Any], *, intake: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    run_id = str(plan.get("workflow_run_id") or "")
    lane = str(plan.get("lane") or "")
    stages = plan.get("stages")
    raw_blocked_actions = plan.get("blocked_actions") or []
    if not isinstance(raw_blocked_actions, list) or any(not isinstance(item, str) for item in raw_blocked_actions):
        errors.append("blocked_actions must be a list of strings")
        raw_blocked_actions = []
    blocked_actions = [item.lower() for item in raw_blocked_actions]
    unknown_plan_fields = sorted(set(plan) - PLAN_FIELDS)
    if unknown_plan_fields:
        errors.append(f"unknown plan field(s): {', '.join(unknown_plan_fields)}")
    if type(plan.get("schema_version")) is not int or plan.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if type(plan.get("plan_version")) is not int or plan.get("plan_version") != 1:
        errors.append("plan_version must be 1")
    if not run_id:
        errors.append("workflow_run_id is required")
    try:
        typed_lane = WorkflowLane(lane)
    except ValueError:
        typed_lane = None
        errors.append(f"unknown lane: {lane or '<missing>'}")
    if not isinstance(stages, list):
        errors.append("stages must be a list")
        stages = []
    stage_ids: set[str] = set()
    all_roles: list[str] = []
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            errors.append(f"stage {index} must be an object")
            continue
        unknown_stage_fields = sorted(set(stage) - STAGE_FIELDS)
        if unknown_stage_fields:
            errors.append(f"unknown stage field(s) in {stage.get('stage_id') or index}: {', '.join(unknown_stage_fields)}")
        stage_id = str(stage.get("stage_id") or "")
        if not stage_id:
            errors.append(f"stage {index} missing stage_id")
        elif stage_id in stage_ids:
            errors.append(f"duplicate stage_id: {stage_id}")
        stage_ids.add(stage_id)
        raw_roles = stage.get("roles") or []
        if not isinstance(raw_roles, list):
            errors.append(f"stage {stage_id or index} roles must be a list")
            raw_roles = []
        roles = _role_names(raw_roles)
        unknown = [role for role in roles if role not in EXPECTED_SUBAGENTS]
        if unknown:
            errors.append(f"unknown role(s) in {stage_id or index}: {', '.join(unknown)}")
        all_roles.extend(roles)
        raw_dependencies = stage.get("depends_on") or []
        if not isinstance(raw_dependencies, list):
            errors.append(f"stage {stage_id or index} depends_on must be a list")
            raw_dependencies = []
        for dep in raw_dependencies:
            if str(dep) == stage_id or str(dep) not in stage_ids:
                errors.append(f"stage {stage_id or index} depends on unknown or later stage: {dep}")
        if str(stage.get("dispatch_mode") or "") not in {"parallel", "sequential", "none"}:
            errors.append(f"stage {stage_id or index} dispatch_mode must be parallel, sequential, or none")
        if not isinstance(stage.get("purpose"), str) or not str(stage.get("purpose") or "").strip():
            errors.append(f"stage {stage_id or index} purpose must be a nonempty string")
        exit_criteria = stage.get("exit_criteria")
        if not isinstance(exit_criteria, list) or any(not isinstance(item, str) for item in exit_criteria):
            errors.append(f"stage {stage_id or index} exit_criteria must be a list of strings")
    duplicate_roles = sorted({role for role in all_roles if all_roles.count(role) > 1})
    if duplicate_roles:
        errors.append(f"roles may appear in only one initial stage: {', '.join(duplicate_roles)}")
    judgment_stages = [
        (index, stage)
        for index, stage in enumerate(stages)
        if isinstance(stage, dict) and JUDGMENT_REVIEW_ROLE in _role_names(stage.get("roles") or [])
    ]
    if judgment_stages:
        judgment_index, judgment_stage = judgment_stages[0]
        judgment_roles = _role_names(judgment_stage.get("roles") or [])
        if judgment_roles != [JUDGMENT_REVIEW_ROLE]:
            errors.append("judgment-reviewer must be alone in its review stage")
        non_judgment_stages = [
            (index, stage)
            for index, stage in enumerate(stages)
            if isinstance(stage, dict) and JUDGMENT_REVIEW_ROLE not in _role_names(stage.get("roles") or [])
        ]
        if not non_judgment_stages:
            errors.append("judgment-reviewer must follow at least one non-judgment stage")
        stage_dependencies = {
            str(stage.get("stage_id") or ""): [str(dep) for dep in stage.get("depends_on") or []]
            for stage in stages
            if isinstance(stage, dict)
        }

        def dependency_closure(stage_id: str) -> set[str]:
            closure: set[str] = set()
            pending = list(stage_dependencies.get(stage_id, []))
            while pending:
                dependency = pending.pop()
                if dependency in closure:
                    continue
                closure.add(dependency)
                pending.extend(stage_dependencies.get(dependency, []))
            return closure

        judgment_stage_id = str(judgment_stage.get("stage_id") or "")
        upstream_stage_ids = {
            str(stage.get("stage_id") or "")
            for index, stage in non_judgment_stages
            if index < judgment_index
        }
        if not upstream_stage_ids:
            errors.append("judgment-reviewer must follow at least one upstream stage")
        elif not upstream_stage_ids.issubset(dependency_closure(judgment_stage_id)):
            errors.append("judgment-reviewer dependency closure must include every upstream stage")
        downstream_without_judgment = [
            str(stage.get("stage_id") or "")
            for index, stage in non_judgment_stages
            if index > judgment_index and judgment_stage_id not in dependency_closure(str(stage.get("stage_id") or ""))
        ]
        if downstream_without_judgment:
            errors.append("every downstream stage must depend on judgment-reviewer")

    envelope = plan.get("routing_envelope") if isinstance(plan.get("routing_envelope"), dict) else {}
    envelope_hash = str(plan.get("routing_envelope_hash") or "")
    embedded_envelope_hash = str(envelope.get("routing_envelope_hash") or "")
    envelope_body = {key: value for key, value in envelope.items() if key != "routing_envelope_hash"}
    actual_envelope_hash = stable_hash(envelope_body) if envelope else ""
    if not envelope:
        errors.append("routing_envelope is required")
    elif envelope_hash != actual_envelope_hash or embedded_envelope_hash != actual_envelope_hash:
        errors.append("routing envelope hash mismatch")
    elif envelope.get("workflow_run_id") != run_id:
        errors.append("routing envelope workflow_run_id mismatch")
    elif envelope.get("lane") != lane or lane not in (envelope.get("permitted_lane_transitions") or []):
        errors.append("plan lane is outside the routing envelope")
    if envelope:
        eligible_roles = set(envelope.get("eligible_roles") or [])
        required_roles = set(envelope.get("required_roles") or [])
        if not set(all_roles).issubset(eligible_roles):
            errors.append("plan includes roles outside the routing envelope")
        if not required_roles.issubset(set(all_roles)):
            errors.append("plan omits required routing-envelope roles")
        envelope_blocks = {str(item).lower() for item in envelope.get("blocked_actions") or []}
        if not envelope_blocks.issubset(set(blocked_actions)):
            errors.append("blocked actions are monotonic within a plan version")
        budgets = envelope.get("budgets") if isinstance(envelope.get("budgets"), dict) else {}
        if len(stages) > int(budgets.get("max_stages") or 0):
            errors.append("stage budget exceeded")
        if len(_unique(all_roles)) > int(budgets.get("max_initial_tasks") or 0):
            errors.append("initial task budget exceeded")
        max_concurrency = int(budgets.get("max_concurrency") or 0)
        if any(stage.get("dispatch_mode") == "parallel" and len(_role_names(stage.get("roles") or [])) > max_concurrency for stage in stages if isinstance(stage, dict)):
            errors.append("stage concurrency budget exceeded")

    expected_plan_hash = workflow_plan_hash(plan)
    if not plan.get("plan_hash"):
        errors.append("plan_hash is required")
    elif str(plan.get("plan_hash")) != expected_plan_hash:
        errors.append("plan_hash does not bind the compiled plan")
    if intake:
        try:
            canonical_policy = _canonical_plan_policy(intake, selected_roles=all_roles)
        except ValueError as exc:
            canonical_policy = None
            errors.append(str(exc))
        if str(intake.get("workflow_run_id") or "") != run_id:
            errors.append("workflow_run_id does not match recorded intake")
        expected_intake_hash = str(intake.get("intake_hash") or intake_contract_hash(intake))
        if str(plan.get("intake_hash") or "") != expected_intake_hash:
            errors.append("plan intake_hash does not match recorded intake")
        if plan.get("strategy_binding") != intake.get("strategy_binding"):
            errors.append("plan strategy_binding does not match recorded intake")
        if plan.get("investor_context_binding") != intake.get("investor_context_binding"):
            errors.append("plan investor_context_binding does not match recorded intake")
        hint = intake.get("deterministic_hint") if isinstance(intake.get("deterministic_hint"), dict) else {}
        hint_lane = str(hint.get("lane") or "")
        if hint_lane and lane != hint_lane:
            errors.append("plan lane widens or replaces the recorded intake lane")
        intake_blocks = {str(item).lower() for item in hint.get("blocked_actions") or []}
        if not intake_blocks.issubset(set(blocked_actions)):
            errors.append("plan removed blocked actions from recorded intake")
        user_constraints = plan.get("user_constraints")
        if not isinstance(user_constraints, list) or any(not isinstance(item, str) for item in user_constraints):
            errors.append("user_constraints must be a list of strings")
            user_constraints = []
        if not set(str(item) for item in intake.get("explicit_negations") or []).issubset(set(user_constraints)):
            errors.append("plan removed explicit user constraints from recorded intake")
        quality_flags = plan.get("decision_quality_flags")
        if not isinstance(quality_flags, dict):
            errors.append("decision_quality_flags must be an object")
            quality_flags = {}
        canonical_quality_flags = (canonical_policy or {}).get("decision_quality_flags") or {}
        if any(not bool(quality_flags.get(key)) for key in canonical_quality_flags):
            errors.append("plan removed decision-quality requirements from recorded intake")
        artifact_requirements = plan.get("artifact_requirements")
        if not isinstance(artifact_requirements, dict):
            errors.append("artifact_requirements must be an object")
            artifact_requirements = {}
        handoff_states = artifact_requirements.get("handoff_states") or []
        if (
            not isinstance(handoff_states, list)
            or not set(HANDOFF_STATES).issubset({str(item) for item in handoff_states})
            or artifact_requirements.get("context_summary_required") is not True
            or artifact_requirements.get("source_as_of_required") is not True
        ):
            errors.append("plan removed canonical artifact requirements")
        if canonical_policy:
            if envelope != canonical_policy["routing_envelope"]:
                errors.append("routing envelope does not match recorded intake policy")
            if str(plan.get("stop_condition") or "") != canonical_policy["stop_condition"]:
                errors.append("stop_condition does not match recorded intake policy")
        if intake.get("secret_only") and all_roles:
            errors.append("secret-only intake must not dispatch investment roles")
        if intake.get("connector_build") and all_roles:
            errors.append("connector build intake must not dispatch investment roles")
        if intake.get("requires_intent_confirmation"):
            if typed_lane != WorkflowLane.RESEARCH_ONLY:
                errors.append("unresolved or low-confidence intent must remain research_only")
            if all_roles:
                errors.append("unresolved or low-confidence intent must not dispatch roles before confirmation")
        negations = set(intake.get("explicit_negations") or [])
        if "valuation" in negations and "valuation-analyst" in all_roles:
            errors.append("negated valuation scope cannot include valuation-analyst")
        if "technical" in negations and "technical-analyst" in all_roles:
            errors.append("negated technical scope cannot include technical-analyst")
        if "news" in negations and "news-analyst" in all_roles:
            errors.append("negated news scope cannot include news-analyst")
        if "portfolio" in negations and "portfolio-manager" in all_roles:
            errors.append("negated portfolio scope cannot include portfolio-manager")
        if "risk" in negations and "risk-manager" in all_roles:
            errors.append("negated risk scope cannot include risk-manager")
        if {"order", "trading", "execution"} & negations and "execution-operator" in all_roles:
            errors.append("negated order/trading/execution scope cannot include execution-operator")
    if typed_lane in NON_DISPATCH_LANES and all_roles:
        errors.append(f"{lane} lane must not dispatch investment roles")
    if typed_lane and not set(all_roles).issubset(LANE_ALLOWED_ROLES[typed_lane]):
        errors.append(f"{lane} contains a role outside its canonical lane policy")
    judgment_required_lanes = {
        WorkflowLane.THESIS_REVIEW,
        WorkflowLane.THESIS_PORTFOLIO_RISK,
        WorkflowLane.PORTFOLIO_RISK,
        WorkflowLane.ORDER_DRAFT,
    }
    if typed_lane in judgment_required_lanes and all_roles and JUDGMENT_REVIEW_ROLE not in all_roles:
        errors.append(f"{lane} requires judgment-reviewer")
    if "execution-operator" in all_roles and lane != "order_ticket_approval_execution_gate":
        errors.append("execution-operator is only valid in order_ticket_approval_execution_gate")
    if lane == "order_ticket_approval_execution_gate" and JUDGMENT_REVIEW_ROLE in all_roles:
        errors.append("order_ticket_approval_execution_gate must not dispatch judgment-reviewer")
    if "execution-operator" in all_roles and not any("execution" in item for item in blocked_actions):
        errors.append("execution role requires explicit execution blocked/precondition language in blocked_actions")
    if any(role in all_roles for role in ("portfolio-manager", "risk-manager", "execution-operator")) and lane == "research_only":
        errors.append("research_only lane cannot include portfolio, risk, or execution roles")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "workflow_run_id": run_id,
        "lane": lane,
        "roles": _unique(all_roles),
        "intake_hash": str(plan.get("intake_hash") or ""),
        "strategy_binding": plan.get("strategy_binding") or _strategy_binding(None),
        "investor_context_binding": plan.get("investor_context_binding") or _context_binding(None),
        "routing_envelope_hash": envelope_hash,
        "plan_hash": expected_plan_hash,
    }


def record_workflow_plan(workspace_root: Path | str, plan: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    stored_intake = {}
    if plan.get("workflow_run_id"):
        value = read_json(_mainagent_path(root, workflow_intake_relpath(str(plan["workflow_run_id"]))), {})
        stored_intake = value if isinstance(value, dict) else {}
    if not stored_intake:
        return _invalid_plan_record(plan, "recorded workflow intake is required")
    intake = stored_intake
    if not is_workflow_plan_draft(plan):
        return _invalid_plan_record(plan, "record_workflow_plan accepts a head-manager team-selection draft only")
    try:
        plan = compile_workflow_plan_draft(plan, intake=intake)
    except ValueError as exc:
        return _invalid_plan_record(plan, str(exc))
    validation = validate_workflow_plan(plan, intake=intake)
    if not validation["ok"]:
        return {"status": "invalid", "validation": validation}
    run_id = validation["workflow_run_id"]
    run_root = Path(workflow_plan_relpath(run_id)).parent
    with exclusive_file_lock(_mainagent_path(root, run_root / "plan-record")):
        existing_state = read_json(_mainagent_path(root, workflow_loop_relpath(run_id)), {})
        if isinstance(existing_state, dict) and existing_state:
            if existing_state.get("plan_hash") == validation["plan_hash"]:
                return {
                    "status": "already_recorded",
                    "workflow_run_id": run_id,
                    "plan_path": workflow_plan_relpath(run_id),
                    "loop_state_path": workflow_loop_relpath(run_id),
                    "validation": validation,
                    "plan_hash": validation["plan_hash"],
                    "routing_envelope_hash": validation["routing_envelope_hash"],
                }
            return {"status": "invalid", "validation": {**validation, "ok": False, "errors": [*validation["errors"], "workflow_run_id is already bound to another plan"]}}
        plan = {**plan, "schema_version": int(plan.get("schema_version") or 1), "plan_hash": validation["plan_hash"], "recorded_at": _now(), "validation": validation}
        plan_path = workflow_plan_relpath(run_id)
        write_json(_mainagent_path(root, plan_path), plan)
        write_json(_mainagent_path(root, LATEST_PLAN_PATH), plan)
        loop_state = _initial_loop_state(plan, intake)
        loop_state = initialize_workflow_state(root, loop_state, latest_projection=compact_workflow_loop_state)
        append_jsonl(_audit_path(root, Path("trading/audit/workflow-plan-events.jsonl")), {
            "ts": _now(),
            "event": "workflow-plan-recorded",
            "workflow_run_id": run_id,
            "plan_hash": validation["plan_hash"],
            "routing_envelope_hash": validation["routing_envelope_hash"],
            "lane": validation["lane"],
            "roles": validation["roles"],
        })
        return {
            "status": "recorded",
            "workflow_run_id": run_id,
            "plan_path": plan_path,
            "latest_plan_path": LATEST_PLAN_PATH.as_posix(),
            "loop_state_path": workflow_loop_relpath(run_id),
            "latest_loop_state_path": LATEST_LOOP_STATE_PATH.as_posix(),
            "validation": validation,
            "plan_hash": validation["plan_hash"],
            "routing_envelope_hash": validation["routing_envelope_hash"],
        }


def _invalid_plan_record(plan: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "validation": {
            "ok": False,
            "errors": [error],
            "warnings": [],
            "workflow_run_id": str(plan.get("workflow_run_id") or ""),
            "lane": str(plan.get("lane") or ""),
            "roles": [],
            "intake_hash": "",
            "routing_envelope_hash": "",
            "plan_hash": "",
        },
    }


def read_workflow_intake(workspace_root: Path | str, workflow_run_id: str = "") -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    path = _mainagent_path(root, workflow_intake_relpath(workflow_run_id) if workflow_run_id else LATEST_INTAKE_PATH)
    value = read_json(path, {})
    return value if isinstance(value, dict) else {}


def _mainagent_path(root: Path, relative: Path | str) -> Path:
    return safe_workspace_path(root, Path(relative).as_posix(), allowed_roots=(MAINAGENT_ROOT,))


def _audit_path(root: Path, relative: Path | str) -> Path:
    return safe_workspace_path(root, Path(relative).as_posix(), allowed_roots=(Path("trading/audit"),))


def workflow_intake_relpath(workflow_run_id: str) -> str:
    return f"{WORKFLOW_ROOT.as_posix()}/{sanitize_id(workflow_run_id)}/intake.json"


def workflow_plan_relpath(workflow_run_id: str) -> str:
    return f"{WORKFLOW_ROOT.as_posix()}/{sanitize_id(workflow_run_id)}/workflow-plan.json"


def workflow_loop_relpath(workflow_run_id: str) -> str:
    return f"{WORKFLOW_ROOT.as_posix()}/{sanitize_id(workflow_run_id)}/loop-state.json"


def _new_workflow_run_id() -> str:
    return f"workflow-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_blocked_actions(secret_warning: bool) -> list[str]:
    if secret_warning:
        return ["secret storage", "secret echo", "raw credential handling"]
    return []


def _quality_flags(flags: dict[str, Any]) -> dict[str, bool]:
    return {
        key: bool(flags.get(key))
        for key in (
            "decision_quality_required",
            "forecast_contract_required",
            "profile_gate_required",
            "anti_overfit_required",
            "deep_thesis_default",
        )
        if flags.get(key)
    }


def _explicit_negations(prompt: str) -> list[str]:
    lower = prompt.lower()
    return [label for label, pattern in NEGATED_SCOPE_PATTERNS.items() if negates_scope(lower, pattern)]


def _canonical_plan_policy(intake: dict[str, Any], *, selected_roles: list[str]) -> dict[str, Any]:
    if not isinstance(intake, dict) or not intake:
        raise ValueError("recorded workflow intake is required")
    expected_intake_hash = intake_contract_hash(intake)
    if str(intake.get("intake_hash") or "") != expected_intake_hash:
        raise ValueError("recorded workflow intake hash mismatch")
    hint = intake.get("deterministic_hint")
    if not isinstance(hint, dict):
        raise ValueError("recorded workflow intake routing hint is required")
    lane = str(hint.get("lane") or "")
    try:
        typed_lane = WorkflowLane(lane)
    except ValueError as exc:
        raise ValueError("recorded workflow intake has an unknown canonical lane") from exc
    raw_roles = hint.get("roles")
    if not isinstance(raw_roles, list) or any(not isinstance(role, str) for role in raw_roles):
        raise ValueError("recorded workflow intake roles must be a list of strings")
    candidate_roles = _unique(raw_roles)
    if any(role not in EXPECTED_SUBAGENTS or role not in LANE_ALLOWED_ROLES[typed_lane] for role in candidate_roles):
        raise ValueError("recorded workflow intake contains a role outside canonical lane policy")
    selected = _unique(selected_roles)
    outside_candidates = sorted(set(selected) - set(candidate_roles))
    if outside_candidates:
        raise ValueError(f"selected role(s) are outside the recorded intake candidates: {', '.join(outside_candidates)}")
    selected_set = set(selected)
    roles = [role for role in candidate_roles if role in selected_set]
    if candidate_roles and not roles:
        raise ValueError("selected_roles must choose at least one recorded intake candidate")
    role_floors = {
        WorkflowLane.THESIS_REVIEW: {JUDGMENT_REVIEW_ROLE},
        WorkflowLane.THESIS_PORTFOLIO_RISK: {JUDGMENT_REVIEW_ROLE, "portfolio-manager", "risk-manager"},
        WorkflowLane.PORTFOLIO_RISK: {JUDGMENT_REVIEW_ROLE, "portfolio-manager", "risk-manager"},
        WorkflowLane.ORDER_DRAFT: {JUDGMENT_REVIEW_ROLE, "portfolio-manager", "risk-manager"},
        WorkflowLane.APPROVED_ACTION: {"portfolio-manager", "risk-manager", "execution-operator"},
    }
    required_roles = set(role_floors.get(typed_lane, set()))
    missing_floor_candidates = sorted(required_roles - set(candidate_roles))
    if missing_floor_candidates:
        raise ValueError(f"recorded workflow intake omits mandatory lane role(s): {', '.join(missing_floor_candidates)}")
    requested_actions = set((intake.get("normalized_intent") or {}).get("requested_actions") or [])
    action_roles = {
        "technical": "technical-analyst",
        "valuation": "valuation-analyst",
        "portfolio": "portfolio-manager",
        "risk": "risk-manager",
        "execution": "execution-operator",
    }
    required_roles.update(role for action, role in action_roles.items() if action in requested_actions and role in candidate_roles)
    if {"valuation", "forecast", "recommendation"}.intersection(requested_actions) and "valuation-analyst" in candidate_roles:
        required_roles.add("valuation-analyst")
    quality_flags = hint.get("quality_flags")
    if not isinstance(quality_flags, dict):
        raise ValueError("recorded workflow intake quality_flags must be an object")
    if quality_flags.get("decision_quality_required") and JUDGMENT_REVIEW_ROLE in candidate_roles:
        required_roles.add(JUDGMENT_REVIEW_ROLE)
    missing_roles = sorted(required_roles - set(roles))
    if missing_roles:
        raise ValueError(f"selected_roles omits required role(s): {', '.join(missing_roles)}")
    evidence_candidates = set(candidate_roles).intersection(RESEARCH_STAGE_ROLES)
    if evidence_candidates and not evidence_candidates.intersection(roles):
        raise ValueError("selected_roles must include at least one research evidence role")
    blocked_actions = _string_list(hint.get("blocked_actions"), "recorded workflow intake blocked_actions")
    stop_condition = _stop_condition(lane, blocked_actions)
    routing_envelope = build_routing_envelope(
        intake,
        lane=lane,
        roles=roles,
        blocked_actions=blocked_actions,
        loop_policy=build_loop_policy(lane),
        terminal_condition=stop_condition,
    )
    return {
        "lane": lane,
        "roles": roles,
        "blocked_actions": blocked_actions,
        "explicit_negations": _string_list(intake.get("explicit_negations"), "recorded workflow intake explicit_negations"),
        "decision_quality_flags": {str(key): True for key, value in quality_flags.items() if value},
        "stop_condition": stop_condition,
        "intake_hash": expected_intake_hash,
        "routing_envelope": routing_envelope,
    }


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return _unique(list(value))


def _strategy_binding(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "strategy_id": str(raw.get("strategy_id") or ""),
        "source_file": str(raw.get("source_file") or ""),
        "content_hash": str(raw.get("content_hash") or ""),
        "snapshot_path": str(raw.get("snapshot_path") or ""),
    }


def _context_binding(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    return {
        "schema_version": 1,
        "applied": bool(raw.get("applied")),
        "configured": bool(raw.get("configured")),
        "enabled_by_default": bool(raw.get("enabled_by_default", True)),
        "source": str(raw.get("source") or "none"),
        "path": str(raw.get("path") or ""),
        "content_hash": str(raw.get("content_hash") or ""),
        "snapshot_path": str(raw.get("snapshot_path") or ""),
        "fields": {str(key): item for key, item in fields.items()},
    }


def _stages_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    previous_ids: list[str] = []
    for stage in summary.get("workflow_stages") or []:
        roles: list[str] = []
        raw_roles = stage.get("roles") or []
        for item in raw_roles:
            role = item.get("role") if isinstance(item, dict) else item
            if role in EXPECTED_SUBAGENTS:
                roles.append(role)
        if not roles:
            continue
        stage_id = sanitize_id(stage.get("key") or stage.get("label") or f"stage-{len(stages) + 1}")
        stages.append({
            "stage_id": stage_id,
            "roles": _unique(roles),
            "depends_on": list(previous_ids),
            "dispatch_mode": "parallel" if len(roles) > 1 else "sequential",
            "purpose": stage.get("summary") or stage.get("label") or stage_id,
            "exit_criteria": stage.get("exit_criteria") or [],
        })
        previous_ids = [stage_id]
    return stages


def _stop_condition(lane: str, blocked_actions: list[str]) -> str:
    if "execution" in blocked_actions:
        return "stop before execution unless service-layer approval and execution gates pass"
    if lane == "research_only":
        return "stop after selected research artifacts are accepted or blocked"
    return "stop at synthesize, blocked, waiting, or lane_escalation_proposal"


def _initial_loop_state(plan: dict[str, Any], intake: dict[str, Any] | None) -> dict[str, Any]:
    run_id = str(plan["workflow_run_id"])
    pending_tasks = [
        {
            "task_id": f"{run_id}:{stage['stage_id']}",
            "stage_id": stage["stage_id"],
            "roles": _role_names(stage.get("roles") or []),
            "task_type": "stage_dispatch",
            "status": "pending" if not stage.get("depends_on") else "blocked_by_dependency",
            "process_status": "queued",
            "process_by_role": {role: "queued" for role in _role_names(stage.get("roles") or [])},
            "artifact_quality": "missing",
            "artifact_quality_by_role": {},
            "handoff_state": "waiting",
            "handoff_by_role": {},
            "stage_gate": "ready" if not stage.get("depends_on") else "waiting",
            "accepted_artifacts_by_role": {},
            "active_roles": [],
            "completed_roles": [],
            "depends_on": stage.get("depends_on") or [],
            "planner_action": "dispatch_ready_stage",
            "delta_brief": stage.get("purpose", ""),
        }
        for stage in plan.get("stages") or []
    ]
    return {
        "workflow_run_id": run_id,
        "lane": plan.get("lane", ""),
        "plan_version": int(plan.get("plan_version") or 1),
        "plan_hash": str(plan.get("plan_hash") or ""),
        "routing_envelope_hash": str(plan.get("routing_envelope_hash") or ""),
        "intake_hash": str(plan.get("intake_hash") or ""),
        "strategy_binding": plan.get("strategy_binding") or _strategy_binding(None),
        "investor_context_binding": plan.get("investor_context_binding") or _context_binding(None),
        "routing_envelope": plan.get("routing_envelope") or {},
        "state_path": workflow_loop_relpath(run_id),
        "latest_state_path": LATEST_LOOP_STATE_PATH.as_posix(),
        "intake_path": (intake or {}).get("intake_path", ""),
        "plan_path": workflow_plan_relpath(run_id),
        "iteration": 0,
        "supervisor_round": 0,
        "process_event_count": 0,
        "state_revision": 0,
        "loop_policy": build_loop_policy(str(plan.get("lane") or "research_only")),
        "selected_team": _unique([role for stage in plan.get("stages") or [] for role in _role_names(stage.get("roles") or [])]),
        "allowed_followup_team": _unique([role for stage in plan.get("stages") or [] for role in _role_names(stage.get("roles") or [])]),
        "escalation_team": [],
        "stages": plan.get("stages") or [],
        "pending_tasks": pending_tasks,
        "completed_artifacts": [],
        "loop_decisions": [{
            "ts": _now(),
            "planner_action": "waiting" if pending_tasks else "synthesize",
            "reason": "Validated dynamic workflow plan recorded; hooks did not choose the final team.",
        }],
        "escalation_proposals": [],
        "blocked_actions": plan.get("blocked_actions") or [],
        "stop_reason": "waiting_for_validated_plan_dispatch" if pending_tasks else "head_manager_lane",
        "state_mode": "validated_dynamic_workflow_plan",
        "auto_spawn": False,
        "recursive_hook_dispatch": False,
        "updated_at": _now(),
    }


def compact_workflow_loop_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_run_id": state.get("workflow_run_id", ""),
        "lane": state.get("lane", ""),
        "state_path": state.get("state_path", ""),
        "plan_path": state.get("plan_path", ""),
        "plan_version": state.get("plan_version", 1),
        "plan_hash": state.get("plan_hash", ""),
        "routing_envelope_hash": state.get("routing_envelope_hash", ""),
        "strategy_binding": state.get("strategy_binding") or _strategy_binding(None),
        "investor_context_binding": state.get("investor_context_binding") or _context_binding(None),
        "state_revision": state.get("state_revision", 0),
        "iteration": state.get("iteration", 0),
        "supervisor_round": state.get("supervisor_round", 0),
        "process_event_count": state.get("process_event_count", 0),
        "selected_team": state.get("selected_team", []),
        "allowed_followup_team": state.get("allowed_followup_team", []),
        "escalation_team": state.get("escalation_team", []),
        "pending_tasks": state.get("pending_tasks", [])[:12],
        "completed_artifacts": state.get("completed_artifacts", [])[-12:],
        "loop_decisions": state.get("loop_decisions", [])[-12:],
        "blocked_actions": state.get("blocked_actions", []),
        "stop_reason": state.get("stop_reason", ""),
        "state_mode": state.get("state_mode", "validated_dynamic_workflow_plan"),
        "auto_spawn": False,
        "recursive_hook_dispatch": False,
        "updated_at": state.get("updated_at", ""),
    }


def _role_names(raw_roles: list[Any]) -> list[str]:
    roles: list[str] = []
    for item in raw_roles:
        role = item.get("role") if isinstance(item, dict) else item
        if role:
            roles.append(str(role))
    return roles
