from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tradingcodex_service.api import ResearchSpecRequest
from tradingcodex_service.application.research import record_source_snapshot
from tradingcodex_service.application.research_specs import (
    EVENT_RESEARCH_PROFILE,
    GENERAL_EVIDENCE_PROFILE,
    LISTED_EQUITY_FCFF_DCF_PROFILE,
    QUANT_REQUIRED_VALIDATION_CHECKS,
    QUANT_SIGNAL_PROFILE,
    create_replay_manifest,
    create_research_spec,
    record_experiment_run,
)
from tradingcodex_service.mcp_runtime import TOOL_REGISTRY
from tradingcodex_service.application.runtime import ensure_workspace_manifest


@pytest.fixture(autouse=True)
def attached_workspace(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)


def _base(profile: str, spec_id: str) -> dict[str, object]:
    return {
        "spec_id": spec_id,
        "created_at": "2026-01-02T00:00:00Z",
        "created_by": "fundamental-analyst",
        "knowledge_cutoff": "2026-01-01T00:00:00Z",
        "method_profile": profile,
        "hypothesis": "The available evidence can resolve the research question.",
        "economic_mechanism": "The stated evidence changes the relevant investment driver.",
        "universe": "listed equities",
        "universe_membership_rule": "Use only instruments known at the cutoff.",
        "target": "research conclusion",
        "horizon": "90 days",
        "falsification_criteria": ["The expected evidence does not materialize."],
        "validation_plan": {"source_review": "independent evidence check"},
        "resolution_rule": "Resolve from the frozen source snapshots.",
    }


def _quant(spec_id: str = "quant-profile") -> dict[str, object]:
    return {
        **_base(QUANT_SIGNAL_PROFILE, spec_id),
        "created_by": "technical-analyst",
        "benchmark": "point-in-time market index",
        "holding_period": "20 trading days",
        "rebalance_rule": "monthly",
        "signal_definition": {"field": "signal", "lag_days": 1},
        "parameter_trial_budget": 2,
        "cost_assumptions": {"slippage_bps": 5},
        "capacity_assumptions": {"max_adv_fraction": 0.01},
    }


def _fcff(spec_id: str = "fcff-profile") -> dict[str, object]:
    drivers = {
        "revenue_growth": 0.1,
        "operating_margin": 0.2,
        "tax_rate": 0.2,
        "sales_to_capital": 2.0,
        "discount_rate": 0.1,
        "terminal_growth": 0.03,
    }
    return {
        **_base(LISTED_EQUITY_FCFF_DCF_PROFILE, spec_id),
        "created_by": "valuation-analyst",
        "instrument": "ACME",
        "driver_tree": {"revenue": ["growth"], "value": ["cash flow"]},
        "base_rate_cohort": {
            "selection_rule": "same-sector issuers",
            "as_of": "2025-12-31T00:00:00Z",
            "sample_size": 10,
            "dispersion": "wide",
            "limitations": ["small cohort"],
        },
        "implied_expectations_plan": {"method": "reverse_dcf"},
        "scenario_plan": {
            "scenarios": [
                {"name": "downside", "weight": 0.5, "drivers": drivers, "assumptions": ["slower growth"]},
                {"name": "upside", "weight": 0.5, "drivers": {**drivers, "revenue_growth": 0.2}, "assumptions": ["faster growth"]},
            ]
        },
        "method_reconciliation_plan": {"policy": "preserve disagreement"},
        "independent_review_plan": {"reviewer": "judgment-reviewer"},
    }


@pytest.mark.parametrize("profile", [GENERAL_EVIDENCE_PROFILE, EVENT_RESEARCH_PROFILE])
def test_general_profiles_do_not_require_or_store_quant_fields(tmp_path: Path, profile: str) -> None:
    artifact = create_research_spec(tmp_path, _base(profile, profile))["artifact"]

    assert artifact["method_profile"] == profile
    assert not {
        "benchmark",
        "signal_definition",
        "parameter_trial_budget",
        "cost_assumptions",
        "capacity_assumptions",
    }.intersection(artifact)


