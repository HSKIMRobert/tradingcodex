from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tradingcodex_cli.codex_trace_audit import (
    _KNOWN_TCX_TOOL_NAMES,
    MAX_FIRST_PROGRESS_LATENCY_MS,
    MAX_REPORTED_TRUNCATION_TOKENS,
    MAX_VISIBLE_SILENCE_MS,
    MAX_WAIT_TIMEOUT_MS,
    MIN_WAIT_TIMEOUT_MS,
    audit_codex_trace,
    discover_rollouts,
    main,
)
from tradingcodex_service.mcp_runtime import TOOL_REGISTRY


HEAD_BASE = "You are the `head-manager` agent for TradingCodex"
CHILD_BASE = "You are a fixed-role child in TradingCodex"
DEFERRED_TOOL = "mcp__tradingcodex__begin_analysis_run"
DEFERRED_NAMES_QUERY = (
    'text(ALL_TOOLS.filter(x => x.name.includes("begin_analysis_run"))'
    ".slice(0, 12).map(x => x.name))"
)
DEFERRED_SCHEMA_QUERY = (
    f'const t = ALL_TOOLS.find(x => x.name === "{DEFERRED_TOOL}"); '
    'text(t ? t.description : "missing")'
)
DEFERRED_COMPOUND_QUERY = (
    'const names = ALL_TOOLS.filter(x => x.name.includes("source_snapshot") || '
    'x.name.includes("research_artifact") || x.name.includes("filing") || '
    'x.name.includes("disclosure")).slice(0, 12).map(x => x.name); text(names);'
)


def test_trace_audit_tcx_tool_privacy_allowlist_matches_registry() -> None:
    assert _KNOWN_TCX_TOOL_NAMES == set(TOOL_REGISTRY)


def _write_jsonl(path: Path, items: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


def _session_meta(
    session_id: str,
    *,
    parent_id: str | None = None,
    role: str = "fundamental-analyst",
    nickname: str | None = None,
    agent_path: str = "/root/fundamental",
    base: str = "",
) -> dict[str, object]:
    source: dict[str, object] = {}
    if parent_id:
        source = {
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": parent_id,
                    "depth": 1,
                    "agent_path": agent_path,
                    "agent_nickname": nickname or role,
                    "agent_role": role,
                }
            }
        }
    return {
        "type": "session_meta",
        "payload": {"id": session_id, "source": source, "base_instructions": {"text": base}},
    }


def _turn_context(*, root: bool = False, model: str | None = None) -> dict[str, object]:
    return {
        "type": "turn_context",
        "payload": {
            "model": model or ("gpt-5.6-sol" if root else "gpt-5.6-terra"),
            "effort": "xhigh" if root else "high",
            "multi_agent_version": "v2",
            "multi_agent_mode": "explicitRequestOnly",
            "sandbox_policy": {"type": "workspace-write", "network_access": True},
            "permission_profile": {"type": "managed"},
        },
    }


def _token(
    total_input: int,
    cached: int,
    output: int,
    *,
    last_input: int,
    include_cache_write: bool = True,
) -> dict[str, object]:
    total_usage = {
        "input_tokens": total_input,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "reasoning_output_tokens": 2,
        "total_tokens": total_input + output,
    }
    last_usage = {
        "input_tokens": last_input,
        "cached_input_tokens": min(cached, last_input),
        "output_tokens": output,
        "reasoning_output_tokens": 2,
        "total_tokens": last_input + output,
    }
    if include_cache_write:
        total_usage["cache_write_input_tokens"] = 0
        last_usage["cache_write_input_tokens"] = 0
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": total_usage,
                "last_token_usage": last_usage,
                "model_context_window": 2_000,
            },
        },
    }


def _spawn(
    call_id: str,
    role: str,
    *,
    task_name: str = "fundamental",
    **extra: object,
) -> dict[str, object]:
    return {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "spawn_agent",
            "namespace": "agents",
            "call_id": call_id,
            "arguments": json.dumps(
                {
                    "agent_type": role,
                    "fork_turns": "none",
                    "message": "Compact fixed-role assignment with evidence scope.",
                    "task_name": task_name,
                    **extra,
                }
            ),
        },
    }


def _started(call_id: str, child_id: str, agent_path: str = "/root/fundamental") -> dict[str, object]:
    return {
        "type": "event_msg",
        "payload": {
            "type": "sub_agent_activity",
            "kind": "started",
            "event_id": call_id,
            "agent_thread_id": child_id,
            "agent_path": agent_path,
        },
    }


def _complete(duration_ms: object = 1_000) -> dict[str, object]:
    return {"type": "event_msg", "payload": {"type": "task_complete", "duration_ms": duration_ms}}


def _at(item: dict[str, object], timestamp: str) -> dict[str, object]:
    return {**item, "timestamp": timestamp}


def _task_started(timestamp: str) -> dict[str, object]:
    return _at(
        {"type": "event_msg", "payload": {"type": "task_started"}},
        timestamp,
    )


def _agent_message(timestamp: str | None, *, phase: str) -> dict[str, object]:
    item: dict[str, object] = {
        "type": "event_msg",
        "payload": {"type": "agent_message", "phase": phase, "message": "PRIVATE"},
    }
    return _at(item, timestamp) if timestamp is not None else item


def _wait_agent(call_id: str, timeout_ms: object | None) -> dict[str, object]:
    return {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "wait_agent",
            "namespace": "agents",
            "call_id": call_id,
            "arguments": json.dumps(
                {} if timeout_ms is None else {"timeout_ms": timeout_ms}
            ),
        },
    }


def _audit_root_cadence(
    tmp_path: Path,
    events: list[dict[str, object]],
    *,
    duration_ms: int | None,
    dispatch_before_progress: bool = False,
) -> dict[str, object]:
    root_id = "root-cadence"
    child_id = "child-cadence"
    root = tmp_path / "root-cadence.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    first_progress_index = next(
        (
            index
            for index, event in enumerate(events)
            if event.get("type") == "event_msg"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("type") == "agent_message"
            and event["payload"].get("phase") != "final_answer"
        ),
        None,
    )
    prefix = (
        events[: first_progress_index + 1]
        if first_progress_index is not None and not dispatch_before_progress
        else []
    )
    suffix = (
        events[first_progress_index + 1 :]
        if first_progress_index is not None and not dispatch_before_progress
        else events
    )
    items = [
        _session_meta(root_id, base=HEAD_BASE),
        _turn_context(root=True),
        *prefix,
        _spawn("spawn-cadence", "fundamental-analyst"),
        _started("spawn-cadence", child_id),
        *suffix,
        _authenticated_artifact_write(
            "synthesis-cadence",
            artifact_type="synthesis_report",
            path="trading/reports/synthesis/synthesis-cadence.md",
            inputs=["fundamental-cadence"],
        ),
        _token(100, 80, 10, last_input=90),
    ]
    if duration_ms is not None:
        items.append(
            _at(
                _complete(duration_ms),
                f"2026-07-18T00:{duration_ms // 60_000:02d}:{(duration_ms % 60_000) // 1_000:02d}.000Z",
            )
        )
    _write_jsonl(root, items)
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            _authenticated_artifact_write(
                "fundamental-cadence",
                artifact_type="fundamental_report",
                path="trading/reports/fundamental/fundamental-cadence.md",
            ),
            _artifact_receipt_message(
                "fundamental-cadence",
                "trading/reports/fundamental/fundamental-cadence.md",
            ),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    return audit_codex_trace(root, candidate=True)


def _mcp(tool: str, arguments: dict[str, object], result: dict[str, object]) -> dict[str, object]:
    return {
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "invocation": {"server": "tradingcodex", "tool": tool, "arguments": arguments},
            "duration": {"secs": 0, "nanos": 10_000_000},
            "result": result,
        },
    }


