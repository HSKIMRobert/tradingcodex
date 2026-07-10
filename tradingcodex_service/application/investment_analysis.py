from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
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
from tradingcodex_service.application.research_specs import get_research_spec
from tradingcodex_service.application.runtime import workspace_context_payload

ANALYSIS_ROOT = Path("trading/research/analyses")
REPLAY_ROOT = Path("trading/research/replay-manifests")
PRIOR_ROOT = Path("trading/research/judgment-priors")
REVIEW_ROOT = Path("trading/research/judgment-reviews")
SOURCE_SNAPSHOT_ROOT = Path("trading/research/source-snapshots")
JUDGMENT_LIFECYCLE_LOCK = Path("trading/research/judgment-lifecycle")
ANALYSIS_PROTOCOL = "frozen_causal_scenarios_v1"
METHOD_PROFILE = "listed_equity_fcff_dcf_v1"
VALUATION_METHOD = "fcff_revenue_margin_dcf_v1"
ANALYSIS_SOURCE_KEY = VALUATION_METHOD
SCENARIO_DRIVER_FIELDS = {
    "revenue_growth",
    "operating_margin",
    "tax_rate",
    "sales_to_capital",
    "discount_rate",
    "terminal_growth",
}
CALLER_INJECTED_ANALYSIS_FIELDS = {
    "instrument",
    "inputs",
    "scenarios",
    "other_method_values",
    "contrary_evidence",
    "update_triggers",
    "invalidation_conditions",
    "investor_profile_gaps",
}


