from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tradingcodex_cli.codex_trace_audit import MAX_CUSTOM_OUTPUT_CHARS, _json_text
from tradingcodex_service.application import artifact_bindings
from tradingcodex_service.application.analysis_runs import begin_analysis_run
from tradingcodex_service.application.data_acquisition import (
    DATA_ACQUISITION_RECEIPT_ROOT,
    record_external_data_result,
)
from tradingcodex_service.application.datasets import (
    DATASET_MANIFEST_ROOT,
    get_dataset_manifest,
)
from tradingcodex_service.application.research import (
    RESEARCH_ARTIFACT_CARD_MAX_SERIALIZED_CHARS,
    RESEARCH_ARTIFACT_MARKDOWN_WINDOW_MAX_CHARS,
    RESEARCH_ARTIFACT_REVIEW_MAX_SERIALIZED_CHARS,
    get_research_artifact,
    list_research_artifacts,
    project_research_artifact,
)
from tradingcodex_service.application.research_objects import content_hash
from tradingcodex_service.application.runtime import ensure_workspace_manifest
from tradingcodex_service.api import ResearchArtifactRequest
from tradingcodex_service.mcp_runtime import (
    RESEARCH_ARTIFACT_LIST_MAX_SERIALIZED_CHARS,
    TOOL_REGISTRY,
    call_mcp_tool,
    handle_mcp_rpc,
    validate_input_schema,
)


RUN_ID = "analysis-research-artifact-detail-levels"


def _artifact_args(
    artifact_id: str,
    *,
    artifact_type: str = "research_memo",
    inputs: list[str] | None = None,
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "universe": "public_equity",
        "workflow_type": "detail_level_test",
        "title": artifact_id,
        "markdown": f"# {artifact_id}\n\n[factual] Verified fixture evidence.\n",
        "source_as_of": "2026-07-12",
        "knowledge_cutoff": "2026-07-12T00:00:00Z",
        "evidence_lane": "live_forward",
        "readiness_label": "accepted",
        "context_summary": "Compact downstream context.",
        "reader_summary": "Plain-language fixture summary.",
        "handoff_state": "accepted",
        "confidence": "high",
        "missing_evidence": [],
        "next_recipient": "head-manager",
        "next_action": "Review the authenticated evidence.",
        "blocked_actions": ["order", "execution"],
        "source_snapshot_ids": [],
        "workflow_run_id": RUN_ID,
        "input_artifact_ids": inputs or [],
    }


def _large_card_artifact_args(artifact_id: str) -> dict[str, object]:
    payload = _artifact_args(artifact_id, artifact_type="risk_assessment")
    payload.update(
        {
            "workflow_type": "workflow-" + ("w" * 2_000),
            "symbol": "s" * 2_000,
            "title": "title " * 1_000,
            "context_summary": "context " * 1_000,
            "reader_summary": "reader " * 1_000,
            "confidence": "confidence " * 1_000,
            "missing_evidence": [
                f"missing-{item}-" + ("e" * 500) for item in range(12)
            ],
            "next_recipient": "head-manager " * 1_000,
            "next_action": "review " * 1_000,
            "blocked_actions": ["blocked-" + ("b" * 500)] * 12,
        }
    )
    return payload


def _attached_workspace(root: Path) -> None:
    ensure_workspace_manifest(root)
    begin_analysis_run(
        root,
        "Exercise bounded research artifact response projections.",
        run_id=RUN_ID,
        apply_investor_context=False,
    )


def _store_source_and_synthesis(root: Path) -> None:
    call_mcp_tool(
        root,
        "create_research_artifact",
        _artifact_args("projection-source"),
        transport_principal="fundamental-analyst",
    )
    call_mcp_tool(
        root,
        "create_research_artifact",
        _artifact_args(
            "projection-synthesis",
            artifact_type="synthesis_report",
            inputs=["projection-source"],
        ),
        transport_principal="head-manager",
    )


def _record_external_lineage(
    root: Path,
    *,
    run_id: str = RUN_ID,
) -> dict[str, Any]:
    return record_external_data_result(
        root,
        {
            "data_need": {
                "run_id": run_id,
                "data_kind": "equity_price",
                "asset_type": "equity",
                "identifiers": ["AAPL"],
                "fields": ["timestamp", "symbol", "close"],
                "period_start": "2026-07-10T00:00:00Z",
                "period_end": "2026-07-11T00:00:00Z",
                "as_of": "2026-07-11T00:00:00Z",
                "frequency": "1d",
                "adjustment_policy": "unadjusted",
                "minimum_evidence_grade": "screen-grade",
                "owner_role": "fundamental-analyst",
                "source_policy": "best_available",
            },
            "source_tier": "user_capability",
            "transport": "mcp__market_data",
            "requested_provider": "fixture-provider",
            "returned_provider": "fixture-provider",
            "upstream_provider": "fixture-provider",
            "tool_name": "mcp__market_data__equity_price_historical",
            "route": "/equity/price/historical",
            "returned_adjustment_policy": "unadjusted",
            "result_status": "complete_valid",
            "evidence_grade": "screen-grade",
            "provider_query": {"provider": "fixture-provider", "symbol": "AAPL"},
            "rows": [
                {
                    "timestamp": "2026-07-11T00:00:00Z",
                    "symbol": "AAPL",
                    "close": 212.5,
                }
            ],
            "columns": [
                {"name": "timestamp", "type": "timestamp", "nullable": False},
                {"name": "symbol", "type": "string", "nullable": False},
                {
                    "name": "close",
                    "type": "float64",
                    "nullable": False,
                    "unit": "price",
                    "currency": "USD",
                },
            ],
            "symbols": ["AAPL"],
            "principal_id": "fundamental-analyst",
        },
    )