def test_create_spec_api_and_mcp_expose_profiles_without_quant_base_requirements() -> None:
    payload = _base(GENERAL_EVIDENCE_PROFILE, "surface-profile")
    payload.pop("created_by")
    request = ResearchSpecRequest(**payload)
    assert request.method_profile == GENERAL_EVIDENCE_PROFILE
    assert request.signal_definition is None

    schema = TOOL_REGISTRY["create_research_spec"].input_schema
    assert set(schema["properties"]["method_profile"]["enum"]) == {
        GENERAL_EVIDENCE_PROFILE,
        EVENT_RESEARCH_PROFILE,
        QUANT_SIGNAL_PROFILE,
        LISTED_EQUITY_FCFF_DCF_PROFILE,
    }
    assert not {
        "benchmark",
        "signal_definition",
        "parameter_trial_budget",
        "cost_assumptions",
        "capacity_assumptions",
    }.intersection(schema["required"])


def test_quant_and_fcff_profiles_enforce_only_their_own_fields(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="benchmark is required"):
        create_research_spec(tmp_path, {**_quant("quant-missing-benchmark"), "benchmark": ""})

    quant = create_research_spec(tmp_path, _quant())["artifact"]
    assert quant["method_profile"] == QUANT_SIGNAL_PROFILE
    assert quant["parameter_trial_budget"] == 2
    assert "driver_tree" not in quant

    with pytest.raises(ValueError, match="driver_tree"):
        create_research_spec(tmp_path, {
            **_base(LISTED_EQUITY_FCFF_DCF_PROFILE, "fcff-missing-drivers"),
            "instrument": "ACME",
        })

    fcff = create_research_spec(tmp_path, _fcff())["artifact"]
    assert fcff["method_profile"] == LISTED_EQUITY_FCFF_DCF_PROFILE
    assert fcff["research_type"] == "listed_equity_valuation"
    assert "signal_definition" not in fcff
    assert "parameter_trial_budget" not in fcff


def test_explicit_profiles_reject_conflicting_selectors_and_irrelevant_fields(tmp_path: Path) -> None:
    conflicts = [
        ({**_base(GENERAL_EVIDENCE_PROFILE, "general-quant-type"), "research_type": "quant_signal"}, "research_type"),
        ({**_quant("quant-causal"), "causal_analysis_required": True}, "causal_analysis_required"),
        ({**_fcff("fcff-noncausal"), "causal_analysis_required": False}, "causal_analysis_required"),
    ]
    for payload, selector in conflicts:
        with pytest.raises(ValueError, match=selector):
            create_research_spec(tmp_path, payload)

    irrelevant = [
        ({**_base(GENERAL_EVIDENCE_PROFILE, "general-with-signal"), "signal_definition": {"field": "x"}}, "signal_definition"),
        ({**_quant("quant-with-drivers"), "driver_tree": {"value": ["growth"]}}, "driver_tree"),
        ({**_fcff("fcff-with-benchmark"), "benchmark": "market index"}, "benchmark"),
    ]
    for payload, field in irrelevant:
        with pytest.raises(ValueError, match=field):
            create_research_spec(tmp_path, payload)


def test_method_profile_is_required_instead_of_inferred(tmp_path: Path) -> None:
    quant_payload = _quant("missing-quant-profile")
    quant_payload.pop("method_profile")
    with pytest.raises(ValueError, match="method_profile is required"):
        create_research_spec(tmp_path, quant_payload)

    fcff_payload = _fcff("missing-fcff-profile")
    fcff_payload.pop("method_profile")
    with pytest.raises(ValueError, match="method_profile is required"):
        create_research_spec(tmp_path, fcff_payload)


