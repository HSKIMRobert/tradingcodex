from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.application.analysis_runs import ANALYSIS_RUNS_ROOT, analysis_run_relpath, read_analysis_run
from tradingcodex_service.application.artifact_bindings import verify_authenticated_artifact_binding
from tradingcodex_service.application.common import atomic_write_text, exclusive_file_lock, file_hash, now_iso, safe_workspace_path, sanitize_id, stable_hash
from tradingcodex_service.application.forecasting import get_forecast, is_forecast_event_anchored
from tradingcodex_service.application.markdown_preview import split_markdown_frontmatter
from tradingcodex_service.application.research import find_workspace_research_artifact
from tradingcodex_service.application.research_specs import EVIDENCE_LANES
from tradingcodex_service.application.runtime import workspace_context_payload

DECISION_ROOT = Path("trading/decisions")
DECISION_SNAPSHOT_SCHEMA_VERSION = 1
DECISION_ARTIFACT_ROOTS = (Path("trading/research"), Path("trading/reports"), DECISION_ROOT)


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
    run_ref, strategy_ref, brain_ref, context_ref = _recorded_run_binding(
        root,
        workflow_run_id,
        args,
        evidence_lane=evidence_lane,
        decided_at=decided_at,
    )
    _require_decision_artifact_run_lineage(decision_artifact_ref, strategy_ref, brain_ref, context_ref)
    _validate_decision_artifact_time(decision_artifact_ref, evidence_lane, knowledge_cutoff, decided_at)
    if args.get("plan_hash"):
        raise ValueError("decision snapshots do not accept a Django workflow plan_hash")
    seed = {
        "analysis_run_hash": run_ref["record_hash"],
        "workflow_run_id": workflow_run_id,
        "decision_artifact_sha256": decision_artifact_ref["sha256"],
        "forecast_event_hashes": [ref["event_hash"] for ref in forecast_refs],
        "decided_at": decided_at,
    }
    decision_id = sanitize_id(args.get("decision_id") or f"decision-snapshot-{stable_hash(seed)[:16]}")
    snapshot = {
        "schema_version": DECISION_SNAPSHOT_SCHEMA_VERSION,
        "artifact_type": "decision_snapshot",
        "decision_id": decision_id,
        "workflow_run_id": workflow_run_id,
        "evidence_lane": evidence_lane,
        "regime": str(args.get("regime") or "unclassified"),
        "knowledge_cutoff": knowledge_cutoff,
        "decided_at": decided_at,
        "created_at": recorded_at,
        "recorded_at": recorded_at,
        "created_by": created_by,
        "analysis_run_ref": run_ref,
        "decision_artifact_ref": decision_artifact_ref,
        "forecast_refs": forecast_refs,
        "forecast_block_reason": forecast_block_reason,
        "strategy_ref": strategy_ref,
        "investment_brain_ref": brain_ref,
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
    _verify_decision_snapshot_refs(root, snapshot)
    return {
        "status": "ok",
        "decision_snapshot": snapshot,
        "verification_status": "verified",
        "export_path": path.relative_to(root).as_posix(),
        "workspace_native": True,
        "authority": "evidence_only",
        "workspace_context": workspace_context_payload(root),
    }


def verify_decision_snapshot(workspace_root: Path | str, decision_id: str) -> dict[str, Any]:
    return get_decision_snapshot(workspace_root, decision_id)


def list_decision_snapshots(workspace_root: Path | str, limit: int = 50) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    items = []
    for path in sorted((root / DECISION_ROOT).glob("*.decision-snapshot.json")):
        snapshot = _read_decision_snapshot(path)
        _verify_decision_snapshot_refs(root, snapshot)
        items.append({
            "decision_id": snapshot.get("decision_id", ""),
            "workflow_run_id": snapshot.get("workflow_run_id", ""),
            "evidence_lane": snapshot.get("evidence_lane", ""),
            "decided_at": snapshot.get("decided_at", ""),
            "strategy_name": (snapshot.get("strategy_ref") or {}).get("name", "no_strategy"),
            "investment_brain_id": (snapshot.get("investment_brain_ref") or {}).get("brain_id", "") or "baseline",
            "snapshot_hash": snapshot.get("snapshot_hash", ""),
            "path": path.relative_to(root).as_posix(),
            "verification_status": "verified",
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
        if decision_id == payload["decision_id"]:
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
        artifact_id = str(frontmatter.get("artifact_id") or "").strip()
        if not artifact_id:
            raise ValueError("decision artifact frontmatter requires artifact_id")
        artifact = find_workspace_research_artifact(root, artifact_id)
        if (
            not artifact
            or str(artifact.get("path") or "") != path.relative_to(root).as_posix()
            or str(artifact.get("content_hash") or "") != body_hash
        ):
            raise ValueError("decision artifact does not match the indexed research artifact")
        authentication = verify_authenticated_artifact_binding(root, artifact)
        if file_hash(path) != ref["sha256"]:
            raise ValueError("decision artifact changed during authentication")
        ref.update({
            "artifact_id": artifact_id,
            "artifact_type": str(frontmatter.get("artifact_type") or ""),
            "content_hash": body_hash,
            "knowledge_cutoff": str(frontmatter.get("knowledge_cutoff") or ""),
            "evidence_lane": str(frontmatter.get("evidence_lane") or ""),
            "recorded_at": str(frontmatter.get("recorded_at") or ""),
            "strategy_name": str(frontmatter.get("strategy_name") or ""),
            "strategy_hash": str(frontmatter.get("strategy_hash") or ""),
            "investment_brain_id": str(frontmatter.get("investment_brain_id") or ""),
            "investment_brain_version": str(frontmatter.get("investment_brain_version") or ""),
            "investment_brain_content_digest": str(frontmatter.get("investment_brain_content_digest") or ""),
            "investor_context_applied": bool(frontmatter.get("investor_context_applied")),
            "investor_context_hash": str(frontmatter.get("investor_context_hash") or ""),
            "authentication": authentication,
        })
    else:
        raise ValueError("decision snapshots require an authenticated Markdown research artifact")
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
            raise ValueError(f"forecast event is not chain-anchored: {forecast_id}")
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


def _recorded_run_binding(
    root: Path,
    workflow_run_id: str,
    args: dict[str, Any],
    *,
    evidence_lane: str,
    decided_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    run = read_analysis_run(root, workflow_run_id)
    if not run or str(run.get("workflow_run_id") or "") != workflow_run_id:
        raise ValueError("recorded analysis run is required for a decision snapshot")
    path = safe_workspace_path(
        root,
        analysis_run_relpath(workflow_run_id),
        allowed_roots=(ANALYSIS_RUNS_ROOT,),
    )
    run_ref = {
        "workflow_run_id": workflow_run_id,
        "path": path.relative_to(root).as_posix(),
        "sha256": file_hash(path),
        "record_hash": str(run.get("record_hash") or ""),
        "recorded_at": str(run.get("created_at") or ""),
    }
    if evidence_lane == "live_forward" and _iso(run_ref["recorded_at"], "analysis run recorded_at") > decided_at:
        raise ValueError("live_forward analysis run was stored after decided_at")
    strategy_ref = _frozen_strategy_ref(root, run.get("strategy_binding"), args)
    brain_ref = _frozen_investment_brain_ref(run.get("investment_brain_binding"), args)
    context_ref = _frozen_context_ref(root, run.get("investor_context_binding"), args)
    return run_ref, strategy_ref, brain_ref, context_ref


def _frozen_strategy_ref(root: Path, raw: Any, args: dict[str, Any]) -> dict[str, Any]:
    binding = raw if isinstance(raw, dict) else {}
    strategy_id = str(binding.get("strategy_id") or "")
    requested = str(args.get("strategy_name") or "").strip()
    if requested and requested != (strategy_id or "no_strategy"):
        raise ValueError("strategy_name does not match the recorded analysis run")
    if not strategy_id:
        return {"name": "no_strategy", "applied": False}
    snapshot_path = str(binding.get("snapshot_path") or "")
    content_hash = str(binding.get("content_hash") or "")
    if not snapshot_path or not content_hash:
        raise ValueError("recorded strategy binding lacks an immutable run snapshot")
    path = safe_workspace_path(root, snapshot_path, allowed_roots=(ANALYSIS_RUNS_ROOT,))
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


def _frozen_investment_brain_ref(raw: Any, args: dict[str, Any]) -> dict[str, Any]:
    binding = raw if isinstance(raw, dict) else {}
    brain_id = str(binding.get("brain_id") or "")
    requested_id = str(args.get("investment_brain_id") or "").strip()
    requested_version = str(args.get("investment_brain_version") or "").strip()
    requested_digest = str(args.get("investment_brain_content_digest") or "").strip()
    if requested_id and requested_id != brain_id:
        raise ValueError("investment_brain_id does not match the recorded analysis run")
    if requested_version and requested_version != str(binding.get("version") or ""):
        raise ValueError("investment_brain_version does not match the recorded analysis run")
    if requested_digest and requested_digest != str(binding.get("content_digest") or ""):
        raise ValueError("investment_brain_content_digest does not match the recorded analysis run")
    if not brain_id:
        if any(
            binding.get(field)
            for field in (
                "version",
                "content_digest",
                "skill_digest",
                "manifest_path",
                "source_file",
                "projected_skill_path",
            )
        ):
            raise ValueError("baseline analysis run contains partial Investment Brain provenance")
        return {"brain_id": "", "applied": False}
    version = str(binding.get("version") or "")
    content_digest = str(binding.get("content_digest") or "")
    skill_digest = str(binding.get("skill_digest") or "")
    source = binding.get("source") if isinstance(binding.get("source"), dict) else {}
    declared = source.get("declared") if isinstance(source.get("declared"), dict) else {}
    if (
        not version
        or not re.fullmatch(r"[0-9a-f]{64}", content_digest)
        or not re.fullmatch(r"[0-9a-f]{64}", skill_digest)
        or not str(binding.get("source_file") or "")
    ):
        raise ValueError("recorded Investment Brain binding is incomplete")
    return {
        "brain_id": brain_id,
        "applied": True,
        "version": version,
        "content_digest": content_digest,
        "source": {
            "kind": str(source.get("kind") or ""),
            "location": str(source.get("location") or ""),
            "ref": str(source.get("ref") or ""),
            "resolved_revision": str(source.get("resolved_revision") or ""),
            "declared": {
                "publisher": str(declared.get("publisher") or ""),
                "repository": str(declared.get("repository") or ""),
                "license": str(declared.get("license") or ""),
            },
        },
        "manifest_path": str(binding.get("manifest_path") or ""),
        "source_file": str(binding.get("source_file") or ""),
        "projected_skill_path": str(binding.get("projected_skill_path") or ""),
    }


def _require_decision_artifact_run_lineage(
    artifact_ref: dict[str, Any],
    strategy_ref: dict[str, Any],
    brain_ref: dict[str, Any],
    context_ref: dict[str, Any],
) -> None:
    expected = {
        "strategy_name": str(strategy_ref.get("name") or "") if strategy_ref.get("applied") else "",
        "strategy_hash": str(strategy_ref.get("content_hash") or "") if strategy_ref.get("applied") else "",
        "investment_brain_id": str(brain_ref.get("brain_id") or "") if brain_ref.get("applied") else "",
        "investment_brain_version": str(brain_ref.get("version") or "") if brain_ref.get("applied") else "",
        "investment_brain_content_digest": str(brain_ref.get("content_digest") or "") if brain_ref.get("applied") else "",
        "investor_context_applied": bool(context_ref.get("applied")),
        "investor_context_hash": str(context_ref.get("content_hash") or "") if context_ref.get("applied") else "",
    }
    if any(artifact_ref.get(field) != value for field, value in expected.items()):
        raise ValueError("decision artifact lineage does not match the recorded analysis run")


def _frozen_context_ref(root: Path, raw: Any, args: dict[str, Any]) -> dict[str, Any]:
    binding = dict(raw) if isinstance(raw, dict) else {}
    applied = bool(binding.get("applied"))
    if "investor_context_applied" in args and bool(args.get("investor_context_applied")) != applied:
        raise ValueError("investor_context_applied does not match the recorded analysis run")
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
    path = safe_workspace_path(root, result["snapshot_path"], allowed_roots=(ANALYSIS_RUNS_ROOT,))
    if not path.exists() or not path.is_file():
        raise ValueError("recorded investor context snapshot is missing")
    digest = file_hash(path) or ""
    if result["source"] != "workspace_file" or digest != result["content_hash"]:
        raise ValueError("recorded investor context snapshot hash mismatch")
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
    if snapshot.get("schema_version") != DECISION_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported decision snapshot schema")
    workflow_run_id = str(snapshot.get("workflow_run_id") or "")
    evidence_lane = str(snapshot.get("evidence_lane") or "")
    knowledge_cutoff = _iso(snapshot.get("knowledge_cutoff"), "decision snapshot knowledge_cutoff")
    decided_at = _iso(snapshot.get("decided_at"), "decision snapshot decided_at")
    recorded_at = _iso(snapshot.get("recorded_at"), "decision snapshot recorded_at")
    if knowledge_cutoff > decided_at or decided_at > recorded_at:
        raise ValueError("decision snapshot time ordering is invalid")

    run_ref = snapshot.get("analysis_run_ref") if isinstance(snapshot.get("analysis_run_ref"), dict) else {}
    run_path = _verify_path_hash(root, run_ref, (ANALYSIS_RUNS_ROOT,), "analysis run")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if (
        str(run.get("workflow_run_id") or "") != workflow_run_id
        or str(run.get("record_hash") or "") != run_ref.get("record_hash")
        or stable_hash({key: value for key, value in run.items() if key != "record_hash"}) != run_ref.get("record_hash")
        or str(run.get("created_at") or "") != run_ref.get("recorded_at")
    ):
        raise ValueError("decision snapshot analysis run binding mismatch")

    expected_strategy_ref = _frozen_strategy_ref(root, run.get("strategy_binding"), {})
    expected_brain_ref = _frozen_investment_brain_ref(run.get("investment_brain_binding"), {})
    expected_context_ref = _frozen_context_ref(root, run.get("investor_context_binding"), {})
    if snapshot.get("strategy_ref") != expected_strategy_ref:
        raise ValueError("decision snapshot strategy binding mismatch")
    if snapshot.get("investment_brain_ref") != expected_brain_ref:
        raise ValueError("decision snapshot Investment Brain binding mismatch")
    if snapshot.get("investor_context_ref") != expected_context_ref:
        raise ValueError("decision snapshot investor context binding mismatch")

    artifact_ref = snapshot.get("decision_artifact_ref") if isinstance(snapshot.get("decision_artifact_ref"), dict) else {}
    artifact_path = _verify_path_hash(root, artifact_ref, DECISION_ARTIFACT_ROOTS, "decision artifact")
    document = split_markdown_frontmatter(artifact_path.read_text(encoding="utf-8"))
    body_hash = hashlib.sha256(document.body.encode("utf-8")).hexdigest()
    if (
        body_hash != artifact_ref.get("content_hash")
        or document.frontmatter.get("handoff_state") != "accepted"
        or str(document.frontmatter.get("workflow_run_id") or "") != workflow_run_id
        or str(document.frontmatter.get("recorded_at") or "") != artifact_ref.get("recorded_at")
        or str(document.frontmatter.get("knowledge_cutoff") or "") != artifact_ref.get("knowledge_cutoff")
    ):
        raise ValueError("decision snapshot accepted artifact binding mismatch")
    indexed_artifact = find_workspace_research_artifact(
        root,
        str(artifact_ref.get("artifact_id") or ""),
    )
    if (
        not indexed_artifact
        or str(indexed_artifact.get("path") or "") != artifact_path.relative_to(root).as_posix()
        or str(indexed_artifact.get("content_hash") or "") != body_hash
    ):
        raise ValueError("decision snapshot research artifact binding is unavailable")
    authentication = verify_authenticated_artifact_binding(root, indexed_artifact)
    if file_hash(artifact_path) != artifact_ref.get("sha256"):
        raise ValueError("decision snapshot artifact changed during authentication")
    if artifact_ref.get("authentication") != authentication:
        raise ValueError("decision snapshot artifact authentication mismatch")
    _require_decision_artifact_run_lineage(
        {
            "artifact_type": str(document.frontmatter.get("artifact_type") or ""),
            "strategy_name": str(document.frontmatter.get("strategy_name") or ""),
            "strategy_hash": str(document.frontmatter.get("strategy_hash") or ""),
            "investment_brain_id": str(document.frontmatter.get("investment_brain_id") or ""),
            "investment_brain_version": str(document.frontmatter.get("investment_brain_version") or ""),
            "investment_brain_content_digest": str(document.frontmatter.get("investment_brain_content_digest") or ""),
            "investor_context_applied": bool(document.frontmatter.get("investor_context_applied")),
            "investor_context_hash": str(document.frontmatter.get("investor_context_hash") or ""),
        },
        expected_strategy_ref,
        expected_brain_ref,
        expected_context_ref,
    )
    _validate_decision_artifact_time(artifact_ref, evidence_lane, knowledge_cutoff, decided_at)
    if evidence_lane == "live_forward" and _iso(run_ref.get("recorded_at"), "analysis run recorded_at") > decided_at:
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
            (ANALYSIS_RUNS_ROOT,),
            "strategy run snapshot",
        )
    context_ref = snapshot.get("investor_context_ref") if isinstance(snapshot.get("investor_context_ref"), dict) else {}
    if context_ref.get("applied"):
        _verify_path_hash(
            root,
            {"path": context_ref.get("snapshot_path"), "sha256": context_ref.get("snapshot_sha256")},
            (ANALYSIS_RUNS_ROOT,),
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
    if snapshot.get("schema_version") != DECISION_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"unsupported decision snapshot schema: {path.stem}")
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
        "universe": str(frontmatter.get("universe") or ""),
        "status": str(frontmatter.get("status") or ""),
        "handoff_state": str(frontmatter.get("handoff_state") or ""),
        "readiness_label": str(frontmatter.get("readiness_label") or ""),
        "blocked_actions": frontmatter.get("blocked_actions") if isinstance(frontmatter.get("blocked_actions"), list) else [],
        "missing_evidence": frontmatter.get("missing_evidence") if isinstance(frontmatter.get("missing_evidence"), list) else [],
        "source_trust_notes": frontmatter.get("source_trust_notes") if isinstance(frontmatter.get("source_trust_notes"), list) else [],
        "thesis_lifecycle": frontmatter.get("thesis_lifecycle") if isinstance(frontmatter.get("thesis_lifecycle"), dict) else {},
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        "workspace_native": True,
    }
    if include_markdown:
        payload["markdown"] = document.body
        payload["frontmatter"] = frontmatter
    return payload