def _external_mcp(
    server: str,
    tool: str,
    arguments: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    event = _mcp(tool, arguments, result)
    payload = event["payload"]
    assert isinstance(payload, dict)
    invocation = payload["invocation"]
    assert isinstance(invocation, dict)
    invocation["server"] = server
    return event


def _external_promotion(
    server: str,
    tool: str,
    external_arguments: dict[str, object],
    *,
    result_status: str = "complete_valid",
    tool_name: str | None = None,
    requested_provider: str | None = None,
) -> dict[str, object]:
    provider = requested_provider or str(
        external_arguments.get("provider")
        or external_arguments.get("provider_name")
        or "direct"
    )
    raw_identifiers = next(
        (
            external_arguments[name]
            for name in (
                "identifiers",
                "identifier",
                "symbols",
                "symbol",
                "tickers",
                "ticker",
                "isin",
                "cik",
                "series_id",
                "contract",
            )
            if name in external_arguments
        ),
        ["UNKNOWN"],
    )
    identifiers = raw_identifiers if isinstance(raw_identifiers, list) else [raw_identifiers]
    raw_fields = external_arguments.get("fields", external_arguments.get("columns", ["value"]))
    fields = raw_fields if isinstance(raw_fields, list) else [raw_fields]
    start = next(
        (
            external_arguments[name]
            for name in ("start_date", "start", "date_from")
            if name in external_arguments
        ),
        None,
    )
    end = next(
        (
            external_arguments[name]
            for name in ("end_date", "end", "date_to")
            if name in external_arguments
        ),
        None,
    )
    as_of = next(
        (
            external_arguments[name]
            for name in ("as_of", "asof", "date")
            if name in external_arguments
        ),
        None,
    )
    frequency = next(
        (
            external_arguments[name]
            for name in ("interval", "frequency", "period")
            if name in external_arguments
        ),
        "1d",
    )
    adjustment = next(
        (
            external_arguments[name]
            for name in ("adjustment", "adjusted")
            if name in external_arguments
        ),
        "unadjusted",
    )
    row_bearing = result_status in {"complete_valid", "partial_valid"}
    identifier_suffix = re.sub(
        r"[^a-z0-9]+", "-", str(identifiers[0]).casefold()
    ).strip("-") or "unknown"
    receipt_id = f"data-acquisition-{identifier_suffix}"
    snapshot_id = f"source-snapshot-{identifier_suffix}" if row_bearing else ""
    dataset_id = f"dataset-{identifier_suffix}" if row_bearing else ""
    exact_tool_name = tool_name or f"mcp__{server}__{tool}"
    data_need: dict[str, object] = {
        "data_kind": "equity_price",
        "asset_type": "equity",
        "identifiers": identifiers,
        "fields": fields,
        "frequency": frequency,
        "adjustment_policy": adjustment,
        "minimum_evidence_grade": "screen-grade",
        "owner_role": "fundamental-analyst",
        "source_policy": "best_available",
    }
    if start is not None:
        data_need["period_start"] = start
    if end is not None:
        data_need["period_end"] = end
    if as_of is not None:
        data_need["as_of"] = as_of
    arguments: dict[str, object] = {
        "data_need": data_need,
        "source_tier": "openbb" if server == "openbb" else "user_capability",
        "transport": f"mcp__{server}",
        "requested_provider": provider,
        "returned_provider": provider if row_bearing else "",
        "upstream_provider": provider,
        "tool_name": exact_tool_name,
        "route": f"/{tool}",
        "returned_adjustment_policy": adjustment if row_bearing else "",
        "result_status": result_status,
        "evidence_grade": "screen-grade" if row_bearing else "unusable",
        "provider_query": dict(external_arguments),
        "rows": ([{"symbol": str(identifiers[0]), "value": 1}] if row_bearing else []),
        "columns": (
            [{"name": "symbol", "type": "string"}, {"name": "value", "type": "float64"}]
            if row_bearing
            else []
        ),
    }
    if not row_bearing:
        arguments["fallback_reason"] = "typed external source gap"
    receipt = {
        "receipt_id": receipt_id,
        "snapshot_id": snapshot_id,
        "dataset_id": dataset_id,
        "row_count": 1 if row_bearing else 0,
        "result_status": result_status,
        "tool_name": exact_tool_name,
        "requested_provider": provider,
        "returned_provider": provider if row_bearing else "",
        "upstream_provider": provider,
    }
    return _mcp(
        "record_external_data_result",
        arguments,
        _ok(
            {
                "status": "recorded",
                "receipt_id": receipt_id,
                "snapshot_id": snapshot_id,
                "dataset_id": dataset_id,
                "receipt": receipt,
            }
        ),
    )


def _official_source_record_arguments(
    external_arguments: dict[str, object],
    *,
    provider_query: dict[str, object] | None = None,
) -> dict[str, object]:
    source_id = str(external_arguments.get("source_id") or "bls-v1")
    normalized_query = provider_query or {
        "provider": source_id,
        "series_ids": list(external_arguments["identifiers"]),
        "start_year": 2026,
        "end_year": 2026,
    }
    return {
        "source_tier": "tradingcodex",
        "transport": "tradingcodex-official",
        "requested_provider": source_id,
        "returned_provider": source_id,
        "upstream_provider": source_id,
        "tool_name": "mcp__tradingcodex__fetch_official_source_data",
        "route": "/publicAPI/v2/timeseries/data/",
        "returned_adjustment_policy": "not_applicable",
        "result_status": "complete_valid",
        "fallback_reason": "",
        "evidence_grade": "factual-baseline",
        "provider_query": normalized_query,
        "source_category": str(external_arguments["data_kind"]),
        "source_locator": "/publicAPI/v2/timeseries/data/",
        "timezone": "UTC",
        "coverage_note": "",
        "warnings": [],
        "rows": [{"series_id": "LNS14000000", "value": 4.1}],
        "columns": [
            {"name": "series_id", "type": "string"},
            {"name": "value", "type": "float64"},
        ],
        "data_classification": "public",
        "redistribution": "not_specified",
    }


def _official_source_result(
    external_arguments: dict[str, object],
    *,
    provider_query: dict[str, object] | None = None,
) -> dict[str, object]:
    source_id = str(external_arguments.get("source_id") or "bls-v1")
    record_arguments = _official_source_record_arguments(
        external_arguments, provider_query=provider_query
    )
    return _ok(
        {
            "schema_version": 1,
            "status": "complete_valid",
            "source_policy": external_arguments.get(
                "source_policy", "best_available"
            ),
            "data_kind": external_arguments["data_kind"],
            "region": external_arguments.get("region", ""),
            "selected_source_id": source_id,
            "attempts": [
                {
                    "source_id": source_id,
                    "result_status": "complete_valid",
                }
            ],
            "accepted_results": [
                {
                    "source_id": source_id,
                    "result_status": "complete_valid",
                    "reference_only": False,
                    "row_count": 1,
                    "result_hash": "official-result-hash",
                }
            ],
            "coverage_gap": "",
            "fallback_exhausted": False,
            "same_call_retries": 0,
            "record_external_data_result_args": record_arguments,
            "recorder_instruction": "record immediately",
        }
    )


def _official_source_promotion(
    external_arguments: dict[str, object],
    *,
    provider_query: dict[str, object] | None = None,
    source_tier: str = "tradingcodex",
) -> dict[str, object]:
    source_id = str(external_arguments.get("source_id") or "bls-v1")
    receipt_id = "data-acquisition-official-source"
    snapshot_id = "source-snapshot-official-source"
    dataset_id = "dataset-official-source"
    tool_name = "mcp__tradingcodex__fetch_official_source_data"
    data_need = {
        "run_id": "analysis-official-source",
        "data_kind": external_arguments["data_kind"],
        "asset_type": external_arguments.get("asset_class", "macro"),
        "identifiers": list(external_arguments["identifiers"]),
        "fields": list(external_arguments.get("fields") or ["value"]),
        "period_start": external_arguments.get("period_start", ""),
        "period_end": external_arguments.get("period_end", ""),
        "frequency": "monthly",
        "adjustment_policy": "not_applicable",
        "minimum_evidence_grade": "factual-baseline",
        "owner_role": "fundamental-analyst",
        "source_policy": external_arguments.get(
            "source_policy", "best_available"
        ),
    }
    arguments = {
        "data_need": data_need,
        **_official_source_record_arguments(
            external_arguments, provider_query=provider_query
        ),
    }
    arguments["source_tier"] = source_tier
    receipt = {
        "receipt_id": receipt_id,
        "snapshot_id": snapshot_id,
        "dataset_id": dataset_id,
        "row_count": 1,
        "result_status": "complete_valid",
        "tool_name": tool_name,
        "requested_provider": source_id,
        "returned_provider": source_id,
        "upstream_provider": source_id,
    }
    return _mcp(
        "record_external_data_result",
        arguments,
        _ok(
            {
                "status": "recorded",
                "receipt_id": receipt_id,
                "snapshot_id": snapshot_id,
                "dataset_id": dataset_id,
                "receipt": receipt,
            }
        ),
    )


def _official_source_failure_pair(
    external_arguments: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    source_id = str(external_arguments.get("source_id") or "bls-v1")
    tool_name = "mcp__tradingcodex__fetch_official_source_data"
    provider_query = {
        "provider": source_id,
        "identifiers": list(external_arguments["identifiers"]),
        "fields": list(external_arguments.get("fields") or []),
        "period_start": external_arguments.get("period_start", ""),
        "period_end": external_arguments.get("period_end", ""),
    }
    record_arguments = {
        "source_tier": "tradingcodex",
        "transport": "tradingcodex-official",
        "requested_provider": source_id,
        "returned_provider": "",
        "upstream_provider": source_id,
        "tool_name": tool_name,
        "route": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "returned_adjustment_policy": "",
        "result_status": "terminal_gap",
        "fallback_reason": "official_fallback_exhausted:no_matching_records",
        "evidence_grade": "unusable",
        "provider_query": provider_query,
        "source_category": str(external_arguments["data_kind"]),
        "source_locator": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "timezone": "UTC",
        "coverage_note": "official_fallback_exhausted",
        "warnings": [],
        "data_classification": "public",
        "redistribution": "not_specified",
    }
    result = _ok(
        {
            "schema_version": 1,
            "status": "terminal_gap",
            "source_policy": external_arguments.get(
                "source_policy", "best_available"
            ),
            "data_kind": external_arguments["data_kind"],
            "region": external_arguments.get("region", ""),
            "selected_source_id": "",
            "attempts": [
                {
                    "source_id": source_id,
                    "result_status": "terminal_gap",
                }
            ],
            "accepted_results": [],
            "coverage_gap": "official_fallback_exhausted",
            "fallback_exhausted": True,
            "same_call_retries": 0,
            "record_external_data_result_args": record_arguments,
            "recorder_instruction": "record immediately",
        }
    )
    receipt_id = "data-acquisition-official-gap"
    data_need = {
        "run_id": "analysis-official-source",
        "data_kind": external_arguments["data_kind"],
        "asset_type": external_arguments.get("asset_class", "macro"),
        "identifiers": list(external_arguments["identifiers"]),
        "fields": list(external_arguments.get("fields") or ["value"]),
        "period_start": external_arguments.get("period_start", ""),
        "period_end": external_arguments.get("period_end", ""),
        "frequency": "monthly",
        "adjustment_policy": "not_applicable",
        "minimum_evidence_grade": "factual-baseline",
        "owner_role": "fundamental-analyst",
        "source_policy": external_arguments.get(
            "source_policy", "best_available"
        ),
    }
    promotion_arguments = {"data_need": data_need, **record_arguments}
    promotion = _mcp(
        "record_external_data_result",
        promotion_arguments,
        _ok(
            {
                "status": "recorded",
                "receipt_id": receipt_id,
                "snapshot_id": "",
                "dataset_id": "",
                "receipt": {
                    "receipt_id": receipt_id,
                    "snapshot_id": "",
                    "dataset_id": "",
                    "row_count": 0,
                    "result_status": "terminal_gap",
                    "tool_name": tool_name,
                    "requested_provider": source_id,
                    "returned_provider": "",
                    "upstream_provider": source_id,
                },
            }
        ),
    )
    return result, promotion


def _ok(value: dict[str, object]) -> dict[str, object]:
    return {"Ok": {"content": [{"type": "text", "text": json.dumps(value)}]}}


def _authenticated_artifact_write(
    artifact_id: str,
    *,
    artifact_type: str,
    path: str,
    inputs: list[str] | None = None,
    handoff_state: str = "accepted",
    response_status: str = "stored",
) -> dict[str, object]:
    return _mcp(
        "create_research_artifact",
        {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "handoff_state": handoff_state,
            "input_artifact_ids": inputs or [],
        },
        _ok(
            {
                "status": response_status,
                "artifact_id": artifact_id,
                "path": path,
                "export_path": path,
                "handoff_state": handoff_state,
                "authentication": {"status": "verified"},
            }
        ),
    )


def _artifact_receipt_message(
    artifact_id: str,
    path: str,
    *,
    handoff_state: str = "accepted",
) -> dict[str, object]:
    return {
        "type": "event_msg",
        "payload": {
            "type": "agent_message",
            "phase": "final_answer",
            "message": f"ARTIFACT {artifact_id} {path} {handoff_state}\nBounded handoff.",
        },
    }


def _structured_error(*, retryable: bool | None) -> dict[str, object]:
    value = {"error_type": "ValueError", "message": "invalid", "same_arguments_retryable": retryable}
    return {"Ok": {"isError": True, "content": [{"type": "text", "text": json.dumps(value)}]}}


def _exec_call(call_id: str, input_text: str) -> dict[str, object]:
    return {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "call_id": call_id,
            "name": "exec",
            "input": input_text,
        },
    }


def _exec_output(
    call_id: str,
    data: str,
    *,
    reference: bool = True,
    extra_blocks: list[dict[str, object]] | None = None,
    status: str = "Script completed\nWall time 0.0 seconds\nOutput:\n",
) -> dict[str, object]:
    output: list[dict[str, object]]
    if reference:
        output = [
            {"type": "input_text", "text": status},
            {"type": "input_text", "text": data},
        ]
    else:
        output = [{"type": "text", "text": data}]
    output.extend(extra_blocks or [])
    return {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": output,
        },
    }


def _artifact_wrapper_output(
    call_id: str,
    response: dict[str, object],
) -> dict[str, object]:
    outer = {
        "content": [{"type": "text", "text": json.dumps(response)}],
        "isError": False,
    }
    return _exec_output(call_id, json.dumps(outer))


def _artifact_list_wrapper_output(
    call_id: str,
    response: dict[str, object],
) -> dict[str, object]:
    outer = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(response, indent=2, ensure_ascii=False),
            }
        ],
        "isError": False,
    }
    return _exec_output(call_id, json.dumps(outer, ensure_ascii=False))


def _pathological_artifact_list_response(
    *,
    marker: object = 12_000,
) -> dict[str, object]:
    cards = [
        {
            "card_max_serialized_chars": 10_000,
            "artifact_id": f"listed-artifact-{index}",
            "content_hash": f"{index:064x}",
            "version": 1,
            "reader_summary": '"\\' * 400,
            "workflow_run_id": "run-list-wrapper",
            "producer_role": "risk-manager",
            "handoff_state": "accepted",
        }
        for index in range(3)
    ]
    return {
        "db_canonical": False,
        "file_sot": True,
        "workspace_native": True,
        "workspace_context": {},
        "artifacts": cards,
        "invalid_artifact_count": 0,
        "run_bound_authentication": {
            "status": "verified",
            "verified_artifact_count": len(cards),
        },
        "artifact_page": {
            "offset": 0,
            "requested_limit": len(cards),
            "returned_count": len(cards),
            "has_more": False,
            "response_truncated": False,
            "max_serialized_chars": marker,
        },
    }


