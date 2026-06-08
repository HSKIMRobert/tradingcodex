from django.contrib import admin

from apps.portfolio.models import CashBalance, PortfolioSnapshot, Position


class PositionInline(admin.TabularInline):
    model = Position
    extra = 0


class CashBalanceInline(admin.TabularInline):
    model = CashBalance
    extra = 0


@admin.register(PortfolioSnapshot)
class PortfolioSnapshotAdmin(admin.ModelAdmin):
    list_display = ("created_at", "source", "portfolio_id", "account_id", "strategy_id")
    list_filter = ("source", "portfolio_id", "account_id", "strategy_id")
    readonly_fields = ("workspace_context",)
    inlines = [PositionInline, CashBalanceInline]
