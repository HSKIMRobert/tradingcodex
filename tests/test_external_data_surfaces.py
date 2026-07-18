from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from django.test import Client

from tradingcodex_service.application import data_acquisition as data_acquisition_module
from tradingcodex_service.application import datasets as datasets_module
from tradingcodex_service.application import data_sources as data_sources_module

from tradingcodex_service.application.analysis_runs import begin_analysis_run
from tradingcodex_service.application.data_acquisition import (
    DATA_ACQUISITION_FAMILY_ROOT,
    DATA_ACQUISITION_RECEIPT_ROOT,
    DATA_ACQUISITION_TRANSACTION_ROOT,
    DataAcquisitionReceipt,
    DataNeed,
    get_data_acquisition_receipt,
    record_external_data_result,
    validate_data_acquisition_receipt,
)
from tradingcodex_service.application.datasets import (
    export_dataset_csv,
    get_dataset_manifest,
    get_dataset_rows,
)
from tradingcodex_service.application.data_sources import get_data_source_status
from tradingcodex_service.application.research import get_source_snapshot
from tradingcodex_service.application.research_object_catalog import search_research_objects
from tradingcodex_service.application.runtime import (
    ensure_runtime_database,
    ensure_workspace_manifest,
)
from tradingcodex_service.mcp_runtime import TOOL_REGISTRY, validate_input_schema
from tradingcodex_cli.commands.research import research as research_command


def _data_need(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "run_id": "analysis-external-data-test",
        "data_kind": "equity_price",
        "asset_type": "equity",
        "identifiers": ["000660.KS"],
        "fields": ["timestamp", "symbol", "close"],
        "period_start": "2026-07-14T00:00:00Z",
        "period_end": "2026-07-16T00:00:00Z",
        "as_of": "2026-07-16T00:00:00Z",
        "frequency": "1d",
        "adjustment_policy": "unadjusted",
        "minimum_evidence_grade": "screen-grade",
        "owner_role": "technical-analyst",
        "source_policy": "best_available",
    }
    value.update(overrides)
    return value


def _external_result(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "data_need": _data_need(),
        "source_tier": "user_capability",
        "transport": "mcp__market_data",
        "requested_provider": "yfinance",
        "returned_provider": "yfinance",
        "upstream_provider": "yfinance",
        "tool_name": "mcp__market_data__equity_price_historical",
        "route": "/api/v1/equity/price/historical",
        "returned_adjustment_policy": "unadjusted",
        "result_status": "complete_valid",
        "evidence_grade": "screen-grade",
        "provider_query": {
            "symbol": "000660.KS",
            "provider": "yfinance",
            "start_date": "2026-07-14",
            "end_date": "2026-07-16",
        },
        "source_locator": "provider:yfinance:equity_price_historical",
        "timezone": "UTC",
        "rows": [
            {"timestamp": "2026-07-14T00:00:00Z", "symbol": "000660.KS", "close": 1678000.0},
            {"timestamp": "2026-07-15T00:00:00Z", "symbol": "000660.KS", "close": 1900000.0},
            {"timestamp": "2026-07-16T00:00:00Z", "symbol": "000660.KS", "close": 1842000.0},
        ],
        "columns": [
            {"name": "timestamp", "type": "timestamp", "nullable": False},
            {"name": "symbol", "type": "string", "nullable": False},
            {
                "name": "close",
                "type": "float64",
                "nullable": False,
                "unit": "price",
                "currency": "KRW",
            },
        ],
        "symbols": ["000660.KS"],
        "redistribution": "allowed",
        "principal_id": "technical-analyst",
    }
    value.update(overrides)
    return value


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ensure_workspace_manifest(tmp_path)
    begin_analysis_run(
        tmp_path,
        "Exercise the bounded external-data acquisition contract.",
        run_id="analysis-external-data-test",
    )
    return tmp_path


def test_external_result_is_promoted_to_snapshot_dataset_and_receipt(workspace: Path) -> None:
    recorded = record_external_data_result(workspace, _external_result())

    assert recorded["status"] == "recorded"
    assert recorded["row_count"] == 3
    assert recorded["receipt"]["source_tier"] == "user_capability"
    assert recorded["receipt"]["upstream_provider"] == "yfinance"
    assert "provider_query" not in recorded["receipt"]
    assert len(recorded["receipt"]["query_hash"]) == 64
    receipt_path = workspace / DATA_ACQUISITION_RECEIPT_ROOT / f"{recorded['receipt_id']}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert validate_data_acquisition_receipt(
        receipt, expected_receipt_id=recorded["receipt_id"]
    ) is receipt

    source_card = get_source_snapshot(
        workspace,
        {"snapshot_id": recorded["snapshot_id"]},
    )
    assert source_card["payload_included"] is False
    assert "payload" not in source_card["snapshot"]
    source_full = get_source_snapshot(
        workspace,
        {"snapshot_id": recorded["snapshot_id"], "include_payload": True},
    )
    assert source_full["snapshot"]["payload"]["rows"] == _external_result()["rows"]

    manifest = get_dataset_manifest(
        workspace,
        {"dataset_id": recorded["dataset_id"]},
    )["dataset"]
    assert manifest["payload"]["row_count"] == 3
    assert manifest["source_snapshot_ids"] == [recorded["snapshot_id"]]

    catalog = search_research_objects(
        workspace,
        {"query": "000660.KS", "object_type": "data_acquisition_receipt"},
    )
    assert [item["object_id"] for item in catalog["objects"]] == [
        recorded["receipt_id"]
    ]

    repeated = record_external_data_result(workspace, _external_result())
    assert repeated["status"] == "existing"
    assert repeated["receipt_id"] == recorded["receipt_id"]
    assert repeated["snapshot_id"] == recorded["snapshot_id"]
    assert repeated["dataset_id"] == recorded["dataset_id"]
    assert len(list((workspace / "trading/research/source-snapshots").glob("*.json"))) == 1
    assert len(list((workspace / "trading/research/datasets/manifests").glob("*.json"))) == 1


def test_exact_receipt_and_dataset_lookup_is_authenticated_and_sanitized(
    workspace: Path,
) -> None:
    recorded = record_external_data_result(workspace, _external_result())
    by_receipt = get_data_acquisition_receipt(
        workspace,
        {
            "receipt_id": recorded["receipt_id"],
            "principal_id": "fundamental-analyst",
        },
    )
    by_dataset = get_data_acquisition_receipt(
        workspace,
        {
            "dataset_id": recorded["dataset_id"],
            "principal_id": "technical-analyst",
        },
    )
    assert by_receipt == by_dataset
    assert by_receipt["receipt_id"] == recorded["receipt_id"]
    assert by_receipt["dataset"]["dataset_id"] == recorded["dataset_id"]
    assert by_receipt["dataset"]["payload"]["row_count"] == 3
    assert by_receipt["evidence"]["meets_minimum_evidence_grade"] is True
    assert by_receipt["source"]["route"] == "/api/v1/equity/price/historical"
    serialized = json.dumps(by_receipt, sort_keys=True)
    assert "provider_query" not in serialized
    assert '"rows"' not in serialized
    assert "start_date" not in serialized

    with pytest.raises(PermissionError, match="authenticated principal"):
        get_data_acquisition_receipt(
            workspace, {"receipt_id": recorded["receipt_id"]}
        )
    with pytest.raises(ValueError, match="receipt_id or dataset_id"):
        get_data_acquisition_receipt(
            workspace, {"principal_id": "technical-analyst"}
        )