def _audit_deferred_sequence(
    tmp_path: Path,
    child_items: list[dict[str, object]],
    *,
    include_lifecycle: bool = True,
) -> dict[str, object]:
    root_id = "root-deferred"
    child_id = "child-deferred"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _agent_message("2026-07-18T00:00:01.000Z", phase="commentary"),
            _spawn("spawn-deferred", "fundamental-analyst", task_name="fundamental"),
            _started("spawn-deferred", child_id),
            *(
                [
                    _authenticated_artifact_write(
                        "synthesis-default",
                        artifact_type="synthesis_report",
                        path="trading/reports/synthesis/synthesis-default.md",
                        inputs=["fundamental-default"],
                    )
                ]
                if include_lifecycle
                else []
            ),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            *child_items,
            *(
                [
                    _authenticated_artifact_write(
                        "fundamental-default",
                        artifact_type="fundamental_report",
                        path="trading/reports/fundamental/fundamental-default.md",
                    ),
                    _artifact_receipt_message(
                        "fundamental-default",
                        "trading/reports/fundamental/fundamental-default.md",
                    ),
                ]
                if include_lifecycle
                else []
            ),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    return audit_codex_trace(root, candidate=True)


def test_trace_audit_rejects_noop_research_lifecycle(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [],
        include_lifecycle=False,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "missing_authenticated_child_artifact",
        "missing_authenticated_root_synthesis",
        "missing_child_artifact_receipt",
    } <= codes


def test_trace_audit_detects_external_semantic_repeat_across_presentation_limits(
    tmp_path: Path,
) -> None:
    arguments = {
        "provider": "sec",
        "symbols": ["NVDA", "MSFT"],
        "fields": ["close", "volume"],
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "interval": "1d",
        "adjustment": "split",
        "limit": 78,
        "chart": False,
    }
    changed_presentation = {
        **arguments,
        "symbols": ["MSFT", "NVDA"],
        "fields": ["volume", "close"],
        "limit": 120,
        "output_format": "csv",
        "include_chart": False,
    }
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                arguments,
                _ok({"results": [{"date": "2026-01-02", "close": 1}]}),
            ),
            _external_mcp(
                "openbb",
                "equity_price_historical",
                changed_presentation,
                _ok({"results": [{"date": "2026-01-02", "close": 1}]}),
            ),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "external_semantic_repeat" in codes
    assert result["summary"]["external_mcp_calls"] == 2
    assert result["summary"]["external_exact_repeat_occurrences"] == 0
    assert result["summary"]["external_semantic_repeat_occurrences"] == 1
    external = result["sessions"][1]["external_mcp"]
    assert external["openbb"]["provider_omissions"] == 0
    assert external["semantic_repeat_occurrences"] == 1


def test_trace_audit_keeps_provider_fields_and_periods_semantically_distinct(
    tmp_path: Path,
) -> None:
    base = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "interval": "1d",
        "adjustment": "split",
        "limit": 20,
        "chart": False,
    }
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp("openbb", "equity_price_historical", base, _ok({"results": []})),
            _external_mcp(
                "openbb",
                "equity_price_historical",
                {**base, "provider": "fmp"},
                _ok({"results": []}),
            ),
            _external_mcp(
                "openbb",
                "equity_price_historical",
                {**base, "fields": ["volume"]},
                _ok({"results": []}),
            ),
            _external_mcp(
                "openbb",
                "equity_price_historical",
                {**base, "start_date": "2026-02-01", "end_date": "2026-02-28"},
                _ok({"results": []}),
            ),
        ],
    )

    assert result["summary"]["external_semantic_repeat_occurrences"] == 0
    assert "external_semantic_repeat" not in {
        item["code"] for item in result["candidate_violations"]
    }


def test_trace_audit_enforces_openbb_provider_discovery_and_read_only_contract(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "available_tools",
                {"query": "equity price"},
                _ok({"tools": ["equity_price_historical"]}),
            ),
            _external_mcp(
                "openbb",
                "available_tools",
                {"query": "macro"},
                _ok({"tools": ["economy_gdp_real"]}),
            ),
            _external_mcp(
                "openbb",
                "activate_tools",
                {"tool_names": ["a", "b", "c", "d"]},
                _ok({"status": "ok"}),
            ),
            _external_mcp(
                "openbb",
                "equity_price_historical",
                {"symbol": "NVDA", "limit": 121, "chart": True},
                _ok({"results": []}),
            ),
            _external_mcp(
                "openbb",
                "install_skill",
                {"name": "remote-skill"},
                _ok({"status": "installed"}),
            ),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "openbb_forbidden_tool",
        "openbb_overbroad_activation",
        "openbb_provider_omitted",
        "openbb_repeated_discovery",
        "openbb_unbounded_result_request",
    } <= codes
    openbb = result["sessions"][1]["external_mcp"]["openbb"]
    assert {
        key: value
        for key, value in openbb.items()
        if key != "admin_scope_fingerprints"
    } == {
        "provider_omissions": 1,
        "forbidden_calls": 1,
        "discovery_calls": 2,
        "activation_calls": 1,
        "overbroad_activations": 1,
        "row_or_page_limit_violations": 1,
        "chart_calls": 1,
        "role_violations": 0,
    }
    assert len(openbb["admin_scope_fingerprints"]) == 2


def test_trace_audit_scopes_openbb_admin_calls_by_category_and_subcategory(
    tmp_path: Path,
) -> None:
    distinct = _audit_deferred_sequence(
        tmp_path / "distinct",
        [
            _external_mcp(
                "openbb",
                "available_tools",
                {"category": "equity", "subcategory": "price"},
                _ok({"tools": ["equity_price_historical"]}),
            ),
            _external_mcp(
                "openbb",
                "available_tools",
                {"category": "economy", "subcategory": "macro"},
                _ok({"tools": ["economy_gdp_real"]}),
            ),
        ],
    )
    distinct_codes = {
        item["code"] for item in distinct["candidate_violations"]
    }
    assert "openbb_repeated_discovery" not in distinct_codes
    assert distinct["summary"]["openbb_discovery_calls"] == 2
    assert distinct["summary"]["openbb_repeated_admin_scope_occurrences"] == 0

    repeated = _audit_deferred_sequence(
        tmp_path / "repeated",
        [
            _external_mcp(
                "openbb",
                "available_tools",
                {"category": "equity", "subcategory": "price"},
                _ok({"tools": ["equity_price_historical"]}),
            ),
            _external_mcp(
                "openbb",
                "available_tools",
                {"category": "EQUITY", "sub_category": "PRICE"},
                _ok({"tools": ["equity_price_historical"]}),
            ),
        ],
    )
    repeated_codes = {
        item["code"] for item in repeated["candidate_violations"]
    }
    assert "openbb_repeated_discovery" in repeated_codes
    assert repeated["summary"]["openbb_repeated_admin_scope_occurrences"] == 1


def test_trace_audit_accepts_one_bounded_provider_explicit_openbb_call(
    tmp_path: Path,
) -> None:
    arguments = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "interval": "1d",
        "adjustment": "unadjusted",
        "limit": 20,
        "chart": False,
    }
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                arguments,
                _ok({"results": [{"date": "2026-01-02", "close": 1}]}),
            ),
            _external_promotion(
                "openbb", "equity_price_historical", arguments
            ),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_mcp_calls"] == 1
    assert result["summary"]["external_semantic_repeat_occurrences"] == 0
    assert result["summary"]["external_dataset_promotions"] == 1
    assert result["summary"]["external_unpromoted_results"] == 0


def test_trace_audit_promotes_only_the_exact_official_source_producer(
    tmp_path: Path,
) -> None:
    arguments = {
        "data_kind": "labor",
        "asset_class": "macro",
        "region": "US",
        "source_id": "bls-v1",
        "source_policy": "preferred",
        "identifiers": ["LNS14000000"],
        "fields": ["value"],
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
    }
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "tradingcodex",
                "get_official_source_plan",
                {"data_kind": "labor", "region": "US"},
                _ok({"candidates": [{"source_id": "bls-v1"}]}),
            ),
            _external_mcp(
                "tradingcodex",
                "fetch_official_source_data",
                arguments,
                _official_source_result(arguments),
            ),
            _official_source_promotion(arguments),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_mcp_calls"] == 1
    assert result["summary"]["external_dataset_promotions"] == 1
    assert result["summary"]["external_unpromoted_results"] == 0
    assert result["sessions"][1]["external_mcp"]["by_tool"] == {
        "tradingcodex::fetch_official_source_data": 1
    }


def test_trace_audit_accepts_official_source_typed_failure_template(
    tmp_path: Path,
) -> None:
    arguments = {
        "data_kind": "labor",
        "asset_class": "macro",
        "region": "US",
        "source_id": "bls-v1",
        "source_policy": "preferred",
        "identifiers": ["LNS14000000"],
        "fields": ["value"],
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
    }
    source_result, promotion = _official_source_failure_pair(arguments)
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "tradingcodex",
                "fetch_official_source_data",
                arguments,
                source_result,
            ),
            promotion,
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_receipt_only_failures"] == 1
    assert result["summary"]["external_unpromoted_results"] == 0


def test_trace_audit_accepts_corrected_local_date_official_price_gap(
    tmp_path: Path,
) -> None:
    arguments = {
        "data_kind": "equity_price",
        "asset_class": "equity",
        "region": "KR",
        "source_id": "data-go-kr-fsc-stock-price",
        "source_policy": "best_available",
        "identifiers": ["KRX 000660", "KRX 005930"],
        "fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "period_start": "2026-07-14",
        "period_end": "2026-07-16",
    }
    source_result, promotion = _official_source_failure_pair(arguments)
    promotion_payload = promotion["payload"]
    assert isinstance(promotion_payload, dict)
    invocation = promotion_payload["invocation"]
    assert isinstance(invocation, dict)
    promotion_arguments = invocation["arguments"]
    assert isinstance(promotion_arguments, dict)
    data_need = promotion_arguments["data_need"]
    assert isinstance(data_need, dict)

    invalid_arguments = {
        **promotion_arguments,
        "data_need": {
            **data_need,
            "period_start": "2026-07-14",
            "period_end": "2026-07-16",
            "adjustment_policy": "unadjusted",
        },
    }
    promotion_arguments["data_need"] = {
        **data_need,
        "period_start": "2026-07-14T00:00:00+09:00",
        "period_end": "2026-07-16T23:59:59+09:00",
        "adjustment_policy": "unadjusted",
    }
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "tradingcodex",
                "fetch_official_source_data",
                arguments,
                source_result,
            ),
            _mcp(
                "record_external_data_result",
                invalid_arguments,
                _structured_error(retryable=False),
            ),
            promotion,
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["tradingcodex_mcp_errors"] == 1
    assert result["summary"]["external_receipt_only_failures"] == 1
    assert result["summary"]["external_unpromoted_results"] == 0
    assert result["summary"]["external_promotion_mismatches"] == 0


@pytest.mark.parametrize(
    ("mismatch", "expected_source_tier"),
    [
        ("provider_query", "tradingcodex"),
        ("source_tier", "user_capability"),
    ],
)
def test_trace_audit_rejects_mismatched_official_source_promotion(
    tmp_path: Path,
    mismatch: str,
    expected_source_tier: str,
) -> None:
    arguments = {
        "data_kind": "labor",
        "asset_class": "macro",
        "region": "US",
        "source_id": "bls-v1",
        "source_policy": "preferred",
        "identifiers": ["LNS14000000"],
        "fields": ["value"],
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
    }
    promotion_query = (
        {"series_ids": ["WRONG"], "start_year": 2026, "end_year": 2026}
        if mismatch == "provider_query"
        else None
    )
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "tradingcodex",
                "fetch_official_source_data",
                arguments,
                _official_source_result(arguments),
            ),
            _official_source_promotion(
                arguments,
                provider_query=promotion_query,
                source_tier=expected_source_tier,
            ),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "external_data_not_promoted",
        "external_data_promotion_mismatch",
    } <= codes
    assert result["summary"]["external_promotion_mismatches"] == 1


