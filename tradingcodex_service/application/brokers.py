from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.utils import timezone as django_timezone

from tradingcodex_service.application.audit import write_audit_event_if_available
from tradingcodex_service.application.common import stable_hash
from tradingcodex_service.application.portfolio import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_PAPER_CASH_KRW,
    DEFAULT_PORTFOLIO_ID,
    DEFAULT_STRATEGY_ID,
    load_paper_portfolio_state,
    portfolio_keys,
)
from tradingcodex_service.application.runtime import ensure_runtime_database, workspace_context_payload


@dataclass(frozen=True)
class BrokerHealth:
    status: str
    message: str = ""


@dataclass(frozen=True)
class BrokerAccountDTO:
    broker_account_id: str
    account_label: str
    account_type: str = "paper"
    base_currency: str = "KRW"
    masked_identifier: str = "paper"
    trading_enabled: bool = False
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class CashDTO:
    currency: str
    amount: float


@dataclass(frozen=True)
class PositionDTO:
    symbol: str
    quantity: float
    average_price: float = 0
    currency: str = "KRW"
    instrument_id: str = ""


@dataclass(frozen=True)
class BrokerOrderDTO:
    broker_order_id: str
    broker_status: str
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class FillDTO:
    fill_id: str
    broker_order_id: str
    quantity: float
    price: float
    currency: str = "KRW"
    fee: float = 0
    filled_at: str = ""


@dataclass(frozen=True)
class OrderValidationResult:
    valid: bool
    reasons: list[str]
    payload: dict[str, Any] | None = None


class BrokerAdapter:
    adapter_type = "base"

    def health_check(self) -> BrokerHealth:
        raise NotImplementedError

    def discover_accounts(self) -> list[BrokerAccountDTO]:
        raise NotImplementedError

    def get_cash(self, account_id: str) -> list[CashDTO]:
        raise NotImplementedError

    def get_positions(self, account_id: str) -> list[PositionDTO]:
        raise NotImplementedError

    def get_orders(self, account_id: str) -> list[BrokerOrderDTO]:
        return []

    def get_fills(self, account_id: str) -> list[FillDTO]:
        return []

    def validate_order(self, order: dict[str, Any]) -> OrderValidationResult:
        return OrderValidationResult(True, [])

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("adapter does not support submit_order")

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        return {"status": "not_supported", "broker_order_id": broker_order_id}

    def get_order_status(self, broker_order_id: str) -> dict[str, Any]:
        return {"status": "local-only", "broker_order_id": broker_order_id}


