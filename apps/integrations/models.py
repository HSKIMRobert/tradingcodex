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


class BrokerProviderSourceApproval(models.Model):
    STATUS_APPROVED = "approved"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = (
        (STATUS_APPROVED, "Approved"),
        (STATUS_REVOKED, "Revoked"),
    )

    workspace_id = models.CharField(max_length=180)
    workspace_path_hash = models.CharField(max_length=64)
    provider_id = models.CharField(max_length=120)
    relative_path = models.CharField(max_length=255)
    source_sha256 = models.CharField(max_length=64)
    bundle_sha256 = models.CharField(max_length=64)
    snapshot_relative_path = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_APPROVED)
    approved_by = models.CharField(max_length=120, default="local-operator")
    approved_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-approved_at", "-id"]
        indexes = [
            models.Index(
                fields=["workspace_id", "workspace_path_hash", "provider_id", "status"],
                name="integration_ws_provider_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "workspace_path_hash", "provider_id"],
                condition=models.Q(status="approved"),
                name="uniq_active_ws_provider",
            ),
            models.UniqueConstraint(
                fields=[
                    "workspace_id",
                    "workspace_path_hash",
                    "provider_id",
                    "relative_path",
                    "source_sha256",
                    "bundle_sha256",
                ],
                name="uniq_ws_provider_source",
            )
        ]
        verbose_name = "Broker provider source approval"
        verbose_name_plural = "Broker provider source approvals"

    def __str__(self) -> str:
        return f"{self.status}:{self.workspace_id}:{self.provider_id}:{self.source_sha256[:12]}"


class BrokerConnection(models.Model):
    broker_id = models.CharField(max_length=120, unique=True)
    provider_id = models.CharField(max_length=120, db_index=True)
    display_name = models.CharField(max_length=160)
    transport = models.CharField(max_length=32)
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
    account_type = models.CharField(max_length=64)
    base_currency = models.CharField(max_length=16)
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
