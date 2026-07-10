from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from django.db import close_old_connections

from tradingcodex_cli.commands.workflow import workflow as workflow_command
from tradingcodex_service.application import research as research_module
from tradingcodex_service.application import workflow_state as workflow_state_module
from tradingcodex_service.application.common import atomic_write_text
from tradingcodex_service.application.forecasting import (
    calibration_report,
    get_forecast,
    issue_forecast,
    resolve_forecast,
    revise_forecast,
    score_forecast,
)
from tradingcodex_service.application.brokers import ExternalMcpBrokerAdapter, ensure_paper_broker_connection
from tradingcodex_service.application.orders import _money_contract_from_fields, normalize_order_ticket_fields
from tradingcodex_service.application.portfolio import (
    PortfolioConcurrencyError,
    load_paper_portfolio_state,
    portfolio_keys,
    persist_paper_portfolio_state,
    submit_paper_order,
)
from tradingcodex_service.application.research import (
    append_research_artifact_version,
    create_research_artifact,
    get_research_artifact,
    rebuild_research_index,
    record_source_snapshot,
    search_research_artifacts,
)
from tradingcodex_service.application.research_specs import (
    REQUIRED_VALIDATION_CHECKS,
    create_replay_manifest,
    create_research_spec,
    record_experiment_run,
)
from tradingcodex_service.application.runtime import (
    active_profile_for_workspace,
    ensure_workspace_manifest,
    ensure_runtime_database,
    read_workspace_profiles,
    save_active_profile_for_workspace,
)
from tradingcodex_service.application.workflow_routing import (
    HIGH_IMPACT_INTENT_ACTIONS,
    classify_structured_intent,
    normalize_structured_intent,
)


def _snapshot(
    root: Path,
    *,
    known_at: str = "2026-01-01T00:00:00Z",
    recorded_at: str = "2026-01-02T00:00:00Z",
) -> str:
    return record_source_snapshot(
        root,
        {
            "provider": "unit-test",
            "source_category": "reference-data",
            "source_locator": "unit-test:reference-data:v1",
            "provider_query": {"series": "fixture"},
            "known_at": known_at,
            "retrieved_at": recorded_at,
            "recorded_at": recorded_at,
            "revision": "original",
            "vintage": "2026-01-02",
            "timezone": "UTC",
            "coverage_note": "Synthetic regression fixture.",
            "payload": {"value": 1},
        },
    )["snapshot_id"]


def _forecast_args(snapshot_id: str, forecast_id: str, **overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "forecast_id": forecast_id,
        "artifact_id": f"artifact-{forecast_id}",
        "role": "fundamental-analyst",
        "author": "analyst-a",
        "instrument": "ACME",
        "forecast_target": "ACME meets its stated milestone",
        "target_type": "binary",
        "horizon": "2026-12-31",
        "issued_at": "2026-01-03T00:00:00Z",
        "knowledge_cutoff": "2026-01-02T00:00:00Z",
        "probability_range": [0.3, 0.5],
        "base_rate": {
            "cohort": "comparable milestones",
            "source_snapshot_id": snapshot_id,
            "sample_size": 20,
            "selection_rule": "announced milestones with observable outcomes",
            "value": 0.4,
        },
        "evidence_ids": [snapshot_id],
        "contrary_evidence": ["execution may slip"],
        "invalidation_conditions": ["milestone is withdrawn"],
        "update_triggers": ["company updates the milestone date"],
        "resolution_rule": "Resolve from the reviewed milestone-status snapshot.",
    }
    args.update(overrides)
    return args


def _research_spec_args() -> dict[str, object]:
    return {
        "spec_id": "pit-regression",
        "created_at": "2026-01-02T00:00:00Z",
        "created_by": "quant-researcher",
        "knowledge_cutoff": "2026-01-01T00:00:00Z",
        "hypothesis": "The preregistered signal predicts the target out of sample.",
        "economic_mechanism": "Delayed information diffusion creates a temporary repricing lag.",
        "universe": "point-in-time listed equities",
        "universe_membership_rule": "Membership is frozen at each observation date.",
        "target": "benchmark-relative 20-day return",
        "horizon": "20 trading days",
        "benchmark": "point-in-time equal-weight universe",
        "signal_definition": {"input": "fixture", "lag_days": 1, "expected_sign": "positive"},
        "falsification_criteria": ["out-of-sample effect is non-positive"],
        "validation_plan": {"out_of_sample": "untouched holdout", "walk_forward": "annual folds"},
        "parameter_trial_budget": 2,
        "cost_assumptions": {"commission_bps": 1, "slippage_bps": 5},
        "capacity_assumptions": {"max_adv_fraction": 0.01},
        "resolution_rule": "Compare the frozen signal with point-in-time benchmark returns.",
    }


