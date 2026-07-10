from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import atomic_write_text, exclusive_file_lock, file_hash, now_iso, safe_workspace_path, sanitize_id, stable_hash
from tradingcodex_service.application.markdown_preview import split_markdown_frontmatter
from tradingcodex_service.application.runtime import workspace_context_payload

RESEARCH_FILE_ROOTS = (Path("trading/research"), Path("trading/reports"))
SOURCE_SNAPSHOT_ROOT = Path("trading/research/source-snapshots")
SOURCE_SNAPSHOT_ROOTS = (SOURCE_SNAPSHOT_ROOT,)
RESEARCH_INDEX_PATH = Path("trading/research/.index/research-index.json")
RESEARCH_INDEX_VERSION = 1
WORKFLOW_ARTIFACT_ROOTS = RESEARCH_FILE_ROOTS + (Path("trading/decisions"), Path("trading/orders"), Path("trading/approvals"))
ANTI_OVERFIT_CHECK_KEYS = (
    "leakage",
    "survivorship_bias",
    "data_snooping",
    "out_of_sample",
    "walk_forward_consistency",
    "monte_carlo_permutation",
    "bootstrap_sharpe_ci",
    "cost_assumptions",
    "capacity",
    "live_friction",
)


def list_workflow_artifacts(workspace_root: Path | str) -> dict[str, Any]:
    root = Path(workspace_root)
    files = []
    for prefix in ["trading/research", "trading/reports", "trading/decisions", "trading/orders", "trading/approvals"]:
        base = root / prefix
        if base.exists():
            files.extend(
                str(path.relative_to(root))
                for path in base.rglob("*")
                if path.is_file() and path.name != ".gitkeep" and ".index" not in path.parts and ".versions" not in path.parts
            )
    return {
        "artifacts": sorted(files),
        "research_artifacts": list_research_artifacts(root, {"include_markdown": False}).get("artifacts", []),
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }


def create_research_artifact(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    markdown = args.get("markdown")
    markdown_path = args.get("markdown_path") or args.get("markdown_file")
    if not markdown and markdown_path:
        markdown = safe_workspace_path(root, markdown_path, allowed_roots=RESEARCH_FILE_ROOTS).read_text(encoding="utf-8")
    if not markdown:
        raise ValueError("research artifact markdown is required")

    source_document = split_markdown_frontmatter(str(markdown))
    source_frontmatter = source_document.frontmatter
    markdown_body = source_document.body or str(markdown)
    artifact_type = str(args.get("artifact_type") or args.get("type") or source_frontmatter.get("artifact_type") or source_frontmatter.get("type") or "research_memo")
    title = str(args.get("title") or source_frontmatter.get("title") or source_document.heading or args.get("artifact_id") or "Untitled research artifact")
    symbol = str(args.get("symbol") or source_frontmatter.get("symbol") or "").upper()
    content_hash = hashlib.sha256(markdown_body.encode("utf-8")).hexdigest()
    artifact_id = str(args.get("artifact_id") or source_frontmatter.get("artifact_id") or f"{sanitize_id(artifact_type)}-{sanitize_id(symbol or title)}-{content_hash[:12]}")
    metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else {}
    if args.get("role") and not metadata.get("role"):
        metadata = {**metadata, "role": args.get("role")}
    created_by = str(args.get("created_by") or args.get("principal_id") or source_frontmatter.get("created_by") or "system")
    existing = find_workspace_research_artifact(root, artifact_id)
    export_path = str(args.get("export_path") or (existing.get("path") if existing else "") or default_research_export_path_from_values(artifact_id, artifact_type, metadata))
    frontmatter = {
        **source_frontmatter,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "universe": args.get("universe") or source_frontmatter.get("universe") or "public_equity",
        "workflow_type": args.get("workflow_type") or source_frontmatter.get("workflow_type") or "",
        "role": args.get("role") or metadata.get("role") or source_frontmatter.get("role") or _role_alias_from_actor(created_by),
        "symbol": symbol,
        "title": title,
        "source_as_of": args.get("source_as_of") or source_frontmatter.get("source_as_of") or "",
        "readiness_label": args.get("readiness_label") or source_frontmatter.get("readiness_label") or "",
        "context_summary": _frontmatter_value(args, metadata, source_frontmatter, "context_summary", ""),
        "reader_summary": _frontmatter_value(args, metadata, source_frontmatter, "reader_summary", ""),
        "handoff_state": _frontmatter_value(args, metadata, source_frontmatter, "handoff_state", ""),
        "confidence": _frontmatter_value(args, metadata, source_frontmatter, "confidence", ""),
        "missing_evidence": _frontmatter_list(args, metadata, source_frontmatter, "missing_evidence"),
        "next_recipient": _frontmatter_value(args, metadata, source_frontmatter, "next_recipient", ""),
        "next_action": _frontmatter_value(args, metadata, source_frontmatter, "next_action", ""),
        "blocked_actions": _frontmatter_list(args, metadata, source_frontmatter, "blocked_actions"),
        "source_snapshot_ids": _frontmatter_list(args, metadata, source_frontmatter, "source_snapshot_ids"),
        "workflow_run_id": _frontmatter_value(args, metadata, source_frontmatter, "workflow_run_id", ""),
        "plan_hash": _frontmatter_value(args, metadata, source_frontmatter, "plan_hash", ""),
        "stage_id": _frontmatter_value(args, metadata, source_frontmatter, "stage_id", ""),
        "task_id": _frontmatter_value(args, metadata, source_frontmatter, "task_id", ""),
        "producer_role": _frontmatter_value(args, metadata, source_frontmatter, "producer_role", args.get("role") or metadata.get("role") or ""),
        "artifact_schema_version": _int_value(_frontmatter_value(args, metadata, source_frontmatter, "artifact_schema_version", 1), default=1),
        "input_artifact_hashes": _frontmatter_value(args, metadata, source_frontmatter, "input_artifact_hashes", {}),
        "knowledge_cutoff": _frontmatter_value(args, metadata, source_frontmatter, "knowledge_cutoff", args.get("source_as_of") or source_frontmatter.get("source_as_of") or ""),
        "follow_up_requests": _frontmatter_list(args, metadata, source_frontmatter, "follow_up_requests"),
        "improvements": _frontmatter_list(args, metadata, source_frontmatter, "improvements"),
        "version": 1,
        "content_hash": content_hash,
        "workspace_native": True,
        "created_by": created_by,
    }
    path = safe_workspace_path(root, export_path, allowed_roots=RESEARCH_FILE_ROOTS)
    lock_path = root / RESEARCH_FILE_ROOTS[0] / ".research-artifacts"
    with exclusive_file_lock(lock_path):
        current = find_workspace_research_artifact(root, artifact_id)
        expected_hash = str(args.get("expected_content_hash") or "")
        if expected_hash and (not current or current.get("content_hash") != expected_hash):
            raise ValueError("research artifact compare-and-swap failed: content hash changed")
        if current and current.get("content_hash") != content_hash and not args.get("_append_version"):
            raise ValueError("research artifact already exists in this workspace; use append_research_artifact_version to create a new version")
        current_version = _int_value(current.get("version") if current else None, default=0)
        version = current_version + 1 if args.get("_append_version") else current_version or 1
        frontmatter["version"] = version
        _validate_source_snapshot_links(root, frontmatter["source_snapshot_ids"], str(frontmatter.get("knowledge_cutoff") or ""))
        if current and args.get("_append_version"):
            current_path = safe_workspace_path(root, current["path"], allowed_roots=RESEARCH_FILE_ROOTS)
            archive = safe_workspace_path(
                root,
                Path("trading/research/.versions") / sanitize_id(artifact_id) / f"v{current_version}-{str(current.get('content_hash') or '')[:12]}.md",
                allowed_roots=(Path("trading/research"),),
            )
            if not archive.exists():
                atomic_write_text(archive, current_path.read_text(encoding="utf-8"))
        atomic_write_text(path, _render_research_markdown(frontmatter, markdown_body))

    result = {
        "status": "updated" if current else "stored",
        "db_canonical": False,
        "file_sot": True,
        "workspace_native": True,
        "artifact_id": artifact_id,
        "version": version,
        "content_hash": content_hash,
        "export_path": path.relative_to(root).as_posix(),
        "workspace_context": workspace_context_payload(root),
    }
    return result


def append_research_artifact_version(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("artifact_id"):
        raise ValueError("artifact_id is required")
    current = get_research_artifact(workspace_root, {"artifact_id": args["artifact_id"]})
    payload = {
        **current,
        **args,
        "_append_version": True,
        "expected_content_hash": args.get("expected_content_hash") or current.get("content_hash"),
        "metadata": args.get("metadata") or current.get("metadata") or {},
        "export_path": args.get("export_path") or current.get("path") or current.get("export_path"),
    }
    if args.get("markdown"):
        payload["markdown"] = args["markdown"]
    elif args.get("markdown_path") or args.get("markdown_file"):
        payload.pop("markdown", None)
    else:
        payload["markdown"] = current.get("markdown")
    return create_research_artifact(workspace_root, payload)


def get_research_artifact(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    artifact_id = args.get("artifact_id") or args.get("id")
    if not artifact_id:
        raise ValueError("artifact_id is required")
    artifact = find_workspace_research_artifact(Path(workspace_root), str(artifact_id))
    if not artifact:
        raise ValueError(f"research artifact not found in workspace: {artifact_id}")
    if args.get("include_markdown", True) is not False:
        artifact["markdown"] = _read_research_markdown_body(Path(workspace_root) / artifact["path"])
    return artifact


def list_research_artifacts(workspace_root: Path | str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    artifacts = list_workspace_research_artifacts(Path(workspace_root), include_markdown=args.get("include_markdown") is True)
    for field in ["artifact_type", "universe", "workflow_type", "symbol", "readiness_label", "handoff_state", "created_by"]:
        value = args.get(field)
        if value:
            artifacts = [artifact for artifact in artifacts if str(artifact.get(field) or "").lower() == str(value).lower()]
    limit = max(1, min(int(args.get("limit") or 50), 200))
    return {
        "db_canonical": False,
        "file_sot": True,
        "workspace_native": True,
        "workspace_context": workspace_context_payload(workspace_root),
        "artifacts": artifacts[:limit],
    }


def search_research_artifacts(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        raise ValueError("query is required")
    root = Path(workspace_root)
    indexed = _refresh_research_index(root)
    query_lower = query.lower()
    candidates = [
        entry
        for entry in indexed.values()
        if query_lower in str(entry.get("metadata_search_text") or "")
        or query_lower in str(entry.get("body_search_text") or "")
    ]
    artifacts = []
    for entry in candidates:
        path = safe_workspace_path(root, entry["path"], allowed_roots=RESEARCH_FILE_ROOTS)
        artifact = _indexed_payload(root, entry)
        if query_lower not in str(entry.get("metadata_search_text") or ""):
            body = _read_research_markdown_body(path)
            if query_lower not in body.lower():
                continue
        artifacts.append(artifact)
    for field in ["universe", "artifact_type"]:
        if args.get(field):
            artifacts = [artifact for artifact in artifacts if str(artifact.get(field) or "").lower() == str(args[field]).lower()]
    limit = max(1, min(int(args.get("limit") or 20), 100))
    for artifact in artifacts:
        artifact.pop("markdown", None)
    return {
        "query": query,
        "db_canonical": False,
        "file_sot": True,
        "workspace_native": True,
        "workspace_context": workspace_context_payload(workspace_root),
        "artifacts": artifacts[:limit],
    }


def export_research_artifact_md(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    artifact_id = args.get("artifact_id") or args.get("id")
    if not artifact_id:
        raise ValueError("artifact_id is required")
    artifact = get_research_artifact(root, {"artifact_id": artifact_id, "include_markdown": True})
    target_rel = str(args.get("export_path") or artifact["path"])
    target = safe_workspace_path(root, target_rel, allowed_roots=RESEARCH_FILE_ROOTS)
    source = safe_workspace_path(root, artifact["path"], allowed_roots=RESEARCH_FILE_ROOTS)
    if target.resolve() != source.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, source.read_text(encoding="utf-8"))
    return {
        "status": "exported",
        "artifact_id": artifact["artifact_id"],
        "export_path": target.relative_to(root).as_posix(),
        "db_canonical": False,
        "file_sot": True,
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }


def record_source_snapshot(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    recorded_at = _normalized_iso(args.get("recorded_at") or now_iso(), "recorded_at")
    retrieved_at = _normalized_iso(args.get("retrieved_at") or recorded_at, "retrieved_at")
    known_at = _normalized_iso(args.get("known_at") or args.get("published_at") or retrieved_at, "known_at")
    if known_at > recorded_at:
        raise ValueError("known_at must not be after recorded_at")
    source_payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
    provider = str(args.get("provider") or "unknown")
    source_category = str(args.get("source_category") or args.get("category") or "unknown")
    payload = {
        "provider": provider,
        "source_category": source_category,
        "source_locator": args.get("source_locator") or args.get("url") or f"provider:{sanitize_id(provider)}:{sanitize_id(source_category)}",
        "provider_query": args.get("provider_query") or args.get("query") or {},
        "as_of": args.get("as_of") or args.get("observed_at") or "",
        "observed_at": args.get("observed_at") or args.get("as_of") or "",
        "effective_at": args.get("effective_at") or "",
        "published_at": args.get("published_at") or "",
        "retrieved_at": retrieved_at,
        "known_at": known_at,
        "revision": args.get("revision") or "not_applicable",
        "vintage": args.get("vintage") or "not_applicable",
        "timezone": args.get("timezone") or "UTC",
        "schema_hash": args.get("schema_hash") or stable_hash({key: type(value).__name__ for key, value in sorted(source_payload.items())}),
        "corporate_action_policy": args.get("corporate_action_policy") or "not_specified",
        "price_adjustment_policy": args.get("price_adjustment_policy") or "not_specified",
        "universe_membership": args.get("universe_membership") if isinstance(args.get("universe_membership"), dict) else {},
        "delisting_policy": args.get("delisting_policy") or "not_specified",
        "coverage_note": args.get("coverage_note") or "coverage and licensing not specified",
        "artifact_id": args.get("artifact_id") or "",
        "warnings": args.get("warnings") if isinstance(args.get("warnings"), list) else [],
        "payload": source_payload,
        "payload_hash": stable_hash(source_payload),
        "created_by": args.get("principal_id") or args.get("created_by") or "system",
        "recorded_at": recorded_at,
        "workspace_native": True,
    }
    payload["snapshot_hash"] = stable_hash(payload)
    snapshot_id = _source_snapshot_id(payload)
    rel_path = SOURCE_SNAPSHOT_ROOT / f"{snapshot_id}.json"
    path = safe_workspace_path(root, rel_path, allowed_roots=SOURCE_SNAPSHOT_ROOTS)
    document = {**payload, "snapshot_id": snapshot_id}
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != document:
        raise ValueError(f"source snapshot id collision: {snapshot_id}")
    atomic_write_text(path, json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    result = {
        "status": "recorded",
        "snapshot_id": snapshot_id,
        "artifact_id": payload["artifact_id"],
        "provider": payload["provider"],
        "source_category": payload["source_category"],
        "export_path": path.relative_to(root).as_posix(),
        "db_canonical": False,
        "file_sot": True,
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }
    return result


def create_evidence_run_card(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    related_rel, related_hash, artifact_hashes = _related_artifact_card_values(root, args)
    config_hash = str(args.get("config_hash") or stable_hash(args.get("config") if args.get("config") is not None else {}))
    card_seed = {"related_artifact_path": related_rel, "related_artifact_hash": related_hash, "config_hash": config_hash}
    card = {
        "schema_version": 1,
        "artifact_type": "evidence_run_card",
        "card_id": str(args.get("card_id") or f"run-card-{sanitize_id(Path(related_rel).stem)}-{stable_hash(card_seed)[:12]}"),
        "related_artifact_path": related_rel,
        "generated_at": str(args.get("generated_at") or now_iso()),
        "created_by": str(args.get("created_by") or args.get("principal_id") or "system"),
        "config_hash": config_hash,
        "input_refs": _coerce_list(args.get("input_refs") or args.get("inputs")),
        "data_source_refs": _coerce_list(args.get("data_source_refs") or args.get("data_sources")),
        "artifact_hashes": artifact_hashes,
        "metrics": args.get("metrics") if isinstance(args.get("metrics"), dict) else {},
        "validation_summary": args.get("validation_summary") or "",
        "warnings": _coerce_list(args.get("warnings")),
        "source_limitations": _coerce_list(args.get("source_limitations")),
        "authority": "evidence_only",
        "blocked_actions": list(dict.fromkeys(["order_drafting", "order_approval", "order_execution", *_coerce_list(args.get("blocked_actions"))])),
    }
    rel_path = str(args.get("export_path") or default_evidence_run_card_path(related_rel))
    if not rel_path.endswith(".run-card.json"):
        raise ValueError("evidence run card export_path must end with .run-card.json")
    path = safe_workspace_path(root, rel_path, allowed_roots=WORKFLOW_ARTIFACT_ROOTS)
    atomic_write_text(path, json.dumps(card, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    return {
        "status": "recorded",
        "card_id": card["card_id"],
        "artifact_type": "evidence_run_card",
        "related_artifact_path": related_rel,
        "export_path": path.relative_to(root).as_posix(),
        "config_hash": card["config_hash"],
        "workspace_native": True,
        "file_sot": True,
        "db_canonical": False,
        "workspace_context": workspace_context_payload(root),
    }


def create_validation_card(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    related_rel, related_hash, artifact_hashes = _related_artifact_card_values(root, args)
    checks = _normalize_validation_checks(args.get("checks"))
    card_seed = {"related_artifact_path": related_rel, "related_artifact_hash": related_hash, "validation_scope": args.get("validation_scope") or "evidence_quality"}
    card = {
        "schema_version": 1,
        "artifact_type": "validation_card",
        "card_id": str(args.get("card_id") or f"validation-card-{sanitize_id(Path(related_rel).stem)}-{stable_hash(card_seed)[:12]}"),
        "related_artifact_path": related_rel,
        "generated_at": str(args.get("generated_at") or now_iso()),
        "created_by": str(args.get("created_by") or args.get("principal_id") or "system"),
        "validation_scope": str(args.get("validation_scope") or "evidence_quality"),
        "evidence_quality_label": str(args.get("evidence_quality_label") or "not_validated"),
        "input_refs": _coerce_list(args.get("input_refs") or args.get("inputs")),
        "data_source_refs": _coerce_list(args.get("data_source_refs") or args.get("data_sources")),
        "artifact_hashes": artifact_hashes,
        "checks": checks,
        "metrics": args.get("metrics") if isinstance(args.get("metrics"), dict) else {},
        "validation_summary": args.get("validation_summary") or "",
        "warnings": _coerce_list(args.get("warnings")),
        "source_limitations": _coerce_list(args.get("source_limitations")),
        "authority": "evidence_only",
        "blocked_actions": list(dict.fromkeys(["order_drafting", "order_approval", "order_execution", *_coerce_list(args.get("blocked_actions"))])),
    }
    if card["evidence_quality_label"] == "validated":
        incomplete = [
            key
            for key, check in checks.items()
            if check["status"] not in {"pass", "not_applicable"} or not check["evidence_refs"]
        ]
        if incomplete:
            raise ValueError(f"validated cards require completed evidence-backed checks: {', '.join(incomplete)}")
    rel_path = str(args.get("export_path") or default_validation_card_path(related_rel))
    if not rel_path.endswith(".validation-card.json"):
        raise ValueError("validation card export_path must end with .validation-card.json")
    path = safe_workspace_path(root, rel_path, allowed_roots=WORKFLOW_ARTIFACT_ROOTS)
    atomic_write_text(path, json.dumps(card, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    return {
        "status": "recorded",
        "card_id": card["card_id"],
        "artifact_type": "validation_card",
        "related_artifact_path": related_rel,
        "export_path": path.relative_to(root).as_posix(),
        "evidence_quality_label": card["evidence_quality_label"],
        "workspace_native": True,
        "file_sot": True,
        "db_canonical": False,
        "workspace_context": workspace_context_payload(root),
    }


def _related_artifact_card_values(root: Path, args: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    related_arg = args.get("related_artifact_path") or args.get("artifact_path") or args.get("path")
    if not related_arg:
        raise ValueError("related_artifact_path is required")
    related = safe_workspace_path(root, str(related_arg), allowed_roots=WORKFLOW_ARTIFACT_ROOTS)
    if not related.exists() or not related.is_file():
        raise ValueError("related artifact path does not exist")
    related_rel = related.relative_to(root).as_posix()
    related_hash = file_hash(related) or ""
    artifact_hashes = args.get("artifact_hashes") if isinstance(args.get("artifact_hashes"), dict) else {}
    artifact_hashes = {str(key): str(value) for key, value in artifact_hashes.items() if value not in (None, "")}
    artifact_hashes.setdefault(related_rel, related_hash)
    return related_rel, related_hash, artifact_hashes


def list_workspace_research_artifacts(root: Path, *, include_markdown: bool = False) -> list[dict[str, Any]]:
    records = []
    for entry in _refresh_research_index(root).values():
        payload = _indexed_payload(root, entry)
        if include_markdown:
            path = safe_workspace_path(root, entry["path"], allowed_roots=RESEARCH_FILE_ROOTS)
            payload["markdown"] = _read_research_markdown_body(path)
        records.append(payload)
    return sorted(records, key=lambda item: item["updated_at"], reverse=True)


def rebuild_research_index(workspace_root: Path | str) -> dict[str, Any]:
    root = Path(workspace_root)
    path = safe_workspace_path(root, RESEARCH_INDEX_PATH, allowed_roots=(Path("trading/research"),))
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    entries = _refresh_research_index(root)
    return {
        "status": "rebuilt",
        "artifact_count": len(entries),
        "index_path": RESEARCH_INDEX_PATH.as_posix(),
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }


def _refresh_research_index(root: Path) -> dict[str, dict[str, Any]]:
    index_path = safe_workspace_path(root, RESEARCH_INDEX_PATH, allowed_roots=(Path("trading/research"),))
    lock_target = root / "trading/research/.index/research-index"
    with exclusive_file_lock(lock_target):
        existing: dict[str, Any] = {}
        if index_path.exists():
            try:
                document = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                document = {}
            if isinstance(document, dict) and document.get("schema_version") == RESEARCH_INDEX_VERSION:
                raw_entries = document.get("entries")
                existing = raw_entries if isinstance(raw_entries, dict) else {}
        paths: list[Path] = []
        for rel_root in RESEARCH_FILE_ROOTS:
            base = root / rel_root
            if base.exists():
                paths.extend(
                    path
                    for path in base.rglob("*.md")
                    if path.name != ".gitkeep" and ".versions" not in path.parts and ".index" not in path.parts
                )
        entries: dict[str, dict[str, Any]] = {}
        changed = set(existing) != {path.relative_to(root).as_posix() for path in paths}
        for path in sorted(paths):
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
            cached = existing.get(rel) if isinstance(existing.get(rel), dict) else {}
            if cached.get("mtime_ns") == stat.st_mtime_ns and cached.get("size") == stat.st_size:
                entries[rel] = cached
                continue
            payload = _research_file_payload(root, path, include_markdown=True)
            body = str(payload.pop("markdown", ""))
            stored_payload = {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in payload.items()
                if key != "workspace_context"
            }
            metadata_search_text = " ".join(
                str(payload.get(key) or "").lower()
                for key in ("artifact_id", "path", "artifact_type", "universe", "role", "symbol", "title", "context_summary", "reader_summary")
            )
            entries[rel] = {
                "path": rel,
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "file_hash": file_hash(path),
                "payload": stored_payload,
                "metadata_search_text": metadata_search_text,
                "body_search_text": body.lower(),
            }
            changed = True
        if changed or not index_path.exists():
            atomic_write_text(
                index_path,
                json.dumps(
                    {
                        "schema_version": RESEARCH_INDEX_VERSION,
                        "generated_at": now_iso(),
                        "entries": entries,
                    },
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                ) + "\n",
            )
        return entries


def _indexed_payload(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    raw = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    payload = dict(raw)
    for field in ("updated_at", "created_at"):
        if payload.get(field):
            payload[field] = datetime.fromisoformat(str(payload[field]).replace("Z", "+00:00"))
    payload["workspace_context"] = workspace_context_payload(root)
    return payload


def find_workspace_research_artifact(root: Path, artifact_id: str) -> dict[str, Any] | None:
    if "/" in artifact_id or "\\" in artifact_id or artifact_id.endswith(".md"):
        try:
            direct = safe_workspace_path(root, artifact_id, allowed_roots=RESEARCH_FILE_ROOTS)
        except ValueError:
            direct = None
        if direct and direct.exists() and direct.is_file():
            return _research_file_payload(root, direct, include_markdown=False)
    for artifact in list_workspace_research_artifacts(root, include_markdown=False):
        if artifact["artifact_id"] == artifact_id or artifact["path"] == artifact_id:
            return artifact
    return None


def _research_file_payload(root: Path, path: Path, *, include_markdown: bool = False) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    frontmatter, heading, body = _research_file_parts(path)
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    artifact_id = str(frontmatter.get("artifact_id") or rel)
    payload = {
        "artifact_id": artifact_id,
        "path": rel,
        "export_path": rel,
        "artifact_type": str(frontmatter.get("artifact_type") or _infer_research_artifact_type(path)),
        "universe": str(frontmatter.get("universe") or _infer_research_universe(path)),
        "workflow_type": str(frontmatter.get("workflow_type") or ""),
        "role": str(frontmatter.get("role") or ""),
        "symbol": str(frontmatter.get("symbol") or ""),
        "title": str(frontmatter.get("title") or heading or path.stem.replace("-", " ").title()),
        "metadata": {},
        "workspace_context": workspace_context_payload(root),
        "source_as_of": str(frontmatter.get("source_as_of") or ""),
        "readiness_label": str(frontmatter.get("readiness_label") or frontmatter.get("handoff_state") or "workspace-file"),
        "context_summary": str(frontmatter.get("context_summary") or ""),
        "reader_summary": str(frontmatter.get("reader_summary") or ""),
        "handoff_state": str(frontmatter.get("handoff_state") or ""),
        "confidence": str(frontmatter.get("confidence") or ""),
        "missing_evidence": _coerce_list(frontmatter.get("missing_evidence")),
        "next_recipient": str(frontmatter.get("next_recipient") or ""),
        "next_action": str(frontmatter.get("next_action") or ""),
        "blocked_actions": _coerce_list(frontmatter.get("blocked_actions")),
        "source_snapshot_ids": _coerce_list(frontmatter.get("source_snapshot_ids")),
        "workflow_run_id": str(frontmatter.get("workflow_run_id") or ""),
        "plan_hash": str(frontmatter.get("plan_hash") or ""),
        "stage_id": str(frontmatter.get("stage_id") or ""),
        "task_id": str(frontmatter.get("task_id") or ""),
        "producer_role": str(frontmatter.get("producer_role") or frontmatter.get("role") or ""),
        "artifact_schema_version": _int_value(frontmatter.get("artifact_schema_version"), default=1),
        "input_artifact_hashes": frontmatter.get("input_artifact_hashes") if isinstance(frontmatter.get("input_artifact_hashes"), dict) else {},
        "knowledge_cutoff": str(frontmatter.get("knowledge_cutoff") or frontmatter.get("source_as_of") or ""),
        "follow_up_requests": _coerce_list(frontmatter.get("follow_up_requests")),
        "improvements": _coerce_list(frontmatter.get("improvements")),
        "created_by": str(frontmatter.get("created_by") or "workspace"),
        "content_hash": str(frontmatter.get("content_hash") or content_hash),
        "version": _int_value(frontmatter.get("version"), default=1),
        "parent_artifact_id": str(frontmatter.get("parent_artifact_id") or ""),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        "created_at": datetime.fromtimestamp(path.stat().st_ctime, tz=timezone.utc),
        "db_canonical": False,
        "file_sot": True,
        "workspace_native": True,
    }
    if include_markdown:
        payload["markdown"] = body
    return payload


def _research_file_parts(path: Path) -> tuple[dict[str, Any], str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}, "", ""
    document = split_markdown_frontmatter(text)
    return document.frontmatter, document.heading, document.body


def _read_research_markdown_body(path: Path) -> str:
    return _research_file_parts(path)[2]


def _render_research_markdown(frontmatter: dict[str, Any], markdown: str) -> str:
    header = "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items()) + "\n---\n\n"
    return header + markdown.rstrip() + "\n"


def _frontmatter_value(args: dict[str, Any], metadata: dict[str, Any], source_frontmatter: dict[str, Any], field: str, default: Any) -> Any:
    for container in (args, metadata, source_frontmatter):
        value = container.get(field)
        if value not in (None, ""):
            return value
    return default


def _frontmatter_list(args: dict[str, Any], metadata: dict[str, Any], source_frontmatter: dict[str, Any], field: str) -> list[Any]:
    return _coerce_list(_frontmatter_value(args, metadata, source_frontmatter, field, []))


def _coerce_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
        if isinstance(parsed, list):
            return parsed
        if parsed in (None, ""):
            return []
        return [parsed]
    return [value]


def _normalize_validation_checks(value: Any) -> dict[str, dict[str, Any]]:
    raw_checks = value if isinstance(value, dict) else {}
    checks: dict[str, dict[str, Any]] = {}
    for key in ANTI_OVERFIT_CHECK_KEYS:
        raw = raw_checks.get(key)
        if isinstance(raw, dict):
            status = str(raw.get("status") or "not_assessed")
            reason = str(raw.get("reason") or "")
            evidence_refs = _coerce_list(raw.get("evidence_refs"))
        else:
            text = str(raw or "not_assessed")
            status = text if text in {"pass", "fail", "not_applicable", "not_assessed"} else "not_assessed"
            reason = "" if status == "not_assessed" else text
            evidence_refs = []
        if status not in {"pass", "fail", "not_applicable", "not_assessed"}:
            raise ValueError(f"validation check {key} has an invalid status")
        checks[key] = {"status": status, "reason": reason, "evidence_refs": evidence_refs}
    return checks


def _validate_source_snapshot_links(root: Path, snapshot_ids: list[Any], knowledge_cutoff: str) -> None:
    if not snapshot_ids:
        return
    cutoff = _normalized_iso(knowledge_cutoff, "knowledge_cutoff") if knowledge_cutoff else ""
    for raw_snapshot_id in snapshot_ids:
        snapshot_id = sanitize_id(raw_snapshot_id)
        path = safe_workspace_path(root, SOURCE_SNAPSHOT_ROOT / f"{snapshot_id}.json", allowed_roots=SOURCE_SNAPSHOT_ROOTS)
        if not path.exists():
            raise ValueError(f"source snapshot not found: {raw_snapshot_id}")
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"source snapshot is invalid: {raw_snapshot_id}") from exc
        if not isinstance(snapshot, dict):
            raise ValueError(f"source snapshot must be an object: {raw_snapshot_id}")
        known_at = _normalized_iso(snapshot.get("known_at"), f"source snapshot {raw_snapshot_id} known_at")
        if cutoff and known_at > cutoff:
            raise ValueError(f"source snapshot is after artifact knowledge cutoff: {raw_snapshot_id}")


def _normalized_iso(value: Any, field: str) -> str:
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


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _infer_research_universe(path: Path) -> str:
    text = path.as_posix().lower()
    if "crypto" in text:
        return "public_crypto"
    if "macro" in text:
        return "macro"
    return "workspace"


def _infer_research_artifact_type(path: Path) -> str:
    parts = path.as_posix().split("/")
    if "reports" in parts:
        index = parts.index("reports")
        if len(parts) > index + 1:
            return f"{parts[index + 1]}_report"
        return "role_report"
    if path.name.endswith(".evidence.md"):
        return "evidence_pack"
    return "research_handoff"


def _role_alias_from_actor(actor: str) -> str:
    return actor.replace("-analyst", "").replace("-manager", "").replace("-operator", "")


def _source_snapshot_id(payload: dict[str, Any]) -> str:
    base = "-".join(
        filter(
            None,
            [
                sanitize_id(str(payload.get("provider") or "unknown")),
                sanitize_id(str(payload.get("source_category") or "unknown")),
                sanitize_id(str(payload.get("artifact_id") or "")),
            ],
        )
    )
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"{base or 'source-snapshot'}-{digest}"


def default_research_export_path_from_values(artifact_id: str, artifact_type: str, metadata: dict[str, Any]) -> str:
    stem = sanitize_id(artifact_id)
    role = metadata.get("role") if isinstance(metadata, dict) else ""
    if artifact_type == "evidence_pack":
        return f"trading/research/{stem}.evidence.md"
    if role in {"fundamental", "technical", "news", "macro", "instrument", "valuation", "portfolio", "risk", "policy"}:
        return f"trading/reports/{role}/{stem}.md"
    return f"trading/research/{stem}.md"


def default_evidence_run_card_path(related_artifact_path: str) -> str:
    related = Path(related_artifact_path)
    return (related.parent / f"{related.stem}.run-card.json").as_posix()


def default_validation_card_path(related_artifact_path: str) -> str:
    related = Path(related_artifact_path)
    return (related.parent / f"{related.stem}.validation-card.json").as_posix()