def test_trace_audit_rejects_raw_openbb_result_without_promotion(
    tmp_path: Path,
) -> None:
    arguments = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "as_of": "2026-07-17",
    }

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                arguments,
                _ok({"results": [{"date": "2026-07-17", "close": 1}]}),
            )
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "external_data_not_promoted" in codes
    assert result["summary"]["external_unpromoted_results"] == 1
    assert result["sessions"][1]["external_mcp"]["promotion"] == {
        "dataset_results": 0,
        "receipt_only_failures": 0,
        "unpromoted_results": 1,
        "invalid_receipts": 0,
        "coordinate_mismatches": 0,
        "results_before_handoff": 1,
        "calls_while_pending": 0,
    }


def test_trace_audit_accepts_receipt_only_typed_external_failure(
    tmp_path: Path,
) -> None:
    arguments = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "as_of": "2026-07-17",
    }

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                arguments,
                _structured_error(retryable=False),
            ),
            _external_promotion(
                "openbb",
                "equity_price_historical",
                arguments,
                result_status="terminal_gap",
            ),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_receipt_only_failures"] == 1
    assert result["summary"]["external_unpromoted_results"] == 0


def test_trace_audit_rejects_second_financial_call_before_first_promotion(
    tmp_path: Path,
) -> None:
    first = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "as_of": "2026-07-17",
    }
    second = {**first, "symbol": "MSFT"}

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                first,
                _ok({"results": [{"symbol": "NVDA", "close": 1}]}),
            ),
            _external_mcp(
                "openbb",
                "equity_price_historical",
                second,
                _ok({"results": [{"symbol": "MSFT", "close": 2}]}),
            ),
            _external_promotion(
                "openbb", "equity_price_historical", first
            ),
            _external_promotion(
                "openbb", "equity_price_historical", second
            ),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "external_data_promotion_not_immediate" in codes
    assert "external_data_not_promoted" not in codes
    assert result["summary"]["external_calls_while_promotion_pending"] == 1
    assert result["summary"]["external_dataset_promotions"] == 2


def test_trace_audit_accepts_promotion_between_independent_financial_calls(
    tmp_path: Path,
) -> None:
    first = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "as_of": "2026-07-17",
    }
    second = {**first, "symbol": "MSFT"}

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                first,
                _ok({"results": [{"symbol": "NVDA", "close": 1}]}),
            ),
            _external_promotion(
                "openbb", "equity_price_historical", first
            ),
            _external_mcp(
                "openbb",
                "equity_price_historical",
                second,
                _ok({"results": [{"symbol": "MSFT", "close": 2}]}),
            ),
            _external_promotion(
                "openbb", "equity_price_historical", second
            ),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_calls_while_promotion_pending"] == 0
    assert result["summary"]["external_dataset_promotions"] == 2


def test_trace_audit_allows_nonfinancial_call_before_financial_promotion(
    tmp_path: Path,
) -> None:
    arguments = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "as_of": "2026-07-17",
    }

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                arguments,
                _ok({"results": [{"symbol": "NVDA", "close": 1}]}),
            ),
            _external_mcp(
                "notion",
                "search_pages",
                {"query": "NVDA research"},
                _ok({"pages": []}),
            ),
            _external_promotion(
                "openbb", "equity_price_historical", arguments
            ),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_mcp_calls"] == 1
    assert result["summary"]["external_calls_while_promotion_pending"] == 0


def test_trace_audit_normalizes_financial_semantic_coordinate_aliases(
    tmp_path: Path,
) -> None:
    first = {
        "provider": "SEC",
        "series_id": "GDP",
        "fields": "VALUE",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "interval": "1d",
        "adjusted": False,
    }
    equivalent = {
        "provider_name": "sec",
        "series_id": ["gdp"],
        "columns": ["value"],
        "date_from": "2026-01-01T00:00:00Z",
        "date_to": "2026-01-31T00:00:00+00:00",
        "frequency": "DAILY",
        "adjustment": "raw",
    }

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb", "economy_series", first, _ok({"results": [{"value": 1}]})
            ),
            _external_promotion("openbb", "economy_series", first),
            _external_mcp(
                "openbb",
                "economy_series",
                equivalent,
                _ok({"results": [{"value": 1}]}),
            ),
            _external_promotion("openbb", "economy_series", equivalent),
        ],
    )

    assert "external_semantic_repeat" in {
        item["code"] for item in result["candidate_violations"]
    }
    assert result["summary"]["external_semantic_repeat_occurrences"] == 1
    assert result["summary"]["external_calls_while_promotion_pending"] == 0


@pytest.mark.parametrize("identifier_key", ["series_id", "contract"])
def test_trace_audit_keeps_distinct_series_and_contract_identifiers_separate(
    tmp_path: Path,
    identifier_key: str,
) -> None:
    first = {
        "provider": "sec",
        identifier_key: "FIRST",
        "fields": ["value"],
        "as_of": "2026-07-17",
    }
    second = {**first, identifier_key: "SECOND"}

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb", "economy_series", first, _ok({"results": [{"value": 1}]})
            ),
            _external_promotion("openbb", "economy_series", first),
            _external_mcp(
                "openbb", "economy_series", second, _ok({"results": [{"value": 2}]})
            ),
            _external_promotion("openbb", "economy_series", second),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_semantic_repeat_occurrences"] == 0


@pytest.mark.parametrize(
    ("tool_name", "requested_provider"),
    [
        ("mcp__openbb__economy_gdp", None),
        (None, "fmp"),
    ],
)
def test_trace_audit_rejects_external_promotion_coordinate_mismatch(
    tmp_path: Path,
    tool_name: str | None,
    requested_provider: str | None,
) -> None:
    arguments = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
    }

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                arguments,
                _ok({"results": [{"date": "2026-01-02", "close": 1}]}),
            ),
            _external_promotion(
                "openbb",
                "equity_price_historical",
                arguments,
                tool_name=tool_name,
                requested_provider=requested_provider,
            ),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "external_data_not_promoted",
        "external_data_promotion_mismatch",
    } <= codes
    assert result["summary"]["external_promotion_mismatches"] == 1


def test_trace_audit_rejects_external_promotion_after_artifact_handoff(
    tmp_path: Path,
) -> None:
    arguments = {
        "provider": "sec",
        "symbol": "NVDA",
        "fields": ["close"],
        "as_of": "2026-07-17",
    }

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "openbb",
                "equity_price_historical",
                arguments,
                _ok({"results": [{"date": "2026-07-17", "close": 1}]}),
            ),
            _authenticated_artifact_write(
                "premature-artifact",
                artifact_type="fundamental_report",
                path="trading/reports/fundamental/premature-artifact.md",
            ),
            _external_promotion(
                "openbb", "equity_price_historical", arguments
            ),
        ],
    )

    assert "external_data_not_promoted" in {
        item["code"] for item in result["candidate_violations"]
    }
    assert result["summary"]["external_unpromoted_results"] == 0
    assert result["sessions"][1]["external_mcp"]["promotion"][
        "results_before_handoff"
    ] == 1


def test_trace_audit_ignores_repeated_nonfinancial_connector_mcp_calls(
    tmp_path: Path,
) -> None:
    repeated = _external_mcp(
        "gmail",
        "search_messages",
        {"query": "NVDA earnings", "max_results": 10},
        _ok({"messages": [{"subject": "NVDA earnings"}]}),
    )

    result = _audit_deferred_sequence(tmp_path, [repeated, repeated])

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["external_mcp_calls"] == 0
    assert result["summary"]["external_semantic_repeat_occurrences"] == 0
    assert result["summary"]["external_unpromoted_results"] == 0


def test_trace_audit_rejects_raw_user_financial_mcp_result(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "user-market-feed",
                "private_quote_tool",
                {"provider": "licensed-feed", "symbol": "NVDA"},
                _ok({"symbol": "NVDA", "price": 200}),
            )
        ],
    )

    assert "external_data_not_promoted" in {
        item["code"] for item in result["candidate_violations"]
    }
    assert result["summary"]["external_mcp_calls"] == 1


def test_trace_audit_exports_only_redacted_external_mcp_metadata(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _external_mcp(
                "user-private-feed",
                "private_quote_tool",
                {
                    "symbol": "SECRET-SYMBOL",
                    "authorization": "Bearer top-secret-token",
                },
                _ok({"private_payload": "TOP-SECRET-RESULT"}),
            )
        ],
    )

    exported = json.dumps(result, ensure_ascii=False)
    assert "user-private-feed" not in exported
    assert "private_quote_tool" not in exported
    assert "SECRET-SYMBOL" not in exported
    assert "top-secret-token" not in exported
    assert "TOP-SECRET-RESULT" not in exported
    assert result["summary"]["external_mcp_calls"] == 1


def test_trace_audit_rejects_receipt_not_matching_authenticated_write(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _authenticated_artifact_write(
                "fundamental-mismatch",
                artifact_type="fundamental_report",
                path="trading/reports/fundamental/fundamental-mismatch.md",
            ),
            _artifact_receipt_message(
                "fundamental-mismatch",
                "trading/reports/fundamental/different-path.md",
            ),
        ],
        include_lifecycle=False,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "mismatched_child_artifact_receipt" in codes
    assert "missing_authenticated_child_artifact" not in codes
    assert "missing_child_artifact_receipt" not in codes


def test_trace_audit_rejects_nonterminal_artifact_write_response(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _authenticated_artifact_write(
                "fundamental-error",
                artifact_type="fundamental_report",
                path="trading/reports/fundamental/fundamental-error.md",
                response_status="error",
            ),
            _artifact_receipt_message(
                "fundamental-error",
                "trading/reports/fundamental/fundamental-error.md",
            ),
        ],
        include_lifecycle=False,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "missing_authenticated_child_artifact" in codes
    assert "mismatched_child_artifact_receipt" in codes


def test_trace_audit_rejects_nonaccepted_child_artifact(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _authenticated_artifact_write(
                "fundamental-rejected",
                artifact_type="fundamental_report",
                path="trading/reports/fundamental/fundamental-rejected.md",
                handoff_state="revise",
            ),
            _artifact_receipt_message(
                "fundamental-rejected",
                "trading/reports/fundamental/fundamental-rejected.md",
                handoff_state="revise",
            ),
        ],
        include_lifecycle=False,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "nonaccepted_child_artifact" in codes
    assert "missing_authenticated_child_artifact" not in codes
    assert "mismatched_child_artifact_receipt" not in codes


