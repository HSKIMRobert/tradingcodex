from __future__ import annotations

import json

import pytest

from tradingcodex_service.application.official_sources import (
    get_official_source_plan,
    official_source_catalog,
)
from tradingcodex_service.application.official_source_adapters import (
    OfficialHttpResponse,
    OfficialSourceAuthError,
    OfficialSourceTransientError,
    execute_official_source_fallback,
    fetch_official_source_data,
    production_official_source_adapters,
)
from tradingcodex_service.application.agents import AGENT_SPECS, RESEARCH_ROLES
from tradingcodex_service.mcp_runtime import TOOL_REGISTRY


def test_catalog_is_secret_free_and_covers_keyless_and_free_key_sources() -> None:
    result = official_source_catalog()

    assert result["contract"] == "tradingcodex.official-data-sources.v1"
    assert {source["source_id"] for source in result["sources"]} >= {
        "sec-edgar",
        "us-treasury-daily-rates",
        "ecb-data-api",
        "world-bank-indicators",
        "cftc-cot",
        "data-go-kr-fsc-stock-price",
        "data-go-kr-fsc-etf-price",
        "data-go-kr-fsc-bond-price",
        "data-go-kr-fsc-futures-price",
        "data-go-kr-fsc-options-price",
        "data-go-kr-fsc-oil-price",
        "data-go-kr-fsc-gold-price",
        "data-go-kr-fsc-emissions-price",
        "opendart",
        "ecos",
        "kosis",
    }
    serialized = json.dumps(result)
    assert "api_key\": \"" not in serialized
    assert "credential_slots" in serialized
    bls_v1 = next(source for source in result["sources"] if source["source_id"] == "bls-v1")
    assert bls_v1["route"] == "https://api.bls.gov/publicAPI/v1/timeseries/data/"


def test_korean_equity_price_routes_to_official_fsc_free_key_source() -> None:
    result = get_official_source_plan(
        None,
        {"data_kind": "equity_price", "asset_class": "equity", "region": "KR"},
    )

    assert result["coverage_gap"] == ""
    assert result["fallback_order"] == ["data-go-kr-fsc-stock-price"]
    assert result["candidates"][0]["credential_state"] == "configuration_required"
    assert result["candidates"][0]["route"].endswith(
        "/GetStockSecuritiesInfoService/getStockPriceInfo"
    )


def test_global_exchange_price_gap_is_explicit() -> None:
    result = get_official_source_plan(
        None,
        {"data_kind": "equity_price", "asset_class": "equity", "region": "US"},
    )

    assert result["candidates"] == []
    assert result["coverage_gap"] == "official_price_unavailable"


def test_exchange_price_requires_region_instead_of_borrowing_korean_coverage() -> None:
    result = get_official_source_plan(
        None,
        {"data_kind": "equity_price", "asset_class": "equity"},
    )

    assert result["candidates"] == []
    assert result["coverage_gap"] == "region_required"


def test_reference_only_statistics_do_not_close_exchange_price_gap() -> None:
    result = get_official_source_plan(
        None,
        {
            "data_kind": "commodity_price",
            "asset_class": "commodity",
            "region": "US",
        },
    )

    assert result["fallback_order"] == ["eia-v2"]
    assert result["actionable_fallback_order"] == []
    assert result["reference_candidate_ids"] == ["eia-v2"]
    assert result["coverage_gap"] == "official_price_unavailable"


def test_all_exchange_price_kinds_use_the_explicit_price_gap() -> None:
    result = get_official_source_plan(
        None,
        {"data_kind": "bond_price", "asset_class": "bond", "region": "EU"},
    )

    assert result["candidates"] == []
    assert result["coverage_gap"] == "official_price_unavailable"


def test_reference_rates_are_not_mislabeled_as_executable_prices() -> None:
    result = get_official_source_plan(
        None,
        {"data_kind": "fx_reference", "asset_class": "fx", "region": "EU"},
    )

    assert result["fallback_order"][0] == "ecb-data-api"
    assert result["candidates"][0]["reference_only"] is True


def test_invalid_data_kind_fails_closed() -> None:
    with pytest.raises(ValueError, match="data_kind must be one of"):
        get_official_source_plan(None, {"data_kind": "live_magic_price"})