def test_dataset_rows_are_bounded_cursor_addressed_and_filterable(workspace: Path) -> None:
    dataset_id = record_external_data_result(workspace, _external_result())["dataset_id"]
    first = get_dataset_rows(
        workspace,
        {"dataset_id": dataset_id, "columns": ["timestamp", "close"], "limit": 2},
    )
    assert [row["close"] for row in first["rows"]] == [1678000.0, 1900000.0]
    assert first["next_cursor"]
    second = get_dataset_rows(
        workspace,
        {
            "dataset_id": dataset_id,
            "columns": ["timestamp", "close"],
            "cursor": first["next_cursor"],
            "limit": 120,
        },
    )
    assert second["rows"] == [
        {"timestamp": "2026-07-16T00:00:00+00:00", "close": 1842000.0}
    ]
    assert second["next_cursor"] is None
    with pytest.raises(ValueError, match="cursor is invalid"):
        get_dataset_rows(
            workspace,
            {
                "dataset_id": dataset_id,
                "columns": ["close"],
                "cursor": first["next_cursor"],
            },
        )

    filtered = get_dataset_rows(
        workspace,
        {
            "dataset_id": dataset_id,
            "columns": ["symbol", "close"],
            "time_column": "timestamp",
            "start": "2026-07-15T00:00:00Z",
            "end": "2026-07-15T00:00:00Z",
        },
    )
    assert filtered["rows"] == [{"symbol": "000660.KS", "close": 1900000.0}]


def test_dataset_csv_export_requires_explicit_redistribution(workspace: Path) -> None:
    exportable = record_external_data_result(workspace, _external_result())["dataset_id"]
    exported = export_dataset_csv(workspace, {"dataset_id": exportable})
    assert exported["status"] == "exported"
    path = workspace / exported["export_path"]
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert rows[-1]["close"] == "1842000"
    assert export_dataset_csv(workspace, {"dataset_id": exportable})["status"] == "existing"

    path.write_text("user-owned different content\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different content"):
        export_dataset_csv(workspace, {"dataset_id": exportable})
    assert path.read_text(encoding="utf-8") == "user-owned different content\n"

    restricted = record_external_data_result(
        workspace,
        _external_result(
            data_need=_data_need(identifiers=["035720.KS"]),
            title="Restricted copy",
            requested_provider="restricted-provider",
            returned_provider="restricted-provider",
            upstream_provider="restricted-provider",
            redistribution="not_specified",
            provider_query={"symbol": "035720.KS", "provider": "restricted-provider"},
            rows=[
                {
                    "timestamp": "2026-07-16T00:00:00Z",
                    "symbol": "035720.KS",
                    "close": 58000.0,
                }
            ],
            symbols=["035720.KS"],
        ),
    )["dataset_id"]
    with pytest.raises(PermissionError, match="not explicitly allowed"):
        export_dataset_csv(workspace, {"dataset_id": restricted})


def test_external_result_rejects_secret_material_and_oversized_results(workspace: Path) -> None:
    with pytest.raises(ValueError, match="secret-bearing field"):
        record_external_data_result(
            workspace,
            _external_result(provider_query={"api_key": "raw-secret-value"}),
        )
    with pytest.raises(ValueError, match="at most 120"):
        record_external_data_result(
            workspace,
            _external_result(rows=[_external_result()["rows"][0]] * 121),
        )
    assert not (workspace / "trading/research/source-snapshots").exists()


def test_external_result_binds_owner_source_provider_adjustment_and_evidence(
    workspace: Path,
) -> None:
    with pytest.raises(PermissionError, match="does not own"):
        record_external_data_result(
            workspace,
            _external_result(principal_id="fundamental-analyst"),
        )

    strict_need = _data_need(
        source_policy="strict",
        explicit_source="sec-edgar",
    )
    with pytest.raises(ValueError, match="explicit_source"):
        record_external_data_result(
            workspace,
            _external_result(data_need=strict_need),
        )

    with pytest.raises(ValueError, match="provider_query.provider"):
        record_external_data_result(
            workspace,
            _external_result(
                requested_provider="sec-edgar",
                provider_query={"provider": "yfinance", "symbol": "000660.KS"},
            ),
        )
    with pytest.raises(ValueError, match="exact MCP tool FQN"):
        record_external_data_result(
            workspace,
            _external_result(tool_name="equity_price_historical"),
        )
    with pytest.raises(ValueError, match="requested_provider, returned_provider"):
        record_external_data_result(
            workspace,
            _external_result(returned_provider="other-provider"),
        )
    with pytest.raises(ValueError, match="returned_adjustment_policy"):
        record_external_data_result(
            workspace,
            _external_result(returned_adjustment_policy="split-adjusted"),
        )
    with pytest.raises(ValueError, match="below data_need.minimum_evidence_grade"):
        record_external_data_result(
            workspace,
            _external_result(
                data_need=_data_need(minimum_evidence_grade="factual-baseline"),
                evidence_grade="screen-grade",
            ),
        )
    assert not (workspace / DATA_ACQUISITION_FAMILY_ROOT).exists()


def test_external_result_rejects_nonexistent_analysis_run_before_leasing(
    workspace: Path,
) -> None:
    with pytest.raises(ValueError, match="existing authenticated analysis run"):
        record_external_data_result(
            workspace,
            _external_result(
                data_need=_data_need(run_id="analysis-does-not-exist")
            ),
        )
    assert not (workspace / DATA_ACQUISITION_FAMILY_ROOT).exists()


def test_tier_order_rejects_jump_and_second_distinct_user_capability(
    workspace: Path,
) -> None:
    with pytest.raises(ValueError, match="exact unavailable/skipped-tier"):
        record_external_data_result(
            workspace,
            _external_result(
                source_tier="tradingcodex",
                transport="official-http",
                requested_provider="official-exchange",
                returned_provider="official-exchange",
                upstream_provider="official-exchange",
                tool_name="official_exchange_history",
                provider_query={
                    "provider": "official-exchange",
                    "symbol": "000660.KS",
                },
            ),
        )

    first = record_external_data_result(workspace, _external_result())
    assert first["status"] == "recorded"
    with pytest.raises(ValueError, match="second distinct user capability"):
        record_external_data_result(
            workspace,
            _external_result(
                transport="mcp__alternate_market_data",
                requested_provider="alternate-provider",
                returned_provider="alternate-provider",
                upstream_provider="alternate-provider",
                tool_name="mcp__alternate_market_data__equity_history",
                route="/equity/history",
                provider_query={
                    "provider": "alternate-provider",
                    "symbol": "000660.KS",
                },
            ),
        )


