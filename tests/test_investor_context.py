from __future__ import annotations

from pathlib import Path

import pytest

from tradingcodex_service.application.investor_context import (
    INVESTOR_CONTEXT_PATH,
    clear_investor_context,
    investor_context_binding,
    read_investor_context,
    set_investor_context_enabled,
    update_investor_context,
)
from tradingcodex_service.application.runtime import (
    active_profile_for_workspace,
    ensure_workspace_manifest,
    save_active_profile_for_workspace,
)
from tradingcodex_service.application.workflow_contracts import intake_contract_hash
from tradingcodex_service.application.workflow_planner import (
    _initial_loop_state,
    build_workflow_intake,
    explicit_strategy_invocation,
    record_workflow_intake,
)


def test_context_is_lazy_file_native_and_can_be_disabled_per_run(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)

    empty = read_investor_context(tmp_path)
    assert empty["configured"] is False
    assert not (tmp_path / INVESTOR_CONTEXT_PATH).exists()

    saved = update_investor_context(
        tmp_path,
        {
            "investment_objective": "long-term capital growth",
            "time_horizon": "more than five years",
            "risk_tolerance_and_loss_capacity": "can tolerate a 20% drawdown",
            "constraints": ["taxable account", "no leverage"],
        },
    )
    assert saved["source"] == "workspace_file"
    assert saved["configured"] is True
    assert saved["content_hash"]

    applied = investor_context_binding(tmp_path)
    skipped = investor_context_binding(tmp_path, apply=False)
    assert applied["applied"] is True
    assert applied["fields"]["investment_objective"] == "long-term capital growth"
    assert skipped["applied"] is False
    assert skipped["fields"] == {}
    assert read_investor_context(tmp_path)["enabled_by_default"] is True


def test_context_default_toggle_clear_and_fail_closed_parsing(tmp_path: Path) -> None:
    update_investor_context(tmp_path, {"investment_objective": "income"})
    disabled = set_investor_context_enabled(tmp_path, False)
    assert disabled["enabled_by_default"] is False
    assert investor_context_binding(tmp_path)["applied"] is False

    cleared = clear_investor_context(tmp_path)
    assert cleared["status"] == "cleared"
    assert cleared["configured"] is False

    (tmp_path / INVESTOR_CONTEXT_PATH).write_text("# missing frontmatter\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version 1"):
        read_investor_context(tmp_path)
    assert clear_investor_context(tmp_path)["configured"] is False


def test_legacy_profile_context_is_read_then_migrated_on_update(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)
    active = active_profile_for_workspace(tmp_path)
    save_active_profile_for_workspace(
        tmp_path,
        {
            **active,
            "investor_profile": {
                "investment_objective": "legacy objective",
                "time_horizon": "legacy horizon",
            },
        },
    )

    legacy = read_investor_context(tmp_path)
    assert legacy["source"] == "legacy_active_profile"
    assert legacy["fields"]["investment_objective"] == "legacy objective"

    migrated = update_investor_context(tmp_path, {"liquidity_needs": "none expected"})
    assert migrated["source"] == "workspace_file"
    assert migrated["fields"]["time_horizon"] == "legacy horizon"
    assert migrated["fields"]["liquidity_needs"] == "none expected"


def test_context_rejects_unknown_or_oversized_fields(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown investor context"):
        update_investor_context(tmp_path, {"broker_password": "secret"})
    with pytest.raises(ValueError, match="exceeds"):
        update_investor_context(tmp_path, {"investment_objective": "x" * 2001})


def test_native_intake_seals_enabled_context_and_respects_workspace_default(tmp_path: Path) -> None:
    update_investor_context(tmp_path, {"investment_objective": "growth"})

    applied = record_workflow_intake(
        tmp_path,
        "Analyze NVDA. No order or trading.",
        workflow_run_id="workflow-native-context",
    )["investor_context_binding"]
    assert applied["applied"] is True
    assert applied["snapshot_path"] == (
        ".tradingcodex/mainagent/workflows/workflow-native-context/investor-context-snapshot.md"
    )
    assert (tmp_path / applied["snapshot_path"]).read_text(encoding="utf-8") == (
        tmp_path / INVESTOR_CONTEXT_PATH
    ).read_text(encoding="utf-8")

    sealed_content = (tmp_path / applied["snapshot_path"]).read_text(encoding="utf-8")
    update_investor_context(tmp_path, {"investment_objective": "income"})
    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        record_workflow_intake(
            tmp_path,
            "Analyze NVDA again. No order or trading.",
            workflow_run_id="workflow-native-context",
        )
    assert (tmp_path / applied["snapshot_path"]).read_text(encoding="utf-8") == sealed_content

    set_investor_context_enabled(tmp_path, False)
    disabled = record_workflow_intake(
        tmp_path,
        "Analyze MSFT. No order or trading.",
        workflow_run_id="workflow-native-context-disabled",
    )["investor_context_binding"]
    assert disabled["configured"] is True
    assert disabled["applied"] is False
    assert disabled["snapshot_path"] == ""
    assert not (
        tmp_path
        / ".tradingcodex/mainagent/workflows/workflow-native-context-disabled/investor-context-snapshot.md"
    ).exists()


def test_explicit_strategy_invocation_never_guesses_from_natural_language() -> None:
    assert explicit_strategy_invocation("Use $strategy-quality-watch for this review.") == "strategy-quality-watch"
    assert explicit_strategy_invocation("Use strategy-quality-watch for this review.") == ""
    assert explicit_strategy_invocation("Discuss `$strategy-quality-watch` without another strategy.") == "strategy-quality-watch"
    with pytest.raises(ValueError, match="exactly one"):
        explicit_strategy_invocation("Use $strategy-quality-watch and $strategy-value-watch.")


def test_workflow_intake_hash_binds_strategy_and_context_choice(tmp_path: Path) -> None:
    update_investor_context(tmp_path, {"investment_objective": "growth"})
    context = investor_context_binding(tmp_path, apply=False)
    strategy = {
        "strategy_id": "strategy-quality",
        "source_file": ".agents/skills/strategy-quality/SKILL.md",
        "content_hash": "a" * 64,
        "snapshot_path": ".tradingcodex/mainagent/workflows/run/strategy-snapshot.md",
    }
    intake = build_workflow_intake(
        "Analyze NVDA. No order or trading.",
        tmp_path,
        strategy_binding=strategy,
        context_binding=context,
    )

    assert intake["strategy_binding"] == strategy
    assert intake["investor_context_binding"]["applied"] is False
    assert intake["intake_hash"] == intake_contract_hash(intake)

    changed = {**intake, "strategy_binding": {**strategy, "strategy_id": "strategy-other"}}
    assert changed["intake_hash"] != intake_contract_hash(changed)

    state = _initial_loop_state(
        {
            "workflow_run_id": intake["workflow_run_id"],
            "lane": "research_only",
            "plan_hash": "b" * 64,
            "routing_envelope_hash": "c" * 64,
            "intake_hash": intake["intake_hash"],
            "strategy_binding": intake["strategy_binding"],
            "investor_context_binding": intake["investor_context_binding"],
            "stages": [],
            "blocked_actions": [],
        },
        intake,
    )
    assert state["strategy_binding"] == strategy
    assert state["investor_context_binding"]["applied"] is False