class PaperBrokerAdapter(BrokerAdapter):
    adapter_type = "paper"

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root or ".").resolve()

    def health_check(self) -> BrokerHealth:
        return BrokerHealth("ok", "local paper broker adapter is available")

    def discover_accounts(self) -> list[BrokerAccountDTO]:
        return [
            BrokerAccountDTO(
                broker_account_id=DEFAULT_ACCOUNT_ID,
                account_label="Local Paper Account",
                account_type="paper",
                base_currency="KRW",
                masked_identifier="paper",
                trading_enabled=True,
                metadata={"default_cash_krw": DEFAULT_PAPER_CASH_KRW},
            )
        ]

    def get_cash(self, account_id: str) -> list[CashDTO]:
        portfolio_id, _, strategy_id = portfolio_keys({"account_id": account_id}, self.workspace_root)
        state = load_paper_portfolio_state(self.workspace_root, portfolio_id, account_id, strategy_id)
        return [CashDTO(currency="KRW", amount=float(state.get("cash_krw", 0)))]

    def get_positions(self, account_id: str) -> list[PositionDTO]:
        portfolio_id, _, strategy_id = portfolio_keys({"account_id": account_id}, self.workspace_root)
        state = load_paper_portfolio_state(self.workspace_root, portfolio_id, account_id, strategy_id)
        positions = state.get("positions") if isinstance(state.get("positions"), dict) else {}
        return [
            PositionDTO(
                symbol=str(symbol).upper(),
                quantity=float(position.get("quantity", 0)),
                average_price=float(position.get("average_price", 0)),
                currency=str(position.get("currency") or "KRW"),
                instrument_id=str(position.get("instrument_id") or symbol).upper(),
            )
            for symbol, position in sorted(positions.items())
            if float(position.get("quantity", 0)) != 0
        ]

    def validate_order(self, order: dict[str, Any]) -> OrderValidationResult:
        reasons: list[str] = []
        side = str(order.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            reasons.append("side must be buy or sell")
        quantity = _float(order.get("quantity"))
        price = _float(order.get("limit_price") or order.get("estimated_price"))
        if quantity is None or quantity <= 0:
            reasons.append("quantity must be positive")
        if price is None or price <= 0:
            reasons.append("limit_price must be positive")
        if side == "buy" and quantity and price:
            cash = sum(item.amount for item in self.get_cash(str(order.get("account_id") or DEFAULT_ACCOUNT_ID)))
            if cash < quantity * price:
                reasons.append(f"insufficient paper cash: required {quantity * price}, available {cash}")
        if side == "sell" and quantity:
            symbol = str(order.get("symbol") or "").upper()
            available = next((item.quantity for item in self.get_positions(str(order.get("account_id") or DEFAULT_ACCOUNT_ID)) if item.symbol == symbol), 0)
            if available < quantity:
                reasons.append(f"insufficient paper position: required {quantity}, available {available}")
        return OrderValidationResult(not reasons, reasons, {"adapter": "paper-trading"})

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        from tradingcodex_service.application.portfolio import submit_paper_order

        return submit_paper_order(self.workspace_root, order)


class ExternalMcpBrokerAdapter(BrokerAdapter):
    adapter_type = "external_mcp"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def health_check(self) -> BrokerHealth:
        status = "ok" if self.connection.status in {"read_only", "trading_locked", "trading_enabled"} else "disabled"
        return BrokerHealth(status, "external MCP broker is manifest-backed; raw execution proxy is not available")

    def discover_accounts(self) -> list[BrokerAccountDTO]:
        accounts = self.connection.metadata.get("accounts") if isinstance(self.connection.metadata, dict) else None
        if not isinstance(accounts, list):
            return []
        return [
            BrokerAccountDTO(
                broker_account_id=str(item.get("broker_account_id") or item.get("id") or ""),
                account_label=str(item.get("account_label") or item.get("label") or ""),
                account_type=str(item.get("account_type") or "brokerage"),
                base_currency=str(item.get("base_currency") or "USD"),
                masked_identifier=str(item.get("masked_identifier") or ""),
                trading_enabled=False,
                metadata=item if isinstance(item, dict) else {},
            )
            for item in accounts
            if isinstance(item, dict) and (item.get("broker_account_id") or item.get("id"))
        ]

    def get_cash(self, account_id: str) -> list[CashDTO]:
        return []

    def get_positions(self, account_id: str) -> list[PositionDTO]:
        return []


class NativeApiBrokerAdapter(BrokerAdapter):
    adapter_type = "native_api"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def health_check(self) -> BrokerHealth:
        return BrokerHealth("disabled", "native API broker adapters are manifest-backed and disabled until reviewed")

    def discover_accounts(self) -> list[BrokerAccountDTO]:
        return []

    def get_cash(self, account_id: str) -> list[CashDTO]:
        return []

    def get_positions(self, account_id: str) -> list[PositionDTO]:
        return []


class ManualBrokerAdapter(BrokerAdapter):
    adapter_type = "manual"

    def health_check(self) -> BrokerHealth:
        return BrokerHealth("ok", "manual broker adapter is read-only and import-backed")

    def discover_accounts(self) -> list[BrokerAccountDTO]:
        return []

    def get_cash(self, account_id: str) -> list[CashDTO]:
        return []

    def get_positions(self, account_id: str) -> list[PositionDTO]:
        return []


def adapter_for_connection(connection: Any, workspace_root: Path | str | None = None) -> BrokerAdapter:
    if connection.adapter_type == "paper" or connection.transport == "paper" or connection.broker_id == "paper-trading":
        return PaperBrokerAdapter(workspace_root)
    if connection.transport == "mcp":
        return ExternalMcpBrokerAdapter(connection)
    if connection.transport == "api" or connection.adapter_type == "native_api":
        return NativeApiBrokerAdapter(connection)
    if connection.transport == "manual" or connection.adapter_type == "manual":
        return ManualBrokerAdapter()
    raise ValueError(f"Unsupported broker adapter type: {connection.adapter_type}")


def ensure_paper_broker_connection(workspace_root: Path | str | None = None, actor: str = "service") -> Any:
    ensure_runtime_database(workspace_root)
    from apps.integrations.models import BrokerAccount, BrokerConnection

    connection, created = BrokerConnection.objects.update_or_create(
        broker_id="paper-trading",
        defaults={
            "display_name": "Paper",
            "transport": "paper",
            "adapter_type": "paper",
            "status": "trading_enabled",
            "credential_ref": "",
            "capabilities": [
                "account.cash.read",
                "account.positions.read",
                "order.validate",
                "order.submit.paper",
                "order.status.read",
            ],
            "enabled_read_scopes": ["account.cash.read", "account.positions.read", "order.status.read"],
            "enabled_trade_scopes": ["order.submit.paper"],
            "trust_level": "built_in",
            "last_health_status": "ok",
            "drift_status": "none",
            "metadata": {"live_execution": False, "paper_only": True},
        },
    )
    BrokerAccount.objects.update_or_create(
        broker_connection=connection,
        broker_account_id=DEFAULT_ACCOUNT_ID,
        defaults={
            "account_label": "Local Paper Account",
            "account_type": "paper",
            "base_currency": "KRW",
            "masked_identifier": "paper",
            "trading_enabled": True,
            "last_seen_at": django_timezone.now(),
            "metadata": {"portfolio_id": DEFAULT_PORTFOLIO_ID, "strategy_id": DEFAULT_STRATEGY_ID},
        },
    )
    if created and actor not in {"service", "read", "system-read"}:
        _audit("broker_connection.created", {"broker_id": connection.broker_id, "status": connection.status}, actor, workspace_root)
    return connection


def create_external_mcp_broker_connection(
    workspace_root: Path | str | None,
    *,
    broker_id: str,
    display_name: str,
    router_name: str,
    discovery_payload: str | dict[str, Any] | None = None,
    credential_ref: str = "",
    actor: str = "web",
) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.integrations.models import BrokerConnection
    from apps.mcp.models import McpRouter
    from apps.mcp.services import create_or_update_router, import_external_mcp_discovery

    router = McpRouter.objects.filter(name=router_name).first()
    if router is None:
        router = create_or_update_router(name=router_name, label=display_name, transport="stdio", credential_ref=credential_ref, enabled=False, actor=actor)
    imported = {"imported": 0, "tool_ids": []}
    if discovery_payload:
        imported = import_external_mcp_discovery(router, discovery_payload, actor=actor)
    connection, created = BrokerConnection.objects.update_or_create(
        broker_id=broker_id,
        defaults={
            "display_name": display_name,
            "transport": "mcp",
            "adapter_type": "external_mcp",
            "status": "read_only",
            "credential_ref": credential_ref,
            "capabilities": _capabilities_for_router(router),
            "enabled_read_scopes": _enabled_read_scopes_for_router(router),
            "enabled_trade_scopes": [],
            "trust_level": "unreviewed",
            "last_health_status": "not_checked",
            "drift_status": "review_required",
            "metadata": {"router": router.name, "execution_enabled": False},
        },
    )
    _audit(
        "broker_connection.mcp_imported" if created else "broker_connection.mcp_updated",
        {"broker_id": connection.broker_id, "router": router.name, "imported": imported.get("imported", 0)},
        actor,
        workspace_root,
    )
    return {"broker_id": connection.broker_id, "router": router.name, "imported": imported, "status": connection.status}


def list_broker_connections(workspace_root: Path | str | None = None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.integrations.models import BrokerConnection

    ensure_paper_broker_connection(workspace_root)
    return {
        "connections": [_serialize_connection(connection) for connection in BrokerConnection.objects.prefetch_related("accounts").all()],
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def get_broker_connection_status(workspace_root: Path | str | None, args: dict[str, Any]) -> dict[str, Any]:
    connection = _get_connection(workspace_root, args.get("broker_id") or args.get("broker_connection_id") or "paper-trading")
    adapter = adapter_for_connection(connection, workspace_root)
    health = adapter.health_check()
    connection.last_health_status = health.status
    connection.save(update_fields=["last_health_status", "updated_at"])
    return {
        "connection": _serialize_connection(connection),
        "health": asdict(health),
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def sync_broker_account(workspace_root: Path | str | None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(args or {})
    connection = _get_connection(workspace_root, args.get("broker_id") or args.get("broker_connection_id") or "paper-trading")
    if connection.status not in {"read_only", "trading_locked", "trading_enabled"}:
        raise ValueError(f"broker connection is not enabled for read sync: {connection.broker_id}")
    adapter = adapter_for_connection(connection, workspace_root)
    ensure_runtime_database(workspace_root)
    from apps.integrations.models import BrokerAccount
    from apps.portfolio.models import BrokerSyncRun

    started_at = django_timezone.now()
    sync_run = BrokerSyncRun.objects.create(broker_connection=connection, status="started", started_at=started_at)
    accounts = adapter.discover_accounts()
    requested_account = str(args.get("broker_account_id") or args.get("account_id") or "")
    synced_accounts: list[dict[str, Any]] = []
    warnings: list[str] = []
    cash_count = 0
    positions_count = 0
    try:
        for account_dto in accounts:
            if requested_account and account_dto.broker_account_id != requested_account:
                continue
            broker_account, _ = BrokerAccount.objects.update_or_create(
                broker_connection=connection,
                broker_account_id=account_dto.broker_account_id,
                defaults={
                    "account_label": account_dto.account_label,
                    "account_type": account_dto.account_type,
                    "base_currency": account_dto.base_currency,
                    "masked_identifier": account_dto.masked_identifier,
                    "trading_enabled": account_dto.trading_enabled and connection.status == "trading_enabled",
                    "last_seen_at": django_timezone.now(),
                    "metadata": account_dto.metadata or {},
                },
            )
            cash = adapter.get_cash(account_dto.broker_account_id)
            positions = adapter.get_positions(account_dto.broker_account_id)
            snapshot = materialize_portfolio_snapshot_from_broker_state(
                workspace_root,
                connection=connection,
                broker_account=broker_account,
                cash=cash,
                positions=positions,
                sync_run_id=sync_run.id,
            )
            reconciliation = create_reconciliation_summary(connection, broker_account, snapshot, cash, positions)
            cash_count += len(cash)
            positions_count += len(positions)
            synced_accounts.append(
                {
                    "broker_account_id": broker_account.broker_account_id,
                    "snapshot_id": snapshot.id,
                    "reconciliation_id": reconciliation.id,
                    "reconciliation_status": reconciliation.status,
                }
            )
        if requested_account and not synced_accounts:
            warnings.append(f"broker account not discovered: {requested_account}")
        sync_run.status = "warning" if warnings else "ok"
        sync_run.pulled_cash_count = cash_count
        sync_run.pulled_positions_count = positions_count
        sync_run.warnings = warnings
        sync_run.payload_hash = stable_hash({"accounts": synced_accounts, "warnings": warnings})
        sync_run.finished_at = django_timezone.now()
        sync_run.save()
        connection.last_sync_at = sync_run.finished_at
        connection.last_health_status = adapter.health_check().status
        connection.save(update_fields=["last_sync_at", "last_health_status", "updated_at"])
    except Exception as exc:
        sync_run.status = "error"
        sync_run.error = str(exc)
        sync_run.finished_at = django_timezone.now()
        sync_run.save(update_fields=["status", "error", "finished_at"])
        _audit("broker_sync.failed", {"broker_id": connection.broker_id, "error": str(exc)}, str(args.get("principal_id") or "service"), workspace_root)
        raise
    result = {
        "status": sync_run.status,
        "broker_id": connection.broker_id,
        "sync_run_id": sync_run.id,
        "accounts": synced_accounts,
        "warnings": warnings,
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }
    _audit("broker_sync.completed", result, str(args.get("principal_id") or "service"), workspace_root)
    return result


def materialize_portfolio_snapshot_from_broker_state(
    workspace_root: Path | str | None,
    *,
    connection: Any,
    broker_account: Any,
    cash: list[CashDTO],
    positions: list[PositionDTO],
    sync_run_id: int | None = None,
) -> Any:
    ensure_runtime_database(workspace_root)
    from apps.portfolio.models import CashBalance, PortfolioLedgerEvent, PortfolioSnapshot, Position

    portfolio_id, account_id, strategy_id = portfolio_keys(
        {
            "portfolio_id": broker_account.metadata.get("portfolio_id") if isinstance(broker_account.metadata, dict) else "",
            "account_id": broker_account.broker_account_id,
            "strategy_id": broker_account.metadata.get("strategy_id") if isinstance(broker_account.metadata, dict) else "",
        },
        workspace_root,
    )
    now = django_timezone.now()
    position_payload = {
        item.symbol: {
            "quantity": item.quantity,
            "average_price": item.average_price,
            "currency": item.currency,
            "instrument_id": item.instrument_id or item.symbol,
        }
        for item in positions
        if item.quantity != 0
    }
    cash_payload = {item.currency: item.amount for item in cash}
    payload = {
        "cash_krw": cash_payload.get("KRW", 0),
        "cash": cash_payload,
        "positions": position_payload,
        "updated_at": now.isoformat(),
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "source": connection.broker_id,
        "broker_connection_id": connection.broker_id,
        "broker_account_id": broker_account.broker_account_id,
        "sync_run_id": sync_run_id,
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }
    snapshot = PortfolioSnapshot.objects.create(
        source="paper-trading" if connection.broker_id == "paper-trading" else "broker-sync",
        portfolio_id=portfolio_id,
        account_id=account_id,
        strategy_id=strategy_id,
        workspace_context=workspace_context_payload(workspace_root),
        payload=payload,
    )
    for item in cash:
        CashBalance.objects.create(
            snapshot=snapshot,
            currency=item.currency,
            amount=item.amount,
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
        )
        raw = {"currency": item.currency, "amount": item.amount, "sync_run_id": sync_run_id}
        PortfolioLedgerEvent.objects.create(
            event_type="cash",
            broker_connection=connection,
            broker_account=broker_account,
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
            amount=item.amount,
            currency=item.currency,
            event_at=now,
            source_payload_hash=stable_hash(raw),
            raw_payload_ref=f"broker_sync_run:{sync_run_id}" if sync_run_id else "",
            metadata=raw,
        )
    for item in positions:
        if item.quantity == 0:
            continue
        Position.objects.create(
            snapshot=snapshot,
            symbol=item.symbol,
            quantity=item.quantity,
            average_price=item.average_price,
            currency=item.currency,
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
        )
        raw = {"symbol": item.symbol, "quantity": item.quantity, "average_price": item.average_price, "currency": item.currency, "sync_run_id": sync_run_id}
        PortfolioLedgerEvent.objects.create(
            event_type="position",
            broker_connection=connection,
            broker_account=broker_account,
            portfolio_id=portfolio_id,
            account_id=account_id,
            strategy_id=strategy_id,
            instrument_id=item.instrument_id or item.symbol,
            symbol=item.symbol,
            quantity=item.quantity,
            price=item.average_price,
            currency=item.currency,
            event_at=now,
            source_payload_hash=stable_hash(raw),
            raw_payload_ref=f"broker_sync_run:{sync_run_id}" if sync_run_id else "",
            metadata=raw,
        )
    return snapshot


def create_reconciliation_summary(connection: Any, broker_account: Any, snapshot: Any, cash: list[CashDTO], positions: list[PositionDTO]) -> Any:
    from apps.portfolio.models import ReconciliationRun

    diffs: list[dict[str, Any]] = []
    if not cash and not positions and connection.transport != "mcp":
        diffs.append({"severity": "warning", "message": "sync returned no cash or positions"})
    status = "warning" if any(diff.get("severity") == "warning" for diff in diffs) else "clean"
    return ReconciliationRun.objects.create(
        broker_connection=connection,
        broker_account=broker_account,
        local_snapshot=snapshot,
        broker_snapshot_ref=f"portfolio_snapshot:{snapshot.id}",
        status=status,
        diffs=diffs,
    )


def list_reconciliation_runs(workspace_root: Path | str | None = None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_runtime_database(workspace_root)
    from apps.portfolio.models import ReconciliationRun

    args = args or {}
    limit = max(1, min(int(args.get("limit") or 20), 200))
    queryset = ReconciliationRun.objects.select_related("broker_connection", "broker_account", "local_snapshot")
    broker_id = args.get("broker_id") or args.get("broker_connection_id")
    if broker_id:
        queryset = queryset.filter(broker_connection__broker_id=broker_id)
    return {
        "reconciliation_runs": [_serialize_reconciliation(run) for run in queryset[:limit]],
        "db_canonical": True,
        "workspace_context": workspace_context_payload(workspace_root),
    }


def record_broker_mapping_review(workspace_root: Path | str | None, args: dict[str, Any]) -> dict[str, Any]:
    connection = _get_connection(workspace_root, args.get("broker_id") or args.get("broker_connection_id") or "")
    ensure_runtime_database(workspace_root)
    from apps.mcp.models import McpExternalTool

    router_name = (connection.metadata or {}).get("router")
    enabled_tools = []
    blocked_tools = []
    if router_name:
        for tool in McpExternalTool.objects.filter(router__name=router_name).order_by("external_name"):
            if tool.enabled and tool.review_status in {"reviewed", "approved"} and tool.proxy_mode in {"read_only", "summary_only", "service_adapter", "service_path"}:
                enabled_tools.append({"name": tool.external_name, "capability": tool.canonical_capability, "proxy_mode": tool.proxy_mode})
            else:
                blocked_tools.append({"name": tool.external_name, "category": tool.category, "proxy_mode": tool.proxy_mode, "review_status": tool.review_status})
    connection.capabilities = sorted({item["capability"] for item in enabled_tools if item.get("capability")})
    connection.enabled_read_scopes = sorted({item["capability"] for item in enabled_tools if str(item.get("proxy_mode")) in {"read_only", "summary_only"}})
    connection.enabled_trade_scopes = []
    connection.drift_status = "none" if enabled_tools else "review_required"
    metadata = dict(connection.metadata or {})
    metadata.update({"tool_mappings": enabled_tools, "blocked_tools": blocked_tools, "execution_enabled": False})
    connection.metadata = metadata
    connection.save()
    result = {"broker_id": connection.broker_id, "enabled_tools": enabled_tools, "blocked_tools": blocked_tools}
    _audit("broker_mapping.reviewed", result, str(args.get("principal_id") or args.get("actor") or "web"), workspace_root)
    return {"status": "recorded", **result, "db_canonical": True, "workspace_context": workspace_context_payload(workspace_root)}


def _get_connection(workspace_root: Path | str | None, broker_id: str) -> Any:
    ensure_runtime_database(workspace_root)
    from apps.integrations.models import BrokerConnection

    if not broker_id or broker_id == "paper-trading":
        return ensure_paper_broker_connection(workspace_root)
    connection = BrokerConnection.objects.filter(broker_id=broker_id).first()
    if connection is None:
        raise ValueError(f"unknown broker connection: {broker_id}")
    return connection


def _serialize_connection(connection: Any) -> dict[str, Any]:
    return {
        "broker_id": connection.broker_id,
        "display_name": connection.display_name,
        "transport": connection.transport,
        "adapter_type": connection.adapter_type,
        "status": connection.status,
        "credential_ref": connection.credential_ref,
        "capabilities": connection.capabilities,
        "enabled_read_scopes": connection.enabled_read_scopes,
        "enabled_trade_scopes": connection.enabled_trade_scopes,
        "trust_level": connection.trust_level,
        "last_sync_at": connection.last_sync_at.isoformat() if connection.last_sync_at else "",
        "last_health_status": connection.last_health_status,
        "drift_status": connection.drift_status,
        "trading_status": "enabled" if connection.enabled_trade_scopes and connection.status == "trading_enabled" else "locked",
        "accounts_count": connection.accounts.count() if hasattr(connection, "accounts") else 0,
        "accounts": [
            {
                "broker_account_id": account.broker_account_id,
                "account_label": account.account_label,
                "account_type": account.account_type,
                "base_currency": account.base_currency,
                "masked_identifier": account.masked_identifier,
                "trading_enabled": account.trading_enabled,
                "last_seen_at": account.last_seen_at.isoformat() if account.last_seen_at else "",
            }
            for account in connection.accounts.all()
        ] if hasattr(connection, "accounts") else [],
        "metadata": connection.metadata,
    }


def _serialize_reconciliation(run: Any) -> dict[str, Any]:
    return {
        "id": run.id,
        "broker_id": run.broker_connection.broker_id,
        "broker_account_id": run.broker_account.broker_account_id if run.broker_account else "",
        "local_snapshot_id": run.local_snapshot_id,
        "broker_snapshot_ref": run.broker_snapshot_ref,
        "status": run.status,
        "diffs": run.diffs,
        "created_at": run.created_at.isoformat(),
    }


def _capabilities_for_router(router: Any) -> list[str]:
    return sorted(
        {
            tool.canonical_capability
            for tool in router.external_tools.all()
            if tool.canonical_capability and tool.proxy_mode in {"read_only", "summary_only"}
        }
    )


def _enabled_read_scopes_for_router(router: Any) -> list[str]:
    return sorted(
        {
            tool.canonical_capability
            for tool in router.external_tools.all()
            if tool.enabled and tool.review_status in {"reviewed", "approved"} and tool.proxy_mode in {"read_only", "summary_only"}
        }
    )


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _audit(action: str, payload: dict[str, Any], actor: str, workspace_root: Path | str | None) -> None:
    write_audit_event_if_available(workspace_root, actor, "service", {"type": action, "payload": payload})
