from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final

from tradingcodex_service.application.common import stable_hash


OFFICIAL_DATA_KINDS: Final[frozenset[str]] = frozenset(
    {
        "bond_price",
        "commodity_price",
        "corporate_action",
        "crypto_price",
        "energy",
        "equity_price",
        "etf_price",
        "filing",
        "fundamentals",
        "futures_price",
        "fx_reference",
        "labor",
        "macro",
        "options_price",
        "positioning",
        "reference",
        "yield_curve",
    }
)

OFFICIAL_ASSET_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "bond",
        "commodity",
        "crypto",
        "equity",
        "etf",
        "filing",
        "futures",
        "fx",
        "macro",
        "options",
    }
)
SOURCE_POLICIES: Final[frozenset[str]] = frozenset(
    {"strict", "preferred", "best_available"}
)
EXCHANGE_PRICE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "bond_price",
        "commodity_price",
        "crypto_price",
        "equity_price",
        "etf_price",
        "futures_price",
        "options_price",
    }
)


@dataclass(frozen=True, slots=True)
class OfficialSourceSpec:
    source_id: str
    label: str
    authority: str
    region: str
    data_kinds: tuple[str, ...]
    asset_classes: tuple[str, ...]
    access: str
    credential_slots: tuple[str, ...]
    cadence: str
    evidence_grade_ceiling: str
    route: str
    documentation_url: str
    terms_url: str
    coverage_note: str
    default_priority: int
    reference_only: bool = False