def test_invalid_source_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="source_policy must be"):
        get_official_source_plan(
            None,
            {"data_kind": "filing", "source_policy": "silently_try_everything"},
        )

    unavailable = get_official_source_plan(
        None,
        {
            "data_kind": "filing",
            "source_policy": "strict",
            "source_id": "not-a-real-source",
        },
    )
    assert unavailable["fallback_order"] == []
    assert unavailable["coverage_gap"] == "requested_source_unavailable"

    with pytest.raises(ValueError, match="strict.*source_id"):
        get_official_source_plan(
            None,
            {"data_kind": "filing", "source_policy": "strict"},
        )


def test_preferred_source_is_first_without_disabling_fallback() -> None:
    result = get_official_source_plan(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "source_policy": "preferred",
            "source_id": "world-bank-indicators",
        },
    )

    assert result["fallback_order"][0] == "world-bank-indicators"
    assert "bls-v1" in result["fallback_order"]


def test_fsc_routes_are_product_specific_and_documented() -> None:
    catalog = official_source_catalog()
    by_id = {source["source_id"]: source for source in catalog["sources"]}

    assert by_id["data-go-kr-fsc-etf-price"]["route"].endswith(
        "/GetSecuritiesProductInfoService/getETFPriceInfo"
    )
    assert by_id["data-go-kr-fsc-bond-price"]["route"].endswith(
        "/GetBondSecuritiesInfoService/getBondPriceInfo"
    )
    assert by_id["data-go-kr-fsc-futures-price"]["route"].endswith(
        "/GetDerivativeProductInfoService/getStockFuturesPriceInfo"
    )
    assert by_id["data-go-kr-fsc-options-price"]["route"].endswith(
        "/GetDerivativeProductInfoService/getOptionsPriceInfo"
    )
    assert by_id["data-go-kr-fsc-oil-price"]["route"].endswith(
        "/GetGeneralProductInfoService/getOilPriceInfo"
    )
    assert by_id["data-go-kr-fsc-gold-price"]["route"].endswith(
        "/GetGeneralProductInfoService/getGoldPriceInfo"
    )
    assert by_id["data-go-kr-fsc-emissions-price"]["route"].endswith(
        "/GetGeneralProductInfoService/getCertifiedEmissionReductionPriceInfo"
    )


def test_executor_falls_back_after_auth_failure_without_retrying() -> None:
    calls: list[str] = []

    def bea(source: dict[str, object], request: dict[str, object]) -> dict[str, object]:
        del request
        calls.append(str(source["source_id"]))
        raise OfficialSourceAuthError("must never leave the adapter boundary")

    def bls(source: dict[str, object], request: dict[str, object]) -> dict[str, object]:
        del request
        calls.append(str(source["source_id"]))
        return {
            "outcome": "complete_valid",
            "rows": [{"series_id": "LNS14000000", "value": "4.1"}],
        }

    result = execute_official_source_fallback(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "region": "US",
            "source_policy": "preferred",
            "source_id": "bea",
        },
        adapters={"bea": bea, "bls-v1": bls},
        credential_states={"bea": "available"},
    )

    assert result["status"] == "complete_valid"
    assert result["selected_source_id"] == "bls-v1"
    assert calls == ["bea", "bls-v1"]
    assert result["same_call_retries"] == 0
    assert result["attempts"][0]["outcome"] == "auth_failed"
    assert result["attempts"][0]["detail_code"] == "credential_rejected"
    assert "must never leave" not in json.dumps(result)


def test_executor_does_not_call_free_key_adapter_without_available_reference() -> None:
    called = False

    def adapter(*_args: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {"outcome": "complete_valid", "rows": [{"value": 1}]}

    result = execute_official_source_fallback(
        None,
        {
            "data_kind": "equity_price",
            "asset_class": "equity",
            "region": "KR",
            "source_policy": "strict",
            "source_id": "data-go-kr-fsc-stock-price",
        },
        adapters={"data-go-kr-fsc-stock-price": adapter},
    )

    assert called is False
    assert result["status"] == "approval_required"
    assert result["attempts"][0]["outcome"] == "credential_unavailable"


def test_executor_classifies_empty_stale_and_transient_before_success() -> None:
    def empty(*_args: object) -> dict[str, object]:
        return {"outcome": "complete_valid", "rows": []}

    def stale(*_args: object) -> dict[str, object]:
        return {
            "outcome": "complete_valid",
            "stale": True,
            "rows": [{"series_id": "stale", "value": 1}],
        }

    def transient(*_args: object) -> dict[str, object]:
        raise OfficialSourceTransientError("redacted")

    def complete(*_args: object) -> dict[str, object]:
        return {
            "outcome": "complete_valid",
            "records": [{"indicator": "NY.GDP.MKTP.CD", "value": 1}],
        }

    result = execute_official_source_fallback(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "source_policy": "preferred",
            "source_id": "bls-v1",
        },
        adapters={
            "bls-v1": empty,
            "us-treasury-daily-rates": stale,
            "ecb-data-api": transient,
            "world-bank-indicators": complete,
        },
    )

    assert result["selected_source_id"] == "world-bank-indicators"
    assert [attempt["outcome"] for attempt in result["attempts"]] == [
        "empty",
        "stale",
        "transient",
        "complete_valid",
    ]