def test_trace_audit_reproduces_efficiency_failures_without_private_content(tmp_path: Path) -> None:
    root_id = "root-session"
    child_id = "child-session"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    artifact = {
        "artifact_id": "fundamental-report-1",
        "version": 1,
        "content_hash": "hash-1",
        "markdown": "evidence",
    }
    duplicate_args = {"artifact_id": "fundamental-report-1", "include_markdown": True}
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("spawn-1", "fundamental-analyst"),
            _started("spawn-1", child_id),
            {
                "type": "response_item",
                "payload": {"type": "reasoning", "summary": "DO-NOT-EXPORT-PRIVATE-REASONING"},
            },
            _token(50, 40, 5, last_input=40),
            _token(100, 80, 10, last_input=90, include_cache_write=False),
            _complete(70_000),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "catalog-call",
                    "name": "exec",
                    "input": "text(ALL_TOOLS.map(x => x.name))",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "mixed-call",
                    "name": "exec",
                    "input": "text(ALL_TOOLS); tools.mcp__tradingcodex__get_research_artifact({})",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "mixed-call",
                    "output": [{"type": "text", "text": "Warning: truncated output (original token count: 20,000)"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "lexical-bypass",
                    "name": "exec",
                    "input": "const ignored = [].slice(0, 12).map(x => x.name); text(ALL_TOOLS.map(x => x.name).join('\\n'))",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "lexical-bypass",
                    "output": [{"type": "text", "text": "tool_a\\ntool_b"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "catalog-call",
                    "output": [
                        {
                            "type": "text",
                            "text": "Warning: truncated output (original token count: 12,345) …2,345 tokens truncated…",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "bracket-artifact-call",
                    "name": "exec",
                    "input": "tools['mcp__tradingcodex__get_research_artifact']({artifact_id: 'unobserved-a'})",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "bracket-artifact-call",
                    "output": [{"type": "text", "text": "x" * 50_000}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "artifact-a-call",
                    "name": "exec",
                    "input": "tools.mcp__tradingcodex__get_research_artifact({artifact_id: 'artifact-a'})",
                },
            },
            _mcp(
                "get_research_artifact",
                {"artifact_id": "artifact-b", "detail_level": "card"},
                _ok(
                        {
                            "artifact_id": "artifact-b",
                            "version": 1,
                            "content_hash": "artifact-b-hash",
                            "card_max_serialized_chars": 10_000,
                        }
                ),
            ),
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "artifact-a-call",
                    "output": [{"type": "text", "text": "unobserved artifact A"}],
                },
            },
            _mcp("get_research_artifact", duplicate_args, _ok(artifact)),
            _mcp("get_research_artifact", duplicate_args, _ok(artifact)),
            _mcp(
                "get_research_artifact",
                {
                    "artifact_id": "extra-blocks",
                    "detail_level": "review",
                    "markdown_start": 0,
                    "markdown_max_chars": 8,
                },
                {
                    "Ok": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "artifact_id": "extra-blocks",
                                        "markdown": "evidence",
                                        "markdown_window": {
                                            "start": 0,
                                            "end": 8,
                                            "total_chars": 8,
                                            "has_more": False,
                                            "next_start": None,
                                        },
                                    }
                                ),
                            },
                            {"type": "text", "text": "y" * 50_000},
                        ]
                    }
                },
            ),
            _mcp("search_datasets", {"query": "malformed"}, {"Ok": "RUNTIME FAILURE"}),
            _mcp("record_dataset_snapshot", {"columns": [{"type": "date"}]}, _structured_error(retryable=False)),
            _mcp("record_dataset_snapshot", {"columns": [{"type": "date32"}]}, _ok({"status": "stored"})),
            _token(200, 150, 20, last_input=160),
            _complete(),
        ],
    )
    _write_jsonl(
        tmp_path / "orphan.jsonl",
        [_session_meta("orphan", parent_id=root_id, base=CHILD_BASE)],
    )

    discovered = discover_rollouts(root)
    assert [meta["id"] for _, meta in discovered] == [root_id, child_id]

    result = audit_codex_trace(root, candidate=True)
    serialized = json.dumps(result)
    assert "DO-NOT-EXPORT-PRIVATE-REASONING" not in serialized
    assert result["scope"] == {
        "session_count": 2,
        "subagent_count": 1,
        "max_depth": 1,
        "roles": {"fundamental-analyst": 1, "head-manager": 1},
        "declared_subagent_count": 1,
        "missing_subagent_rollout_ids": [],
        "unstarted_descendant_ids": [],
    }
    assert result["summary"]["tradingcodex_mcp_calls"] == 7
    assert result["summary"]["exact_repeat_occurrences"] == 1
    assert result["summary"]["artifact_read_repeat_occurrences"] == 1
    assert result["summary"]["unbounded_artifact_reads"] == 3
    assert result["summary"]["oversized_custom_outputs"] == 1
    assert result["summary"]["unbounded_catalog_queries"] == 3
    assert result["aggregate_final_token_usage"]["input_tokens"] == 300
    assert result["max_observed_session"]["last_input_tokens"] == 160
    assert result["privacy"]["private_reasoning_analyzed"] is False
    retry_analysis = result["sessions"][1]["tradingcodex_mcp"]["retry_analysis"]
    assert retry_analysis["corrected_successes"] == 1
    assert retry_analysis["blind_deterministic_retries"] == 0
    assert retry_analysis["transitions"][0]["changed_path_count"] == 1
    assert retry_analysis["transitions"][0]["changed_paths_fingerprint"]
    assert "columns" not in serialized
    violation_codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "artifact_window_repeat",
        "broad_tool_catalog_scan",
        "consecutive_deterministic_repeat",
        "missing_progress_update",
        "oversized_custom_output",
        "truncated_tool_catalog",
        "unbounded_artifact_read",
    } <= violation_codes


def test_trace_audit_candidate_passes_complete_compact_contract(tmp_path: Path) -> None:
    root_id = "root-pass"
    child_id = "child-pass"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _agent_message("2026-07-18T00:00:01.000Z", phase="commentary"),
            _spawn("spawn-pass", "fundamental-analyst"),
            _started("spawn-pass", child_id),
            _authenticated_artifact_write(
                "synthesis-pass",
                artifact_type="synthesis_report",
                path="trading/reports/synthesis/synthesis-pass.md",
                inputs=["fundamental-pass"],
            ),
            _token(100, 80, 10, last_input=90, include_cache_write=False),
            _complete(20_000),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "bounded-catalog",
                    "name": "exec",
                    "input": "text(ALL_TOOLS.filter(x => x.name.includes(\"begin_analysis_run\")).slice(0, 12).map(x => x.name))\n",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "bounded-catalog",
                    "output": [
                        {
                            "type": "input_text",
                            "text": "Script completed\nWall time 0.0 seconds\nOutput:\n",
                        },
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                ["mcp__tradingcodex__begin_analysis_run"]
                            ),
                        },
                    ],
                },
            },
            _exec_call(
                "schema-begin-analysis",
                'const t = ALL_TOOLS.find(x => x.name === "mcp__tradingcodex__begin_analysis_run"); text(t ? t.description : "missing")\n',
            ),
            _exec_output(
                "schema-begin-analysis",
                "PRIVATE SCHEMA BODY\n\nexec tool declaration:\n```ts\ndeclare const tools: unknown;\n```",
            ),
            _mcp("create_research_artifact", {"title": "bounded"}, _ok({"artifact_id": "fundamental-1"})),
            _mcp(
                "get_research_artifact",
                {"artifact_id": "card-1", "detail_level": "card"},
                    _ok(
                        {
                            "artifact_id": "card-1",
                            "version": 1,
                            "content_hash": "card-hash",
                            "card_max_serialized_chars": 10_000,
                        }
                    ),
            ),
            _mcp(
                "get_research_artifact",
                {
                    "artifact_id": "review-metadata-1",
                    "detail_level": "review",
                    "include_markdown": False,
                },
                _ok(
                    {
                            "artifact_id": "review-metadata-1",
                            "version": 1,
                            "content_hash": "review-metadata-hash",
                            "review_max_serialized_chars": 18_000,
                    }
                ),
            ),
            _mcp(
                "get_research_artifact",
                {
                    "artifact_id": "review-window-1",
                    "detail_level": "review",
                    "markdown_start": 0,
                    "markdown_max_chars": 12,
                },
                _ok(
                    {
                            "artifact_id": "review-window-1",
                            "version": 1,
                            "content_hash": "review-window-hash",
                            "review_max_serialized_chars": 18_000,
                        "markdown": "evidence",
                        "markdown_window": {
                            "start": 0,
                            "end": 8,
                            "total_chars": 8,
                            "has_more": False,
                            "next_start": None,
                        },
                    }
                ),
            ),
            _mcp(
                "record_audit_event",
                {"event_type": "repeatable", "message": "append"},
                _ok({"status": "recorded"}),
            ),
            _mcp(
                "record_audit_event",
                {"event_type": "repeatable", "message": "append"},
                _ok({"status": "recorded"}),
            ),
            _mcp(
                "get_research_artifact",
                {"artifact_id": "stateful-1", "detail_level": "card"},
                _structured_error(retryable=False),
            ),
            _mcp(
                "create_research_artifact",
                {"title": "stateful"},
                _ok({"artifact_id": "stateful-1"}),
            ),
            _mcp(
                "get_research_artifact",
                {"artifact_id": "stateful-1", "detail_level": "card"},
                _ok(
                    {
                            "artifact_id": "stateful-1",
                            "version": 1,
                            "content_hash": "stateful-hash",
                            "card_max_serialized_chars": 10_000,
                    }
                ),
            ),
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "inert-artifact-example",
                    "name": "exec",
                    "input": "const example='get_research_artifact'; text('no call')",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "inert-artifact-example",
                    "output": [{"type": "text", "text": "no call"}],
                },
            },
            _authenticated_artifact_write(
                "fundamental-pass",
                artifact_type="fundamental_report",
                path="trading/reports/fundamental/fundamental-pass.md",
            ),
            _artifact_receipt_message(
                "fundamental-pass",
                "trading/reports/fundamental/fundamental-pass.md",
            ),
            _token(200, 150, 20, last_input=160),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    assert result["status"] == "pass", result["candidate_violations"]
    assert result["candidate_violations"] == []
    assert result["summary"]["names_only_queries"] == 1
    assert result["summary"]["valid_names_only_results"] == 1
    assert result["summary"]["schema_lookup_queries"] == 1
    assert result["summary"]["valid_schema_lookups"] == 1
    assert "PRIVATE SCHEMA BODY" not in json.dumps(result)
    assert result["summary"]["created_artifact_ids"] == [
        "fundamental-1",
        "fundamental-pass",
        "stateful-1",
        "synthesis-pass",
    ]
    assert result["summary"]["authenticated_artifact_writes"] == 2
    assert result["summary"]["matched_child_artifact_receipts"] == 1
    assert result["summary"]["authenticated_root_syntheses"] == 1
    assert result["summary"]["root_first_progress_latency_ms"] is None
    assert result["summary"]["root_max_visible_silence_ms"] is None
    assert result["summary"]["wait_agent_calls"] == 0
    assert result["summary"]["wait_timeouts_outside_contract"] == 0
    assert result["summary"]["chained_waits_without_progress"] == 0


def test_trace_audit_measures_visible_cadence_and_excludes_final_answer(
    tmp_path: Path,
) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:00:20.000Z", phase="commentary"),
            _agent_message("2026-07-18T00:00:50.000Z", phase="commentary"),
            _agent_message("2026-07-18T00:01:10.000Z", phase="final_answer"),
        ],
        duration_ms=71_000,
    )

    assert result["status"] == "pass", result["candidate_violations"]
    root = result["sessions"][0]
    assert root["visible_progress_messages"] == 2
    assert root["first_progress_latency_ms"] == 20_000
    assert root["max_visible_silence_ms"] == 30_000
    assert result["summary"]["root_first_progress_latency_ms"] == 20_000
    assert result["summary"]["root_max_visible_silence_ms"] == 30_000
    assert "PRIVATE" not in json.dumps(result)


def test_trace_audit_accepts_bounded_waits_separated_by_visible_progress(
    tmp_path: Path,
) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:00:05.000Z", phase="commentary"),
            _wait_agent("wait-one", MAX_WAIT_TIMEOUT_MS),
            _agent_message("2026-07-18T00:00:25.000Z", phase="commentary"),
            _wait_agent("wait-two", MIN_WAIT_TIMEOUT_MS),
            _agent_message("2026-07-18T00:00:50.000Z", phase="final_answer"),
        ],
        duration_ms=51_000,
    )

    assert result["status"] == "pass", result["candidate_violations"]
    root_wait = result["sessions"][0]["wait_agent"]
    assert root_wait == {
        "calls": 2,
        "timeouts_outside_contract": 0,
        "chained_without_progress": 0,
    }
    assert result["summary"]["wait_agent_calls"] == 2
    assert result["summary"]["wait_timeouts_outside_contract"] == 0
    assert result["summary"]["chained_waits_without_progress"] == 0


def test_trace_audit_rejects_out_of_range_and_chained_waits(
    tmp_path: Path,
) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:00:05.000Z", phase="commentary"),
            _wait_agent("wait-too-long", MAX_WAIT_TIMEOUT_MS + 1),
            _wait_agent("wait-too-short", MIN_WAIT_TIMEOUT_MS - 1),
            _agent_message("2026-07-18T00:00:50.000Z", phase="final_answer"),
        ],
        duration_ms=51_000,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {"invalid_wait_timeout", "chained_wait_without_progress"} <= codes
    root_wait = result["sessions"][0]["wait_agent"]
    assert root_wait == {
        "calls": 2,
        "timeouts_outside_contract": 2,
        "chained_without_progress": 1,
    }
    assert result["summary"]["wait_agent_calls"] == 2
    assert result["summary"]["wait_timeouts_outside_contract"] == 2
    assert result["summary"]["chained_waits_without_progress"] == 1


