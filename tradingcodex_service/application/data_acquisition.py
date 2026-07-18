from __future__ import annotations

import json
import math
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tradingcodex_service.application.common import (
    atomic_write_text,
    exclusive_file_lock,
    file_hash,
    now_iso,
    safe_workspace_path,
    stable_hash,
)
from tradingcodex_service.application.datasets import (
    DATASET_MANIFEST_ROOT,
    DATASET_OBJECT_ROOT,
    get_dataset_manifest,
    record_dataset_snapshot,
    validate_dataset_lineage,
    validate_dataset_manifest,
)
from tradingcodex_service.application.research import (
    get_source_snapshot,
    record_source_snapshot,
)
from tradingcodex_service.application.research_objects import (
    canonical_json_bytes,
    content_hash,
    derive_content_id,
    normalize_timestamp,
    read_regular_json,
    write_immutable_json,
)
from tradingcodex_service.application.runtime import workspace_context_payload
from tradingcodex_service.application.official_sources import (
    OFFICIAL_ASSET_CLASSES,
    OFFICIAL_DATA_KINDS,
)


DATA_ACQUISITION_SCHEMA_VERSION = 4
DATA_ACQUISITION_RECEIPT_ROOT = Path("trading/research/data-acquisitions/receipts")
DATA_ACQUISITION_FAMILY_ROOT = Path("trading/research/data-acquisitions/families")
DATA_ACQUISITION_TRANSACTION_ROOT = Path(
    "trading/research/data-acquisitions/transactions"
)
DATA_ACQUISITION_LOCK = Path("trading/research/.index/data-acquisitions")
MAX_EXTERNAL_ROWS = 120
MAX_EXTERNAL_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_FALLBACK_REASON_CHARS = 500
MAX_COVERAGE_NOTE_CHARS = 1_000

SOURCE_POLICIES = frozenset({"strict", "preferred", "best_available"})
RESULT_STATES = frozenset(
    {
        "complete_valid",
        "partial_valid",
        "correctable_error",
        "terminal_gap",
        "unsafe",
        "transient",
        "approval_required",
        "conflict",
    }
)
SOURCE_TIERS = frozenset({"user_capability", "openbb", "tradingcodex"})
SOURCE_TIER_ORDER = ("user_capability", "openbb", "tradingcodex")
_SOURCE_TIER_RANK = {
    source_tier: index for index, source_tier in enumerate(SOURCE_TIER_ORDER)
}
_TIER_FALLBACK_STATES = frozenset(
    {"terminal_gap", "partial_valid", "approval_required", "conflict"}
)
_SKIPPED_TIER_STATES = frozenset({"unavailable", "skipped"})
_SKIPPABLE_SOURCE_TIERS = frozenset({"user_capability", "openbb"})
_ROW_RESULT_STATES = frozenset({"complete_valid", "partial_valid"})
EVIDENCE_GRADES = frozenset({"unusable", "screen-grade", "factual-baseline"})
_EVIDENCE_GRADE_RANK = {
    "unusable": 0,
    "screen-grade": 1,
    "factual-baseline": 2,
}
DATA_NEED_DATA_KINDS = frozenset(
    {
        *OFFICIAL_DATA_KINDS,
        "calendar",
        "company_news",
        "corporate_events",
        "estimates",
        "instrument_reference",
        "market_microstructure",
        "news",
        "ownership",
        "technical_indicators",
        "valuation_inputs",
    }
)
DATA_NEED_ASSET_TYPES = frozenset(
    {*OFFICIAL_ASSET_CLASSES, "cash", "index", "multi_asset"}
)
DATA_NEED_FREQUENCIES = frozenset(
    {
        "tick",
        "1m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d",
        "1wk",
        "1mo",
        "daily",
        "weekly",
        "monthly",
        "quarterly",
        "annual",
        "event",
        "irregular",
        "point_in_time",
        "release_calendar",
    }
)
_PRICE_DATA_KINDS = frozenset(
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
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|authorization|cookie|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_HEADER_SECRET_VALUE = re.compile(
    r"\b(?:x-api-key|api-key|api_key|authorization|cookie|set-cookie|access_token)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_KNOWN_SECRET_TOKEN = re.compile(
    r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bAKIA[A-Z0-9]{16}\b"
)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,179}")
_FAMILY_ID = re.compile(r"data-family-[0-9a-f]{24}")
_RECEIPT_ID = re.compile(r"data-acquisition-[0-9a-f]{24}")
_DATASET_ID = re.compile(r"dataset-[0-9a-f]{24}")
_TRANSACTION_ID = re.compile(r"data-acquisition-txn-[0-9a-f]{24}")
_FAMILY_FREQUENCY = {
    "daily": "1d",
    "weekly": "1wk",
    "monthly": "1mo",
}


def _normalized_family_payload(
    *,
    data_kind: str,
    asset_type: str,
    identifiers: tuple[str, ...],
    period_start: str,
    period_end: str,
    as_of: str,
    frequency: str,
    adjustment_policy: str,
) -> dict[str, Any]:
    return {
        "data_kind": data_kind,
        "asset_type": asset_type,
        "identifiers": sorted(item.casefold() for item in identifiers),
        "period_start": period_start,
        "period_end": period_end,
        "as_of": as_of,
        "frequency": _FAMILY_FREQUENCY.get(frequency, frequency),
        "adjustment_policy": adjustment_policy.casefold(),
    }


@dataclass(frozen=True)
class DataNeed:
    run_id: str
    family_id: str
    data_kind: str
    asset_type: str
    identifiers: tuple[str, ...]
    fields: tuple[str, ...]
    period_start: str
    period_end: str
    as_of: str
    frequency: str
    adjustment_policy: str
    minimum_evidence_grade: str
    owner_role: str
    source_policy: str
    explicit_source: str = ""

    @classmethod
    def from_mapping(cls, value: Any) -> "DataNeed":
        if not isinstance(value, dict):
            raise ValueError("data_need must be an object")
        allowed_fields = {
            "run_id",
            "family_id",
            "data_kind",
            "asset_type",
            "identifiers",
            "fields",
            "period_start",
            "period_end",
            "as_of",
            "frequency",
            "adjustment_policy",
            "minimum_evidence_grade",
            "owner_role",
            "source_policy",
            "explicit_source",
        }
        unknown = sorted(set(value) - allowed_fields)
        if unknown:
            raise ValueError(
                "data_need does not allow additional properties: " + ", ".join(unknown)
            )
        identifiers = _string_tuple(value.get("identifiers"), "data_need.identifiers")
        fields = _string_tuple(value.get("fields"), "data_need.fields")
        if not identifiers:
            raise ValueError("data_need.identifiers requires at least one identifier")
        if not fields:
            raise ValueError("data_need.fields requires at least one field")
        if len({item.casefold() for item in identifiers}) != len(identifiers):
            raise ValueError("data_need.identifiers must be unique ignoring case")
        if len({item.casefold() for item in fields}) != len(fields):
            raise ValueError("data_need.fields must be unique ignoring case")
        policy = _required_text(value.get("source_policy"), "data_need.source_policy")
        if policy not in SOURCE_POLICIES:
            raise ValueError(
                "data_need.source_policy must be strict, preferred, or best_available"
            )
        period_start = normalize_timestamp(
            value.get("period_start"), "data_need.period_start", required=False
        )
        period_end = normalize_timestamp(
            value.get("period_end"), "data_need.period_end", required=False
        )
        as_of = normalize_timestamp(value.get("as_of"), "data_need.as_of", required=False)
        if bool(period_start) != bool(period_end):
            raise ValueError(
                "data_need.period_start and data_need.period_end must be supplied together"
            )
        if not as_of and not period_start:
            raise ValueError("data_need requires as_of or a complete period")
        if period_start and _utc_datetime(period_start) > _utc_datetime(period_end):
            raise ValueError("data_need.period_start must not be after period_end")
        if period_end and as_of and _utc_datetime(period_end) > _utc_datetime(as_of):
            raise ValueError("data_need.period_end must not be after as_of")
        explicit_source = str(value.get("explicit_source") or "").strip()
        if policy == "strict" and not explicit_source:
            raise ValueError("strict data_need.source_policy requires explicit_source")
        data_kind = _choice(
            value.get("data_kind"), DATA_NEED_DATA_KINDS, "data_need.data_kind"
        )
        asset_type = _choice(
            value.get("asset_type"), DATA_NEED_ASSET_TYPES, "data_need.asset_type"
        )
        frequency = _choice(
            value.get("frequency"), DATA_NEED_FREQUENCIES, "data_need.frequency"
        )
        owner_role = _required_text(value.get("owner_role"), "data_need.owner_role")
        from tradingcodex_service.application.agents import RESEARCH_ROLES

        if owner_role not in RESEARCH_ROLES:
            raise ValueError(
                "data_need.owner_role must be one of: " + ", ".join(RESEARCH_ROLES)
            )
        adjustment_policy = _required_text(
            value.get("adjustment_policy"),
            "data_need.adjustment_policy",
        )
        if data_kind in _PRICE_DATA_KINDS and adjustment_policy == "not_specified":
            raise ValueError(
                "price data needs require an explicit data_need.adjustment_policy"
            )
        minimum_evidence_grade = _choice(
            value.get("minimum_evidence_grade"),
            EVIDENCE_GRADES - {"unusable"},
            "data_need.minimum_evidence_grade",
        )
        run_id = _required_text(value.get("run_id"), "data_need.run_id")
        if _RUN_ID.fullmatch(run_id) is None:
            raise ValueError(
                "data_need.run_id must be a safe opaque run identifier"
            )
        family_seed = {
            "run_id": run_id,
            **_normalized_family_payload(
                data_kind=data_kind,
                asset_type=asset_type,
                identifiers=identifiers,
                period_start=period_start,
                period_end=period_end,
                as_of=as_of,
                frequency=frequency,
                adjustment_policy=adjustment_policy,
            ),
        }
        family_id = f"data-family-{stable_hash(family_seed)[:24]}"
        supplied_family_id = str(value.get("family_id") or "").strip()
        if supplied_family_id and supplied_family_id != family_id:
            raise ValueError(
                "data_need.family_id does not match the normalized run-scoped family"
            )
        return cls(
            run_id=run_id,
            family_id=family_id,
            data_kind=data_kind,
            asset_type=asset_type,
            identifiers=identifiers,
            fields=fields,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
            frequency=frequency,
            adjustment_policy=adjustment_policy,
            minimum_evidence_grade=minimum_evidence_grade,
            owner_role=owner_role,
            source_policy=policy,
            explicit_source=explicit_source,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "family_id": self.family_id,
            "data_kind": self.data_kind,
            "asset_type": self.asset_type,
            "identifiers": list(self.identifiers),
            "fields": list(self.fields),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "as_of": self.as_of,
            "frequency": self.frequency,
            "adjustment_policy": self.adjustment_policy,
            "minimum_evidence_grade": self.minimum_evidence_grade,
            "owner_role": self.owner_role,
            "source_policy": self.source_policy,
            "explicit_source": self.explicit_source,
        }

    def normalized_family(self) -> dict[str, Any]:
        """Return the owner- and source-independent family claimed within one run."""

        return _normalized_family_payload(
            data_kind=self.data_kind,
            asset_type=self.asset_type,
            identifiers=self.identifiers,
            period_start=self.period_start,
            period_end=self.period_end,
            as_of=self.as_of,
            frequency=self.frequency,
            adjustment_policy=self.adjustment_policy,
        )


def _authenticate_analysis_run(root: Path, data_need: DataNeed) -> dict[str, Any]:
    """Require the DataNeed to bind an existing integrity-checked analysis run."""

    from tradingcodex_service.application.analysis_runs import read_analysis_run

    run = read_analysis_run(root, data_need.run_id)
    if (
        not run
        or run.get("marker") != "tradingcodex-analysis-run"
        or run.get("workflow_run_id") != data_need.run_id
        or not isinstance(run.get("record_hash"), str)
        or not run["record_hash"]
    ):
        raise ValueError(
            "data_need.run_id must identify an existing authenticated analysis run"
        )
    return run


def _data_attempt_key(
    data_need: DataNeed,
    *,
    source_tier: str,
    transport: str,
    requested_provider: str,
    tool_name: str,
    route: str,
    compatibility_receipt_hash: str,
) -> str:
    return stable_hash(
        {
            "run_id": data_need.run_id,
            "family_id": data_need.family_id,
            "source_tier": source_tier,
            "transport": transport,
            "requested_provider": requested_provider,
            "tool_name": tool_name,
            "route": route,
            "fields": sorted(item.casefold() for item in data_need.fields),
            "adjustment_policy": data_need.adjustment_policy,
            "minimum_evidence_grade": data_need.minimum_evidence_grade,
            "source_policy": data_need.source_policy,
            "explicit_source": data_need.explicit_source.casefold(),
            "compatibility_receipt_hash": compatibility_receipt_hash,
        }
    )