def test_executor_obeys_strict_pin_and_does_not_fallback() -> None:
    result = execute_official_source_fallback(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "source_policy": "strict",
            "source_id": "bls-v1",
        },
        adapters={
            "bls-v1": lambda *_args: {"outcome": "complete_valid", "rows": []},
            "world-bank-indicators": lambda *_args: {
                "outcome": "complete_valid",
                "rows": [{"value": 1}],
            },
        },
    )

    assert result["status"] == "terminal_gap"
    assert [attempt["source_id"] for attempt in result["attempts"]] == ["bls-v1"]
    assert result["attempts"][0]["outcome"] == "empty"


def test_reference_only_adapter_result_remains_partial_with_price_gap() -> None:
    result = execute_official_source_fallback(
        None,
        {
            "data_kind": "commodity_price",
            "asset_class": "commodity",
            "region": "US",
        },
        adapters={
            "eia-v2": lambda *_args: {
                "outcome": "complete_valid",
                "rows": [{"series_id": "PET.RWTC.D", "value": 75.0}],
            }
        },
        credential_states={"eia-v2": "available"},
    )

    assert result["status"] == "partial_valid"
    assert result["selected_source_id"] == "eia-v2"
    assert result["coverage_gap"] == "official_price_unavailable"
    assert result["attempts"][0]["outcome"] == "reference_only_result"


def test_executor_rejects_over_120_rows_without_carrying_raw_result() -> None:
    result = execute_official_source_fallback(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "source_policy": "strict",
            "source_id": "bls-v1",
        },
        adapters={
            "bls-v1": lambda *_args: {
                "outcome": "complete_valid",
                "rows": [{"series_id": "x", "value": index} for index in range(121)],
            }
        },
    )

    assert result["status"] == "terminal_gap"
    assert result["attempts"][0]["outcome"] == "truncated"
    assert result["attempts"][0]["row_count"] == 0
    assert result["accepted_results"] == []


def test_executor_stops_after_first_partial_before_calling_second_provider() -> None:
    calls: list[str] = []

    def partial(source, _request):
        calls.append(source["source_id"])
        return {
            "outcome": "partial_valid",
            "rows": [{"identifier": "LNS14000000", "value": "4.1"}],
            "missing_fields": ["revision"],
        }

    def must_not_run(source, _request):
        calls.append(source["source_id"])
        return {"outcome": "complete_valid", "rows": [{"value": 1}]}

    result = execute_official_source_fallback(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "region": "US",
            "source_policy": "preferred",
            "source_id": "bls-v1",
            "identifiers": ["LNS14000000"],
            "fields": ["value", "revision"],
            "as_of": "2026-07-18T00:00:00Z",
        },
        adapters={"bls-v1": partial, "world-bank-indicators": must_not_run},
    )

    assert result["status"] == "partial_valid"
    assert result["selected_source_id"] == "bls-v1"
    assert calls == ["bls-v1"]
    assert len(result["accepted_results"]) == 1


def test_production_registry_contains_only_reviewed_keyless_adapters() -> None:
    adapters = production_official_source_adapters(
        http_transport=lambda _request: OfficialHttpResponse(500, {}, b"")
    )

    assert set(adapters) == {
        "sec-edgar",
        "us-treasury-daily-rates",
        "bls-v1",
        "ecb-data-api",
        "world-bank-indicators",
        "cftc-cot",
        "bank-of-canada-valet",
    }
    assert not any(source_id.startswith("data-go-kr") for source_id in adapters)