def test_experiment_rules_follow_the_frozen_method_profile(tmp_path: Path) -> None:
    general = create_research_spec(tmp_path, _base(GENERAL_EVIDENCE_PROFILE, "general-experiment"))["artifact"]
    quant = create_research_spec(tmp_path, _quant("quant-experiment"))["artifact"]
    snapshot_id = record_source_snapshot(tmp_path, {
        "provider": "profile-test",
        "source_category": "fundamental",
        "known_at": "2026-01-01T00:00:00Z",
        "retrieved_at": "2026-01-01T00:00:00Z",
        "recorded_at": "2026-01-01T00:00:00Z",
        "payload": {"value": 1},
        "principal_id": "fundamental-analyst",
    })["snapshot_id"]
    manifests = {
        spec["method_profile"]: create_replay_manifest(tmp_path, {
            "manifest_id": f"manifest-{spec['spec_id']}",
            "spec_id": spec["spec_id"],
            "source_snapshot_ids": [snapshot_id],
            "created_at": "2026-01-02T00:00:00Z",
            "created_by": spec["created_by"],
        })["artifact"]
        for spec in (general, quant)
    }
    evidence = tmp_path / "trading/research/profile-evidence.json"
    evidence.write_text('{"supported": true}\n', encoding="utf-8")
    evidence_ref = {
        "path": "trading/research/profile-evidence.json",
        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
    }
    common = {
        "created_at": "2026-01-02T00:00:00Z",
        "created_by": "fundamental-analyst",
        "code_hash": "a" * 64,
        "data_hash": "b" * 64,
        "config_hash": "c" * 64,
        "splits": {"evidence": "frozen"},
        "metrics": {"coverage": 1},
    }
    with pytest.raises(ValueError, match="checks must be a non-empty object"):
        record_experiment_run(tmp_path, {
            **common,
            "run_id": "general-empty-checks",
            "spec_id": general["spec_id"],
            "replay_manifest_id": manifests[GENERAL_EVIDENCE_PROFILE]["manifest_id"],
            "checks": {},
            "conclusion": "evidence_supported",
        })
    general_run = record_experiment_run(tmp_path, {
        **common,
        "run_id": "general-run",
        "spec_id": general["spec_id"],
        "replay_manifest_id": manifests[GENERAL_EVIDENCE_PROFILE]["manifest_id"],
        "trial_count": 100,
        "checks": {"source_quality": {"status": "pass", "reason": "Source is frozen.", "evidence_refs": [evidence_ref]}},
        "conclusion": "evidence_supported",
    })["artifact"]
    assert general_run["method_profile"] == GENERAL_EVIDENCE_PROFILE
    assert general_run["conclusion"] == "evidence_supported"
    assert general_run["trial_count"] == 100

    with pytest.raises(ValueError, match="checks.point_in_time"):
        record_experiment_run(tmp_path, {
            **common,
            "run_id": "quant-incomplete-run",
            "spec_id": quant["spec_id"],
            "replay_manifest_id": manifests[QUANT_SIGNAL_PROFILE]["manifest_id"],
            "checks": {"source_quality": {"status": "pass", "reason": "Source is frozen.", "evidence_refs": [evidence_ref]}},
            "conclusion": "evidence_supported",
        })
    quant_checks = {
        key: {"status": "pass", "reason": "Check passed.", "evidence_refs": [evidence_ref]}
        for key in QUANT_REQUIRED_VALIDATION_CHECKS
    }
    with pytest.raises(ValueError, match="conclusion must be one of"):
        record_experiment_run(tmp_path, {
            **common,
            "run_id": "quant-invalid-conclusion",
            "spec_id": quant["spec_id"],
            "replay_manifest_id": manifests[QUANT_SIGNAL_PROFILE]["manifest_id"],
            "checks": quant_checks,
            "conclusion": "evidence_supported",
        })


def test_research_services_accept_a_symlinked_workspace_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-workspace"
    real_root.mkdir()
    ensure_workspace_manifest(real_root)
    linked_root = tmp_path / "linked-workspace"
    linked_root.symlink_to(real_root, target_is_directory=True)

    created = create_research_spec(
        linked_root,
        _base(GENERAL_EVIDENCE_PROFILE, "symlink-profile"),
    )

    assert created["export_path"] == "trading/research/specs/symlink-profile.json"
    assert create_research_spec(linked_root, _base(GENERAL_EVIDENCE_PROFILE, "symlink-profile"))["status"] == "existing"
