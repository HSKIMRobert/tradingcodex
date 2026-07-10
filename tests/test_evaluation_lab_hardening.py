from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from django.test import Client

from apps.policy.models import Capability, Principal
from apps.policy.services import sync_builtin_principals_and_capabilities
from tradingcodex_cli.commands.evaluation import evaluation as evaluation_command
from tradingcodex_service.application.common import file_hash, stable_hash
from tradingcodex_service.application.evaluation_lab import (
    HARD_FAILURE_CHECKS,
    REQUIRED_CASE_TAGS,
    compare_evaluation_runs,
    create_evaluation_corpus,
    record_evaluation_run,
)
from tradingcodex_service.application.runtime import ensure_runtime_database
from tradingcodex_service.mcp_runtime import call_mcp_tool


def _frozen_corpus(root: Path, *, minimum_reviews: int = 2) -> dict:
    manifest = {
        "schema_version": 1,
        "artifact_type": "replay_manifest",
        "manifest_id": "evaluation-replay",
        "knowledge_cutoff": "2026-01-01T00:00:00Z",
    }
    manifest["manifest_hash"] = stable_hash(manifest)
    manifest_path = root / "trading/research/replay-manifests/evaluation-replay.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    hard_checks = {check: True for check in HARD_FAILURE_CHECKS.values()}
    cases = [
        {
            "case_id": f"case-{index:02d}-{tag}",
            "tags": [tag],
            "replay_manifest_id": "evaluation-replay",
            "prompt": f"Evaluate the frozen {tag} case.",
            "expected_checks": {**hard_checks, "case_outcome_correct": True},
            "blind_review_rubric": {"quality": "Prefer the more accurate evidence-bound output."},
            "forbidden_actions": ["portfolio_mutation"],
        }
        for index, tag in enumerate(sorted(REQUIRED_CASE_TAGS), start=1)
    ]
    return create_evaluation_corpus(root, {
        "corpus_id": f"corpus-{uuid.uuid4().hex[:8]}",
        "created_by": "head-manager",
        "cases": cases,
        "minimum_blind_reviews": minimum_reviews,
        "promotion_criteria": [{
            "dimension": "evidence",
            "metric": "quality",
            "direction": "higher_is_better",
            "max_regression": 0,
            "minimum_candidate": 0.5,
        }],
    })["artifact"]


def _case_results(root: Path, corpus: dict, arm: str, score: float, *, hard_failure: bool = False) -> list[dict]:
    results = []
    for index, case in enumerate(corpus["cases"]):
        artifact_path = root / f"trading/evaluations/artifacts/{arm}/{case['case_id']}.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(f"# {arm} blind output\n\ncase={case['case_id']}\n", encoding="utf-8")
        checks = dict(case["expected_checks"])
        if hard_failure and index == 0:
            checks["no_scope_widening"] = False
        results.append({
            "case_id": case["case_id"],
            "deterministic_checks": checks,
            "artifact_hashes": {artifact_path.relative_to(root).as_posix(): file_hash(artifact_path)},
            "metrics": {"evidence": {"quality": score}},
        })
    return results


def _run(root: Path, corpus: dict, arm: str, score: float, *, hard_failure: bool = False, **overrides) -> dict:
    payload = {
        "run_id": f"{arm}-{uuid.uuid4().hex[:8]}",
        "corpus_id": corpus["corpus_id"],
        "arm": arm,
        "model": "gpt-5.5" if arm == "control" else "gpt-5.6",
        "reasoning_effort": "high",
        "prompt_hash": "1" * 64,
        "config_hash": "2" * 64,
        "tool_profile_hash": "3" * 64,
        "deterministic_calculation_hash": "4" * 64,
        "extension_profile_hash": "5" * 64,
        "case_results": _case_results(root, corpus, arm, score, hard_failure=hard_failure),
        "metrics": {"evidence": {"quality": score}},
        "operations": {"budget": {"max_tokens": 100_000, "max_seconds": 3_600}, "latency_ms": 100},
        "created_by": "head-manager",
    }
    payload.update(overrides)
    return record_evaluation_run(root, payload)["artifact"]


def _reviewer(principal_id: str) -> None:
    principal, _ = Principal.objects.update_or_create(
        principal_id=principal_id,
        defaults={"role": "judgment-reviewer", "active": True},
    )
    for action in ("evaluation.review", "evaluation.review.read"):
        Capability.objects.get_or_create(
            principal=principal,
            action=action,
            resource_pattern="*",
            defaults={"effect": "allow"},
        )