_SOURCES: Final[tuple[OfficialSourceSpec, ...]] = (
    OfficialSourceSpec(
        "sec-edgar",
        "SEC EDGAR",
        "United States Securities and Exchange Commission",
        "US",
        ("filing", "fundamentals"),
        ("equity", "filing"),
        "keyless",
        (),
        "near_real_time_filings",
        "factual-baseline",
        "https://data.sec.gov/",
        "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "https://www.sec.gov/about/webmaster-frequently-asked-questions",
        "Requires a declared, identifying User-Agent and SEC rate-limit compliance.",
        10,
    ),
    OfficialSourceSpec(
        "us-treasury-daily-rates",
        "U.S. Treasury Daily Rates",
        "United States Department of the Treasury",
        "US",
        ("yield_curve", "macro"),
        ("bond", "macro"),
        "keyless",
        (),
        "daily",
        "factual-baseline",
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
        "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
        "https://home.treasury.gov/utility/policies-and-notices",
        "Publishes reference par, real, and bill-rate series rather than executable bond prices.",
        20,
        True,
    ),
    OfficialSourceSpec(
        "bls-v1",
        "BLS Public Data API v1",
        "United States Bureau of Labor Statistics",
        "US",
        ("labor", "macro"),
        ("macro",),
        "keyless",
        (),
        "release_calendar",
        "factual-baseline",
        "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        "https://www.bls.gov/developers/",
        "https://www.bls.gov/developers/termsOfService.htm",
        "Unregistered access has lower daily and per-request limits and may lag publication.",
        30,
    ),
    OfficialSourceSpec(
        "ecb-data-api",
        "ECB Data Portal API",
        "European Central Bank",
        "EU",
        ("macro", "fx_reference", "yield_curve"),
        ("macro", "fx", "bond"),
        "keyless",
        (),
        "series_dependent",
        "factual-baseline",
        "https://data-api.ecb.europa.eu/service/data/",
        "https://data.ecb.europa.eu/help/api/data",
        "https://www.ecb.europa.eu/services/data/html/index.en.html",
        "Third-party series can carry separate rights; reference FX is not an executable quote.",
        40,
        True,
    ),
    OfficialSourceSpec(
        "world-bank-indicators",
        "World Bank Indicators API",
        "World Bank",
        "GLOBAL",
        ("macro", "reference"),
        ("macro",),
        "keyless",
        (),
        "series_dependent",
        "factual-baseline",
        "https://api.worldbank.org/v2/",
        "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
        "https://data.worldbank.org/summary-terms-of-use",
        "Use only series whose dataset-level license metadata permits the intended use.",
        50,
    ),
    OfficialSourceSpec(
        "cftc-cot",
        "CFTC Commitments of Traders",
        "United States Commodity Futures Trading Commission",
        "US",
        ("positioning",),
        ("futures", "commodity"),
        "keyless",
        (),
        "weekly",
        "factual-baseline",
        "https://publicreporting.cftc.gov/",
        "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        "https://www.cftc.gov/Privacy",
        "Reports positioning with a publication lag and is not a futures-price source.",
        60,
        True,
    ),
    OfficialSourceSpec(
        "bank-of-canada-valet",
        "Bank of Canada Valet API",
        "Bank of Canada",
        "CA",
        ("fx_reference", "macro", "yield_curve"),
        ("fx", "macro", "bond"),
        "keyless",
        (),
        "series_dependent",
        "screen-grade",
        "https://www.bankofcanada.ca/valet/",
        "https://www.bankofcanada.ca/valet-api-how-to/",
        "https://www.bankofcanada.ca/terms/",
        "Indicative statistical reference values must not be treated as executable prices.",
        70,
        True,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-stock-price",
        "Korea FSC Stock Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("equity_price",),
        ("equity",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo",
        "https://www.data.go.kr/data/15094808/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "Korea Exchange stock prices republished by FSC; the portal states that the feed is updated once per business day after the reference date.",
        10,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-etf-price",
        "Korea FSC Securities Product Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("etf_price",),
        ("etf",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/service/GetSecuritiesProductInfoService/getETFPriceInfo",
        "https://www.data.go.kr/data/15094806/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "The service covers ETF, ETN, and ELW products; this route is the ETF operation and must not be used as a stock or bond route.",
        11,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-bond-price",
        "Korea FSC Bond Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("bond_price",),
        ("bond",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/service/GetBondSecuritiesInfoService/getBondPriceInfo",
        "https://www.data.go.kr/data/15094784/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "Korea Exchange bond-market prices republished by FSC; bind market segment, ISIN, date, and price/yield units.",
        12,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-futures-price",
        "Korea FSC Futures Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("futures_price",),
        ("futures",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/GetDerivativeProductInfoService/getStockFuturesPriceInfo",
        "https://www.data.go.kr/data/15094802/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "The derivatives service has distinct futures and options operations; retain contract identity and expiry.",
        13,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-options-price",
        "Korea FSC Options Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("options_price",),
        ("options",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/GetDerivativeProductInfoService/getOptionsPriceInfo",
        "https://www.data.go.kr/data/15094802/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "The derivatives service has distinct futures and options operations; retain strike, call/put, contract identity, and expiry.",
        14,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-oil-price",
        "Korea FSC Exchange Oil Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("commodity_price",),
        ("commodity",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/service/GetGeneralProductInfoService/getOilPriceInfo",
        "https://www.data.go.kr/data/15094805/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "Oil products traded on the Korea Exchange petroleum market; retain product and unit identity.",
        15,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-gold-price",
        "Korea FSC KRX Gold Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("commodity_price",),
        ("commodity",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/service/GetGeneralProductInfoService/getGoldPriceInfo",
        "https://www.data.go.kr/data/15094805/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "Gold products traded on the KRX gold market; retain product, weight unit, and currency.",
        16,
    ),
    OfficialSourceSpec(
        "data-go-kr-fsc-emissions-price",
        "Korea FSC Emissions Allowance Price API",
        "Financial Services Commission of Korea",
        "KR",
        ("commodity_price",),
        ("commodity",),
        "free_key",
        ("data_go_kr_api_key",),
        "delayed_eod",
        "factual-baseline",
        "https://apis.data.go.kr/1160100/service/GetGeneralProductInfoService/getCertifiedEmissionReductionPriceInfo",
        "https://www.data.go.kr/data/15094805/openapi.do",
        "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
        "Emissions allowances traded on the Korea Exchange; retain allowance vintage and unit identity.",
        17,
    ),
    OfficialSourceSpec(
        "opendart",
        "OpenDART",
        "Financial Supervisory Service of Korea",
        "KR",
        ("filing", "fundamentals"),
        ("equity", "filing"),
        "free_key",
        ("opendart_api_key",),
        "near_real_time_filings",
        "factual-baseline",
        "https://opendart.fss.or.kr/api/",
        "https://opendart.fss.or.kr/guide/main.do",
        "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001",
        "Bind disclosure identifiers, publication time, fiscal period, units, and amendment posture.",
        20,
    ),
    OfficialSourceSpec(
        "ecos",
        "Bank of Korea ECOS",
        "Bank of Korea",
        "KR",
        ("macro", "fx_reference", "yield_curve"),
        ("macro", "fx", "bond"),
        "free_key",
        ("ecos_api_key",),
        "series_dependent",
        "factual-baseline",
        "https://ecos.bok.or.kr/api/",
        "https://ecos.bok.or.kr/api/",
        "https://ecos.bok.or.kr/#/CustomerService/OpenAPI",
        "Historical analysis must distinguish current revisions from cutoff-valid vintages.",
        30,
        True,
    ),
    OfficialSourceSpec(
        "kosis",
        "KOSIS Open API",
        "Statistics Korea",
        "KR",
        ("macro", "labor", "reference"),
        ("macro",),
        "free_key",
        ("kosis_api_key",),
        "series_dependent",
        "factual-baseline",
        "https://kosis.kr/openapi/",
        "https://kosis.kr/openapi/index/index.jsp?serviceCD=4",
        "https://kosis.kr/serviceInfo/policy/openApiDetail.do",
        "Observe published call limits and preserve statistical-table identity and revision posture.",
        40,
    ),
    OfficialSourceSpec(
        "bea",
        "BEA API",
        "United States Bureau of Economic Analysis",
        "US",
        ("macro",),
        ("macro",),
        "free_key",
        ("bea_api_key",),
        "release_calendar",
        "factual-baseline",
        "https://apps.bea.gov/api/data/",
        "https://apps.bea.gov/api/signup/",
        "https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf",
        "Preserve dataset, table, line, frequency, unit, and vintage identity.",
        50,
    ),
    OfficialSourceSpec(
        "eia-v2",
        "EIA API v2",
        "United States Energy Information Administration",
        "US",
        ("energy", "commodity_price", "macro"),
        ("commodity", "macro"),
        "free_key",
        ("eia_api_key",),
        "series_dependent",
        "factual-baseline",
        "https://api.eia.gov/v2/",
        "https://www.eia.gov/opendata/documentation.php",
        "https://www.eia.gov/about/copyrights_reuse.php",
        "Many series are official statistics rather than executable commodity prices; pagination is required.",
        60,
        True,
    ),
    OfficialSourceSpec(
        "bls-v2-registered",
        "BLS Public Data API v2 Registered",
        "United States Bureau of Labor Statistics",
        "US",
        ("labor", "macro"),
        ("macro",),
        "free_key",
        ("bls_api_key",),
        "release_calendar",
        "factual-baseline",
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "https://www.bls.gov/developers/",
        "https://www.bls.gov/developers/termsOfService.htm",
        "Registered access raises request limits but does not alter revision or publication-time requirements.",
        70,
    ),
)


def official_source_catalog() -> dict[str, Any]:
    sources = [_public_source(spec) for spec in _SOURCES]
    return {
        "schema_version": 1,
        "contract": "tradingcodex.official-data-sources.v1",
        "data_kinds": sorted(OFFICIAL_DATA_KINDS),
        "asset_classes": sorted(OFFICIAL_ASSET_CLASSES),
        "sources": sources,
        "catalog_digest": stable_hash(sources),
        "credential_policy": "environment references only; never include raw values",
        "default_quality_posture": "end_of_day_or_delayed",
    }


def get_official_source_plan(
    workspace_root: Any,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del workspace_root
    request = args or {}
    data_kind = str(request.get("data_kind") or "").strip().lower()
    asset_class = str(request.get("asset_class") or "").strip().lower()
    region = str(request.get("region") or "").strip().upper()
    exact_source = str(request.get("source_id") or "").strip().lower()
    source_policy = str(
        request.get("source_policy") or "best_available"
    ).strip().lower()
    if data_kind not in OFFICIAL_DATA_KINDS:
        raise ValueError(
            f"data_kind must be one of: {', '.join(sorted(OFFICIAL_DATA_KINDS))}"
        )
    if asset_class and asset_class not in OFFICIAL_ASSET_CLASSES:
        raise ValueError(
            f"asset_class must be one of: {', '.join(sorted(OFFICIAL_ASSET_CLASSES))}"
        )
    if region and region != "GLOBAL" and (
        len(region) != 2 or not region.isalpha()
    ):
        raise ValueError("region must be a two-letter country code or GLOBAL")
    if source_policy not in SOURCE_POLICIES:
        raise ValueError(
            "source_policy must be strict, preferred, or best_available"
        )
    if source_policy == "strict" and not exact_source:
        raise ValueError("strict source_policy requires source_id")
    if data_kind in EXCHANGE_PRICE_KINDS and not region:
        return {
            "schema_version": 1,
            "data_kind": data_kind,
            "asset_class": asset_class,
            "region": region,
            "source_policy": source_policy,
            "candidates": [],
            "coverage_gap": "region_required",
            "requested_source_id": exact_source,
            "fallback_order": [],
            "actionable_fallback_order": [],
            "reference_candidate_ids": [],
            "quality_rule": "transport priority never overrides underlying-source evidence quality",
        }
    candidates = []
    for spec in _SOURCES:
        if (
            source_policy == "strict"
            and exact_source
            and spec.source_id != exact_source
        ):
            continue
        if data_kind not in spec.data_kinds:
            continue
        if asset_class and asset_class not in spec.asset_classes:
            continue
        if region and spec.region not in {region, "GLOBAL"}:
            continue
        candidates.append(spec)
    candidates.sort(
        key=lambda spec: (
            0 if exact_source and spec.source_id == exact_source else 1,
            0 if region and spec.region == region else 1,
            0 if spec.access == "keyless" else 1,
            spec.default_priority,
            spec.source_id,
        )
    )
    actionable = [spec for spec in candidates if not spec.reference_only]
    reference_candidates = [spec for spec in candidates if spec.reference_only]
    gap = ""
    if source_policy == "strict" and exact_source and not candidates:
        gap = "requested_source_unavailable"
    elif data_kind in EXCHANGE_PRICE_KINDS and not actionable:
        gap = "official_price_unavailable"
    elif not candidates:
        gap = "official_source_unavailable"
    return {
        "schema_version": 1,
        "data_kind": data_kind,
        "asset_class": asset_class,
        "region": region,
        "source_policy": source_policy,
        "candidates": [_public_source(spec) for spec in candidates],
        "coverage_gap": gap,
        "requested_source_id": exact_source,
        "fallback_order": [spec.source_id for spec in candidates],
        "actionable_fallback_order": [spec.source_id for spec in actionable],
        "reference_candidate_ids": [
            spec.source_id for spec in reference_candidates
        ],
        "quality_rule": "transport priority never overrides underlying-source evidence quality",
    }


def _public_source(spec: OfficialSourceSpec) -> dict[str, Any]:
    payload = asdict(spec)
    payload["credential_slots"] = list(spec.credential_slots)
    payload["data_kinds"] = list(spec.data_kinds)
    payload["asset_classes"] = list(spec.asset_classes)
    payload["credential_state"] = "not_required" if not spec.credential_slots else "configuration_required"
    return payload
