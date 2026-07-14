from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tradingcodex_service.application import investment_analysis
from tradingcodex_service.application.common import atomic_write_text, stable_hash
from tradingcodex_service.application.investment_analysis import (
    ANALYSIS_PROTOCOL,
    METHOD_PROFILE,
    VALUATION_METHOD,
    _dcf_enterprise_value,
    _reverse_dcf,
    complete_judgment_review,
    create_causal_equity_analysis,
    record_blind_judgment_prior,
)
from tradingcodex_service.application.research import record_source_snapshot
from tradingcodex_service.application.research_specs import RESEARCH_SPEC_SCHEMA_VERSION, create_replay_manifest
from tradingcodex_service.application.runtime import ensure_workspace_manifest
from tradingcodex_service.mcp_runtime import TOOL_REGISTRY


@pytest.fixture(autouse=True)
def attached_workspace(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)


def _scenarios() -> list[dict[str, object]]:
    return [
        {
            "name": "bear",
            "weight": "0.25",
            "revenue_growth": "-0.02",
            "operating_margin": "0.10",
            "tax_rate": "0.25",
            "sales_to_capital": "2",
            "discount_rate": "0.10",
            "terminal_growth": "0.03",
            "assumptions": ["demand contracts"],
        },
        {
            "name": "base",
            "weight": "0.50",
            "revenue_growth": "0.05",
            "operating_margin": "0.15",
            "tax_rate": "0.25",
            "sales_to_capital": "2",
            "discount_rate": "0.10",
            "terminal_growth": "0.03",
            "assumptions": ["current economics persist"],
        },
        {
            "name": "bull",
            "weight": "0.25",
            "revenue_growth": "0.10",
            "operating_margin": "0.20",
            "tax_rate": "0.25",
            "sales_to_capital": "2",
            "discount_rate": "0.10",
            "terminal_growth": "0.03",
            "assumptions": ["operating leverage appears"],
        },
    ]


def _analysis_source(*, scenarios: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "instrument": "ACME",
        "inputs": {
            "current_revenue": "1000",
            "current_price": "10",
            "shares_outstanding": "100",
            "net_debt": "100",
            "operating_margin": "0.15",
            "tax_rate": "0.25",
            "sales_to_capital": "2",
            "discount_rate": "0.10",
            "terminal_growth": "0.03",
            "forecast_years": 5,
        },
        "scenarios": scenarios or _scenarios(),
        "other_method_values": [
            {"method": "peer_multiples", "per_share": "12", "source": "frozen peer cohort in this snapshot"}
        ],
        "contrary_evidence": ["the addressable market may be overstated"],
        "update_triggers": ["new audited filing"],
        "invalidation_conditions": ["durable negative unit economics"],
        "investor_context_gaps": ["tax residency is unknown"],
    }


