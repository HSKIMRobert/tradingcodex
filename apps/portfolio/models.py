from django.db import models


class PaperPortfolioState(models.Model):
    portfolio_id = models.CharField(max_length=120)
    account_id = models.CharField(max_length=120)
    strategy_id = models.CharField(max_length=120)
    version = models.PositiveBigIntegerField(default=1)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["portfolio_id", "account_id", "strategy_id"],
                name="unique_paper_portfolio_state",
            )
        ]
        verbose_name = "Paper portfolio state"
        verbose_name_plural = "Paper portfolio states"

    def __str__(self) -> str:
        return f"{self.portfolio_id}/{self.account_id}/{self.strategy_id} v{self.version}"


class PortfolioSnapshot(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=64, default="paper-trading")
    portfolio_id = models.CharField(max_length=120)
    account_id = models.CharField(max_length=120)
    strategy_id = models.CharField(max_length=120)
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Portfolio snapshot"
        verbose_name_plural = "Portfolio snapshots"

    def __str__(self) -> str:
        return f"{self.source} {self.created_at:%Y-%m-%d %H:%M:%S}"


class Position(models.Model):
    snapshot = models.ForeignKey(PortfolioSnapshot, on_delete=models.CASCADE, related_name="positions")
    symbol = models.CharField(max_length=64)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    average_price = models.DecimalField(max_digits=20, decimal_places=6)
    currency = models.CharField(max_length=16, default="USD")
    portfolio_id = models.CharField(max_length=120)
    account_id = models.CharField(max_length=120)
    strategy_id = models.CharField(max_length=120)

    class Meta:
        verbose_name = "Position"
        verbose_name_plural = "Positions"

    def __str__(self) -> str:
        return f"{self.symbol} {self.quantity}"


class CashBalance(models.Model):
    snapshot = models.ForeignKey(PortfolioSnapshot, on_delete=models.CASCADE, related_name="cash_balances")
    currency = models.CharField(max_length=16, default="USD")
    amount = models.DecimalField(max_digits=24, decimal_places=6)
    portfolio_id = models.CharField(max_length=120)
    account_id = models.CharField(max_length=120)
    strategy_id = models.CharField(max_length=120)

    class Meta:
        verbose_name = "Cash balance"
        verbose_name_plural = "Cash balances"

    def __str__(self) -> str:
        return f"{self.currency} {self.amount}"


class PortfolioLedgerEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField(max_length=32)
    broker_connection = models.ForeignKey(
        "integrations.BrokerConnection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portfolio_ledger_events",
    )
    broker_account = models.ForeignKey(
        "integrations.BrokerAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portfolio_ledger_events",
    )
    portfolio_id = models.CharField(max_length=120)
    account_id = models.CharField(max_length=120)
    strategy_id = models.CharField(max_length=120)
    instrument_id = models.CharField(max_length=120, blank=True)
    symbol = models.CharField(max_length=64, blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    amount = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    currency = models.CharField(max_length=16, default="USD")
    event_at = models.DateTimeField(null=True, blank=True)
    source_payload_hash = models.CharField(max_length=64, blank=True)
    raw_payload_ref = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-event_at", "-created_at", "-id"]
        verbose_name = "Portfolio ledger event"
        verbose_name_plural = "Portfolio ledger events"

    def __str__(self) -> str:
        target = self.symbol or self.currency or self.event_type
        return f"{self.event_type} {target}"


class BrokerSyncRun(models.Model):
    broker_connection = models.ForeignKey(
        "integrations.BrokerConnection",
        on_delete=models.CASCADE,
        related_name="sync_runs",
    )
    status = models.CharField(max_length=32, default="started")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    pulled_positions_count = models.PositiveIntegerField(default=0)
    pulled_cash_count = models.PositiveIntegerField(default=0)
    pulled_orders_count = models.PositiveIntegerField(default=0)
    pulled_fills_count = models.PositiveIntegerField(default=0)
    warnings = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        verbose_name = "Broker sync run"
        verbose_name_plural = "Broker sync runs"

    def __str__(self) -> str:
        return f"{self.broker_connection.broker_id} {self.status}"


class ReconciliationRun(models.Model):
    broker_connection = models.ForeignKey(
        "integrations.BrokerConnection",
        on_delete=models.CASCADE,
        related_name="reconciliation_runs",
    )
    broker_account = models.ForeignKey(
        "integrations.BrokerAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_runs",
    )
    local_snapshot = models.ForeignKey(
        PortfolioSnapshot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_runs",
    )
    broker_snapshot_ref = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=32, default="clean")
    diffs = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Reconciliation run"
        verbose_name_plural = "Reconciliation runs"

    def __str__(self) -> str:
        return f"{self.broker_connection.broker_id} {self.status}"