def test_workflow_help_does_not_create_an_intake(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workflow_command(tmp_path, ["plan", "--help"])
    workflow_command(tmp_path, ["validate", "--help"])

    assert "Usage: tcx workflow" in capsys.readouterr().out
    assert not (tmp_path / ".tradingcodex/mainagent/latest-workflow-intake.json").exists()


def _checks(evidence_path: str, digest: str, *, failed: str = "") -> dict[str, dict[str, object]]:
    return {
        key: {
            "status": "fail" if key == failed else "pass",
            "reason": "Synthetic evidence exercises the typed gate.",
            "evidence_refs": [{"path": evidence_path, "sha256": digest}],
        }
        for key in REQUIRED_VALIDATION_CHECKS
    }


def test_money_contract_requires_fresh_snapshot_backed_fx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = ensure_workspace_manifest(tmp_path)
    save_active_profile_for_workspace(tmp_path, {**manifest["active_profile"], "base_currency": "EUR"})
    snapshot_id = _snapshot(tmp_path)
    fields = {
        "quantity": "0.1",
        "limit_price": "19.99",
        "currency": "GBP",
        "base_currency": "EUR",
        "fx_rate": "1.25",
        "fx_source_snapshot_id": snapshot_id,
        "fx_as_of": "2026-01-02T00:00:00Z",
        "created_at": "2026-01-02T12:00:00Z",
    }

    money = _money_contract_from_fields(tmp_path, fields)

    assert str(money["native_notional"]) == "1.999000"
    assert str(money["base_notional"]) == "2.498750"
    assert str(money["fx_rate"]) == "1.25"
    with pytest.raises(ValueError, match="positive fx_rate"):
        _money_contract_from_fields(tmp_path, {**fields, "fx_rate": ""})

    monkeypatch.setenv("TRADINGCODEX_MAX_FX_AGE_SECONDS", "60")
    with pytest.raises(ValueError, match="stale"):
        _money_contract_from_fields(tmp_path, fields)


def test_concurrent_decimal_paper_buys_do_not_overspend(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)
    portfolio_id, account_id, strategy_id = portfolio_keys({}, tmp_path)
    state = load_paper_portfolio_state(tmp_path, portfolio_id, account_id, strategy_id)
    state.update({"cash": {"USD": "100.00"}, "cash_base": "100.00", "expected_version": state["version"]})
    persist_paper_portfolio_state(tmp_path, state, portfolio_id, account_id, strategy_id)

    def buy(symbol: str) -> tuple[str, object]:
        close_old_connections()
        try:
            result = submit_paper_order(
                tmp_path,
                {
                    "id": f"concurrent-{symbol}",
                    "symbol": symbol,
                    "side": "buy",
                    "quantity": "1",
                    "limit_price": "60.00",
                    "currency": "USD",
                    "portfolio_id": portfolio_id,
                    "account_id": account_id,
                    "strategy_id": strategy_id,
                },
            )
            return "ok", result
        except (ValueError, PortfolioConcurrencyError) as exc:
            return "error", exc
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(buy, ("AAA", "BBB")))

    final = load_paper_portfolio_state(tmp_path, portfolio_id, account_id, strategy_id)
    assert [status for status, _ in results].count("ok") == 1
    assert final["cash"]["USD"] == "40.000000"
    assert sum(position["quantity"] == "1" for position in final["positions"].values()) == 1
    assert all(isinstance(value, str) for value in final["cash"].values())
    assert all(isinstance(position["quantity"], str) for position in final["positions"].values())


def test_paper_portfolio_does_not_spend_base_cash_as_foreign_cash(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)
    portfolio_id, account_id, strategy_id = portfolio_keys({}, tmp_path)

    with pytest.raises(ValueError, match="insufficient paper cash in EUR"):
        submit_paper_order(
            tmp_path,
            {
                "id": "missing-native-cash",
                "symbol": "EUR-ASSET",
                "side": "buy",
                "quantity": "1",
                "limit_price": "1.00",
                "currency": "EUR",
                "portfolio_id": portfolio_id,
                "account_id": account_id,
                "strategy_id": strategy_id,
            },
        )