def test_trace_audit_rejects_wait_without_explicit_timeout(tmp_path: Path) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:00:05.000Z", phase="commentary"),
            _wait_agent("wait-missing-timeout", None),
            _agent_message("2026-07-18T00:00:50.000Z", phase="final_answer"),
        ],
        duration_ms=51_000,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "invalid_wait_timeout" in codes
    assert result["sessions"][0]["wait_agent"] == {
        "calls": 1,
        "timeouts_outside_contract": 1,
        "chained_without_progress": 0,
    }


def test_trace_audit_rejects_late_first_visible_progress(tmp_path: Path) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:01:00.001Z", phase="commentary"),
            _agent_message("2026-07-18T00:01:10.000Z", phase="final_answer"),
        ],
        duration_ms=71_000,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "late_first_progress_update",
        "visible_progress_silence_exceeded",
    } <= codes
    assert (
        result["sessions"][0]["first_progress_latency_ms"]
        == MAX_FIRST_PROGRESS_LATENCY_MS + 1
    )
    assert (
        result["sessions"][0]["max_visible_silence_ms"]
        == MAX_VISIBLE_SILENCE_MS + 1
    )


def test_trace_audit_rejects_long_visible_silence_after_timely_progress(
    tmp_path: Path,
) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:00:30.000Z", phase="commentary"),
            _agent_message("2026-07-18T00:01:30.001Z", phase="commentary"),
            _agent_message("2026-07-18T00:01:50.000Z", phase="final_answer"),
        ],
        duration_ms=111_000,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "late_first_progress_update" not in codes
    assert "visible_progress_silence_exceeded" in codes
    assert result["sessions"][0]["first_progress_latency_ms"] == 30_000
    assert result["sessions"][0]["max_visible_silence_ms"] == 60_001


def test_trace_audit_detects_provable_live_silence_from_latest_event(
    tmp_path: Path,
) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:00:10.000Z", phase="commentary"),
            _at(
                {"type": "event_msg", "payload": {"type": "agent_reasoning"}},
                "2026-07-18T00:01:10.001Z",
            ),
        ],
        duration_ms=None,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {"incomplete_rollout", "visible_progress_silence_exceeded"} <= codes
    assert result["sessions"][0]["first_progress_latency_ms"] == 10_000
    assert result["sessions"][0]["max_visible_silence_ms"] == 60_001


def test_trace_audit_does_not_infer_cadence_from_missing_progress_timestamp(
    tmp_path: Path,
) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message(None, phase="commentary"),
            _agent_message("2026-07-18T00:02:00.000Z", phase="final_answer"),
        ],
        duration_ms=121_000,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "late_first_progress_update" not in codes
    assert "visible_progress_silence_exceeded" not in codes
    assert "missing_progress_update" not in codes
    assert "unverifiable_progress_cadence" in codes
    assert result["sessions"][0]["first_progress_latency_ms"] is None
    assert result["sessions"][0]["max_visible_silence_ms"] is None


def test_trace_audit_rejects_initial_progress_after_first_spawn(
    tmp_path: Path,
) -> None:
    result = _audit_root_cadence(
        tmp_path,
        [
            _task_started("2026-07-18T00:00:00.000Z"),
            _agent_message("2026-07-18T00:00:20.000Z", phase="commentary"),
            _agent_message("2026-07-18T00:01:00.000Z", phase="final_answer"),
        ],
        duration_ms=61_000,
        dispatch_before_progress=True,
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "initial_progress_after_spawn" in codes


def test_trace_audit_counts_nested_tool_when_custom_call_is_first_event(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("first-custom", "const r = await tools.web__run({}); text(r);"),
            _exec_output("first-custom", "bounded"),
        ],
    )

    assert result["sessions"][1]["nested_tools"] == {"web__run": 1}


def test_trace_audit_hashes_unknown_syntactically_valid_tcx_tool_name(
    tmp_path: Path,
) -> None:
    private_tool_name = "secretlikeidentifier"
    result = _audit_deferred_sequence(
        tmp_path,
        [_mcp(private_tool_name, {}, _ok({"status": "ok"}))],
    )

    serialized = json.dumps(result)
    assert private_tool_name not in serialized
    assert any(
        tool.startswith("invalid-sha256:")
        for tool in result["sessions"][1]["tradingcodex_mcp"]["by_tool"]
    )


@pytest.mark.parametrize(
    "tool_name",
    [
        "followup_task",
        "interrupt_agent",
        "list_agents",
        "send_message",
        "spawn_agent",
        "wait_agent",
    ],
)
def test_trace_audit_rejects_child_coordination_tools(
    tmp_path: Path,
    tool_name: str,
) -> None:
    arguments = {"timeout_ms": MIN_WAIT_TIMEOUT_MS} if tool_name == "wait_agent" else {}
    result = _audit_deferred_sequence(
        tmp_path,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": tool_name,
                    "arguments": json.dumps(arguments),
                },
            }
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "child_coordination_attempt" in codes