def _artifact_args_with_external_lineage(
    artifact_id: str,
    lineage: dict[str, Any],
) -> dict[str, object]:
    payload = _artifact_args(artifact_id)
    payload.update(
        {
            "knowledge_cutoff": lineage["receipt"]["recorded_at"],
            "source_snapshot_ids": [lineage["snapshot_id"]],
            "dataset_ids": [lineage["dataset_id"]],
            "data_acquisition_receipt_ids": [lineage["receipt_id"]],
        }
    )
    return payload


def test_authenticated_write_returns_exact_artifact_receipt_fields(
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)

    stored = call_mcp_tool(
        tmp_path,
        "create_research_artifact",
        _artifact_args("receipt-source"),
        transport_principal="fundamental-analyst",
    )

    assert stored["artifact_id"] == "receipt-source"
    assert stored["path"] == stored["export_path"]
    assert stored["path"] == "trading/reports/fundamental/receipt-source.md"
    assert stored["handoff_state"] == "accepted"
    legacy_shape = get_research_artifact(
        tmp_path,
        {"artifact_id": "receipt-source", "include_markdown": False},
    )
    verification = artifact_bindings.verify_authenticated_artifact_binding(
        tmp_path,
        legacy_shape,
    )
    receipt = json.loads(
        (tmp_path / verification["path"]).read_text(encoding="utf-8")
    )
    assert receipt["schema_version"] == 1
    assert "dataset_ids" not in receipt
    assert "data_acquisition_receipt_ids" not in receipt