def test_run_metrics_hard_failures_duplicates_and_artifacts_are_service_derived(tmp_path: Path) -> None:
    corpus = _frozen_corpus(tmp_path)
    results = _case_results(tmp_path, corpus, "control", 0.8)
    duplicate_results = [*results, dict(results[0])]
    with pytest.raises(ValueError, match="duplicate evaluation case result"):
        _run(tmp_path, corpus, "control", 0.8, case_results=duplicate_results)

    bad_hash_results = _case_results(tmp_path, corpus, "bad-hash", 0.8)
    bad_hash_results[0]["artifact_hashes"] = {next(iter(bad_hash_results[0]["artifact_hashes"])): "z" * 64}
    with pytest.raises(ValueError, match="64-character hexadecimal"):
        _run(tmp_path, corpus, "control", 0.8, case_results=bad_hash_results)

    with pytest.raises(ValueError, match="do not match metrics derived"):
        _run(tmp_path, corpus, "control", 0.8, metrics={"evidence": {"quality": 0.9}})

    candidate = _run(
        tmp_path,
        corpus,
        "candidate",
        0.9,
        hard_failure=True,
        pair_provenance={"status": "trusted_runner_verified", "verified": True},
    )
    assert candidate["metrics"] == {"evidence": {"quality": pytest.approx(0.9)}}
    assert candidate["metrics_source"] == "derived_from_frozen_case_results"
    assert candidate["hard_failures"] == [{
        "case_id": corpus["cases"][0]["case_id"],
        "failure_type": "scope_widening",
        "failed_check": "no_scope_widening",
    }]
    assert candidate["pair_provenance"]["verified"] is False
    assert candidate["pair_provenance"]["status"] == "caller_attested_unverified"


def test_evaluation_services_accept_a_symlinked_workspace_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-workspace"
    real_root.mkdir()
    linked_root = tmp_path / "linked-workspace"
    linked_root.symlink_to(real_root, target_is_directory=True)

    corpus = _frozen_corpus(linked_root)
    control = _run(linked_root, corpus, "control", 0.8)
    candidate = _run(linked_root, corpus, "candidate", 0.8)
    comparison = compare_evaluation_runs(linked_root, {
        "control_run_id": control["run_id"],
        "candidate_run_id": candidate["run_id"],
    })

    assert comparison["export_path"].startswith("trading/evaluations/comparisons/")


def test_corpus_requires_distinct_case_breadth_and_pair_hashes_are_immutable(tmp_path: Path) -> None:
    manifest = {"manifest_id": "one"}
    manifest["manifest_hash"] = stable_hash(manifest)
    path = tmp_path / "trading/research/replay-manifests/one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    checks = {check: True for check in HARD_FAILURE_CHECKS.values()}
    with pytest.raises(ValueError, match="distinct case"):
        create_evaluation_corpus(tmp_path, {
            "created_by": "head-manager",
            "cases": [{
                "case_id": "one-case",
                "tags": sorted(REQUIRED_CASE_TAGS),
                "replay_manifest_id": "one",
                "prompt": "one broad case",
                "expected_checks": checks,
                "blind_review_rubric": {"quality": "rubric"},
                "forbidden_actions": ["order"],
            }],
            "promotion_criteria": [{
                "dimension": "evidence",
                "metric": "quality",
                "direction": "higher_is_better",
                "max_regression": 0,
            }],
        })

    corpus = _frozen_corpus(tmp_path)
    control = _run(tmp_path, corpus, "control", 0.8)
    candidate = _run(tmp_path, corpus, "candidate", 0.9, prompt_hash="9" * 64)
    with pytest.raises(ValueError, match="prompt_hash"):
        compare_evaluation_runs(tmp_path, {
            "control_run_id": control["run_id"],
            "candidate_run_id": candidate["run_id"],
        })

    run_path = tmp_path / f"trading/evaluations/runs/{control['run_id']}.json"
    tampered = json.loads(run_path.read_text(encoding="utf-8"))
    tampered["model"] = "tampered"
    run_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        compare_evaluation_runs(tmp_path, {
            "control_run_id": control["run_id"],
            "candidate_run_id": candidate["run_id"],
        })


