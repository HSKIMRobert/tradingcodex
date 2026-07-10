from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tradingcodex_service.application.common import (
    atomic_write_text,
    exclusive_file_lock,
    file_hash,
    now_iso,
    safe_workspace_path,
    sanitize_id,
    stable_hash,
)
from tradingcodex_service.application.runtime import workspace_context_payload

CORPUS_ROOT = Path("trading/evaluations/corpora")
RUN_ROOT = Path("trading/evaluations/runs")
ASSIGNMENT_ROOT = Path("trading/evaluations/blind-review-assignments")
REVIEW_ROOT = Path("trading/evaluations/blind-reviews")
COMPARISON_ROOT = Path("trading/evaluations/comparisons")
REPLAY_ROOT = Path("trading/research/replay-manifests")
CASE_ARTIFACT_ROOTS = (
    Path("trading/research"),
    Path("trading/reports"),
    Path("trading/forecasts"),
    Path("trading/decisions"),
    Path("trading/evaluations/artifacts"),
)
CORE_EVALUATION_PROFILE_ID = "core_investment_v1"
REQUIRED_CASE_TAGS = {
    "withheld_future_earnings",
    "restated_vintage",
    "delisted_historical_universe",
    "corporate_action_ambiguity",
    "null_signal",
    "subperiod_failure",
    "cost_capacity_failure",
    "hidden_factor_exposure",
    "overlapping_label_leakage",
    "incoherent_scenarios",
    "malformed_forecast",
    "forecast_revision",
    "conflicting_stale_sources",
    "multilingual_scope_negation",
    "paired_model_replay",
}
METRIC_DIMENSIONS = {
    "evidence",
    "workflow",
    "analysis",
    "forecasting",
    "quant_research",
    "safety",
    "operations",
}
BUILTIN_EVALUATION_PROFILES = {
    CORE_EVALUATION_PROFILE_ID: {
        "source": "tradingcodex_bundled",
        "required_case_tags": sorted(REQUIRED_CASE_TAGS),
        "metric_dimensions": sorted(METRIC_DIMENSIONS),
    }
}
HARD_FAILURE_CHECKS = {
    "safety_violation": "no_safety_violation",
    "scope_widening": "no_scope_widening",
    "fabricated_evidence": "no_fabricated_evidence",
    "incorrect_privileged_tool_use": "no_incorrect_privileged_tool_use",
    "unregistered_extension_use": "no_unregistered_extension_use",
}
PAIR_INVARIANT_FIELDS = (
    "reasoning_effort",
    "prompt_hash",
    "config_hash",
    "tool_profile_hash",
    "deterministic_calculation_hash",
    "extension_profile_hash",
    "evaluation_budget_hash",
)
MAX_BLIND_ARTIFACT_BYTES = 1_000_000
PAIR_PROVENANCE_STATUS = "caller_attested_unverified"


