from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from tradingcodex_service.application.agents import get_strategy_skill_record
from tradingcodex_service.application.common import (
    atomic_write_text,
    exclusive_file_lock,
    file_hash,
    now_iso,
    read_json,
    safe_workspace_path,
    sanitize_id,
    stable_hash,
    write_json,
)
from tradingcodex_service.application.investor_context import (
    INVESTOR_CONTEXT_ROOT,
    investor_context_binding,
    read_investor_context,
)
from tradingcodex_service.application.investment_brains import resolve_active_investment_brain
from tradingcodex_service.application.markdown_preview import split_markdown_frontmatter


MAINAGENT_ROOT = Path(".tradingcodex/mainagent")
ANALYSIS_RUNS_ROOT = MAINAGENT_ROOT / "runs"
ANALYSIS_RUN_FILE = "run.json"
STRATEGY_SNAPSHOT_FILE = "strategy-snapshot.md"
INVESTOR_CONTEXT_SNAPSHOT_FILE = "investor-context-snapshot.md"
EXPLICIT_STRATEGY_INVOCATION = re.compile(
    r"(?<![A-Za-z0-9_-])(\$strategy-[a-z0-9]+(?:-[a-z0-9]+)*)(?![A-Za-z0-9_-])"
)
EXPLICIT_INVESTMENT_BRAIN_INVOCATION = re.compile(
    r"(?<![A-Za-z0-9_-])(\$investment-brain-[a-z0-9]+(?:-[a-z0-9]+)*)(?![A-Za-z0-9_-])"
)


def new_analysis_run_id() -> str:
    return f"analysis-{uuid.uuid4().hex}"


def analysis_run_relpath(run_id: str) -> Path:
    _validate_run_id(run_id)
    return ANALYSIS_RUNS_ROOT / run_id / ANALYSIS_RUN_FILE


def analysis_run_dir(workspace_root: Path | str, run_id: str) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    _validate_run_id(run_id)
    return safe_workspace_path(root, ANALYSIS_RUNS_ROOT / run_id, allowed_roots=(ANALYSIS_RUNS_ROOT,))


