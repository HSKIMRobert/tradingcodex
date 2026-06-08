from django.db import models


class OrderIntent(models.Model):
    intent_id = models.CharField(max_length=160, unique=True)
    symbol = models.CharField(max_length=64)
    side = models.CharField(max_length=8)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    limit_price = models.DecimalField(max_digits=20, decimal_places=6)
    currency = models.CharField(max_length=16, default="KRW")
    broker = models.CharField(max_length=64)
    estimated_notional_krw = models.DecimalField(max_digits=24, decimal_places=2)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField()
    portfolio_id = models.CharField(max_length=120, default="default-paper")
    account_id = models.CharField(max_length=120, default="local-paper")
    strategy_id = models.CharField(max_length=120, default="default-strategy")
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Order intent"
        verbose_name_plural = "Order intents"

    def __str__(self) -> str:
        return self.intent_id


class ApprovalReceipt(models.Model):
    receipt_id = models.CharField(max_length=160, unique=True)
    order_intent_id = models.CharField(max_length=160)
    approved_by = models.CharField(max_length=128)
    valid = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Approval receipt"
        verbose_name_plural = "Approval receipts"

    def __str__(self) -> str:
        return self.receipt_id


class ExecutionResult(models.Model):
    order_intent_id = models.CharField(max_length=160)
    approval_receipt_id = models.CharField(max_length=160, blank=True)
    idempotency_key = models.CharField(max_length=220, unique=True, null=True, blank=True)
    adapter = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    portfolio_id = models.CharField(max_length=120, default="default-paper")
    account_id = models.CharField(max_length=120, default="local-paper")
    strategy_id = models.CharField(max_length=120, default="default-strategy")
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Execution result"
        verbose_name_plural = "Execution results"

    def __str__(self) -> str:
        return f"{self.status}: {self.order_intent_id}"
