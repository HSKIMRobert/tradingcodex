from django.db import models


class AdapterDefinition(models.Model):
    adapter_id = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=64, default="execution")
    enabled = models.BooleanField(default=False)
    live = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Adapter definition"
        verbose_name_plural = "Adapter definitions"

    def __str__(self) -> str:
        return self.adapter_id


class BrokerConnection(models.Model):
    broker_id = models.CharField(max_length=120, unique=True)
    display_name = models.CharField(max_length=160)
    transport = models.CharField(max_length=32, default="paper")
    adapter_type = models.CharField(max_length=64, default="paper")
    status = models.CharField(max_length=32, default="read_only")
    credential_ref = models.CharField(max_length=255, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    enabled_read_scopes = models.JSONField(default=list, blank=True)
    enabled_trade_scopes = models.JSONField(default=list, blank=True)
    trust_level = models.CharField(max_length=32, default="unreviewed")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_health_status = models.CharField(max_length=32, default="not_checked")
    drift_status = models.CharField(max_length=32, default="none")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name", "broker_id"]
        verbose_name = "Broker connection"
        verbose_name_plural = "Broker connections"

    def __str__(self) -> str:
        return f"{self.display_name} ({self.status})"


class BrokerAccount(models.Model):
    broker_connection = models.ForeignKey(BrokerConnection, on_delete=models.CASCADE, related_name="accounts")
    broker_account_id = models.CharField(max_length=160)
    account_label = models.CharField(max_length=160, blank=True)
    account_type = models.CharField(max_length=64, default="paper")
    base_currency = models.CharField(max_length=16, default="USD")
    masked_identifier = models.CharField(max_length=120, blank=True)
    trading_enabled = models.BooleanField(default=False)
    discovered_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["broker_connection__display_name", "broker_account_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["broker_connection", "broker_account_id"],
                name="unique_broker_account_per_connection",
            )
        ]
        verbose_name = "Broker account"
        verbose_name_plural = "Broker accounts"

    def __str__(self) -> str:
        return self.account_label or self.broker_account_id


class InstrumentMap(models.Model):
    canonical_symbol = models.CharField(max_length=64)
    broker_symbol = models.CharField(max_length=120)
    broker_connection = models.ForeignKey(BrokerConnection, on_delete=models.CASCADE, related_name="instrument_maps")
    exchange = models.CharField(max_length=64, blank=True)
    asset_type = models.CharField(max_length=64, default="equity")
    currency = models.CharField(max_length=16, default="USD")
    tick_size = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    lot_size = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    min_order_quantity = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["canonical_symbol", "broker_symbol"]
        constraints = [
            models.UniqueConstraint(
                fields=["broker_connection", "canonical_symbol", "broker_symbol"],
                name="unique_instrument_map_per_broker",
            )
        ]
        verbose_name = "Instrument map"
        verbose_name_plural = "Instrument maps"

    def __str__(self) -> str:
        return f"{self.canonical_symbol} -> {self.broker_symbol}"
