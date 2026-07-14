from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingcodex_service.application.common import stable_hash
from tradingcodex_service.application.evaluation_lab import (
    CORE_EVALUATION_PROFILE_ID,
    HARD_FAILURE_CHECKS,
    create_evaluation_corpus,
)
from tradingcodex_service.application.runtime import ensure_workspace_manifest


@pytest.fixture(autouse=True)
def attached_workspace(tmp_path: Path) -> None:
    ensure_workspace_manifest(tmp_path)


def _replay_manifest(root: Path) -> None:
    manifest = {
        "schema_version": 1,
        "artifact_type": "replay_manifest",
        "manifest_id": "profile-replay",
        "knowledge_cutoff": "2026-01-01T00:00:00Z",
    }
    manifest["manifest_hash"] = stable_hash(manifest)
    path = root / "trading/research/replay-manifests/profile-replay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_evaluation_engine_accepts_a_corpus_defined_non_quant_profile(tmp_path: Path) -> None:
    _replay_manifest(tmp_path)
    hard_checks = {check: True for check in HARD_FAILURE_CHECKS.values()}
    tags = ["fundamental_evidence", "event_resolution"]
    cases = [
        {
            "case_id": f"case-{tag}",
            "tags": [tag],
            "replay_manifest_id": "profile-replay",
            "prompt": f"Evaluate {tag} without a quantitative signal contract.",
            "expected_checks": {**hard_checks, "answer_supported": True},
            "blind_review_rubric": {"quality": "Prefer evidence-bound reasoning."},
            "forbidden_actions": ["portfolio_mutation"],
        }
        for tag in tags
    ]

    artifact = create_evaluation_corpus(
        tmp_path,
        {
            "corpus_id": "fundamental-events",
            "created_by": "head-manager",
            "evaluation_profile": "fundamental_events_v1",
            "required_case_tags": tags,
            "metric_dimensions": ["qualitative_analysis"],
            "cases": cases,
            "promotion_criteria": [
                {
                    "dimension": "qualitative_analysis",
                    "metric": "quality",
                    "direction": "higher_is_better",
                    "max_regression": 0,
                }
            ],
        },
    )["artifact"]

    assert artifact["evaluation_profile"] == {
        "id": "fundamental_events_v1",
        "source": "corpus_defined",
        "required_case_tags": sorted(tags),
        "metric_dimensions": ["qualitative_analysis"],
    }
    assert CORE_EVALUATION_PROFILE_ID == "core_investment_v1"