def test_research_artifact_detail_levels_preserve_full_and_bound_review(
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    _store_source_and_synthesis(tmp_path)

    default_full = get_research_artifact(
        tmp_path,
        {"artifact_id": "projection-synthesis", "include_markdown": False},
    )
    explicit_full = get_research_artifact(
        tmp_path,
        {
            "artifact_id": "projection-synthesis",
            "detail_level": "full",
            "include_markdown": False,
        },
    )
    assert explicit_full == default_full
    assert "metadata" in explicit_full
    assert "workspace_context" in explicit_full
    assert explicit_full["source_snapshot_ids"] == []
    assert explicit_full["dataset_ids"] == []
    assert explicit_full["dataset_manifest_hashes"] == {}
    assert explicit_full["data_acquisition_receipt_ids"] == []
    assert explicit_full["data_acquisition_receipt_hashes"] == {}

    review = get_research_artifact(
        tmp_path,
        {
            "artifact_id": "projection-synthesis",
            "detail_level": "review",
            "include_markdown": True,
        },
    )
    assert review["artifact_id"] == "projection-synthesis"
    assert review["workflow_run_id"] == RUN_ID
    assert review["input_artifact_ids"] == ["projection-source"]
    assert review["input_artifact_hashes"]["projection-source"] == default_full[
        "input_artifact_hashes"
    ]["projection-source"]
    assert "Verified fixture evidence." in review["markdown"]
    assert "metadata" not in review
    assert "workspace_context" not in review
    assert "export_path" not in review
    assert "source_snapshot_ids" not in review
    assert "dataset_ids" not in review
    assert "data_acquisition_receipt_ids" not in review
    assert "calculation_run_ids" not in review
    assert len(json.dumps(review, ensure_ascii=False, separators=(",", ":"))) <= (
        RESEARCH_ARTIFACT_REVIEW_MAX_SERIALIZED_CHARS
    )

    review_without_markdown = get_research_artifact(
        tmp_path,
        {
            "artifact_id": "projection-synthesis",
            "detail_level": "review",
            "include_markdown": False,
        },
    )
    assert "markdown" not in review_without_markdown

    card = get_research_artifact(
        tmp_path,
        {
            "artifact_id": "projection-synthesis",
            "detail_level": "card",
            "include_markdown": True,
        },
    )
    assert card["artifact_id"] == "projection-synthesis"
    assert card["context_summary"] == "Compact downstream context."
    assert card["next_recipient"] == "head-manager"
    assert "markdown" not in card
    assert "input_artifact_ids" not in card
    assert "input_artifact_hashes" not in card
    assert "anti_overfit_checks" not in card
    assert "workspace_context" not in card

    with pytest.raises(ValueError, match="detail_level must be one of"):
        get_research_artifact(
            tmp_path,
            {"artifact_id": "projection-synthesis", "detail_level": "summary"},
        )


def test_research_artifact_binds_authenticated_dataset_and_acquisition_lineage(
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    lineage = _record_external_lineage(tmp_path)
    call_mcp_tool(
        tmp_path,
        "create_research_artifact",
        _artifact_args_with_external_lineage("external-lineage", lineage),
        transport_principal="fundamental-analyst",
    )

    manifest = get_dataset_manifest(
        tmp_path,
        {"dataset_id": lineage["dataset_id"]},
    )["dataset"]
    full = get_research_artifact(
        tmp_path,
        {"artifact_id": "external-lineage", "include_markdown": False},
    )
    assert full["dataset_ids"] == [lineage["dataset_id"]]
    assert full["dataset_manifest_hashes"] == {
        lineage["dataset_id"]: manifest["manifest_hash"]
    }
    assert full["data_acquisition_receipt_ids"] == [lineage["receipt_id"]]
    assert full["data_acquisition_receipt_hashes"] == {
        lineage["receipt_id"]: lineage["receipt"]["receipt_hash"]
    }
    verification = artifact_bindings.verify_authenticated_artifact_binding(
        tmp_path,
        full,
    )
    assert verification["status"] == "verified"
    artifact_receipt = json.loads(
        (tmp_path / verification["path"]).read_text(encoding="utf-8")
    )
    assert artifact_receipt["schema_version"] == 3
    assert artifact_receipt["dataset_ids"] == full["dataset_ids"]
    assert artifact_receipt["dataset_manifest_hashes"] == full[
        "dataset_manifest_hashes"
    ]
    assert artifact_receipt["data_acquisition_receipt_ids"] == full[
        "data_acquisition_receipt_ids"
    ]
    assert artifact_receipt["data_acquisition_receipt_hashes"] == full[
        "data_acquisition_receipt_hashes"
    ]

    review = get_research_artifact(
        tmp_path,
        {
            "artifact_id": "external-lineage",
            "detail_level": "review",
            "include_markdown": False,
        },
    )
    for field in (
        "dataset_ids",
        "dataset_manifest_hashes",
        "data_acquisition_receipt_ids",
        "data_acquisition_receipt_hashes",
    ):
        assert review[field] == full[field]

    card = get_research_artifact(
        tmp_path,
        {"artifact_id": "external-lineage", "detail_level": "card"},
    )
    assert "dataset_ids" not in card
    assert "dataset_manifest_hashes" not in card
    assert "data_acquisition_receipt_ids" not in card
    assert "data_acquisition_receipt_hashes" not in card

    call_mcp_tool(
        tmp_path,
        "append_research_artifact_version",
        {
            "artifact_id": "external-lineage",
            "markdown": "# External lineage\n\n[factual] Verified updated evidence.\n",
        },
        transport_principal="fundamental-analyst",
    )
    appended = get_research_artifact(
        tmp_path,
        {"artifact_id": "external-lineage", "include_markdown": False},
    )
    assert appended["version"] == 2
    for field in (
        "dataset_ids",
        "dataset_manifest_hashes",
        "data_acquisition_receipt_ids",
        "data_acquisition_receipt_hashes",
    ):
        assert appended[field] == full[field]


@pytest.mark.parametrize(
    ("omitted_field", "message"),
    [
        ("dataset_ids", "must be included in artifact dataset_ids"),
        ("source_snapshot_ids", "must be included in artifact source_snapshot_ids"),
    ],
)
def test_acquisition_receipt_requires_explicit_dataset_and_snapshot_bindings(
    tmp_path: Path,
    omitted_field: str,
    message: str,
) -> None:
    _attached_workspace(tmp_path)
    lineage = _record_external_lineage(tmp_path)
    payload = _artifact_args_with_external_lineage(
        f"missing-{omitted_field}",
        lineage,
    )
    payload[omitted_field] = []

    with pytest.raises(ValueError, match=message):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            payload,
            transport_principal="fundamental-analyst",
        )


def test_acquisition_receipt_must_belong_to_artifact_workflow_run(
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    other_run_id = "analysis-other-workflow"
    begin_analysis_run(
        tmp_path,
        "Create authenticated external lineage for a different workflow.",
        run_id=other_run_id,
        apply_investor_context=False,
    )
    lineage = _record_external_lineage(tmp_path, run_id=other_run_id)

    with pytest.raises(ValueError, match="belongs to workflow run analysis-other-workflow"):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            _artifact_args_with_external_lineage("wrong-receipt-run", lineage),
            transport_principal="fundamental-analyst",
        )


@pytest.mark.parametrize(
    ("field", "lineage_id", "message"),
    [
        (
            "dataset_ids",
            "dataset-" + ("f" * 24),
            "dataset manifest .* not found",
        ),
        (
            "data_acquisition_receipt_ids",
            "data-acquisition-" + ("f" * 24),
            "data acquisition receipt .* not found",
        ),
    ],
)
def test_artifact_rejects_missing_data_lineage_objects(
    tmp_path: Path,
    field: str,
    lineage_id: str,
    message: str,
) -> None:
    _attached_workspace(tmp_path)
    payload = _artifact_args(f"missing-{field}")
    payload[field] = [lineage_id]

    with pytest.raises(ValueError, match=message):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            payload,
            transport_principal="fundamental-analyst",
        )


def test_artifact_cutoff_covers_dataset_and_receipt_lineage(tmp_path: Path) -> None:
    _attached_workspace(tmp_path)
    lineage = _record_external_lineage(tmp_path)
    manifest = get_dataset_manifest(
        tmp_path,
        {"dataset_id": lineage["dataset_id"]},
    )["dataset"]

    dataset_payload = _artifact_args("dataset-cutoff-too-early")
    dataset_payload.update(
        {
            "dataset_ids": [lineage["dataset_id"]],
            "knowledge_cutoff": "2026-07-11T00:00:00Z",
        }
    )
    with pytest.raises(ValueError, match="dataset .* knowledge_cutoff .* is after"):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            dataset_payload,
            transport_principal="fundamental-analyst",
        )

    receipt_payload = _artifact_args_with_external_lineage(
        "receipt-cutoff-too-early",
        lineage,
    )
    receipt_payload["knowledge_cutoff"] = manifest["knowledge_cutoff"]
    with pytest.raises(ValueError, match="recorded_at .* is after artifact knowledge_cutoff"):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            receipt_payload,
            transport_principal="fundamental-analyst",
        )


