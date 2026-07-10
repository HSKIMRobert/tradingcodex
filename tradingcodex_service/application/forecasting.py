from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import exclusive_file_lock, file_hash, now_iso, safe_workspace_path, sanitize_id, stable_hash
from tradingcodex_service.application.runtime import workspace_context_payload

FORECAST_ROOT = Path("trading/forecasts")
FORECAST_LEDGER = FORECAST_ROOT / "forecast-ledger.jsonl"
SOURCE_SNAPSHOT_ROOT = Path("trading/research/source-snapshots")
TARGET_TYPES = {"binary", "categorical", "continuous"}
MIN_CALIBRATION_SAMPLE = 20


def issue_forecast(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ledger = _ledger_path(root)
    issued_at = _iso(args.get("issued_at") or now_iso(), "issued_at")
    knowledge_cutoff = _iso(args.get("knowledge_cutoff") or args.get("source_as_of"), "knowledge_cutoff")
    if knowledge_cutoff > issued_at:
        raise ValueError("knowledge_cutoff must not be after issued_at")
    horizon = _horizon_iso(args.get("horizon"))
    if horizon < issued_at:
        raise ValueError("horizon must not be before issued_at")
    forecast_id = sanitize_id(args.get("forecast_id") or f"forecast-{uuid.uuid4().hex}")
    event = {
        "schema_version": 2,
        "event_id": uuid.uuid4().hex,
        "event_type": "issued",
        "forecast_id": forecast_id,
        "version": 1,
        "workflow_run_id": str(args.get("workflow_run_id") or ""),
        "artifact_id": _required_text(args, "artifact_id"),
        "role": _required_text(args, "role"),
        "author": str(args.get("author") or args.get("principal_id") or args.get("role") or ""),
        "instrument": str(args.get("instrument") or args.get("symbol") or "").upper(),
        "universe": str(args.get("universe") or ""),
        "regime": str(args.get("regime") or "unclassified"),
        "forecast_target": _required_text(args, "forecast_target"),
        "target_type": str(args.get("target_type") or "binary").lower(),
        "unit": str(args.get("unit") or ""),
        "benchmark": str(args.get("benchmark") or ""),
        "horizon": horizon,
        "issued_at": issued_at,
        "knowledge_cutoff": knowledge_cutoff,
        "probability": args.get("probability"),
        "probability_range": args.get("probability_range"),
        "probabilities": args.get("probabilities"),
        "prediction": args.get("prediction"),
        "interval": args.get("interval"),
        "quantiles": args.get("quantiles"),
        "base_rate": args.get("base_rate"),
        "evidence_ids": _required_list(args, "evidence_ids"),
        "contrary_evidence": _required_list(args, "contrary_evidence"),
        "invalidation_conditions": _required_list(args, "invalidation_conditions"),
        "update_triggers": _required_list(args, "update_triggers"),
        "resolution_rule": str(args.get("resolution_rule") or args.get("resolution_source") or ""),
        "resolution_source": str(args.get("resolution_source") or args.get("resolution_rule") or ""),
        "review_date": str(args.get("review_date") or args.get("horizon") or ""),
        "model": str(args.get("model") or ""),
        "reasoning_effort": str(args.get("reasoning_effort") or ""),
        "prompt_hash": str(args.get("prompt_hash") or ""),
        "tool_profile_hash": str(args.get("tool_profile_hash") or ""),
        "config_hash": str(args.get("config_hash") or ""),
        "status": "open",
        "idempotency_key": str(args.get("idempotency_key") or forecast_id),
        "authority": "evidence_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
        "recorded_at": now_iso(),
    }
    if not event["author"]:
        raise ValueError("author is required")
    if not event["resolution_rule"]:
        raise ValueError("resolution_rule is required")
    _validate_prediction(event)
    event["base_rate"] = _validate_base_rate(root, event)
    with exclusive_file_lock(ledger):
        events = _read_events(ledger)
        existing = _idempotent_event(events, "issued", forecast_id, event["idempotency_key"])
        if existing is not None:
            return _result(root, existing)
        if any(item.get("forecast_id") == forecast_id for item in events):
            raise ValueError(f"forecast already exists: {forecast_id}")
        _append_event(ledger, event)
    return _result(root, event)


def revise_forecast(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ledger = _ledger_path(root)
    forecast_id = _required_text(args, "forecast_id")
    with exclusive_file_lock(ledger):
        events = _read_events(ledger)
        idempotency_key = str(args.get("idempotency_key") or "")
        existing = _idempotent_event(events, "revised", forecast_id, idempotency_key)
        if existing is not None:
            return _result(root, existing)
        history = _history(events, forecast_id)
        current = _latest(history)
        if not current:
            raise ValueError(f"forecast not found: {forecast_id}")
        if current.get("status") != "open":
            raise ValueError("only open forecasts can be revised")
        actor = str(args.get("author") or args.get("principal_id") or current.get("author") or "")
        if actor != current.get("author"):
            raise PermissionError("only the forecast author may revise an open forecast")
        event = {
            **current,
            "event_id": uuid.uuid4().hex,
            "event_type": "revised",
            "version": int(current.get("version") or 1) + 1,
            "prior_event_id": current.get("event_id"),
            "prior_version": current.get("version"),
            "revision_reason": _required_text(args, "revision_reason"),
            "revised_at": _iso(args.get("revised_at") or now_iso(), "revised_at"),
            "recorded_at": now_iso(),
            "idempotency_key": idempotency_key or uuid.uuid4().hex,
        }
        for field in (
            "probability",
            "probability_range",
            "probabilities",
            "prediction",
            "interval",
            "quantiles",
            "base_rate",
            "evidence_ids",
            "contrary_evidence",
            "invalidation_conditions",
            "update_triggers",
            "model",
            "reasoning_effort",
            "prompt_hash",
            "tool_profile_hash",
            "config_hash",
            "knowledge_cutoff",
            "regime",
        ):
            if field in args:
                event[field] = args[field]
        event["knowledge_cutoff"] = _iso(event.get("knowledge_cutoff"), "knowledge_cutoff")
        previous_time = str(current.get("revised_at") or current.get("issued_at") or "")
        if event["revised_at"] < previous_time:
            raise ValueError("revised_at must not be before the previous forecast event")
        if event["knowledge_cutoff"] < str(current.get("knowledge_cutoff") or ""):
            raise ValueError("knowledge_cutoff must not move backward on revision")
        if event["knowledge_cutoff"] > event["revised_at"]:
            raise ValueError("knowledge_cutoff must not be after revised_at")
        if not any(
            field in args
            for field in (
                "probability",
                "probability_range",
                "probabilities",
                "prediction",
                "interval",
                "quantiles",
                "base_rate",
                "evidence_ids",
                "contrary_evidence",
                "invalidation_conditions",
                "update_triggers",
            )
        ):
            raise ValueError("forecast revision must change evidence, prediction, base rate, or update conditions")
        _validate_prediction(event)
        event["base_rate"] = _validate_base_rate(root, event)
        _append_event(ledger, event)
    return _result(root, event)


def resolve_forecast(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ledger = _ledger_path(root)
    forecast_id = _required_text(args, "forecast_id")
    resolver = str(args.get("resolver") or args.get("principal_id") or "").strip()
    if not resolver:
        raise ValueError("resolver is required")
    snapshot_id = _required_text(args, "resolution_source_snapshot_id")
    snapshot_path = safe_workspace_path(root, SOURCE_SNAPSHOT_ROOT / f"{sanitize_id(snapshot_id)}.json", allowed_roots=(SOURCE_SNAPSHOT_ROOT,))
    if not snapshot_path.exists():
        raise ValueError(f"resolution source snapshot not found: {snapshot_id}")
    with exclusive_file_lock(ledger):
        events = _read_events(ledger)
        idempotency_key = str(args.get("idempotency_key") or "")
        resolve_dispute = args.get("resolve_dispute") is True
        event_type = "dispute_resolved" if resolve_dispute else "resolved"
        existing = _idempotent_event(events, event_type, forecast_id, idempotency_key)
        if existing is not None:
            return _result(root, existing)
        history = _history(events, forecast_id)
        current = _latest(history)
        if not current:
            raise ValueError(f"forecast not found: {forecast_id}")
        if resolve_dispute:
            if current.get("status") != "closed" or current.get("dispute_state") not in {"disputed", "under_review"}:
                raise ValueError("resolve_dispute requires a closed disputed or under-review forecast")
        elif current.get("status") != "open":
            if current.get("dispute_state") in {"disputed", "under_review"}:
                raise ValueError("forecast is disputed; retry with resolve_dispute=true")
            raise ValueError("forecast is already closed")
        if resolver == current.get("author"):
            raise ValueError("forecast resolver must be independent from the forecast author")
        outcome = args.get("outcome")
        _validate_outcome(current, outcome)
        resolved_at = _iso(args.get("resolved_at") or now_iso(), "resolved_at")
        observed_at = _iso(args.get("observed_at") or resolved_at, "observed_at")
        if observed_at > resolved_at:
            raise ValueError("observed_at must not be after resolved_at")
        if observed_at < str(current.get("horizon") or ""):
            raise ValueError("observed_at must not be before the forecast horizon")
        snapshot = _source_snapshot_document(snapshot_path, snapshot_id)
        snapshot_known_at = _iso(snapshot.get("known_at"), f"source snapshot {snapshot_id} known_at")
        if snapshot_known_at < observed_at:
            raise ValueError("resolution source snapshot must not predate observed_at")
        if snapshot_known_at > resolved_at:
            raise ValueError("resolution source snapshot must be known by resolved_at")
        dispute_state = str(args.get("dispute_state") or "undisputed")
        if resolve_dispute and dispute_state != "undisputed":
            raise ValueError("resolve_dispute must close the dispute as undisputed")
        if dispute_state not in {"undisputed", "disputed", "under_review"}:
            raise ValueError("dispute_state must be undisputed, disputed, or under_review")
        event = {
            **current,
            "event_id": uuid.uuid4().hex,
            "event_type": event_type,
            "version": int(current.get("version") or 1) + 1,
            "prior_event_id": current.get("event_id"),
            "prior_version": current.get("version"),
            "status": "closed",
            "outcome": outcome,
            "resolver": resolver,
            "resolution_source_snapshot_id": snapshot_id,
            "resolution_source_content_hash": file_hash(snapshot_path),
            "resolution_source_snapshot_hash": snapshot["snapshot_hash"],
            "resolved_at": resolved_at,
            "observed_at": observed_at,
            "resolution_note": str(args.get("resolution_note") or ""),
            "dispute_state": dispute_state,
            "resolution_supersedes_event_id": current.get("event_id") if resolve_dispute else "",
            "recorded_at": now_iso(),
            "idempotency_key": idempotency_key or uuid.uuid4().hex,
        }
        _append_event(ledger, event)
    return _result(root, event)


def score_forecast(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    ledger = _ledger_path(root)
    forecast_id = _required_text(args, "forecast_id")
    with exclusive_file_lock(ledger):
        events = _read_events(ledger)
        idempotency_key = str(args.get("idempotency_key") or "")
        existing = _idempotent_event(events, "scored", forecast_id, idempotency_key)
        if existing is not None:
            return _result(root, existing)
        history = _history(events, forecast_id)
        current = _latest(history)
        if not current:
            raise ValueError(f"forecast not found: {forecast_id}")
        if current.get("event_type") == "scored":
            return _result(root, current)
        if current.get("status") != "closed" or "outcome" not in current:
            raise ValueError("forecast must be resolved before scoring")
        if current.get("dispute_state") != "undisputed":
            raise ValueError("disputed forecasts cannot be scored until independently resolved")
        scoreable = [item for item in history if item.get("event_type") in {"issued", "revised"}]
        scores_by_event = [
            {
                "event_id": item["event_id"],
                "version": item["version"],
                "scores": _scores({**item, "outcome": current["outcome"]}),
            }
            for item in scoreable
        ]
        scores = scores_by_event[-1]["scores"]
        event = {
            **current,
            "event_id": uuid.uuid4().hex,
            "event_type": "scored",
            "version": int(current.get("version") or 1) + 1,
            "prior_event_id": current.get("event_id"),
            "prior_version": current.get("version"),
            "score_version": 1,
            "scores": scores,
            "original_scores": scores_by_event[0]["scores"],
            "scores_by_event": scores_by_event,
            "scored_at": now_iso(),
            "recorded_at": now_iso(),
            "idempotency_key": idempotency_key or f"score:{forecast_id}",
        }
        _append_event(ledger, event)
    return _result(root, event)


def get_forecast(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root)
    forecast_id = _required_text(args, "forecast_id")
    history = _history(_read_events(_ledger_path(root)), forecast_id)
    current = _latest(history)
    if not current:
        raise ValueError(f"forecast not found: {forecast_id}")
    return {
        **_result(root, current),
        "history": history if args.get("include_history", True) is not False else [],
    }


def list_forecasts(workspace_root: Path | str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    root = Path(workspace_root)
    latest = _latest_records(_read_events(_ledger_path(root)))
    status = str(args.get("status") or "")
    role = str(args.get("role") or "")
    if status:
        latest = [item for item in latest if item.get("status") == status]
    if role:
        latest = [item for item in latest if item.get("role") == role]
    limit = max(1, min(int(args.get("limit") or 100), 1000))
    return {
        "forecasts": latest[-limit:],
        "count": len(latest),
        "ledger_path": FORECAST_LEDGER.as_posix(),
        "authority": "evidence_only",
        "workspace_context": workspace_context_payload(root),
    }


def calibration_report(workspace_root: Path | str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    minimum = max(2, int(args.get("minimum_sample") or MIN_CALIBRATION_SAMPLE))
    binary_records = [
        item
        for item in _latest_records(_read_events(_ledger_path(Path(workspace_root))))
        if item.get("event_type") == "scored" and item.get("target_type") == "binary"
    ]
    records = [item for item in binary_records if item.get("scoring_probability") is not None and item.get("scores", {}).get("brier") is not None]
    count = len(records)
    report: dict[str, Any] = {
        "status": "ok" if count >= minimum else "insufficient_sample",
        "sample_size": count,
        "minimum_sample": minimum,
        "excluded_range_only": len(binary_records) - count,
        "authority": "evidence_only",
        "warning": "" if count >= minimum else "Calibration statistics are withheld until the documented minimum sample resolves.",
    }
    if count < minimum:
        return report
    report["mean_brier"] = sum(float(item["scores"]["brier"]) for item in records) / count
    baseline = [float(item["scores"]["base_rate_brier"]) for item in records if item.get("scores", {}).get("base_rate_brier") is not None]
    report["mean_base_rate_brier"] = sum(baseline) / len(baseline) if baseline else None
    report["buckets"] = _calibration_buckets(records)
    report["by_role"] = _group_brier(records, "role")
    report["by_model"] = _group_brier(records, "model")
    report["by_horizon"] = _group_brier(records, "horizon")
    report["by_universe"] = _group_brier(records, "universe")
    report["by_regime"] = _group_brier(records, "regime")
    return report


def _validate_prediction(record: dict[str, Any]) -> None:
    target_type = str(record.get("target_type") or "")
    if target_type not in TARGET_TYPES:
        raise ValueError(f"target_type must be one of: {', '.join(sorted(TARGET_TYPES))}")
    if target_type == "binary":
        record.pop("scoring_probability", None)
        probability = None
        if record.get("probability") not in (None, ""):
            probability = _probability(record.get("probability"), "probability")
            record["probability"] = probability
        if record.get("probability_range") not in (None, ""):
            low, high = _probability_range(record["probability_range"])
            if probability is not None and not low <= probability <= high:
                raise ValueError("probability must fall inside probability_range")
            record["probability_range"] = [low, high]
            if probability is not None:
                record["scoring_probability"] = probability
        elif probability is not None:
            record["scoring_probability"] = probability
        else:
            raise ValueError("binary forecasts require probability or probability_range")
    elif target_type == "categorical":
        probabilities = record.get("probabilities")
        if not isinstance(probabilities, dict) or len(probabilities) < 2:
            raise ValueError("categorical forecasts require probabilities for at least two outcomes")
        normalized = {str(key): _probability(value, f"probabilities.{key}") for key, value in probabilities.items()}
        if not math.isclose(sum(normalized.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("categorical probabilities must sum to 1")
        record["probabilities"] = normalized
    else:
        if record.get("prediction") in (None, "") and not isinstance(record.get("interval"), dict) and not isinstance(record.get("quantiles"), dict):
            raise ValueError("continuous forecasts require prediction, interval, or quantiles")
        if record.get("prediction") not in (None, ""):
            record["prediction"] = _finite(record["prediction"], "prediction")
        if isinstance(record.get("interval"), dict):
            low = _finite(record["interval"].get("lower"), "interval.lower")
            high = _finite(record["interval"].get("upper"), "interval.upper")
            if low > high:
                raise ValueError("interval.lower must not exceed interval.upper")
            normalized_interval = {"lower": low, "upper": high}
            if record["interval"].get("coverage") not in (None, ""):
                coverage = _probability(record["interval"]["coverage"], "interval.coverage")
                if coverage in {0.0, 1.0}:
                    raise ValueError("interval.coverage must be strictly between 0 and 1")
                normalized_interval["coverage"] = coverage
            record["interval"] = normalized_interval
        if isinstance(record.get("quantiles"), dict):
            record["quantiles"] = _validated_quantiles(record["quantiles"])


def _validate_outcome(record: dict[str, Any], outcome: Any) -> None:
    target_type = record.get("target_type")
    if target_type == "binary" and outcome not in (0, 1, False, True):
        raise ValueError("binary outcome must be 0 or 1")
    if target_type == "categorical" and str(outcome) not in (record.get("probabilities") or {}):
        raise ValueError("categorical outcome must match a forecast category")
    if target_type == "continuous":
        _finite(outcome, "outcome")


def _scores(record: dict[str, Any]) -> dict[str, Any]:
    outcome = record["outcome"]
    if record["target_type"] == "binary":
        y = 1.0 if outcome in (1, True) else 0.0
        if record.get("scoring_probability") is None:
            low, high = (float(item) for item in record["probability_range"])
            endpoint_scores = [(low - y) ** 2, (high - y) ** 2]
            return {
                "score_type": "probability_range_diagnostic",
                "proper_score_available": False,
                "brier": None,
                "log_score": None,
                "brier_bounds": [min(endpoint_scores), max(endpoint_scores)],
                "base_rate_brier": (_base_rate_probability(record.get("base_rate")) - y) ** 2,
            }
        p = float(record["scoring_probability"])
        safe_p = min(max(p, 1e-15), 1 - 1e-15)
        base_rate = _base_rate_probability(record.get("base_rate"))
        return {
            "score_type": "binary_probability",
            "proper_score_available": True,
            "brier": (p - y) ** 2,
            "log_score": -(y * math.log(safe_p) + (1 - y) * math.log(1 - safe_p)),
            "base_rate_brier": (base_rate - y) ** 2 if base_rate is not None else None,
        }
    if record["target_type"] == "categorical":
        probabilities = record["probabilities"]
        baseline = record["base_rate"]["probabilities"]
        outcome_key = str(outcome)
        safe_p = max(float(probabilities[outcome_key]), 1e-15)
        return {
            "brier": sum((float(probability) - (1.0 if key == outcome_key else 0.0)) ** 2 for key, probability in probabilities.items()),
            "log_score": -math.log(safe_p),
            "base_rate_brier": sum((float(probability) - (1.0 if key == outcome_key else 0.0)) ** 2 for key, probability in baseline.items()),
            "base_rate_log_score": -math.log(max(float(baseline[outcome_key]), 1e-15)),
        }
    actual = _finite(outcome, "outcome")
    scores: dict[str, Any] = {
        "base_rate_error": float(record["base_rate"]["prediction"]) - actual,
        "base_rate_absolute_error": abs(float(record["base_rate"]["prediction"]) - actual),
    }
    if record.get("prediction") not in (None, ""):
        error = float(record["prediction"]) - actual
        scores.update({"error": error, "absolute_error": abs(error), "squared_error": error**2})
    if isinstance(record.get("interval"), dict):
        low = float(record["interval"]["lower"])
        high = float(record["interval"]["upper"])
        covered = low <= actual <= high
        scores.update({"interval_covered": covered, "interval_width": high - low})
        coverage = record["interval"].get("coverage")
        if coverage is None:
            scores["proper_interval_score_available"] = False
        else:
            alpha = 1.0 - float(coverage)
            penalty = (2.0 / alpha) * ((low - actual) if actual < low else (actual - high) if actual > high else 0.0)
            scores.update({"proper_interval_score_available": True, "interval_score": high - low + penalty})
    if isinstance(record.get("quantiles"), dict):
        losses = {}
        for raw_quantile, value in record["quantiles"].items():
            quantile = _probability(raw_quantile, f"quantile {raw_quantile}")
            error = actual - float(value)
            losses[str(raw_quantile)] = max(quantile * error, (quantile - 1) * error)
        scores["quantile_loss"] = losses
    return scores


def _base_rate_probability(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        value = value.get("value")
    return _probability(value, "base_rate")


def _validate_base_rate(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("base_rate")
    if not isinstance(value, dict):
        raise ValueError("base_rate must include cohort, source_snapshot_id, sample_size, selection_rule, and target baseline")
    required = ("cohort", "source_snapshot_id", "sample_size", "selection_rule")
    missing = [field for field in required if value.get(field) in (None, "", [], {})]
    if missing:
        raise ValueError(f"base_rate missing: {', '.join(missing)}")
    if int(value["sample_size"]) < 1:
        raise ValueError("base_rate.sample_size must be positive")
    snapshot_id = sanitize_id(value["source_snapshot_id"])
    path = safe_workspace_path(root, SOURCE_SNAPSHOT_ROOT / f"{snapshot_id}.json", allowed_roots=(SOURCE_SNAPSHOT_ROOT,))
    if not path.exists():
        raise ValueError(f"base-rate source snapshot not found: {snapshot_id}")
    snapshot = _source_snapshot_document(path, snapshot_id)
    known_at = _iso(snapshot.get("known_at"), f"source snapshot {snapshot_id} known_at")
    if known_at > str(record.get("knowledge_cutoff") or ""):
        raise ValueError("base-rate source snapshot is after forecast knowledge_cutoff")
    normalized = dict(value)
    as_of = _iso(value.get("as_of") or known_at, "base_rate.as_of")
    if as_of > str(record.get("knowledge_cutoff") or ""):
        raise ValueError("base_rate.as_of is after forecast knowledge_cutoff")
    normalized["as_of"] = as_of
    normalized["source_snapshot_content_hash"] = file_hash(path)
    normalized["source_snapshot_hash"] = snapshot["snapshot_hash"]
    if record["target_type"] == "binary":
        normalized["value"] = _probability(value.get("value"), "base_rate.value")
    elif record["target_type"] == "categorical":
        raw = value.get("probabilities")
        if not isinstance(raw, dict) or set(raw) != set(record.get("probabilities") or {}):
            raise ValueError("categorical base_rate.probabilities must match forecast categories")
        normalized["probabilities"] = {key: _probability(item, f"base_rate.probabilities.{key}") for key, item in raw.items()}
        if not math.isclose(sum(normalized["probabilities"].values()), 1.0, abs_tol=1e-9):
            raise ValueError("categorical base-rate probabilities must sum to 1")
    else:
        normalized["prediction"] = _finite(value.get("prediction"), "base_rate.prediction")
    return normalized


def _probability(value: Any, field: str) -> float:
    number = _finite(value, field)
    if not 0 <= number <= 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return number


def _probability_range(value: Any) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        low, high = value
    else:
        text = str(value).strip().rstrip("%")
        parts = text.split("-", 1)
        if len(parts) != 2:
            raise ValueError("probability_range must contain lower and upper bounds")
        low, high = parts
        if "%" in str(value) or max(abs(float(low)), abs(float(high))) > 1:
            low, high = float(low) / 100, float(high) / 100
    low_value = _probability(low, "probability_range.lower")
    high_value = _probability(high, "probability_range.upper")
    if low_value > high_value:
        raise ValueError("probability_range lower bound must not exceed upper bound")
    return low_value, high_value


def _validated_quantiles(value: dict[Any, Any]) -> dict[str, float]:
    levels: list[tuple[float, float]] = []
    seen: set[float] = set()
    for raw_level, raw_value in value.items():
        level = _probability(raw_level, f"quantile {raw_level}")
        if level in seen:
            raise ValueError("quantile levels must be unique")
        seen.add(level)
        levels.append((level, _finite(raw_value, f"quantiles.{raw_level}")))
    levels.sort()
    if any(current[1] < previous[1] for previous, current in zip(levels, levels[1:])):
        raise ValueError("quantile values must be nondecreasing by probability level")
    return {format(level, ".15g"): prediction for level, prediction in levels}


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


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


def _horizon_iso(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 10:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        else:
            return parsed.isoformat().replace("+00:00", "Z")
    return _iso(text, "horizon")


def _source_snapshot_known_at(path: Path, snapshot_id: str) -> str:
    snapshot = _source_snapshot_document(path, snapshot_id)
    return _iso(snapshot.get("known_at"), f"source snapshot {snapshot_id} known_at")


def _source_snapshot_document(path: Path, snapshot_id: str) -> dict[str, Any]:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"source snapshot is invalid: {snapshot_id}") from exc
    if not isinstance(snapshot, dict):
        raise ValueError(f"source snapshot must be an object: {snapshot_id}")
    if str(snapshot.get("snapshot_id") or "") != snapshot_id:
        raise ValueError(f"source snapshot id mismatch: {snapshot_id}")
    payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else {}
    if stable_hash(payload) != snapshot.get("payload_hash"):
        raise ValueError(f"source snapshot payload hash mismatch: {snapshot_id}")
    snapshot_seed = {key: value for key, value in snapshot.items() if key not in {"snapshot_id", "snapshot_hash"}}
    if stable_hash(snapshot_seed) != snapshot.get("snapshot_hash"):
        raise ValueError(f"source snapshot hash mismatch: {snapshot_id}")
    return snapshot


def _required_text(args: dict[str, Any], field: str) -> str:
    value = str(args.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _required_list(args: dict[str, Any], field: str) -> list[Any]:
    value = args.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    return value


def _ledger_path(root: Path) -> Path:
    return safe_workspace_path(root, FORECAST_LEDGER, allowed_roots=(FORECAST_ROOT,))


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"forecast ledger line {line_number} is invalid JSON") from exc
        if not isinstance(event, dict):
            raise ValueError(f"forecast ledger line {line_number} must be an object")
        events.append(event)
    return events


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _history(events: list[dict[str, Any]], forecast_id: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("forecast_id") == forecast_id]


def _latest(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    return history[-1] if history else None


def _latest_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        forecast_id = str(event.get("forecast_id") or "")
        if forecast_id:
            latest[forecast_id] = event
    return list(latest.values())


def _idempotent_event(
    events: list[dict[str, Any]],
    event_type: str,
    forecast_id: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    return next(
        (
            event
            for event in events
            if event.get("event_type") == event_type
            and event.get("forecast_id") == forecast_id
            and event.get("idempotency_key") == idempotency_key
        ),
        None,
    )


def _result(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "recorded",
        "forecast": event,
        "ledger_path": FORECAST_LEDGER.as_posix(),
        "authority": "evidence_only",
        "workspace_context": workspace_context_payload(root),
    }


def _calibration_buckets(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = []
    for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
        upper = lower + 0.2
        items = [
            item
            for item in records
            if lower <= float(item.get("scoring_probability", item.get("probability"))) <= upper
            and (lower == 0.8 or float(item.get("scoring_probability", item.get("probability"))) < upper)
        ]
        if items:
            buckets.append(
                {
                    "range": [lower, upper],
                    "count": len(items),
                    "mean_probability": sum(float(item.get("scoring_probability", item.get("probability"))) for item in items) / len(items),
                    "observed_frequency": sum(1.0 if item["outcome"] in (1, True) else 0.0 for item in items) / len(items),
                    "observed_frequency_95pct": _wilson_interval(
                        sum(1 for item in items if item["outcome"] in (1, True)),
                        len(items),
                    ),
                }
            )
    return buckets


def _group_brier(records: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for item in records:
        key = str(item.get(field) or "unknown")
        grouped.setdefault(key, []).append(float(item["scores"]["brier"]))
    return {
        key: {"sample_size": len(values), "mean_brier": sum(values) / len(values)}
        for key, values in sorted(grouped.items())
    }


def _wilson_interval(successes: int, sample_size: int) -> list[float]:
    if sample_size <= 0:
        return [0.0, 1.0]
    z = 1.96
    proportion = successes / sample_size
    denominator = 1 + (z * z / sample_size)
    center = (proportion + z * z / (2 * sample_size)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) / sample_size) + (z * z / (4 * sample_size * sample_size))) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]