def test_partial_residual_fallback_requires_exact_nonoverlapping_gap(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        data_sources_module,
        "validate_openbb_compatibility_receipt_hash",
        lambda root, receipt_hash: {"receipt_hash": receipt_hash},
    )
    first = record_external_data_result(
        workspace,
        _external_result(
            result_status="partial_valid",
            missing_periods=[
                {
                    "start": "2026-07-14T00:00:00Z",
                    "end": "2026-07-15T00:00:00Z",
                }
            ],
            rows=[
                {
                    "timestamp": "2026-07-16T00:00:00Z",
                    "symbol": "000660.KS",
                    "close": 1842000.0,
                }
            ],
        ),
    )
    fallback_base = {
        "source_tier": "openbb",
        "transport": "openbb-mcp",
        "requested_provider": "openbb-yfinance",
        "returned_provider": "openbb-yfinance",
        "upstream_provider": "openbb-yfinance",
        "tool_name": "equity_price_historical",
        "route": "/equity/price/historical",
        "provider_query": {
            "provider": "openbb-yfinance",
            "symbol": "000660.KS",
        },
        "compatibility_receipt_hash": "a" * 64,
        "predecessor_receipt_ids": [first["receipt_id"]],
    }
    with pytest.raises(ValueError, match="overlaps values retained"):
        record_external_data_result(
            workspace,
            _external_result(
                **fallback_base,
                rows=[
                    {
                        "timestamp": "2026-07-16T00:00:00Z",
                        "symbol": "000660.KS",
                        "close": 1842000.0,
                    }
                ],
            ),
        )

    residual = record_external_data_result(
        workspace,
        _external_result(
            **fallback_base,
            rows=[
                {
                    "timestamp": "2026-07-14T00:00:00Z",
                    "symbol": "000660.KS",
                    "close": 1678000.0,
                },
                {
                    "timestamp": "2026-07-15T00:00:00Z",
                    "symbol": "000660.KS",
                    "close": 1900000.0,
                },
            ],
        ),
    )
    assert residual["receipt"]["predecessor_receipt_ids"] == [
        first["receipt_id"]
    ]
    assert residual["receipt"]["source_tier"] == "openbb"


def test_tradingcodex_same_tier_allows_only_predecessor_linked_residual_provider(
    workspace: Path,
) -> None:
    first = record_external_data_result(
        workspace,
        _external_result(
            source_tier="tradingcodex",
            transport="official-http",
            requested_provider="official-source-a",
            returned_provider="official-source-a",
            upstream_provider="official-source-a",
            tool_name="official_source_a_history",
            route="/history",
            provider_query={
                "provider": "official-source-a",
                "symbol": "000660.KS",
            },
            result_status="partial_valid",
            missing_periods=[
                {
                    "start": "2026-07-14T00:00:00Z",
                    "end": "2026-07-15T00:00:00Z",
                }
            ],
            rows=[
                {
                    "timestamp": "2026-07-16T00:00:00Z",
                    "symbol": "000660.KS",
                    "close": 1842000.0,
                }
            ],
            skipped_tier_attestations=[
                {
                    "source_tier": "user_capability",
                    "status": "unavailable",
                    "reason": "No enabled user capability covers the official request.",
                },
                {
                    "source_tier": "openbb",
                    "status": "unavailable",
                    "reason": "The isolated OpenBB runtime has no compatible route.",
                },
            ],
        ),
    )
    second = record_external_data_result(
        workspace,
        _external_result(
            source_tier="tradingcodex",
            transport="official-http",
            requested_provider="official-source-b",
            returned_provider="official-source-b",
            upstream_provider="official-source-b",
            tool_name="official_source_b_history",
            route="/timeseries",
            provider_query={
                "provider": "official-source-b",
                "symbol": "000660.KS",
            },
            predecessor_receipt_ids=[first["receipt_id"]],
            rows=[
                {
                    "timestamp": "2026-07-14T00:00:00Z",
                    "symbol": "000660.KS",
                    "close": 1678000.0,
                },
                {
                    "timestamp": "2026-07-15T00:00:00Z",
                    "symbol": "000660.KS",
                    "close": 1900000.0,
                },
            ],
        ),
    )
    assert second["receipt"]["predecessor_receipt_ids"] == [first["receipt_id"]]
    assert [
        item["source_tier"]
        for item in second["receipt"]["skipped_tier_attestations"]
    ] == ["user_capability", "openbb"]


def test_run_scoped_family_has_one_immutable_role_owner(
    workspace: Path,
) -> None:
    assert DataNeed.from_mapping(_data_need()).family_id == DataNeed.from_mapping(
        _data_need(frequency="daily", identifiers=["000660.ks"])
    ).family_id
    first = record_external_data_result(workspace, _external_result())
    assert first["receipt"]["run_id"] == "analysis-external-data-test"
    assert first["receipt"]["family_id"] == first["receipt"]["data_need"]["family_id"]
    leases = list((workspace / DATA_ACQUISITION_FAMILY_ROOT).glob("*/*.json"))
    assert len(leases) == 1
    assert json.loads(leases[0].read_text(encoding="utf-8"))["owner_role"] == "technical-analyst"

    with pytest.raises(PermissionError, match="already owned by another role"):
        record_external_data_result(
            workspace,
            _external_result(
                data_need=_data_need(owner_role="fundamental-analyst"),
                principal_id="fundamental-analyst",
            ),
        )

    independent = record_external_data_result(
        workspace,
        _external_result(
            data_need=_data_need(identifiers=["005930.KS"]),
            provider_query={"provider": "yfinance", "symbol": "005930.KS"},
            rows=[
                {
                    "timestamp": "2026-07-16T00:00:00Z",
                    "symbol": "005930.KS",
                    "close": 255000.0,
                }
            ],
            symbols=["005930.KS"],
        ),
    )
    assert independent["status"] == "recorded"
    assert independent["receipt"]["family_id"] != first["receipt"]["family_id"]

    mismatched = _data_need(family_id="data-family-" + "0" * 24)
    with pytest.raises(ValueError, match="normalized run-scoped family"):
        DataNeed.from_mapping(mismatched)