@pytest.mark.parametrize(
    ("derived_field", "message"),
    [
        ("dataset_manifest_hashes", "service-derived from dataset_ids"),
        (
            "data_acquisition_receipt_hashes",
            "service-derived from data_acquisition_receipt_ids",
        ),
    ],
)
def test_artifact_rejects_caller_forged_data_lineage_hashes(
    tmp_path: Path,
    derived_field: str,
    message: str,
) -> None:
    _attached_workspace(tmp_path)
    lineage = _record_external_lineage(tmp_path)
    payload = _artifact_args_with_external_lineage(
        f"forged-{derived_field}",
        lineage,
    )
    lineage_id = (
        lineage["dataset_id"]
        if derived_field == "dataset_manifest_hashes"
        else lineage["receipt_id"]
    )
    payload[derived_field] = {lineage_id: "0" * 64}

    with pytest.raises(ValueError, match=message):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            payload,
            transport_principal="fundamental-analyst",
        )


def test_artifact_read_rejects_dataset_and_receipt_tampering(tmp_path: Path) -> None:
    _attached_workspace(tmp_path)
    lineage = _record_external_lineage(tmp_path)
    call_mcp_tool(
        tmp_path,
        "create_research_artifact",
        _artifact_args_with_external_lineage("tamper-lineage", lineage),
        transport_principal="fundamental-analyst",
    )
    loaded_artifact = get_research_artifact(
        tmp_path,
        {"artifact_id": "tamper-lineage", "include_markdown": False},
    )

    manifest_path = (
        tmp_path / DATASET_MANIFEST_ROOT / f"{lineage['dataset_id']}.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_by"] = "tampered-principal"
    manifest["manifest_hash"] = content_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dataset manifest hashes do not match"):
        get_research_artifact(
            tmp_path,
            {"artifact_id": "tamper-lineage", "include_markdown": False},
        )
    with pytest.raises(ValueError, match="manifest hashes must match current Datasets"):
        artifact_bindings.verify_authenticated_artifact_binding(
            tmp_path,
            loaded_artifact,
        )

    manifest["created_by"] = "fundamental-analyst"
    manifest["manifest_hash"] = content_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path = (
        tmp_path
        / DATA_ACQUISITION_RECEIPT_ROOT
        / f"{lineage['receipt_id']}.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["receipt_hash"] = "0" * 64
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="receipt hash mismatch"):
        get_research_artifact(
            tmp_path,
            {"artifact_id": "tamper-lineage", "include_markdown": False},
        )
    with pytest.raises(ValueError, match="receipt hash mismatch"):
        artifact_bindings.verify_authenticated_artifact_binding(
            tmp_path,
            loaded_artifact,
        )