def test_trace_audit_rejects_interleaved_deterministic_repeat_without_mutation(
    tmp_path: Path,
) -> None:
    repeated = _mcp(
        "get_research_artifact",
        {"artifact_id": "resource-a", "detail_level": "card"},
        _ok(
            {
                "artifact_id": "resource-a",
                "version": 1,
                "content_hash": "hash-a",
                "card_max_serialized_chars": 10_000,
            }
        ),
    )
    result = _audit_deferred_sequence(
        tmp_path,
        [
            repeated,
            _mcp("get_service_status", {"scope": "resource-b"}, _ok({"status": "ok"})),
            repeated,
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "deterministic_repeat_without_mutation" in codes
    assert (
        result["summary"]["deterministic_repeat_without_mutation_occurrences"]
        == 1
    )


def test_trace_audit_allows_repeat_after_successful_affecting_mutation(
    tmp_path: Path,
) -> None:
    arguments = {"artifact_id": "resource-a", "detail_level": "card"}
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _mcp(
                "get_research_artifact",
                arguments,
                _ok(
                    {
                        "artifact_id": "resource-a",
                        "version": 1,
                        "content_hash": "hash-a-1",
                        "card_max_serialized_chars": 10_000,
                    }
                ),
            ),
            _mcp(
                "create_research_artifact",
                {"artifact_id": "resource-a"},
                _ok({"artifact_id": "resource-a", "status": "updated"}),
            ),
            _mcp(
                "get_research_artifact",
                arguments,
                _ok(
                    {
                        "artifact_id": "resource-a",
                        "version": 2,
                        "content_hash": "hash-a-2",
                        "card_max_serialized_chars": 10_000,
                    }
                ),
            ),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "deterministic_repeat_without_mutation" not in codes
    assert (
        result["summary"]["deterministic_repeat_without_mutation_occurrences"]
        == 0
    )


def test_trace_audit_accepts_exact_legacy_deferred_tool_envelopes(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("names", DEFERRED_NAMES_QUERY),
            _exec_output("names", json.dumps([DEFERRED_TOOL]), reference=False),
            _exec_call("schema", DEFERRED_SCHEMA_QUERY),
            _exec_output("schema", "bounded schema declaration", reference=False),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["valid_names_only_results"] == 1
    assert result["summary"]["valid_schema_lookups"] == 1


@pytest.mark.parametrize(
    "query",
    [
        DEFERRED_COMPOUND_QUERY,
        (
            'text(ALL_TOOLS.filter(x => x.name.includes("equity_fundamental") && '
            '(x.name.includes("metrics") || x.name.includes("income") || '
            'x.name.includes("cash"))).slice(0, 12).map(tool => tool.name));'
        ),
    ],
    ids=("observed-local-or", "observed-parenthesized-mixed"),
)
def test_trace_audit_accepts_bounded_compound_names_then_exact_schema(
    tmp_path: Path,
    query: str,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("compound-names", query),
            _exec_output("compound-names", json.dumps([DEFERRED_TOOL])),
            _exec_call("compound-schema", DEFERRED_SCHEMA_QUERY),
            _exec_output("compound-schema", "bounded schema declaration"),
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["canonical_compound_catalog_queries"] == 1
    assert result["summary"]["valid_names_only_results"] == 1
    assert result["summary"]["valid_schema_lookups"] == 1
    assert result["summary"]["unresolved_schema_lookups"] == 0


def test_trace_audit_separates_safe_noncanonical_catalog_form_from_broad_scan(
    tmp_path: Path,
) -> None:
    query = (
        'let names = ALL_TOOLS.filter(x => x.name.includes("begin_analysis_run"))'
        ".slice(0, 10).map(x => x.name); text(names);"
    )
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("noncanonical-names", query),
            _exec_output("noncanonical-names", json.dumps([DEFERRED_TOOL])),
            _exec_call("noncanonical-schema", DEFERRED_SCHEMA_QUERY),
            _exec_output("noncanonical-schema", "bounded schema declaration"),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "noncanonical_tool_catalog_query" in codes
    assert "broad_tool_catalog_scan" not in codes
    assert "unresolved_tool_schema_lookup" not in codes
    assert result["summary"]["noncanonical_tool_catalog_queries"] == 1
    assert result["summary"]["valid_schema_lookups"] == 1


@pytest.mark.parametrize("detail_level", ["card", "review"])
def test_trace_audit_exempts_valid_bounded_artifact_wrapper_from_generic_size_gate(
    tmp_path: Path,
    detail_level: str,
) -> None:
    call_id = f"bounded-{detail_level}"
    if detail_level == "card":
        arguments = (
            '{artifact_id:"artifact-card",detail_level:"card",'
            "include_markdown:false}"
        )
        response: dict[str, object] = {
            "artifact_id": "artifact-card",
            "version": 1,
            "content_hash": "card-hash",
            "card_max_serialized_chars": 10_000,
            "reader_summary": '"\\' * 1_230,
        }
    else:
        markdown = '"\\' * 3_500
        arguments = (
            '{artifact_id:"artifact-review",detail_level:"review",'
            "include_markdown:true,markdown_start:0,markdown_max_chars:12000}"
        )
        response = {
            "artifact_id": "artifact-review",
            "version": 1,
            "content_hash": "review-hash",
            "review_max_serialized_chars": 18_000,
            "markdown": markdown,
            "markdown_window": {
                "start": 0,
                "end": len(markdown),
                "total_chars": len(markdown),
                "has_more": False,
                "next_start": None,
            },
        }
    call = _exec_call(
        call_id,
        "const r = await tools.mcp__tradingcodex__get_research_artifact("
        f"{arguments}); text(r);",
    )
    output = _artifact_wrapper_output(call_id, response)
    assert len(json.dumps(output)) > 20_000

    result = _audit_deferred_sequence(tmp_path, [call, output])

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["oversized_custom_outputs"] == 0
    assert result["summary"]["bounded_artifact_oversize_exemptions"] == 1


def test_trace_audit_exempts_only_transport_expansion_for_bounded_artifact_list(
    tmp_path: Path,
) -> None:
    call_id = "bounded-artifact-list"
    response = _pathological_artifact_list_response()
    output = _artifact_list_wrapper_output(call_id, response)
    inner_text = json.dumps(response, indent=2, ensure_ascii=False)
    assert len(inner_text) <= 12_000
    assert len(json.dumps(output, ensure_ascii=False)) > 20_000

    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call(
                call_id,
                "const r = await tools."
                "mcp__tradingcodex__list_research_artifacts("
                '{workflow_run_id:"run-list-wrapper",producer_role:"risk-manager",'
                'handoff_state:"accepted",detail_level:"card",limit:3}); text(r);',
            ),
            output,
        ],
    )

    assert result["status"] == "pass", result["candidate_violations"]
    assert result["summary"]["oversized_custom_outputs"] == 0
    assert result["summary"]["bounded_artifact_oversize_exemptions"] == 1


@pytest.mark.parametrize("marker", [12_001, "12000", True, None])
def test_trace_audit_rejects_malformed_artifact_list_bound_marker(
    tmp_path: Path,
    marker: object,
) -> None:
    call_id = "malformed-artifact-list-marker"
    response = _pathological_artifact_list_response(marker=marker)
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call(
                call_id,
                "const r = await tools."
                "mcp__tradingcodex__list_research_artifacts("
                '{workflow_run_id:"run-list-wrapper",producer_role:"risk-manager",'
                'handoff_state:"accepted",detail_level:"card",limit:3}); text(r);',
            ),
            _artifact_list_wrapper_output(call_id, response),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "oversized_custom_output" in codes
    assert result["summary"]["oversized_custom_outputs"] == 1
    assert result["summary"]["bounded_artifact_oversize_exemptions"] == 0


def test_trace_audit_requires_exact_research_list_tool_for_bounded_exemption(
    tmp_path: Path,
) -> None:
    call_id = "wrong-artifact-list-tool"
    response = _pathological_artifact_list_response()
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call(
                call_id,
                "const r = await tools."
                "mcp__tradingcodex__list_workflow_artifacts("
                '{workflow_run_id:"run-list-wrapper",producer_role:"risk-manager",'
                'handoff_state:"accepted",detail_level:"card",limit:3}); text(r);',
            ),
            _artifact_list_wrapper_output(call_id, response),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "oversized_custom_output" in codes
    assert result["summary"]["bounded_artifact_oversize_exemptions"] == 0


@pytest.mark.parametrize(
    ("detail_level", "bound_field", "bound"),
    [
        ("card", "card_max_serialized_chars", 10_000),
        ("review", "review_max_serialized_chars", 18_000),
    ],
)
def test_trace_audit_rejects_artifact_wrapper_above_service_response_bound(
    tmp_path: Path,
    detail_level: str,
    bound_field: str,
    bound: int,
) -> None:
    call_id = f"oversized-{detail_level}"
    response: dict[str, object] = {
        "artifact_id": f"artifact-{detail_level}",
        "version": 1,
        "content_hash": f"{detail_level}-hash",
        bound_field: bound,
        "reader_summary": "x" * 25_000,
    }
    arguments = (
        f'{{artifact_id:"artifact-{detail_level}",detail_level:"{detail_level}",'
        "include_markdown:false}"
    )
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call(
                call_id,
                "const r = await tools.mcp__tradingcodex__get_research_artifact("
                f"{arguments}); text(r);",
            ),
            _artifact_wrapper_output(call_id, response),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "oversized_custom_output" in codes
    assert result["summary"]["oversized_custom_outputs"] == 1
    assert result["summary"]["bounded_artifact_oversize_exemptions"] == 0


@pytest.mark.parametrize(
    "input_text",
    [
        "const r = await tools.web__run({}); text(r);",
        'const r = await tools.shell_command({"command":"bounded"}); text(r);',
        (
            "const r = await tools.mcp__tradingcodex__list_workflow_artifacts({}); "
            "text(r);"
        ),
        (
            "const r = await tools.mcp__tradingcodex__get_research_artifact("
            '{artifact_id:"artifact-review",detail_level:"review",'
            "include_markdown:true,markdown_start:0,markdown_max_chars:12001}); "
            "text(r);"
        ),
    ],
    ids=("web", "shell", "workflow-list", "unbounded-artifact"),
)
def test_trace_audit_keeps_nonartifact_and_unbounded_wrapper_size_gate(
    tmp_path: Path,
    input_text: str,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("bulk-output", input_text),
            _exec_output("bulk-output", "x" * 20_001),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "oversized_custom_output" in codes
    assert result["summary"]["oversized_custom_outputs"] == 1
    assert result["summary"]["bounded_artifact_oversize_exemptions"] == 0


def test_trace_audit_does_not_exempt_valid_looking_unbounded_artifact_window(
    tmp_path: Path,
) -> None:
    markdown = '"\n\\' * 4_000
    call_id = "unbounded-artifact-window"
    call = _exec_call(
        call_id,
        "const r = await tools.mcp__tradingcodex__get_research_artifact("
        '{artifact_id:"artifact-review",detail_level:"review",'
        "include_markdown:true,markdown_start:0,markdown_max_chars:12001}); "
        "text(r);",
    )
    output = _artifact_wrapper_output(
        call_id,
        {
            "artifact_id": "artifact-review",
            "version": 1,
            "content_hash": "review-hash",
            "markdown": markdown,
            "markdown_window": {
                "start": 0,
                "end": 12_000,
                "total_chars": 12_000,
                "has_more": False,
                "next_start": None,
            },
        },
    )
    result = _audit_deferred_sequence(tmp_path, [call, output])

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "oversized_custom_output" in codes
    assert result["summary"]["oversized_custom_outputs"] == 1
    assert result["summary"]["bounded_artifact_oversize_exemptions"] == 0


@pytest.mark.parametrize(
    ("query", "description_scan"),
    [
        ("text(ALL_TOOLS.slice(0, 12).map(x => x.description))", True),
        (
            "text(ALL_TOOLS.filter(x => /analysis/i.test(x.name + ' ' + x.description)).slice(0, 12).map(x => x.name))",
            True,
        ),
        ("text(ALL_TOOLS)", False),
        (
            'text(ALL_TOOLS.filter(x => x.name.includes("a") || '
            'x.name.includes("b") || x.name.includes("c") || '
            'x.name.includes("d") || x.name.includes("e"))'
            ".slice(0, 12).map(x => x.name))",
            False,
        ),
        (
            'text(ALL_TOOLS.filter(x => x.name.includes(fragment))'
            ".slice(0, 12).map(x => x.name))",
            False,
        ),
        (
            'text(ALL_TOOLS.filter(x => x.name.includes("analysis"))'
            ".slice(0, 12).map(x => x))",
            False,
        ),
    ],
    ids=(
        "description-map",
        "description-search",
        "full-catalog",
        "five-predicates",
        "dynamic-fragment",
        "full-record-map",
    ),
)
def test_trace_audit_keeps_broad_catalog_forms_failing(
    tmp_path: Path,
    query: str,
    description_scan: bool,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("broad", query),
            _exec_output("broad", json.dumps([DEFERRED_TOOL]), reference=False),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "broad_tool_catalog_scan" in codes
    assert ("tool_catalog_description_scan" in codes) is description_scan
    assert result["summary"]["unbounded_catalog_queries"] == 1


@pytest.mark.parametrize(
    "output",
    [
        [
            {
                "type": "input_text",
                "text": "Script completed\nWall time 0.0 seconds\nOutput:\n",
            },
            {"type": "input_text", "text": json.dumps([DEFERRED_TOOL])},
            {"type": "input_text", "text": "extra"},
        ],
        [
            {
                "type": "input_text",
                "text": "prefix\nScript completed\nWall time 0.0 seconds\nOutput:\n",
            },
            {"type": "input_text", "text": json.dumps([DEFERRED_TOOL])},
        ],
        [
            {
                "type": "input_text",
                "text": "Script completed\nWall time 0.0 seconds\nOutput:\n",
            },
            {
                "type": "input_text",
                "text": json.dumps([f"tool_{index}" for index in range(13)]),
            },
        ],
        [
            {
                "type": "text",
                "text": json.dumps([DEFERRED_TOOL]),
                "unexpected": "extra envelope field",
            }
        ],
    ],
    ids=("extra-block", "unanchored-status", "too-many-names", "extra-field"),
)
def test_trace_audit_rejects_nonexact_names_only_results(
    tmp_path: Path,
    output: list[dict[str, object]],
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("names", DEFERRED_NAMES_QUERY),
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "names",
                    "output": output,
                },
            },
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert "broad_tool_catalog_scan" in codes
    assert result["summary"]["valid_names_only_results"] == 0
    assert result["summary"]["unbounded_catalog_queries"] == 1


@pytest.mark.parametrize(
    ("lookup_query", "schema_output", "expected_codes", "metric"),
    [
        (
            'const t = ALL_TOOLS.find(x => x.name === "mcp__tradingcodex__other"); text(t ? t.description : "missing")',
            "bounded schema declaration",
            {"unresolved_tool_schema_lookup"},
            "unresolved_schema_lookups",
        ),
        (
            DEFERRED_SCHEMA_QUERY,
            "missing",
            {"invalid_tool_schema_output", "missing_tool_schema_output"},
            "missing_schema_outputs",
        ),
        (
            DEFERRED_SCHEMA_QUERY,
            "Warning: truncated output (original token count: 25,000)",
            {"invalid_tool_schema_output", "truncated_tool_schema"},
            "truncated_schema_outputs",
        ),
        (
            DEFERRED_SCHEMA_QUERY,
            "x" * 20_001,
            {"invalid_tool_schema_output", "oversized_custom_output"},
            "invalid_schema_outputs",
        ),
        (
            f'const t = ALL_TOOLS.find(x => x.name === "{DEFERRED_TOOL}"); text(t?.description)',
            "bounded schema declaration",
            {
                "broad_tool_catalog_scan",
                "noncanonical_tool_schema_lookup",
                "tool_catalog_description_scan",
            },
            "noncanonical_schema_lookups",
        ),
    ],
    ids=("unresolved", "missing", "truncated", "oversized", "noncanonical"),
)
def test_trace_audit_rejects_invalid_targeted_schema_lookup_flow(
    tmp_path: Path,
    lookup_query: str,
    schema_output: str,
    expected_codes: set[str],
    metric: str,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("names", DEFERRED_NAMES_QUERY),
            _exec_output("names", json.dumps([DEFERRED_TOOL])),
            _exec_call("schema", lookup_query),
            _exec_output("schema", schema_output),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert expected_codes <= codes
    assert result["summary"][metric] == 1
    assert result["summary"]["valid_schema_lookups"] == 0


def test_trace_audit_rejects_extra_schema_block_and_repeated_lookup(
    tmp_path: Path,
) -> None:
    result = _audit_deferred_sequence(
        tmp_path,
        [
            _exec_call("names", DEFERRED_NAMES_QUERY),
            _exec_output("names", json.dumps([DEFERRED_TOOL])),
            _exec_call("schema-first", DEFERRED_SCHEMA_QUERY),
            _exec_output(
                "schema-first",
                "bounded schema declaration",
                extra_blocks=[{"type": "input_text", "text": "extra"}],
            ),
            _exec_call("schema-repeat", DEFERRED_SCHEMA_QUERY),
            _exec_output("schema-repeat", "bounded schema declaration"),
        ],
    )

    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "invalid_tool_schema_output",
        "repeated_tool_schema_lookup",
    } <= codes
    assert result["summary"]["invalid_schema_outputs"] == 1
    assert result["summary"]["repeated_schema_lookups"] == 1
    assert result["summary"]["valid_schema_lookups"] == 0


def test_trace_audit_requires_prior_name_result_in_the_same_session(
    tmp_path: Path,
) -> None:
    root_id = "root-cross-session"
    child_id = "child-cross-session"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _exec_call("root-names", DEFERRED_NAMES_QUERY),
            _exec_output("root-names", json.dumps([DEFERRED_TOOL])),
            _spawn("spawn-cross-session", "fundamental-analyst"),
            _started("spawn-cross-session", child_id),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            _exec_call("child-schema", DEFERRED_SCHEMA_QUERY),
            _exec_output("child-schema", "bounded schema declaration"),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert "unresolved_tool_schema_lookup" in codes
    assert result["summary"]["valid_names_only_results"] == 1
    assert result["summary"]["valid_schema_lookups"] == 0


def test_trace_audit_follows_started_child_across_midnight_and_checks_role(tmp_path: Path) -> None:
    root_id = "root-midnight"
    child_id = "child-midnight"
    root = tmp_path / "sessions/2026/07/17/root-midnight.jsonl"
    child = tmp_path / "sessions/2026/07/18/child-midnight.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("spawn-midnight", "fundamental-analyst"),
            _started("spawn-midnight", child_id),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, role="news-analyst", base=CHILD_BASE),
            _turn_context(model="wrong-model"),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    assert [meta["id"] for _, meta in discover_rollouts(root)] == [root_id, child_id]
    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert {"child_role_mismatch", "unexpected_child_model"} <= codes


@pytest.mark.parametrize(
    ("nickname", "expected_pass"),
    [
        ("fundamental-analyst the 2nd", True),
        ("fundamental-analyst the 21st", True),
        ("fundamental-analyst the 2th", False),
        ("fundamental-analyst backup", False),
    ],
)
def test_trace_audit_accepts_only_exact_native_ordinal_nickname_suffix(
    tmp_path: Path,
    nickname: str,
    expected_pass: bool,
) -> None:
    root_id = "root-native-nickname"
    child_id = "child-native-nickname"
    root = tmp_path / "root-native-nickname.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
            [
                _session_meta(root_id, base=HEAD_BASE),
                _turn_context(root=True),
                _agent_message("2026-07-18T00:00:01.000Z", phase="commentary"),
                _spawn("spawn-native-nickname", "fundamental-analyst"),
                _started("spawn-native-nickname", child_id),
                _authenticated_artifact_write(
                    "synthesis-nickname",
                    artifact_type="synthesis_report",
                    path="trading/reports/synthesis/synthesis-nickname.md",
                    inputs=["fundamental-nickname"],
                ),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(
                child_id,
                parent_id=root_id,
                nickname=nickname,
                base=CHILD_BASE,
                ),
                _turn_context(),
                _authenticated_artifact_write(
                    "fundamental-nickname",
                    artifact_type="fundamental_report",
                    path="trading/reports/fundamental/fundamental-nickname.md",
                ),
                _artifact_receipt_message(
                    "fundamental-nickname",
                    "trading/reports/fundamental/fundamental-nickname.md",
                ),
                _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert (result["status"] == "pass") is expected_pass
    assert ("child_nickname_mismatch" not in codes) is expected_pass
    if expected_pass:
        assert result["sessions"][1]["agent_nickname"] == "fundamental-analyst"
    else:
        assert result["sessions"][1]["agent_nickname"].startswith("invalid-sha256:")


def test_trace_audit_rejects_blind_deterministic_and_unstructured_errors(tmp_path: Path) -> None:
    root_id = "root-errors"
    child_id = "child-errors"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    args = {"artifact_id": "a-1"}
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("spawn-errors", "fundamental-analyst"),
            _started("spawn-errors", child_id),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            _mcp("get_research_artifact", args, _structured_error(retryable=False)),
            *[
                _mcp("search_datasets", {"query": f"intervening-{index}"}, _ok({"status": "ok"}))
                for index in range(7)
            ],
            _mcp(
                "record_audit_event",
                {"event_type": "unrelated", "message": "does not mutate artifact a-1"},
                _ok({"status": "recorded"}),
            ),
            _mcp("get_research_artifact", args, _ok({"artifact_id": "a-1"})),
            _mcp("record_dataset_snapshot", {"title": "x"}, {"Err": "legacy transport error"}),
            _mcp("materialize_dataset_slice", {"start": "bad-1"}, _structured_error(retryable=False)),
            _mcp("materialize_dataset_slice", {"start": "bad-2"}, _structured_error(retryable=False)),
            _mcp("materialize_dataset_slice", {"start": "bad-3"}, _structured_error(retryable=False)),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "blind_deterministic_retry",
        "unstructured_mcp_error",
    } <= codes
    assert "excessive_deterministic_corrections" not in codes


def test_trace_audit_rejects_incomplete_context_overrides_and_followup(tmp_path: Path) -> None:
    root_id = "root-incomplete"
    child_id = "child-incomplete"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id),
            _spawn("spawn-incomplete", "fundamental-analyst", model="override"),
            _started("spawn-incomplete", child_id),
            {"type": "event_msg", "payload": {"type": "token_count", "info": {}}},
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "followup_task", "arguments": "{}"},
            },
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "followup_task_used",
        "head_manager_base_missing",
        "incomplete_rollout",
        "incomplete_turn_context",
        "missing_token_evidence",
        "spawn_model_override",
    } <= codes
    assert result["sessions"][0]["tokens"]["event_count"] == 1
    assert result["sessions"][0]["tokens"]["valid_event_count"] == 0