def test_workflow_event_log_repairs_projection_after_interrupted_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = "event-first-recovery"
    initial = {
        "workflow_run_id": run_id,
        "lane": "research_only",
        "plan_version": 1,
        "plan_hash": "a" * 64,
        "routing_envelope_hash": "b" * 64,
        "intake_hash": "c" * 64,
        "blocked_actions": ["execution"],
        "counter": 0,
    }
    workflow_state_module.initialize_workflow_state(tmp_path, initial, latest_projection=dict)
    original_write_json = workflow_state_module.write_json
    failed_once = False

    def interrupted_write(path: Path, value: object) -> None:
        nonlocal failed_once
        if path.name == "loop-state.json" and not failed_once:
            failed_once = True
            raise OSError("simulated projection interruption")
        original_write_json(path, value)

    monkeypatch.setattr(workflow_state_module, "write_json", interrupted_write)
    with pytest.raises(OSError, match="projection interruption"):
        workflow_state_module.transition_workflow_state(
            tmp_path,
            run_id,
            event_type="increment",
            reason="exercise event-first recovery",
            event_id="increment:1",
            reducer=lambda state: {**state, "counter": int(state.get("counter") or 0) + 1},
            latest_projection=dict,
        )

    monkeypatch.setattr(workflow_state_module, "write_json", original_write_json)
    recovered = workflow_state_module.transition_workflow_state(
        tmp_path,
        run_id,
        event_type="increment",
        reason="idempotent retry",
        event_id="increment:1",
        reducer=lambda state: {**state, "counter": int(state.get("counter") or 0) + 1},
        latest_projection=dict,
    )
    assert recovered["counter"] == 1
    assert recovered["state_revision"] == 2
    assert workflow_state_module.replay_workflow_state(tmp_path, run_id) == recovered
    events = (workflow_state_module.workflow_state_path(tmp_path, run_id).parent / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 2


def test_research_append_is_atomic_compare_and_swap_with_immutable_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = create_research_artifact(
        tmp_path,
        {
            "artifact_id": "cas-note",
            "title": "CAS note",
            "markdown": "# CAS note\n\nalpha version",
            "export_path": "trading/research/cas-note.md",
        },
    )
    current_path = tmp_path / first["export_path"]
    original = current_path.read_text(encoding="utf-8")
    real_atomic_write = atomic_write_text

    def interrupt_current_write(path: Path, text: str) -> None:
        if Path(path) == current_path:
            raise OSError("simulated interrupted replace")
        real_atomic_write(Path(path), text)

    monkeypatch.setattr(research_module, "atomic_write_text", interrupt_current_write)
    with pytest.raises(OSError, match="simulated interrupted replace"):
        append_research_artifact_version(
            tmp_path,
            {
                "artifact_id": "cas-note",
                "markdown": "# CAS note\n\nbeta version",
                "expected_content_hash": first["content_hash"],
            },
        )
    assert current_path.read_text(encoding="utf-8") == original

    monkeypatch.setattr(research_module, "atomic_write_text", real_atomic_write)
    second = append_research_artifact_version(
        tmp_path,
        {
            "artifact_id": "cas-note",
            "markdown": "# CAS note\n\nbeta version",
            "expected_content_hash": first["content_hash"],
        },
    )
    assert second["version"] == 2
    assert "beta version" in get_research_artifact(tmp_path, {"artifact_id": "cas-note"})["markdown"]

    archive = tmp_path / "trading/research/.versions/cas-note" / f"v1-{first['content_hash'][:12]}.md"
    assert archive.exists()
    assert "alpha version" in archive.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="compare-and-swap failed"):
        append_research_artifact_version(
            tmp_path,
            {
                "artifact_id": "cas-note",
                "markdown": "# CAS note\n\nstale writer",
                "expected_content_hash": first["content_hash"],
            },
        )