def create_evaluation_corpus(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    evaluation_profile = _evaluation_profile(args)
    required_case_tags = set(evaluation_profile["required_case_tags"])
    criteria = _promotion_criteria(
        args.get("promotion_criteria"),
        set(evaluation_profile["metric_dimensions"]),
    )
    cases = args.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    normalized_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    covered_tags: set[str] = set()
    for index, raw in enumerate(cases, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = sanitize_id(_required_text(raw, "case_id"))
        if case_id in seen_ids:
            raise ValueError(f"duplicate evaluation case id: {case_id}")
        seen_ids.add(case_id)
        tags = {_nonempty_text(item, f"cases[{index}].tags") for item in _required_list(raw, "tags")}
        unknown = tags - required_case_tags
        if unknown:
            raise ValueError(f"cases[{index}] has unknown tags: {', '.join(sorted(unknown))}")
        covered_tags.update(tags)
        manifest_id = sanitize_id(_required_text(raw, "replay_manifest_id"))
        manifest_path = _path(root, REPLAY_ROOT, manifest_id)
        if not manifest_path.exists():
            raise ValueError(f"replay manifest not found: {manifest_id}")
        manifest = _verified_artifact(manifest_path, "manifest_hash")
        expected_checks = _expected_checks(raw.get("expected_checks"), index)
        forbidden_actions = {
            _nonempty_text(item, f"cases[{index}].forbidden_actions")
            for item in _required_list(raw, "forbidden_actions")
        }
        normalized_cases.append({
            "case_id": case_id,
            "tags": sorted(tags),
            "replay_manifest_id": manifest_id,
            "replay_manifest_hash": _digest_text(manifest.get("manifest_hash"), "replay manifest hash"),
            "prompt": _required_text(raw, "prompt"),
            "expected_checks": expected_checks,
            "blind_review_rubric": _required_dict(raw, "blind_review_rubric"),
            "forbidden_actions": sorted(forbidden_actions | {"order", "approval", "execution"}),
        })
    missing_tags = required_case_tags - covered_tags
    if missing_tags:
        raise ValueError(f"evaluation corpus missing required cases: {', '.join(sorted(missing_tags))}")
    if not _has_distinct_tag_coverage(normalized_cases, required_case_tags):
        raise ValueError("each required evaluation tag must be covered by a distinct case")
    minimum_blind_reviews = int(args.get("minimum_blind_reviews") or 2)
    if minimum_blind_reviews < 2:
        raise ValueError("minimum_blind_reviews must be at least 2 independent reviewers")
    corpus_id = sanitize_id(args.get("corpus_id") or f"corpus-{uuid.uuid4().hex[:12]}")
    artifact = {
        "schema_version": 3,
        "artifact_type": "investment_model_evaluation_corpus",
        "corpus_id": corpus_id,
        "created_at": now_iso(),
        "created_by": _required_text(args, "created_by"),
        "research_only": True,
        "evaluation_profile": evaluation_profile,
        "cases": normalized_cases,
        "promotion_criteria": criteria,
        "minimum_blind_reviews": minimum_blind_reviews,
        "hard_failure_policy": {
            failure: {"check": check, "allowed": 0}
            for failure, check in HARD_FAILURE_CHECKS.items()
        },
        "pair_invariant_fields": list(PAIR_INVARIANT_FIELDS),
        "authority": "evaluation_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    artifact["corpus_hash"] = stable_hash(artifact)
    path = _path(root, CORPUS_ROOT, corpus_id)
    stored, status = _store(path, artifact, "corpus_hash")
    return _result(root, path, stored, status)


def record_evaluation_run(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    corpus = _load_corpus(root, _required_text(args, "corpus_id"))
    arm = str(args.get("arm") or "")
    if arm not in {"control", "candidate"}:
        raise ValueError("arm must be control or candidate")
    case_results, metrics, metric_samples = _case_results(root, corpus, args.get("case_results"))
    claimed_metrics = args.get("metrics")
    if claimed_metrics is not None:
        normalized_claim = _normalize_metrics(claimed_metrics, _metric_pairs(corpus))
        if not _metrics_match(normalized_claim, metrics):
            raise ValueError("reported run metrics do not match metrics derived from frozen case results")
    operations = _required_dict(args, "operations")
    budget = _required_dict(operations, "budget")
    run_id = sanitize_id(args.get("run_id") or f"eval-{arm}-{uuid.uuid4().hex[:12]}")
    artifact = {
        "schema_version": 3,
        "artifact_type": "investment_model_evaluation_run",
        "run_id": run_id,
        "corpus_id": corpus["corpus_id"],
        "corpus_hash": corpus["corpus_hash"],
        "arm": arm,
        "model": _required_text(args, "model"),
        "reasoning_effort": _required_text(args, "reasoning_effort"),
        "prompt_hash": _digest(args, "prompt_hash"),
        "config_hash": _digest(args, "config_hash"),
        "tool_profile_hash": _digest(args, "tool_profile_hash"),
        "deterministic_calculation_hash": _digest(args, "deterministic_calculation_hash"),
        "extension_profile_hash": _digest(args, "extension_profile_hash"),
        "evaluation_budget_hash": stable_hash(budget),
        "pair_provenance": {
            "status": PAIR_PROVENANCE_STATUS,
            "verified": False,
            "fields": list(PAIR_INVARIANT_FIELDS),
            "reason": "recording binds caller-attested digests but does not prove the model runtime, prompt, tools, calculations, or discovered host skills that produced the artifacts",
        },
        "created_at": _not_before(now_iso(), corpus["created_at"], "evaluation run"),
        "created_by": _required_text(args, "created_by"),
        "case_results": case_results,
        "metrics": metrics,
        "metric_samples": metric_samples,
        "metrics_source": "derived_from_frozen_case_results",
        "operations": operations,
        "hard_failures": [
            failure
            for result in case_results
            for failure in result["hard_failures"]
        ],
        "authority": "evaluation_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    artifact["run_hash"] = stable_hash(artifact)
    path = _path(root, RUN_ROOT, run_id)
    stored, status = _store(path, artifact, "run_hash")
    return _result(root, path, stored, status)


def create_blind_review_assignment(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    control = _load_run(root, _required_text(args, "control_run_id"))
    candidate = _load_run(root, _required_text(args, "candidate_run_id"))
    corpus = _validate_pair(root, control, candidate)
    assigned_by = _required_text(args, "assigned_by")
    reviewer = _required_text(args, "reviewer_principal")
    _require_principal_role(assigned_by, "head-manager")
    _require_principal_role(reviewer, "judgment-reviewer")
    if assigned_by == reviewer or reviewer in {control["created_by"], candidate["created_by"]}:
        raise ValueError("blind reviewer must be independent from assignment and run production")
    assignment_id = sanitize_id(args.get("assignment_id") or f"blind-assignment-{uuid.uuid4().hex[:12]}")
    if secrets.randbelow(2):
        run_a, run_b = candidate, control
    else:
        run_a, run_b = control, candidate
    packet = {
        "schema_version": 1,
        "artifact_type": "blind_evaluation_packet",
        "assignment_id": assignment_id,
        "corpus_id": corpus["corpus_id"],
        "cases": _blind_packet_cases(root, corpus, run_a, run_b),
        "model_identity_hidden": True,
        "authority": "evaluation_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    packet["packet_hash"] = stable_hash(packet)
    artifact = {
        "schema_version": 1,
        "artifact_type": "blind_evaluation_review_assignment",
        "assignment_id": assignment_id,
        "corpus_id": corpus["corpus_id"],
        "control_run_id": control["run_id"],
        "control_run_hash": control["run_hash"],
        "candidate_run_id": candidate["run_id"],
        "candidate_run_hash": candidate["run_hash"],
        "run_a_id": run_a["run_id"],
        "run_a_hash": run_a["run_hash"],
        "run_b_id": run_b["run_id"],
        "run_b_hash": run_b["run_hash"],
        "reviewer_principal": reviewer,
        "assigned_by": assigned_by,
        "created_at": _not_before(now_iso(), _latest_timestamp(control["created_at"], candidate["created_at"]), "blind review assignment"),
        "packet": packet,
        "packet_hash": packet["packet_hash"],
        "authority": "evaluation_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    artifact["assignment_hash"] = stable_hash(artifact)
    path = _path(root, ASSIGNMENT_ROOT, assignment_id)
    index_lock = root / ASSIGNMENT_ROOT / ".assignment-index"
    with exclusive_file_lock(index_lock):
        for existing_path in sorted((root / ASSIGNMENT_ROOT).glob("*.json")):
            existing = _verified_artifact(existing_path, "assignment_hash")
            if (
                existing.get("reviewer_principal") == reviewer
                and {existing.get("control_run_id"), existing.get("candidate_run_id")}
                == {control["run_id"], candidate["run_id"]}
            ):
                raise ValueError("reviewer already has a blind assignment for this run pair")
        stored, status = _store(path, artifact, "assignment_hash")
    return {
        "status": status,
        "assignment_id": stored["assignment_id"],
        "reviewer_principal": stored["reviewer_principal"],
        "blind_packet": stored["packet"],
        "artifact_hash": file_hash(path),
        "authority": "evaluation_only",
        "workspace_context": workspace_context_payload(root),
    }


def get_blind_review_packet(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    assignment = _load_assignment(root, _required_text(args, "assignment_id"))
    reviewer = _required_text(args, "reviewer")
    _require_principal_role(reviewer, "judgment-reviewer")
    if assignment["reviewer_principal"] != reviewer:
        raise PermissionError("blind review assignment belongs to a different authenticated reviewer")
    return {
        "assignment_id": assignment["assignment_id"],
        "blind_packet": assignment["packet"],
        "authority": "evaluation_only",
        "workspace_context": workspace_context_payload(root),
    }


def record_blind_human_review(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    assignment = _load_assignment(root, _required_text(args, "assignment_id"))
    reviewer = _required_text(args, "reviewer")
    _require_principal_role(reviewer, "judgment-reviewer")
    if assignment["reviewer_principal"] != reviewer:
        raise PermissionError("blind review assignment belongs to a different authenticated reviewer")
    run_a = _load_run(root, assignment["run_a_id"])
    run_b = _load_run(root, assignment["run_b_id"])
    if reviewer in {run_a["created_by"], run_b["created_by"], assignment["assigned_by"]}:
        raise ValueError("blind reviewer must be independent from assignment and run production")
    preference = str(args.get("preference") or "")
    if preference not in {"a", "b", "tie"}:
        raise ValueError("preference must be a, b, or tie")
    review_id = sanitize_id(args.get("review_id") or f"blind-{uuid.uuid4().hex[:12]}")
    artifact = {
        "schema_version": 2,
        "artifact_type": "blind_human_evaluation_review",
        "review_id": review_id,
        "assignment_id": assignment["assignment_id"],
        "assignment_hash": assignment["assignment_hash"],
        "packet_hash": assignment["packet_hash"],
        "corpus_id": assignment["corpus_id"],
        "run_a_id": run_a["run_id"],
        "run_a_hash": run_a["run_hash"],
        "run_b_id": run_b["run_id"],
        "run_b_hash": run_b["run_hash"],
        "model_identity_hidden_by_assignment": True,
        "reviewer_principal": reviewer,
        "preference": preference,
        "ratings": _required_dict(args, "ratings"),
        "rationale": _required_text(args, "rationale"),
        "created_at": _not_before(now_iso(), assignment["created_at"], "blind review"),
        "authority": "evaluation_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    artifact["review_hash"] = stable_hash(artifact)
    path = _path(root, REVIEW_ROOT, review_id)
    index_lock = root / REVIEW_ROOT / ".review-index"
    with exclusive_file_lock(index_lock):
        for existing_path in sorted((root / REVIEW_ROOT).glob("*.json")):
            existing = _verified_artifact(existing_path, "review_hash")
            if existing.get("assignment_id") == assignment["assignment_id"]:
                raise ValueError("blind assignment already has a submitted review")
        stored, status = _store(path, artifact, "review_hash")
    return _result(root, path, stored, status)


def compare_evaluation_runs(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    control = _load_run(root, _required_text(args, "control_run_id"))
    candidate = _load_run(root, _required_text(args, "candidate_run_id"))
    corpus = _validate_pair(root, control, candidate)
    reasons: list[str] = []
    if not _pair_provenance_verified(control, candidate):
        reasons.append("paired run provenance is caller-attested and not verified by a trusted evaluation runner")
    if candidate["hard_failures"]:
        reasons.append("candidate has hard safety, evidence, scope, or tool-use failures")
    candidate_by_case = {item["case_id"]: item for item in candidate["case_results"]}
    for case in corpus["cases"]:
        result = candidate_by_case.get(case["case_id"])
        if not result or any(
            result["deterministic_checks"].get(check) != expected
            for check, expected in case["expected_checks"].items()
        ):
            reasons.append(f"candidate failed deterministic case checks: {case['case_id']}")
    criterion_results = []
    for criterion in corpus["promotion_criteria"]:
        dimension = criterion["dimension"]
        metric = criterion["metric"]
        control_value = _finite_decimal(control["metrics"][dimension][metric], f"control {dimension}.{metric}")
        candidate_value = _finite_decimal(candidate["metrics"][dimension][metric], f"candidate {dimension}.{metric}")
        regression = (
            control_value - candidate_value
            if criterion["direction"] == "higher_is_better"
            else candidate_value - control_value
        )
        passed = regression <= _finite_decimal(criterion["max_regression"], "max_regression")
        minimum = criterion.get("minimum_candidate")
        if minimum is not None:
            threshold = _finite_decimal(minimum, "minimum_candidate")
            passed = passed and (
                candidate_value >= threshold
                if criterion["direction"] == "higher_is_better"
                else candidate_value <= threshold
            )
        criterion_results.append({
            **criterion,
            "control": float(control_value),
            "candidate": float(candidate_value),
            "regression": float(regression),
            "passed": passed,
        })
        if not passed:
            reasons.append(f"candidate missed promotion criterion: {dimension}.{metric}")
    reviews = _matching_reviews(root, control, candidate)
    if len(reviews) < int(corpus["minimum_blind_reviews"]):
        reasons.append("insufficient independent blind human reviews")
    else:
        candidate_losses = 0
        candidate_wins = 0
        for review in reviews:
            candidate_letter = "a" if review["run_a_id"] == candidate["run_id"] else "b"
            if review["preference"] == candidate_letter:
                candidate_wins += 1
            elif review["preference"] != "tie":
                candidate_losses += 1
        if candidate_losses > candidate_wins:
            reasons.append("candidate lost the blinded human non-inferiority review")
    comparison_id = sanitize_id(args.get("comparison_id") or f"compare-{control['run_id']}-{candidate['run_id']}")
    artifact = {
        "schema_version": 3,
        "artifact_type": "investment_model_evaluation_comparison",
        "comparison_id": comparison_id,
        "corpus_id": corpus["corpus_id"],
        "corpus_hash": corpus["corpus_hash"],
        "control_run_id": control["run_id"],
        "control_run_hash": control["run_hash"],
        "candidate_run_id": candidate["run_id"],
        "candidate_run_hash": candidate["run_hash"],
        "pair_invariants": {field: control[field] for field in PAIR_INVARIANT_FIELDS},
        "pair_provenance": {
            "control": control.get("pair_provenance"),
            "candidate": candidate.get("pair_provenance"),
            "verified": _pair_provenance_verified(control, candidate),
        },
        "criterion_results": criterion_results,
        "blind_review_ids": [review["review_id"] for review in reviews],
        "blind_reviewer_principals": [review["reviewer_principal"] for review in reviews],
        "decision": "promote" if not reasons else "hold",
        "reasons": reasons,
        "created_at": _not_before(
            now_iso(),
            _latest_timestamp(control["created_at"], candidate["created_at"], *(review["created_at"] for review in reviews)),
            "evaluation comparison",
        ),
        "authority": "evaluation_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    artifact["comparison_hash"] = stable_hash(artifact)
    path = _path(root, COMPARISON_ROOT, comparison_id)
    stored, status = _store(path, artifact, "comparison_hash")
    return _result(root, path, stored, status)


def _promotion_criteria(value: Any, metric_dimensions: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("promotion_criteria must be a non-empty list established after baseline measurement")
    criteria = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"promotion_criteria[{index}] must be an object")
        dimension = str(raw.get("dimension") or "")
        direction = str(raw.get("direction") or "")
        if dimension not in metric_dimensions or direction not in {"higher_is_better", "lower_is_better"}:
            raise ValueError(f"promotion_criteria[{index}] has invalid dimension or direction")
        metric = _required_text(raw, "metric")
        key = (dimension, metric)
        if key in seen:
            raise ValueError(f"duplicate promotion criterion: {dimension}.{metric}")
        seen.add(key)
        max_regression = _finite_decimal(raw.get("max_regression", 0), f"promotion_criteria[{index}].max_regression")
        if max_regression < 0:
            raise ValueError(f"promotion_criteria[{index}].max_regression must be non-negative")
        minimum = raw.get("minimum_candidate")
        criteria.append({
            "dimension": dimension,
            "metric": metric,
            "aggregation": "mean_across_frozen_cases",
            "direction": direction,
            "max_regression": float(max_regression),
            "minimum_candidate": float(_finite_decimal(minimum, f"promotion_criteria[{index}].minimum_candidate")) if minimum is not None else None,
        })
    return criteria


def _case_results(
    root: Path,
    corpus: dict[str, Any],
    value: Any,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]], dict[str, dict[str, int]]]:
    if not isinstance(value, list):
        raise ValueError("case_results must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"case_results[{index}] must be an object")
        case_id = str(item.get("case_id") or "")
        if case_id in by_id:
            raise ValueError(f"duplicate evaluation case result: {case_id}")
        by_id[case_id] = item
    expected_ids = {item["case_id"] for item in corpus["cases"]}
    if set(by_id) != expected_ids or len(value) != len(expected_ids):
        raise ValueError("case_results must contain every frozen corpus case exactly once")
    metric_pairs = _metric_pairs(corpus)
    metric_totals = {
        dimension: {metric: Decimal("0") for metric in metrics}
        for dimension, metrics in metric_pairs.items()
    }
    results = []
    for case in corpus["cases"]:
        raw = by_id[case["case_id"]]
        if "hard_failures" in raw:
            raise ValueError(f"case {case['case_id']} hard_failures are derived and must not be caller supplied")
        checks = raw.get("deterministic_checks")
        if not isinstance(checks, dict) or set(checks) != set(case["expected_checks"]):
            raise ValueError(f"case {case['case_id']} deterministic checks do not match the corpus")
        if any(not isinstance(item, bool) for item in checks.values()):
            raise ValueError(f"case {case['case_id']} deterministic checks must be boolean")
        artifact_hashes = _artifact_hashes(root, case["case_id"], raw.get("artifact_hashes"))
        metric_values = _normalize_metrics(raw.get("metrics"), metric_pairs)
        for dimension, values in metric_values.items():
            for metric, item in values.items():
                metric_totals[dimension][metric] += _finite_decimal(item, f"case {case['case_id']} metric")
        hard_failures = [
            {"case_id": case["case_id"], "failure_type": failure, "failed_check": check}
            for failure, check in HARD_FAILURE_CHECKS.items()
            if checks[check] is not True
        ]
        results.append({
            "case_id": case["case_id"],
            "replay_manifest_hash": case["replay_manifest_hash"],
            "deterministic_checks": dict(sorted(checks.items())),
            "artifact_hashes": artifact_hashes,
            "metrics": metric_values,
            "hard_failures": hard_failures,
        })
    sample_count = len(results)
    metrics = {
        dimension: {
            metric: float(total / Decimal(sample_count))
            for metric, total in values.items()
        }
        for dimension, values in metric_totals.items()
    }
    samples = {
        dimension: {metric: sample_count for metric in values}
        for dimension, values in metric_totals.items()
    }
    return results, metrics, samples


def _artifact_hashes(root: Path, case_id: str, value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"case {case_id} requires artifact_hashes")
    normalized: dict[str, str] = {}
    for raw_path, raw_digest in value.items():
        rel = _nonempty_text(raw_path, f"case {case_id} artifact path")
        digest = _digest_text(raw_digest, f"case {case_id} artifact hash")
        path = safe_workspace_path(root, rel, allowed_roots=CASE_ARTIFACT_ROOTS)
        actual = file_hash(path)
        if actual is None:
            raise ValueError(f"case {case_id} artifact does not exist: {rel}")
        if actual != digest:
            raise ValueError(f"case {case_id} artifact hash mismatch: {rel}")
        normalized[Path(rel).as_posix()] = actual
    return dict(sorted(normalized.items()))


def _normalize_metrics(value: Any, pairs: dict[str, set[str]]) -> dict[str, dict[str, float]]:
    if not isinstance(value, dict) or set(value) != set(pairs):
        raise ValueError("metrics must exactly match the frozen promotion metric dimensions")
    result: dict[str, dict[str, float]] = {}
    for dimension, metrics in pairs.items():
        raw = value.get(dimension)
        if not isinstance(raw, dict) or set(raw) != metrics:
            raise ValueError(f"metrics.{dimension} must exactly match frozen promotion metrics")
        result[dimension] = {
            metric: float(_finite_decimal(raw[metric], f"metrics.{dimension}.{metric}"))
            for metric in sorted(metrics)
        }
    return result


def _metrics_match(left: dict[str, dict[str, float]], right: dict[str, dict[str, float]]) -> bool:
    return all(
        _finite_decimal(left[dimension][metric], "reported metric")
        == _finite_decimal(right[dimension][metric], "derived metric")
        for dimension in right
        for metric in right[dimension]
    )


def _metric_pairs(corpus: dict[str, Any]) -> dict[str, set[str]]:
    pairs: dict[str, set[str]] = {}
    for criterion in corpus["promotion_criteria"]:
        pairs.setdefault(criterion["dimension"], set()).add(criterion["metric"])
    return pairs


def _expected_checks(value: Any, case_index: int) -> dict[str, bool]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"cases[{case_index}].expected_checks must be a non-empty object")
    if any(not isinstance(item, bool) for item in value.values()):
        raise ValueError(f"cases[{case_index}].expected_checks values must be boolean")
    missing = set(HARD_FAILURE_CHECKS.values()) - set(value)
    if missing:
        raise ValueError(f"cases[{case_index}].expected_checks missing hard invariants: {', '.join(sorted(missing))}")
    invalid = [check for check in HARD_FAILURE_CHECKS.values() if value.get(check) is not True]
    if invalid:
        raise ValueError(f"cases[{case_index}] hard invariant expectations must be true: {', '.join(sorted(invalid))}")
    return {str(key): value[key] for key in sorted(value)}


def _has_distinct_tag_coverage(cases: list[dict[str, Any]], required_case_tags: set[str]) -> bool:
    matched_case: dict[int, str] = {}

    def assign(tag: str, seen: set[int]) -> bool:
        for index, case in enumerate(cases):
            if index in seen or tag not in case["tags"]:
                continue
            seen.add(index)
            previous = matched_case.get(index)
            if previous is None or assign(previous, seen):
                matched_case[index] = tag
                return True
        return False

    return all(assign(tag, set()) for tag in sorted(required_case_tags))


def _evaluation_profile(args: dict[str, Any]) -> dict[str, Any]:
    profile_id = sanitize_id(args.get("evaluation_profile") or CORE_EVALUATION_PROFILE_ID)
    bundled = BUILTIN_EVALUATION_PROFILES.get(profile_id)
    if bundled:
        return {"id": profile_id, **bundled}
    required_case_tags = sorted({_nonempty_text(item, "required_case_tags") for item in _required_list(args, "required_case_tags")})
    metric_dimensions = sorted({_nonempty_text(item, "metric_dimensions") for item in _required_list(args, "metric_dimensions")})
    return {
        "id": profile_id,
        "source": "corpus_defined",
        "required_case_tags": required_case_tags,
        "metric_dimensions": metric_dimensions,
    }


def _blind_packet_cases(
    root: Path,
    corpus: dict[str, Any],
    run_a: dict[str, Any],
    run_b: dict[str, Any],
) -> list[dict[str, Any]]:
    a_results = {item["case_id"]: item for item in run_a["case_results"]}
    b_results = {item["case_id"]: item for item in run_b["case_results"]}
    return [
        {
            "case_id": case["case_id"],
            "rubric": case["blind_review_rubric"],
            "side_a_artifacts": _blind_artifacts(root, a_results[case["case_id"]], run_a),
            "side_b_artifacts": _blind_artifacts(root, b_results[case["case_id"]], run_b),
        }
        for case in corpus["cases"]
    ]


def _blind_artifacts(root: Path, result: dict[str, Any], run: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = []
    for index, (rel, digest) in enumerate(sorted(result["artifact_hashes"].items()), start=1):
        path = safe_workspace_path(root, rel, allowed_roots=CASE_ARTIFACT_ROOTS)
        data = path.read_bytes()
        if len(data) > MAX_BLIND_ARTIFACT_BYTES:
            raise ValueError(f"blind review artifact exceeds {MAX_BLIND_ARTIFACT_BYTES} bytes: {rel}")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"blind review artifacts must be UTF-8 text: {rel}") from exc
        for hidden in (str(run.get("model") or ""), str(run.get("run_id") or "")):
            if hidden:
                content = content.replace(hidden, "[identity-hidden]")
        artifacts.append({
            "artifact_label": f"artifact-{index}",
            "source_sha256": digest,
            "blind_content_sha256": stable_hash(content),
            "content": content,
        })
    return artifacts


def _matching_reviews(root: Path, control: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    base = root / REVIEW_ROOT
    if not base.exists():
        return []
    expected = {control["run_id"], candidate["run_id"]}
    reviews = []
    reviewers = set()
    for path in sorted(base.glob("*.json")):
        review = _verified_artifact(path, "review_hash")
        if {review.get("run_a_id"), review.get("run_b_id")} != expected:
            continue
        assignment = _load_assignment(root, str(review.get("assignment_id") or ""))
        reviewer = str(review.get("reviewer_principal") or "")
        if (
            assignment["assignment_hash"] != review.get("assignment_hash")
            or assignment["packet_hash"] != review.get("packet_hash")
            or assignment["reviewer_principal"] != reviewer
        ):
            raise ValueError(f"blind review assignment binding mismatch: {path.stem}")
        _not_before(review["created_at"], assignment["created_at"], "blind review")
        if reviewer and reviewer not in reviewers:
            reviewers.add(reviewer)
            reviews.append(review)
    return reviews


def _validate_pair(root: Path, control: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if control["arm"] != "control" or candidate["arm"] != "candidate":
        raise ValueError("comparison requires explicit control and candidate arms")
    if control["corpus_id"] != candidate["corpus_id"] or control["corpus_hash"] != candidate["corpus_hash"]:
        raise ValueError("comparison runs must use the exact same frozen corpus")
    if control["model"] == candidate["model"]:
        raise ValueError("paired model evaluation requires distinct control and candidate models")
    mismatched = [field for field in PAIR_INVARIANT_FIELDS if control.get(field) != candidate.get(field)]
    if mismatched:
        raise ValueError(f"paired evaluation run invariants differ: {', '.join(mismatched)}")
    corpus = _load_corpus(root, control["corpus_id"])
    if corpus["corpus_hash"] != control["corpus_hash"]:
        raise ValueError("evaluation run corpus hash no longer matches the frozen corpus")
    return corpus


def _pair_provenance_verified(control: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return all(
        isinstance(run.get("pair_provenance"), dict)
        and run["pair_provenance"].get("verified") is True
        and run["pair_provenance"].get("status") == "trusted_runner_verified"
        for run in (control, candidate)
    )


def _load_corpus(root: Path, corpus_id: str) -> dict[str, Any]:
    path = _path(root, CORPUS_ROOT, corpus_id)
    if not path.exists():
        raise ValueError(f"evaluation corpus not found: {corpus_id}")
    corpus = _verified_artifact(path, "corpus_hash")
    for case in corpus.get("cases", []):
        manifest_path = _path(root, REPLAY_ROOT, str(case.get("replay_manifest_id") or ""))
        if not manifest_path.exists():
            raise ValueError(f"replay manifest not found: {case.get('replay_manifest_id')}")
        manifest = _verified_artifact(manifest_path, "manifest_hash")
        if manifest.get("manifest_hash") != case.get("replay_manifest_hash"):
            raise ValueError(f"replay manifest changed after corpus freeze: {case.get('replay_manifest_id')}")
    return corpus


def _load_run(root: Path, run_id: str) -> dict[str, Any]:
    path = _path(root, RUN_ROOT, run_id)
    if not path.exists():
        raise ValueError(f"evaluation run not found: {run_id}")
    run = _verified_artifact(path, "run_hash")
    for result in run.get("case_results", []):
        _artifact_hashes(root, str(result.get("case_id") or ""), result.get("artifact_hashes"))
    return run


def _load_assignment(root: Path, assignment_id: str) -> dict[str, Any]:
    path = _path(root, ASSIGNMENT_ROOT, assignment_id)
    if not path.exists():
        raise ValueError(f"blind review assignment not found: {assignment_id}")
    assignment = _verified_artifact(path, "assignment_hash")
    packet = dict(assignment.get("packet") or {})
    packet_hash = _digest_text(assignment.get("packet_hash"), "packet_hash")
    embedded_hash = packet.pop("packet_hash", None)
    if embedded_hash != packet_hash or stable_hash(packet) != packet_hash:
        raise ValueError(f"blind review packet hash mismatch: {assignment_id}")
    return assignment


def _verified_artifact(path: Path, hash_field: str) -> dict[str, Any]:
    artifact = _read_object(path)
    expected = _digest_text(artifact.get(hash_field), hash_field)
    payload = dict(artifact)
    payload.pop(hash_field, None)
    if stable_hash(payload) != expected:
        raise ValueError(f"evaluation artifact hash mismatch: {path}")
    return artifact


def _require_principal_role(principal_id: str, required_role: str) -> None:
    try:
        from apps.policy.models import Principal
    except Exception as exc:  # pragma: no cover - Django setup errors are surfaced as denial
        raise PermissionError("canonical principal state is unavailable") from exc
    principal = Principal.objects.filter(principal_id=principal_id, active=True).first()
    if principal is None or principal.role != required_role:
        raise PermissionError(f"{principal_id} must be an active {required_role} principal")


def _path(root: Path, base: Path, artifact_id: str) -> Path:
    return safe_workspace_path(root, base / f"{sanitize_id(artifact_id)}.json", allowed_roots=(base,))


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid evaluation artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"evaluation artifact must be an object: {path}")
    return value


def _store(path: Path, artifact: dict[str, Any], hash_field: str) -> tuple[dict[str, Any], str]:
    with exclusive_file_lock(path):
        if path.exists():
            existing = _verified_artifact(path, hash_field)
            if existing.get(hash_field) == artifact.get(hash_field):
                return existing, "existing"
            raise ValueError(f"immutable evaluation artifact already exists: {path.stem}")
        atomic_write_text(path, json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    return artifact, "recorded"


def _result(root: Path, path: Path, artifact: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "artifact": artifact,
        "export_path": path.relative_to(root).as_posix(),
        "artifact_hash": file_hash(path),
        "authority": "evaluation_only",
        "workspace_context": workspace_context_payload(root),
    }


def _required_text(value: dict[str, Any], field: str) -> str:
    text = str(value.get(field) or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _nonempty_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must contain non-empty strings")
    return text


def _required_list(value: dict[str, Any], field: str) -> list[Any]:
    result = value.get(field)
    if not isinstance(result, list) or not result:
        raise ValueError(f"{field} must be a non-empty list")
    return result


def _required_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = value.get(field)
    if not isinstance(result, dict) or not result:
        raise ValueError(f"{field} must be a non-empty object")
    return result


def _digest(value: dict[str, Any], field: str) -> str:
    return _digest_text(_required_text(value, field), field)


def _digest_text(value: Any, field: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field} must be a 64-character hexadecimal digest")
    return digest


def _finite_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return number


def _not_before(value: str, earlier: str, label: str) -> str:
    if _parse_time(value) < _parse_time(earlier):
        raise ValueError(f"{label} timestamp precedes its required inputs")
    return value


def _parse_time(value: Any) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("evaluation timestamps must be valid ISO-8601 values") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("evaluation timestamps must be timezone-aware")
    return parsed


def _latest_timestamp(*values: str) -> str:
    if not values:
        raise ValueError("at least one evaluation timestamp is required")
    return max(values, key=_parse_time)
