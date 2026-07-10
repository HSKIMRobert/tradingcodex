from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import atomic_write_text, exclusive_file_lock, file_hash, now_iso, safe_workspace_path, sanitize_id, stable_hash
from tradingcodex_service.application.forecasting import get_forecast, is_forecast_event_anchored
from tradingcodex_service.application.harness import build_subagent_starter_prompt, build_workflow_intake_summary
from tradingcodex_service.application.markdown_preview import split_markdown_frontmatter
from tradingcodex_service.application.research_specs import EVIDENCE_LANES
from tradingcodex_service.application.runtime import ensure_runtime_database, workspace_context_payload
from tradingcodex_service.application.workflow_contracts import intake_contract_hash, workflow_plan_hash
from tradingcodex_service.application.workflow_planner import (
    build_deterministic_workflow_plan,
    read_workflow_intake,
    workflow_intake_relpath,
    workflow_plan_relpath,
)

DECISION_ROOT = Path("trading/decisions")
WORKFLOW_RUN_ROOT = Path("trading/workflows/runs")
DECISION_ARTIFACT_ROOTS = (Path("trading/research"), Path("trading/reports"), DECISION_ROOT)
NON_INVESTMENT_WORKFLOW_LANES = {"connector_build", "head_manager_connector_operations", "head_manager_strategy_authoring"}