def test_two_authenticated_reviewers_use_blind_assignments_across_mcp_and_api(monkeypatch, tmp_path: Path) -> None:
    ensure_runtime_database(tmp_path)
    sync_builtin_principals_and_capabilities()
    reviewer_one = f"reviewer-one-{uuid.uuid4().hex[:8]}"
    reviewer_two = f"reviewer-two-{uuid.uuid4().hex[:8]}"
    _reviewer(reviewer_one)
    _reviewer(reviewer_two)
    corpus = _frozen_corpus(tmp_path)
    control = _run(tmp_path, corpus, "control", 0.8)
    candidate = _run(tmp_path, corpus, "candidate", 0.9)

    assignments = []
    for reviewer in (reviewer_one, reviewer_two):
        assignments.append(call_mcp_tool(tmp_path, "create_blind_review_assignment", {
            "control_run_id": control["run_id"],
            "candidate_run_id": candidate["run_id"],
            "reviewer_principal": reviewer,
        }, transport_principal="head-manager"))
    assert all("run_a_id" not in item["blind_packet"] for item in assignments)
    packet = call_mcp_tool(tmp_path, "get_blind_review_packet", {
        "assignment_id": assignments[0]["assignment_id"],
    }, transport_principal=reviewer_one)
    assert packet["blind_packet"]["model_identity_hidden"] is True
    with pytest.raises(PermissionError, match="does not match"):
        call_mcp_tool(tmp_path, "record_blind_human_review", {
            "principal_id": reviewer_two,
            "assignment_id": assignments[0]["assignment_id"],
            "preference": "tie",
            "ratings": {"quality": 4},
            "rationale": "independent tie",
        }, transport_principal=reviewer_one)
    first_review = call_mcp_tool(tmp_path, "record_blind_human_review", {
        "assignment_id": assignments[0]["assignment_id"],
        "preference": "tie",
        "ratings": {"quality": 4},
        "rationale": "Both satisfy the frozen rubric.",
    }, transport_principal=reviewer_one)
    assert first_review["artifact"]["reviewer_principal"] == reviewer_one

    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADINGCODEX_API_KEY", "evaluation-key")
    monkeypatch.setenv("TRADINGCODEX_API_PRINCIPAL", reviewer_two)
    client = Client(REMOTE_ADDR="127.0.0.1", HTTP_X_TRADINGCODEX_KEY="evaluation-key")
    packet_response = client.get(f"/api/evaluations/blind-review-assignments/{assignments[1]['assignment_id']}")
    assert packet_response.status_code == 200, packet_response.content
    review_response = client.post(
        "/api/evaluations/blind-reviews",
        data=json.dumps({
            "assignment_id": assignments[1]["assignment_id"],
            "preference": "tie",
            "ratings": {"quality": 4},
            "rationale": "Independent second review.",
            "reviewer": reviewer_one,
        }),
        content_type="application/json",
    )
    assert review_response.status_code == 200, review_response.content
    assert review_response.json()["artifact"]["reviewer_principal"] == reviewer_two

    comparison = call_mcp_tool(tmp_path, "compare_evaluation_runs", {
        "control_run_id": control["run_id"],
        "candidate_run_id": candidate["run_id"],
    }, transport_principal="head-manager")
    assert comparison["artifact"]["decision"] == "hold"
    assert comparison["artifact"]["pair_provenance"]["verified"] is False
    assert any(
        "not verified by a trusted evaluation runner" in reason
        for reason in comparison["artifact"]["reasons"]
    )
    assert set(comparison["artifact"]["blind_reviewer_principals"]) == {reviewer_one, reviewer_two}


def test_evaluation_cli_requires_transport_identity_and_rejects_payload_spoof(monkeypatch, tmp_path: Path, capsys) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({"corpus_id": "test"}), encoding="utf-8")
    with pytest.raises(ValueError, match="--principal is required"):
        evaluation_command(tmp_path, ["run", str(payload_path)])

    payload_path.write_text(json.dumps({"corpus_id": "test", "created_by": "spoofed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="identity comes from --principal"):
        evaluation_command(tmp_path, ["run", str(payload_path), "--principal", "head-manager"])

    captured = {}

    def fake_call(root, tool, payload, *, transport_principal=None):
        captured.update({"root": root, "tool": tool, "payload": payload, "principal": transport_principal})
        return {"status": "ok"}

    monkeypatch.setattr("tradingcodex_cli.commands.evaluation.call_mcp_tool", fake_call)
    payload_path.write_text(json.dumps({"corpus_id": "test"}), encoding="utf-8")
    evaluation_command(tmp_path, ["run", str(payload_path), "--principal", "head-manager"])
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert captured == {
        "root": tmp_path,
        "tool": "record_evaluation_run",
        "payload": {"corpus_id": "test"},
        "principal": "head-manager",
    }
