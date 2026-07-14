from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from tradingcodex_service.application.audit import write_policy_decision_if_available
from tradingcodex_service.application.common import _number, _parse_datetime
from tradingcodex_service.application.execution_gateway import (
    NATIVE_CANCEL_ACTION,
    NATIVE_SUBMIT_ACTION,
    NATIVE_USER_PRINCIPAL_ID,
)
from tradingcodex_service.application.portfolio import currency_quantum
from tradingcodex_service.application.runtime import (
    base_currency_for_workspace,
    ensure_runtime_database,
    normalize_currency_code,
    workspace_context_payload,
)

LIVE_EXECUTION_POSTURES = {"live_broker"}
SUPPORTED_EXECUTION_POSTURES = {"paper_only", "broker_validation_only", *LIVE_EXECUTION_POSTURES}
EXECUTION_POLICY_FIELDS = {
    "max_single_order_base",
    "enabled_adapters",
    "enabled_execution_postures",
    "live_enabled",
}
EXPLICIT_DENY_ACTIONS = {
    "api_key.read",
    "api_key.rotate",
    "secret.read",
    "broker.raw_api",
    "broker_api.direct_call",
    "approval.self_issue",
    "approval_receipt.self_issue",
    "execute_order",
    "order.execute",
    "trade.execute",
    "trading.execute",
    "cash.withdraw",
    "cash.transfer",
    "permissions.write",
    "policy.write",
    "mcp.tradingcodex.write_policy_and_execute",
    "mcp.tradingcodex.submit_approved_order",
    "mcp.tradingcodex.cancel_submitted_order",
}


@dataclass(frozen=True)
class RuntimePolicy:
    max_single_order_base: int
    allowed_adapters: frozenset[str]
    allowed_execution_postures: frozenset[str]
    live_enabled: bool
    source: tuple[str, ...]


class PolicyConfigurationError(ValueError):
    pass


def _validate_execution_postures(values: list[str], field: str) -> set[str]:
    unsupported = sorted(set(values) - SUPPORTED_EXECUTION_POSTURES)
    if unsupported:
        raise PolicyConfigurationError(f"{field} contains unsupported execution posture(s): {', '.join(unsupported)}")
    return set(values)


def read_runtime_policy(workspace_root: Path | str) -> RuntimePolicy:
    root = Path(workspace_root)
    config_data = _read_yaml_mapping(root / ".tradingcodex" / "config.yaml", required=True)
    execution = config_data.get("execution")
    if not isinstance(execution, dict):
        raise PolicyConfigurationError("config.execution must be a mapping")
    missing = sorted(EXECUTION_POLICY_FIELDS - set(execution))
    unknown = sorted(set(execution) - EXECUTION_POLICY_FIELDS)
    if missing:
        raise PolicyConfigurationError(f"config.execution is missing required field(s): {', '.join(missing)}")
    if unknown:
        raise PolicyConfigurationError(f"config.execution contains unsupported field(s): {', '.join(unknown)}")

    max_single_order = execution["max_single_order_base"]
    if not isinstance(max_single_order, int) or isinstance(max_single_order, bool) or max_single_order < 0:
        raise PolicyConfigurationError("config.execution.max_single_order_base must be an integer >= 0")
    configured_adapters = execution["enabled_adapters"]
    if not isinstance(configured_adapters, list) or not all(isinstance(item, str) and item for item in configured_adapters):
        raise PolicyConfigurationError("config.execution.enabled_adapters must be a string list")
    configured_postures = execution["enabled_execution_postures"]
    if not isinstance(configured_postures, list) or not all(isinstance(item, str) and item for item in configured_postures):
        raise PolicyConfigurationError("config.execution.enabled_execution_postures must be a string list")
    live_enabled = execution["live_enabled"]
    if not isinstance(live_enabled, bool):
        raise PolicyConfigurationError("config.execution.live_enabled must be a boolean")
    allowed_execution_postures = _validate_execution_postures(
        configured_postures,
        "config.execution.enabled_execution_postures",
    )
    if not live_enabled:
        allowed_execution_postures -= LIVE_EXECUTION_POSTURES

    return RuntimePolicy(
        max_single_order,
        frozenset(configured_adapters),
        frozenset(allowed_execution_postures),
        live_enabled,
        (".tradingcodex/config.yaml",),
    )