def build_workflow_plan(workspace_root: Path | str, prompt: str, *, workflow_run_id: str = "") -> dict[str, Any]:
    if not prompt.strip():
        raise ValueError("prompt is required")
    summary = build_workflow_intake_summary(prompt, workspace_root)
    staged_plan = build_deterministic_workflow_plan(workspace_root, prompt, workflow_run_id=workflow_run_id)
    return {
        "workflow_run_id": staged_plan["workflow_run_id"],
        "lane": summary["workflow_lane"],
        "universe": summary["investment_universe"],
        "universe_label": summary["investment_universe_label"],
        "selected_roles": [item["role"] for item in summary.get("subagents") or []],
        "staged_plan": staged_plan,
        "dynamic_plan_required": True,
        "missing_profile": summary.get("investor_profile_inputs") or [],
        "blocked_actions": summary.get("blocked_actions") or [],
        "routing_flags": summary.get("routing_flags") or {},
        "allowed_next_actions": summary.get("next_allowed_actions") or [],
        "starter_prompt": build_subagent_starter_prompt(prompt, workspace_root),
        "intake_summary": summary,
        "workspace_native": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def create_decision_package(workspace_root: Path | str, prompt: str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    suffix = _decision_suffix(prompt)
    run_id = f"workflow-{suffix}"
    decision_id = f"decision-{suffix}"
    plan = build_workflow_plan(root, prompt, workflow_run_id=run_id)
    package_rel = DECISION_ROOT / f"{decision_id}.md"
    run_rel = WORKFLOW_RUN_ROOT / f"{run_id}.json"
    metadata = _run_metadata(run_id, decision_id, prompt, plan, package_rel)

    run_path = safe_workspace_path(root, run_rel, allowed_roots=(WORKFLOW_RUN_ROOT,))
    run_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(run_path, json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n")

    package_path = safe_workspace_path(root, package_rel, allowed_roots=(DECISION_ROOT,))
    package_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(package_path, _decision_markdown(metadata, plan))
    _store_workflow_run(root, metadata)

    return {
        "status": "planned",
        "run_id": run_id,
        "decision_id": decision_id,
        "workflow_run_path": run_rel.as_posix(),
        "decision_package_path": package_rel.as_posix(),
        "plan": plan,
        "workspace_native": True,
        "workspace_context": plan["workspace_context"],
    }


def record_decision_snapshot(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    recorded_at = _iso(now_iso(), "system recorded_at")
    workflow_run_id = _required_text(args, "workflow_run_id")
    decided_at = _iso(args.get("decided_at") or recorded_at, "decided_at")
    knowledge_cutoff = _iso(args.get("knowledge_cutoff"), "knowledge_cutoff")
    if knowledge_cutoff > decided_at:
        raise ValueError("knowledge_cutoff must not be after decided_at")
    decision_artifact_ref = _decision_artifact_ref(root, args, workflow_run_id)
    forecast_ids = args.get("forecast_ids") if isinstance(args.get("forecast_ids"), list) else []
    forecast_refs = _decision_forecast_refs(root, forecast_ids, decided_at, knowledge_cutoff, workflow_run_id)
    forecast_lanes = {str(ref.get("evidence_lane") or "") for ref in forecast_refs}
    requested_lane = str(args.get("evidence_lane") or "").strip()
    if len(forecast_lanes) > 1:
        raise ValueError("one decision snapshot cannot mix forecast evidence lanes")
    evidence_lane = next(iter(forecast_lanes), requested_lane or "live_forward")
    if requested_lane and requested_lane != evidence_lane:
        raise ValueError("decision evidence_lane must match its forecast references")
    if evidence_lane not in EVIDENCE_LANES:
        raise ValueError(f"evidence_lane must be one of: {', '.join(sorted(EVIDENCE_LANES))}")
    forecast_block_reason = str(args.get("forecast_block_reason") or "").strip()
    if not forecast_refs and not forecast_block_reason:
        raise ValueError("forecast_ids or forecast_block_reason is required")
    if recorded_at < decided_at:
        raise ValueError("decided_at must not be after system recorded_at")
    created_by = _required_text(args, "created_by")
    if created_by != "head-manager":
        raise PermissionError("decision snapshots must be recorded by head-manager")
    intake_ref, workflow_plan_ref, strategy_ref, context_ref = _recorded_run_bindings(
        root,
        workflow_run_id,
        args,
        evidence_lane=evidence_lane,
        decided_at=decided_at,
    )
    _validate_decision_artifact_time(decision_artifact_ref, evidence_lane, knowledge_cutoff, decided_at)
    artifact_plan_hash = str(decision_artifact_ref.get("plan_hash") or "")
    if not artifact_plan_hash:
        raise ValueError("decision artifact plan_hash is required")
    if artifact_plan_hash != workflow_plan_ref["plan_hash"]:
        raise ValueError("decision artifact plan_hash does not match the recorded workflow plan")
    requested_plan_hash = str(args.get("plan_hash") or "").strip()
    if requested_plan_hash and requested_plan_hash != workflow_plan_ref["plan_hash"]:
        raise ValueError("plan_hash does not match the recorded workflow plan")
    seed = {
        "intake_hash": intake_ref["intake_hash"],
        "workflow_run_id": workflow_run_id,
        "decision_artifact_sha256": decision_artifact_ref["sha256"],
        "forecast_event_hashes": [ref["event_hash"] for ref in forecast_refs],
        "decided_at": decided_at,
    }
    decision_id = sanitize_id(args.get("decision_id") or f"decision-snapshot-{stable_hash(seed)[:16]}")
    snapshot = {
        "schema_version": 2,
        "artifact_type": "decision_snapshot",
        "decision_id": decision_id,
        "workflow_run_id": workflow_run_id,
        "plan_hash": workflow_plan_ref["plan_hash"],
        "evidence_lane": evidence_lane,
        "regime": str(args.get("regime") or "unclassified"),
        "knowledge_cutoff": knowledge_cutoff,
        "decided_at": decided_at,
        "created_at": recorded_at,
        "recorded_at": recorded_at,
        "created_by": created_by,
        "workflow_intake_ref": intake_ref,
        "workflow_plan_ref": workflow_plan_ref,
        "decision_artifact_ref": decision_artifact_ref,
        "forecast_refs": forecast_refs,
        "forecast_block_reason": forecast_block_reason,
        "strategy_ref": strategy_ref,
        "investor_context_ref": context_ref,
        "authority": "evidence_only",
        "blocked_actions": ["order_approval", "order_execution"],
    }
    snapshot["snapshot_hash"] = stable_hash(snapshot)
    path = safe_workspace_path(root, DECISION_ROOT / f"{decision_id}.decision-snapshot.json", allowed_roots=(DECISION_ROOT,))
    with exclusive_file_lock(path):
        if path.exists():
            existing = _read_decision_snapshot(path)
            if existing.get("snapshot_hash") == snapshot["snapshot_hash"]:
                status = "existing"
                snapshot = existing
            else:
                raise ValueError(f"decision snapshot is immutable and already exists: {decision_id}")
        else:
            atomic_write_text(path, json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            status = "recorded"
    _verify_decision_snapshot_refs(root, snapshot)
    return {
        "status": status,
        "decision_snapshot": snapshot,
        "export_path": path.relative_to(root).as_posix(),
        "workspace_native": True,
        "authority": "evidence_only",
        "workspace_context": workspace_context_payload(root),
    }


def get_decision_snapshot(workspace_root: Path | str, decision_id: str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not decision_id:
        raise ValueError("decision_id is required")
    path = safe_workspace_path(root, DECISION_ROOT / f"{sanitize_id(decision_id)}.decision-snapshot.json", allowed_roots=(DECISION_ROOT,))
    if not path.exists():
        raise ValueError(f"decision snapshot not found: {decision_id}")
    snapshot = _read_decision_snapshot(path)
    verification_status = "legacy_non_promotable"
    if int(snapshot.get("schema_version") or 0) >= 2:
        _verify_decision_snapshot_refs(root, snapshot)
        verification_status = "verified"
    return {
        "status": "ok",
        "decision_snapshot": snapshot,
        "verification_status": verification_status,
        "export_path": path.relative_to(root).as_posix(),
        "workspace_native": True,
        "authority": "evidence_only",
        "workspace_context": workspace_context_payload(root),
    }


def verify_decision_snapshot(workspace_root: Path | str, decision_id: str) -> dict[str, Any]:
    result = get_decision_snapshot(workspace_root, decision_id)
    if result.get("verification_status") != "verified":
        raise ValueError("legacy decision snapshot is readable but non-promotable")
    return result


def list_decision_snapshots(workspace_root: Path | str, limit: int = 50) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    items = []
    for path in sorted((root / DECISION_ROOT).glob("*.decision-snapshot.json")):
        snapshot = _read_decision_snapshot(path)
        verification_status = "legacy_non_promotable"
        if int(snapshot.get("schema_version") or 0) >= 2:
            _verify_decision_snapshot_refs(root, snapshot)
            verification_status = "verified"
        items.append({
            "decision_id": snapshot.get("decision_id", ""),
            "workflow_run_id": snapshot.get("workflow_run_id", ""),
            "evidence_lane": snapshot.get("evidence_lane", ""),
            "decided_at": snapshot.get("decided_at", ""),
            "strategy_name": (snapshot.get("strategy_ref") or {}).get("name", "no_strategy"),
            "snapshot_hash": snapshot.get("snapshot_hash", ""),
            "path": path.relative_to(root).as_posix(),
            "verification_status": verification_status,
        })
    items.sort(key=lambda item: str(item["decided_at"]), reverse=True)
    return {
        "decision_snapshots": items[: max(1, min(int(limit), 200))],
        "count": len(items),
        "workspace_native": True,
        "authority": "evidence_only",
        "workspace_context": workspace_context_payload(root),
    }


def list_decision_packages(workspace_root: Path | str, limit: int = 50) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    packages = [_decision_payload(root, path) for path in sorted((root / DECISION_ROOT).glob("*.md"))]
    packages.sort(key=lambda item: item["updated_at"], reverse=True)
    return {
        "packages": packages[: max(1, min(int(limit), 200))],
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }


def get_decision_package(workspace_root: Path | str, decision_id: str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not decision_id:
        raise ValueError("decision_id is required")
    for path in sorted((root / DECISION_ROOT).glob("*.md")):
        payload = _decision_payload(root, path, include_markdown=True)
        if decision_id in {payload["decision_id"], payload["path"]}:
            return payload
    raise ValueError(f"decision package not found: {decision_id}")


def export_decision_package(workspace_root: Path | str, decision_id: str, export_path: str | None = None) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    package = get_decision_package(root, decision_id)
    source = safe_workspace_path(root, package["path"], allowed_roots=(DECISION_ROOT,))
    target_rel = export_path or package["path"]
    target = safe_workspace_path(root, target_rel, allowed_roots=(DECISION_ROOT,))
    if target.resolve() != source.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, source.read_text(encoding="utf-8"))
    return {
        "status": "exported",
        "decision_id": package["decision_id"],
        "export_path": target.relative_to(root).as_posix(),
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }


def _decision_artifact_ref(root: Path, args: dict[str, Any], workflow_run_id: str) -> dict[str, Any]:
    raw_path = _required_text(args, "decision_artifact_path")
    path = safe_workspace_path(root, raw_path, allowed_roots=DECISION_ARTIFACT_ROOTS)
    if not path.exists() or not path.is_file():
        raise ValueError(f"decision artifact does not exist: {raw_path}")
    ref: dict[str, Any] = {
        "path": path.relative_to(root).as_posix(),
        "sha256": file_hash(path),
    }
    if path.suffix.lower() == ".md":
        document = split_markdown_frontmatter(path.read_text(encoding="utf-8"))
        frontmatter = document.frontmatter
        if str(frontmatter.get("handoff_state") or "") != "accepted":
            raise ValueError("decision artifact must have accepted handoff_state")
        if str(frontmatter.get("workflow_run_id") or "") != workflow_run_id:
            raise ValueError("decision artifact workflow_run_id does not match the decision snapshot")
        body_hash = hashlib.sha256(document.body.encode("utf-8")).hexdigest()
        declared_hash = str(frontmatter.get("content_hash") or "")
        if not declared_hash or declared_hash != body_hash:
            raise ValueError("decision artifact content_hash does not match its body")
        ref.update({
            "artifact_id": str(frontmatter.get("artifact_id") or path.stem),
            "artifact_type": str(frontmatter.get("artifact_type") or ""),
            "content_hash": body_hash,
            "plan_hash": str(frontmatter.get("plan_hash") or ""),
            "knowledge_cutoff": str(frontmatter.get("knowledge_cutoff") or frontmatter.get("source_as_of") or ""),
            "evidence_lane": str(frontmatter.get("evidence_lane") or ""),
            "recorded_at": str(frontmatter.get("recorded_at") or ""),
        })
    else:
        ref.update({"artifact_id": str(args.get("decision_artifact_id") or path.stem), "artifact_type": "decision_artifact"})
    return ref


def _decision_forecast_refs(
    root: Path,
    forecast_ids: list[Any],
    decided_at: str,
    knowledge_cutoff: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_forecast_id in forecast_ids:
        forecast_id = str(raw_forecast_id or "").strip()
        if not forecast_id or forecast_id in seen:
            continue
        seen.add(forecast_id)
        history = get_forecast(root, {"forecast_id": forecast_id, "include_history": True})["history"]
        eligible = [
            event
            for event in history
            if event.get("event_type") in {"issued", "revised"}
            and str(event.get("revised_at") or event.get("issued_at") or "") <= decided_at
        ]
        if not eligible:
            raise ValueError(f"forecast has no decision-time event at or before decided_at: {forecast_id}")
        event = eligible[-1]
        if not event.get("event_hash") or not is_forecast_event_anchored(root, event):
            raise ValueError(f"forecast event is legacy or not chain-anchored: {forecast_id}")
        if str(event.get("workflow_run_id") or "") != workflow_run_id:
            raise ValueError(f"forecast belongs to another workflow run: {forecast_id}")
        event_cutoff = _iso(event.get("knowledge_cutoff"), f"forecast {forecast_id} knowledge_cutoff")
        if event_cutoff > knowledge_cutoff:
            raise ValueError(f"forecast knowledge_cutoff exceeds decision cutoff: {forecast_id}")
        event_recorded_at = _iso(event.get("recorded_at"), f"forecast {forecast_id} recorded_at")
        if event.get("evidence_lane") == "live_forward" and event_recorded_at > decided_at:
            raise ValueError(f"live_forward forecast was stored after decided_at: {forecast_id}")
        origin_ref = event.get("origin_artifact_ref") if isinstance(event.get("origin_artifact_ref"), dict) else {}
        if origin_ref.get("binding_status") != "verified":
            raise ValueError(f"forecast origin artifact is not verified: {forecast_id}")
        _verify_path_hash(root, origin_ref, DECISION_ARTIFACT_ROOTS, f"forecast origin artifact {forecast_id}")
        refs.append({
            "forecast_id": forecast_id,
            "event_id": event["event_id"],
            "event_hash": event["event_hash"],
            "version": event["version"],
            "forecast_target": event["forecast_target"],
            "horizon": event["horizon"],
            "workflow_run_id": workflow_run_id,
            "knowledge_cutoff": event_cutoff,
            "recorded_at": event_recorded_at,
            "evidence_lane": event.get("evidence_lane") or "",
            "origin_artifact_ref": origin_ref,
            "research_spec_ref": event.get("research_spec_ref") or {},
            "replay_manifest_ref": event.get("replay_manifest_ref") or {},
        })
    return refs


def _recorded_run_bindings(
    root: Path,
    workflow_run_id: str,
    args: dict[str, Any],
    *,
    evidence_lane: str,
    decided_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    intake = read_workflow_intake(root, workflow_run_id)
    if not intake or str(intake.get("workflow_run_id") or "") != workflow_run_id:
        raise ValueError("recorded workflow intake is required for a decision snapshot")
    expected_intake_hash = intake_contract_hash(intake)
    if str(intake.get("intake_hash") or "") != expected_intake_hash:
        raise ValueError("recorded workflow intake hash mismatch")
    intake_path = safe_workspace_path(
        root,
        workflow_intake_relpath(workflow_run_id),
        allowed_roots=(Path(".tradingcodex/mainagent/workflows"),),
    )
    if not intake_path.exists():
        raise ValueError("recorded workflow intake file is missing")
    intake_ref = {
        "workflow_run_id": workflow_run_id,
        "path": intake_path.relative_to(root).as_posix(),
        "sha256": file_hash(intake_path),
        "intake_hash": expected_intake_hash,
        "recorded_at": str(intake.get("created_at") or ""),
    }
    workflow_plan_ref = _recorded_workflow_plan_ref(root, workflow_run_id, intake, expected_intake_hash)
    if evidence_lane == "live_forward":
        if _iso(intake_ref["recorded_at"], "workflow intake recorded_at") > decided_at:
            raise ValueError("live_forward workflow intake was stored after decided_at")
        if _iso(workflow_plan_ref["recorded_at"], "workflow plan recorded_at") > decided_at:
            raise ValueError("live_forward workflow plan was stored after decided_at")
    strategy_ref = _frozen_strategy_ref(root, intake.get("strategy_binding"), args)
    context_ref = _frozen_context_ref(root, intake.get("investor_context_binding"), args)
    return intake_ref, workflow_plan_ref, strategy_ref, context_ref


def _recorded_workflow_plan_ref(
    root: Path,
    workflow_run_id: str,
    intake: dict[str, Any],
    expected_intake_hash: str,
) -> dict[str, Any]:
    path = safe_workspace_path(
        root,
        workflow_plan_relpath(workflow_run_id),
        allowed_roots=(Path(".tradingcodex/mainagent/workflows"),),
    )
    if not path.exists() or not path.is_file():
        raise ValueError("recorded workflow plan is required for a decision snapshot")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("recorded workflow plan is invalid") from exc
    if not isinstance(plan, dict):
        raise ValueError("recorded workflow plan must be an object")
    if str(plan.get("workflow_run_id") or "") != workflow_run_id:
        raise ValueError("recorded workflow plan belongs to another workflow run")
    if str(plan.get("intake_hash") or "") != expected_intake_hash:
        raise ValueError("recorded workflow plan does not bind the recorded workflow intake")
    declared_plan_hash = str(plan.get("plan_hash") or "")
    if not declared_plan_hash or declared_plan_hash != workflow_plan_hash(plan):
        raise ValueError("recorded workflow plan hash mismatch")
    validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
    if validation.get("ok") is not True or str(validation.get("plan_hash") or "") != declared_plan_hash:
        raise ValueError("recorded workflow plan lacks a matching successful validation")
    if plan.get("strategy_binding") != intake.get("strategy_binding"):
        raise ValueError("recorded workflow plan strategy binding does not match its intake")
    if plan.get("investor_context_binding") != intake.get("investor_context_binding"):
        raise ValueError("recorded workflow plan investor context binding does not match its intake")
    return {
        "workflow_run_id": workflow_run_id,
        "path": path.relative_to(root).as_posix(),
        "sha256": file_hash(path),
        "plan_hash": declared_plan_hash,
        "routing_envelope_hash": str(plan.get("routing_envelope_hash") or ""),
        "recorded_at": str(plan.get("recorded_at") or ""),
    }


def _frozen_strategy_ref(root: Path, raw: Any, args: dict[str, Any]) -> dict[str, Any]:
    binding = raw if isinstance(raw, dict) else {}
    strategy_id = str(binding.get("strategy_id") or "")
    requested = str(args.get("strategy_name") or "").strip()
    if requested and requested != (strategy_id or "no_strategy"):
        raise ValueError("strategy_name does not match the recorded workflow intake")
    if not strategy_id:
        return {"name": "no_strategy", "applied": False}
    snapshot_path = str(binding.get("snapshot_path") or "")
    content_hash = str(binding.get("content_hash") or "")
    if not snapshot_path or not content_hash:
        raise ValueError("recorded strategy binding lacks an immutable run snapshot")
    path = safe_workspace_path(root, snapshot_path, allowed_roots=(Path(".tradingcodex/mainagent/workflows"),))
    digest = file_hash(path) or ""
    if not digest or digest != content_hash:
        raise ValueError("recorded strategy snapshot hash mismatch")
    return {
        "name": strategy_id,
        "applied": True,
        "source_file": str(binding.get("source_file") or ""),
        "snapshot_path": path.relative_to(root).as_posix(),
        "content_hash": digest,
    }


def _frozen_context_ref(root: Path, raw: Any, args: dict[str, Any]) -> dict[str, Any]:
    binding = dict(raw) if isinstance(raw, dict) else {}
    applied = bool(binding.get("applied"))
    if "investor_context_applied" in args and bool(args.get("investor_context_applied")) != applied:
        raise ValueError("investor_context_applied does not match the recorded workflow intake")
    fields = dict(binding.get("fields") or {})
    result = {
        "schema_version": int(binding.get("schema_version") or 1),
        "applied": applied,
        "configured": bool(binding.get("configured")),
        "enabled_by_default": bool(binding.get("enabled_by_default", True)),
        "source": str(binding.get("source") or "none"),
        "path": str(binding.get("path") or ""),
        "content_hash": str(binding.get("content_hash") or ""),
        "snapshot_path": str(binding.get("snapshot_path") or ""),
    }
    if not applied:
        return result
    if not result["snapshot_path"] or not result["content_hash"]:
        raise ValueError("recorded investor context binding lacks an immutable run snapshot")
    path = safe_workspace_path(root, result["snapshot_path"], allowed_roots=(Path(".tradingcodex/mainagent/workflows"),))
    if not path.exists() or not path.is_file():
        raise ValueError("recorded investor context snapshot is missing")
    content = path.read_text(encoding="utf-8")
    digest = file_hash(path) or ""
    if result["source"] == "workspace_file":
        if digest != result["content_hash"]:
            raise ValueError("recorded investor context snapshot hash mismatch")
    else:
        frontmatter = split_markdown_frontmatter(content).frontmatter
        if str(frontmatter.get("source_content_hash") or "") != result["content_hash"]:
            raise ValueError("recorded investor context provenance hash mismatch")
        if any(frontmatter.get(key) != value for key, value in fields.items()):
            raise ValueError("recorded investor context snapshot fields mismatch")
    return {**result, "snapshot_sha256": digest}


def _validate_decision_artifact_time(ref: dict[str, Any], evidence_lane: str, knowledge_cutoff: str, decided_at: str) -> None:
    artifact_cutoff = _iso(ref.get("knowledge_cutoff"), "decision artifact knowledge_cutoff")
    if artifact_cutoff > knowledge_cutoff:
        raise ValueError("decision artifact knowledge_cutoff exceeds the decision cutoff")
    artifact_lane = str(ref.get("evidence_lane") or "")
    if artifact_lane and artifact_lane != evidence_lane:
        raise ValueError("decision artifact evidence_lane does not match the decision snapshot")
    recorded_at = _iso(ref.get("recorded_at"), "decision artifact recorded_at")
    if evidence_lane == "live_forward" and recorded_at > decided_at:
        raise ValueError("live_forward decision artifact was stored after decided_at")


def _verify_decision_snapshot_refs(root: Path, snapshot: dict[str, Any]) -> None:
    if int(snapshot.get("schema_version") or 0) < 2:
        raise ValueError("legacy decision snapshot is readable but non-promotable")
    workflow_run_id = str(snapshot.get("workflow_run_id") or "")
    evidence_lane = str(snapshot.get("evidence_lane") or "")
    knowledge_cutoff = _iso(snapshot.get("knowledge_cutoff"), "decision snapshot knowledge_cutoff")
    decided_at = _iso(snapshot.get("decided_at"), "decision snapshot decided_at")
    recorded_at = _iso(snapshot.get("recorded_at"), "decision snapshot recorded_at")
    if knowledge_cutoff > decided_at or decided_at > recorded_at:
        raise ValueError("decision snapshot time ordering is invalid")

    intake_ref = snapshot.get("workflow_intake_ref") if isinstance(snapshot.get("workflow_intake_ref"), dict) else {}
    intake_path = _verify_path_hash(
        root,
        intake_ref,
        (Path(".tradingcodex/mainagent/workflows"),),
        "workflow intake",
    )
    intake = json.loads(intake_path.read_text(encoding="utf-8"))
    if (
        str(intake.get("workflow_run_id") or "") != workflow_run_id
        or intake_contract_hash(intake) != intake_ref.get("intake_hash")
        or str(intake.get("created_at") or "") != intake_ref.get("recorded_at")
    ):
        raise ValueError("decision snapshot workflow intake binding mismatch")

    plan_ref = snapshot.get("workflow_plan_ref") if isinstance(snapshot.get("workflow_plan_ref"), dict) else {}
    plan_path = _verify_path_hash(
        root,
        plan_ref,
        (Path(".tradingcodex/mainagent/workflows"),),
        "workflow plan",
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if (
        str(plan.get("workflow_run_id") or "") != workflow_run_id
        or str(plan.get("plan_hash") or "") != snapshot.get("plan_hash")
        or workflow_plan_hash(plan) != snapshot.get("plan_hash")
        or str(plan.get("recorded_at") or "") != plan_ref.get("recorded_at")
    ):
        raise ValueError("decision snapshot workflow plan binding mismatch")

    artifact_ref = snapshot.get("decision_artifact_ref") if isinstance(snapshot.get("decision_artifact_ref"), dict) else {}
    artifact_path = _verify_path_hash(root, artifact_ref, DECISION_ARTIFACT_ROOTS, "decision artifact")
    document = split_markdown_frontmatter(artifact_path.read_text(encoding="utf-8"))
    body_hash = hashlib.sha256(document.body.encode("utf-8")).hexdigest()
    if (
        body_hash != artifact_ref.get("content_hash")
        or document.frontmatter.get("handoff_state") != "accepted"
        or str(document.frontmatter.get("workflow_run_id") or "") != workflow_run_id
        or str(document.frontmatter.get("plan_hash") or "") != snapshot.get("plan_hash")
        or str(document.frontmatter.get("recorded_at") or "") != artifact_ref.get("recorded_at")
        or str(document.frontmatter.get("knowledge_cutoff") or document.frontmatter.get("source_as_of") or "") != artifact_ref.get("knowledge_cutoff")
    ):
        raise ValueError("decision snapshot accepted artifact binding mismatch")
    _validate_decision_artifact_time(artifact_ref, evidence_lane, knowledge_cutoff, decided_at)
    if evidence_lane == "live_forward" and (
        _iso(intake_ref.get("recorded_at"), "workflow intake recorded_at") > decided_at
        or _iso(plan_ref.get("recorded_at"), "workflow plan recorded_at") > decided_at
    ):
        raise ValueError("live_forward workflow binding was stored after decided_at")

    for ref in snapshot.get("forecast_refs") or []:
        if not isinstance(ref, dict):
            raise ValueError("decision snapshot forecast refs must be objects")
        history = get_forecast(root, {"forecast_id": str(ref.get("forecast_id") or ""), "include_history": True})["history"]
        event = next((item for item in history if item.get("event_id") == ref.get("event_id")), None)
        if not event or event.get("event_hash") != ref.get("event_hash") or not is_forecast_event_anchored(root, event):
            raise ValueError("decision snapshot forecast event binding mismatch")
        if (
            str(event.get("workflow_run_id") or "") != workflow_run_id
            or str(event.get("evidence_lane") or "") != evidence_lane
            or _iso(event.get("knowledge_cutoff"), "forecast knowledge_cutoff") > knowledge_cutoff
        ):
            raise ValueError("decision snapshot forecast provenance mismatch")
        event_recorded_at = _iso(event.get("recorded_at"), "forecast recorded_at")
        if evidence_lane == "live_forward" and event_recorded_at > decided_at:
            raise ValueError("decision snapshot contains a post-decision live forecast")
        origin_ref = event.get("origin_artifact_ref") if isinstance(event.get("origin_artifact_ref"), dict) else {}
        if origin_ref.get("binding_status") != "verified":
            raise ValueError("decision snapshot forecast origin is not verified")
        _verify_path_hash(root, origin_ref, DECISION_ARTIFACT_ROOTS, "forecast origin artifact")

    strategy_ref = snapshot.get("strategy_ref") if isinstance(snapshot.get("strategy_ref"), dict) else {}
    if strategy_ref.get("applied"):
        _verify_path_hash(
            root,
            {"path": strategy_ref.get("snapshot_path"), "sha256": strategy_ref.get("content_hash")},
            (Path(".tradingcodex/mainagent/workflows"),),
            "strategy run snapshot",
        )
    context_ref = snapshot.get("investor_context_ref") if isinstance(snapshot.get("investor_context_ref"), dict) else {}
    if context_ref.get("applied"):
        _verify_path_hash(
            root,
            {"path": context_ref.get("snapshot_path"), "sha256": context_ref.get("snapshot_sha256")},
            (Path(".tradingcodex/mainagent/workflows"),),
            "investor context run snapshot",
        )


def _verify_path_hash(
    root: Path,
    ref: dict[str, Any],
    allowed_roots: tuple[Path, ...],
    label: str,
) -> Path:
    raw_path = str(ref.get("path") or "")
    path = safe_workspace_path(root, raw_path, allowed_roots=allowed_roots)
    digest = file_hash(path)
    if not digest or digest != str(ref.get("sha256") or ""):
        raise ValueError(f"{label} path/hash mismatch")
    return path


def _read_decision_snapshot(path: Path) -> dict[str, Any]:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid decision snapshot: {path.stem}") from exc
    if not isinstance(snapshot, dict):
        raise ValueError(f"decision snapshot must be an object: {path.stem}")
    expected = str(snapshot.get("snapshot_hash") or "")
    payload = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if not expected or stable_hash(payload) != expected:
        raise ValueError(f"decision snapshot hash mismatch: {path.stem}")
    return snapshot


def _required_text(args: dict[str, Any], field: str) -> str:
    value = str(args.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _iso(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_metadata(run_id: str, decision_id: str, prompt: str, plan: dict[str, Any], package_rel: Path) -> dict[str, Any]:
    summary = plan["intake_summary"]
    non_investment = plan["lane"] in NON_INVESTMENT_WORKFLOW_LANES
    missing_evidence = ["validated workflow output"] if non_investment else ["accepted role artifacts"]
    source_as_of = "pending workflow output" if non_investment else "pending accepted artifacts"
    source_trust_notes = ["pending validated workflow output"] if non_investment else ["pending accepted role artifacts"]
    return {
        "schema_version": 1,
        "run_id": run_id,
        "decision_id": decision_id,
        "status": "planned",
        "handoff_state": "waiting",
        "readiness_label": "waiting",
        "original_prompt": prompt,
        "interpreted_question": (summary.get("idea_translation") or {}).get("plain_english") or summary.get("primary_question") or "",
        "workflow_lane": plan["lane"],
        "workflow_label": summary.get("label") or plan["lane"],
        "universe": plan["universe"],
        "selected_roles": plan["selected_roles"],
        "missing_profile": plan["missing_profile"],
        "missing_evidence": missing_evidence,
        "artifact_paths": [],
        "source_as_of": source_as_of,
        "source_trust_notes": source_trust_notes,
        "contrary_evidence": ["pending validated workflow output"] if non_investment else ["pending accepted role artifacts"],
        "update_triggers": ["new user request changes workflow scope"] if non_investment else ["accepted role artifacts identify new material evidence"],
        "invalidation_conditions": ["workflow gate blocks requested change"] if non_investment else ["accepted role artifacts identify invalidating evidence"],
        "thesis_lifecycle": {} if non_investment else {
            "state": "exploring",
            "key_forecastable_claims": ["pending accepted role artifacts"],
            "review_date": "pending accepted artifacts",
            "what_would_change_our_mind": ["accepted role artifacts identify invalidating evidence"],
            "strongest_contrary_evidence": ["pending accepted role artifacts"],
            "owner_role": "head-manager",
            "required_follow_up": ["dispatch selected roles and review accepted artifacts"],
            "postmortem_requirement": "required after thesis change, rejected order, execution, or process failure",
        },
        "workflow_lifecycle": {
            "key_deliverables": ["pending validated workflow output"],
            "completion_condition": "workflow output accepted or blocked",
            "what_would_change_scope": ["new user request changes lane or blocked actions"],
            "owner_role": "head-manager",
            "required_follow_up": ["run the selected head-manager workflow"],
            "postmortem_requirement": "required after connector, strategy, policy, or process failure",
        } if non_investment else {},
        "blocked_actions": plan["blocked_actions"],
        "routing_flags": plan.get("routing_flags") or {},
        "allowed_next_actions": plan["allowed_next_actions"],
        "order_gate_status": "blocked" if any(action in plan["blocked_actions"] for action in ("order ticket", "approval", "execution")) else "waiting",
        "decision_package_path": package_rel.as_posix(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace_context": plan["workspace_context"],
    }


def _decision_markdown(metadata: dict[str, Any], plan: dict[str, Any]) -> str:
    frontmatter = {
        "artifact_id": metadata["decision_id"],
        "decision_id": metadata["decision_id"],
        "workflow_run_id": metadata["run_id"],
        "artifact_type": "decision_package",
        "role": "head-manager",
        "title": f"Decision Package: {metadata['decision_id']}",
        "workflow_lane": metadata["workflow_lane"],
        "workflow_label": metadata["workflow_label"],
        "universe": metadata["universe"],
        "status": metadata["status"],
        "handoff_state": metadata["handoff_state"],
        "readiness_label": metadata["readiness_label"],
        "source_as_of": metadata["source_as_of"],
        "context_summary": metadata["interpreted_question"],
        "reader_summary": f"{metadata['workflow_label']} package is waiting for workflow output.",
        "next_action": (metadata["allowed_next_actions"][0]["detail"] if metadata["allowed_next_actions"] else "Run or record the selected workflow."),
        "confidence": "low",
        "next_recipient": "head-manager",
        "created_by": "head-manager",
        "blocked_actions": metadata["blocked_actions"],
        "missing_evidence": metadata["missing_evidence"],
        "source_snapshot_ids": ["not-applicable-planned-package"],
        "source_trust_notes": metadata["source_trust_notes"],
        "contrary_evidence": metadata["contrary_evidence"],
        "update_triggers": metadata["update_triggers"],
        "invalidation_conditions": metadata["invalidation_conditions"],
        "decision_quality_required": bool(metadata.get("routing_flags", {}).get("decision_quality_required")),
        "forecast_contract_required": bool(metadata.get("routing_flags", {}).get("forecast_contract_required")),
        "anti_overfit_required": bool(metadata.get("routing_flags", {}).get("anti_overfit_required")),
    }
    if metadata["thesis_lifecycle"]:
        frontmatter["thesis_lifecycle"] = metadata["thesis_lifecycle"]
    if metadata.get("workflow_lifecycle"):
        frontmatter["workflow_lifecycle"] = metadata["workflow_lifecycle"]
    next_actions = "\n".join(f"- {item['label']}: {item['detail']}" for item in metadata["allowed_next_actions"]) or "- None yet."
    roles = ", ".join(metadata["selected_roles"]) or "head-manager"
    investor_context = "\n".join(f"- {item}" for item in metadata["missing_profile"]) or "- No required investor-context gaps for this lane."
    stages = "\n".join(f"- {stage['label']}: {stage['summary']}" for stage in plan["intake_summary"].get("workflow_stages") or [])
    artifact_waiting = "waiting for workflow artifacts" if metadata.get("workflow_lifecycle") else "waiting for accepted role artifacts"
    lifecycle_section = _lifecycle_markdown(metadata)
    boundary_section = _boundary_markdown(metadata)
    body = f"""# Decision Package: {metadata['decision_id']}

## Overview

- [factual] This package records a planned TradingCodex workflow before accepted outputs exist.
- Original prompt: {metadata['original_prompt']}
- Interpreted question: {metadata['interpreted_question']}
- Workflow lane: {metadata['workflow_lane']}
- Workflow label: {metadata['workflow_label']}
- Universe: {metadata['universe']}
- Selected roles: {roles}
- Handoff state: {metadata['handoff_state']}
- Readiness label: {metadata['readiness_label']}

## Evidence

- Source/as-of posture: {metadata['source_as_of']}
- Artifact paths: {artifact_waiting}
- Missing evidence: {', '.join(metadata['missing_evidence'])}
- Source trust notes: {', '.join(metadata['source_trust_notes'])}
- [assumption] Pending fields must be replaced by accepted workflow artifacts before downstream use.

{lifecycle_section}

## Investor Context Gaps

{investor_context}

{boundary_section}

## Next Allowed Actions

{next_actions}

## Workflow Stages

{stages}

## Codex Starter Prompt

```text
{plan['starter_prompt']}
```
"""
    header = "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items()) + "\n---\n\n"
    return header + body.rstrip() + "\n"


def _lifecycle_markdown(metadata: dict[str, Any]) -> str:
    if metadata.get("workflow_lifecycle"):
        lifecycle = metadata["workflow_lifecycle"]
        return f"""## Workflow Lifecycle

- Key deliverables: {', '.join(lifecycle['key_deliverables'])}
- Completion condition: {lifecycle['completion_condition']}
- What would change scope: {', '.join(lifecycle['what_would_change_scope'])}
- Owner role: {lifecycle['owner_role']}
- Required follow-up: {', '.join(lifecycle['required_follow_up'])}
- Postmortem requirement: {lifecycle['postmortem_requirement']}"""
    lifecycle = metadata["thesis_lifecycle"]
    return f"""## Thesis Lifecycle

- State: {lifecycle['state']}
- Key forecastable claims: {', '.join(lifecycle['key_forecastable_claims'])}
- Review date: {lifecycle['review_date']}
- What would change our mind: {', '.join(lifecycle['what_would_change_our_mind'])}
- Strongest contrary evidence: {', '.join(lifecycle['strongest_contrary_evidence'])}
- Owner role: {lifecycle['owner_role']}
- Required follow-up: {', '.join(lifecycle['required_follow_up'])}
- Postmortem requirement: {lifecycle['postmortem_requirement']}"""


def _boundary_markdown(metadata: dict[str, Any]) -> str:
    blocked = ", ".join(metadata["blocked_actions"]) or "none"
    if metadata.get("workflow_lifecycle"):
        return f"""## Boundaries

- Workflow boundary: head-manager lane; no fixed-role investment subagent dispatch.
- Order gate status: {metadata['order_gate_status']}
- Blocked actions: {blocked}"""
    return f"""## Portfolio And Risk

- Portfolio/risk status: waiting for selected Codex role artifacts.
- Order gate status: {metadata['order_gate_status']}
- Blocked actions: {blocked}"""


def _decision_suffix(prompt: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    return sanitize_id(f"{stamp}-{digest}")


def _store_workflow_run(root: Path, metadata: dict[str, Any]) -> None:
    try:
        ensure_runtime_database(root)
        from apps.workflows.models import WorkflowRun

        WorkflowRun.objects.update_or_create(
            run_id=metadata["run_id"],
            defaults={
                "lane": metadata["workflow_lane"],
                "universe": metadata["universe"],
                "readiness_label": metadata["readiness_label"],
                "status": metadata["status"],
                "original_request": metadata["original_prompt"],
                "workspace_context": metadata["workspace_context"],
            },
        )
    except Exception:
        pass


def _decision_payload(root: Path, path: Path, *, include_markdown: bool = False) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    document = split_markdown_frontmatter(text)
    frontmatter = document.frontmatter
    payload = {
        "decision_id": str(frontmatter.get("decision_id") or path.stem),
        "workflow_run_id": str(frontmatter.get("workflow_run_id") or ""),
        "path": rel,
        "title": document.heading or path.stem,
        "workflow_lane": str(frontmatter.get("workflow_lane") or ""),
        "workflow_label": str(frontmatter.get("workflow_label") or frontmatter.get("workflow_lane") or ""),
        "universe": str(frontmatter.get("universe") or ""),
        "status": str(frontmatter.get("status") or ""),
        "handoff_state": str(frontmatter.get("handoff_state") or ""),
        "readiness_label": str(frontmatter.get("readiness_label") or ""),
        "blocked_actions": frontmatter.get("blocked_actions") if isinstance(frontmatter.get("blocked_actions"), list) else [],
        "missing_evidence": frontmatter.get("missing_evidence") if isinstance(frontmatter.get("missing_evidence"), list) else [],
        "source_trust_notes": frontmatter.get("source_trust_notes") if isinstance(frontmatter.get("source_trust_notes"), list) else [],
        "thesis_lifecycle": frontmatter.get("thesis_lifecycle") if isinstance(frontmatter.get("thesis_lifecycle"), dict) else {},
        "workflow_lifecycle": frontmatter.get("workflow_lifecycle") if isinstance(frontmatter.get("workflow_lifecycle"), dict) else {},
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        "workspace_native": True,
    }
    if include_markdown:
        payload["markdown"] = document.body
        payload["frontmatter"] = frontmatter
    return payload