def test_mcp_authenticates_full_artifact_before_card_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    _store_source_and_synthesis(tmp_path)
    original_verify = artifact_bindings.verify_authenticated_artifact_binding
    verified_artifact: dict[str, Any] = {}

    def capture_full_artifact(
        workspace_root: Path | str,
        artifact: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if artifact.get("artifact_id") == "projection-synthesis":
            verified_artifact.update(artifact)
        return original_verify(workspace_root, artifact, **kwargs)

    monkeypatch.setattr(
        artifact_bindings,
        "verify_authenticated_artifact_binding",
        capture_full_artifact,
    )

    card = call_mcp_tool(
        tmp_path,
        "get_research_artifact",
        {
            "artifact_id": "projection-synthesis",
            "detail_level": "card",
            "include_markdown": True,
        },
        transport_principal="head-manager",
    )

    assert verified_artifact["input_artifact_ids"] == ["projection-source"]
    assert verified_artifact["input_artifact_hashes"]
    assert "metadata" in verified_artifact
    assert "workspace_context" in verified_artifact
    assert "input_artifact_ids" not in card
    assert "metadata" not in card
    assert "workspace_context" not in card
    assert "markdown" not in card


def test_mcp_lists_authenticate_full_artifacts_before_card_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    _store_source_and_synthesis(tmp_path)
    original_verify = artifact_bindings.verify_authenticated_artifact_binding
    verified_artifact: dict[str, Any] = {}

    def capture_full_artifact(
        workspace_root: Path | str,
        artifact: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if artifact.get("artifact_id") == "projection-synthesis":
            verified_artifact.update(artifact)
        return original_verify(workspace_root, artifact, **kwargs)

    monkeypatch.setattr(
        artifact_bindings,
        "verify_authenticated_artifact_binding",
        capture_full_artifact,
    )

    for tool_name in ("list_research_artifacts", "list_workflow_artifacts"):
        verified_artifact.clear()
        response = call_mcp_tool(
            tmp_path,
            tool_name,
            {
                "workflow_run_id": RUN_ID,
                "producer_role": "head-manager",
                "handoff_state": "accepted",
                "detail_level": "card",
                "limit": 1,
            },
            transport_principal="head-manager",
        )
        cards = (
            response["research_artifacts"]
            if tool_name == "list_workflow_artifacts"
            else response["artifacts"]
        )

        assert verified_artifact["input_artifact_ids"] == ["projection-source"]
        assert verified_artifact["input_artifact_hashes"]
        assert "metadata" in verified_artifact
        assert "workspace_context" in verified_artifact
        assert response["run_bound_authentication"] == {
            "status": "verified",
            "verified_artifact_count": 1,
        }
        assert [card["artifact_id"] for card in cards] == [
            "projection-synthesis"
        ]
        assert "input_artifact_ids" not in cards[0]
        assert "metadata" not in cards[0]
        assert "workspace_context" not in cards[0]
        assert "markdown" not in cards[0]


def test_review_markdown_windows_are_bounded_and_resumable(tmp_path: Path) -> None:
    _attached_workspace(tmp_path)
    args = _artifact_args("projection-large")
    args["markdown"] = "# Large\n\n" + "0123456789abcdef\n" * 2_000
    args["handoff_state"] = "waiting"
    args["readiness_label"] = "waiting_for_targeted_review"
    call_mcp_tool(
        tmp_path,
        "create_research_artifact",
        args,
        transport_principal="fundamental-analyst",
    )
    full = get_research_artifact(
        tmp_path,
        {"artifact_id": "projection-large", "detail_level": "full"},
    )["markdown"]

    chunks: list[str] = []
    next_start = 0
    while True:
        review = call_mcp_tool(
            tmp_path,
            "get_research_artifact",
            {
                "artifact_id": "projection-large",
                "detail_level": "review",
                "markdown_start": next_start,
                "markdown_max_chars": 4_000,
            },
            transport_principal="head-manager",
        )
        assert len(review["markdown"]) <= 4_000
        chunks.append(review["markdown"])
        window = review["markdown_window"]
        assert window["start"] == next_start
        if not window["has_more"]:
            assert "next_start" not in window
            break
        assert window["next_start"] > next_start
        next_start = window["next_start"]
    assert "".join(chunks) == full

    with pytest.raises(ValueError, match="exceeds the Markdown body length"):
        get_research_artifact(
            tmp_path,
            {
                "artifact_id": "projection-large",
                "detail_level": "review",
                "markdown_start": len(full) + 1,
                "markdown_max_chars": 100,
            },
        )
    with pytest.raises(ValueError, match="does not accept Markdown window"):
        get_research_artifact(
            tmp_path,
            {
                "artifact_id": "projection-large",
                "detail_level": "card",
                "markdown_start": 0,
            },
        )


def test_card_projection_has_a_hard_serialized_bound() -> None:
    artifact = {
        "artifact_id": "bounded-card",
        "content_hash": "a" * 64,
        "version": 7,
        "title": "T" * 50_000,
        "context_summary": "C" * 100_000,
        "reader_summary": "R" * 100_000,
        "missing_evidence": ["M" * 10_000 for _ in range(100)],
        "blocked_actions": ["B" * 10_000 for _ in range(100)],
        "confidence": {f"dimension-{index}": "X" * 10_000 for index in range(100)},
        "markdown": "must never enter the card",
    }
    card = project_research_artifact(artifact, detail_level="card")

    serialized = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
    assert RESEARCH_ARTIFACT_CARD_MAX_SERIALIZED_CHARS == 10_000
    assert len(serialized) > 8_000
    assert len(serialized) <= RESEARCH_ARTIFACT_CARD_MAX_SERIALIZED_CHARS
    assert len(json.dumps(card, indent=2, ensure_ascii=False)) < (
        RESEARCH_ARTIFACT_LIST_MAX_SERIALIZED_CHARS
    )
    assert card["artifact_id"] == artifact["artifact_id"]
    assert card["content_hash"] == artifact["content_hash"]
    assert card["version"] == artifact["version"]
    assert "markdown" not in card
    assert set(card["card_truncated_fields"]) >= {
        "title",
        "context_summary",
        "reader_summary",
        "missing_evidence",
        "blocked_actions",
        "confidence",
    }


def test_review_projection_bounds_the_whole_response_and_remains_resumable() -> None:
    markdown = "0123456789abcdef\n" * 3_000
    input_ids = [f"input-{index}" for index in range(12)]
    artifact = {
        "artifact_id": "bounded-review",
        "content_hash": "a" * 64,
        "version": 3,
        "workflow_run_id": RUN_ID,
        "producer_role": "fundamental-analyst",
        "input_artifact_ids": input_ids,
        "input_artifact_hashes": {
            artifact_id: str(index) * 64
            for index, artifact_id in enumerate(input_ids, start=1)
        },
        "title": "T" * 50_000,
        "context_summary": "C" * 100_000,
        "reader_summary": "R" * 100_000,
        "contrary_evidence": ["X" * 10_000 for _ in range(100)],
        "missing_evidence": ["M" * 10_000 for _ in range(100)],
        "markdown": markdown,
        "metadata": {"unbounded": "must not enter review" * 10_000},
        "workspace_context": {"unbounded": "must not enter review" * 10_000},
    }

    chunks: list[str] = []
    next_start = 0
    while True:
        review = project_research_artifact(
            artifact,
            detail_level="review",
            markdown_start=next_start,
            markdown_max_chars=RESEARCH_ARTIFACT_MARKDOWN_WINDOW_MAX_CHARS,
        )
        serialized = json.dumps(review, ensure_ascii=False, separators=(",", ":"))
        assert len(serialized) <= RESEARCH_ARTIFACT_REVIEW_MAX_SERIALIZED_CHARS
        assert review["artifact_id"] == artifact["artifact_id"]
        assert review["content_hash"] == artifact["content_hash"]
        assert review["input_artifact_ids"] == input_ids
        assert review["input_artifact_hashes"] == artifact["input_artifact_hashes"]
        assert "metadata" not in review
        assert "workspace_context" not in review
        chunks.append(review["markdown"])
        window = review["markdown_window"]
        if not window["has_more"]:
            assert "next_start" not in window
            break
        assert window["next_start"] > next_start
        next_start = window["next_start"]

    assert "".join(chunks) == markdown


def test_research_artifact_list_supports_exact_bounded_receipt_recovery(
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    _store_source_and_synthesis(tmp_path)
    call_mcp_tool(
        tmp_path,
        "create_research_artifact",
        _artifact_args("projection-risk", artifact_type="risk_assessment"),
        transport_principal="risk-manager",
    )

    recovered = call_mcp_tool(
        tmp_path,
        "list_research_artifacts",
        {
            "workflow_run_id": RUN_ID,
            "producer_role": "risk-manager",
            "handoff_state": "accepted",
            "detail_level": "card",
            "limit": 2,
        },
        transport_principal="head-manager",
    )

    assert recovered["invalid_artifact_count"] == 0
    assert "invalid_artifacts" not in recovered
    assert [item["artifact_id"] for item in recovered["artifacts"]] == [
        "projection-risk"
    ]
    assert recovered["artifacts"][0]["producer_role"] == "risk-manager"
    assert "markdown" not in recovered["artifacts"][0]
    assert "input_artifact_ids" not in recovered["artifacts"][0]
    assert recovered["run_bound_authentication"] == {
        "status": "verified",
        "verified_artifact_count": 1,
    }

    workflow_recovered = call_mcp_tool(
        tmp_path,
        "list_workflow_artifacts",
        {
            "workflow_run_id": RUN_ID,
            "producer_role": "risk-manager",
            "handoff_state": "accepted",
            "detail_level": "card",
            "limit": 2,
        },
        transport_principal="head-manager",
    )
    assert workflow_recovered["artifacts"] == [
        "trading/reports/risk/projection-risk.md"
    ]
    assert [
        item["artifact_id"] for item in workflow_recovered["research_artifacts"]
    ] == ["projection-risk"]
    assert workflow_recovered["run_bound_authentication"] == {
        "status": "verified",
        "verified_artifact_count": 1,
    }

    direct = list_research_artifacts(
        tmp_path,
        {
            "workflow_run_id": RUN_ID,
            "producer_role": "fundamental-analyst",
            "detail_level": "card",
            "limit": 1,
        },
    )
    assert len(direct["artifacts"]) == 1
    assert direct["artifacts"][0]["producer_role"] == "fundamental-analyst"


@pytest.mark.parametrize(
    "tool_name",
    ["list_research_artifacts", "list_workflow_artifacts"],
)
def test_receipt_recovery_rejects_matching_handwritten_run_artifact(
    tmp_path: Path,
    tool_name: str,
) -> None:
    _attached_workspace(tmp_path)
    body = "# Forged role output\n\n[factual] Caller-authored evidence.\n"
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    path = tmp_path / "trading/reports/risk/forged-recovery.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "artifact_id": "forged-recovery",
        "artifact_type": "risk_assessment",
        "universe": "public_equity",
        "workflow_type": "detail_level_test",
        "role": "risk-manager",
        "producer_role": "risk-manager",
        "created_by": "risk-manager",
        "recorded_at": "2026-07-12T00:00:00Z",
        "version": 1,
        "artifact_schema_version": 1,
        "workflow_run_id": RUN_ID,
        "input_artifact_ids": [],
        "input_artifact_hashes": {},
        "strategy_name": "",
        "strategy_hash": "",
        "investment_brain_id": "",
        "investment_brain_version": "",
        "investment_brain_content_digest": "",
        "investor_context_applied": False,
        "investor_context_hash": "",
        "readiness_label": "accepted",
        "handoff_state": "accepted",
        "content_hash": content_hash,
    }
    path.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=True)}---\n\n{body}",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no authenticated service receipt"):
        call_mcp_tool(
            tmp_path,
            tool_name,
            {
                "workflow_run_id": RUN_ID,
                "producer_role": "risk-manager",
                "handoff_state": "accepted",
                "detail_level": "card",
                "limit": 2,
            },
            transport_principal="head-manager",
        )