def read_restricted_symbols(workspace_root: Path | str) -> set[str]:
    symbols: set[str] = set()
    try:
        ensure_runtime_database(workspace_root)
        from apps.policy.models import RestrictedSymbol

        symbols.update(symbol.upper() for symbol in RestrictedSymbol.objects.filter(active=True).values_list("symbol", flat=True))
    except Exception as exc:
        raise PolicyConfigurationError(f"restricted symbol DB unavailable: {exc}") from exc
    data = _read_yaml_mapping(
        Path(workspace_root) / ".tradingcodex" / "policies" / "restricted-list.yaml",
        required=True,
    )
    if set(data) != {"restricted_symbols"}:
        raise PolicyConfigurationError("restricted-list policy must contain only restricted_symbols")
    configured = data["restricted_symbols"]
    if not isinstance(configured, list) or not all(isinstance(item, str) and item for item in configured):
        raise PolicyConfigurationError("restricted_symbols must be a string list")
    symbols.update(symbol.upper() for symbol in configured)
    return symbols


def _read_yaml_mapping(path: Path, *, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise PolicyConfigurationError(f"required policy configuration is missing: {path}")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PolicyConfigurationError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PolicyConfigurationError(f"{path} must contain a YAML mapping")
    return data


def evaluate_policy(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.policy.services import capability_check, sync_builtin_principals_and_capabilities
    from tradingcodex_service.application.orders import resolve_canonical_approval_receipt, resolve_order_ticket_payload

    sync_builtin_principals_and_capabilities()
    reasons: list[str] = []
    try:
        policy = read_runtime_policy(workspace_root)
    except PolicyConfigurationError as exc:
        policy = RuntimePolicy(0, frozenset(), frozenset(), False, ("invalid-runtime-policy",))
        reasons.append(f"runtime policy invalid: {exc}")
    order = resolve_order_ticket_payload(Path(workspace_root), args)
    receipt = resolve_canonical_approval_receipt(Path(workspace_root), args, order)
    principal_id = args.get("principal_id") or "unknown"
    action = args.get("action") or "unknown"
    capability_allowed, capability_reasons = capability_check(principal_id, action, args.get("resource"))
    if not capability_allowed:
        reasons.extend(capability_reasons)

    if action in EXPLICIT_DENY_ACTIONS:
        reasons.append(f"explicit deny action: {action}")
    if action.startswith(("broker_api.", "broker.")):
        reasons.append("direct broker API actions are explicitly denied")
    if action != NATIVE_SUBMIT_ACTION and "live" in action.lower() and re.search(r"order|execution|submit|broker", action.lower()):
        reasons.append("live execution must enter the approved submit_approved_order service boundary")
    if action != NATIVE_SUBMIT_ACTION and "live" in str(args.get("resource") or "").lower() and re.search(r"order|execution|submit|broker", action.lower()):
        reasons.append("live execution resources require the approved TradingCodex service boundary")
    if action in {"approval.create", "approval_receipt.create"} and principal_id != "risk-manager":
        reasons.append("only risk-manager can create approval receipts")
    if action in {NATIVE_SUBMIT_ACTION, NATIVE_CANCEL_ACTION} and principal_id != NATIVE_USER_PRINCIPAL_ID:
        reasons.append("only a native-user mandate can request order submission or cancellation")
    if action == "mcp.tradingcodex.discard_draft_order" and principal_id != "portfolio-manager":
        reasons.append("only portfolio-manager can discard draft orders")
    if order.get("broker_id"):
        broker_allowed, broker_reason = _broker_allowed_by_policy(workspace_root, str(order["broker_id"]), policy)
        if not broker_allowed:
            reasons.append(broker_reason)

    has_order_money = any(
        order.get(field) not in (None, "")
        for field in ("symbol", "quantity", "limit_price", "currency", "estimated_notional", "native_notional")
    )
    notional = _number(order.get("estimated_notional"))
    if has_order_money and (notional is None or notional <= 0):
        reasons.append("estimated_notional must be a positive number")
    elif notional is not None and notional > policy.max_single_order_base:
        reasons.append(f"estimated_notional exceeds {policy.max_single_order_base}")
    reasons.extend(_money_contract_reasons(order, base_currency_for_workspace(workspace_root)))

    try:
        restricted_symbols = read_restricted_symbols(workspace_root)
    except PolicyConfigurationError as exc:
        restricted_symbols = set()
        reasons.append(f"restricted-list policy invalid: {exc}")
    if order.get("symbol") and str(order["symbol"]).upper() in restricted_symbols:
        reasons.append(f"symbol is restricted: {order['symbol']}")
    if args.get("require_approval_check") and receipt.get("valid") is not True:
        reasons.append("approval_receipt.valid == false")

    decision = "allow" if not reasons else "deny"
    result = {
        "decision": decision,
        "reasons": reasons,
        "enforced_by": ["TradingCodex service policy"],
        "policy_source": list(policy.source),
        "principal_id": principal_id,
        "action": action,
        "resource": args.get("resource"),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }
    write_policy_decision_if_available(workspace_root, result)
    return result


def _money_contract_reasons(order: dict[str, Any], configured_base_currency: str) -> list[str]:
    reasons: list[str] = []
    if not any(
        order.get(field) not in (None, "")
        for field in ("currency", "base_currency", "estimated_notional", "native_notional", "fx_rate")
    ):
        return reasons
    try:
        currency = normalize_currency_code(order.get("currency") or configured_base_currency)
        base_currency = normalize_currency_code(order.get("base_currency") or configured_base_currency, "base_currency")
    except ValueError as exc:
        return [str(exc)]
    if base_currency != configured_base_currency:
        reasons.append(f"base_currency must match the paper account scope ({configured_base_currency})")
    required = ("native_notional", "fx_rate", "fx_source_snapshot_id", "fx_as_of")
    for field in required:
        if order.get(field) in (None, ""):
            reasons.append(f"money contract missing {field}")
    if currency != base_currency:
        fx_as_of = _parse_datetime(order.get("fx_as_of"))
        if fx_as_of is not None:
            age = (datetime.now(timezone.utc) - fx_as_of).total_seconds()
            maximum = int(os.environ.get("TRADINGCODEX_MAX_FX_AGE_SECONDS", "86400"))
            if age < -300 or age > maximum:
                reasons.append("foreign-currency FX quote is future-dated or stale")
        elif order.get("fx_as_of") not in (None, ""):
            reasons.append("fx_as_of must be an ISO-8601 datetime")
    try:
        native = Decimal(str(order.get("native_notional")))
        rate = Decimal(str(order.get("fx_rate")))
        base = Decimal(str(order.get("estimated_notional")))
    except (InvalidOperation, ValueError):
        if all(order.get(field) not in (None, "") for field in ("native_notional", "fx_rate", "estimated_notional")):
            reasons.append("money contract values must be finite decimals")
    else:
        if not all(value.is_finite() and value > 0 for value in (native, rate, base)):
            reasons.append("money contract values must be positive finite decimals")
        elif abs((native * rate) - base) > currency_quantum(base_currency):
            reasons.append("base notional does not reconcile to native_notional * fx_rate")
    return reasons


def _broker_allowed_by_policy(workspace_root: Path | str, broker_id: str, policy: RuntimePolicy) -> tuple[bool, str]:
    if broker_id not in policy.allowed_adapters:
        return False, f"adapter not enabled: {broker_id}"
    if broker_id == "paper-trading":
        return True, ""
    try:
        from apps.integrations.models import BrokerConnection

        connection = BrokerConnection.objects.filter(broker_id=broker_id).first()
    except Exception as exc:
        return False, f"adapter not enabled: {broker_id} (broker registry unavailable: {exc})"
    if connection is None:
        return False, f"adapter not enabled: {broker_id}"
    metadata = connection.metadata if isinstance(connection.metadata, dict) else {}
    profile = metadata.get("capability_profile") if isinstance(metadata.get("capability_profile"), dict) else {}
    posture = str(profile.get("execution_posture") or "")
    if posture not in policy.allowed_execution_postures:
        return False, f"execution posture not enabled: {broker_id} ({posture or 'unknown'})"
    if connection.status != "trading_enabled":
        return False, f"broker connection is not trading_enabled: {broker_id}"
    if not connection.enabled_trade_scopes:
        return False, f"broker connection has no enabled trade scopes: {broker_id}"
    return True, ""


def simulate_policy(workspace_root: Path | str, args: dict[str, Any]) -> dict[str, Any]:
    return evaluate_policy(workspace_root, args)
