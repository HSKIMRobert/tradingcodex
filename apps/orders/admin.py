from django.contrib import admin

from apps.orders.models import ApprovalReceipt, ExecutionResult, OrderIntent


@admin.register(OrderIntent)
class OrderIntentAdmin(admin.ModelAdmin):
    list_display = ("intent_id", "symbol", "side", "quantity", "broker", "portfolio_id", "account_id", "strategy_id", "created_by", "created_at")
    list_filter = ("broker", "portfolio_id", "account_id", "strategy_id")
    search_fields = ("intent_id", "symbol", "broker", "created_by")
    readonly_fields = ("workspace_context",)


@admin.register(ApprovalReceipt)
class ApprovalReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_id", "order_intent_id", "approved_by", "valid", "expires_at")
    list_filter = ("valid", "approved_by")
    search_fields = ("receipt_id", "order_intent_id", "approved_by")
    readonly_fields = ("workspace_context",)


@admin.register(ExecutionResult)
class ExecutionResultAdmin(admin.ModelAdmin):
    list_display = ("created_at", "order_intent_id", "adapter", "status", "portfolio_id", "account_id", "strategy_id")
    list_filter = ("adapter", "status", "portfolio_id", "account_id", "strategy_id")
    search_fields = ("order_intent_id", "approval_receipt_id")
    readonly_fields = ("workspace_context",)