def test_research_index_search_rebuild_and_stale_entry_removal(tmp_path: Path) -> None:
    created = create_research_artifact(
        tmp_path,
        {
            "artifact_id": "indexed-note",
            "title": "Indexed note",
            "markdown": "# Indexed note\n\nalpha-token",
            "export_path": "trading/research/indexed-note.md",
        },
    )
    assert [item["artifact_id"] for item in search_research_artifacts(tmp_path, {"query": "alpha-token"})["artifacts"]] == [
        "indexed-note"
    ]

    index_path = tmp_path / "trading/research/.index/research-index.json"
    index_path.write_text("{broken", encoding="utf-8")
    assert search_research_artifacts(tmp_path, {"query": "alpha-token"})["artifacts"]

    artifact_path = tmp_path / created["export_path"]
    stat = artifact_path.stat()
    artifact_path.write_text(artifact_path.read_text(encoding="utf-8").replace("alpha-token", "omega-token"), encoding="utf-8")
    os.utime(artifact_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    rebuilt = rebuild_research_index(tmp_path)
    assert rebuilt["artifact_count"] == 1
    assert [item["artifact_id"] for item in search_research_artifacts(tmp_path, {"query": "omega-token"})["artifacts"]] == [
        "indexed-note"
    ]

    artifact_path.unlink()
    assert search_research_artifacts(tmp_path, {"query": "omega-token"})["artifacts"] == []


def test_unsupported_language_fails_to_research_only_and_blocks_high_impact_actions() -> None:
    envelope = normalize_structured_intent("NVDA ÀÁÂÃÄÅ")
    routed = classify_structured_intent(envelope)

    assert envelope.safe_fallback is True
    assert envelope.requires_confirmation is True
    assert envelope.language == "und"
    assert set(HIGH_IMPACT_INTENT_ACTIONS) <= set(envelope.forbidden_actions)
    assert routed["lane"] == "research_only"
    assert routed["subagents"] == []


def test_high_confidence_language_adapter_schema_routes_only_validated_actions() -> None:
    envelope = normalize_structured_intent(
        "classified request",
        {
            "requested_actions": ["research", "valuation"],
            "forbidden_actions": ["order", "approval", "execution"],
            "unresolved_actions": [],
            "language": "x-test",
            "confidence": 0.95,
            "classifier_id": "reviewed-language-adapter",
            "classifier_version": "1",
        },
    )
    routed = classify_structured_intent(envelope)

    assert envelope.requires_confirmation is False
    assert routed["lane"] == "thesis_review"
    assert "execution-operator" not in routed["subagents"]
    assert {"order", "approval", "execution"} <= set(routed["blockedActions"])
    assert routed["structuredIntent"]["classifier_id"] == "reviewed-language-adapter"

    with pytest.raises(ValueError, match="unknown actions"):
        normalize_structured_intent(
            "classified",
            {
                "requested_actions": ["transfer_funds"],
                "confidence": 1,
                "classifier_id": "bad-adapter",
                "classifier_version": "1",
            },
        )


def test_new_workspaces_start_with_isolated_profiles_and_portfolios(tmp_path: Path) -> None:
    root_a = tmp_path / "workspace-a"
    root_b = tmp_path / "workspace-b"
    manifest_a = ensure_workspace_manifest(root_a)
    manifest_b = ensure_workspace_manifest(root_b)
    profile_a = manifest_a["active_profile"]
    profile_b = manifest_b["active_profile"]

    assert profile_a["shared"] is False
    assert profile_b["shared"] is False
    assert profile_a["portfolio_id"] != profile_b["portfolio_id"]
    save_active_profile_for_workspace(root_a, {**profile_a, "label": "workspace A only"})
    assert profile_a["profile_id"] in read_workspace_profiles(root_a)
    assert profile_a["profile_id"] not in read_workspace_profiles(root_b)

    submit_paper_order(
        root_a,
        {"id": "workspace-a-buy", "symbol": "ONLYA", "side": "buy", "quantity": "1", "limit_price": "1000"},
    )
    keys_a = portfolio_keys({}, root_a)
    keys_b = portfolio_keys({}, root_b)
    assert "ONLYA" in load_paper_portfolio_state(root_a, *keys_a)["positions"]
    assert load_paper_portfolio_state(root_b, *keys_b)["positions"] == {}
    assert active_profile_for_workspace(root_a)["label"] == "workspace A only"


def test_legacy_workspace_cash_and_currency_are_preserved(tmp_path: Path) -> None:
    manifest = ensure_workspace_manifest(tmp_path)
    legacy_profile = dict(manifest["active_profile"])
    legacy_profile.pop("base_currency")
    manifest.update({"schema_version": 1, "active_profile": legacy_profile})
    manifest_path = tmp_path / ".tradingcodex" / "workspace.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    ensure_runtime_database(tmp_path)
    from apps.portfolio.models import PortfolioSnapshot

    PortfolioSnapshot.objects.create(
        source="paper-trading",
        portfolio_id=legacy_profile["portfolio_id"],
        account_id=legacy_profile["account_id"],
        strategy_id=legacy_profile["strategy_id"],
        payload={"cash_krw": "100000000", "positions": {}},
    )

    state = load_paper_portfolio_state(
        tmp_path,
        legacy_profile["portfolio_id"],
        legacy_profile["account_id"],
        legacy_profile["strategy_id"],
    )

    assert active_profile_for_workspace(tmp_path)["base_currency"] == "KRW"
    assert state["base_currency"] == "KRW"
    assert state["cash"] == {"KRW": "100000000"}
    assert state["cash_base"] == "100000000"
    assert "cash_krw" not in state


def test_paper_accounts_follow_isolated_profiles_and_base_currencies(tmp_path: Path) -> None:
    root_a = tmp_path / "paper-account-a"
    root_b = tmp_path / "paper-account-b"
    profile_a = ensure_workspace_manifest(root_a)["active_profile"]
    profile_b = ensure_workspace_manifest(root_b)["active_profile"]
    save_active_profile_for_workspace(root_b, {**profile_b, "base_currency": "EUR"})

    connection_a = ensure_paper_broker_connection(root_a)
    connection_b = ensure_paper_broker_connection(root_b)

    from apps.integrations.models import BrokerAccount

    account_a = BrokerAccount.objects.get(
        broker_connection=connection_a,
        broker_account_id=profile_a["account_id"],
    )
    account_b = BrokerAccount.objects.get(
        broker_connection=connection_b,
        broker_account_id=profile_b["account_id"],
    )
    assert account_a.base_currency == "USD"
    assert account_b.base_currency == "EUR"
    assert account_a.metadata["portfolio_id"] == profile_a["portfolio_id"]
    assert account_b.metadata["portfolio_id"] == profile_b["portfolio_id"]


def test_currency_inference_fails_closed_at_external_boundaries(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)
    with pytest.raises(ValueError, match="currency symbols are ambiguous"):
        normalize_order_ticket_fields(tmp_path, {"natural_language": "buy 1 ACME at $100"})

    connection = type(
        "Connection",
        (),
        {
            "status": "read_only",
            "metadata": {"accounts": [{"id": "account-without-currency"}]},
        },
    )()
    with pytest.raises(ValueError, match="explicit base_currency"):
        ExternalMcpBrokerAdapter(connection).discover_accounts()


def test_range_only_forecast_preserves_revisions_without_claiming_a_proper_point_score(tmp_path: Path) -> None:
    snapshot_id = _snapshot(tmp_path)
    resolution_snapshot_id = _snapshot(
        tmp_path,
        known_at="2026-12-31T00:00:00Z",
        recorded_at="2026-12-31T00:00:00Z",
    )
    issued = issue_forecast(tmp_path, _forecast_args(snapshot_id, "range-only"))["forecast"]
    assert issued["probability"] is None
    assert issued.get("scoring_probability") is None
    with pytest.raises(ValueError, match="resolved before scoring"):
        score_forecast(tmp_path, {"forecast_id": "range-only"})
    with pytest.raises(ValueError, match="independent"):
        resolve_forecast(
            tmp_path,
            {
                "forecast_id": "range-only",
                "resolver": "analyst-a",
                "outcome": 1,
                "resolution_source_snapshot_id": snapshot_id,
            },
        )

    revise_forecast(
        tmp_path,
        {
            "forecast_id": "range-only",
            "author": "analyst-a",
            "revision_reason": "New execution evidence.",
            "probability_range": [0.5, 0.7],
            "revised_at": "2026-06-01T00:00:00Z",
        },
    )
    resolve_forecast(
        tmp_path,
        {
            "forecast_id": "range-only",
            "resolver": "independent-reviewer",
            "outcome": 1,
            "resolution_source_snapshot_id": resolution_snapshot_id,
            "resolved_at": "2026-12-31T00:00:00Z",
            "observed_at": "2026-12-31T00:00:00Z",
        },
    )
    scored = score_forecast(tmp_path, {"forecast_id": "range-only"})["forecast"]
    assert scored["scores"]["proper_score_available"] is False
    assert scored["scores"]["brier"] is None
    assert scored["scores"]["brier_bounds"] == pytest.approx([0.09, 0.25])
    assert scored["original_scores"]["brier_bounds"] == pytest.approx([0.25, 0.49])
    assert len(scored["scores_by_event"]) == 2
    assert [item["event_type"] for item in get_forecast(tmp_path, {"forecast_id": "range-only"})["history"]] == [
        "issued",
        "revised",
        "resolved",
        "scored",
    ]

    issue_forecast(tmp_path, _forecast_args(snapshot_id, "point", probability=0.8, probability_range=None))
    resolve_forecast(
        tmp_path,
        {
            "forecast_id": "point",
            "resolver": "independent-reviewer",
            "outcome": 1,
            "resolution_source_snapshot_id": resolution_snapshot_id,
            "resolved_at": "2026-12-31T00:00:00Z",
            "observed_at": "2026-12-31T00:00:00Z",
        },
    )
    score_forecast(tmp_path, {"forecast_id": "point"})

    assert calibration_report(tmp_path)["status"] == "insufficient_sample"
    report = calibration_report(tmp_path, {"minimum_sample": 2})
    assert report["status"] == "insufficient_sample"
    assert report["sample_size"] == 1
    assert report["excluded_range_only"] == 1


def test_forecast_chronology_scoped_idempotency_and_dispute_recovery(tmp_path: Path) -> None:
    base_snapshot_id = _snapshot(tmp_path)
    resolution_snapshot_id = _snapshot(
        tmp_path,
        known_at="2026-12-31T00:00:00Z",
        recorded_at="2026-12-31T00:00:00Z",
    )
    corrected_snapshot_id = _snapshot(
        tmp_path,
        known_at="2027-01-01T00:00:00Z",
        recorded_at="2027-01-01T00:00:00Z",
    )
    first = issue_forecast(
        tmp_path,
        _forecast_args(base_snapshot_id, "scoped-one", idempotency_key="shared-key"),
    )["forecast"]
    second = issue_forecast(
        tmp_path,
        _forecast_args(base_snapshot_id, "scoped-two", idempotency_key="shared-key"),
    )["forecast"]
    assert first["forecast_id"] == "scoped-one"
    assert second["forecast_id"] == "scoped-two"
    assert issue_forecast(
        tmp_path,
        _forecast_args(base_snapshot_id, "scoped-one", idempotency_key="shared-key"),
    )["forecast"]["event_id"] == first["event_id"]

    revised = revise_forecast(
        tmp_path,
        {
            "forecast_id": "scoped-one",
            "author": "analyst-a",
            "revision_reason": "New evidence.",
            "probability_range": [0.4, 0.6],
            "revised_at": "2026-06-01T00:00:00Z",
            "idempotency_key": "shared-key",
        },
    )["forecast"]
    assert revised["event_type"] == "revised"
    assert revise_forecast(
        tmp_path,
        {
            "forecast_id": "scoped-one",
            "author": "analyst-a",
            "revision_reason": "Ignored by idempotent retry.",
            "probability_range": [0.1, 0.2],
            "idempotency_key": "shared-key",
        },
    )["forecast"]["event_id"] == revised["event_id"]
    with pytest.raises(ValueError, match="previous forecast event"):
        revise_forecast(
            tmp_path,
            {
                "forecast_id": "scoped-one",
                "author": "analyst-a",
                "revision_reason": "Backdated revision.",
                "probability_range": [0.5, 0.6],
                "revised_at": "2026-05-31T00:00:00Z",
            },
        )
    with pytest.raises(ValueError, match="must not move backward"):
        revise_forecast(
            tmp_path,
            {
                "forecast_id": "scoped-one",
                "author": "analyst-a",
                "revision_reason": "Regressed cutoff.",
                "probability_range": [0.5, 0.6],
                "revised_at": "2026-06-02T00:00:00Z",
                "knowledge_cutoff": "2026-01-01T00:00:00Z",
            },
        )
    with pytest.raises(ValueError, match="forecast horizon"):
        resolve_forecast(
            tmp_path,
            {
                "forecast_id": "scoped-one",
                "resolver": "independent-reviewer",
                "outcome": 1,
                "resolution_source_snapshot_id": resolution_snapshot_id,
                "observed_at": "2026-12-30T00:00:00Z",
                "resolved_at": "2026-12-31T00:00:00Z",
            },
        )

    disputed = resolve_forecast(
        tmp_path,
        {
            "forecast_id": "scoped-one",
            "resolver": "independent-reviewer",
            "outcome": 1,
            "resolution_source_snapshot_id": resolution_snapshot_id,
            "observed_at": "2026-12-31T00:00:00Z",
            "resolved_at": "2026-12-31T00:00:00Z",
            "dispute_state": "disputed",
            "idempotency_key": "resolution-key",
        },
    )["forecast"]
    assert disputed["dispute_state"] == "disputed"
    with pytest.raises(ValueError, match="cannot be scored"):
        score_forecast(tmp_path, {"forecast_id": "scoped-one"})
    with pytest.raises(ValueError, match="resolve_dispute=true"):
        resolve_forecast(
            tmp_path,
            {
                "forecast_id": "scoped-one",
                "resolver": "independent-reviewer",
                "outcome": 0,
                "resolution_source_snapshot_id": corrected_snapshot_id,
            },
        )
    corrected = resolve_forecast(
        tmp_path,
        {
            "forecast_id": "scoped-one",
            "resolver": "independent-reviewer",
            "outcome": 0,
            "resolution_source_snapshot_id": corrected_snapshot_id,
            "observed_at": "2026-12-31T00:00:00Z",
            "resolved_at": "2027-01-01T00:00:00Z",
            "resolve_dispute": True,
            "idempotency_key": "resolution-key",
        },
    )["forecast"]
    assert corrected["event_type"] == "dispute_resolved"
    assert corrected["resolution_supersedes_event_id"] == disputed["event_id"]
    assert score_forecast(tmp_path, {"forecast_id": "scoped-one"})["forecast"]["event_type"] == "scored"

    future_base_rate = _forecast_args(base_snapshot_id, "future-base-rate")
    future_base_rate["base_rate"] = {**future_base_rate["base_rate"], "as_of": "2026-01-03T00:00:00Z"}
    with pytest.raises(ValueError, match="base_rate.as_of"):
        issue_forecast(tmp_path, future_base_rate)


def test_continuous_forecast_rejects_crossed_quantiles_and_scores_declared_intervals(tmp_path: Path) -> None:
    base_snapshot_id = _snapshot(tmp_path)
    resolution_snapshot_id = _snapshot(
        tmp_path,
        known_at="2026-12-31T00:00:00Z",
        recorded_at="2026-12-31T00:00:00Z",
    )
    crossed = _forecast_args(
        base_snapshot_id,
        "crossed-quantiles",
        target_type="continuous",
        probability_range=None,
        prediction=None,
        quantiles={"0.1": 20, "0.9": 10},
        base_rate={
            "cohort": "comparable outcomes",
            "source_snapshot_id": base_snapshot_id,
            "sample_size": 20,
            "selection_rule": "same target and unit",
            "prediction": 15,
        },
    )
    with pytest.raises(ValueError, match="nondecreasing"):
        issue_forecast(tmp_path, crossed)

    issue_forecast(
        tmp_path,
        _forecast_args(
            base_snapshot_id,
            "continuous-interval",
            target_type="continuous",
            probability_range=None,
            prediction=7,
            interval={"lower": 5, "upper": 10, "coverage": 0.8},
            quantiles={"0.1": 5, "0.9": 10},
            base_rate={
                "cohort": "comparable outcomes",
                "source_snapshot_id": base_snapshot_id,
                "sample_size": 20,
                "selection_rule": "same target and unit",
                "prediction": 8,
            },
        ),
    )
    resolve_forecast(
        tmp_path,
        {
            "forecast_id": "continuous-interval",
            "resolver": "independent-reviewer",
            "outcome": 12,
            "resolution_source_snapshot_id": resolution_snapshot_id,
            "observed_at": "2026-12-31T00:00:00Z",
            "resolved_at": "2026-12-31T00:00:00Z",
        },
    )
    scores = score_forecast(tmp_path, {"forecast_id": "continuous-interval"})["forecast"]["scores"]
    assert scores["proper_interval_score_available"] is True
    assert scores["interval_score"] == pytest.approx(25.0)


def test_research_spec_enforces_point_in_time_cutoff_and_typed_experiment_gates(tmp_path: Path) -> None:
    eligible_snapshot = _snapshot(tmp_path, known_at="2025-12-31T00:00:00Z")
    late_snapshot = _snapshot(tmp_path, known_at="2026-01-01T12:00:00Z")
    late_effective_snapshot = record_source_snapshot(
        tmp_path,
        {
            "provider": "unit-test",
            "source_category": "fundamental",
            "source_locator": "unit-test:late-effective",
            "known_at": "2025-12-31T00:00:00Z",
            "retrieved_at": "2026-01-02T00:00:00Z",
            "recorded_at": "2026-01-02T00:00:00Z",
            "effective_at": "2026-01-01T12:00:00Z",
            "revision": "original",
            "vintage": "2026Q1",
            "timezone": "UTC",
            "payload": {"value": 1},
        },
    )["snapshot_id"]
    spec = create_research_spec(tmp_path, _research_spec_args())["artifact"]

    with pytest.raises(ValueError, match="after knowledge cutoff"):
        create_replay_manifest(
            tmp_path,
            {
                "manifest_id": "late-replay",
                "spec_id": spec["spec_id"],
                "source_snapshot_ids": [late_snapshot],
                "created_by": "quant-researcher",
            },
        )

    with pytest.raises(ValueError, match="effective_at is after knowledge cutoff"):
        create_replay_manifest(
            tmp_path,
            {
                "manifest_id": "late-effective-replay",
                "spec_id": spec["spec_id"],
                "source_snapshot_ids": [late_effective_snapshot],
                "created_by": "quant-researcher",
            },
        )

    with pytest.raises(ValueError, match="must not predate"):
        create_replay_manifest(
            tmp_path,
            {
                "manifest_id": "backdated-replay",
                "spec_id": spec["spec_id"],
                "source_snapshot_ids": [eligible_snapshot],
                "created_at": "2026-01-01T00:00:00Z",
                "created_by": "quant-researcher",
            },
        )

    manifest = create_replay_manifest(
        tmp_path,
        {
            "manifest_id": "eligible-replay",
            "spec_id": spec["spec_id"],
            "source_snapshot_ids": [eligible_snapshot],
            "created_by": "quant-researcher",
        },
    )["artifact"]
    evidence = tmp_path / "trading/research/experiment-evidence.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('{"metric": 1}\n', encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    common = {
        "spec_id": spec["spec_id"],
        "replay_manifest_id": manifest["manifest_id"],
        "created_by": "quant-researcher",
        "code_hash": "a" * 64,
        "data_hash": "b" * 64,
        "config_hash": "c" * 64,
        "splits": {"train": "2000-2018", "test": "2019-2025"},
        "metrics": {"out_of_sample_return": -0.01},
    }
    failed_checks = _checks("trading/research/experiment-evidence.json", digest, failed="out_of_sample")
    not_applicable_checks = _checks("trading/research/experiment-evidence.json", digest)
    for check in not_applicable_checks.values():
        check["status"] = "not_applicable"

    with pytest.raises(ValueError, match="not allowed while validation checks fail"):
        record_experiment_run(
            tmp_path,
            {**common, "run_id": "invalid-positive", "trial_count": 1, "checks": failed_checks, "conclusion": "conditionally_promising"},
        )
    with pytest.raises(ValueError, match="trial_count exceeds"):
        record_experiment_run(
            tmp_path,
            {**common, "run_id": "over-budget", "trial_count": 3, "checks": _checks("trading/research/experiment-evidence.json", digest), "conclusion": "keep_researching"},
        )
    with pytest.raises(ValueError, match="at least one passed"):
        record_experiment_run(
            tmp_path,
            {
                **common,
                "run_id": "all-not-applicable",
                "trial_count": 1,
                "checks": not_applicable_checks,
                "conclusion": "conditionally_promising",
            },
        )

    recorded = record_experiment_run(
        tmp_path,
        {**common, "run_id": "rejected-signal", "trial_count": 2, "checks": failed_checks, "conclusion": "likely_overfit"},
    )["artifact"]
    assert recorded["failed_checks"] == ["out_of_sample"]
    assert recorded["conclusion"] == "likely_overfit"
    assert recorded["authority"] == "evidence_only"
    with pytest.raises(ValueError, match="cumulative trial_count"):
        record_experiment_run(
            tmp_path,
            {
                **common,
                "run_id": "cumulative-over-budget",
                "trial_count": 1,
                "checks": _checks("trading/research/experiment-evidence.json", digest),
                "conclusion": "keep_researching",
            },
        )


def test_causal_research_spec_rejects_post_cutoff_base_rate_cohort(tmp_path: Path) -> None:
    args = {
        **_research_spec_args(),
        "spec_id": "future-base-rate-cohort",
        "research_type": "listed_equity_valuation",
        "instrument": "ACME",
        "driver_tree": {"revenue": "units times price"},
        "base_rate_cohort": {
            "selection_rule": "same-industry issuers",
            "as_of": "2026-01-01T12:00:00Z",
            "sample_size": 20,
            "dispersion": "interquartile range",
            "limitations": ["small cohort"],
        },
        "implied_expectations_plan": {"method": "reverse_dcf"},
        "scenario_plan": {
            "scenarios": [
                {"name": "downside", "drivers": {"growth": -0.1}, "weight": 0.5},
                {"name": "upside", "drivers": {"growth": 0.1}, "weight": 0.5},
            ]
        },
        "method_reconciliation_plan": {"policy": "preserve disagreement"},
        "independent_review_plan": {"role": "judgment-reviewer"},
    }
    with pytest.raises(ValueError, match="base_rate_cohort.as_of"):
        create_research_spec(tmp_path, args)