def _claim_data_need_family(
    root: Path,
    data_need: DataNeed,
    *,
    principal_id: str,
) -> dict[str, Any]:
    """Create or authenticate the immutable owner lease for one run-scoped family."""

    relative = (
        DATA_ACQUISITION_FAMILY_ROOT
        / data_need.run_id
        / f"{data_need.family_id}.json"
    )
    path = safe_workspace_path(
        root,
        relative,
        allowed_roots=(DATA_ACQUISITION_FAMILY_ROOT,),
    )
    if path.exists() or path.is_symlink():
        lease = _validate_data_need_family_lease(
            read_regular_json(path, label="data need family lease"),
            data_need=data_need,
        )
        if lease["owner_role"] != data_need.owner_role:
            raise PermissionError(
                "data need family is already owned by another role in this run"
            )
        return lease

    seed = {
        "schema_version": 1,
        "artifact_type": "data_need_family_lease",
        "run_id": data_need.run_id,
        "family_id": data_need.family_id,
        "normalized_family": data_need.normalized_family(),
        "owner_role": data_need.owner_role,
        "claimed_by": principal_id,
        "claimed_at": normalize_timestamp(now_iso(), "claimed_at"),
    }
    lease = {**seed, "lease_id": derive_content_id("data-family-lease", seed)}
    lease["lease_hash"] = content_hash(lease)
    _validate_data_need_family_lease(lease, data_need=data_need)
    write_immutable_json(path, lease)
    return lease