def test_production_sec_adapter_uses_fixed_host_identifying_user_agent_and_normalizes() -> None:
    seen = []
    payload = {
        "name": "Example Corp",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000000-26-000001"],
                "filingDate": ["2026-07-15"],
                "reportDate": ["2026-06-30"],
                "acceptanceDateTime": ["2026-07-15T12:34:56.000Z"],
                "form": ["10-Q"],
                "primaryDocument": ["example-20260630.htm"],
                "primaryDocDescription": ["Quarterly report"],
                "isXBRL": [1],
                "isInlineXBRL": [1],
            }
        },
    }

    def transport(request):
        seen.append(request)
        return OfficialHttpResponse(
            200,
            {"set-cookie": "must-not-escape"},
            json.dumps(payload).encode(),
            request.url,
        )

    result = fetch_official_source_data(
        None,
        {
            "data_kind": "filing",
            "asset_class": "equity",
            "region": "US",
            "source_policy": "strict",
            "source_id": "sec-edgar",
            "identifiers": ["CIK320193"],
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-07-18T00:00:00Z",
            "fields": ["report_date"],
        },
        http_transport=transport,
    )

    assert result["status"] == "complete_valid"
    response = result["record_external_data_result_args"]
    assert response["rows"] == [
        {
            "identifier": "CIK320193",
            "cik": "CIK0000320193",
            "accession_number": "0000000000-26-000001",
            "filing_date": "2026-07-15",
            "form": "10-Q",
            "report_date": "2026-06-30",
        }
    ]
    assert seen[0].method == "GET"
    assert seen[0].url == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert "@" in seen[0].headers["User-Agent"]
    serialized = json.dumps(result)
    assert "set-cookie" not in serialized
    assert "must-not-escape" not in serialized
    assert "Immediately call record_external_data_result" in result["recorder_instruction"]
    assert len(serialized) <= 20_000


def test_production_bls_adapter_posts_only_bounded_public_series_contract() -> None:
    seen = []
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": "LNS14000000",
                    "data": [
                        {
                            "year": "2026",
                            "period": "M06",
                            "periodName": "June",
                            "value": "4.1",
                            "latest": "true",
                        }
                    ],
                }
            ]
        },
    }

    def transport(request):
        seen.append(request)
        return OfficialHttpResponse(200, {}, json.dumps(payload).encode(), request.url)

    result = fetch_official_source_data(
        None,
        {
            "data_kind": "labor",
            "asset_class": "macro",
            "region": "US",
            "source_policy": "strict",
            "source_id": "bls-v1",
            "identifiers": ["LNS14000000"],
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-07-18T00:00:00Z",
        },
        http_transport=transport,
    )

    assert result["status"] == "complete_valid"
    assert seen[0].method == "POST"
    assert seen[0].url == "https://api.bls.gov/publicAPI/v1/timeseries/data/"
    request_body = json.loads(seen[0].body)
    assert request_body == {
        "seriesid": ["LNS14000000"],
        "startyear": "2026",
        "endyear": "2026",
    }
    assert "registrationkey" not in request_body
    row = result["record_external_data_result_args"]["rows"][0]
    assert row["series_id"] == "LNS14000000"
    assert row["value"] == "4.1"


@pytest.mark.parametrize(
    ("status_code", "expected_outcome"),
    [
        (401, "auth_failed"),
        (403, "entitlement_failed"),
        (204, "empty"),
        (429, "rate_limited"),
        (504, "timeout"),
        (503, "transient"),
    ],
)
def test_production_http_failures_are_typed_without_exception_body_leakage(
    status_code: int,
    expected_outcome: str,
) -> None:
    def transport(request):
        return OfficialHttpResponse(
            status_code,
            {"authorization": "must-not-escape"},
            b"upstream-secret-bearing-exception-body",
            request.url,
        )

    result = fetch_official_source_data(
        None,
        {
            "data_kind": "labor",
            "asset_class": "macro",
            "region": "US",
            "source_policy": "strict",
            "source_id": "bls-v1",
            "identifiers": ["LNS14000000"],
            "as_of": "2026-07-18T00:00:00Z",
        },
        http_transport=transport,
    )

    assert result["attempts"][0]["outcome"] == expected_outcome
    serialized = json.dumps(result)
    assert "must-not-escape" not in serialized
    assert "secret-bearing" not in serialized
    assert "rows" not in result["record_external_data_result_args"]
    assert result["record_external_data_result_args"]["returned_provider"] == ""


def test_production_sec_adapter_classifies_only_pre_window_filings_as_stale() -> None:
    payload = {
        "name": "Example Corp",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000000-20-000001"],
                "filingDate": ["2020-01-15"],
                "form": ["10-K"],
            }
        },
    }

    def transport(request):
        return OfficialHttpResponse(200, {}, json.dumps(payload).encode(), request.url)

    result = fetch_official_source_data(
        None,
        {
            "data_kind": "filing",
            "asset_class": "equity",
            "region": "US",
            "source_policy": "strict",
            "source_id": "sec-edgar",
            "identifiers": ["CIK320193"],
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-07-18T00:00:00Z",
        },
        http_transport=transport,
    )

    assert result["status"] == "terminal_gap"
    assert result["attempts"][0]["outcome"] == "stale"