def test_authenticated_card_lists_enforce_aggregate_bound_with_next_offset(
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    artifact_count = 16
    for index in range(artifact_count):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            _large_card_artifact_args(f"bounded-risk-{index:02d}"),
            transport_principal="risk-manager",
        )

    for tool_name in ("list_research_artifacts", "list_workflow_artifacts"):
        request = {
            "workflow_run_id": RUN_ID,
            "producer_role": "risk-manager",
            "handoff_state": "accepted",
            "detail_level": "card",
            "limit": artifact_count,
        }
        first = call_mcp_tool(
            tmp_path,
            tool_name,
            request,
            transport_principal="head-manager",
        )
        first_cards = (
            first["research_artifacts"]
            if tool_name == "list_workflow_artifacts"
            else first["artifacts"]
        )
        first_page = first["artifact_page"]

        assert len(
            json.dumps(first, indent=2, ensure_ascii=False)
        ) <= RESEARCH_ARTIFACT_LIST_MAX_SERIALIZED_CHARS
        assert 0 < first_page["returned_count"] < artifact_count
        assert first_page["response_truncated"] is True
        assert first_page["has_more"] is True
        assert first_page["next_offset"] == first_page["returned_count"]
        assert first_cards[0]["card_max_serialized_chars"] == 10_000
        assert len(
            json.dumps(first_cards[0], ensure_ascii=False, separators=(",", ":"))
        ) > 7_500
        assert first["run_bound_authentication"]["verified_artifact_count"] == len(
            first_cards
        )

        rpc = handle_mcp_rpc(
            tmp_path,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": request},
            },
            transport_principal="head-manager",
        )
        assert rpc is not None
        wire_text = rpc["result"]["content"][0]["text"]
        assert len(wire_text) <= RESEARCH_ARTIFACT_LIST_MAX_SERIALIZED_CHARS
        assert json.loads(wire_text)["artifact_page"] == first_page
        call_tool_result = {
            "content": [{"type": "text", "text": wire_text}],
            "isError": False,
        }
        observable_exec_output = [
            {
                "type": "input_text",
                "text": "Script completed\nWall time 0.0 seconds\nOutput:\n",
            },
            {
                "type": "input_text",
                "text": json.dumps(call_tool_result, ensure_ascii=False),
            },
        ]
        assert len(_json_text(observable_exec_output)) <= MAX_CUSTOM_OUTPUT_CHARS

        second = call_mcp_tool(
            tmp_path,
            tool_name,
            {**request, "offset": first_page["next_offset"]},
            transport_principal="head-manager",
        )
        second_cards = (
            second["research_artifacts"]
            if tool_name == "list_workflow_artifacts"
            else second["artifacts"]
        )
        assert len(
            json.dumps(second, indent=2, ensure_ascii=False)
        ) <= RESEARCH_ARTIFACT_LIST_MAX_SERIALIZED_CHARS
        assert {card["artifact_id"] for card in first_cards}.isdisjoint(
            card["artifact_id"] for card in second_cards
        )