def _validate_data_need_family_lease(
    value: Any,
    *,
    data_need: DataNeed,
) -> dict[str, Any]:
    expected = {
        "schema_version",
        "artifact_type",
        "lease_id",
        "run_id",
        "family_id",
        "normalized_family",
        "owner_role",
        "claimed_by",
        "claimed_at",
        "lease_hash",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("data need family lease schema is invalid")
    if value["schema_version"] != 1 or value["artifact_type"] != "data_need_family_lease":
        raise ValueError("data need family lease identity is invalid")
    if (
        value["run_id"] != data_need.run_id
        or value["family_id"] != data_need.family_id
        or value["normalized_family"] != data_need.normalized_family()
    ):
        raise ValueError("data need family lease does not match the normalized family")
    if not isinstance(value["owner_role"], str) or not value["owner_role"]:
        raise ValueError("data need family lease owner_role is invalid")
    if not isinstance(value["claimed_by"], str) or not value["claimed_by"]:
        raise ValueError("data need family lease claimed_by is invalid")
    normalize_timestamp(value["claimed_at"], "claimed_at")
    seed = {
        key: item
        for key, item in value.items()
        if key not in {"lease_id", "lease_hash"}
    }
    if value["lease_id"] != derive_content_id("data-family-lease", seed):
        raise ValueError("data need family lease id mismatch")
    if value["lease_hash"] != content_hash(
        {key: item for key, item in value.items() if key != "lease_hash"}
    ):
        raise ValueError("data need family lease hash mismatch")
    return value


def _validate_result_attestation(
    *,
    workspace_root: Path,
    data_need: DataNeed,
    source_tier: str,
    storable: bool,
    transport: str,
    requested_provider: str,
    returned_provider: str,
    upstream_provider: str,
    tool_name: str,
    route: str,
    provider_query: dict[str, Any],
    evidence_grade: str,
    returned_adjustment_policy: str,
    compatibility_receipt_hash: str,
    principal_id: str,
) -> None:
    if not principal_id:
        raise PermissionError(
            "record_external_data_result requires an authenticated principal"
        )
    from apps.policy.services import role_for_principal_id

    principal_role = role_for_principal_id(principal_id)
    if principal_role != data_need.owner_role:
        raise PermissionError(
            "authenticated principal role does not own this data_need"
        )

    query_provider = str(provider_query.get("provider") or "").strip()
    if not query_provider:
        raise ValueError("provider_query.provider is required for source attestation")
    if query_provider != requested_provider:
        raise ValueError(
            "provider_query.provider must exactly match requested_provider"
        )
    if source_tier == "user_capability" and not (
        re.fullmatch(r"mcp__[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+", tool_name)
        or re.fullmatch(r"skill:[A-Za-z0-9_.:-]+", tool_name)
    ):
        raise ValueError(
            "user capability results require an exact MCP tool FQN or skill:<name> identity"
        )

    actual_source = returned_provider if storable else requested_provider
    if data_need.source_policy == "strict":
        accepted_source_ids = {
            requested_provider.casefold(),
            actual_source.casefold(),
            transport.casefold(),
            tool_name.casefold(),
            route.casefold(),
            f"{transport}:{requested_provider}".casefold(),
            f"{source_tier}:{transport}:{requested_provider}".casefold(),
        }
        if data_need.explicit_source.casefold() not in accepted_source_ids:
            raise ValueError(
                "strict data_need.explicit_source does not match the attested source"
            )

    if storable:
        if not returned_provider:
            raise ValueError("storable external results require returned_provider")
        if returned_provider != requested_provider or upstream_provider != returned_provider:
            raise ValueError(
                "requested_provider, returned_provider, and upstream_provider must match"
            )
        if returned_adjustment_policy != data_need.adjustment_policy:
            raise ValueError(
                "returned_adjustment_policy must exactly match data_need.adjustment_policy"
            )
        if _EVIDENCE_GRADE_RANK[evidence_grade] < _EVIDENCE_GRADE_RANK[
            data_need.minimum_evidence_grade
        ]:
            raise ValueError(
                "evidence_grade is below data_need.minimum_evidence_grade"
            )
    else:
        if upstream_provider != requested_provider:
            raise ValueError(
                "failed external result upstream_provider must match requested_provider"
            )
        if returned_provider and returned_provider != requested_provider:
            raise ValueError(
                "failed external result returned_provider must be empty or match requested_provider"
            )
        if returned_adjustment_policy and (
            returned_adjustment_policy != data_need.adjustment_policy
        ):
            raise ValueError(
                "failed external result returned_adjustment_policy must be empty or match the request"
            )
        if evidence_grade != "unusable":
            raise ValueError("non-row external results require evidence_grade=unusable")

    if source_tier == "openbb":
        if re.fullmatch(r"[0-9a-f]{64}", compatibility_receipt_hash) is None:
            raise ValueError(
                "OpenBB results require a validated compatibility_receipt_hash"
            )
        from tradingcodex_service.application.data_sources import (
            validate_openbb_compatibility_receipt_hash,
        )

        validate_openbb_compatibility_receipt_hash(
            workspace_root, compatibility_receipt_hash
        )
    elif compatibility_receipt_hash:
        raise ValueError(
            "compatibility_receipt_hash is reserved for source_tier=openbb"
        )


def _normalize_predecessor_receipt_ids(value: Any) -> list[str]:
    receipt_ids = list(_string_tuple(value, "predecessor_receipt_ids"))
    if len(receipt_ids) > 20:
        raise ValueError(
            "predecessor_receipt_ids exceeds the bounded transition chain"
        )
    for receipt_id in receipt_ids:
        if _RECEIPT_ID.fullmatch(receipt_id) is None:
            raise ValueError("predecessor_receipt_ids contains an invalid receipt id")
    return receipt_ids


def _normalize_skipped_tier_attestations(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > len(SOURCE_TIER_ORDER) - 1:
        raise ValueError(
            "skipped_tier_attestations must be a bounded source-tier array"
        )
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "source_tier",
            "status",
            "reason",
        }:
            raise ValueError(
                "skipped_tier_attestations items require source_tier, status, and reason"
            )
        source_tier = _choice(
            item.get("source_tier"),
            _SKIPPABLE_SOURCE_TIERS,
            "skipped_tier.source_tier",
        )
        if source_tier in seen:
            raise ValueError("skipped_tier_attestations must not repeat a source tier")
        seen.add(source_tier)
        status = _choice(
            item.get("status"), _SKIPPED_TIER_STATES, "skipped_tier.status"
        )
        reason = _bounded_single_line(
            item.get("reason"), "skipped_tier.reason", max_chars=300
        )
        if not reason:
            raise ValueError("skipped_tier.reason is required")
        normalized.append(
            {"source_tier": source_tier, "status": status, "reason": reason}
        )
    _reject_secret_material(normalized, path="skipped_tier_attestations")
    return normalized


def _receipt_source_identity(receipt: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        receipt["transport"],
        receipt["requested_provider"],
        receipt["tool_name"],
        receipt["route"],
    )


def _current_source_identity(
    *, transport: str, requested_provider: str, tool_name: str, route: str
) -> tuple[str, str, str, str]:
    return (transport, requested_provider, tool_name, route)


def _family_receipts(root: Path, data_need: DataNeed) -> list[dict[str, Any]]:
    receipt_root = root / DATA_ACQUISITION_RECEIPT_ROOT
    if not receipt_root.exists():
        return []
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        raise ValueError("data acquisition receipt root must be a real directory")
    receipts: list[dict[str, Any]] = []
    for path in sorted(receipt_root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("data acquisition receipt must be a regular file")
        receipt = validate_data_acquisition_receipt(
            read_regular_json(path, label="data acquisition receipt")
        )
        if (
            receipt["run_id"] == data_need.run_id
            and receipt["family_id"] == data_need.family_id
        ):
            validate_data_acquisition_lineage(root, receipt)
            receipts.append(receipt)
    receipts.sort(key=lambda item: (item["recorded_at"], item["receipt_id"]))
    return receipts


def _transition_predecessor(
    receipts: list[dict[str, Any]], source_tier: str
) -> dict[str, Any] | None:
    current_rank = _SOURCE_TIER_RANK[source_tier]
    eligible = [
        receipt
        for receipt in receipts
        if _SOURCE_TIER_RANK[receipt["source_tier"]] <= current_rank
    ]
    return eligible[-1] if eligible else None


def _validate_tier_transition(
    *,
    data_need: DataNeed,
    source_tier: str,
    transport: str,
    requested_provider: str,
    tool_name: str,
    route: str,
    attempt_key: str,
    receipts: list[dict[str, Any]],
    predecessor_receipt_ids: list[str],
    skipped_tier_attestations: list[dict[str, str]],
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    timezone_name: str,
) -> tuple[list[str], list[dict[str, str]]]:
    """Validate and return the complete auditable source-tier ancestry."""

    current_rank = _SOURCE_TIER_RANK[source_tier]
    current_identity = _current_source_identity(
        transport=transport,
        requested_provider=requested_provider,
        tool_name=tool_name,
        route=route,
    )
    by_id = {receipt["receipt_id"]: receipt for receipt in receipts}
    for predecessor_id in predecessor_receipt_ids:
        if predecessor_id not in by_id:
            raise ValueError(
                "predecessor_receipt_ids must identify exact receipts in this run family"
            )

    same_attempts = [
        receipt for receipt in receipts if receipt["attempt_key"] == attempt_key
    ]
    if same_attempts:
        first = min(same_attempts, key=lambda item: item["attempt_number"])
        if _receipt_source_identity(first) != current_identity:
            raise ValueError("corrected acquisition attempt changed source identity")
        if predecessor_receipt_ids != first["predecessor_receipt_ids"]:
            raise ValueError(
                "corrected acquisition attempt changed predecessor receipt ancestry"
            )
        if skipped_tier_attestations != first["skipped_tier_attestations"]:
            raise ValueError(
                "corrected acquisition attempt changed skipped-tier attestations"
            )
        return predecessor_receipt_ids, skipped_tier_attestations

    user_identities = {
        _receipt_source_identity(receipt)
        for receipt in receipts
        if receipt["source_tier"] == "user_capability"
    }
    if (
        source_tier == "user_capability"
        and user_identities
        and current_identity not in user_identities
    ):
        raise ValueError(
            "a second distinct user capability is not allowed in one run family"
        )

    strict_receipts = [
        receipt
        for receipt in receipts
        if receipt["data_need"]["source_policy"] == "strict"
    ]
    if (strict_receipts or data_need.source_policy == "strict") and any(
        _receipt_source_identity(receipt) != current_identity
        for receipt in (strict_receipts or receipts)
    ):
        raise ValueError("strict source policy does not permit source-tier fallback")

    skipped_by_tier = {
        item["source_tier"]: item for item in skipped_tier_attestations
    }
    predecessor = _transition_predecessor(receipts, source_tier)
    if predecessor is None:
        required_skips = list(SOURCE_TIER_ORDER[:current_rank])
        expected_predecessors: list[str] = []
        inherited_skips: list[dict[str, str]] = []
    else:
        predecessor_rank = _SOURCE_TIER_RANK[predecessor["source_tier"]]
        if current_rank < predecessor_rank:
            raise ValueError("source-tier regression is not allowed")
        if predecessor["source_tier"] == source_tier and not (
            source_tier == "tradingcodex"
            and predecessor["result_status"] == "partial_valid"
        ):
            raise ValueError(
                "same-tier continuation is limited to exact TradingCodex partial residuals"
            )
        if predecessor["result_status"] not in _TIER_FALLBACK_STATES:
            raise ValueError(
                "source-tier fallback requires an exact terminal, partial, approval, or conflict gap"
            )
        expected_predecessors = [
            *predecessor["predecessor_receipt_ids"],
            predecessor["receipt_id"],
        ]
        inherited_skips = list(predecessor["skipped_tier_attestations"])
        required_skips = list(
            SOURCE_TIER_ORDER[predecessor_rank + 1 : current_rank]
        )

    if predecessor_receipt_ids != expected_predecessors:
        raise ValueError(
            "predecessor_receipt_ids must exactly match the auditable tier chain"
        )
    if set(skipped_by_tier) != set(required_skips):
        raise ValueError(
            "lower source tier requires exact unavailable/skipped-tier attestations"
        )
    if any(_SOURCE_TIER_RANK[tier] >= current_rank for tier in skipped_by_tier):
        raise ValueError("skipped-tier attestations may name only higher-priority tiers")

    if predecessor is not None and predecessor["result_status"] == "partial_valid":
        _validate_partial_residual_result(
            predecessor,
            rows=rows,
            columns=columns,
            timezone_name=timezone_name,
        )
    return expected_predecessors, [
        *inherited_skips,
        *(skipped_by_tier[tier] for tier in required_skips),
    ]


def _validate_partial_residual_result(
    predecessor: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    timezone_name: str,
) -> None:
    """Reject lower-tier values that overlap a partial predecessor's retained cells."""

    if not rows:
        return
    missing_fields = {item.casefold() for item in predecessor["missing_fields"]}
    missing_identifiers = {
        item.casefold() for item in predecessor["missing_identifiers"]
    }
    missing_periods = predecessor["missing_periods"]
    if len(missing_periods) > 1 or not (
        missing_fields or missing_identifiers or missing_periods
    ):
        raise ValueError("partial predecessor has an invalid residual coverage shape")

    try:
        declared_timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone name") from exc
    columns_by_fold = {str(item["name"]).casefold(): item for item in columns}
    identifier_name = next(
        (
            name
            for name in (
                "instrument_id",
                "symbol",
                "identifier",
                "ticker",
                "series_id",
                "cik",
                "lei",
                "contract",
                "id",
            )
            if name in columns_by_fold
        ),
        "",
    )
    timestamp_name = next(
        (
            name
            for name in (
                "timestamp",
                "datetime",
                "date",
                "observed_at",
                "as_of",
                "period_end",
                "published_at",
            )
            if name in columns_by_fold
        ),
        "",
    )
    key_fields = {identifier_name, timestamp_name, ""}
    requested_fields = {
        item.casefold() for item in predecessor["data_need"]["fields"]
    }
    gap_start = _utc_datetime(missing_periods[0]["start"]) if missing_periods else None
    gap_end = _utc_datetime(missing_periods[0]["end"]) if missing_periods else None

    for index, raw_row in enumerate(rows):
        row = {str(key).casefold(): value for key, value in raw_row.items()}
        identifier = str(row.get(identifier_name) or "").strip().casefold()
        identifier_gap = bool(identifier and identifier in missing_identifiers)
        period_gap = False
        if gap_start is not None and timestamp_name:
            timestamp = _normalized_observation_time(
                row.get(timestamp_name),
                timestamp_name,
                column_type=str(columns_by_fold[timestamp_name]["type"]),
                declared_timezone=declared_timezone,
            )
            observation = _utc_datetime(timestamp)
            period_gap = gap_start <= observation <= gap_end

        matched_gap = identifier_gap or period_gap
        for field in requested_fields - key_fields:
            if row.get(field) is None:
                continue
            if field in missing_fields or identifier_gap or period_gap:
                matched_gap = True
                continue
            raise ValueError(
                "lower-tier residual result overlaps values retained by its partial predecessor"
            )
        if not matched_gap:
            raise ValueError(
                f"lower-tier residual rows[{index}] does not address a predecessor coverage gap"
            )


def _promotion_transaction_id(
    *, data_need: DataNeed, attempt_key: str, semantic_key: str
) -> str:
    return derive_content_id(
        "data-acquisition-txn",
        {
            "run_id": data_need.run_id,
            "family_id": data_need.family_id,
            "attempt_key": attempt_key,
            "semantic_key": semantic_key,
        },
    )


def _promotion_transaction_path(root: Path, transaction_id: str) -> Path:
    if _TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise ValueError("data acquisition transaction id is invalid")
    return safe_workspace_path(
        root,
        DATA_ACQUISITION_TRANSACTION_ROOT / f"{transaction_id}.json",
        allowed_roots=(DATA_ACQUISITION_TRANSACTION_ROOT,),
    )


def _write_promotion_transaction(
    root: Path,
    *,
    transaction_id: str,
    data_need: DataNeed,
    attempt_key: str,
    semantic_key: str,
    state: str,
    snapshot_id: str = "",
    dataset_id: str = "",
    receipt_id: str = "",
) -> dict[str, Any]:
    document = {
        "schema_version": 1,
        "artifact_type": "data_acquisition_promotion_transaction",
        "transaction_id": transaction_id,
        "run_id": data_need.run_id,
        "family_id": data_need.family_id,
        "attempt_key": attempt_key,
        "semantic_key": semantic_key,
        "state": state,
        "snapshot_id": snapshot_id,
        "dataset_id": dataset_id,
        "receipt_id": receipt_id,
        "updated_at": normalize_timestamp(now_iso(), "updated_at"),
    }
    document["transaction_hash"] = content_hash(document)
    _validate_promotion_transaction(document, expected_id=transaction_id)
    path = _promotion_transaction_path(root, transaction_id)
    atomic_write_text(
        path,
        json.dumps(
            document,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )
    return document


def _validate_promotion_transaction(
    value: Any, *, expected_id: str | None = None
) -> dict[str, Any]:
    expected = {
        "schema_version",
        "artifact_type",
        "transaction_id",
        "run_id",
        "family_id",
        "attempt_key",
        "semantic_key",
        "state",
        "snapshot_id",
        "dataset_id",
        "receipt_id",
        "updated_at",
        "transaction_hash",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("data acquisition promotion transaction schema is invalid")
    if (
        value["schema_version"] != 1
        or value["artifact_type"]
        != "data_acquisition_promotion_transaction"
        or value["state"]
        not in {"prepared", "snapshot_recorded", "dataset_recorded", "receipt_recorded"}
    ):
        raise ValueError("data acquisition promotion transaction identity is invalid")
    if _TRANSACTION_ID.fullmatch(str(value["transaction_id"])) is None or (
        expected_id is not None and value["transaction_id"] != expected_id
    ):
        raise ValueError("data acquisition promotion transaction id mismatch")
    if _RUN_ID.fullmatch(str(value["run_id"])) is None or _FAMILY_ID.fullmatch(
        str(value["family_id"])
    ) is None:
        raise ValueError("data acquisition promotion transaction scope is invalid")
    for field in ("attempt_key", "semantic_key", "transaction_hash"):
        if re.fullmatch(r"[0-9a-f]{64}", str(value[field])) is None:
            raise ValueError(
                f"data acquisition promotion transaction {field} is invalid"
            )
    for field, pattern in (
        ("snapshot_id", _RUN_ID),
        ("dataset_id", _DATASET_ID),
        ("receipt_id", _RECEIPT_ID),
    ):
        if value[field] and pattern.fullmatch(str(value[field])) is None:
            raise ValueError(
                f"data acquisition promotion transaction {field} is invalid"
            )
    normalize_timestamp(value["updated_at"], "updated_at")
    if value["transaction_hash"] != content_hash(
        {key: item for key, item in value.items() if key != "transaction_hash"}
    ):
        raise ValueError("data acquisition promotion transaction hash mismatch")
    return value


def recover_incomplete_data_acquisitions(
    workspace_root: Path | str,
) -> dict[str, Any]:
    """Roll back authenticated interrupted promotions before they become readable."""

    root = Path(workspace_root).expanduser().resolve()
    transaction_root = root / DATA_ACQUISITION_TRANSACTION_ROOT
    if not transaction_root.exists():
        return {"status": "clean", "recovered_transaction_ids": []}
    with exclusive_file_lock(root / DATA_ACQUISITION_LOCK):
        recovered = _recover_incomplete_promotions_locked(root)
    return {
        "status": "recovered" if recovered else "clean",
        "recovered_transaction_ids": recovered,
    }


def _recover_incomplete_promotions_locked(root: Path) -> list[str]:
    transaction_root = root / DATA_ACQUISITION_TRANSACTION_ROOT
    if not transaction_root.exists():
        return []
    if transaction_root.is_symlink() or not transaction_root.is_dir():
        raise ValueError("data acquisition transaction root must be a real directory")

    recovered: list[str] = []
    for marker_path in sorted(transaction_root.glob("*.json")):
        if marker_path.is_symlink() or not marker_path.is_file():
            raise ValueError("data acquisition transaction must be a regular file")
        transaction = _validate_promotion_transaction(
            read_regular_json(marker_path, label="data acquisition transaction"),
            expected_id=marker_path.stem,
        )
        transaction_id = transaction["transaction_id"]
        snapshot_ids = _transaction_snapshot_ids(root, transaction)
        if transaction["snapshot_id"]:
            snapshot_ids.add(transaction["snapshot_id"])
        dataset_ids = _transaction_dataset_ids(root, snapshot_ids)
        if transaction["dataset_id"]:
            dataset_ids.add(transaction["dataset_id"])

        committed = _committed_transaction_receipt(
            root,
            transaction=transaction,
            snapshot_ids=snapshot_ids,
            dataset_ids=dataset_ids,
        )
        if committed is not None:
            marker_path.unlink()
            continue

        for dataset_id in sorted(dataset_ids):
            manifest_path = root / DATASET_MANIFEST_ROOT / f"{dataset_id}.json"
            if not manifest_path.exists() and not manifest_path.is_symlink():
                continue
            _rollback_new_dataset(
                root,
                {
                    "status": "recorded",
                    "dataset_id": dataset_id,
                    "manifest_path": (
                        DATASET_MANIFEST_ROOT / f"{dataset_id}.json"
                    ).as_posix(),
                },
                set(),
            )
        for snapshot_id in sorted(snapshot_ids):
            _rollback_new_snapshot(
                root,
                {
                    "snapshot_id": snapshot_id,
                    "export_path": (
                        Path("trading/research/source-snapshots")
                        / f"{snapshot_id}.json"
                    ).as_posix(),
                },
                set(),
            )
        marker_path.unlink()
        recovered.append(transaction_id)
    return recovered


def _transaction_snapshot_ids(
    root: Path, transaction: dict[str, Any]
) -> set[str]:
    snapshot_root = root / "trading/research/source-snapshots"
    if not snapshot_root.exists():
        return set()
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise ValueError("SourceSnapshot root must be a real directory")
    from tradingcodex_service.application.source_snapshots import (
        validate_source_snapshot,
    )

    result: set[str] = set()
    for path in sorted(snapshot_root.glob("*.json")):
        snapshot = validate_source_snapshot(
            read_regular_json(path, label="SourceSnapshot during recovery"),
            expected_snapshot_id=path.stem,
        )
        transaction_binding = {
            "acquisition_transaction_id": transaction["transaction_id"],
            "acquisition_run_id": transaction["run_id"],
            "acquisition_family_id": transaction["family_id"],
            "acquisition_attempt_key": transaction["attempt_key"],
            "acquisition_semantic_key": transaction["semantic_key"],
        }
        if all(
            snapshot["payload"].get(key) == expected
            for key, expected in transaction_binding.items()
        ):
            result.add(snapshot["snapshot_id"])
    return result


def _transaction_dataset_ids(root: Path, snapshot_ids: set[str]) -> set[str]:
    if not snapshot_ids:
        return set()
    manifest_root = root / DATASET_MANIFEST_ROOT
    if not manifest_root.exists():
        return set()
    if manifest_root.is_symlink() or not manifest_root.is_dir():
        raise ValueError("Dataset manifest root must be a real directory")
    result: set[str] = set()
    for path in sorted(manifest_root.glob("*.json")):
        manifest = validate_dataset_manifest(
            read_regular_json(path, label="Dataset manifest during recovery"),
            expected_dataset_id=path.stem,
        )
        if snapshot_ids.intersection(manifest["source_snapshot_ids"]):
            result.add(manifest["dataset_id"])
    return result


def _committed_transaction_receipt(
    root: Path,
    *,
    transaction: dict[str, Any],
    snapshot_ids: set[str],
    dataset_ids: set[str],
) -> dict[str, Any] | None:
    receipt_root = root / DATA_ACQUISITION_RECEIPT_ROOT
    if not receipt_root.exists():
        return None
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        raise ValueError("data acquisition receipt root must be a real directory")
    for path in sorted(receipt_root.glob("*.json")):
        receipt = validate_data_acquisition_receipt(
            read_regular_json(path, label="data acquisition receipt during recovery"),
            expected_receipt_id=path.stem,
        )
        if transaction["receipt_id"] and receipt["receipt_id"] != transaction["receipt_id"]:
            continue
        if (
            receipt["snapshot_id"] in snapshot_ids
            and receipt["dataset_id"] in dataset_ids
            and receipt["attempt_key"] == transaction["attempt_key"]
            and receipt["semantic_key"] == transaction["semantic_key"]
        ):
            validate_data_acquisition_lineage(root, receipt)
            return receipt
    return None


@dataclass(frozen=True)
class DataAcquisitionReceipt:
    receipt_id: str
    document: dict[str, Any]

    @classmethod
    def build(
        cls,
        *,
        data_need: DataNeed,
        source_tier: str,
        transport: str,
        requested_provider: str,
        returned_provider: str,
        upstream_provider: str,
        tool_name: str,
        route: str,
        requested_adjustment_policy: str,
        returned_adjustment_policy: str,
        compatibility_receipt_hash: str,
        schema_hash: str,
        query_hash: str,
        result_hash: str,
        attempt_key: str,
        attempt_number: int,
        corrects_receipt_id: str,
        predecessor_receipt_ids: list[str],
        skipped_tier_attestations: list[dict[str, str]],
        semantic_key: str,
        result_status: str,
        fallback_reason: str,
        evidence_grade: str,
        snapshot_id: str,
        dataset_id: str,
        row_count: int,
        missing_fields: list[str],
        missing_identifiers: list[str],
        missing_periods: list[dict[str, str]],
        coverage_note: str,
        warnings: list[str],
        created_by: str,
    ) -> "DataAcquisitionReceipt":
        recorded_at = normalize_timestamp(now_iso(), "recorded_at")
        seed = {
            "schema_version": DATA_ACQUISITION_SCHEMA_VERSION,
            "artifact_type": "data_acquisition_receipt",
            "run_id": data_need.run_id,
            "family_id": data_need.family_id,
            "data_need": data_need.as_dict(),
            "source_tier": source_tier,
            "transport": transport,
            "requested_provider": requested_provider,
            "returned_provider": returned_provider,
            "upstream_provider": upstream_provider,
            "tool_name": tool_name,
            "route": route,
            "requested_adjustment_policy": requested_adjustment_policy,
            "returned_adjustment_policy": returned_adjustment_policy,
            "compatibility_receipt_hash": compatibility_receipt_hash,
            "schema_hash": schema_hash,
            "query_hash": query_hash,
            "result_hash": result_hash,
            "attempt_key": attempt_key,
            "attempt_number": attempt_number,
            "corrects_receipt_id": corrects_receipt_id,
            "predecessor_receipt_ids": predecessor_receipt_ids,
            "skipped_tier_attestations": skipped_tier_attestations,
            "semantic_key": semantic_key,
            "result_status": result_status,
            "fallback_reason": fallback_reason,
            "evidence_grade": evidence_grade,
            "snapshot_id": snapshot_id,
            "dataset_id": dataset_id,
            "row_count": row_count,
            "missing_fields": missing_fields,
            "missing_identifiers": missing_identifiers,
            "missing_periods": missing_periods,
            "coverage_note": coverage_note,
            "warnings": warnings,
            "recorded_at": recorded_at,
            "created_by": created_by,
            "workspace_native": True,
        }
        receipt_id = derive_content_id("data-acquisition", seed)
        document = {**seed, "receipt_id": receipt_id}
        document["receipt_hash"] = content_hash(document)
        validate_data_acquisition_receipt(document, expected_receipt_id=receipt_id)
        return cls(receipt_id=receipt_id, document=document)


def record_external_data_result(
    workspace_root: Path | str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Promote one bounded external result into SourceSnapshot, Dataset, and receipt."""

    root = Path(workspace_root).expanduser().resolve()
    _reject_secret_material(args)
    data_need = DataNeed.from_mapping(args.get("data_need"))
    _authenticate_analysis_run(root, data_need)
    principal_id = str(args.get("principal_id") or "")
    source_tier = _choice(args.get("source_tier"), SOURCE_TIERS, "source_tier")
    result_status = _choice(args.get("result_status"), RESULT_STATES, "result_status")
    has_rows = args.get("rows") not in (None, [])
    has_columns = args.get("columns") not in (None, [])
    if has_rows != has_columns:
        raise ValueError("rows and columns must be supplied together")
    storable = result_status in _ROW_RESULT_STATES or (
        result_status == "conflict" and has_rows
    )
    transport = _required_text(args.get("transport"), "transport")
    requested_provider = _required_text(
        args.get("requested_provider"), "requested_provider"
    )
    returned_provider = str(args.get("returned_provider") or "").strip()
    upstream_provider = _required_text(args.get("upstream_provider"), "upstream_provider")
    tool_name = _required_text(args.get("tool_name"), "tool_name")
    route = _required_text(args.get("route"), "route")
    evidence_grade = _choice(args.get("evidence_grade"), EVIDENCE_GRADES, "evidence_grade")
    returned_adjustment_policy = str(
        args.get("returned_adjustment_policy") or ""
    ).strip()
    compatibility_receipt_hash = str(
        args.get("compatibility_receipt_hash") or ""
    ).strip()
    provider_query = _json_object(args.get("provider_query"), "provider_query")
    predecessor_receipt_ids = _normalize_predecessor_receipt_ids(
        args.get("predecessor_receipt_ids")
    )
    skipped_tier_attestations = _normalize_skipped_tier_attestations(
        args.get("skipped_tier_attestations")
    )
    _validate_result_attestation(
        workspace_root=root,
        data_need=data_need,
        source_tier=source_tier,
        storable=storable,
        transport=transport,
        requested_provider=requested_provider,
        returned_provider=returned_provider,
        upstream_provider=upstream_provider,
        tool_name=tool_name,
        route=route,
        provider_query=provider_query,
        evidence_grade=evidence_grade,
        returned_adjustment_policy=returned_adjustment_policy,
        compatibility_receipt_hash=compatibility_receipt_hash,
        principal_id=principal_id,
    )
    warnings = _bounded_messages(args.get("warnings") or [], "warnings")
    fallback_reason = _bounded_single_line(
        args.get("fallback_reason"),
        "fallback_reason",
        max_chars=MAX_FALLBACK_REASON_CHARS,
    )
    coverage_note = _bounded_single_line(
        args.get("coverage_note"),
        "coverage_note",
        max_chars=MAX_COVERAGE_NOTE_CHARS,
    )
    if storable:
        rows = _external_rows(args.get("rows"))
        columns = _external_columns(args.get("columns"), rows)
        missing_fields, missing_identifiers, missing_periods = _validate_result_against_need(
            data_need,
            result_status=result_status,
            rows=rows,
            columns=columns,
            timezone_name=str(args.get("timezone") or "UTC"),
            explicit_missing_fields=args.get("missing_fields"),
            explicit_missing_identifiers=args.get("missing_identifiers"),
            explicit_missing_periods=args.get("missing_periods"),
            coverage_note=coverage_note,
            warnings=warnings,
        )
    else:
        if args.get("rows") not in (None, []) or args.get("columns") not in (None, []):
            raise ValueError("failed external results must not include rows or columns")
        if not fallback_reason:
            raise ValueError("failed external results require fallback_reason")
        rows = []
        columns = []
        missing_fields = list(data_need.fields)
        missing_identifiers = list(data_need.identifiers)
        missing_periods = (
            [{"start": data_need.period_start, "end": data_need.period_end}]
            if data_need.period_start
            else []
        )
        coverage_note = coverage_note or fallback_reason
    _reject_secret_material(
        {
            "transport": transport,
            "requested_provider": requested_provider,
            "returned_provider": returned_provider,
            "upstream_provider": upstream_provider,
            "tool_name": tool_name,
            "route": route,
            "returned_adjustment_policy": returned_adjustment_policy,
            "compatibility_receipt_hash": compatibility_receipt_hash,
            "provider_query": provider_query,
            "columns": columns,
            "rows": rows,
            "warnings": warnings,
            "persisted_metadata": {
                "data_need": data_need.as_dict(),
                "evidence_grade": evidence_grade,
                "fallback_reason": fallback_reason,
                "source_category": args.get("source_category") or "",
                "source_locator": args.get("source_locator") or "",
                "observed_at": args.get("observed_at") or "",
                "published_at": args.get("published_at") or "",
                "revision": args.get("revision") or "",
                "vintage": args.get("vintage") or "",
                "coverage_note": coverage_note,
                "title": args.get("title") or "",
                "description": args.get("description") or "",
                "tags": args.get("tags") or [],
                "instrument_ids": args.get("instrument_ids") or [],
                "symbols": args.get("symbols") or [],
                "universe_membership": args.get("universe_membership") or {},
                "license_notes": args.get("license_notes") or "",
            },
        }
    )
    serialized_rows = canonical_json_bytes(rows)
    if len(serialized_rows) > MAX_EXTERNAL_PAYLOAD_BYTES:
        raise ValueError(
            f"external rows exceed {MAX_EXTERNAL_PAYLOAD_BYTES} encoded bytes"
        )

    schema_hash = stable_hash(columns)
    query_hash = stable_hash(provider_query)
    result_hash = stable_hash(
        rows
        if storable
        else {
            "result_status": result_status,
            "fallback_reason": fallback_reason,
            "warnings": warnings,
        }
    )
    effective_as_of = data_need.as_of or data_need.period_end
    effective_period_start = data_need.period_start or effective_as_of
    effective_period_end = data_need.period_end or effective_as_of
    snapshot_payload = {
        "transport": transport,
        "tool_name": tool_name,
        "route": route,
        "requested_provider": requested_provider,
        "returned_provider": returned_provider,
        "upstream_provider": upstream_provider,
        "requested_adjustment_policy": data_need.adjustment_policy,
        "returned_adjustment_policy": returned_adjustment_policy,
        "compatibility_receipt_hash": compatibility_receipt_hash,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "result_status": result_status,
        "evidence_grade": evidence_grade,
    }
    snapshot_args = {
        "provider": upstream_provider,
        "source_category": str(args.get("source_category") or data_need.data_kind),
        "source_locator": str(args.get("source_locator") or f"provider:{upstream_provider}"),
        "provider_query": provider_query,
        "as_of": effective_as_of,
        "observed_at": str(args.get("observed_at") or ""),
        "published_at": str(args.get("published_at") or ""),
        "revision": str(args.get("revision") or "not_applicable"),
        "vintage": str(args.get("vintage") or "not_applicable"),
        "timezone": str(args.get("timezone") or "UTC"),
        "schema_hash": schema_hash,
        "corporate_action_policy": str(
            args.get("corporate_action_policy") or "not_specified"
        ),
        "price_adjustment_policy": data_need.adjustment_policy,
        "universe_membership": _json_object(
            args.get("universe_membership"), "universe_membership"
        ),
        "delisting_policy": str(args.get("delisting_policy") or "not_specified"),
        "coverage_note": coverage_note
        or "bounded external result promoted by TradingCodex",
        "warnings": warnings,
        "payload": snapshot_payload,
        "principal_id": principal_id,
    }
    attempt_key = _data_attempt_key(
        data_need,
        source_tier=source_tier,
        transport=transport,
        requested_provider=requested_provider,
        tool_name=tool_name,
        route=route,
        compatibility_receipt_hash=compatibility_receipt_hash,
    )
    semantic_key = stable_hash(
        {
            "attempt_key": attempt_key,
            "query_hash": query_hash,
        }
    )
    transaction_id = _promotion_transaction_id(
        data_need=data_need,
        attempt_key=attempt_key,
        semantic_key=semantic_key,
    )
    snapshot_payload.update(
        {
            "acquisition_transaction_id": transaction_id,
            "acquisition_run_id": data_need.run_id,
            "acquisition_family_id": data_need.family_id,
            "acquisition_attempt_key": attempt_key,
            "acquisition_semantic_key": semantic_key,
        }
    )

    snapshot_result: dict[str, Any] | None = None
    dataset_result: dict[str, Any] | None = None
    receipt: DataAcquisitionReceipt | None = None
    receipt_path: Path | None = None
    with exclusive_file_lock(root / DATA_ACQUISITION_LOCK):
        _recover_incomplete_promotions_locked(root)
        existing, attempt_number, corrects_receipt_id = _resolve_attempt(
            root,
            attempt_key=attempt_key,
            semantic_key=semantic_key,
            query_hash=query_hash,
        )
        if existing is not None:
            _claim_data_need_family(
                root,
                data_need,
                principal_id=principal_id,
            )
            return _record_result(root, existing, status="existing")

        family_receipts = _family_receipts(root, data_need)
        (
            predecessor_receipt_ids,
            skipped_tier_attestations,
        ) = _validate_tier_transition(
            data_need=data_need,
            source_tier=source_tier,
            transport=transport,
            requested_provider=requested_provider,
            tool_name=tool_name,
            route=route,
            attempt_key=attempt_key,
            receipts=family_receipts,
            predecessor_receipt_ids=predecessor_receipt_ids,
            skipped_tier_attestations=skipped_tier_attestations,
            rows=rows,
            columns=columns,
            timezone_name=str(args.get("timezone") or "UTC"),
        )
        _claim_data_need_family(
            root,
            data_need,
            principal_id=principal_id,
        )

        if not storable:
            receipt = DataAcquisitionReceipt.build(
                data_need=data_need,
                source_tier=source_tier,
                transport=transport,
                requested_provider=requested_provider,
                returned_provider=returned_provider,
                upstream_provider=upstream_provider,
                tool_name=tool_name,
                route=route,
                requested_adjustment_policy=data_need.adjustment_policy,
                returned_adjustment_policy=returned_adjustment_policy,
                compatibility_receipt_hash=compatibility_receipt_hash,
                schema_hash=schema_hash,
                query_hash=query_hash,
                result_hash=result_hash,
                attempt_key=attempt_key,
                attempt_number=attempt_number,
                corrects_receipt_id=corrects_receipt_id,
                predecessor_receipt_ids=predecessor_receipt_ids,
                skipped_tier_attestations=skipped_tier_attestations,
                semantic_key=semantic_key,
                result_status=result_status,
                fallback_reason=fallback_reason,
                evidence_grade=evidence_grade,
                snapshot_id="",
                dataset_id="",
                row_count=0,
                missing_fields=missing_fields,
                missing_identifiers=missing_identifiers,
                missing_periods=missing_periods,
                coverage_note=coverage_note,
                warnings=warnings,
                created_by=principal_id,
            )
            receipt_path = safe_workspace_path(
                root,
                DATA_ACQUISITION_RECEIPT_ROOT / f"{receipt.receipt_id}.json",
                allowed_roots=(DATA_ACQUISITION_RECEIPT_ROOT,),
            )
            write_immutable_json(receipt_path, receipt.document)
            return _record_result(root, receipt.document, status="recorded")

        prior_snapshot_names = _json_names(root / "trading/research/source-snapshots")
        prior_manifest_names = _json_names(root / DATASET_MANIFEST_ROOT)
        prior_receipt_names = _json_names(root / DATA_ACQUISITION_RECEIPT_ROOT)
        _write_promotion_transaction(
            root,
            transaction_id=transaction_id,
            data_need=data_need,
            attempt_key=attempt_key,
            semantic_key=semantic_key,
            state="prepared",
        )
        try:
            snapshot_result = record_source_snapshot(root, snapshot_args)
            _write_promotion_transaction(
                root,
                transaction_id=transaction_id,
                data_need=data_need,
                attempt_key=attempt_key,
                semantic_key=semantic_key,
                state="snapshot_recorded",
                snapshot_id=snapshot_result["snapshot_id"],
            )
            with tempfile.TemporaryDirectory(prefix="tcx-external-data-") as temporary_dir:
                source = Path(temporary_dir) / "external-result.jsonl"
                source.write_text(
                    "".join(
                        json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)
                        + "\n"
                        for row in rows
                    ),
                    encoding="utf-8",
                )
                identifiers = list(data_need.identifiers)
                dataset_result = record_dataset_snapshot(
                    root,
                    {
                        "source_filename": source.name,
                        "title": str(
                            args.get("title")
                            or f"{upstream_provider} {data_need.data_kind} external result"
                        ),
                        "description": str(args.get("description") or ""),
                        "tags": list(_string_tuple(args.get("tags") or [], "tags")),
                        "provider": upstream_provider,
                        "provider_query": provider_query,
                        "source_snapshot_ids": [snapshot_result["snapshot_id"]],
                        "known_at": snapshot_result["known_at"],
                        "knowledge_cutoff": snapshot_result["known_at"],
                        "as_of": effective_as_of,
                        "vintage": str(args.get("vintage") or effective_as_of),
                        "period_start": effective_period_start,
                        "period_end": effective_period_end,
                        "observed_at": str(args.get("observed_at") or ""),
                        "published_at": str(args.get("published_at") or ""),
                        "timezone": str(args.get("timezone") or "UTC"),
                        "frequency": data_need.frequency,
                        "instrument_ids": list(
                            _string_tuple(args.get("instrument_ids") or [], "instrument_ids")
                        ),
                        "symbols": list(
                            _string_tuple(args.get("symbols") or identifiers, "symbols")
                        ),
                        "universe_membership_policy": str(
                            args.get("universe_membership_policy")
                            or "requested_identifiers_point_in_time"
                        ),
                        "universe_membership": _json_object(
                            args.get("universe_membership"), "universe_membership"
                        ),
                        "columns": columns,
                        "adjustment_policy": data_need.adjustment_policy,
                        "corporate_action_policy": str(
                            args.get("corporate_action_policy") or "not_specified"
                        ),
                        "delisting_policy": str(
                            args.get("delisting_policy") or "not_specified"
                        ),
                        "retention_policy": str(
                            args.get("retention_policy") or "permanent_local"
                        ),
                        "redistribution": str(
                            args.get("redistribution") or "not_specified"
                        ),
                        "license_notes": str(args.get("license_notes") or ""),
                        "data_classification": str(
                            args.get("data_classification") or "public"
                        ),
                        "principal_id": principal_id,
                    },
                    scratch_root=temporary_dir,
                )

            _write_promotion_transaction(
                root,
                transaction_id=transaction_id,
                data_need=data_need,
                attempt_key=attempt_key,
                semantic_key=semantic_key,
                state="dataset_recorded",
                snapshot_id=snapshot_result["snapshot_id"],
                dataset_id=dataset_result["dataset_id"],
            )

            receipt = DataAcquisitionReceipt.build(
                data_need=data_need,
                source_tier=source_tier,
                transport=transport,
                requested_provider=requested_provider,
                returned_provider=returned_provider,
                upstream_provider=upstream_provider,
                tool_name=tool_name,
                route=route,
                requested_adjustment_policy=data_need.adjustment_policy,
                returned_adjustment_policy=returned_adjustment_policy,
                compatibility_receipt_hash=compatibility_receipt_hash,
                schema_hash=schema_hash,
                query_hash=query_hash,
                result_hash=result_hash,
                attempt_key=attempt_key,
                attempt_number=attempt_number,
                corrects_receipt_id=corrects_receipt_id,
                predecessor_receipt_ids=predecessor_receipt_ids,
                skipped_tier_attestations=skipped_tier_attestations,
                semantic_key=semantic_key,
                result_status=result_status,
                fallback_reason=fallback_reason,
                evidence_grade=evidence_grade,
                snapshot_id=snapshot_result["snapshot_id"],
                dataset_id=dataset_result["dataset_id"],
                row_count=len(rows),
                missing_fields=missing_fields,
                missing_identifiers=missing_identifiers,
                missing_periods=missing_periods,
                coverage_note=coverage_note,
                warnings=warnings,
                created_by=principal_id,
            )
            receipt_path = safe_workspace_path(
                root,
                DATA_ACQUISITION_RECEIPT_ROOT / f"{receipt.receipt_id}.json",
                allowed_roots=(DATA_ACQUISITION_RECEIPT_ROOT,),
            )
            _write_promotion_transaction(
                root,
                transaction_id=transaction_id,
                data_need=data_need,
                attempt_key=attempt_key,
                semantic_key=semantic_key,
                state="receipt_recorded",
                snapshot_id=snapshot_result["snapshot_id"],
                dataset_id=dataset_result["dataset_id"],
                receipt_id=receipt.receipt_id,
            )
            write_immutable_json(receipt_path, receipt.document)
        except Exception as exc:
            rollback_errors: list[str] = []
            for operation in (
                (
                    "receipt",
                    lambda: _rollback_new_receipt(
                        root, receipt_path, prior_receipt_names
                    )
                    if receipt_path is not None
                    else None,
                ),
                (
                    "dataset",
                    lambda: _rollback_new_dataset(
                        root, dataset_result, prior_manifest_names
                    )
                    if dataset_result is not None
                    else None,
                ),
                (
                    "snapshot",
                    lambda: _rollback_new_snapshot(
                        root, snapshot_result, prior_snapshot_names
                    )
                    if snapshot_result is not None
                    else None,
                ),
            ):
                try:
                    operation[1]()
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"{operation[0]}:{type(rollback_exc).__name__}:{rollback_exc}"
                    )
            if rollback_errors:
                raise RuntimeError(
                    "external data promotion failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from exc
            _promotion_transaction_path(root, transaction_id).unlink(missing_ok=True)
            raise
        _promotion_transaction_path(root, transaction_id).unlink(missing_ok=True)
    if receipt is None:
        raise RuntimeError("external data promotion completed without a receipt")
    return _record_result(root, receipt.document, status="recorded")


def validate_data_acquisition_receipt(
    value: Any,
    *,
    expected_receipt_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("data acquisition receipt must be an object")
    expected = {
        "schema_version",
        "artifact_type",
        "receipt_id",
        "run_id",
        "family_id",
        "data_need",
        "source_tier",
        "transport",
        "requested_provider",
        "returned_provider",
        "upstream_provider",
        "tool_name",
        "route",
        "requested_adjustment_policy",
        "returned_adjustment_policy",
        "compatibility_receipt_hash",
        "schema_hash",
        "query_hash",
        "result_hash",
        "attempt_key",
        "attempt_number",
        "corrects_receipt_id",
        "predecessor_receipt_ids",
        "skipped_tier_attestations",
        "semantic_key",
        "result_status",
        "fallback_reason",
        "evidence_grade",
        "snapshot_id",
        "dataset_id",
        "row_count",
        "missing_fields",
        "missing_identifiers",
        "missing_periods",
        "coverage_note",
        "warnings",
        "recorded_at",
        "created_by",
        "workspace_native",
        "receipt_hash",
    }
    if set(value) != expected:
        raise ValueError(
            f"data acquisition receipt fields do not match v{DATA_ACQUISITION_SCHEMA_VERSION} schema"
        )
    if value["schema_version"] != DATA_ACQUISITION_SCHEMA_VERSION:
        raise ValueError("data acquisition receipt schema_version is invalid")
    if value["artifact_type"] != "data_acquisition_receipt":
        raise ValueError("data acquisition receipt artifact_type is invalid")
    if value["source_tier"] not in SOURCE_TIERS or value["result_status"] not in RESULT_STATES:
        raise ValueError("data acquisition receipt source tier or result status is invalid")
    data_need = DataNeed.from_mapping(value["data_need"])
    if value["run_id"] != data_need.run_id or value["family_id"] != data_need.family_id:
        raise ValueError(
            "data acquisition receipt run and family must match its DataNeed"
        )
    if value["evidence_grade"] not in EVIDENCE_GRADES:
        raise ValueError("data acquisition receipt evidence_grade is invalid")
    if value["source_tier"] == "user_capability" and not (
        re.fullmatch(
            r"mcp__[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+",
            str(value.get("tool_name") or ""),
        )
        or re.fullmatch(
            r"skill:[A-Za-z0-9_.:-]+",
            str(value.get("tool_name") or ""),
        )
    ):
        raise ValueError(
            "user capability receipt requires an exact MCP tool FQN or skill identity"
        )
    for field in (
        "receipt_id",
        "run_id",
        "family_id",
        "transport",
        "requested_provider",
        "upstream_provider",
        "tool_name",
        "route",
        "requested_adjustment_policy",
        "schema_hash",
        "query_hash",
        "result_hash",
        "attempt_key",
        "semantic_key",
        "evidence_grade",
        "recorded_at",
        "created_by",
        "receipt_hash",
    ):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"data acquisition receipt {field} is required")
    for field in (
        "returned_provider",
        "returned_adjustment_policy",
        "compatibility_receipt_hash",
        "corrects_receipt_id",
    ):
        if not isinstance(value[field], str):
            raise ValueError(f"data acquisition receipt {field} must be a string")
    for field in (
        "schema_hash",
        "query_hash",
        "result_hash",
        "attempt_key",
        "semantic_key",
        "receipt_hash",
    ):
        if re.fullmatch(r"[0-9a-f]{64}", value[field]) is None:
            raise ValueError(f"data acquisition receipt {field} must be a lowercase SHA-256 hash")
    if _RUN_ID.fullmatch(value["run_id"]) is None or _FAMILY_ID.fullmatch(value["family_id"]) is None:
        raise ValueError("data acquisition receipt run or family id is invalid")
    if type(value["attempt_number"]) is not int or value["attempt_number"] not in {1, 2}:
        raise ValueError("data acquisition receipt attempt_number must be 1 or 2")
    if value["attempt_number"] == 1 and value["corrects_receipt_id"]:
        raise ValueError("first data acquisition attempt cannot correct another receipt")
    if value["attempt_number"] == 2 and _RECEIPT_ID.fullmatch(
        value["corrects_receipt_id"]
    ) is None:
        raise ValueError(
            "second data acquisition attempt must bind the corrected receipt"
        )
    predecessor_receipt_ids = _normalize_predecessor_receipt_ids(
        value["predecessor_receipt_ids"]
    )
    if value["receipt_id"] in predecessor_receipt_ids:
        raise ValueError("data acquisition receipt cannot precede itself")
    skipped_tier_attestations = _normalize_skipped_tier_attestations(
        value["skipped_tier_attestations"]
    )
    current_tier_rank = _SOURCE_TIER_RANK[value["source_tier"]]
    if any(
        _SOURCE_TIER_RANK[item["source_tier"]] >= current_tier_rank
        for item in skipped_tier_attestations
    ):
        raise ValueError(
            "data acquisition receipt skipped tiers must have higher priority"
        )
    if value["semantic_key"] != stable_hash(
        {
            "attempt_key": value["attempt_key"],
            "query_hash": value["query_hash"],
        }
    ):
        raise ValueError("data acquisition receipt semantic_key is invalid")
    if value["attempt_key"] != _data_attempt_key(
        data_need,
        source_tier=value["source_tier"],
        transport=value["transport"],
        requested_provider=value["requested_provider"],
        tool_name=value["tool_name"],
        route=value["route"],
        compatibility_receipt_hash=value["compatibility_receipt_hash"],
    ):
        raise ValueError("data acquisition receipt attempt_key is invalid")
    if not isinstance(value["fallback_reason"], str):
        raise ValueError("data acquisition receipt fallback_reason must be a string")
    if not isinstance(value["snapshot_id"], str) or not isinstance(value["dataset_id"], str):
        raise ValueError("data acquisition receipt lineage ids must be strings")
    if (
        type(value["row_count"]) is not int
        or value["row_count"] < 0
        or value["row_count"] > MAX_EXTERNAL_ROWS
    ):
        raise ValueError(
            f"data acquisition receipt row_count must be between 0 and {MAX_EXTERNAL_ROWS}"
        )
    missing_fields = _string_tuple(value["missing_fields"], "missing_fields")
    missing_identifiers = _string_tuple(
        value["missing_identifiers"],
        "missing_identifiers",
    )
    if not set(missing_fields).issubset(set(data_need.fields)):
        raise ValueError(
            "data acquisition receipt missing_fields must be requested fields"
        )
    if not set(missing_identifiers).issubset(set(data_need.identifiers)):
        raise ValueError(
            "data acquisition receipt missing_identifiers must be requested identifiers"
        )
    missing_periods = _normalize_missing_periods(
        value["missing_periods"],
        data_need,
    )
    accepted_source_ids = {
        value["requested_provider"].casefold(),
        (value["returned_provider"] or value["requested_provider"]).casefold(),
        value["transport"].casefold(),
        value["tool_name"].casefold(),
        value["route"].casefold(),
        f"{value['transport']}:{value['requested_provider']}".casefold(),
        (
            f"{value['source_tier']}:{value['transport']}:"
            f"{value['requested_provider']}"
        ).casefold(),
    }
    if (
        data_need.source_policy == "strict"
        and data_need.explicit_source.casefold() not in accepted_source_ids
    ):
        raise ValueError(
            "strict data acquisition receipt source does not match its attestation"
        )
    if value["source_tier"] == "openbb":
        if re.fullmatch(r"[0-9a-f]{64}", value["compatibility_receipt_hash"]) is None:
            raise ValueError(
                "OpenBB data acquisition receipt requires compatibility receipt binding"
            )
    elif value["compatibility_receipt_hash"]:
        raise ValueError(
            "non-OpenBB data acquisition receipt cannot claim compatibility receipt binding"
        )
    if value["requested_adjustment_policy"] != data_need.adjustment_policy:
        raise ValueError(
            "data acquisition receipt requested adjustment policy does not match its DataNeed"
        )
    coverage_note = _bounded_single_line(
        value["coverage_note"],
        "coverage_note",
        max_chars=MAX_COVERAGE_NOTE_CHARS,
    )
    row_bearing = bool(
        value["snapshot_id"] or value["dataset_id"] or value["row_count"]
    )
    if value["result_status"] in _ROW_RESULT_STATES and not row_bearing:
        raise ValueError(
            "complete_valid and partial_valid receipts require promoted row lineage"
        )
    if row_bearing:
        if value["result_status"] not in {*_ROW_RESULT_STATES, "conflict"}:
            raise ValueError("non-row result states cannot claim promoted row lineage")
        if not value["snapshot_id"] or not value["dataset_id"] or value["row_count"] < 1:
            raise ValueError("storable data acquisition receipts require Snapshot, Dataset, and rows")
        if (
            value["returned_provider"] != value["upstream_provider"]
            or value["returned_provider"] != value["requested_provider"]
        ):
            raise ValueError(
                "storable data acquisition receipts require matching requested, returned, and upstream providers"
            )
        if (
            value["requested_adjustment_policy"] != data_need.adjustment_policy
            or value["returned_adjustment_policy"] != data_need.adjustment_policy
        ):
            raise ValueError(
                "storable data acquisition receipts require matching requested and returned adjustment policy"
            )
        if _EVIDENCE_GRADE_RANK[value["evidence_grade"]] < _EVIDENCE_GRADE_RANK[
            data_need.minimum_evidence_grade
        ]:
            raise ValueError(
                "data acquisition receipt evidence grade is below the requested minimum"
            )
        if value["result_status"] == "complete_valid" and (
            missing_fields or missing_identifiers or missing_periods
        ):
            raise ValueError(
                "complete_valid data acquisition receipts cannot have coverage gaps"
            )
        if value["result_status"] == "partial_valid" and not (
            missing_fields or missing_identifiers or missing_periods
        ):
            raise ValueError(
                "partial_valid data acquisition receipts require a structured coverage gap"
            )
        if value["result_status"] == "conflict" and not (
            coverage_note or value["warnings"]
        ):
            raise ValueError(
                "conflict data acquisition receipts must describe the conflict"
            )
    elif value["snapshot_id"] or value["dataset_id"] or value["row_count"] != 0:
        raise ValueError("failed data acquisition receipts must not claim Snapshot or Dataset lineage")
    elif value["evidence_grade"] != "unusable":
        raise ValueError("failed data acquisition receipts require evidence_grade=unusable")
    elif value["upstream_provider"] != value["requested_provider"]:
        raise ValueError(
            "failed data acquisition receipt upstream provider must match requested provider"
        )
    elif value["returned_provider"] not in {"", value["requested_provider"]}:
        raise ValueError(
            "failed data acquisition receipt returned provider must be empty or requested provider"
        )
    elif value["returned_adjustment_policy"] not in {
        "",
        data_need.adjustment_policy,
    }:
        raise ValueError(
            "failed data acquisition receipt adjustment policy must be empty or requested policy"
        )
    elif not value["fallback_reason"].strip():
        raise ValueError("failed data acquisition receipts require fallback_reason")
    elif set(missing_fields) != set(value["data_need"]["fields"]):
        raise ValueError("failed data acquisition receipts must name every requested field as missing")
    elif set(missing_identifiers) != set(value["data_need"]["identifiers"]):
        raise ValueError(
            "failed data acquisition receipts must name every requested identifier as missing"
        )
    elif data_need.period_start and missing_periods != [
        {"start": data_need.period_start, "end": data_need.period_end}
    ]:
        raise ValueError(
            "failed data acquisition receipts must name the complete requested period as missing"
        )
    _bounded_messages(value["warnings"], "warnings")
    if len(value["fallback_reason"]) > MAX_FALLBACK_REASON_CHARS or any(
        ord(character) < 32 for character in value["fallback_reason"]
    ):
        raise ValueError("data acquisition receipt fallback_reason is not bounded")
    _reject_secret_material(
        {
            "fallback_reason": value["fallback_reason"],
            "coverage_note": coverage_note,
            "warnings": value["warnings"],
            "route": value["route"],
            "upstream_provider": value["upstream_provider"],
            "requested_provider": value["requested_provider"],
            "returned_provider": value["returned_provider"],
        },
        path="data_acquisition_receipt",
    )
    if value["workspace_native"] is not True:
        raise ValueError("data acquisition receipt workspace_native must be true")
    normalize_timestamp(value["recorded_at"], "recorded_at")
    seed = {
        key: item
        for key, item in value.items()
        if key not in {"receipt_id", "receipt_hash"}
    }
    expected_id = derive_content_id("data-acquisition", seed)
    if value["receipt_id"] != expected_id or (
        expected_receipt_id is not None and value["receipt_id"] != expected_receipt_id
    ):
        raise ValueError("data acquisition receipt id mismatch")
    if value["receipt_hash"] != content_hash(
        {key: item for key, item in value.items() if key != "receipt_hash"}
    ):
        raise ValueError("data acquisition receipt hash mismatch")
    return value


def validate_data_acquisition_lineage(
    workspace_root: Path | str,
    receipt: dict[str, Any],
) -> None:
    """Authenticate a receipt and its exact SourceSnapshot/Dataset bindings."""

    root = Path(workspace_root).expanduser().resolve()
    validate_data_acquisition_receipt(
        receipt,
        expected_receipt_id=str(receipt.get("receipt_id") or ""),
    )
    if not receipt["snapshot_id"]:
        return
    from tradingcodex_service.application.source_snapshots import (
        validate_source_snapshot,
    )

    snapshot_path = safe_workspace_path(
        root,
        Path("trading/research/source-snapshots")
        / f"{receipt['snapshot_id']}.json",
        allowed_roots=(Path("trading/research/source-snapshots"),),
    )
    source = validate_source_snapshot(
        read_regular_json(snapshot_path, label="data acquisition SourceSnapshot"),
        expected_snapshot_id=receipt["snapshot_id"],
    )
    manifest_path = safe_workspace_path(
        root,
        DATASET_MANIFEST_ROOT / f"{receipt['dataset_id']}.json",
        allowed_roots=(DATASET_MANIFEST_ROOT,),
    )
    manifest = validate_dataset_manifest(
        read_regular_json(manifest_path, label="data acquisition Dataset manifest"),
        expected_dataset_id=receipt["dataset_id"],
    )
    validate_dataset_lineage(root, manifest)
    if receipt["snapshot_id"] not in manifest["source_snapshot_ids"]:
        raise ValueError("data acquisition receipt Dataset does not bind its SourceSnapshot")
    if manifest["payload"]["row_count"] != receipt["row_count"]:
        raise ValueError("data acquisition receipt row_count does not match its Dataset")
    if source["provider"] != receipt["upstream_provider"]:
        raise ValueError("data acquisition receipt provider does not match its SourceSnapshot")
    if manifest["provider"] != receipt["upstream_provider"]:
        raise ValueError("data acquisition receipt provider does not match its Dataset")


def get_data_acquisition_receipt(
    workspace_root: Path | str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Return one authenticated, sanitized receipt selected by exact object id."""

    root = Path(workspace_root).expanduser().resolve()
    unknown = set(args) - {"principal_id", "receipt_id", "dataset_id"}
    if unknown:
        raise ValueError(
            "get_data_acquisition_receipt does not allow additional properties: "
            + ", ".join(sorted(unknown))
        )
    principal_id = str(args.get("principal_id") or "").strip()
    if not principal_id:
        raise PermissionError(
            "get_data_acquisition_receipt requires an authenticated principal"
        )
    from apps.policy.services import BUILTIN_ROLE_IDS, role_for_principal_id

    principal_role = role_for_principal_id(principal_id)
    if principal_role not in BUILTIN_ROLE_IDS:
        raise PermissionError(
            "get_data_acquisition_receipt requires an active TradingCodex role"
        )

    receipt_id = str(args.get("receipt_id") or "").strip()
    dataset_id = str(args.get("dataset_id") or "").strip()
    if not receipt_id and not dataset_id:
        raise ValueError("receipt_id or dataset_id is required")
    if receipt_id and _RECEIPT_ID.fullmatch(receipt_id) is None:
        raise ValueError("receipt_id is invalid")
    if dataset_id and _DATASET_ID.fullmatch(dataset_id) is None:
        raise ValueError("dataset_id is invalid")

    recover_incomplete_data_acquisitions(root)
    receipt: dict[str, Any] | None = None
    if receipt_id:
        receipt_path = safe_workspace_path(
            root,
            DATA_ACQUISITION_RECEIPT_ROOT / f"{receipt_id}.json",
            allowed_roots=(DATA_ACQUISITION_RECEIPT_ROOT,),
        )
        receipt = validate_data_acquisition_receipt(
            read_regular_json(receipt_path, label=f"data acquisition receipt {receipt_id}"),
            expected_receipt_id=receipt_id,
        )
    if dataset_id:
        matches = _receipts_for_exact_dataset(root, dataset_id)
        if not matches:
            raise ValueError(
                f"data acquisition receipt not found for Dataset: {dataset_id}"
            )
        if len(matches) != 1:
            raise ValueError(
                "exact Dataset is bound by multiple data acquisition receipts"
            )
        if receipt is not None and receipt["receipt_id"] != matches[0]["receipt_id"]:
            raise ValueError("receipt_id and dataset_id do not resolve to one receipt")
        receipt = matches[0]
    if receipt is None:
        raise RuntimeError("exact data acquisition receipt resolution failed")

    data_need = DataNeed.from_mapping(receipt["data_need"])
    _authenticate_analysis_run(root, data_need)
    validate_data_acquisition_lineage(root, receipt)

    source: dict[str, Any] = {
        "source_tier": receipt["source_tier"],
        "transport": receipt["transport"],
        "requested_provider": receipt["requested_provider"],
        "returned_provider": receipt["returned_provider"],
        "upstream_provider": receipt["upstream_provider"],
        "tool_name": receipt["tool_name"],
        "route": _sanitized_route(receipt["route"]),
        "source_policy": data_need.source_policy,
        "explicit_source": _sanitized_source_id(data_need.explicit_source),
        "strict_source_verified": data_need.source_policy == "strict",
        "attested_source_ids": sorted(
            {
                receipt["requested_provider"],
                receipt["returned_provider"] or receipt["requested_provider"],
                receipt["transport"],
                receipt["tool_name"],
                _sanitized_route(receipt["route"]),
                f"{receipt['transport']}:{receipt['requested_provider']}",
                (
                    f"{receipt['source_tier']}:{receipt['transport']}:"
                    f"{receipt['requested_provider']}"
                ),
            }
        ),
        "compatibility_receipt_bound": bool(
            receipt["compatibility_receipt_hash"]
        ),
    }
    coverage = {
        "requested": {
            "data_kind": data_need.data_kind,
            "asset_type": data_need.asset_type,
            "identifiers": list(data_need.identifiers),
            "fields": list(data_need.fields),
            "period_start": data_need.period_start,
            "period_end": data_need.period_end,
            "as_of": data_need.as_of,
            "frequency": data_need.frequency,
            "adjustment_policy": data_need.adjustment_policy,
        },
        "row_count": receipt["row_count"],
        "missing_fields": list(receipt["missing_fields"]),
        "missing_identifiers": list(receipt["missing_identifiers"]),
        "missing_periods": list(receipt["missing_periods"]),
        "coverage_note": receipt["coverage_note"],
        "warnings": list(receipt["warnings"]),
    }
    evidence = {
        "result_status": receipt["result_status"],
        "evidence_grade": receipt["evidence_grade"],
        "minimum_evidence_grade": data_need.minimum_evidence_grade,
        "meets_minimum_evidence_grade": _EVIDENCE_GRADE_RANK[
            receipt["evidence_grade"]
        ]
        >= _EVIDENCE_GRADE_RANK[data_need.minimum_evidence_grade],
    }
    lineage: dict[str, Any] = {
        "receipt_hash": receipt["receipt_hash"],
        "schema_hash": receipt["schema_hash"],
        "query_hash": receipt["query_hash"],
        "result_hash": receipt["result_hash"],
        "snapshot_id": receipt["snapshot_id"],
        "dataset_id": receipt["dataset_id"],
        "predecessor_receipt_ids": list(receipt["predecessor_receipt_ids"]),
        "skipped_tier_attestations": list(
            receipt["skipped_tier_attestations"]
        ),
        "corrects_receipt_id": receipt["corrects_receipt_id"],
        "attempt_number": receipt["attempt_number"],
    }
    dataset: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    if receipt["dataset_id"]:
        manifest = get_dataset_manifest(
            root, {"dataset_id": receipt["dataset_id"]}
        )["dataset"]
        dataset = {
            "dataset_id": manifest["dataset_id"],
            "provider": manifest["provider"],
            "as_of": manifest["as_of"],
            "vintage": manifest["vintage"],
            "period_start": manifest["period_start"],
            "period_end": manifest["period_end"],
            "known_at": manifest["known_at"],
            "knowledge_cutoff": manifest["knowledge_cutoff"],
            "frequency": manifest["frequency"],
            "symbols": list(manifest["symbols"]),
            "instrument_ids": list(manifest["instrument_ids"]),
            "columns": list(manifest["columns"]),
            "adjustment_policy": manifest["adjustment_policy"],
            "payload": {
                "sha256": manifest["payload"]["sha256"],
                "row_count": manifest["payload"]["row_count"],
                "format": manifest["payload"]["format"],
            },
            "manifest_hash": manifest["manifest_hash"],
        }
        source_document = get_source_snapshot(
            root, {"snapshot_id": receipt["snapshot_id"]}
        )["snapshot"]
        snapshot = {
            "snapshot_id": source_document["snapshot_id"],
            "provider": source_document["provider"],
            "source_category": source_document["source_category"],
            "as_of": source_document["as_of"],
            "known_at": source_document["known_at"],
            "retrieved_at": source_document["retrieved_at"],
            "recorded_at": source_document["recorded_at"],
            "payload_hash": source_document["payload_hash"],
            "snapshot_hash": source_document["snapshot_hash"],
        }
    return {
        "receipt_id": receipt["receipt_id"],
        "run_id": receipt["run_id"],
        "family_id": receipt["family_id"],
        "recorded_at": receipt["recorded_at"],
        "source": source,
        "evidence": evidence,
        "coverage": coverage,
        "lineage": lineage,
        "dataset": dataset,
        "source_snapshot": snapshot,
        "file_sot": True,
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }


def _receipts_for_exact_dataset(
    root: Path, dataset_id: str
) -> list[dict[str, Any]]:
    receipt_root = root / DATA_ACQUISITION_RECEIPT_ROOT
    if not receipt_root.exists():
        return []
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        raise ValueError("data acquisition receipt root must be a real directory")
    matches: list[dict[str, Any]] = []
    for path in sorted(receipt_root.glob("*.json")):
        receipt = validate_data_acquisition_receipt(
            read_regular_json(path, label="data acquisition receipt"),
            expected_receipt_id=path.stem,
        )
        if receipt["dataset_id"] == dataset_id:
            matches.append(receipt)
    return matches


def _sanitized_route(route: str) -> str:
    parsed = urlsplit(route)
    if parsed.scheme or parsed.netloc:
        return parsed.path or "/"
    return route.split("?", 1)[0].split("#", 1)[0]


def _sanitized_source_id(source_id: str) -> str:
    if source_id.startswith(("http://", "https://", "/")):
        return _sanitized_route(source_id)
    return source_id.split("?", 1)[0].split("#", 1)[0]


def _resolve_attempt(
    root: Path,
    *,
    attempt_key: str,
    semantic_key: str,
    query_hash: str,
) -> tuple[dict[str, Any] | None, int, str]:
    """Resolve idempotence and the single changed correction allowed per source call."""

    receipt_root = root / DATA_ACQUISITION_RECEIPT_ROOT
    if not receipt_root.exists():
        return None, 1, ""
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        raise ValueError("data acquisition receipt root must be a real directory")
    attempts: list[dict[str, Any]] = []
    for path in sorted(receipt_root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("data acquisition receipt must be a regular file")
        receipt = validate_data_acquisition_receipt(
            read_regular_json(path, label="data acquisition receipt")
        )
        if receipt["attempt_key"] == attempt_key:
            validate_data_acquisition_lineage(root, receipt)
            attempts.append(receipt)
    if not attempts:
        return None, 1, ""
    attempts.sort(key=lambda item: item["attempt_number"])
    if [item["attempt_number"] for item in attempts] != list(
        range(1, len(attempts) + 1)
    ) or len(attempts) > 2:
        raise ValueError("data acquisition receipt attempt chain is invalid")

    first = attempts[0]
    if len(attempts) == 2:
        corrected = attempts[1]
        if (
            first["result_status"] != "correctable_error"
            or corrected["corrects_receipt_id"] != first["receipt_id"]
            or corrected["query_hash"] == first["query_hash"]
            or corrected["predecessor_receipt_ids"]
            != first["predecessor_receipt_ids"]
            or corrected["skipped_tier_attestations"]
            != first["skipped_tier_attestations"]
        ):
            raise ValueError("data acquisition corrected-attempt chain is invalid")
        # Once the correction exists it is canonical for this source call. In
        # particular, a replay of the original bad query must not mask a later
        # successful correction.
        return corrected, corrected["attempt_number"], corrected["corrects_receipt_id"]

    if first["semantic_key"] == semantic_key:
        return first, first["attempt_number"], first["corrects_receipt_id"]
    if first["result_status"] == "correctable_error" and first["query_hash"] != query_hash:
        return None, 2, first["receipt_id"]
    return first, first["attempt_number"], first["corrects_receipt_id"]


def _record_result(
    root: Path,
    receipt: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    snapshot_path = (
        (
            Path("trading/research/source-snapshots")
            / f"{receipt['snapshot_id']}.json"
        ).as_posix()
        if receipt["snapshot_id"]
        else ""
    )
    dataset_manifest_path = (
        (DATASET_MANIFEST_ROOT / f"{receipt['dataset_id']}.json").as_posix()
        if receipt["dataset_id"]
        else ""
    )
    return {
        "status": status,
        "receipt_id": receipt["receipt_id"],
        "receipt": receipt,
        "snapshot_id": receipt["snapshot_id"],
        "dataset_id": receipt["dataset_id"],
        "row_count": receipt["row_count"],
        "receipt_path": (
            DATA_ACQUISITION_RECEIPT_ROOT / f"{receipt['receipt_id']}.json"
        ).as_posix(),
        "snapshot_path": snapshot_path,
        "dataset_manifest_path": dataset_manifest_path,
        "file_sot": True,
        "workspace_native": True,
        "workspace_context": workspace_context_payload(root),
    }


def _json_names(root: Path) -> set[str]:
    if not root.exists():
        return set()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"immutable research object root must be a real directory: {root}")
    return {
        path.name
        for path in root.glob("*.json")
        if path.is_file() and not path.is_symlink()
    }


def _rollback_new_receipt(
    root: Path,
    receipt_path: Path,
    prior_receipt_names: set[str],
) -> None:
    if receipt_path.name in prior_receipt_names:
        return
    resolved = safe_workspace_path(
        root,
        DATA_ACQUISITION_RECEIPT_ROOT / receipt_path.name,
        allowed_roots=(DATA_ACQUISITION_RECEIPT_ROOT,),
    )
    if resolved.exists() or resolved.is_symlink():
        if resolved.is_symlink() or not resolved.is_file():
            raise RuntimeError("cannot roll back a non-regular data acquisition receipt")
        resolved.unlink()


def _rollback_new_dataset(
    root: Path,
    dataset_result: dict[str, Any],
    prior_manifest_names: set[str],
) -> None:
    manifest_name = Path(str(dataset_result.get("manifest_path") or "")).name
    if dataset_result.get("status") != "recorded" or manifest_name in prior_manifest_names:
        return
    manifest_path = safe_workspace_path(
        root,
        DATASET_MANIFEST_ROOT / manifest_name,
        allowed_roots=(DATASET_MANIFEST_ROOT,),
    )
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError("cannot roll back a missing or non-regular Dataset manifest")
    manifest = validate_dataset_manifest(
        read_regular_json(manifest_path, label="Dataset rollback manifest"),
        expected_dataset_id=str(dataset_result.get("dataset_id") or ""),
    )
    payload_hash = manifest["payload"]["sha256"]
    manifest_path.unlink()

    manifest_root = root / DATASET_MANIFEST_ROOT
    for candidate in manifest_root.glob("*.json") if manifest_root.exists() else ():
        if candidate.is_symlink() or not candidate.is_file():
            return
        other = validate_dataset_manifest(
            read_regular_json(candidate, label="Dataset manifest during rollback")
        )
        if other["payload"]["sha256"] == payload_hash:
            return
    payload_path = safe_workspace_path(
        root,
        DATASET_OBJECT_ROOT / f"{payload_hash}.parquet",
        allowed_roots=(DATASET_OBJECT_ROOT,),
    )
    if payload_path.exists() or payload_path.is_symlink():
        if (
            payload_path.is_symlink()
            or not payload_path.is_file()
            or file_hash(payload_path) != payload_hash
        ):
            raise RuntimeError("cannot roll back an unauthenticated Dataset payload")
        payload_path.unlink()


def _external_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("rows must be a non-empty array")
    if len(value) > MAX_EXTERNAL_ROWS:
        raise ValueError(f"rows must contain at most {MAX_EXTERNAL_ROWS} items")
    if not all(isinstance(row, dict) and row for row in value):
        raise ValueError("each external result row must be a non-empty object")
    return value


def _validate_result_against_need(
    data_need: DataNeed,
    *,
    result_status: str,
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    timezone_name: str,
    explicit_missing_fields: Any,
    explicit_missing_identifiers: Any,
    explicit_missing_periods: Any,
    coverage_note: str,
    warnings: list[str],
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    try:
        declared_timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone name") from exc

    columns_by_fold = {str(column["name"]).casefold(): column for column in columns}
    requested_by_fold = {field.casefold(): field for field in data_need.fields}
    folded_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        folded_row = {str(key).casefold(): value for key, value in row.items()}
        if len(folded_row) != len(row):
            raise ValueError(f"rows[{index}] has case-insensitive duplicate columns")
        folded_rows.append(folded_row)

    explicit_fields = list(
        _string_tuple(explicit_missing_fields, "missing_fields")
    )
    unknown_missing_fields = sorted(set(explicit_fields) - set(data_need.fields))
    if unknown_missing_fields:
        raise ValueError(
            "missing_fields must be requested fields: "
            + ", ".join(unknown_missing_fields)
        )
    derived_missing_fields = {
        original
        for folded, original in requested_by_fold.items()
        if folded not in columns_by_fold
        or any(row.get(folded) is None for row in folded_rows)
    }
    false_missing_fields = sorted(set(explicit_fields) - derived_missing_fields)
    if false_missing_fields:
        raise ValueError(
            "missing_fields cannot include fields present in every retained row: "
            + ", ".join(false_missing_fields)
        )
    missing_field_set = derived_missing_fields
    missing_fields = [
        field for field in data_need.fields if field in missing_field_set
    ]
    present_requested_values = {
        folded
        for folded in requested_by_fold
        if folded in columns_by_fold
        and any(row.get(folded) is not None for row in folded_rows)
    }
    if result_status == "complete_valid" and missing_fields:
        raise ValueError(
            "complete_valid result is missing requested fields: "
            + ", ".join(missing_fields)
        )
    if result_status in {"partial_valid", "conflict"} and not present_requested_values:
        raise ValueError(
            f"{result_status} result must preserve a non-empty subset of requested fields"
        )

    identifier_name = next(
        (
            name
            for name in (
                "instrument_id",
                "symbol",
                "identifier",
                "ticker",
                "series_id",
                "cik",
                "lei",
                "contract",
                "id",
            )
            if name in columns_by_fold
        ),
        "",
    )
    if not identifier_name:
        raise ValueError(
            "external result requires a declared identifier column to verify data_need.identifiers"
        )
    requested_identifier_map = {
        identifier.casefold(): identifier for identifier in data_need.identifiers
    }
    if len(requested_identifier_map) != len(data_need.identifiers):
        raise ValueError("data_need.identifiers must be unique ignoring case")
    observed_identifiers: set[str] = set()
    row_identifier_keys: list[str] = []
    for index, row in enumerate(folded_rows):
        raw_identifier = row.get(identifier_name)
        if not isinstance(raw_identifier, str) or not raw_identifier.strip():
            raise ValueError(f"rows[{index}].{identifier_name} must be a non-empty string")
        normalized_identifier = raw_identifier.strip().casefold()
        if normalized_identifier not in requested_identifier_map:
            raise ValueError(
                f"rows[{index}].{identifier_name} is not a requested identifier; "
                "conflict status does not authorize foreign identifiers"
            )
        observed_identifiers.add(normalized_identifier)
        row_identifier_keys.append(normalized_identifier)
    explicit_identifiers = list(
        _string_tuple(explicit_missing_identifiers, "missing_identifiers")
    )
    unknown_missing_identifiers = sorted(
        set(explicit_identifiers) - set(data_need.identifiers)
    )
    if unknown_missing_identifiers:
        raise ValueError(
            "missing_identifiers must be requested identifiers: "
            + ", ".join(unknown_missing_identifiers)
        )
    derived_missing_identifiers = {
        original
        for normalized, original in requested_identifier_map.items()
        if normalized not in observed_identifiers
    }
    false_missing_identifiers = sorted(
        set(explicit_identifiers) - derived_missing_identifiers
    )
    if false_missing_identifiers:
        raise ValueError(
            "missing_identifiers cannot include identifiers present in retained rows: "
            + ", ".join(false_missing_identifiers)
        )
    missing_identifier_set = derived_missing_identifiers
    missing_identifiers = [
        identifier
        for identifier in data_need.identifiers
        if identifier in missing_identifier_set
    ]
    if result_status == "complete_valid" and missing_identifiers:
        raise ValueError(
            "complete_valid result is missing requested identifiers: "
            + ", ".join(missing_identifiers)
        )
    missing_periods = _normalize_missing_periods(
        explicit_missing_periods,
        data_need,
    )

    numeric_columns = {
        column["name"]: column["type"]
        for column in columns
        if column["type"] in {"int64", "float64"}
        or str(column["type"]).startswith("decimal128")
    }
    for column in columns:
        currency = str(column.get("currency") or "")
        if currency and re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise ValueError(
                f"dataset column {column['name']} currency must be an uppercase ISO-style code"
            )
    for index, (row, folded_row) in enumerate(zip(rows, folded_rows, strict=True)):
        if result_status == "complete_valid":
            for folded, original in requested_by_fold.items():
                if folded_row.get(folded) is None:
                    raise ValueError(
                        f"complete_valid rows[{index}] has no value for requested field {original}"
                    )
        for name, type_name in numeric_columns.items():
            value = row.get(name)
            if value is None:
                continue
            _finite_numeric(value, field=f"rows[{index}].{name}", type_name=type_name)
        _validate_ohlcv_row(folded_row, index=index)
        if "venue" in columns_by_fold:
            venue = folded_row.get("venue")
            if venue is not None and (not isinstance(venue, str) or not venue.strip()):
                raise ValueError(f"rows[{index}].venue must be a non-empty string")
        if "currency" in columns_by_fold:
            currency_value = folded_row.get("currency")
            if currency_value is not None and (
                not isinstance(currency_value, str)
                or re.fullmatch(r"[A-Z]{3}", currency_value) is None
            ):
                raise ValueError(f"rows[{index}].currency must be an uppercase ISO-style code")

    timestamp_name = next(
        (
            name
            for name in (
                "timestamp",
                "datetime",
                "date",
                "observed_at",
                "as_of",
                "period_end",
                "published_at",
            )
            if name in columns_by_fold
        ),
        "",
    )
    if data_need.data_kind in _PRICE_DATA_KINDS and not timestamp_name:
        raise ValueError("price results require a declared observation-time column")
    if timestamp_name:
        lower_bound = _utc_datetime(data_need.period_start) if data_need.period_start else None
        upper_bound = _utc_datetime(data_need.period_end or data_need.as_of)
        seen: set[tuple[str, str]] = set()
        column_type = str(columns_by_fold[timestamp_name]["type"])
        observations: list[datetime] = []
        for index, (folded_row, identifier_key) in enumerate(
            zip(folded_rows, row_identifier_keys, strict=True)
        ):
            timestamp = folded_row.get(timestamp_name)
            if timestamp in (None, ""):
                raise ValueError(f"rows[{index}].{timestamp_name} is required")
            timestamp_key = _normalized_observation_time(
                timestamp,
                timestamp_name,
                column_type=column_type,
                declared_timezone=declared_timezone,
            )
            observation = _utc_datetime(timestamp_key)
            observations.append(observation)
            if lower_bound is not None and observation < lower_bound:
                raise ValueError(
                    f"rows[{index}].{timestamp_name} is before data_need.period_start"
                )
            if observation > upper_bound:
                bound_name = "period_end" if data_need.period_end else "as_of"
                raise ValueError(
                    f"rows[{index}].{timestamp_name} is after data_need.{bound_name}"
                )
            key = (identifier_key, timestamp_key)
            if key in seen:
                raise ValueError(
                    f"{result_status} result contains duplicate identifier+timestamp observations"
                )
            seen.add(key)
        for missing_period in missing_periods:
            gap_start = _utc_datetime(missing_period["start"])
            gap_end = _utc_datetime(missing_period["end"])
            if any(gap_start <= observation <= gap_end for observation in observations):
                raise ValueError(
                    "missing_periods must not overlap retained observations"
                )

    if result_status == "partial_valid" and not (
        missing_fields or missing_identifiers or missing_periods
    ):
        raise ValueError(
            "partial_valid result requires missing_fields, missing_identifiers, or missing_periods"
        )
    if result_status == "conflict" and not (coverage_note or warnings):
        raise ValueError("conflict result must describe the conflict in coverage_note or warnings")
    if result_status == "complete_valid" and missing_periods:
        raise ValueError("complete_valid result cannot declare missing_periods")
    return missing_fields, missing_identifiers, missing_periods


def _finite_numeric(value: Any, *, field: str, type_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    if type_name == "int64" and type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not numeric.is_finite() or (
        isinstance(value, float) and not math.isfinite(value)
    ):
        raise ValueError(f"{field} must be finite")
    return numeric


def _validate_ohlcv_row(row: dict[str, Any], *, index: int) -> None:
    prices: dict[str, Decimal] = {}
    for name in ("open", "high", "low", "close"):
        value = row.get(name)
        if value is not None:
            prices[name] = _finite_numeric(
                value,
                field=f"rows[{index}].{name}",
                type_name="float64",
            )
    if "high" in prices and "low" in prices and prices["high"] < prices["low"]:
        raise ValueError(f"rows[{index}] OHLC invariant failed: high is below low")
    if "high" in prices:
        for name in ("open", "close"):
            if name in prices and prices["high"] < prices[name]:
                raise ValueError(
                    f"rows[{index}] OHLC invariant failed: high is below {name}"
                )
    if "low" in prices:
        for name in ("open", "close"):
            if name in prices and prices["low"] > prices[name]:
                raise ValueError(
                    f"rows[{index}] OHLC invariant failed: low is above {name}"
                )
    if row.get("volume") is not None:
        volume = _finite_numeric(
            row["volume"],
            field=f"rows[{index}].volume",
            type_name="float64",
        )
        if volume < 0:
            raise ValueError(f"rows[{index}].volume must not be negative")


def _normalized_observation_time(
    value: Any,
    field: str,
    *,
    column_type: str,
    declared_timezone: ZoneInfo,
) -> str:
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        expected = "ISO date" if column_type == "date32" else "ISO datetime"
        raise ValueError(f"{field} must be an {expected}") from exc
    if column_type == "date32" and parsed.time() != datetime.min.time():
        raise ValueError(f"{field} date32 values must not include a time component")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=declared_timezone)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _normalize_missing_periods(
    value: Any,
    data_need: DataNeed,
) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1:
        raise ValueError("missing_periods must contain at most one exact period")
    if value and not data_need.period_start:
        raise ValueError(
            "missing_periods requires data_need.period_start and period_end"
        )
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            raise ValueError("missing_periods items require only start and end")
        start = normalize_timestamp(item.get("start"), "missing_periods.start")
        end = normalize_timestamp(item.get("end"), "missing_periods.end")
        if _utc_datetime(start) > _utc_datetime(end):
            raise ValueError("missing_periods start must not be after end")
        if (
            _utc_datetime(start) < _utc_datetime(data_need.period_start)
            or _utc_datetime(end) > _utc_datetime(data_need.period_end)
        ):
            raise ValueError("missing_periods must stay within the requested period")
        normalized.append({"start": start, "end": end})
    return normalized


def _external_columns(value: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("columns must be a non-empty array")
    names: list[str] = []
    folded_names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    allowed_types = re.compile(
        r"^(?:string|bool|int64|float64|date32|timestamp|decimal128\((\d{1,2}),(\d{1,2})\))$"
    )
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each dataset column must be an object")
        unknown = set(item) - {
            "name",
            "type",
            "nullable",
            "unit",
            "currency",
            "description",
        }
        if unknown:
            raise ValueError(
                "dataset column has unknown fields: " + ", ".join(sorted(unknown))
            )
        name = _required_text(item.get("name"), "columns.name")
        column_type = _required_text(item.get("type"), f"columns.{name}.type")
        match = allowed_types.fullmatch(column_type)
        if match is None:
            raise ValueError(f"columns.{name}.type is unsupported")
        if column_type.startswith("decimal128") and int(match.group(2)) > int(match.group(1)):
            raise ValueError(f"columns.{name}.type decimal scale exceeds precision")
        if name.casefold() in folded_names:
            raise ValueError(f"duplicate dataset column: {name}")
        names.append(name)
        folded_names.add(name.casefold())
        nullable_value = item.get("nullable", True)
        if type(nullable_value) is not bool:
            raise ValueError(f"columns.{name}.nullable must be boolean")
        currency = str(item.get("currency") or "").strip()
        if currency and re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise ValueError(
                f"columns.{name}.currency must be an uppercase ISO-style code"
            )
        normalized.append(
            {
                "name": name,
                "type": column_type,
                "nullable": nullable_value,
                "unit": str(item.get("unit") or "").strip(),
                "currency": currency,
                "description": str(item.get("description") or "").strip(),
            }
        )
    expected = set(names)
    nullable = {item["name"] for item in normalized if item.get("nullable", True) is True}
    for index, row in enumerate(rows):
        unknown = set(row) - expected
        missing_required = expected - set(row) - nullable
        if unknown:
            raise ValueError(f"rows[{index}] has undeclared column: {sorted(unknown)[0]}")
        if missing_required:
            raise ValueError(f"rows[{index}] is missing required column: {sorted(missing_required)[0]}")
    return normalized


def _reject_secret_material(value: Any, *, path: str = "external_result") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text) and item not in (None, "", [], {}):
                if not (
                    key_text.lower().endswith("credential_ref")
                    and isinstance(item, str)
                    and re.fullmatch(r"env:[A-Za-z_][A-Za-z0-9_]*", item)
                ):
                    raise ValueError(f"secret-bearing field is not allowed: {path}.{key_text}")
            _reject_secret_material(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_material(item, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if (
        _BEARER_VALUE.search(value)
        or _HEADER_SECRET_VALUE.search(value)
        or _KNOWN_SECRET_TOKEN.search(value)
    ):
        raise ValueError(f"credential material is not allowed: {path}")
    urls = [value] if value.startswith(("http://", "https://")) else _URL_IN_TEXT.findall(value)
    for candidate in urls:
        parsed = urlsplit(candidate.rstrip(".,);"))
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(f"credential-bearing URL is not allowed: {path}")
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            if _SENSITIVE_KEY.search(key) and item:
                raise ValueError(f"credential-bearing URL query is not allowed: {path}")


def _rollback_new_snapshot(
    root: Path,
    snapshot_result: dict[str, Any],
    prior_snapshot_names: set[str],
) -> None:
    path = root / str(snapshot_result.get("export_path") or "")
    if path.name in prior_snapshot_names:
        return
    snapshot_id = str(snapshot_result.get("snapshot_id") or "")
    manifest_root = root / DATASET_MANIFEST_ROOT
    for candidate in manifest_root.glob("*.json") if manifest_root.exists() else ():
        if candidate.is_symlink() or not candidate.is_file():
            return
        manifest = validate_dataset_manifest(
            read_regular_json(candidate, label="Dataset manifest during snapshot rollback")
        )
        if snapshot_id in manifest["source_snapshot_ids"]:
            return
    receipt_root = root / DATA_ACQUISITION_RECEIPT_ROOT
    for candidate in receipt_root.glob("*.json") if receipt_root.exists() else ():
        if candidate.is_symlink() or not candidate.is_file():
            return
        receipt = validate_data_acquisition_receipt(
            read_regular_json(candidate, label="receipt during snapshot rollback")
        )
        if receipt["snapshot_id"] == snapshot_id:
            return
    resolved = safe_workspace_path(
        root,
        Path("trading/research/source-snapshots") / path.name,
        allowed_roots=(Path("trading/research/source-snapshots"),),
    )
    if not resolved.exists() and not resolved.is_symlink():
        return
    if resolved.is_symlink() or not resolved.is_file():
        raise RuntimeError("cannot roll back a missing or non-regular SourceSnapshot")
    resolved.unlink()


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _choice(value: Any, choices: frozenset[str], field: str) -> str:
    text = _required_text(value, field)
    if text not in choices:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(choices))}")
    return text


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be an array of non-empty strings")
    normalized = tuple(item.strip() for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _bounded_messages(value: Any, field: str) -> list[str]:
    messages = list(_string_tuple(value, field))
    if len(messages) > 20:
        raise ValueError(f"{field} must contain at most 20 items")
    for message in messages:
        if len(message) > 300 or any(ord(character) < 32 for character in message):
            raise ValueError(f"{field} items must be single-line strings of at most 300 characters")
    return messages


def _bounded_single_line(value: Any, field: str, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_chars:
        raise ValueError(f"{field} must not exceed {max_chars} characters")
    if any(ord(character) < 32 for character in text):
        raise ValueError(f"{field} must be a single-line string")
    return text


def _json_object(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    canonical_json_bytes(value)
    return value