def read_analysis_run(workspace_root: Path | str, run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    root = Path(workspace_root).expanduser().resolve()
    record = read_json(safe_workspace_path(root, analysis_run_relpath(run_id), allowed_roots=(ANALYSIS_RUNS_ROOT,)), {})
    if not isinstance(record, dict):
        raise ValueError("analysis run record is not a JSON object")
    if record and record.get("record_hash") != _record_hash(record):
        raise ValueError("analysis run integrity check failed")
    return record


def begin_analysis_run(
    workspace_root: Path | str,
    request: str,
    *,
    run_id: str = "",
    strategy_id: str = "",
    apply_investor_context: bool | None = None,
    strategy_binding: dict[str, Any] | None = None,
    context_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    request = str(request or "")
    if not request.strip():
        raise ValueError("request is required")
    run_id = run_id or new_analysis_run_id()
    _validate_run_id(run_id)
    existing = read_analysis_run(root, run_id)
    request_bytes = request.encode("utf-8")
    request_sha256 = hashlib.sha256(request_bytes).hexdigest()
    if existing:
        if existing.get("request_sha256") != request_sha256:
            raise ValueError("analysis run is already bound to a different request")
        return existing

    strategy_id = strategy_id or explicit_strategy_invocation(request)
    investment_brain_id = explicit_investment_brain_invocation(request)
    investment_brain_binding = select_investment_brain_binding(root, investment_brain_id)
    strategy_content = ""
    context_content = ""
    if strategy_binding is None:
        strategy_binding, strategy_content = select_strategy_binding(root, strategy_id)
    elif strategy_id and str(strategy_binding.get("strategy_id") or "") != strategy_id:
        raise ValueError("explicit strategy selection does not match the supplied binding")
    if context_binding is None:
        context_binding, context_content = select_investor_context_binding(root, apply_investor_context)
    strategy_binding, context_binding = seal_analysis_run_bindings(
        root,
        run_id,
        strategy_binding=strategy_binding,
        context_binding=context_binding,
        strategy_content=strategy_content,
        context_content=context_content,
    )
    record = {
        "schema_version": 1,
        "marker": "tradingcodex-analysis-run",
        "workflow_run_id": run_id,
        "created_at": now_iso(),
        "request_sha256": request_sha256,
        "request_bytes": len(request_bytes),
        "strategy_binding": strategy_binding,
        "investor_context_binding": context_binding,
        "investment_brain_binding": investment_brain_binding,
        "orchestration_owner": "codex-head-manager",
        "service_authority": "persistence-policy-execution",
    }
    record["record_hash"] = _record_hash(record)
    path = safe_workspace_path(root, analysis_run_relpath(run_id), allowed_roots=(ANALYSIS_RUNS_ROOT,))
    with exclusive_file_lock(path):
        current = read_json(path, {})
        if current:
            if not isinstance(current, dict) or current.get("record_hash") != _record_hash(current):
                raise ValueError("analysis run record changed while it was being created")
            if current.get("request_sha256") != request_sha256:
                raise ValueError("analysis run is already bound to a different request")
            return current
        write_json(path, record)
    return record


def explicit_strategy_invocation(prompt: str) -> str:
    names = [item.removeprefix("$") for item in dict.fromkeys(EXPLICIT_STRATEGY_INVOCATION.findall(prompt or ""))]
    if len(names) > 1:
        raise ValueError("select exactly one explicit $strategy-* skill for an analysis run")
    return names[0] if names else ""


def explicit_investment_brain_invocation(prompt: str) -> str:
    names = [
        item.removeprefix("$")
        for item in dict.fromkeys(EXPLICIT_INVESTMENT_BRAIN_INVOCATION.findall(prompt or ""))
    ]
    if len(names) > 1:
        raise ValueError("select exactly one explicit $investment-brain-* skill for an analysis run")
    return names[0] if names else ""


def select_investment_brain_binding(workspace_root: Path | str, brain_id: str) -> dict[str, Any]:
    if not brain_id:
        return _investment_brain_binding(None)
    resolved = resolve_active_investment_brain(Path(workspace_root).expanduser().resolve(), brain_id)
    binding = _investment_brain_binding(resolved)
    if binding["brain_id"] != brain_id:
        raise ValueError("resolved Investment Brain id does not match the explicit invocation")
    if not binding["version"]:
        raise ValueError(f"Investment Brain version is unavailable: {brain_id}")
    if not re.fullmatch(r"[0-9a-f]{64}", binding["content_digest"]):
        raise ValueError(f"Investment Brain content digest is invalid: {brain_id}")
    if not re.fullmatch(r"[0-9a-f]{64}", binding["skill_digest"]):
        raise ValueError(f"Investment Brain skill digest is invalid: {brain_id}")
    if not binding["source_file"] or not binding["projected_skill_path"]:
        raise ValueError(f"Investment Brain projection is unavailable: {brain_id}")
    return binding


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
    if record.get("source_file_hash") and record["source_file_hash"] != content_hash:
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
        return _context_binding(binding), ""
    context = read_investor_context(root)
    if context.get("source") != "workspace_file":
        raise ValueError("applied investor context must come from the workspace file")
    source = safe_workspace_path(root, str(context.get("path") or ""), allowed_roots=(INVESTOR_CONTEXT_ROOT,))
    try:
        source_bytes = source.read_bytes()
        content = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("workspace investor context is unavailable") from exc
    if hashlib.sha256(source_bytes).hexdigest() != binding.get("content_hash"):
        raise ValueError("investor context changed while it was being bound")
    return _context_binding(binding), content


def seal_analysis_run_bindings(
    workspace_root: Path | str,
    run_id: str,
    *,
    strategy_binding: dict[str, Any] | None,
    context_binding: dict[str, Any] | None,
    strategy_content: str = "",
    context_content: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(workspace_root).expanduser().resolve()
    _validate_run_id(run_id)
    run_dir = safe_workspace_path(root, ANALYSIS_RUNS_ROOT / run_id, allowed_roots=(ANALYSIS_RUNS_ROOT,))
    sealed_strategy = _strategy_binding(strategy_binding)
    sealed_context = _context_binding(context_binding)

    if sealed_strategy["strategy_id"]:
        if not strategy_content:
            selected, strategy_content = select_strategy_binding(root, sealed_strategy["strategy_id"])
            _require_same_binding(sealed_strategy, selected, ("strategy_id", "source_file", "content_hash"), "strategy")
            sealed_strategy = selected
        if hashlib.sha256(strategy_content.encode("utf-8")).hexdigest() != sealed_strategy["content_hash"]:
            raise ValueError("strategy content hash does not match its binding")
        path = run_dir / STRATEGY_SNAPSHOT_FILE
        _write_immutable_snapshot(path, strategy_content, sealed_strategy["content_hash"])
        sealed_strategy["snapshot_path"] = path.relative_to(root).as_posix()
    elif any(sealed_strategy.get(field) for field in ("source_file", "content_hash", "snapshot_path")):
        raise ValueError("no-strategy binding must not contain strategy provenance")

    if sealed_context.get("applied"):
        if not context_content:
            selected, context_content = select_investor_context_binding(root, True)
            _require_same_binding(
                sealed_context,
                selected,
                ("applied", "configured", "enabled_by_default", "source", "path", "content_hash", "fields"),
                "investor context",
            )
            sealed_context = selected
        path = run_dir / INVESTOR_CONTEXT_SNAPSHOT_FILE
        _write_immutable_snapshot(path, context_content, sealed_context["content_hash"])
        _verify_context_snapshot(path, sealed_context)
        sealed_context["snapshot_path"] = path.relative_to(root).as_posix()
    elif sealed_context.get("snapshot_path"):
        raise ValueError("disabled investor context must not contain a run snapshot")
    # The snapshot is privacy-ignored workspace state. Keep only its hash/path
    # binding in the versionable run record, never the private suitability body.
    sealed_context.pop("fields", None)
    return sealed_strategy, sealed_context


def _write_immutable_snapshot(path: Path, content: str, expected_hash: str) -> None:
    with exclusive_file_lock(path):
        if path.exists():
            if not path.is_file() or file_hash(path) != expected_hash:
                raise ValueError(f"protected analysis snapshot already exists with different content: {path.name}")
        else:
            atomic_write_text(path, content)


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


def _require_same_binding(
    recorded: dict[str, Any],
    current: dict[str, Any],
    fields: tuple[str, ...],
    label: str,
) -> None:
    if any(recorded.get(field) != current.get(field) for field in fields):
        raise ValueError(f"{label} changed while it was being bound")


def _strategy_binding(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    return {
        "strategy_id": str(value.get("strategy_id") or ""),
        "source_file": str(value.get("source_file") or ""),
        "content_hash": str(value.get("content_hash") or ""),
        "snapshot_path": str(value.get("snapshot_path") or ""),
    }


def _context_binding(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    fields = value.get("fields") if isinstance(value.get("fields"), dict) else {}
    return {
        "configured": bool(value.get("configured")),
        "enabled_by_default": bool(value.get("enabled_by_default")),
        "applied": bool(value.get("applied")),
        "source": str(value.get("source") or ""),
        "path": str(value.get("path") or ""),
        "content_hash": str(value.get("content_hash") or ""),
        "snapshot_path": str(value.get("snapshot_path") or ""),
        "fields": {str(key): fields[key] for key in sorted(fields)},
    }


def _investment_brain_binding(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    raw_source = value.get("source") if isinstance(value.get("source"), dict) else {}
    declared = raw_source.get("declared") if isinstance(raw_source.get("declared"), dict) else {}
    return {
        "brain_id": str(value.get("brain_id") or ""),
        "version": str(value.get("version") or ""),
        "content_digest": str(value.get("content_digest") or ""),
        "skill_digest": str(value.get("skill_digest") or ""),
        "source": {
            "kind": str(raw_source.get("kind") or ""),
            "location": str(raw_source.get("location") or ""),
            "ref": str(raw_source.get("ref") or ""),
            "resolved_revision": str(raw_source.get("resolved_revision") or ""),
            "declared": {
                "publisher": str(declared.get("publisher") or ""),
                "repository": str(declared.get("repository") or ""),
                "license": str(declared.get("license") or ""),
            },
        },
        "manifest_path": str(value.get("manifest_path") or ""),
        "source_file": str(value.get("source_file") or ""),
        "projected_skill_path": str(value.get("projected_skill_path") or ""),
    }


def _record_hash(record: dict[str, Any]) -> str:
    return stable_hash({key: value for key, value in record.items() if key != "record_hash"})


def _validate_run_id(run_id: str) -> None:
    if not run_id or sanitize_id(run_id) != run_id or len(run_id) > 180:
        raise ValueError("invalid analysis run id")