def test_limit_two_recovery_page_cannot_misstate_a_truncated_match_as_unique(
    tmp_path: Path,
) -> None:
    _attached_workspace(tmp_path)
    for artifact_id in ("nonunique-risk-a", "nonunique-risk-b"):
        call_mcp_tool(
            tmp_path,
            "create_research_artifact",
            _large_card_artifact_args(artifact_id),
            transport_principal="risk-manager",
        )

    for tool_name in ("list_research_artifacts", "list_workflow_artifacts"):
        response = call_mcp_tool(
            tmp_path,
            tool_name,
            {
                "workflow_run_id": RUN_ID,
                "producer_role": "risk-manager",
                "handoff_state": "accepted",
                "detail_level": "card",
                "limit": 2,
            },
            transport_principal="head-manager",
        )

        assert response["artifact_page"] == {
            "offset": 0,
            "requested_limit": 2,
            "returned_count": 1,
            "has_more": True,
            "response_truncated": True,
            "max_serialized_chars": RESEARCH_ARTIFACT_LIST_MAX_SERIALIZED_CHARS,
            "next_offset": 1,
        }
        assert response["run_bound_authentication"] == {
            "status": "verified",
            "verified_artifact_count": 1,
        }


def test_research_dataset_and_calculation_mcp_schemas_are_exact() -> None:
    create_artifact_schema = TOOL_REGISTRY["create_research_artifact"].input_schema[
        "properties"
    ]
    for field, pattern in (
        ("dataset_ids", r"^dataset-[0-9a-f]{24}$"),
        (
            "data_acquisition_receipt_ids",
            r"^data-acquisition-[0-9a-f]{24}$",
        ),
    ):
        assert create_artifact_schema[field]["maxItems"] == 50
        assert create_artifact_schema[field]["items"]["pattern"] == pattern
    assert "dataset_manifest_hashes" not in create_artifact_schema
    assert "data_acquisition_receipt_hashes" not in create_artifact_schema
    valid_dataset_id = "dataset-" + ("a" * 24)
    valid_receipt_id = "data-acquisition-" + ("b" * 24)
    validate_input_schema(
        TOOL_REGISTRY["create_research_artifact"],
        {
            "dataset_ids": [valid_dataset_id],
            "data_acquisition_receipt_ids": [valid_receipt_id],
        },
    )

    api_artifact_schema = ResearchArtifactRequest.model_json_schema()["properties"]
    assert api_artifact_schema["dataset_ids"]["maxItems"] == 50
    assert api_artifact_schema["data_acquisition_receipt_ids"]["maxItems"] == 50
    assert "dataset_manifest_hashes" not in api_artifact_schema
    assert "data_acquisition_receipt_hashes" not in api_artifact_schema
    api_request = ResearchArtifactRequest(
        title="Data lineage schema",
        markdown="# Data lineage schema",
        dataset_ids=[valid_dataset_id],
        data_acquisition_receipt_ids=[valid_receipt_id],
    ).model_dump()
    assert api_request["dataset_ids"] == [valid_dataset_id]
    assert api_request["data_acquisition_receipt_ids"] == [valid_receipt_id]

    get_schema = TOOL_REGISTRY["get_research_artifact"].input_schema
    detail_schema = get_schema["properties"]["detail_level"]
    assert detail_schema["enum"] == ["full", "review", "card"]
    assert "forces include_markdown=false" in detail_schema["description"]
    assert get_schema["properties"]["markdown_max_chars"]["maximum"] == (
        RESEARCH_ARTIFACT_MARKDOWN_WINDOW_MAX_CHARS
    )
    with pytest.raises(ValueError, match="must be <="):
        validate_input_schema(
            TOOL_REGISTRY["get_research_artifact"],
            {
                "artifact_id": "artifact",
                "markdown_max_chars": RESEARCH_ARTIFACT_MARKDOWN_WINDOW_MAX_CHARS
                + 1,
            },
        )
    with pytest.raises(ValueError, match="detail_level must be one of"):
        validate_input_schema(
            TOOL_REGISTRY["get_research_artifact"],
            {"artifact_id": "artifact", "detail_level": "summary"},
        )

    for tool_name in ("list_workflow_artifacts", "list_research_artifacts"):
        list_schema = TOOL_REGISTRY[tool_name].input_schema["properties"]
        assert {
            "workflow_run_id",
            "producer_role",
            "handoff_state",
            "detail_level",
            "limit",
        } <= set(list_schema)
        assert list_schema["detail_level"]["enum"] == ["full", "card"]
        assert list_schema["offset"] == {
            "type": "integer",
            "minimum": 0,
            "maximum": 199,
            "description": "Deterministic artifact offset returned as artifact_page.next_offset.",
        }

    columns_schema = TOOL_REGISTRY["record_dataset_snapshot"].input_schema[
        "properties"
    ]["columns"]["items"]["properties"]["type"]
    pattern = columns_schema["pattern"]
    for value in (
        "string",
        "bool",
        "int64",
        "float64",
        "date32",
        "timestamp",
        "decimal128(18,4)",
    ):
        assert re.fullmatch(pattern, value), value
    assert re.fullmatch(pattern, "integer") is None
    assert "Exact Dataset service type grammar" in columns_schema["description"]
    invalid_dataset = {
        "source_filename": "fixture.csv",
        "title": "Fixture",
        "provider": "fixture",
        "knowledge_cutoff": "2026-07-12T00:00:00Z",
        "as_of": "2026-07-12T00:00:00Z",
        "vintage": "2026-07-12",
        "period_start": "2026-07-01",
        "period_end": "2026-07-12",
        "timezone": "UTC",
        "frequency": "daily",
        "universe_membership_policy": "explicit",
        "universe_membership": {},
        "columns": [{"name": "value", "type": "integer"}],
    }
    with pytest.raises(ValueError, match=r"columns\[0\]\.type.*pattern"):
        validate_input_schema(
            TOOL_REGISTRY["record_dataset_snapshot"],
            invalid_dataset,
        )

    materialize_schema = TOOL_REGISTRY["materialize_dataset_slice"].input_schema[
        "properties"
    ]
    assert "exact Dataset type timestamp" in materialize_schema["time_column"][
        "description"
    ]
    for field in ("start", "end"):
        assert materialize_schema[field]["format"] == "date-time"
        description = materialize_schema[field]["description"]
        assert "RFC 3339" in description
        assert "timezone-aware" in description
        assert "explicit UTC offset or Z" in description
    for invalid_timestamp in (
        "2026-07-12",
        "2026-07-12T01:02+00:00",
        "2026-07-12T01:02:03+0000",
        "2026-07-12T01:02:03+00",
    ):
        with pytest.raises(ValueError, match="timezone-aware RFC 3339"):
            validate_input_schema(
                TOOL_REGISTRY["materialize_dataset_slice"],
                {
                    "dataset_id": "dataset-one",
                    "columns": ["timestamp"],
                    "time_column": "timestamp",
                    "start": invalid_timestamp,
                },
            )

    prepare_tool = TOOL_REGISTRY["prepare_calculation"]
    kind_schema = prepare_tool.input_schema["properties"]["inputs"]["items"][
        "properties"
    ]["kind"]
    assert kind_schema["enum"] == [
        "dataset_slice",
        "private_account",
        "private_ledger",
        "private_portfolio",
    ]
    with pytest.raises(ValueError, match=r"inputs\[0\]\.kind must be one of"):
        validate_input_schema(
            prepare_tool,
            {
                "script_name": "calculation.py",
                "workflow_run_id": "analysis-one",
                "calculation_type": "unit_return",
                "calculation_version": "1",
                "knowledge_cutoff": "2026-07-12T00:00:00Z",
                "output_schema": {
                    "metrics": [{"name": "return", "value_type": "number"}]
                },
                "inputs": [
                    {
                        "name": "prices",
                        "filename": "prices.parquet",
                        "kind": "arbitrary_file",
                    }
                ],
            },
        )
    with pytest.raises(ValueError, match="must contain at least 1 items"):
        validate_input_schema(
            prepare_tool,
            {
                "script_name": "calculation.py",
                "workflow_run_id": "analysis-one",
                "calculation_type": "unit_return",
                "calculation_version": "1",
                "knowledge_cutoff": "2026-07-12T00:00:00Z",
                "output_schema": {"metrics": []},
            },
        )