def _write_spec(root: Path) -> dict[str, object]:
    scenarios = _scenarios()
    spec: dict[str, object] = {
        "schema_version": RESEARCH_SPEC_SCHEMA_VERSION,
        "artifact_type": "research_spec",
        "spec_id": "acme-valuation",
        "created_at": "2026-01-03T00:00:00Z",
        "created_by": "fundamental-analyst",
        "knowledge_cutoff": "2026-01-02T00:00:00Z",
        "hypothesis": "Market expectations imply an observable operating path.",
        "economic_mechanism": "Revenue growth and reinvestment drive enterprise value.",
        "research_type": "listed_equity_valuation",
        "method_profile": METHOD_PROFILE,
        "instrument": "ACME",
        "universe": "ACME common stock",
        "universe_membership_rule": "The instrument is fixed by the ResearchSpec.",
        "target": "intrinsic value per share",
        "horizon": "five years",
        "benchmark": "current market price",
        "holding_period": "five years",
        "rebalance_rule": "not applicable",
        "signal_definition": {"type": "causal valuation"},
        "falsification_criteria": ["driver evidence fails"],
        "validation_plan": {"point_in_time": True},
        "parameter_trial_budget": 1,
        "cost_assumptions": {"not_applicable": True},
        "capacity_assumptions": {"not_applicable": True},
        "resolution_rule": "Compare preregistered drivers with later audited results.",
        "driver_tree": {"revenue": ["volume", "price"], "margin": ["gross margin", "opex"]},
        "base_rate_cohort": {
            "selection_rule": "same-industry issuers",
            "as_of": "2026-01-02T00:00:00Z",
            "sample_size": 20,
            "dispersion": "wide",
            "limitations": ["small cohort"],
        },
        "implied_expectations_plan": {"solve_for": "revenue_growth"},
        "scenario_plan": {
            "scenarios": [
                {
                    "name": item["name"],
                    "weight": item["weight"],
                    "drivers": {
                        "revenue_growth": item["revenue_growth"],
                        "operating_margin": item["operating_margin"],
                        "tax_rate": item["tax_rate"],
                        "sales_to_capital": item["sales_to_capital"],
                        "discount_rate": item["discount_rate"],
                        "terminal_growth": item["terminal_growth"],
                    },
                }
                for item in scenarios
            ]
        },
        "method_reconciliation_plan": {"policy": "preserve disagreement"},
        "independent_review_plan": {"passes": 2, "blind_prior_required": True},
        "authority": "evidence_only",
        "blocked_actions": ["order_drafting", "order_approval", "order_execution"],
    }
    spec["analysis_plan_hash"] = stable_hash(spec)
    path = root / "trading/research/specs/acme-valuation.json"
    atomic_write_text(path, json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return spec


def _frozen_inputs(
    root: Path,
    *,
    scenarios: list[dict[str, object]] | None = None,
) -> tuple[str, str, str]:
    _write_spec(root)
    snapshot = record_source_snapshot(
        root,
        {
            "provider": "test-provider",
            "source_category": "valuation-inputs",
            "source_locator": "test-provider:acme:valuation-inputs:v1",
            "known_at": "2026-01-01T00:00:00Z",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "recorded_at": "2026-01-01T00:00:00Z",
            "revision": "original",
            "vintage": "2025Q4",
            "timezone": "UTC",
            "coverage_note": "Synthetic deterministic test fixture.",
            "payload": {"fcff_revenue_margin_dcf_v1": _analysis_source(scenarios=scenarios)},
            "principal_id": "valuation-analyst",
        },
    )
    manifest = create_replay_manifest(
        root,
        {
            "manifest_id": "acme-replay",
            "spec_id": "acme-valuation",
            "source_snapshot_ids": [snapshot["snapshot_id"]],
            "created_by": "valuation-analyst",
        },
    )
    return snapshot["snapshot_id"], snapshot["export_path"], manifest["artifact"]["manifest_id"]


def _prior(root: Path, prior_id: str = "acme-prior") -> dict[str, object]:
    return record_blind_judgment_prior(
        root,
        {
            "prior_id": prior_id,
            "spec_id": "acme-valuation",
            "reviewer": "judgment-reviewer",
            "specification_view": "The specification is causal and falsifiable.",
            "evidence_quality_view": "Evidence is frozen but uncertainty remains.",
            "key_driver_view": ["revenue growth", "operating margin"],
            "falsifiers": ["source hash mismatch", "scenario-plan mismatch"],
        },
    )["artifact"]


def _create_analysis(root: Path, snapshot_id: str, manifest_id: str, prior_id: str = "acme-prior") -> dict[str, object]:
    return create_causal_equity_analysis(
        root,
        {
            "analysis_id": "acme-analysis",
            "spec_id": "acme-valuation",
            "replay_manifest_id": manifest_id,
            "analysis_input_snapshot_id": snapshot_id,
            "prior_id": prior_id,
            "created_by": "valuation-analyst",
        },
    )["artifact"]


def test_analysis_rejects_caller_injection_and_snapshot_tampering(tmp_path: Path) -> None:
    snapshot_id, snapshot_path, manifest_id = _frozen_inputs(tmp_path)
    _prior(tmp_path)
    with pytest.raises(ValueError, match="not caller fields"):
        create_causal_equity_analysis(
            tmp_path,
            {
                "spec_id": "acme-valuation",
                "replay_manifest_id": manifest_id,
                "analysis_input_snapshot_id": snapshot_id,
                "prior_id": "acme-prior",
                "created_by": "valuation-analyst",
                "inputs": {"current_price": "0.01"},
            },
        )

    path = tmp_path / snapshot_path
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["payload"]["fcff_revenue_margin_dcf_v1"]["inputs"]["current_price"] = "0.01"
    atomic_write_text(path, json.dumps(tampered, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="content hash"):
        _create_analysis(tmp_path, snapshot_id, manifest_id)


def test_analysis_rejects_scenarios_that_differ_from_preregistered_plan(tmp_path: Path) -> None:
    scenarios = copy.deepcopy(_scenarios())
    scenarios[1]["name"] = "management-case"
    snapshot_id, _, manifest_id = _frozen_inputs(tmp_path, scenarios=scenarios)
    _prior(tmp_path)
    with pytest.raises(ValueError, match="names/order"):
        _create_analysis(tmp_path, snapshot_id, manifest_id)


def test_blind_prior_must_precede_analysis(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot_id, _, manifest_id = _frozen_inputs(tmp_path)
    monkeypatch.setattr(investment_analysis, "now_iso", lambda: "2026-06-02T00:00:00Z")
    _prior(tmp_path)
    monkeypatch.setattr(investment_analysis, "now_iso", lambda: "2026-06-01T00:00:00Z")
    with pytest.raises(ValueError, match="must precede"):
        _create_analysis(tmp_path, snapshot_id, manifest_id)


def test_two_pass_review_is_bound_and_late_priors_are_rejected(tmp_path: Path) -> None:
    snapshot_id, _, manifest_id = _frozen_inputs(tmp_path)
    prior = _prior(tmp_path)
    analysis = _create_analysis(tmp_path, snapshot_id, manifest_id)
    assert analysis["blind_prior_binding"]["prior_hash"] == prior["prior_hash"]
    assert analysis["analysis_protocol"] == ANALYSIS_PROTOCOL
    assert analysis["method_profile"] == METHOD_PROFILE
    assert analysis["valuation_method"] == VALUATION_METHOD
    assert analysis["instrument"] == "ACME"
    assert analysis["analysis_source"]["snapshot_id"] == snapshot_id
    assert analysis["method_reconciliation"]["methods"][-1]["method"] == "peer_multiples"

    with pytest.raises(PermissionError, match="only the blind-prior reviewer"):
        complete_judgment_review(
            tmp_path,
            {
                "prior_id": prior["prior_id"],
                "analysis_id": analysis["analysis_id"],
                "reviewer": "valuation-analyst",
                "conclusion": "accept",
                "remaining_disagreements": ["terminal assumptions"],
            },
        )
    review = complete_judgment_review(
        tmp_path,
        {
            "review_id": "acme-review",
            "prior_id": prior["prior_id"],
            "analysis_id": analysis["analysis_id"],
            "reviewer": "judgment-reviewer",
            "conclusion": "The arithmetic is reproducible; uncertainty remains.",
            "changed_views": ["base case is less likely"],
            "remaining_disagreements": ["terminal margin"],
            "acceptance": "accepted",
        },
    )["artifact"]
    assert review["prior_hash"] == prior["prior_hash"]
    assert review["analysis_hash"] == analysis["analysis_hash"]

    with pytest.raises(ValueError, match="before any causal analysis"):
        _prior(tmp_path, "late-prior")


def test_investment_analysis_accepts_a_symlinked_workspace_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-workspace"
    real_root.mkdir()
    ensure_workspace_manifest(real_root)
    linked_root = tmp_path / "linked-workspace"
    linked_root.symlink_to(real_root, target_is_directory=True)
    snapshot_id, _, manifest_id = _frozen_inputs(real_root)

    prior = _prior(linked_root)
    analysis = _create_analysis(linked_root, snapshot_id, manifest_id)
    review = complete_judgment_review(
        linked_root,
        {
            "review_id": "symlink-review",
            "prior_id": prior["prior_id"],
            "analysis_id": analysis["analysis_id"],
            "reviewer": "judgment-reviewer",
            "conclusion": "The frozen analysis is reproducible.",
            "remaining_disagreements": ["terminal assumptions"],
            "acceptance": "accepted",
        },
    )

    assert review["export_path"] == "trading/research/judgment-reviews/symlink-review.json"


def test_reverse_dcf_reports_multiple_and_no_solutions(monkeypatch: pytest.MonkeyPatch) -> None:
    def non_monotonic(_inputs: dict[str, object], drivers: dict[str, Decimal]) -> Decimal:
        growth = drivers["revenue_growth"]
        return (growth - Decimal("0.2")) ** 2

    monkeypatch.setattr(investment_analysis, "_dcf_enterprise_value", non_monotonic)
    inputs = {
        "target_enterprise_value": Decimal("0.04"),
        "operating_margin": Decimal("0.2"),
        "tax_rate": Decimal("0.2"),
        "sales_to_capital": Decimal("2"),
        "discount_rate": Decimal("0.1"),
        "terminal_growth": Decimal("0.03"),
    }
    multiple = _reverse_dcf(inputs)
    assert multiple["status"] == "multiple_solutions"
    assert [item["implied_revenue_growth"] for item in multiple["solutions"]] == [
        "0.0000000000",
        "0.4000000000",
    ]
    inputs["target_enterprise_value"] = Decimal("2")
    assert _reverse_dcf(inputs)["status"] == "no_solution"


def test_terminal_fcff_recomputes_terminal_revenue_nopat_and_reinvestment() -> None:
    inputs = {"current_revenue": Decimal("100"), "forecast_years": 1}
    drivers = {
        "revenue_growth": Decimal("0.10"),
        "operating_margin": Decimal("0.20"),
        "tax_rate": Decimal("0.25"),
        "sales_to_capital": Decimal("2"),
        "discount_rate": Decimal("0.10"),
        "terminal_growth": Decimal("0.03"),
    }
    year_one_revenue = Decimal("110")
    year_one_fcff = year_one_revenue * Decimal("0.20") * Decimal("0.75") - Decimal("10") / Decimal("2")
    terminal_revenue = year_one_revenue * Decimal("1.03")
    terminal_fcff = (
        terminal_revenue * Decimal("0.20") * Decimal("0.75")
        - (terminal_revenue - year_one_revenue) / Decimal("2")
    )
    expected = year_one_fcff / Decimal("1.10") + (
        terminal_fcff / (Decimal("0.10") - Decimal("0.03")) / Decimal("1.10")
    )
    assert _dcf_enterprise_value(inputs, drivers) == expected


def test_causal_mcp_schema_accepts_only_frozen_bindings() -> None:
    schema = TOOL_REGISTRY["create_causal_equity_analysis"].input_schema
    assert set(schema["required"]) == {
        "spec_id",
        "replay_manifest_id",
        "analysis_input_snapshot_id",
        "prior_id",
    }
    assert not {"instrument", "inputs", "scenarios", "other_method_values"}.intersection(schema["properties"])