def test_trace_audit_rejects_duplicate_lineage_and_child_spawn_attempt(tmp_path: Path) -> None:
    root_id = "root-duplicate"
    child_ids = ["child-duplicate-1", "child-duplicate-2"]
    root = tmp_path / "root.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("duplicate-call", "fundamental-analyst"),
            _spawn("duplicate-call", "fundamental-analyst"),
            _started("duplicate-call", child_ids[0]),
            _started("duplicate-call", child_ids[1]),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    for index, child_id in enumerate(child_ids):
        items = [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
        ]
        if index == 0:
            items.append(_spawn("child-spawn-attempt", "news-analyst"))
        items.extend([_token(100, 80, 10, last_input=90), _complete()])
        _write_jsonl(tmp_path / f"rollout-{child_id}.jsonl", items)

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "child_spawn_attempt",
        "duplicate_child_path",
        "non_unique_spawn_lineage",
    } <= codes


def test_trace_audit_hashes_invalid_free_form_lineage_metadata(tmp_path: Path) -> None:
    root_id = "root-private"
    child_id = "child-private"
    secret_role = "SECRET-SPAWN-PAYLOAD"
    secret_path = "/root/SECRET-PATH-PAYLOAD"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("private-call", secret_role),
            _started("private-call", child_id, secret_path),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(
                child_id,
                parent_id=root_id,
                role=secret_role,
                agent_path=secret_path,
                base=CHILD_BASE,
            ),
            _turn_context(model="SECRET-MODEL-CANARY"),
            {
                "type": "event_msg",
                "payload": {
                    "type": "sub_agent_activity",
                    "kind": "SECRET_ACTIVITY_CANARY",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "SECRET_FUNCTION_CANARY",
                    "arguments": "{}",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "private-custom-call",
                    "name": "exec",
                    "input": "tools.SECRET_NESTED_CANARY({})",
                },
            },
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    serialized = json.dumps(result)
    assert "SECRET" not in serialized
    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "invalid_spawn_contract",
        "unexpected_child_model",
        "unexpected_child_role",
    } <= codes


def test_trace_audit_rejects_partial_and_regressing_token_evidence(
    tmp_path: Path,
) -> None:
    root_id = "root-token-series"
    child_id = "child-token-series"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("spawn-token-series", "fundamental-analyst"),
            _started("spawn-token-series", child_id),
            _token(100, 80, 10, last_input=90),
            {"type": "event_msg", "payload": {"type": "token_count", "info": {}}},
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            _token(100, 80, 10, last_input=90),
            _token(90, 70, 9, last_input=80),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert "invalid_token_evidence" in codes
    assert result["sessions"][0]["tokens"]["invalid_event_count"] == 1
    assert result["sessions"][1]["tokens"]["series_monotonic"] is False


def test_trace_audit_rejects_description_scan_and_unlinked_task_path(
    tmp_path: Path,
) -> None:
    root_id = "root-lineage"
    child_id = "child-lineage"
    wrong_path = "/root/wrong"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("spawn-lineage", "fundamental-analyst"),
            _started("spawn-lineage", child_id, wrong_path),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(
                child_id,
                parent_id=root_id,
                nickname="news-analyst",
                agent_path=wrong_path,
                base=CHILD_BASE,
            ),
            _turn_context(),
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "description-catalog",
                    "name": "exec",
                    "input": "text(ALL_TOOLS.map(x => x.description).slice(0, 1))",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "description-catalog",
                    "output": [{"type": "text", "text": json.dumps(["valid_tool"])}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "split-catalog",
                    "name": "exec",
                    "input": "const ignored=ALL_TOOLS[0].name; text(ALL_TOOLS.slice(0,1).map(({description}) => description))",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "split-catalog",
                    "output": [
                        {"type": "text", "text": json.dumps(["first_tool"])},
                        {"type": "image", "data": "non-text-extra-block"},
                    ],
                },
            },
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert {
        "broad_tool_catalog_scan",
        "child_nickname_mismatch",
        "child_path_mismatch",
        "tool_catalog_description_scan",
    } <= codes
    assert result["sessions"][1]["custom_exec"]["unbounded_catalog_queries"] == 2


def test_trace_audit_cli_returns_json_error_for_malformed_numeric_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta("root-invalid-number", base=HEAD_BASE),
            _turn_context(root=True),
            _complete("not-an-integer"),
        ],
    )

    assert main([str(root), "--compact"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "error"
    assert captured.err == ""


def test_trace_audit_rejects_missing_raw_spawn_and_started_ids(
    tmp_path: Path,
) -> None:
    root_id = "root-missing-ids"
    child_id = "child-missing-ids"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    spawn = _spawn("discarded-spawn-id", "fundamental-analyst")
    started = _started("discarded-event-id", child_id)
    spawn_payload = spawn["payload"]
    started_payload = started["payload"]
    assert isinstance(spawn_payload, dict)
    assert isinstance(started_payload, dict)
    spawn_payload.pop("call_id")
    started_payload.pop("event_id")
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            spawn,
            started,
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert "invalid_spawn_lineage_id" in codes


@pytest.mark.parametrize("seconds", [10**400, 1e308])
def test_trace_audit_cli_rejects_non_finite_or_extreme_duration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    seconds: int | float,
) -> None:
    root = tmp_path / "root.jsonl"
    event = _mcp("search_datasets", {"query": "bounded"}, _ok({"status": "ok"}))
    payload = event["payload"]
    assert isinstance(payload, dict)
    payload["duration"] = {"secs": seconds, "nanos": 0}
    _write_jsonl(
        root,
        [
            _session_meta("root-extreme-duration", base=HEAD_BASE),
            _turn_context(root=True),
            event,
            _complete(),
        ],
    )

    assert main([str(root), "--compact"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "error"
    assert "Infinity" not in captured.out
    assert captured.err == ""


def test_trace_audit_rejects_invalid_turn_context_hidden_by_later_valid_event(
    tmp_path: Path,
) -> None:
    root_id = "root-context-series"
    child_id = "child-context-series"
    root = tmp_path / "root.jsonl"
    child = tmp_path / f"rollout-{child_id}.jsonl"
    _write_jsonl(
        root,
        [
            _session_meta(root_id, base=HEAD_BASE),
            _turn_context(root=True),
            _spawn("spawn-context-series", "fundamental-analyst"),
            _started("spawn-context-series", child_id),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )
    _write_jsonl(
        child,
        [
            _session_meta(child_id, parent_id=root_id, base=CHILD_BASE),
            _turn_context(model="wrong-model"),
            _turn_context(),
            _token(100, 80, 10, last_input=90),
            _complete(),
        ],
    )

    result = audit_codex_trace(root, candidate=True)
    codes = {item["code"] for item in result["candidate_violations"]}
    assert "invalid_turn_context_evidence" in codes
    assert result["sessions"][1]["turn_context_events"] == {
        "event_count": 2,
        "valid_event_count": 1,
        "all_events_valid": False,
        "series_consistent": True,
    }


def test_trace_audit_caps_pathological_truncation_counter_without_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root.jsonl"
    digits = "9" * 5_000
    _write_jsonl(
        root,
        [
            _session_meta("root-large-truncation", base=HEAD_BASE),
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "large-truncation",
                    "name": "exec",
                    "input": "text(ALL_TOOLS.map(x => x.name))",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "large-truncation",
                    "output": [
                        {
                            "type": "text",
                            "text": "Warning: truncated output (original token count: "
                            + digits
                            + ")",
                        }
                    ],
                },
            },
        ],
    )

    result = audit_codex_trace(root)
    assert result["summary"]["oversized_truncation_counts"] == 1
    assert (
        result["sessions"][0]["custom_exec"]["max_truncated_original_tokens"]
        == MAX_REPORTED_TRUNCATION_TOKENS
    )
    assert main([str(root), "--compact"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "pass"
    assert digits not in captured.out
    assert captured.err == ""