def test_correctable_error_allows_one_changed_correction_then_closes(
    workspace: Path,
) -> None:
    failed_args = _external_result(
        result_status="correctable_error",
        fallback_reason="provider rejected the original date argument",
        evidence_grade="unusable",
    )
    failed_args.pop("rows")
    failed_args.pop("columns")
    failed = record_external_data_result(workspace, failed_args)
    assert failed["receipt"]["attempt_number"] == 1
    assert failed["receipt"]["corrects_receipt_id"] == ""

    corrected_args = _external_result(
        provider_query={
            "provider": "yfinance",
            "symbol": "000660.KS",
            "start_date": "2026-07-14",
            "end_date": "2026-07-16",
            "date_format": "iso-8601",
        }
    )
    corrected = record_external_data_result(workspace, corrected_args)
    assert corrected["status"] == "recorded"
    assert corrected["receipt"]["attempt_number"] == 2
    assert corrected["receipt"]["corrects_receipt_id"] == failed["receipt_id"]
    assert corrected["receipt"]["query_hash"] != failed["receipt"]["query_hash"]

    replayed_original = record_external_data_result(workspace, failed_args)
    assert replayed_original["status"] == "existing"
    assert replayed_original["receipt_id"] == corrected["receipt_id"]
    assert replayed_original["receipt"]["result_status"] == "complete_valid"

    third_args = _external_result(
        provider_query={
            "provider": "yfinance",
            "symbol": "000660.KS",
            "start_date": "2026-07-14",
            "end_date": "2026-07-16",
            "date_format": "epoch",
        }
    )
    closed = record_external_data_result(workspace, third_args)
    assert closed["status"] == "existing"
    assert closed["receipt_id"] == corrected["receipt_id"]
    assert len(list((workspace / DATA_ACQUISITION_RECEIPT_ROOT).glob("*.json"))) == 2


