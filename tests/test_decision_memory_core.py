from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradingcodex_cli.commands.decision import decision as decision_command
from tradingcodex_cli.commands.mcp import mcp as mcp_command
from tradingcodex_cli.commands.orders import postmortem as postmortem_command
from tradingcodex_service.application.common import file_hash
from tradingcodex_service.application.decision_packages import get_decision_snapshot, record_decision_snapshot
from tradingcodex_service.application.forecasting import get_forecast, issue_forecast, list_forecasts, resolve_forecast, score_forecast
from tradingcodex_service.application.postmortems import create_postmortem, promote_lesson, record_postmortem_process_review
from tradingcodex_service.application.research import create_research_artifact, record_source_snapshot
from tradingcodex_service.application.research_specs import create_replay_manifest, create_research_spec
from tradingcodex_service.application.workflow_planner import record_workflow_intake, record_workflow_plan


def _snapshot(root: Path, category: str, known_at: str, value: object) -> str:
    return record_source_snapshot(root, {
        "provider": "decision-memory-test",
        "source_category": category,
        "known_at": known_at,
        "retrieved_at": known_at,
        "recorded_at": known_at,
        "revision": "original",
        "vintage": known_at[:10],
        "payload": {"value": value},
    })["snapshot_id"]


def _forecast_args(snapshot_id: str, forecast_id: str, **overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "forecast_id": forecast_id,
        "artifact_id": "decision-evidence",
        "role": "fundamental-analyst",
        "author": "fundamental-analyst",
        "forecast_target": "Revenue growth is positive.",
        "target_type": "binary",
        "horizon": "2026-06-30T00:00:00Z",
        "issued_at": "2026-01-02T00:00:00Z",
        "knowledge_cutoff": "2026-01-01T00:00:00Z",
        "probability": 0.7,
        "base_rate": {
            "cohort": "comparable issuers",
            "source_snapshot_id": snapshot_id,
            "sample_size": 30,
            "selection_rule": "same reporting regime",
            "value": 0.5,
        },
        "evidence_ids": ["decision-evidence"],
        "contrary_evidence": ["Demand may weaken."],
        "invalidation_conditions": ["Reported growth is non-positive."],
        "update_triggers": ["Guidance changes."],
        "resolution_rule": "Resolve from the audited filing.",
    }
    args.update(overrides)
    return args


def test_historical_lane_is_inherited_and_forecast_hash_chain_detects_tampering(tmp_path: Path) -> None:
    base_snapshot = _snapshot(tmp_path, "base-rate", "2026-01-01T00:00:00Z", 0.5)
    spec = create_research_spec(tmp_path, {
        "spec_id": "historical-spec",
        "created_by": "fundamental-analyst",
        "knowledge_cutoff": "2026-01-01T00:00:00Z",
        "evidence_lane": "historical_replay",
        "hypothesis": "The point-in-time evidence predicts positive growth.",
        "economic_mechanism": "Demand converts into reported revenue.",
        "universe": "point-in-time listed equities",
        "universe_membership_rule": "Use membership known at the cutoff.",
        "target": "positive revenue growth",
        "horizon": "2026-06-30",
        "falsification_criteria": ["non-positive revenue growth"],
        "validation_plan": {"walk_forward": True},
        "resolution_rule": "Resolve from the audited filing.",
    })["artifact"]
    manifest = create_replay_manifest(tmp_path, {
        "manifest_id": "historical-replay",
        "spec_id": spec["spec_id"],
        "source_snapshot_ids": [base_snapshot],
        "created_by": "fundamental-analyst",
    })["artifact"]

    issued = issue_forecast(tmp_path, _forecast_args(
        base_snapshot,
        "historical-forecast",
        research_spec_id=spec["spec_id"],
        replay_manifest_id=manifest["manifest_id"],
    ))["forecast"]
    assert manifest["evidence_lane"] == "historical_replay"
    assert issued["evidence_lane"] == "historical_replay"
    assert issued["research_spec_ref"]["analysis_plan_hash"] == spec["analysis_plan_hash"]
    assert issued["replay_manifest_ref"]["manifest_hash"] == manifest["manifest_hash"]
    assert issued["event_hash"]
    assert issued["prior_event_hash"] == ""
    assert list_forecasts(tmp_path, {"evidence_lane": "live_forward"})["count"] == 0
    assert list_forecasts(tmp_path, {"evidence_lane": "historical_replay"})["count"] == 1
    with pytest.raises(ValueError, match="evidence_lane must be one of"):
        create_research_artifact(tmp_path, {
            "artifact_id": "invalid-lane",
            "markdown": "# Invalid lane\n",
            "evidence_lane": "backtest",
        })

    ledger = tmp_path / "trading/forecasts/forecast-ledger.jsonl"
    event = json.loads(ledger.read_text(encoding="utf-8"))
    event["schema_version"] = 2
    event.pop("event_hash", None)
    event["probability"] = 0.1
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="chain head mismatch|chain head count mismatch"):
        get_forecast(tmp_path, {"forecast_id": "historical-forecast"})


