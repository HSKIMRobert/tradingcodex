from django.db import models


class ApprovalReceipt(models.Model):
    approval_receipt_id = models.CharField(max_length=160, unique=True)
    order_ticket = models.ForeignKey(
        "orders.OrderTicket",
        on_delete=models.PROTECT,
        to_field="ticket_id",
        db_column="order_ticket_id",
        related_name="approval_receipts",
    )
    approved_by = models.CharField(max_length=128)
    valid = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    exact_order_hash = models.CharField(max_length=64)
    broker_id = models.CharField(max_length=120)
    broker_account_id = models.CharField(max_length=160)
    max_notional = models.DecimalField(max_digits=24, decimal_places=6)
    max_price = models.DecimalField(max_digits=20, decimal_places=6)
    max_slippage_bps = models.PositiveIntegerField(null=True, blank=True)
    approved_order_type = models.CharField(max_length=32)
    approved_time_in_force = models.CharField(max_length=32)
    valid_until = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    quote_as_of_requirement = models.CharField(max_length=80, blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Approval receipt"
        verbose_name_plural = "Approval receipts"

    def __str__(self) -> str:
        return self.approval_receipt_id


class ExecutionResult(models.Model):
    order_ticket = models.ForeignKey(
        "orders.OrderTicket",
        on_delete=models.PROTECT,
        to_field="ticket_id",
        db_column="order_ticket_id",
        related_name="execution_results",
    )
    approval_receipt = models.ForeignKey(
        ApprovalReceipt,
        on_delete=models.PROTECT,
        to_field="approval_receipt_id",
        db_column="approval_receipt_id",
        related_name="execution_results",
    )
    idempotency_key = models.CharField(max_length=220, unique=True)
    adapter = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    provider_invoked_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    portfolio_id = models.CharField(max_length=120)
    account_id = models.CharField(max_length=120)
    strategy_id = models.CharField(max_length=120)
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Execution result"
        verbose_name_plural = "Execution results"

    def __str__(self) -> str:
        return f"{self.status}: {self.order_ticket_id}"


class OrderTurnGrant(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_RESERVED = "reserved"
    STATUS_CONSUMED = "consumed"
    STATUS_REVOKED = "revoked"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_RESERVED, "Reserved"),
        (STATUS_CONSUMED, "Consumed"),
        (STATUS_REVOKED, "Revoked"),
        (STATUS_EXPIRED, "Expired"),
    )
    MODE_PAPER = "paper"
    MODE_VALIDATION = "validation"
    MODE_LIVE = "live"
    MODE_CHOICES = (
        (MODE_PAPER, "Paper"),
        (MODE_VALIDATION, "Validation"),
        (MODE_LIVE, "Live"),
    )

    grant_id = models.CharField(max_length=80, unique=True)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    workspace_id = models.CharField(max_length=180)
    workspace_path_hash = models.CharField(max_length=64)
    session_id_hash = models.CharField(max_length=64)
    turn_id_hash = models.CharField(max_length=64)
    prompt_sha256 = models.CharField(max_length=64)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    reserved_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    reservation_tool_use_id_hash = models.CharField(max_length=64, blank=True)
    reservation_arguments_hash = models.CharField(max_length=64, blank=True)
    reservation_proof_hash = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=16, blank=True)
    ticket_id = models.CharField(max_length=160, blank=True)
    approval_receipt_id = models.CharField(max_length=160, blank=True)
    broker_order_id = models.CharField(max_length=160, blank=True)
    live_confirmation_hash = models.CharField(max_length=64, blank=True)
    result_status = models.CharField(max_length=32, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-issued_at", "-id"]
        indexes = [
            models.Index(
                fields=["workspace_id", "workspace_path_hash", "session_id_hash", "status"],
                name="orders_grant_session_idx",
            ),
            models.Index(fields=["expires_at", "status"], name="orders_grant_expiry_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "workspace_path_hash", "session_id_hash", "turn_id_hash"],
                name="unique_order_grant_per_turn",
            )
        ]
        verbose_name = "Order turn grant"
        verbose_name_plural = "Order turn grants"

    def __str__(self) -> str:
        return f"{self.mode}:{self.status}:{self.grant_id}"


class OrderTicket(models.Model):
    ticket_id = models.CharField(max_length=160, unique=True)
    source = models.CharField(max_length=32, default="web")
    portfolio_id = models.CharField(max_length=120)
    account_id = models.CharField(max_length=120)
    strategy_id = models.CharField(max_length=120)
    broker_connection = models.ForeignKey(
        "integrations.BrokerConnection",
        on_delete=models.PROTECT,
        related_name="order_tickets",
    )
    broker_account = models.ForeignKey(
        "integrations.BrokerAccount",
        on_delete=models.PROTECT,
        related_name="order_tickets",
    )
    instrument_id = models.CharField(max_length=120, blank=True)
    symbol = models.CharField(max_length=64)
    side = models.CharField(max_length=8)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    order_type = models.CharField(max_length=32, default="limit")
    limit_price = models.DecimalField(max_digits=20, decimal_places=6)
    stop_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    time_in_force = models.CharField(max_length=32, default="day")
    estimated_notional = models.DecimalField(max_digits=24, decimal_places=6)
    native_notional = models.DecimalField(max_digits=24, decimal_places=6)
    currency = models.CharField(max_length=16, default="USD")
    base_currency = models.CharField(max_length=16, default="USD")
    fx_rate = models.DecimalField(max_digits=24, decimal_places=10)
    fx_source_snapshot_id = models.CharField(max_length=160, blank=True)
    fx_as_of = models.DateTimeField()
    status = models.CharField(max_length=32, default="DRAFT")
    current_state = models.CharField(max_length=32, default="DRAFT")
    payload_hash = models.CharField(max_length=64, blank=True)
    user_visible_summary = models.TextField(blank=True)
    created_by = models.CharField(max_length=128, default="portfolio-manager")
    natural_language_source = models.TextField(blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Order ticket"
        verbose_name_plural = "Order tickets"

    def __str__(self) -> str:
        return self.ticket_id


class OrderCheckRun(models.Model):
    ticket = models.ForeignKey(OrderTicket, on_delete=models.CASCADE, related_name="check_runs")
    check_type = models.CharField(max_length=32)
    decision = models.CharField(max_length=16)
    reasons = models.JSONField(default=list, blank=True)
    quote_as_of = models.CharField(max_length=80, blank=True)
    source_snapshot_ref = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["check_type", "-created_at", "-id"]
        verbose_name = "Order check run"
        verbose_name_plural = "Order check runs"

    def __str__(self) -> str:
        return f"{self.ticket.ticket_id} {self.check_type} {self.decision}"


class BrokerOrder(models.Model):
    ticket = models.ForeignKey(OrderTicket, on_delete=models.CASCADE, related_name="broker_orders")
    broker_order_id = models.CharField(max_length=160)
    broker_status = models.CharField(max_length=64)
    submitted_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    raw_status_payload_hash = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-submitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["ticket", "broker_order_id"], name="unique_broker_order_per_ticket")
        ]
        verbose_name = "Broker order"
        verbose_name_plural = "Broker orders"

    def __str__(self) -> str:
        return f"{self.ticket.ticket_id} {self.broker_order_id}"


class Fill(models.Model):
    ticket = models.ForeignKey(OrderTicket, on_delete=models.CASCADE, related_name="fills")
    broker_order_id = models.CharField(max_length=160)
    fill_id = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    price = models.DecimalField(max_digits=20, decimal_places=6)
    fee = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    currency = models.CharField(max_length=16, default="USD")
    filled_at = models.DateTimeField()
    raw_payload_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-filled_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["ticket", "broker_order_id", "fill_id"], name="unique_fill_per_ticket")
        ]
        verbose_name = "Fill"
        verbose_name_plural = "Fills"

    def __str__(self) -> str:
        return f"{self.ticket.ticket_id} {self.fill_id}"


class OrderEvent(models.Model):
    ticket = models.ForeignKey(OrderTicket, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=64)
    actor = models.CharField(max_length=128, default="system")
    payload = models.JSONField(default=dict, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "Order event"
        verbose_name_plural = "Order events"

    def __str__(self) -> str:
        return f"{self.ticket.ticket_id} {self.event_type}"
