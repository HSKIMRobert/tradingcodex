from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingcodex_service.application.artifact_quality import evaluate_artifact_quality, estimate_tokens
from tradingcodex_service.application.common import read_json
from tradingcodex_service.application.research import list_workspace_research_artifacts


MAX_SESSION_STATE_TOKENS = 2000
MAX_CONTEXT_SUMMARY_CHARS = 1200
LARGE_ARTIFACT_BODY_TOKENS = 6000


def audit_context_budget(workspace_root: Path | str, *, strict: bool = False) -> dict[str, Any]:
    root = Path(workspace_root)
    session_path = root / ".tradingcodex/mainagent/subagent-session-state.json"
    session = read_json(session_path, {"active": {}, "completed": [], "events": []})
    session_tokens = estimate_tokens(json.dumps(session, ensure_ascii=False, sort_keys=True))
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    _add_check(
        checks,
        "subagent session state stays compact",
        session_tokens <= MAX_SESSION_STATE_TOKENS,
        estimated_tokens=session_tokens,
        limit_tokens=MAX_SESSION_STATE_TOKENS,
    )

    records: list[dict[str, Any]] = []
    missing_context: list[str] = []
    oversized_context: list[str] = []
    large_bodies: list[dict[str, Any]] = []
    for artifact in list_workspace_research_artifacts(root, include_markdown=False):
        quality = evaluate_artifact_quality(root, artifact["path"], strict=False)
        efficiency = quality.get("context_efficiency") or {}
        record = {
            "artifact_id": artifact.get("artifact_id"),
            "path": artifact.get("path"),
            "context_summary_chars": int(efficiency.get("context_summary_chars") or 0),
            "context_summary_present": bool(efficiency.get("context_summary_present")),
            "body_estimated_tokens": int(efficiency.get("body_estimated_tokens") or 0),
        }
        records.append(record)
        if not record["context_summary_present"]:
            missing_context.append(str(record["path"]))
        if record["context_summary_chars"] > MAX_CONTEXT_SUMMARY_CHARS:
            oversized_context.append(str(record["path"]))
        if record["body_estimated_tokens"] > LARGE_ARTIFACT_BODY_TOKENS:
            large_bodies.append(record)
    _add_check(
        checks,
        "research artifacts expose context summaries",
        not missing_context if strict else True,
        missing=missing_context,
        strict=strict,
    )
    _add_check(
        checks,
        "context summaries stay concise",
        not oversized_context,
        oversized=oversized_context,
        limit_chars=MAX_CONTEXT_SUMMARY_CHARS,
    )
    if missing_context:
        warnings.append(f"{len(missing_context)} research artifact(s) missing context_summary")
    if large_bodies:
        warnings.append("large artifacts detected; pass artifact IDs and context summaries before targeted body reads")
    return {
        "status": "fail" if any(item["status"] == "fail" for item in checks) else "pass",
        "strict": strict,
        "checks": checks,
        "warnings": warnings,
        "session_state": {
            "path": ".tradingcodex/mainagent/subagent-session-state.json",
            "estimated_tokens": session_tokens,
            "active_count": len(session.get("active", {}) if isinstance(session, dict) else {}),
            "retained_event_count": len(session.get("events", []) if isinstance(session, dict) else []),
        },
        "artifacts": {
            "checked": len(records),
            "missing_context_summary": missing_context,
            "oversized_context_summary": oversized_context,
            "large_body_count": len(large_bodies),
            "records": records,
        },
        "recommended_handoff": "pass exact artifact IDs plus context_summary; read full bodies only for synthesis or targeted conflict checks",
    }


def _add_check(checks: list[dict[str, Any]], name: str, ok: bool, **extra: Any) -> None:
    checks.append({"name": name, "status": "pass" if ok else "fail", **extra})
