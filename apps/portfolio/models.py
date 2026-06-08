from django.db import models


class PortfolioSnapshot(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=64, default="paper-trading")
    portfolio_id = models.CharField(max_length=120, default="default-paper")
    account_id = models.CharField(max_length=120, default="local-paper")
    strategy_id = models.CharField(max_length=120, default="default-strategy")
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
    currency = models.CharField(max_length=16, default="KRW")
    portfolio_id = models.CharField(max_length=120, default="default-paper")
    account_id = models.CharField(max_length=120, default="local-paper")
    strategy_id = models.CharField(max_length=120, default="default-strategy")

    class Meta:
        verbose_name = "Position"
        verbose_name_plural = "Positions"

    def __str__(self) -> str:
        return f"{self.symbol} {self.quantity}"


class CashBalance(models.Model):
    snapshot = models.ForeignKey(PortfolioSnapshot, on_delete=models.CASCADE, related_name="cash_balances")
    currency = models.CharField(max_length=16, default="KRW")
    amount = models.DecimalField(max_digits=24, decimal_places=2)
    portfolio_id = models.CharField(max_length=120, default="default-paper")
    account_id = models.CharField(max_length=120, default="local-paper")
    strategy_id = models.CharField(max_length=120, default="default-strategy")

    class Meta:
        verbose_name = "Cash balance"
        verbose_name_plural = "Cash balances"

    def __str__(self) -> str:
        return f"{self.currency} {self.amount}"