def test_openbb_result_requires_and_validates_compatibility_receipt_binding(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated: list[tuple[Path, str]] = []

    def validate_receipt(root: Path, receipt_hash: str) -> dict[str, str]:
        validated.append((Path(root), receipt_hash))
        return {"receipt_hash": receipt_hash}

    monkeypatch.setattr(
        data_sources_module,
        "validate_openbb_compatibility_receipt_hash",
        validate_receipt,
    )
    with pytest.raises(ValueError, match="compatibility_receipt_hash"):
        record_external_data_result(
            workspace,
            _external_result(
                source_tier="openbb",
                transport="openbb-mcp",
                tool_name="equity_price_historical",
            ),
        )

    receipt_hash = "a" * 64
    recorded = record_external_data_result(
        workspace,
        _external_result(
            source_tier="openbb",
            transport="openbb-mcp",
            tool_name="equity_price_historical",
            compatibility_receipt_hash=receipt_hash,
            skipped_tier_attestations=[
                {
                    "source_tier": "user_capability",
                    "status": "unavailable",
                    "reason": "No enabled user capability covers this request.",
                }
            ],
        ),
    )
    assert validated == [(workspace.resolve(), receipt_hash)]
    assert recorded["receipt"]["compatibility_receipt_hash"] == receipt_hash

    with pytest.raises(ValueError, match="skipped_tier.source_tier"):
        record_external_data_result(
            workspace,
            _external_result(
                skipped_tier_attestations=[
                    {
                        "source_tier": "tradingcodex",
                        "status": "skipped",
                        "reason": "A current tier cannot attest that it skipped itself.",
                    }
                ]
            ),
        )


def test_openbb_provider_conflict_can_fall_back_to_official_with_exact_ancestry(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        data_sources_module,
        "validate_openbb_compatibility_receipt_hash",
        lambda _root, receipt_hash: {"receipt_hash": receipt_hash},
    )
    conflict = record_external_data_result(
        workspace,
        _external_result(
            source_tier="openbb",
            transport="openbb-mcp",
            requested_provider="fmp",
            returned_provider="",
            upstream_provider="fmp",
            tool_name="equity_price_historical",
            route="equity.price.historical",
            returned_adjustment_policy="",
            compatibility_receipt_hash="b" * 64,
            result_status="conflict",
            fallback_reason="OpenBB returned a different provider than requested.",
            evidence_grade="unusable",
            provider_query={
                "provider": "fmp",
                "symbol": "000660.KS",
                "start_date": "2026-07-14",
                "end_date": "2026-07-16",
            },
            coverage_note="OpenBB returned a different provider than the exact requested provider.",
            rows=None,
            columns=None,
            skipped_tier_attestations=[
                {
                    "source_tier": "user_capability",
                    "status": "unavailable",
                    "reason": "No relevant callable user capability covered this request.",
                }
            ],
        ),
    )

    official = record_external_data_result(
        workspace,
        _external_result(
            source_tier="tradingcodex",
            transport="tradingcodex-official",
            requested_provider="sec-edgar",
            returned_provider="",
            upstream_provider="sec-edgar",
            tool_name="mcp__tradingcodex__fetch_official_source_data",
            route="sec-edgar",
            returned_adjustment_policy="",
            result_status="terminal_gap",
            fallback_reason="The official adapter has no matching equity-price coverage.",
            evidence_grade="unusable",
            provider_query={"provider": "sec-edgar", "symbol": "000660.KS"},
            rows=None,
            columns=None,
            predecessor_receipt_ids=[conflict["receipt_id"]],
            skipped_tier_attestations=None,
        ),
    )

    assert official["receipt"]["predecessor_receipt_ids"] == [
        conflict["receipt_id"]
    ]
    assert official["receipt"]["skipped_tier_attestations"] == [
        {
            "source_tier": "user_capability",
            "status": "unavailable",
            "reason": "No relevant callable user capability covered this request.",
        }
    ]


def test_data_need_uses_instant_ordering_and_bounded_evidence_vocabulary() -> None:
    with pytest.raises(ValueError, match="period_start must not be after"):
        DataNeed.from_mapping(
            _data_need(
                period_start="2026-07-16T00:00:00.100000Z",
                period_end="2026-07-16T00:00:00Z",
                as_of="2026-07-16T00:00:00Z",
            )
        )
    with pytest.raises(ValueError, match="minimum_evidence_grade"):
        DataNeed.from_mapping(_data_need(minimum_evidence_grade="marketing-grade"))


def test_receipt_validator_rejects_more_than_external_row_bound() -> None:
    data_need = DataNeed.from_mapping(_data_need())
    attempt_key = data_acquisition_module._data_attempt_key(
        data_need,
        source_tier="user_capability",
        transport="mcp__market_data",
        requested_provider="yfinance",
        tool_name="mcp__market_data__equity_price_historical",
        route="/api/v1/equity/price/historical",
        compatibility_receipt_hash="",
    )
    with pytest.raises(ValueError, match="between 0 and 120"):
        DataAcquisitionReceipt.build(
            data_need=data_need,
            source_tier="user_capability",
            transport="mcp__market_data",
            requested_provider="yfinance",
            returned_provider="yfinance",
            upstream_provider="yfinance",
            tool_name="mcp__market_data__equity_price_historical",
            route="/api/v1/equity/price/historical",
            requested_adjustment_policy="unadjusted",
            returned_adjustment_policy="unadjusted",
            compatibility_receipt_hash="",
            schema_hash="0" * 64,
            query_hash="1" * 64,
            result_hash="2" * 64,
            attempt_key=attempt_key,
            attempt_number=1,
            corrects_receipt_id="",
            predecessor_receipt_ids=[],
            skipped_tier_attestations=[],
            semantic_key=data_acquisition_module.stable_hash(
                {"attempt_key": attempt_key, "query_hash": "1" * 64}
            ),
            result_status="complete_valid",
            fallback_reason="",
            evidence_grade="screen-grade",
            snapshot_id="source-snapshot-test",
            dataset_id="dataset-test",
            row_count=121,
            missing_fields=[],
            missing_identifiers=[],
            missing_periods=[],
            coverage_note="",
            warnings=[],
            created_by="technical-analyst",
        )


@pytest.mark.parametrize(
    "fallback_reason",
    [
        "Authorization: Bearer abcdefghijklmnop",
        "provider failed at https://example.test/data?api_key=raw-secret",
        "Cookie=session-secret-value",
        "Invalid API key sk-abcdefghijklmnop",
    ],
)
def test_failure_receipt_rejects_secret_bearing_error_text(
    workspace: Path,
    fallback_reason: str,
) -> None:
    args = _external_result(
        result_status="terminal_gap",
        fallback_reason=fallback_reason,
        evidence_grade="unusable",
    )
    args.pop("rows")
    args.pop("columns")
    with pytest.raises(ValueError, match="credential"):
        record_external_data_result(workspace, args)
    assert not (workspace / DATA_ACQUISITION_RECEIPT_ROOT).exists()


def test_complete_partial_and_semantic_result_contracts(workspace: Path) -> None:
    missing_close = _external_result(
        columns=[
            {"name": "timestamp", "type": "timestamp", "nullable": False},
            {"name": "symbol", "type": "string", "nullable": False},
        ],
        rows=[
            {"timestamp": "2026-07-16T00:00:00Z", "symbol": "000660.KS"},
        ],
    )
    with pytest.raises(ValueError, match="missing requested fields: close"):
        record_external_data_result(workspace, missing_close)

    partial = record_external_data_result(
        workspace,
        _external_result(
            result_status="partial_valid",
            columns=[
                {"name": "timestamp", "type": "timestamp", "nullable": False},
                {"name": "symbol", "type": "string", "nullable": False},
            ],
            rows=[
                {"timestamp": "2026-07-16T00:00:00Z", "symbol": "000660.KS"},
            ],
        ),
    )
    assert partial["receipt"]["missing_fields"] == ["close"]

    first = record_external_data_result(
        workspace,
        _external_result(
            data_need=_data_need(identifiers=["005930.KS"]),
            provider_query={"symbol": "005930.KS", "provider": "yfinance", "limit": 3},
            symbols=["005930.KS"],
            rows=[
                {
                    "timestamp": "2026-07-16T00:00:00Z",
                    "symbol": "005930.KS",
                    "close": 255000.0,
                }
            ],
        ),
    )
    repeated_args = _external_result(
        data_need=_data_need(identifiers=["005930.KS"]),
        result_status="terminal_gap",
        fallback_reason="later presentation reported an empty result",
        evidence_grade="unusable",
        provider_query={"symbol": "005930.KS", "provider": "yfinance", "limit": 120},
        title="A different presentation title",
    )
    repeated_args.pop("rows")
    repeated_args.pop("columns")
    repeated = record_external_data_result(workspace, repeated_args)
    assert repeated["status"] == "existing"
    assert repeated["receipt_id"] == first["receipt_id"]
    assert repeated["receipt"]["result_status"] == "complete_valid"


def test_complete_series_rejects_duplicate_observations_and_invalid_ohlcv(
    workspace: Path,
) -> None:
    duplicated = _external_result(
        rows=[
            {
                "timestamp": "2026-07-16T00:00:00Z",
                "symbol": "000660.KS",
                "close": 1842000.0,
            },
            {
                "timestamp": "2026-07-16T00:00:00+00:00",
                "symbol": "000660.KS",
                "close": 1843000.0,
            },
        ]
    )
    with pytest.raises(ValueError, match=r"duplicate identifier\+timestamp"):
        record_external_data_result(workspace, duplicated)

    ohlcv_columns = [
        {"name": "timestamp", "type": "timestamp", "nullable": False},
        {"name": "symbol", "type": "string", "nullable": False},
        {"name": "open", "type": "float64", "nullable": False, "currency": "KRW"},
        {"name": "high", "type": "float64", "nullable": False, "currency": "KRW"},
        {"name": "low", "type": "float64", "nullable": False, "currency": "KRW"},
        {"name": "close", "type": "float64", "nullable": False, "currency": "KRW"},
        {"name": "volume", "type": "int64", "nullable": False, "unit": "shares"},
    ]
    invalid_ohlc = _external_result(
        data_need=_data_need(fields=["timestamp", "symbol", "open", "high", "low", "close", "volume"]),
        columns=ohlcv_columns,
        rows=[
            {
                "timestamp": "2026-07-16T00:00:00Z",
                "symbol": "000660.KS",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 10,
            }
        ],
    )
    with pytest.raises(ValueError, match="high is below close"):
        record_external_data_result(workspace, invalid_ohlc)

    negative_volume = _external_result(
        data_need=_data_need(fields=["timestamp", "symbol", "open", "high", "low", "close", "volume"]),
        columns=ohlcv_columns,
        rows=[
            {
                "timestamp": "2026-07-16T00:00:00Z",
                "symbol": "000660.KS",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": -1,
            }
        ],
    )
    with pytest.raises(ValueError, match="volume must not be negative"):
        record_external_data_result(workspace, negative_volume)


@pytest.mark.parametrize("result_status", ["partial_valid", "conflict"])
def test_every_storable_result_rejects_duplicate_identifier_timestamp_keys(
    workspace: Path,
    result_status: str,
) -> None:
    with pytest.raises(ValueError, match=r"duplicate identifier\+timestamp"):
        record_external_data_result(
            workspace,
            _external_result(
                result_status=result_status,
                coverage_note="bounded source response has residual coverage",
                warnings=["upstream values conflict"] if result_status == "conflict" else [],
                rows=[
                    {
                        "timestamp": "2026-07-16T00:00:00Z",
                        "symbol": "000660.KS",
                        "close": 1842000.0,
                    },
                    {
                        "timestamp": "2026-07-16T00:00:00+00:00",
                        "symbol": "000660.KS",
                        "close": 1843000.0,
                    },
                ],
            ),
        )


def test_result_identifiers_and_observation_bounds_are_enforced(workspace: Path) -> None:
    with pytest.raises(ValueError, match="not a requested identifier"):
        record_external_data_result(
            workspace,
            _external_result(
                rows=[
                    {
                        "timestamp": "2026-07-16T00:00:00Z",
                        "symbol": "FOREIGN.KS",
                        "close": 1.0,
                    }
                ]
            ),
        )

    with pytest.raises(ValueError, match="missing requested identifiers: 005930.KS"):
        record_external_data_result(
            workspace,
            _external_result(
                data_need=_data_need(identifiers=["000660.KS", "005930.KS"]),
                symbols=["000660.KS", "005930.KS"],
                rows=[
                    {
                        "timestamp": "2026-07-16T00:00:00Z",
                        "symbol": "000660.KS",
                        "close": 1842000.0,
                    }
                ],
            ),
        )

    with pytest.raises(ValueError, match="after data_need.period_end"):
        record_external_data_result(
            workspace,
            _external_result(
                rows=[
                    {
                        "timestamp": "2026-07-17T00:00:00Z",
                        "symbol": "000660.KS",
                        "close": 1800000.0,
                    }
                ]
            ),
        )


def test_partial_result_preserves_explicit_and_derived_residual_coverage(
    workspace: Path,
) -> None:
    one_row = [
        {
            "timestamp": "2026-07-16T00:00:00Z",
            "symbol": "000660.KS",
            "close": 1842000.0,
        }
    ]
    with pytest.raises(ValueError, match="requires missing_fields"):
        record_external_data_result(
            workspace,
            _external_result(result_status="partial_valid", rows=one_row),
        )

    with pytest.raises(ValueError, match="present in every retained row"):
        record_external_data_result(
            workspace,
            _external_result(
                result_status="partial_valid",
                missing_fields=["close"],
                rows=one_row,
            ),
        )

    bounded = record_external_data_result(
        workspace,
        _external_result(
            result_status="partial_valid",
            coverage_note="source returned 70 of 78 requested observations; calendar gaps not inferred",
            missing_periods=[
                {
                    "start": "2026-07-14T00:00:00Z",
                    "end": "2026-07-15T00:00:00Z",
                }
            ],
            rows=one_row,
        ),
    )
    assert bounded["receipt"]["missing_fields"] == []
    assert bounded["receipt"]["missing_identifiers"] == []
    assert bounded["receipt"]["missing_periods"] == [
        {
            "start": "2026-07-14T00:00:00Z",
            "end": "2026-07-15T00:00:00Z",
        }
    ]
    assert "70 of 78" in bounded["receipt"]["coverage_note"]

    nullable_columns = [
        {"name": "timestamp", "type": "timestamp", "nullable": False},
        {"name": "symbol", "type": "string", "nullable": False},
        {"name": "close", "type": "float64", "nullable": False, "currency": "KRW"},
        {"name": "volume", "type": "int64", "nullable": True, "unit": "shares"},
    ]
    derived = record_external_data_result(
        workspace,
        _external_result(
            data_need=_data_need(
                identifiers=["005930.KS", "000660.KS"],
                fields=["timestamp", "symbol", "close", "volume"],
            ),
            provider_query={"symbol": "005930.KS,000660.KS", "provider": "yfinance"},
            result_status="partial_valid",
            columns=nullable_columns,
            rows=[
                {
                    "timestamp": "2026-07-16T00:00:00Z",
                    "symbol": "005930.KS",
                    "close": 255000.0,
                    "volume": None,
                }
            ],
            symbols=["005930.KS", "000660.KS"],
        ),
    )
    assert derived["receipt"]["missing_fields"] == ["volume"]
    assert derived["receipt"]["missing_identifiers"] == ["000660.KS"]

    prefix = record_external_data_result(
        workspace,
        _external_result(
            data_need=_data_need(identifiers=["035420.KS"]),
            provider_query={"symbol": "035420.KS", "provider": "yfinance"},
            result_status="partial_valid",
            missing_periods=[
                {
                    "start": "2026-07-15T00:00:00Z",
                    "end": "2026-07-16T00:00:00Z",
                }
            ],
            rows=[
                {
                    "timestamp": "2026-07-14T00:00:00Z",
                    "symbol": "035420.KS",
                    "close": 300000.0,
                }
            ],
            symbols=["035420.KS"],
        ),
    )
    assert prefix["receipt"]["missing_periods"] == [
        {
            "start": "2026-07-15T00:00:00Z",
            "end": "2026-07-16T00:00:00Z",
        }
    ]

    with pytest.raises(ValueError, match="must not overlap retained observations"):
        record_external_data_result(
            workspace,
            _external_result(
                data_need=_data_need(identifiers=["068270.KS"]),
                provider_query={"symbol": "068270.KS", "provider": "yfinance"},
                result_status="partial_valid",
                missing_periods=[
                    {
                        "start": "2026-07-15T00:00:00Z",
                        "end": "2026-07-16T00:00:00Z",
                    }
                ],
                rows=[
                    {
                        "timestamp": "2026-07-16T00:00:00Z",
                        "symbol": "068270.KS",
                        "close": 180000.0,
                    }
                ],
                symbols=["068270.KS"],
            ),
        )


def test_conflict_result_requires_an_explicit_conflict_explanation(workspace: Path) -> None:
    with pytest.raises(ValueError, match="describe the conflict"):
        record_external_data_result(
            workspace,
            _external_result(result_status="conflict"),
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"timezone": "Not/A_Timezone"}, "valid IANA timezone"),
        (
            {
                "columns": [
                    {"name": "timestamp", "type": "timestamp", "nullable": False},
                    {"name": "symbol", "type": "string", "nullable": False},
                    {"name": "close", "type": "float64", "nullable": False, "currency": "krw"},
                ]
            },
            "uppercase ISO-style code",
        ),
        (
            {
                "rows": [
                    {
                        "timestamp": "2026-07-16T00:00:00Z",
                        "symbol": "000660.KS",
                        "close": float("inf"),
                    }
                ]
            },
            "must be finite",
        ),
    ],
)
def test_external_result_rejects_invalid_metadata_and_nonfinite_values(
    workspace: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        record_external_data_result(workspace, _external_result(**overrides))
    assert not (workspace / "trading/research/source-snapshots").exists()


@pytest.mark.parametrize(
    "result_status",
    [
        "correctable_error",
        "terminal_gap",
        "unsafe",
        "transient",
        "approval_required",
        "conflict",
    ],
)
def test_failed_external_attempts_record_receipt_only_without_fabricated_lineage(
    workspace: Path,
    result_status: str,
) -> None:
    args = _external_result(
        result_status=result_status,
        fallback_reason=f"{result_status}:provider did not return usable public rows",
        evidence_grade="unusable",
    )
    args.pop("rows")
    args.pop("columns")

    recorded = record_external_data_result(workspace, args)
    assert recorded["status"] == "recorded"
    assert recorded["row_count"] == 0
    assert recorded["snapshot_id"] == ""
    assert recorded["dataset_id"] == ""
    assert recorded["snapshot_path"] == ""
    assert recorded["dataset_manifest_path"] == ""
    assert recorded["receipt"]["result_status"] == result_status
    assert recorded["receipt"]["fallback_reason"].startswith(result_status)
    assert not (workspace / "trading/research/source-snapshots").exists()
    assert not (workspace / "trading/research/datasets/manifests").exists()

    repeated = record_external_data_result(workspace, args)
    assert repeated["status"] == "existing"
    assert repeated["receipt_id"] == recorded["receipt_id"]


def test_external_result_rolls_back_snapshot_dataset_and_payload_when_receipt_write_fails(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_receipt_write(path: Path, value: dict[str, object]) -> bool:
        del path, value
        raise OSError("fault-injected receipt write failure")

    monkeypatch.setattr(
        data_acquisition_module,
        "write_immutable_json",
        fail_receipt_write,
    )
    with pytest.raises(OSError, match="fault-injected"):
        record_external_data_result(workspace, _external_result())

    for relative in (
        "trading/research/source-snapshots",
        "trading/research/datasets/manifests",
        "trading/research/datasets/objects",
        "trading/research/data-acquisitions/receipts",
    ):
        directory = workspace / relative
        assert not directory.exists() or list(directory.iterdir()) == []


def test_interrupted_promotion_is_recovered_before_dataset_read(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_write = data_acquisition_module.write_immutable_json

    def interrupt_receipt_write(path: Path, value: dict[str, object]) -> bool:
        if path.parent == workspace / DATA_ACQUISITION_RECEIPT_ROOT:
            raise SystemExit("simulated abrupt termination")
        return original_write(path, value)

    monkeypatch.setattr(
        data_acquisition_module,
        "write_immutable_json",
        interrupt_receipt_write,
    )
    with pytest.raises(SystemExit, match="abrupt termination"):
        record_external_data_result(workspace, _external_result())

    manifests = list(
        (workspace / "trading/research/datasets/manifests").glob("*.json")
    )
    assert len(manifests) == 1
    interrupted_dataset_id = manifests[0].stem
    markers = list((workspace / DATA_ACQUISITION_TRANSACTION_ROOT).glob("*.json"))
    assert len(markers) == 1

    with pytest.raises(ValueError, match="dataset manifest .* not found"):
        get_dataset_manifest(workspace, {"dataset_id": interrupted_dataset_id})
    assert not list(
        (workspace / "trading/research/datasets/manifests").glob("*.json")
    )
    assert not list(
        (workspace / "trading/research/source-snapshots").glob("*.json")
    )
    assert not list((workspace / DATA_ACQUISITION_TRANSACTION_ROOT).glob("*.json"))


def test_committed_stale_marker_is_cleared_without_reentrant_recovery_deadlock(
    workspace: Path,
) -> None:
    recorded = record_external_data_result(workspace, _external_result())
    data_need = DataNeed.from_mapping(recorded["receipt"]["data_need"])
    transaction_id = data_acquisition_module._promotion_transaction_id(
        data_need=data_need,
        attempt_key=recorded["receipt"]["attempt_key"],
        semantic_key=recorded["receipt"]["semantic_key"],
    )
    data_acquisition_module._write_promotion_transaction(
        workspace,
        transaction_id=transaction_id,
        data_need=data_need,
        attempt_key=recorded["receipt"]["attempt_key"],
        semantic_key=recorded["receipt"]["semantic_key"],
        state="receipt_recorded",
        snapshot_id=recorded["snapshot_id"],
        dataset_id=recorded["dataset_id"],
        receipt_id=recorded["receipt_id"],
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from tradingcodex_service.application.datasets import "
                "get_dataset_manifest; "
                f"result=get_dataset_manifest({str(workspace)!r}, "
                f"{{'dataset_id': {recorded['dataset_id']!r}}}); "
                f"assert result['dataset']['dataset_id'] == {recorded['dataset_id']!r}"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert not list((workspace / DATA_ACQUISITION_TRANSACTION_ROOT).glob("*.json"))


def test_dataset_manifest_failure_does_not_leave_an_orphan_payload(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_manifest_write(path: Path, value: dict[str, object]) -> bool:
        del path, value
        raise OSError("fault-injected Dataset manifest write failure")

    monkeypatch.setattr(
        datasets_module,
        "write_immutable_json",
        fail_manifest_write,
    )
    with pytest.raises(OSError, match="Dataset manifest"):
        record_external_data_result(workspace, _external_result())

    for relative in (
        "trading/research/source-snapshots",
        "trading/research/datasets/manifests",
        "trading/research/datasets/objects",
        "trading/research/data-acquisitions/receipts",
    ):
        directory = workspace / relative
        assert not directory.exists() or list(directory.iterdir()) == []


def test_two_78_row_provider_results_round_trip_all_156_rows_without_loss(
    workspace: Path,
) -> None:
    start = datetime(2026, 3, 23, tzinfo=timezone.utc)
    datasets: list[tuple[str, list[dict[str, object]]]] = []
    for symbol, base in (("000660.KS", 1000.0), ("005930.KS", 2000.0)):
        rows = [
            {
                "timestamp": (start + timedelta(days=index)).isoformat().replace("+00:00", "Z"),
                "symbol": symbol,
                "close": base + index,
            }
            for index in range(78)
        ]
        end = rows[-1]["timestamp"]
        args = _external_result(
            data_need=_data_need(
                identifiers=[symbol],
                period_start=rows[0]["timestamp"],
                period_end=end,
                as_of=end,
            ),
            provider_query={"symbol": symbol, "provider": "yfinance"},
            rows=rows,
            symbols=[symbol],
            title=f"{symbol} 78-row source result",
        )
        recorded = record_external_data_result(workspace, args)
        assert recorded["row_count"] == 78
        datasets.append((recorded["dataset_id"], rows))

    observed_total = 0
    for dataset_id, expected_rows in datasets:
        page = get_dataset_rows(workspace, {"dataset_id": dataset_id, "limit": 120})
        assert page["next_cursor"] is None
        assert page["rows"] == [
            {**row, "timestamp": str(row["timestamp"]).replace("Z", "+00:00")}
            for row in expected_rows
        ]
        observed_total += len(page["rows"])

        exported = export_dataset_csv(workspace, {"dataset_id": dataset_id})
        with (workspace / exported["export_path"]).open(
            newline="", encoding="utf-8"
        ) as handle:
            csv_rows = list(csv.DictReader(handle))
        assert len(csv_rows) == 78
        assert [float(row["close"]) for row in csv_rows] == [
            float(row["close"]) for row in expected_rows
        ]
    assert observed_total == 156


def test_data_need_and_mcp_contracts_are_strict() -> None:
    missing_adjustment = _data_need()
    missing_adjustment.pop("adjustment_policy")
    with pytest.raises(ValueError, match="adjustment_policy is required"):
        DataNeed.from_mapping(missing_adjustment)
    missing_run = _data_need()
    missing_run.pop("run_id")
    with pytest.raises(ValueError, match="run_id is required"):
        DataNeed.from_mapping(missing_run)
    with pytest.raises(ValueError, match="strict.*explicit_source"):
        DataNeed.from_mapping(_data_need(source_policy="strict"))
    as_of_only = _data_need()
    as_of_only.pop("period_start")
    as_of_only.pop("period_end")
    assert DataNeed.from_mapping(as_of_only).as_of == "2026-07-16T00:00:00Z"
    period_only = _data_need()
    period_only.pop("as_of")
    assert DataNeed.from_mapping(period_only).period_end == "2026-07-16T00:00:00Z"
    with pytest.raises(ValueError, match="supplied together"):
        DataNeed.from_mapping({**as_of_only, "period_start": "2026-07-14T00:00:00Z"})

    external_tool = TOOL_REGISTRY["record_external_data_result"]
    assert external_tool.input_schema["properties"]["rows"]["maxItems"] == 120
    assert "rows" not in external_tool.input_schema["required"]
    assert "terminal_gap" in external_tool.input_schema["properties"]["result_status"]["enum"]
    data_need_required = external_tool.input_schema["properties"]["data_need"]["required"]
    assert {"period_start", "period_end", "as_of"}.isdisjoint(data_need_required)
    assert "run_id" in data_need_required
    assert "family_id" in external_tool.input_schema["properties"]["data_need"]["properties"]
    assert "adjustment_policy" in data_need_required
    assert external_tool.input_schema["properties"]["predecessor_receipt_ids"]["maxItems"] == 20
    skipped_schema = external_tool.input_schema["properties"]["skipped_tier_attestations"]
    assert skipped_schema["maxItems"] == 2
    assert skipped_schema["items"]["properties"]["source_tier"]["enum"] == [
        "user_capability",
        "openbb",
    ]
    assert external_tool.risk_level == "write"
    receipt_tool = TOOL_REGISTRY["get_data_acquisition_receipt"]
    assert receipt_tool.risk_level == "read"
    assert receipt_tool.input_schema["additionalProperties"] is False
    assert set(receipt_tool.input_schema["properties"]) == {
        "principal_id",
        "receipt_id",
        "dataset_id",
    }
    rows_tool = TOOL_REGISTRY["get_dataset_rows"]
    assert rows_tool.input_schema["properties"]["limit"]["maximum"] == 120
    assert TOOL_REGISTRY["get_source_snapshot"].risk_level == "read"
    assert TOOL_REGISTRY["get_official_source_plan"].risk_level == "read"
    status_tool = TOOL_REGISTRY["get_data_source_status"]
    assert status_tool.risk_level == "read"
    assert status_tool.input_schema["additionalProperties"] is False
    assert "data_kind" in status_tool.input_schema["properties"]
    assert "data_kind" in status_tool.input_schema["properties"]

    with pytest.raises(ValueError, match="does not allow additional properties"):
        validate_input_schema(
            rows_tool,
            {"dataset_id": "dataset-" + "0" * 24, "sql": "select *"},
        )


def test_data_source_status_is_available_through_service_and_authenticated_api(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_home = workspace.parent / f"{workspace.name}-runtime-home"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(runtime_home))
    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("TRADINGCODEX_API_KEY", "status-surface-key")
    monkeypatch.setenv("TRADINGCODEX_API_PRINCIPAL", "head-manager")

    direct = get_data_source_status(workspace, {"data_kind": "equity_price"})
    assert direct["integration"] == "openbb"
    assert direct["data_kind"] == "equity_price"
    assert direct["providers"] == []
    assert "matching_source_ids" in direct["official_sources"]
    assert "raw values are never returned" in direct["secret_policy"]

    response = Client(
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_TRADINGCODEX_KEY="status-surface-key",
    ).get(
        "/api/integrations/data-sources/status",
        {"data_kind": "equity_price"},
    )
    assert response.status_code == 200, response.content
    assert response.json()["integration"] == "openbb"
    assert response.json()["data_kind"] == "equity_price"

    filtered = Client(
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_TRADINGCODEX_KEY="status-surface-key",
    ).get("/api/integrations/data-sources/status?data_kind=equity_price")
    assert filtered.status_code == 200, filtered.content
    assert filtered.json()["integration"] == "openbb"


def test_external_data_api_round_trips_snapshot_rows_and_export(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_home = workspace.parent / f"{workspace.name}-api-runtime-home"
    monkeypatch.setenv("TRADINGCODEX_HOME", str(runtime_home))
    monkeypatch.setenv("TRADINGCODEX_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("TRADINGCODEX_API_KEY", "external-data-surface-key")
    monkeypatch.setenv("TRADINGCODEX_API_PRINCIPAL", "technical-analyst")
    ensure_runtime_database(workspace)
    client = Client(
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_TRADINGCODEX_KEY="external-data-surface-key",
    )
    payload = _external_result()
    payload.pop("principal_id")
    response = client.post(
        "/api/research/external-data-results",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    recorded = response.json()

    receipt = client.get(
        f"/api/research/data-acquisition-receipts/{recorded['receipt_id']}",
        {"dataset_id": recorded["dataset_id"]},
    )
    assert receipt.status_code == 200, receipt.content
    assert receipt.json()["lineage"]["dataset_id"] == recorded["dataset_id"]
    assert "provider_query" not in receipt.json()

    dataset_receipt = client.get(
        f"/api/research/datasets/{recorded['dataset_id']}/acquisition-receipt"
    )
    assert dataset_receipt.status_code == 200, dataset_receipt.content
    assert dataset_receipt.json()["receipt_id"] == recorded["receipt_id"]

    source = client.get(
        f"/api/research/source-snapshots/{recorded['snapshot_id']}",
        {"include_payload": "true"},
    )
    assert source.status_code == 200, source.content
    assert source.json()["snapshot"]["payload"]["row_count"] == 3

    rows = client.get(
        f"/api/research/datasets/{recorded['dataset_id']}/rows",
        {"limit": 120},
    )
    assert rows.status_code == 200, rows.content
    assert rows.json()["row_count"] == 3

    monkeypatch.setenv("TRADINGCODEX_API_PRINCIPAL", "head-manager")
    exported = client.post(
        f"/api/research/datasets/{recorded['dataset_id']}/export",
        data="{}",
        content_type="application/json",
    )
    assert exported.status_code == 200, exported.content
    assert (workspace / exported.json()["export_path"]).is_file()


def test_research_cli_reads_source_rows_and_exports_dataset(
    workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded = record_external_data_result(workspace, _external_result())

    research_command(
        workspace,
        ["source", "get", recorded["snapshot_id"]],
    )
    source_output = json.loads(capsys.readouterr().out)
    assert source_output["payload_included"] is False

    research_command(
        workspace,
        ["dataset", "rows", recorded["dataset_id"], "--limit", "1"],
    )
    rows_output = json.loads(capsys.readouterr().out)
    assert rows_output["row_count"] == 1
    assert rows_output["next_cursor"]

    research_command(
        workspace,
        ["dataset", "export", recorded["dataset_id"]],
    )
    export_output = json.loads(capsys.readouterr().out)
    assert (workspace / export_output["export_path"]).is_file()