def test_production_world_bank_adapter_uses_exact_country_indicator_and_bounded_page() -> None:
    seen = []
    payload = [
        {"page": 1, "pages": 1, "per_page": 120, "total": 1},
        [
            {
                "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP"},
                "country": {"id": "US", "value": "United States"},
                "date": "2025",
                "value": 1,
                "unit": "USD",
                "obs_status": "",
                "decimal": 0,
            }
        ],
    ]

    def transport(request):
        seen.append(request)
        return OfficialHttpResponse(200, {}, json.dumps(payload).encode(), request.url)

    result = fetch_official_source_data(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "region": "US",
            "source_policy": "strict",
            "source_id": "world-bank-indicators",
            "identifiers": ["US:NY.GDP.MKTP.CD"],
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-12-31T23:59:59Z",
        },
        http_transport=transport,
    )

    assert result["status"] == "complete_valid"
    assert seen[0].method == "GET"
    assert seen[0].url.startswith(
        "https://api.worldbank.org/v2/country/US/indicator/NY.GDP.MKTP.CD?"
    )
    assert "per_page=120" in seen[0].url
    response = result["record_external_data_result_args"]
    assert response["provider_query"] == {
        "provider": "world-bank-indicators",
        "country": "US",
        "indicator": "NY.GDP.MKTP.CD",
        "start_year": 2025,
        "end_year": 2025,
    }


def test_production_fallback_changes_source_once_and_never_repeats_http_call() -> None:
    calls = []
    payload = [
        {"page": 1, "pages": 1, "per_page": 120, "total": 1},
        [
            {
                "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP"},
                "country": {"id": "US", "value": "United States"},
                "date": "2025",
                "value": 1,
            }
        ],
    ]

    def transport(request):
        calls.append(request.url)
        return OfficialHttpResponse(200, {}, json.dumps(payload).encode(), request.url)

    result = fetch_official_source_data(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "region": "US",
            "source_policy": "preferred",
            "source_id": "bls-v1",
            "identifiers": ["US:NY.GDP.MKTP.CD"],
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-12-31T23:59:59Z",
        },
        http_transport=transport,
    )

    assert result["selected_source_id"] == "world-bank-indicators"
    assert result["same_call_retries"] == 0
    assert [attempt["outcome"] for attempt in result["attempts"]] == [
        "correctable_error",
        "correctable_error",
        "credential_unavailable",
        "credential_unavailable",
        "credential_unavailable",
        "complete_valid",
    ]
    assert len(calls) == 1
    assert calls[0].startswith("https://api.worldbank.org/")


def test_production_free_key_source_remains_approval_gap_without_env_access() -> None:
    called = False

    def transport(_request):
        nonlocal called
        called = True
        return OfficialHttpResponse(200, {}, b"{}")

    result = fetch_official_source_data(
        None,
        {
            "data_kind": "macro",
            "asset_class": "macro",
            "region": "US",
            "source_policy": "strict",
            "source_id": "bea",
            "identifiers": ["NIPA:T10101"],
            "as_of": "2026-07-18T00:00:00Z",
        },
        http_transport=transport,
    )

    assert called is False
    assert result["status"] == "approval_required"
    assert result["attempts"][0]["outcome"] == "credential_unavailable"


def test_official_fetch_tool_is_only_projected_to_six_evidence_producers() -> None:
    tool = TOOL_REGISTRY["fetch_official_source_data"]

    assert tool.risk_level == "read"
    assert tool.public_definition()["annotations"]["openWorldHint"] is True
    assert tool.allowed_roles == frozenset(RESEARCH_ROLES)
    assert all(
        "fetch_official_source_data" in AGENT_SPECS[role].mcp_allowlist
        for role in RESEARCH_ROLES
    )
    assert all(
        "fetch_official_source_data" not in AGENT_SPECS[role].mcp_allowlist
        for role in ("head-manager", "portfolio-manager", "risk-manager", "judgment-reviewer")
    )
    assert set(tool.input_schema["properties"]).isdisjoint(
        {"url", "headers", "credential", "credential_ref", "request_body"}
    )
