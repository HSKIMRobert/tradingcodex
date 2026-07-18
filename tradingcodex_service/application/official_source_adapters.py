from __future__ import annotations

import csv
import io
import json
import re
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from tradingcodex_service.application.common import stable_hash
from tradingcodex_service.application.official_sources import (
    EXCHANGE_PRICE_KINDS,
    get_official_source_plan,
)


MAX_OFFICIAL_RESULT_ROWS = 120
MAX_OFFICIAL_RESULT_CHARS = 20_000
MAX_OFFICIAL_HTTP_BODY_BYTES = 2 * 1024 * 1024
OFFICIAL_HTTP_TIMEOUT_SECONDS = 12.0
_ADAPTER_RESULT_TARGET_CHARS = 16_000
_SEC_USER_AGENT = (
    "TradingCodex/1.0 tradingcodex@users.noreply.github.com "
    "https://github.com/monarchjuno/tradingcodex"
)

OfficialSourceAdapter = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class OfficialHttpRequest:
    """One internally constructed, read-only request to a reviewed official host."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None
    timeout_seconds: float = OFFICIAL_HTTP_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class OfficialHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str = ""


OfficialHttpTransport = Callable[[OfficialHttpRequest], OfficialHttpResponse]


class OfficialSourceAuthError(RuntimeError):
    """An official source rejected the configured credential."""


class OfficialSourceEntitlementError(RuntimeError):
    """The credential is valid but cannot access the requested dataset."""


class OfficialSourceRateLimitError(RuntimeError):
    """The official source refused the bounded call because of a rate limit."""


class OfficialSourceTransientError(RuntimeError):
    """The transport failed before a usable official result was returned."""


class OfficialSourceCorrectableError(RuntimeError):
    """The bounded request is invalid and can be corrected without retrying it."""


class OfficialSourceEmptyError(RuntimeError):
    """The official source returned no matching observations."""


class OfficialSourceStaleError(RuntimeError):
    """The official source only returned observations before the requested window."""


class OfficialSourceTruncationError(RuntimeError):
    """The transport or normalized result exceeded a hard response boundary."""


class OfficialSourceUnsafeError(RuntimeError):
    """The request or redirect escaped the reviewed official-source boundary."""


class OfficialSourceConflictError(RuntimeError):
    """The official source returned a malformed or contradictory result."""


_OUTCOME_TO_RESULT_STATUS = {
    "complete_valid": "complete_valid",
    "partial_valid": "partial_valid",
    "correctable_error": "correctable_error",
    "auth_failed": "terminal_gap",
    "entitlement_failed": "terminal_gap",
    "empty": "terminal_gap",
    "stale": "terminal_gap",
    "rate_limited": "terminal_gap",
    "timeout": "terminal_gap",
    "truncated": "terminal_gap",
    "adapter_unavailable": "terminal_gap",
    "terminal_gap": "terminal_gap",
    "credential_unavailable": "approval_required",
    "approval_required": "approval_required",
    "unsafe": "unsafe",
    "transient": "transient",
    "conflict": "conflict",
    "adapter_error": "conflict",
    "reference_only_result": "partial_valid",
}


def execute_official_source_fallback(
    workspace_root: Any,
    request: dict[str, Any],
    *,
    adapters: Mapping[str, OfficialSourceAdapter] | None = None,
    credential_states: Mapping[str, str] | None = None,
    http_transport: OfficialHttpTransport | None = None,
) -> dict[str, Any]:
    """Execute one deterministic, sequential official-source fallback plan.

    Callers may inject adapters for deterministic testing. When omitted, the
    executor uses the reviewed keyless production registry with an injectable
    HTTP transport. This canonical executor never discovers providers, reads
    credentials, performs parallel calls, or retries a source. Each adapter
    receives the public source card and a shallow request copy and returns one
    bounded typed result.
    """

    plan = get_official_source_plan(workspace_root, request)
    active_adapters = (
        dict(adapters)
        if adapters is not None
        else production_official_source_adapters(http_transport=http_transport)
    )
    credentials = dict(credential_states or {})
    attempts: list[dict[str, Any]] = []
    accepted_results: list[dict[str, Any]] = []

    for ordinal, candidate in enumerate(plan["candidates"], start=1):
        source_id = candidate["source_id"]
        if candidate["credential_slots"]:
            credential_state = str(credentials.get(source_id) or "ref_missing")
            if credential_state != "available":
                attempt = _attempt(
                    candidate,
                    ordinal=ordinal,
                    outcome="credential_unavailable",
                    detail_code=credential_state,
                )
                attempts.append(attempt)
                if plan["source_policy"] == "strict":
                    break
                continue

        adapter = active_adapters.get(source_id)
        if adapter is None:
            attempts.append(
                _attempt(
                    candidate,
                    ordinal=ordinal,
                    outcome="adapter_unavailable",
                    detail_code="adapter_not_registered",
                )
            )
            if plan["source_policy"] == "strict":
                break
            continue

        response, outcome, detail_code = _call_adapter(adapter, candidate, request)
        if (
            candidate["reference_only"]
            and plan["data_kind"] in EXCHANGE_PRICE_KINDS
            and outcome == "complete_valid"
        ):
            outcome = "reference_only_result"
            detail_code = "not_executable_price_coverage"
        attempt = _attempt(
            candidate,
            ordinal=ordinal,
            outcome=outcome,
            detail_code=detail_code,
            response=response,
        )
        attempts.append(attempt)

        if outcome in {"complete_valid", "partial_valid", "reference_only_result"}:
            accepted_results.append(
                {
                    "source_id": source_id,
                    "result_status": attempt["result_status"],
                    "reference_only": bool(candidate["reference_only"]),
                    "row_count": attempt["row_count"],
                    "result_hash": attempt["result_hash"],
                }
            )
        if outcome in {"complete_valid", "partial_valid", "reference_only_result"}:
            complete = outcome == "complete_valid"
            return _execution_result(
                plan,
                attempts,
                accepted_results,
                status="complete_valid" if complete else "partial_valid",
                selected_source_id=source_id,
                coverage_gap=(
                    ""
                    if complete
                    else str(plan.get("coverage_gap") or "partial_official_result")
                ),
                fallback_exhausted=False,
                record_external_data_result_args=_success_record_args(
                    candidate,
                    request,
                    response,
                    result_status=attempt["result_status"],
                    coverage_gap=(
                        ""
                        if complete
                        else str(plan.get("coverage_gap") or "partial_official_result")
                    ),
                ),
            )
        if plan["source_policy"] == "strict":
            break

    if accepted_results:
        status = "partial_valid"
    elif attempts and all(
        attempt["result_status"] == "approval_required" for attempt in attempts
    ):
        status = "approval_required"
    elif attempts and all(
        attempt["result_status"] == "transient" for attempt in attempts
    ):
        status = "transient"
    else:
        status = "terminal_gap"
    gap = str(plan.get("coverage_gap") or "")
    if not gap:
        gap = (
            "official_price_unavailable"
            if plan["data_kind"] in EXCHANGE_PRICE_KINDS
            else "official_fallback_exhausted"
        )
    return _execution_result(
        plan,
        attempts,
        accepted_results,
        status=status,
        selected_source_id="",
        coverage_gap=gap,
        fallback_exhausted=bool(plan["candidates"]),
        record_external_data_result_args=_failure_record_args(
            plan,
            request,
            attempts,
            result_status=status,
            coverage_gap=gap,
        ),
    )


def _call_adapter(
    adapter: OfficialSourceAdapter,
    candidate: dict[str, Any],
    request: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    try:
        raw = adapter(dict(candidate), dict(request))
    except OfficialSourceAuthError:
        return {}, "auth_failed", "credential_rejected"
    except OfficialSourceEntitlementError:
        return {}, "entitlement_failed", "dataset_not_entitled"
    except OfficialSourceRateLimitError:
        return {}, "rate_limited", "rate_limit_observed"
    except OfficialSourceCorrectableError:
        return {}, "correctable_error", "request_contract_invalid"
    except OfficialSourceEmptyError:
        return {}, "empty", "no_matching_records"
    except OfficialSourceStaleError:
        return {}, "stale", "only_stale_records"
    except OfficialSourceTruncationError:
        return {}, "truncated", "bounded_result_exceeded"
    except OfficialSourceUnsafeError:
        return {}, "unsafe", "official_boundary_rejected"
    except OfficialSourceConflictError:
        return {}, "conflict", "malformed_official_result"
    except TimeoutError:
        return {}, "timeout", "transport_timeout"
    except (OfficialSourceTransientError, ConnectionError):
        return {}, "transient", "transport_unavailable"
    except Exception:
        # Adapter exception bodies can contain headers, URLs, or credential
        # values. Preserve only a fixed classification outside the adapter.
        return {}, "adapter_error", "unclassified_adapter_exception"

    if not isinstance(raw, dict):
        return {}, "conflict", "adapter_result_not_object"
    response = dict(raw)
    outcome = str(response.pop("outcome", response.pop("status", ""))).strip()
    if outcome not in _OUTCOME_TO_RESULT_STATUS:
        return {}, "conflict", "unknown_adapter_outcome"
    if response.get("stale") is True and outcome in {
        "complete_valid",
        "partial_valid",
    }:
        return {}, "stale", "adapter_marked_stale"
    rows = response.get("rows")
    if rows is not None:
        if not isinstance(rows, list):
            return {}, "conflict", "rows_not_array"
        if len(rows) > MAX_OFFICIAL_RESULT_ROWS:
            return {}, "truncated", "row_limit_exceeded"
    if outcome in {"complete_valid", "partial_valid"} and not _has_data(response):
        return {}, "empty", "no_usable_records"
    try:
        rendered = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return {}, "conflict", "result_not_canonical_json"
    if len(rendered) > MAX_OFFICIAL_RESULT_CHARS:
        return {}, "truncated", "result_character_limit_exceeded"
    return response, outcome, "adapter_reported"


def _has_data(response: dict[str, Any]) -> bool:
    for field in ("rows", "records"):
        value = response.get(field)
        if isinstance(value, list) and value:
            return True
    payload = response.get("payload")
    return payload not in (None, "", [], {})


def fetch_official_source_data(
    workspace_root: Any,
    request: dict[str, Any],
    *,
    http_transport: OfficialHttpTransport | None = None,
) -> dict[str, Any]:
    """Fetch one bounded, sequential vanilla TradingCodex official-source plan.

    The public service deliberately has no URL, header, credential, HTTP method,
    or request-body override. Free-key sources remain configuration gaps; only
    the reviewed keyless registry can perform production calls here.
    """

    _validate_public_fetch_request(request)
    return execute_official_source_fallback(
        workspace_root,
        request,
        http_transport=http_transport,
    )


def production_official_source_adapters(
    *,
    http_transport: OfficialHttpTransport | None = None,
) -> dict[str, OfficialSourceAdapter]:
    """Return the fixed production adapter registry for reviewed keyless sources."""

    transport = http_transport or _urllib_http_transport
    return {
        "sec-edgar": lambda source, request: _fetch_sec_edgar(
            transport, source, request
        ),
        "us-treasury-daily-rates": lambda source, request: _fetch_us_treasury(
            transport, source, request
        ),
        "bls-v1": lambda source, request: _fetch_bls_v1(
            transport, source, request
        ),
        "ecb-data-api": lambda source, request: _fetch_ecb(
            transport, source, request
        ),
        "world-bank-indicators": lambda source, request: _fetch_world_bank(
            transport, source, request
        ),
        "cftc-cot": lambda source, request: _fetch_cftc_cot(
            transport, source, request
        ),
        "bank-of-canada-valet": lambda source, request: _fetch_bank_of_canada(
            transport, source, request
        ),
    }


class _SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        original_host = (urlsplit(req.full_url).hostname or "").casefold()
        redirected_host = (urlsplit(newurl).hostname or "").casefold()
        if not original_host or redirected_host != original_host:
            raise OfficialSourceUnsafeError("cross-host redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_public_fetch_request(request: Any) -> None:
    if not isinstance(request, dict):
        raise ValueError("official fetch request must be an object")
    allowed = {
        "data_kind",
        "asset_class",
        "region",
        "source_id",
        "source_policy",
        "identifiers",
        "fields",
        "period_start",
        "period_end",
        "as_of",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise ValueError(
            "official fetch request does not allow additional properties: "
            + ", ".join(unknown)
        )
    identifiers = request.get("identifiers")
    if not isinstance(identifiers, list) or not (1 <= len(identifiers) <= 5):
        raise ValueError("official fetch identifiers must contain between 1 and 5 items")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 160 for item in identifiers):
        raise ValueError("official fetch identifier is invalid")
    fields = request.get("fields")
    if fields is not None and (
        not isinstance(fields, list)
        or len(fields) > 40
        or any(not isinstance(item, str) or len(item) > 64 for item in fields)
    ):
        raise ValueError("official fetch fields are invalid")
    for name in (
        "data_kind",
        "asset_class",
        "region",
        "source_id",
        "source_policy",
        "period_start",
        "period_end",
        "as_of",
    ):
        value = request.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > 64):
            raise ValueError(f"official fetch {name} is invalid")


def _urllib_http_transport(request: OfficialHttpRequest) -> OfficialHttpResponse:
    parsed = urlsplit(request.url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise OfficialSourceUnsafeError("official request must use a fixed HTTPS host")
    if request.method not in {"GET", "POST"}:
        raise OfficialSourceUnsafeError("official request method is not read-only")
    req = urllib.request.Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method=request.method,
    )
    opener = urllib.request.build_opener(_SameHostRedirectHandler())
    try:
        with opener.open(req, timeout=request.timeout_seconds) as response:
            body = response.read(MAX_OFFICIAL_HTTP_BODY_BYTES + 1)
            if len(body) > MAX_OFFICIAL_HTTP_BODY_BYTES:
                raise OfficialSourceTruncationError("official response body exceeded cap")
            return OfficialHttpResponse(
                status_code=int(response.status),
                headers={},
                body=body,
                final_url=str(response.geturl() or request.url),
            )
    except urllib.error.HTTPError as exc:
        # Never read or expose the error body: official gateways can echo URLs,
        # headers, tokens, or verbose upstream diagnostics.
        return OfficialHttpResponse(
            status_code=int(exc.code),
            headers={},
            body=b"",
            final_url=str(exc.geturl() or request.url),
        )
    except (TimeoutError, socket.timeout) as exc:
        raise TimeoutError("official transport timeout") from exc
    except OfficialSourceTruncationError:
        raise
    except OfficialSourceUnsafeError:
        raise
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        raise OfficialSourceTransientError("official transport unavailable") from exc


def _perform_http(
    transport: OfficialHttpTransport,
    *,
    method: str,
    url: str,
    expected_host: str,
    accept: str,
    body: bytes | None = None,
    content_type: str = "",
    sec_identity: bool = False,
) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != expected_host.casefold()
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise OfficialSourceUnsafeError("official request escaped its fixed host")
    headers = {
        "Accept": accept,
        "User-Agent": _SEC_USER_AGENT if sec_identity else "TradingCodex/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    response = transport(
        OfficialHttpRequest(
            method=method,
            url=url,
            headers=headers,
            body=body,
        )
    )
    if not isinstance(response, OfficialHttpResponse):
        raise OfficialSourceConflictError("transport returned an invalid response")
    final_url = response.final_url or url
    final = urlsplit(final_url)
    if (
        final.scheme != "https"
        or (final.hostname or "").casefold() != expected_host.casefold()
        or final.username
        or final.password
    ):
        raise OfficialSourceUnsafeError("official response escaped its fixed host")
    status = int(response.status_code)
    if status in {401}:
        raise OfficialSourceAuthError("official source rejected authentication")
    if status in {403}:
        raise OfficialSourceEntitlementError("official source denied access")
    if status == 429:
        raise OfficialSourceRateLimitError("official source rate limited the call")
    if status in {408, 504}:
        raise TimeoutError("official source timed out")
    if status == 204 or status == 404:
        raise OfficialSourceEmptyError("official source returned no record")
    if status in {400, 409, 422}:
        raise OfficialSourceCorrectableError("official source rejected the query")
    if status >= 500:
        raise OfficialSourceTransientError("official source unavailable")
    if status < 200 or status >= 300:
        raise OfficialSourceConflictError("unexpected official HTTP status")
    if len(response.body) > MAX_OFFICIAL_HTTP_BODY_BYTES:
        raise OfficialSourceTruncationError("official response body exceeded cap")
    if not response.body:
        raise OfficialSourceEmptyError("official source returned an empty body")
    return response.body


def _json_body(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialSourceConflictError("official response is not valid JSON") from exc


def _request_identifiers(
    request: dict[str, Any],
    *,
    minimum: int = 1,
    maximum: int = 1,
) -> list[str]:
    raw = request.get("identifiers")
    if not isinstance(raw, list) or not (minimum <= len(raw) <= maximum):
        raise OfficialSourceCorrectableError("exact identifiers are required")
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if not value or len(value) > 160 or any(ord(char) < 32 for char in value):
            raise OfficialSourceCorrectableError("identifier is invalid")
        folded = value.casefold()
        if folded in seen:
            raise OfficialSourceCorrectableError("identifiers must be unique")
        result.append(value)
        seen.add(folded)
    return result


def _request_fields(request: dict[str, Any]) -> list[str]:
    raw = request.get("fields")
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > 40:
        raise OfficialSourceCorrectableError("fields must be a bounded array")
    fields: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) is None:
            raise OfficialSourceCorrectableError("field name is invalid")
        if name not in fields:
            fields.append(name)
    return fields


def _request_dates(
    request: dict[str, Any],
    *,
    period_required: bool = False,
) -> tuple[date | None, date]:
    start_raw = str(request.get("period_start") or "").strip()
    end_raw = str(request.get("period_end") or "").strip()
    as_of_raw = str(request.get("as_of") or "").strip()
    if bool(start_raw) != bool(end_raw):
        raise OfficialSourceCorrectableError("period_start and period_end must be paired")
    if period_required and not start_raw:
        raise OfficialSourceCorrectableError("this source requires a bounded period")
    if start_raw:
        start = _parse_date(start_raw)
        end = _parse_date(end_raw)
        if start > end:
            raise OfficialSourceCorrectableError("period_start is after period_end")
        if as_of_raw and end > _parse_date(as_of_raw):
            raise OfficialSourceCorrectableError("period_end is after as_of")
        return start, end
    if not as_of_raw:
        raise OfficialSourceCorrectableError("as_of or a complete period is required")
    return None, _parse_date(as_of_raw)


def _parse_date(value: str) -> date:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfficialSourceCorrectableError("date must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise OfficialSourceCorrectableError("datetime bounds require a timezone")
    return parsed.astimezone(timezone.utc).date()


def _project_rows(
    rows: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    mandatory: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not rows:
        raise OfficialSourceEmptyError("official source returned no matching rows")
    available = set().union(*(row.keys() for row in rows))
    requested = _request_fields(request)
    unknown = [field for field in requested if field not in available]
    if unknown:
        raise OfficialSourceCorrectableError("requested field is unavailable")
    selected = list(dict.fromkeys((*mandatory, *requested))) if requested else sorted(available)
    return [
        {name: _bounded_cell(row.get(name)) for name in selected if name in row}
        for row in rows
    ]


def _bounded_cell(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        rendered = str(value)
    rendered = rendered.replace("\x00", "").strip()
    return rendered[:1_000]


def _columns_for_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = sorted(set().union(*(row.keys() for row in rows)))
    columns: list[dict[str, Any]] = []
    for name in names:
        values = [row.get(name) for row in rows if row.get(name) is not None]
        if values and all(type(value) is bool for value in values):
            type_name = "bool"
        elif values and all(type(value) is int for value in values):
            type_name = "int64"
        elif values and all(type(value) in {int, float} and type(value) is not bool for value in values):
            type_name = "float64"
        elif values and all(
            isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
            for value in values
        ):
            type_name = "date32"
        else:
            type_name = "string"
        columns.append(
            {
                "name": name,
                "type": type_name,
                "nullable": any(name not in row or row.get(name) is None for row in rows),
            }
        )
    return columns


def _adapter_result(
    *,
    source_id: str,
    route: str,
    provider_query: dict[str, Any],
    rows: list[dict[str, Any]],
    request: dict[str, Any],
    mandatory: tuple[str, ...],
    reference_only: bool = False,
) -> dict[str, Any]:
    requested_identifiers = _request_identifiers(request, maximum=5)
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        if len(requested_identifiers) == 1:
            normalized["identifier"] = requested_identifiers[0]
        else:
            series_id = str(normalized.get("series_id") or "")
            if series_id not in requested_identifiers:
                raise OfficialSourceConflictError(
                    "official source row cannot bind a requested identifier"
                )
            normalized["identifier"] = series_id
        normalized_rows.append(normalized)
    projected = _project_rows(
        normalized_rows,
        request,
        mandatory=("identifier", *mandatory),
    )
    if len(projected) > MAX_OFFICIAL_RESULT_ROWS:
        raise OfficialSourceTruncationError("official row limit exceeded")
    result = {
        "outcome": "complete_valid",
        "rows": projected,
        "columns": _columns_for_rows(projected),
        "requested_provider": source_id,
        "returned_provider": source_id,
        "upstream_provider": source_id,
        "route": route,
        "provider_query": provider_query,
        "timezone": "UTC",
        "returned_adjustment_policy": "not_applicable",
        "reference_only": reference_only,
    }
    try:
        rendered = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OfficialSourceConflictError("official rows are not canonical JSON") from exc
    if len(rendered) > _ADAPTER_RESULT_TARGET_CHARS:
        raise OfficialSourceTruncationError("normalized official result exceeded cap")
    return result


def _fetch_sec_edgar(
    transport: OfficialHttpTransport,
    source: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    start, end = _request_dates(request, period_required=True)
    identifiers = _request_identifiers(request)
    data_kind = str(request.get("data_kind") or "").strip().lower()
    identifier = identifiers[0]
    if data_kind == "filing":
        match = re.fullmatch(r"(?:CIK)?(\d{1,10})", identifier, re.IGNORECASE)
        if match is None:
            raise OfficialSourceCorrectableError("SEC filing identifier must be a CIK")
        cik = match.group(1).zfill(10)
        route = f"https://data.sec.gov/submissions/CIK{cik}.json"
        payload = _json_body(
            _perform_http(
                transport,
                method="GET",
                url=route,
                expected_host="data.sec.gov",
                accept="application/json",
                sec_identity=True,
            )
        )
        rows = _sec_filing_rows(payload, cik=cik, start=start, end=end)
        return _adapter_result(
            source_id="sec-edgar",
            route="https://data.sec.gov/submissions/CIK##########.json",
            provider_query={"cik": f"CIK{cik}", "period_start": start.isoformat(), "period_end": end.isoformat()},
            rows=rows,
            request=request,
            mandatory=("cik", "accession_number", "filing_date", "form"),
        )
    if data_kind != "fundamentals":
        raise OfficialSourceCorrectableError("SEC adapter supports filing or fundamentals")
    match = re.fullmatch(
        r"(?:CIK)?(\d{1,10})/([A-Za-z][A-Za-z0-9-]{0,31})/([A-Za-z][A-Za-z0-9]{0,127})",
        identifier,
        re.IGNORECASE,
    )
    if match is None:
        raise OfficialSourceCorrectableError(
            "SEC fundamentals identifier must be CIK/taxonomy/concept"
        )
    cik = match.group(1).zfill(10)
    taxonomy = match.group(2)
    concept = match.group(3)
    route = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    payload = _json_body(
        _perform_http(
            transport,
            method="GET",
            url=route,
            expected_host="data.sec.gov",
            accept="application/json",
            sec_identity=True,
        )
    )
    rows = _sec_company_fact_rows(
        payload,
        cik=cik,
        taxonomy=taxonomy,
        concept=concept,
        start=start,
        end=end,
    )
    return _adapter_result(
        source_id="sec-edgar",
        route="https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json",
        provider_query={
            "cik": f"CIK{cik}",
            "taxonomy": taxonomy,
            "concept": concept,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        rows=rows,
        request=request,
        mandatory=("cik", "taxonomy", "concept", "unit", "value", "end", "filed", "accession_number"),
    )


def _sec_filing_rows(
    payload: Any,
    *,
    cik: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise OfficialSourceConflictError("SEC submissions response is not an object")
    recent = payload.get("filings", {}).get("recent")
    if not isinstance(recent, dict):
        raise OfficialSourceConflictError("SEC submissions response lacks recent filings")
    columns = {
        "accession_number": recent.get("accessionNumber"),
        "filing_date": recent.get("filingDate"),
        "report_date": recent.get("reportDate"),
        "acceptance_datetime": recent.get("acceptanceDateTime"),
        "form": recent.get("form"),
        "primary_document": recent.get("primaryDocument"),
        "primary_doc_description": recent.get("primaryDocDescription"),
        "is_xbrl": recent.get("isXBRL"),
        "is_inline_xbrl": recent.get("isInlineXBRL"),
    }
    required = columns["accession_number"], columns["filing_date"], columns["form"]
    if any(not isinstance(value, list) for value in required):
        raise OfficialSourceConflictError("SEC recent filing arrays are malformed")
    count = min(len(value) for value in required if isinstance(value, list))
    rows: list[dict[str, Any]] = []
    for index in range(count):
        filing_date = _safe_date_value(columns["filing_date"][index])
        if filing_date is None or not (start <= filing_date <= end):
            continue
        row = {
            "cik": f"CIK{cik}",
            "entity_name": payload.get("name"),
        }
        for name, values in columns.items():
            row[name] = values[index] if isinstance(values, list) and index < len(values) else None
        rows.append(row)
    if not rows:
        available_dates = [
            item
            for item in (_safe_date_value(value) for value in columns["filing_date"])
            if item is not None
        ]
        if available_dates and max(available_dates) < start:
            raise OfficialSourceStaleError("SEC only returned filings before the requested period")
        raise OfficialSourceEmptyError("SEC returned no filings in the requested period")
    return rows


def _sec_company_fact_rows(
    payload: Any,
    *,
    cik: str,
    taxonomy: str,
    concept: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise OfficialSourceConflictError("SEC companyfacts response is not an object")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise OfficialSourceConflictError("SEC companyfacts response lacks facts")
    taxonomy_payload = next(
        (value for key, value in facts.items() if str(key).casefold() == taxonomy.casefold()),
        None,
    )
    if not isinstance(taxonomy_payload, dict):
        raise OfficialSourceEmptyError("SEC taxonomy is unavailable")
    fact = next(
        (value for key, value in taxonomy_payload.items() if str(key).casefold() == concept.casefold()),
        None,
    )
    if not isinstance(fact, dict) or not isinstance(fact.get("units"), dict):
        raise OfficialSourceEmptyError("SEC concept is unavailable")
    rows: list[dict[str, Any]] = []
    for unit, observations in fact["units"].items():
        if not isinstance(observations, list):
            continue
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            observation_end = _safe_date_value(observation.get("end"))
            filed = _safe_date_value(observation.get("filed"))
            if observation_end is None or filed is None or not (start <= filed <= end):
                continue
            rows.append(
                {
                    "cik": f"CIK{cik}",
                    "entity_name": payload.get("entityName"),
                    "taxonomy": taxonomy,
                    "concept": concept,
                    "label": fact.get("label"),
                    "unit": unit,
                    "value": observation.get("val"),
                    "start": observation.get("start"),
                    "end": observation.get("end"),
                    "filed": observation.get("filed"),
                    "form": observation.get("form"),
                    "fiscal_year": observation.get("fy"),
                    "fiscal_period": observation.get("fp"),
                    "frame": observation.get("frame"),
                    "accession_number": observation.get("accn"),
                }
            )
    rows.sort(key=lambda row: (str(row.get("filed") or ""), str(row.get("accession_number") or "")), reverse=True)
    if not rows:
        raise OfficialSourceEmptyError("SEC returned no concept facts in the requested period")
    return rows


def _safe_date_value(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _fetch_bls_v1(
    transport: OfficialHttpTransport,
    source: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    del source
    start, end = _request_dates(request)
    start_year = (start or end).year
    end_year = end.year
    identifiers = _request_identifiers(request, maximum=5)
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{2,49}", item) is None for item in identifiers):
        raise OfficialSourceCorrectableError("BLS identifiers must be exact series ids")
    year_count = end_year - start_year + 1
    if year_count > 10 or year_count * len(identifiers) * 12 > MAX_OFFICIAL_RESULT_ROWS:
        raise OfficialSourceCorrectableError("BLS request can exceed the 120-row contract")
    body = json.dumps(
        {"seriesid": identifiers, "startyear": str(start_year), "endyear": str(end_year)},
        separators=(",", ":"),
    ).encode("utf-8")
    route = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
    payload = _json_body(
        _perform_http(
            transport,
            method="POST",
            url=route,
            expected_host="api.bls.gov",
            accept="application/json",
            body=body,
            content_type="application/json",
        )
    )
    if not isinstance(payload, dict) or str(payload.get("status") or "") != "REQUEST_SUCCEEDED":
        raise OfficialSourceConflictError("BLS response did not report success")
    series = payload.get("Results", {}).get("series")
    if not isinstance(series, list):
        raise OfficialSourceConflictError("BLS response lacks series data")
    rows: list[dict[str, Any]] = []
    for item in series:
        if not isinstance(item, dict) or not isinstance(item.get("data"), list):
            continue
        series_id = str(item.get("seriesID") or "")
        if series_id not in identifiers:
            raise OfficialSourceConflictError("BLS returned an unrequested series")
        for observation in item["data"]:
            if not isinstance(observation, dict):
                continue
            rows.append(
                {
                    "series_id": series_id,
                    "year": observation.get("year"),
                    "period": observation.get("period"),
                    "period_name": observation.get("periodName"),
                    "value": observation.get("value"),
                    "latest": observation.get("latest"),
                }
            )
    return _adapter_result(
        source_id="bls-v1",
        route=route,
        provider_query={"series_ids": identifiers, "start_year": start_year, "end_year": end_year},
        rows=rows,
        request=request,
        mandatory=("series_id", "year", "period", "value"),
    )


def _fetch_world_bank(
    transport: OfficialHttpTransport,
    source: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    del source
    start, end = _request_dates(request)
    identifier = _request_identifiers(request)[0]
    match = re.fullmatch(r"([A-Za-z0-9]{2,3}):([A-Za-z][A-Za-z0-9_.-]{1,79})", identifier)
    if match is None:
        raise OfficialSourceCorrectableError("World Bank identifier must be COUNTRY:INDICATOR")
    country = match.group(1).upper()
    indicator = match.group(2)
    start_year = (start or end).year
    end_year = end.year
    if end_year - start_year + 1 > MAX_OFFICIAL_RESULT_ROWS:
        raise OfficialSourceCorrectableError("World Bank period can exceed 120 observations")
    query = urlencode(
        {
            "date": f"{start_year}:{end_year}",
            "format": "json",
            "per_page": str(MAX_OFFICIAL_RESULT_ROWS),
        }
    )
    route = (
        f"https://api.worldbank.org/v2/country/{quote(country, safe='')}"
        f"/indicator/{quote(indicator, safe='')}?{query}"
    )
    payload = _json_body(
        _perform_http(
            transport,
            method="GET",
            url=route,
            expected_host="api.worldbank.org",
            accept="application/json",
        )
    )
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], dict):
        raise OfficialSourceConflictError("World Bank response is malformed")
    metadata = payload[0]
    if int(metadata.get("total") or 0) > MAX_OFFICIAL_RESULT_ROWS:
        raise OfficialSourceTruncationError("World Bank result requires pagination")
    observations = payload[1]
    if not isinstance(observations, list):
        raise OfficialSourceEmptyError("World Bank returned no observations")
    rows = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        returned_indicator = observation.get("indicator") or {}
        if isinstance(returned_indicator, dict) and returned_indicator.get("id") not in {None, indicator}:
            raise OfficialSourceConflictError("World Bank returned an unrequested indicator")
        rows.append(
            {
                "country_id": (observation.get("country") or {}).get("id") if isinstance(observation.get("country"), dict) else country,
                "country": (observation.get("country") or {}).get("value") if isinstance(observation.get("country"), dict) else None,
                "indicator_id": indicator,
                "indicator": returned_indicator.get("value") if isinstance(returned_indicator, dict) else None,
                "year": observation.get("date"),
                "value": observation.get("value"),
                "unit": observation.get("unit"),
                "observation_status": observation.get("obs_status"),
                "decimal": observation.get("decimal"),
            }
        )
    return _adapter_result(
        source_id="world-bank-indicators",
        route="https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
        provider_query={"country": country, "indicator": indicator, "start_year": start_year, "end_year": end_year},
        rows=rows,
        request=request,
        mandatory=("country_id", "indicator_id", "year", "value"),
    )


_TREASURY_SERIES = {
    "daily_treasury_yield_curve": "daily_treasury_yield_curve",
    "daily_treasury_real_yield_curve": "daily_treasury_real_yield_curve",
    "daily_treasury_bill_rates": "daily_treasury_bill_rates",
    "daily_treasury_long_term_rate": "daily_treasury_long_term_rate",
}


def _fetch_us_treasury(
    transport: OfficialHttpTransport,
    source: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    del source
    start, end = _request_dates(request, period_required=True)
    identifier = _request_identifiers(request)[0].lower()
    series = _TREASURY_SERIES.get(identifier)
    if series is None:
        raise OfficialSourceCorrectableError("Treasury series identifier is unsupported")
    if start.year != end.year or (end - start).days > 120:
        raise OfficialSourceCorrectableError(
            "Treasury requests must stay within one year and 120 calendar days"
        )
    query = urlencode({"type": series, "field_tdr_date_value": str(end.year)})
    route = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?"
        + query
    )
    body = _perform_http(
        transport,
        method="GET",
        url=route,
        expected_host="home.treasury.gov",
        accept="application/atom+xml,application/xml,text/xml",
    )
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise OfficialSourceConflictError("Treasury response is not valid XML") from exc
    rows: list[dict[str, Any]] = []
    for entry in root.iter():
        if _local_xml_name(entry.tag).casefold() != "properties":
            continue
        row: dict[str, Any] = {}
        for item in list(entry):
            name = _safe_column_name(_local_xml_name(item.tag))
            value = str(item.text or "").strip()
            if name in {"new_date", "date"} and len(value) >= 10:
                value = value[:10]
            row[name] = value or None
        row_date = _safe_date_value(row.get("new_date") or row.get("date"))
        if row_date is not None and start <= row_date <= end:
            rows.append(row)
    return _adapter_result(
        source_id="us-treasury-daily-rates",
        route="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
        provider_query={"series_id": series, "year": end.year, "period_start": start.isoformat(), "period_end": end.isoformat()},
        rows=rows,
        request=request,
        mandatory=("new_date",),
        reference_only=True,
    )


def _local_xml_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].split(":")[-1]


def _safe_column_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    if not normalized or not normalized[0].isalpha():
        normalized = "field_" + normalized
    return normalized[:64]


def _fetch_ecb(
    transport: OfficialHttpTransport,
    source: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    del source
    start, end = _request_dates(request, period_required=True)
    identifier = _request_identifiers(request)[0]
    match = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9_-]{0,31})/([A-Za-z0-9][A-Za-z0-9._-]{0,159})",
        identifier,
    )
    if match is None:
        raise OfficialSourceCorrectableError("ECB identifier must be FLOW/SERIES_KEY")
    flow, key = match.groups()
    query = urlencode(
        {
            "startPeriod": start.isoformat(),
            "endPeriod": end.isoformat(),
            "format": "csvdata",
            "detail": "dataonly",
        }
    )
    route = (
        f"https://data-api.ecb.europa.eu/service/data/{quote(flow, safe='')}"
        f"/{quote(key, safe='.-_')}?{query}"
    )
    body = _perform_http(
        transport,
        method="GET",
        url=route,
        expected_host="data-api.ecb.europa.eu",
        accept="text/csv",
    )
    try:
        reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        raw_rows = [dict(row) for row in reader]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise OfficialSourceConflictError("ECB response is not valid CSV") from exc
    selected_names = {
        "KEY",
        "FREQ",
        "CURRENCY",
        "CURRENCY_DENOM",
        "EXR_TYPE",
        "EXR_SUFFIX",
        "TIME_PERIOD",
        "OBS_VALUE",
        "OBS_STATUS",
        "UNIT",
        "UNIT_MULT",
        "DECIMALS",
    }
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        row = {
            _safe_column_name(name): value
            for name, value in raw.items()
            if name and name.upper() in selected_names
        }
        if row:
            rows.append(row)
    returned_keys = {str(row.get("key") or key) for row in rows}
    if len(returned_keys) > 1 or (returned_keys and key not in returned_keys):
        raise OfficialSourceConflictError("ECB returned an unrequested series")
    return _adapter_result(
        source_id="ecb-data-api",
        route="https://data-api.ecb.europa.eu/service/data/{flow}/{series_key}",
        provider_query={"flow": flow, "series_key": key, "period_start": start.isoformat(), "period_end": end.isoformat()},
        rows=rows,
        request=request,
        mandatory=("time_period", "obs_value"),
        reference_only=True,
    )


_CFTC_DATASETS = frozenset({"72hh-3qpy"})


def _fetch_cftc_cot(
    transport: OfficialHttpTransport,
    source: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    del source
    start, end = _request_dates(request, period_required=True)
    identifier = _request_identifiers(request)[0]
    match = re.fullmatch(r"([a-z0-9]{4}-[a-z0-9]{4})/([A-Za-z0-9]{1,20})", identifier)
    if match is None or match.group(1) not in _CFTC_DATASETS:
        raise OfficialSourceCorrectableError(
            "CFTC identifier must be a reviewed DATASET/CONTRACT_MARKET_CODE"
        )
    dataset_id, contract_code = match.groups()
    where = (
        f"cftc_contract_market_code='{contract_code}' AND "
        f"report_date_as_yyyy_mm_dd between '{start.isoformat()}T00:00:00.000' "
        f"and '{end.isoformat()}T23:59:59.999'"
    )
    query = urlencode(
        {
            "$limit": str(MAX_OFFICIAL_RESULT_ROWS + 1),
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$where": where,
        }
    )
    route = f"https://publicreporting.cftc.gov/resource/{dataset_id}.json?{query}"
    payload = _json_body(
        _perform_http(
            transport,
            method="GET",
            url=route,
            expected_host="publicreporting.cftc.gov",
            accept="application/json",
        )
    )
    if not isinstance(payload, list):
        raise OfficialSourceConflictError("CFTC response is not an array")
    if len(payload) > MAX_OFFICIAL_RESULT_ROWS:
        raise OfficialSourceTruncationError("CFTC result requires a narrower period")
    allowed_fields = (
        "report_date_as_yyyy_mm_dd",
        "market_and_exchange_names",
        "cftc_contract_market_code",
        "open_interest_all",
        "prod_merc_positions_long",
        "prod_merc_positions_short",
        "swap_positions_long_all",
        "swap__positions_short_all",
        "m_money_positions_long_all",
        "m_money_positions_short_all",
        "other_rept_positions_long",
        "other_rept_positions_short",
    )
    rows = [
        {name: item.get(name) for name in allowed_fields if name in item}
        for item in payload
        if isinstance(item, dict)
    ]
    for row in rows:
        returned_code = str(row.get("cftc_contract_market_code") or "")
        if returned_code and returned_code != contract_code:
            raise OfficialSourceConflictError("CFTC returned an unrequested contract")
        report_date = str(row.get("report_date_as_yyyy_mm_dd") or "")
        if len(report_date) >= 10:
            row["report_date_as_yyyy_mm_dd"] = report_date[:10]
    return _adapter_result(
        source_id="cftc-cot",
        route="https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
        provider_query={"dataset_id": dataset_id, "contract_market_code": contract_code, "period_start": start.isoformat(), "period_end": end.isoformat()},
        rows=rows,
        request=request,
        mandatory=("report_date_as_yyyy_mm_dd", "cftc_contract_market_code"),
        reference_only=True,
    )


def _fetch_bank_of_canada(
    transport: OfficialHttpTransport,
    source: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    del source
    start, end = _request_dates(request, period_required=True)
    series_id = _request_identifiers(request)[0]
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", series_id) is None:
        raise OfficialSourceCorrectableError("Bank of Canada identifier must be a series id")
    query = urlencode({"start_date": start.isoformat(), "end_date": end.isoformat()})
    route = (
        f"https://www.bankofcanada.ca/valet/observations/{quote(series_id, safe='.-_')}"
        f"/json?{query}"
    )
    payload = _json_body(
        _perform_http(
            transport,
            method="GET",
            url=route,
            expected_host="www.bankofcanada.ca",
            accept="application/json",
        )
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise OfficialSourceConflictError("Bank of Canada response lacks observations")
    rows: list[dict[str, Any]] = []
    for observation in payload["observations"]:
        if not isinstance(observation, dict):
            continue
        value = observation.get(series_id)
        if not isinstance(value, dict):
            continue
        rows.append(
            {
                "series_id": series_id,
                "observation_date": observation.get("d"),
                "value": value.get("v"),
            }
        )
    return _adapter_result(
        source_id="bank-of-canada-valet",
        route="https://www.bankofcanada.ca/valet/observations/{series_id}/json",
        provider_query={"series_id": series_id, "period_start": start.isoformat(), "period_end": end.isoformat()},
        rows=rows,
        request=request,
        mandatory=("series_id", "observation_date", "value"),
        reference_only=True,
    )


def _attempt(
    candidate: dict[str, Any],
    *,
    ordinal: int,
    outcome: str,
    detail_code: str,
    response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bounded_response = response or {}
    rows = bounded_response.get("rows")
    records = bounded_response.get("records")
    row_count = (
        len(rows)
        if isinstance(rows, list)
        else len(records)
        if isinstance(records, list)
        else 0
    )
    return {
        "ordinal": ordinal,
        "source_id": candidate["source_id"],
        "outcome": outcome,
        "result_status": _OUTCOME_TO_RESULT_STATUS[outcome],
        "detail_code": detail_code,
        "reference_only": bool(candidate["reference_only"]),
        "evidence_grade_ceiling": candidate["evidence_grade_ceiling"],
        "row_count": row_count,
        "result_hash": stable_hash(bounded_response),
        "retry_same_call": False,
    }


def _common_provider_query(request: dict[str, Any], provider: str) -> dict[str, Any]:
    query: dict[str, Any] = {
        "provider": provider,
        "identifiers": list(request.get("identifiers") or []),
    }
    for field in ("fields", "period_start", "period_end", "as_of"):
        value = request.get(field)
        if value not in (None, "", []):
            query[field] = value
    return query


def _success_record_args(
    candidate: dict[str, Any],
    request: dict[str, Any],
    response: dict[str, Any],
    *,
    result_status: str,
    coverage_gap: str,
) -> dict[str, Any]:
    source_id = str(candidate["source_id"])
    provider_query = dict(response.get("provider_query") or {})
    provider_query["provider"] = source_id
    rows = response.get("rows")
    if rows is None:
        rows = response.get("records")
    bounded_rows = list(rows) if isinstance(rows, list) else []
    columns = response.get("columns")
    if not isinstance(columns, list) and bounded_rows:
        columns = _columns_for_rows(bounded_rows)
    result = {
        "source_tier": "tradingcodex",
        "transport": "tradingcodex-official",
        "requested_provider": source_id,
        "returned_provider": source_id,
        "upstream_provider": source_id,
        "tool_name": "mcp__tradingcodex__fetch_official_source_data",
        "route": str(response.get("route") or candidate["route"]),
        "returned_adjustment_policy": str(
            response.get("returned_adjustment_policy") or "not_applicable"
        ),
        "result_status": result_status,
        "fallback_reason": "",
        "evidence_grade": str(candidate["evidence_grade_ceiling"]),
        "provider_query": provider_query,
        "source_category": str(request.get("data_kind") or "official_data"),
        "source_locator": str(response.get("route") or candidate["route"]),
        "timezone": str(response.get("timezone") or "UTC"),
        "coverage_note": coverage_gap or str(candidate.get("coverage_note") or ""),
        "warnings": list(response.get("warnings") or []),
        "rows": bounded_rows,
        "columns": columns or [],
        "data_classification": "public",
        "redistribution": "not_specified",
    }
    for field in ("missing_fields", "missing_identifiers", "missing_periods"):
        if response.get(field) not in (None, []):
            result[field] = response[field]
    return result


def _failure_record_args(
    plan: dict[str, Any],
    request: dict[str, Any],
    attempts: list[dict[str, Any]],
    *,
    result_status: str,
    coverage_gap: str,
) -> dict[str, Any]:
    final_attempt = attempts[-1] if attempts else {}
    provider = str(
        final_attempt.get("source_id")
        or plan.get("requested_source_id")
        or "tradingcodex-official-gap"
    )
    candidate = next(
        (
            item
            for item in plan.get("candidates", [])
            if item.get("source_id") == provider
        ),
        {},
    )
    route = str(candidate.get("route") or "tradingcodex:official-source-plan")
    detail = str(final_attempt.get("detail_code") or coverage_gap or result_status)
    return {
        "source_tier": "tradingcodex",
        "transport": "tradingcodex-official",
        "requested_provider": provider,
        "returned_provider": "",
        "upstream_provider": provider,
        "tool_name": "mcp__tradingcodex__fetch_official_source_data",
        "route": route,
        "returned_adjustment_policy": "",
        "result_status": result_status,
        "fallback_reason": f"{coverage_gap or 'official_source_gap'}:{detail}"[:500],
        "evidence_grade": "unusable",
        "provider_query": _common_provider_query(request, provider),
        "source_category": str(request.get("data_kind") or "official_data"),
        "source_locator": route,
        "timezone": "UTC",
        "coverage_note": coverage_gap or detail,
        "warnings": [],
        "data_classification": "public",
        "redistribution": "not_specified",
    }


def _truncated_record_args(value: dict[str, Any]) -> dict[str, Any]:
    provider = str(value.get("requested_provider") or "tradingcodex-official-gap")
    query = value.get("provider_query")
    if not isinstance(query, dict):
        query = {"provider": provider}
    else:
        query = dict(query)
        query["provider"] = provider
    return {
        "source_tier": "tradingcodex",
        "transport": "tradingcodex-official",
        "requested_provider": provider,
        "returned_provider": "",
        "upstream_provider": provider,
        "tool_name": "mcp__tradingcodex__fetch_official_source_data",
        "route": str(value.get("route") or "tradingcodex:official-source-plan"),
        "returned_adjustment_policy": "",
        "result_status": "terminal_gap",
        "fallback_reason": "official_result_truncated:bounded output exceeded 20000 characters",
        "evidence_grade": "unusable",
        "provider_query": query,
        "source_category": str(value.get("source_category") or "official_data"),
        "source_locator": str(value.get("source_locator") or value.get("route") or "tradingcodex:official-source-plan"),
        "timezone": "UTC",
        "coverage_note": "official_result_truncated",
        "warnings": [],
        "data_classification": "public",
        "redistribution": "not_specified",
    }


def _execution_result(
    plan: dict[str, Any],
    attempts: list[dict[str, Any]],
    accepted_results: list[dict[str, Any]],
    *,
    status: str,
    selected_source_id: str,
    coverage_gap: str,
    fallback_exhausted: bool,
    record_external_data_result_args: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "schema_version": 1,
        "status": status,
        "source_policy": plan["source_policy"],
        "data_kind": plan["data_kind"],
        "region": plan["region"],
        "selected_source_id": selected_source_id,
        "attempts": attempts,
        "accepted_results": accepted_results,
        "coverage_gap": coverage_gap,
        "fallback_exhausted": fallback_exhausted,
        "same_call_retries": 0,
        "record_external_data_result_args": record_external_data_result_args,
        "recorder_instruction": (
            "Immediately call record_external_data_result for this DataNeed, including "
            "typed failures; do not refetch the same semantic request."
        ),
    }
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(rendered) <= MAX_OFFICIAL_RESULT_CHARS:
        return result
    return {
        "schema_version": 1,
        "status": "terminal_gap",
        "source_policy": plan["source_policy"],
        "data_kind": plan["data_kind"],
        "region": plan["region"],
        "selected_source_id": "",
        "attempts": attempts,
        "accepted_results": [],
        "coverage_gap": "official_result_truncated",
        "fallback_exhausted": True,
        "same_call_retries": 0,
        "record_external_data_result_args": _truncated_record_args(
            record_external_data_result_args
        ),
        "recorder_instruction": (
            "Immediately call record_external_data_result with terminal_gap and no rows; "
            "narrow the DataNeed before any changed follow-up."
        ),
    }