def create_causal_equity_analysis(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic reverse/forward DCF arithmetic against a frozen ResearchSpec."""

    root = Path(workspace_root).expanduser().resolve()
    injected = sorted(CALLER_INJECTED_ANALYSIS_FIELDS.intersection(args))
    if injected:
        raise ValueError(
            "causal analysis values must come from the selected replay snapshot, not caller fields: "
            + ", ".join(injected)
        )
    spec_id = _required_text(args, "spec_id")
    spec = get_research_spec(root, {"spec_id": spec_id})["artifact"]
    _verify_embedded_hash(spec, "analysis_plan_hash", "ResearchSpec")
    if spec.get("method_profile") != METHOD_PROFILE:
        raise ValueError(f"causal equity analysis requires the explicit {METHOD_PROFILE} ResearchSpec profile")
    instrument = _required_text(spec, "instrument")
    manifest_id = _required_text(args, "replay_manifest_id")
    manifest_path = _json_path(root, REPLAY_ROOT, manifest_id)
    if not manifest_path.exists():
        raise ValueError(f"replay manifest not found: {manifest_id}")
    manifest = _read_object(manifest_path)
    _verify_embedded_hash(manifest, "manifest_hash", "replay manifest")
    if manifest.get("spec_id") != spec_id or manifest.get("analysis_plan_hash") != spec.get("analysis_plan_hash"):
        raise ValueError("replay manifest does not match the frozen ResearchSpec")
    source_binding, source_values = _load_analysis_source(
        root,
        manifest,
        _required_text(args, "analysis_input_snapshot_id"),
        spec["knowledge_cutoff"],
    )
    if _required_text(source_values, "instrument") != instrument:
        raise ValueError("analysis source instrument does not match the frozen ResearchSpec")
    inputs = _analysis_inputs(source_values.get("inputs"))
    raw_scenarios = source_values.get("scenarios")
    _reconcile_scenarios(spec.get("scenario_plan"), raw_scenarios)
    scenarios = _scenario_results(inputs, raw_scenarios)
    reverse = _reverse_dcf(inputs)
    market_price = inputs["current_price"]
    methods = [
        {"method": "reverse_dcf_market_anchor", "per_share": _text(market_price)},
        *[
            {"method": f"forward_dcf:{item['name']}", "per_share": item["per_share"]}
            for item in scenarios
        ],
        *_validated_method_values(source_values.get("other_method_values")),
    ]
    values = [_decimal(item["per_share"], f"method {item['method']} per_share") for item in methods]
    weighted_forward = sum(
        _decimal(item["weight"], "scenario weight") * _decimal(item["per_share"], "scenario per_share")
        for item in scenarios
    )
    created_at = now_iso()
    prior = _load_prior(root, _required_text(args, "prior_id"), spec, created_at)
    created_by = _required_text(args, "created_by")
    if created_by == prior.get("reviewer"):
        raise ValueError("causal analysis producer must differ from the blind-prior reviewer")
    analysis_id = sanitize_id(args.get("analysis_id") or f"analysis-{spec_id}-{uuid.uuid4().hex[:12]}")
    artifact = {
        "schema_version": 2,
        "artifact_type": "causal_equity_analysis",
        "analysis_id": analysis_id,
        "analysis_protocol": ANALYSIS_PROTOCOL,
        "method_profile": METHOD_PROFILE,
        "valuation_method": VALUATION_METHOD,
        "method_sequence": ["market_implied_reverse_dcf", "scenario_forward_dcf"],
        "spec_id": spec_id,
        "analysis_plan_hash": spec["analysis_plan_hash"],
        "replay_manifest_id": manifest_id,
        "replay_manifest_hash": manifest["manifest_hash"],
        "replay_manifest_file_hash": file_hash(manifest_path),
        "analysis_source": source_binding,
        "blind_prior_binding": {
            "prior_id": prior["prior_id"],
            "prior_hash": prior["prior_hash"],
            "reviewer": prior["reviewer"],
            "created_at": prior["created_at"],
        },
        "knowledge_cutoff": spec["knowledge_cutoff"],
        "created_at": created_at,
        "created_by": created_by,
        "instrument": instrument,
        "driver_tree": spec["driver_tree"],
        "base_rate_cohort": spec["base_rate_cohort"],
        "market_anchor": {
            "current_price": _text(inputs["current_price"]),
            "shares_outstanding": _text(inputs["shares_outstanding"]),
            "net_debt": _text(inputs["net_debt"]),
            "implied_enterprise_value": _text(inputs["target_enterprise_value"]),
        },
        "reverse_dcf": reverse,
        "forward_scenarios": scenarios,
        "weighted_forward_value_per_share": _text(weighted_forward),
        "method_reconciliation": {
            "methods": methods,
            "minimum_per_share": _text(min(values)),
            "maximum_per_share": _text(max(values)),
            "spread_per_share": _text(max(values) - min(values)),
            "policy": "preserve disagreement; do not average incompatible methods",
        },
        "contrary_evidence": _required_list(source_values, "contrary_evidence"),
        "update_triggers": _required_list(source_values, "update_triggers"),
        "invalidation_conditions": _required_list(source_values, "invalidation_conditions"),
        "investor_profile_gaps": (
            source_values.get("investor_profile_gaps")
            if isinstance(source_values.get("investor_profile_gaps"), list)
            else []
        ),
        "calculation_manifest": {
            "engine": f"tradingcodex.{VALUATION_METHOD}.v1",
            "formulas": [
                "revenue_t = revenue_(t-1) * (1 + growth)",
                "nopat_t = revenue_t * operating_margin * (1 - tax_rate)",
                "reinvestment_t = change_in_revenue / sales_to_capital",
                "terminal_revenue = revenue_n * (1 + terminal_growth)",
                "terminal_fcff = terminal_nopat - terminal_reinvestment",
                "terminal_value = terminal_fcff / (discount_rate - terminal_growth)",
                "equity_value_per_share = (enterprise_value - net_debt) / shares_outstanding",
            ],
            "input_hash": stable_hash(_canonical_numeric_inputs(inputs)),
            "scenario_config_hash": stable_hash(scenarios),
            "source_snapshot_ids": [item["snapshot_id"] for item in manifest["snapshots"]],
        },
        "authority": "evidence_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    artifact["analysis_hash"] = stable_hash(artifact)
    path = _json_path(root, ANALYSIS_ROOT, analysis_id)
    with exclusive_file_lock(root / JUDGMENT_LIFECYCLE_LOCK):
        # Re-read under the lifecycle lock so a concurrent writer cannot backfill a prior.
        prior = _load_prior(root, prior["prior_id"], spec, created_at)
        if artifact["blind_prior_binding"]["prior_hash"] != prior["prior_hash"]:
            raise ValueError("blind prior changed before analysis storage")
        stored, status = _store_immutable(path, artifact, "analysis_hash")
    return _result(root, path, stored, status)


def record_blind_judgment_prior(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    spec_id = _required_text(args, "spec_id")
    spec = get_research_spec(root, {"spec_id": spec_id})["artifact"]
    _verify_embedded_hash(spec, "analysis_plan_hash", "ResearchSpec")
    reviewer = _required_text(args, "reviewer")
    if reviewer == spec.get("created_by"):
        raise ValueError("independent reviewer must differ from the ResearchSpec owner")
    prior_id = sanitize_id(args.get("prior_id") or f"prior-{spec_id}-{reviewer}")
    artifact = {
        "schema_version": 1,
        "artifact_type": "blind_judgment_prior",
        "prior_id": prior_id,
        "spec_id": spec_id,
        "analysis_plan_hash": spec["analysis_plan_hash"],
        "instrument": str(spec.get("instrument") or ""),
        "reviewer": reviewer,
        "created_at": now_iso(),
        "blind_to_producer_conclusion": True,
        "specification_view": _required_text(args, "specification_view"),
        "evidence_quality_view": _required_text(args, "evidence_quality_view"),
        "key_driver_view": _required_list(args, "key_driver_view"),
        "falsifiers": _required_list(args, "falsifiers"),
        "authority": "evidence_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    artifact["prior_hash"] = stable_hash(artifact)
    path = _json_path(root, PRIOR_ROOT, prior_id)
    with exclusive_file_lock(root / JUDGMENT_LIFECYCLE_LOCK):
        if _analysis_exists_for_spec(root, spec_id):
            raise ValueError("blind judgment prior must be recorded before any causal analysis for the ResearchSpec")
        stored, status = _store_immutable(path, artifact, "prior_hash")
    return _result(root, path, stored, status)


def complete_judgment_review(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    prior_id = _required_text(args, "prior_id")
    analysis_id = _required_text(args, "analysis_id")
    prior_path = _json_path(root, PRIOR_ROOT, prior_id)
    analysis_path = _json_path(root, ANALYSIS_ROOT, analysis_id)
    if not prior_path.exists() or not analysis_path.exists():
        raise ValueError("judgment review requires an immutable blind prior and causal analysis")
    prior = _read_object(prior_path)
    analysis = _read_object(analysis_path)
    _verify_embedded_hash(prior, "prior_hash", "blind prior")
    _verify_embedded_hash(analysis, "analysis_hash", "causal analysis")
    reviewer = _required_text(args, "reviewer")
    if reviewer != prior.get("reviewer"):
        raise PermissionError("only the blind-prior reviewer may complete the second pass")
    if prior.get("spec_id") != analysis.get("spec_id"):
        raise ValueError("blind prior and analysis do not share the same ResearchSpec")
    binding = analysis.get("blind_prior_binding") if isinstance(analysis.get("blind_prior_binding"), dict) else {}
    if (
        binding.get("prior_id") != prior_id
        or binding.get("prior_hash") != prior.get("prior_hash")
        or binding.get("reviewer") != prior.get("reviewer")
    ):
        raise ValueError("causal analysis is not bound to this blind prior")
    if _parse_iso(prior.get("created_at"), "blind prior created_at") >= _parse_iso(
        analysis.get("created_at"), "causal analysis created_at"
    ):
        raise ValueError("blind prior must precede the causal analysis")
    review_id = sanitize_id(args.get("review_id") or f"review-{analysis_id}-{reviewer}")
    artifact = {
        "schema_version": 1,
        "artifact_type": "two_pass_judgment_review",
        "review_id": review_id,
        "prior_id": prior_id,
        "prior_hash": prior["prior_hash"],
        "analysis_id": analysis_id,
        "analysis_hash": analysis["analysis_hash"],
        "reviewer": reviewer,
        "created_at": now_iso(),
        "conclusion": _required_text(args, "conclusion"),
        "changed_views": args.get("changed_views") if isinstance(args.get("changed_views"), list) else [],
        "remaining_disagreements": _required_list(args, "remaining_disagreements"),
        "acceptance": str(args.get("acceptance") or "revise"),
        "authority": "evidence_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    if artifact["acceptance"] not in {"accepted", "revise", "blocked"}:
        raise ValueError("acceptance must be accepted, revise, or blocked")
    artifact["review_hash"] = stable_hash(artifact)
    path = _json_path(root, REVIEW_ROOT, review_id)
    stored, status = _store_immutable(path, artifact, "review_hash")
    return _result(root, path, stored, status)


def _analysis_inputs(value: Any) -> dict[str, Decimal | int]:
    if not isinstance(value, dict):
        raise ValueError("inputs must be an object")
    result: dict[str, Decimal | int] = {
        "current_revenue": _positive(value.get("current_revenue"), "current_revenue"),
        "current_price": _positive(value.get("current_price"), "current_price"),
        "shares_outstanding": _positive(value.get("shares_outstanding"), "shares_outstanding"),
        "net_debt": _decimal(value.get("net_debt"), "net_debt"),
        "operating_margin": _rate(value.get("operating_margin"), "operating_margin", minimum=Decimal("-1")),
        "tax_rate": _rate(value.get("tax_rate"), "tax_rate"),
        "sales_to_capital": _positive(value.get("sales_to_capital"), "sales_to_capital"),
        "discount_rate": _rate(value.get("discount_rate"), "discount_rate", minimum=Decimal("0.000001")),
        "terminal_growth": _rate(value.get("terminal_growth"), "terminal_growth", minimum=Decimal("-0.99")),
        "forecast_years": int(value.get("forecast_years") or 5),
    }
    if not 1 <= int(result["forecast_years"]) <= 20:
        raise ValueError("forecast_years must be between 1 and 20")
    if result["discount_rate"] <= result["terminal_growth"]:
        raise ValueError("discount_rate must exceed terminal_growth")
    result["target_enterprise_value"] = result["current_price"] * result["shares_outstanding"] + result["net_debt"]
    return result


def _scenario_results(inputs: dict[str, Any], value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("scenarios must contain at least two mutually exclusive cases")
    results = []
    total_weight = Decimal("0")
    for index, scenario in enumerate(value, start=1):
        if not isinstance(scenario, dict):
            raise ValueError(f"scenario {index} must be an object")
        weight = _rate(scenario.get("weight"), f"scenario {index} weight")
        total_weight += weight
        drivers = {
            "revenue_growth": _rate(scenario.get("revenue_growth"), f"scenario {index} revenue_growth", minimum=Decimal("-0.99")),
            "operating_margin": _rate(scenario.get("operating_margin"), f"scenario {index} operating_margin", minimum=Decimal("-1")),
            "tax_rate": _rate(scenario.get("tax_rate", inputs["tax_rate"]), f"scenario {index} tax_rate"),
            "sales_to_capital": _positive(scenario.get("sales_to_capital", inputs["sales_to_capital"]), f"scenario {index} sales_to_capital"),
            "discount_rate": _rate(scenario.get("discount_rate", inputs["discount_rate"]), f"scenario {index} discount_rate", minimum=Decimal("0.000001")),
            "terminal_growth": _rate(scenario.get("terminal_growth", inputs["terminal_growth"]), f"scenario {index} terminal_growth", minimum=Decimal("-0.99")),
        }
        if drivers["discount_rate"] <= drivers["terminal_growth"]:
            raise ValueError(f"scenario {index} discount_rate must exceed terminal_growth")
        enterprise_value = _dcf_enterprise_value(inputs, drivers)
        per_share = (enterprise_value - inputs["net_debt"]) / inputs["shares_outstanding"]
        results.append({
            "name": _required_text(scenario, "name"),
            "weight": _text(weight),
            "drivers": {key: _text(item) for key, item in drivers.items()},
            "enterprise_value": _text(enterprise_value),
            "per_share": _text(per_share),
            "assumptions": _required_list(scenario, "assumptions"),
        })
    if abs(total_weight - Decimal("1")) > Decimal("0.000000001"):
        raise ValueError("scenario weights must sum to 1")
    return results


def _reverse_dcf(inputs: dict[str, Any]) -> dict[str, Any]:
    low = Decimal("-0.50")
    high = Decimal("1.00")
    target = inputs["target_enterprise_value"]
    common = {
        "operating_margin": inputs["operating_margin"],
        "tax_rate": inputs["tax_rate"],
        "sales_to_capital": inputs["sales_to_capital"],
        "discount_rate": inputs["discount_rate"],
        "terminal_growth": inputs["terminal_growth"],
    }
    step_count = 600
    step = (high - low) / step_count
    samples: list[tuple[Decimal, Decimal, Decimal]] = []
    for index in range(step_count + 1):
        growth = low + step * index
        value = _dcf_enterprise_value(inputs, {**common, "revenue_growth": growth})
        samples.append((growth, value, value - target))

    roots: list[Decimal] = []
    for sample in samples:
        if sample[2] == 0:
            _append_distinct_root(roots, sample[0])
    for left, right in zip(samples, samples[1:]):
        if left[2] * right[2] < 0:
            _append_distinct_root(roots, _bisect_root(inputs, common, target, left, right))

    solutions = [
        {
            "implied_revenue_growth": _text(root),
            "reconciled_enterprise_value": _text(
                _dcf_enterprise_value(inputs, {**common, "revenue_growth": root})
            ),
        }
        for root in sorted(roots)
    ]
    base = {
        "search_bounds": [_text(low), _text(high)],
        "target_enterprise_value": _text(target),
        "grid_value_range": [
            _text(min(item[1] for item in samples)),
            _text(max(item[1] for item in samples)),
        ],
        "fixed_drivers": {key: _text(value) for key, value in common.items()},
    }
    if not solutions:
        closest = min(samples, key=lambda item: abs(item[2]))
        return {
            "status": "no_solution",
            **base,
            "closest_grid_growth": _text(closest[0]),
            "closest_grid_enterprise_value": _text(closest[1]),
        }
    if len(solutions) == 1:
        return {"status": "solved", **base, **solutions[0], "solutions": solutions}
    return {"status": "multiple_solutions", **base, "solutions": solutions}


def _dcf_enterprise_value(inputs: dict[str, Any], drivers: dict[str, Decimal]) -> Decimal:
    revenue = inputs["current_revenue"]
    present_value = Decimal("0")
    years = int(inputs["forecast_years"])
    for year in range(1, years + 1):
        prior_revenue = revenue
        revenue = prior_revenue * (Decimal("1") + drivers["revenue_growth"])
        nopat = revenue * drivers["operating_margin"] * (Decimal("1") - drivers["tax_rate"])
        reinvestment = (revenue - prior_revenue) / drivers["sales_to_capital"]
        fcff = nopat - reinvestment
        present_value += fcff / ((Decimal("1") + drivers["discount_rate"]) ** year)
    terminal_revenue = revenue * (Decimal("1") + drivers["terminal_growth"])
    terminal_nopat = terminal_revenue * drivers["operating_margin"] * (Decimal("1") - drivers["tax_rate"])
    terminal_reinvestment = (terminal_revenue - revenue) / drivers["sales_to_capital"]
    terminal_fcff = terminal_nopat - terminal_reinvestment
    terminal_value = terminal_fcff / (drivers["discount_rate"] - drivers["terminal_growth"])
    return present_value + terminal_value / ((Decimal("1") + drivers["discount_rate"]) ** years)


def _bisect_root(
    inputs: dict[str, Any],
    common: dict[str, Decimal],
    target: Decimal,
    left: tuple[Decimal, Decimal, Decimal],
    right: tuple[Decimal, Decimal, Decimal],
) -> Decimal:
    left_growth, left_delta = left[0], left[2]
    right_growth = right[0]
    for _ in range(120):
        middle = (left_growth + right_growth) / 2
        middle_delta = _dcf_enterprise_value(inputs, {**common, "revenue_growth": middle}) - target
        if middle_delta == 0:
            return middle
        if left_delta * middle_delta < 0:
            right_growth = middle
        else:
            left_growth, left_delta = middle, middle_delta
    candidates = (left_growth, (left_growth + right_growth) / 2, right_growth)
    return min(
        candidates,
        key=lambda growth: abs(_dcf_enterprise_value(inputs, {**common, "revenue_growth": growth}) - target),
    )


def _append_distinct_root(roots: list[Decimal], candidate: Decimal) -> None:
    if not any(abs(candidate - existing) <= Decimal("0.000000000000000001") for existing in roots):
        roots.append(candidate)


def _validated_method_values(value: Any) -> list[dict[str, str]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("other_method_values must be a list")
    results = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"other_method_values[{index}] must be an object")
        results.append({
            "method": _required_text(item, "method"),
            "per_share": _text(_positive(item.get("per_share"), f"other_method_values[{index}].per_share")),
            "source": _required_text(item, "source"),
        })
    return results


def _load_analysis_source(
    root: Path,
    manifest: dict[str, Any],
    snapshot_id: str,
    knowledge_cutoff: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list):
        raise ValueError("replay manifest snapshots must be a list")
    matches = [item for item in snapshots if isinstance(item, dict) and item.get("snapshot_id") == snapshot_id]
    if len(matches) != 1:
        raise ValueError("analysis input snapshot must appear exactly once in the replay manifest")
    entry = matches[0]
    path = safe_workspace_path(root, str(entry.get("path") or ""), allowed_roots=(SOURCE_SNAPSHOT_ROOT,))
    expected_file_hash = str(entry.get("content_hash") or "")
    actual_file_hash = file_hash(path)
    if actual_file_hash is None or actual_file_hash != expected_file_hash:
        raise ValueError("analysis input snapshot content hash does not match the replay manifest")
    snapshot = _read_object(path)
    if snapshot.get("snapshot_id") != snapshot_id:
        raise ValueError("analysis input snapshot id does not match the replay manifest")
    payload = snapshot.get("payload")
    if not isinstance(payload, dict) or snapshot.get("payload_hash") != stable_hash(payload):
        raise ValueError("analysis input snapshot payload hash is invalid")
    snapshot_seed = {key: value for key, value in snapshot.items() if key not in {"snapshot_id", "snapshot_hash"}}
    if snapshot.get("snapshot_hash") != stable_hash(snapshot_seed):
        raise ValueError("analysis input snapshot hash is invalid")
    known_at = _parse_iso(snapshot.get("known_at"), "analysis input snapshot known_at")
    if known_at > _parse_iso(knowledge_cutoff, "ResearchSpec knowledge_cutoff"):
        raise ValueError("analysis input snapshot is after the ResearchSpec knowledge cutoff")
    analysis_values = payload.get(ANALYSIS_SOURCE_KEY)
    if not isinstance(analysis_values, dict):
        raise ValueError(f"analysis input snapshot payload requires {ANALYSIS_SOURCE_KEY}")
    return (
        {
            "snapshot_id": snapshot_id,
            "path": path.relative_to(root).as_posix(),
            "content_hash": actual_file_hash,
            "snapshot_hash": snapshot["snapshot_hash"],
            "payload_hash": snapshot["payload_hash"],
            "known_at": snapshot["known_at"],
        },
        analysis_values,
    )


def _reconcile_scenarios(plan: Any, scenarios: Any) -> None:
    planned = plan.get("scenarios") if isinstance(plan, dict) else None
    if not isinstance(planned, list) or not isinstance(scenarios, list):
        raise ValueError("actual scenarios require a preregistered scenario_plan")
    if len(planned) != len(scenarios):
        raise ValueError("actual scenarios do not match the preregistered scenario_plan")
    planned_names = [str(item.get("name") or "") if isinstance(item, dict) else "" for item in planned]
    actual_names = [str(item.get("name") or "") if isinstance(item, dict) else "" for item in scenarios]
    if not all(planned_names) or len(set(planned_names)) != len(planned_names) or actual_names != planned_names:
        raise ValueError("actual scenario names/order do not match the preregistered scenario_plan")
    for index, (expected, actual) in enumerate(zip(planned, scenarios), start=1):
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            raise ValueError(f"scenario {index} does not match the preregistered scenario_plan")
        if _decimal(expected.get("weight"), f"scenario_plan.scenarios[{index}].weight") != _decimal(
            actual.get("weight"), f"scenario {index} weight"
        ):
            raise ValueError(f"scenario {index} weight does not match the preregistered scenario_plan")
        expected_drivers = expected.get("drivers")
        if not isinstance(expected_drivers, dict):
            raise ValueError(f"scenario_plan.scenarios[{index}].drivers must be an object")
        expected_keys = set(expected_drivers)
        actual_keys = SCENARIO_DRIVER_FIELDS.intersection(actual)
        if expected_keys != SCENARIO_DRIVER_FIELDS or actual_keys != SCENARIO_DRIVER_FIELDS:
            raise ValueError(f"scenario {index} drivers do not match the preregistered scenario_plan")
        for field, preregistered in expected_drivers.items():
            expected_value = preregistered.get("value") if isinstance(preregistered, dict) else preregistered
            expected_number = _decimal(expected_value, f"scenario_plan.scenarios[{index}].drivers.{field}")
            if _decimal(actual.get(field), f"scenario {index} {field}") != expected_number:
                raise ValueError(f"scenario {index} driver {field} does not match the preregistered scenario_plan")
        if "assumptions" in expected and expected["assumptions"] != actual.get("assumptions"):
            raise ValueError(f"scenario {index} assumptions do not match the preregistered scenario_plan")


def _load_prior(
    root: Path,
    prior_id: str,
    spec: dict[str, Any],
    analysis_created_at: str,
) -> dict[str, Any]:
    path = _json_path(root, PRIOR_ROOT, prior_id)
    if not path.exists():
        raise ValueError(f"blind judgment prior not found: {prior_id}")
    prior = _read_object(path)
    _verify_embedded_hash(prior, "prior_hash", "blind prior")
    if prior.get("spec_id") != spec.get("spec_id") or prior.get("analysis_plan_hash") != spec.get("analysis_plan_hash"):
        raise ValueError("blind prior does not match the frozen ResearchSpec")
    if prior.get("blind_to_producer_conclusion") is not True:
        raise ValueError("judgment prior is not marked blind to the producer conclusion")
    if _parse_iso(prior.get("created_at"), "blind prior created_at") >= _parse_iso(
        analysis_created_at, "causal analysis created_at"
    ):
        raise ValueError("blind prior must precede the causal analysis")
    return prior


def _analysis_exists_for_spec(root: Path, spec_id: str) -> bool:
    base = root / ANALYSIS_ROOT
    if not base.exists():
        return False
    return any(_read_object(path).get("spec_id") == spec_id for path in base.glob("*.json"))


def _verify_embedded_hash(value: dict[str, Any], hash_field: str, label: str) -> None:
    expected = str(value.get(hash_field) or "")
    seed = {key: item for key, item in value.items() if key != hash_field}
    if not expected or expected != stable_hash(seed):
        raise ValueError(f"{label} {hash_field} is invalid")


def _parse_iso(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _canonical_numeric_inputs(inputs: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value) if isinstance(value, int) else _text(value)
        for key, value in inputs.items()
    }


def _json_path(root: Path, base: Path, artifact_id: str) -> Path:
    return safe_workspace_path(root, base / f"{sanitize_id(artifact_id)}.json", allowed_roots=(base,))


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid immutable analysis artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"analysis artifact must be an object: {path}")
    return value


def _store_immutable(path: Path, artifact: dict[str, Any], hash_field: str) -> tuple[dict[str, Any], str]:
    with exclusive_file_lock(path):
        if path.exists():
            existing = _read_object(path)
            if existing.get(hash_field) == artifact.get(hash_field):
                return existing, "existing"
            raise ValueError(f"immutable analysis artifact already exists: {path.stem}")
        atomic_write_text(path, json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    return artifact, "recorded"


def _result(root: Path, path: Path, artifact: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "artifact": artifact,
        "export_path": path.relative_to(root).as_posix(),
        "artifact_hash": file_hash(path),
        "authority": "evidence_only",
        "workspace_context": workspace_context_payload(root),
    }


def _required_text(value: dict[str, Any], field: str) -> str:
    text = str(value.get(field) or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _required_list(value: dict[str, Any], field: str) -> list[Any]:
    result = value.get(field)
    if not isinstance(result, list) or not result:
        raise ValueError(f"{field} must be a non-empty list")
    return result


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return number


def _positive(value: Any, field: str) -> Decimal:
    number = _decimal(value, field)
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _rate(value: Any, field: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    number = _decimal(value, field)
    if number < minimum or number > 1:
        raise ValueError(f"{field} must be between {minimum} and 1")
    return number


def _text(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_EVEN)
    return format(rounded, "f")