def test_decision_snapshot_postmortem_and_live_lesson_promotion_are_hash_bound(tmp_path: Path, capsys, monkeypatch) -> None:
    clock = [datetime.now(timezone.utc) + timedelta(minutes=5)]

    def system_now() -> str:
        return clock[0].isoformat().replace("+00:00", "Z")

    for module in ("forecasting", "decision_packages", "postmortems", "research", "research_specs"):
        monkeypatch.setattr(f"tradingcodex_service.application.{module}.now_iso", system_now)

    cutoff = (clock[0] - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    issued_at = system_now()
    horizon = (clock[0] + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    base_snapshot = _snapshot(tmp_path, "base-rate", cutoff, 0.5)
    future_issue = (clock[0] + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="issued_at must not be after system recorded_at"):
        issue_forecast(tmp_path, _forecast_args(
            base_snapshot,
            "future-live-forecast",
            issued_at=future_issue,
            horizon=horizon,
        ))
    protected_dir = tmp_path / ".tradingcodex/mainagent/workflows/workflow-memory"
    protected_dir.mkdir(parents=True)
    strategy_content = "---\nname: strategy-frozen\nstatus: active\n---\n\n# Frozen Strategy\n"
    strategy_snapshot = protected_dir / "strategy-snapshot.md"
    strategy_snapshot.write_text(strategy_content, encoding="utf-8")
    strategy_hash = hashlib.sha256(strategy_content.encode("utf-8")).hexdigest()
    context_content = "---\nschema_version: 1\nrisk_tolerance_and_loss_capacity: moderate\n---\n\n# Investor Context\n"
    context_snapshot = protected_dir / "investor-context-snapshot.md"
    context_snapshot.write_text(context_content, encoding="utf-8")
    context_hash = hashlib.sha256(context_content.encode("utf-8")).hexdigest()

    first_strategy = {
        "strategy_id": "strategy-frozen",
        "source_file": ".agents/skills/strategy-frozen/SKILL.md",
        "content_hash": strategy_hash,
        "snapshot_path": strategy_snapshot.relative_to(tmp_path).as_posix(),
    }
    first_context = {
        "schema_version": 1,
        "applied": True,
        "configured": True,
        "enabled_by_default": True,
        "source": "workspace_file",
        "path": ".tradingcodex/user/investor-context.md",
        "content_hash": context_hash,
        "snapshot_path": context_snapshot.relative_to(tmp_path).as_posix(),
        "fields": {"risk_tolerance_and_loss_capacity": "moderate"},
    }
    no_context = {"schema_version": 1, "applied": False, "configured": False, "source": "none"}

    def create_episode(name: str, *, strategy_binding=None, context_binding=None) -> dict:
        workflow_run_id = f"workflow-{name}"
        intake = record_workflow_intake(
            tmp_path,
            f"Analyze bounded forecast {name}. No order or execution.",
            workflow_run_id=workflow_run_id,
            strategy_binding=strategy_binding,
            context_binding=context_binding or no_context,
        )
        plan = record_workflow_plan(tmp_path, {
            "workflow_run_id": workflow_run_id,
            "selected_roles": intake["heuristic_roles"],
            "planner_rationale": "Freeze a test episode for Decision Memory.",
        })
        assert plan["status"] == "recorded"
        artifact_id = f"{name}-decision-evidence"
        artifact = create_research_artifact(tmp_path, {
            "artifact_id": artifact_id,
            "artifact_type": "synthesis_report",
            "role": "head-manager",
            "title": f"Accepted decision evidence {name}",
            "markdown": f"# Accepted decision evidence {name}\n\n[factual] Bounded evidence for {name}.\n",
            "handoff_state": "accepted",
            "readiness_label": "accepted",
            "workflow_run_id": workflow_run_id,
            "plan_hash": plan["plan_hash"],
            "knowledge_cutoff": cutoff,
            "evidence_lane": "live_forward",
            "created_by": "head-manager",
            "export_path": f"trading/reports/head-manager/{artifact_id}.md",
        })
        forecast_id = f"{name}-forecast"
        issued = issue_forecast(tmp_path, _forecast_args(
            base_snapshot,
            forecast_id,
            artifact_id=artifact_id,
            workflow_run_id=workflow_run_id,
            artifact_path=artifact["export_path"],
            knowledge_cutoff=cutoff,
            issued_at=issued_at,
            horizon=horizon,
        ))["forecast"]
        snapshot_result = record_decision_snapshot(tmp_path, {
            "decision_id": f"{name}-decision",
            "workflow_run_id": workflow_run_id,
            "decision_artifact_path": artifact["export_path"],
            "forecast_ids": [forecast_id],
            "knowledge_cutoff": cutoff,
            "decided_at": system_now(),
            "created_by": "head-manager",
        })
        return {"name": name, "plan": plan, "artifact": artifact, "issued": issued, "forecast_id": forecast_id, "snapshot": snapshot_result}

    first = create_episode("memory", strategy_binding=first_strategy, context_binding=first_context)
    second = create_episode("corroboration")
    third = create_episode("validation")
    disputed = create_episode("disputed")
    late_review = create_episode("late-review")
    with pytest.raises(ValueError, match="forecast belongs to another workflow run"):
        record_decision_snapshot(tmp_path, {
            "decision_id": "wrong-run-decision",
            "workflow_run_id": "workflow-corroboration",
            "decision_artifact_path": second["artifact"]["export_path"],
            "forecast_ids": [first["forecast_id"]],
            "knowledge_cutoff": cutoff,
            "decided_at": system_now(),
            "created_by": "head-manager",
        })
    earlier_cutoff = (datetime.fromisoformat(cutoff.replace("Z", "+00:00")) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="forecast knowledge_cutoff exceeds decision cutoff"):
        record_decision_snapshot(tmp_path, {
            "decision_id": "wrong-cutoff-decision",
            "workflow_run_id": "workflow-memory",
            "decision_artifact_path": first["artifact"]["export_path"],
            "forecast_ids": [first["forecast_id"]],
            "knowledge_cutoff": earlier_cutoff,
            "decided_at": system_now(),
            "created_by": "head-manager",
        })
    snapshot = first["snapshot"]["decision_snapshot"]
    assert "content" not in snapshot["strategy_ref"]
    assert "content" not in snapshot["investor_context_ref"]
    assert "fields" not in snapshot["investor_context_ref"]
    assert snapshot["strategy_ref"]["content_hash"] == strategy_hash
    assert snapshot["investor_context_ref"]["snapshot_sha256"] == context_hash
    assert get_decision_snapshot(tmp_path, "memory-decision")["verification_status"] == "verified"
    decision_command(tmp_path, ["snapshot", "show", "memory-decision"])
    assert json.loads(capsys.readouterr().out)["decision_snapshot"]["decision_id"] == "memory-decision"

    process_review = record_postmortem_process_review(tmp_path, {
        "id": "memory-process-review",
        "decision_snapshot_id": "memory-decision",
        "created_by": "head-manager",
        "process_review": {
            "original_thesis": "Revenue growth would remain positive.",
            "evidence_quality": "Sources were bounded and point in time.",
            "base_rate_quality": "The comparison cohort was explicit.",
            "alternatives_considered": "Demand weakening was considered.",
            "assumptions": "Demand translated into revenue.",
            "confidence_process": "The probability was stated before the outcome.",
            "invalidation_discipline": "Negative growth would invalidate the thesis.",
            "handoff_process": "The accepted artifact was run-bound.",
            "process_conclusion": "The process was adequate before outcome reveal.",
        },
    })
    disputed_process_review = record_postmortem_process_review(tmp_path, {
        "id": "disputed-process-review",
        "decision_snapshot_id": "disputed-decision",
        "created_by": "head-manager",
        "process_review": process_review["process_review"]["process_review"],
    })

    clock[0] += timedelta(days=31)
    outcome_at = system_now()
    outcome_snapshot = _snapshot(tmp_path, "resolution", outcome_at, 1)
    scores = {}
    for episode in (first, second, third):
        resolve_forecast(tmp_path, {
            "forecast_id": episode["forecast_id"],
            "resolver": "judgment-reviewer",
            "outcome": 1,
            "resolution_source_snapshot_id": outcome_snapshot,
            "observed_at": outcome_at,
            "resolved_at": outcome_at,
        })
        scores[episode["name"]] = score_forecast(tmp_path, {"forecast_id": episode["forecast_id"]})["forecast"]

    resolve_forecast(tmp_path, {
        "forecast_id": disputed["forecast_id"],
        "resolver": "judgment-reviewer",
        "outcome": 1,
        "resolution_source_snapshot_id": outcome_snapshot,
        "observed_at": outcome_at,
        "resolved_at": outcome_at,
        "dispute_state": "disputed",
    })
    with pytest.raises(ValueError, match="disputed forecasts cannot be scored"):
        score_forecast(tmp_path, {"forecast_id": disputed["forecast_id"]})

    resolve_forecast(tmp_path, {
        "forecast_id": late_review["forecast_id"],
        "resolver": "judgment-reviewer",
        "outcome": 1,
        "resolution_source_snapshot_id": outcome_snapshot,
        "observed_at": outcome_at,
        "resolved_at": outcome_at,
    })
    clock[0] += timedelta(seconds=1)
    with pytest.raises(ValueError, match="outcome is already recorded"):
        record_postmortem_process_review(tmp_path, {
            "id": "late-process-review",
            "decision_snapshot_id": "late-review-decision",
            "created_by": "head-manager",
            "process_review": process_review["process_review"]["process_review"],
        })

    postmortem_payload = {
        "id": "memory-postmortem",
        "decision_snapshot_id": "memory-decision",
        "process_review_id": process_review["process_review"]["id"],
        "forecast_ids": [first["forecast_id"]],
        "trigger": "forecast_outcome",
        "created_by": "head-manager",
        "findings": [{"category": "forecast", "summary": "The forecast resolved positively."}],
        "investment_judgment_review": {
            "original_thesis": "Revenue growth would remain positive.",
            "what_happened": "Revenue growth was positive.",
            "failed_assumption": "No material assumption failed.",
            "role_evidence_miss_or_overstatement": "The evidence range was appropriately bounded.",
            "stale_weak_or_misleading_source": "No stale source was used.",
            "confidence_calibration": "The probability was directionally calibrated.",
            "future_warning_pattern": "Recheck demand before reusing the lesson.",
        },
        "next_actions": ["Seek an independent live-forward case."],
        "lesson_candidates": [{
            "statement": "Positive demand evidence may support positive revenue growth.",
            "reason": "The bounded forecast resolved positively.",
            "scope": "comparable reporting regimes",
            "counterevidence": ["Demand can reverse before reporting."],
            "invalidation_conditions": ["Guidance turns negative."],
        }],
    }
    postmortem = create_postmortem(tmp_path, postmortem_payload)
    with pytest.raises(ValueError, match="outcome is disputed or under review"):
        create_postmortem(tmp_path, {
            **postmortem_payload,
            "id": "disputed-postmortem",
            "decision_snapshot_id": "disputed-decision",
            "process_review_id": disputed_process_review["process_review"]["id"],
            "forecast_ids": [disputed["forecast_id"]],
        })
    lesson = postmortem["lesson_records"][0]
    assert lesson["lesson_state"] == "candidate"
    assert lesson["lesson_sequence"] == 1
    postmortem_command(tmp_path, ["show", "memory-postmortem"])
    assert json.loads(capsys.readouterr().out)["verification_status"] == "verified"
    with pytest.raises(PermissionError, match="unavailable from CLI"):
        postmortem_command(tmp_path, ["promote-lesson"])
    with pytest.raises(PermissionError, match="unavailable from generic CLI"):
        mcp_command(tmp_path, ["call", "promote_lesson", "--principal", "judgment-reviewer"])
    with pytest.raises(PermissionError, match="authenticated judgment-reviewer"):
        promote_lesson(tmp_path, {"lesson_id": lesson["lesson_id"], "to_state": "retired", "reason": "unauthorized"}, authenticated_principal="head-manager")
    with pytest.raises(ValueError, match="invalid lesson transition"):
        promote_lesson(tmp_path, {
            "lesson_id": lesson["lesson_id"], "to_state": "validated", "reason": "cannot skip", "regimes": ["test"]
        }, authenticated_principal="judgment-reviewer")

    def evidence_ref(episode: dict) -> dict:
        scored = scores[episode["name"]]
        return {
            "forecast_id": episode["forecast_id"],
            "event_id": scored["event_id"],
            "event_hash": scored["event_hash"],
            "decision_snapshot_id": episode["snapshot"]["decision_snapshot"]["decision_id"],
        }

    corroborated = promote_lesson(tmp_path, {
        "lesson_id": lesson["lesson_id"],
        "to_state": "corroborated",
        "reason": "A second sealed episode corroborates the candidate.",
        "regimes": ["test"],
        "evidence_refs": [evidence_ref(second)],
    }, authenticated_principal="judgment-reviewer")["lesson"]
    assert corroborated["lesson_sequence"] == 2
    assert len(corroborated["used_episode_ids"]) == 2
    with pytest.raises(ValueError, match="untouched scored"):
        promote_lesson(tmp_path, {
            "lesson_id": lesson["lesson_id"],
            "to_state": "validated",
            "reason": "The original episode is not an untouched test.",
            "regimes": ["test"],
            "evidence_refs": [evidence_ref(first)],
        }, authenticated_principal="judgment-reviewer")
    validated = promote_lesson(tmp_path, {
        "lesson_id": lesson["lesson_id"],
        "to_state": "validated",
        "reason": "A third untouched live-forward episode passed.",
        "regimes": ["test"],
        "evidence_refs": [evidence_ref(third)],
    }, authenticated_principal="judgment-reviewer")["lesson"]
    assert validated["lesson_sequence"] == 3
    assert validated["reuse_state"] == "available_for_future_judgment"

    strategy_snapshot.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="strategy run snapshot path/hash mismatch"):
        get_decision_snapshot(tmp_path, "memory-decision")
    strategy_snapshot.write_text(strategy_content, encoding="utf-8")
    ledger = tmp_path / ".tradingcodex/mainagent/improve.jsonl"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"lesson_id": lesson["lesson_id"], "lesson_state": "validated", "reuse_state": "available_for_future_judgment"}) + "\n")
    with pytest.raises(ValueError, match="unsealed downgrade"):
        promote_lesson(tmp_path, {"lesson_id": lesson["lesson_id"], "to_state": "retired", "reason": "tamper check"}, authenticated_principal="judgment-reviewer")


def test_postmortem_schema_matches_the_service_contract() -> None:
    path = Path(
        "workspace_templates/modules/enforcement-guardrails/files/"
        ".tradingcodex/schemas/postmortem_report.schema.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == 3
    assert {
        "recorded_at",
        "decision_snapshot_ref",
        "process_review_ref",
        "forecast_outcome_refs",
        "investment_judgment_review",
        "lesson_candidates",
        "report_hash",
    }.issubset(schema["required"])
    assert set(schema["properties"]["investment_judgment_review"]["required"]) == {
        "original_thesis",
        "what_happened",
        "failed_assumption",
        "role_evidence_miss_or_overstatement",
        "stale_weak_or_misleading_source",
        "confidence_calibration",
        "future_warning_pattern",
    }
