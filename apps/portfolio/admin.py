from django.contrib import admin

from apps.portfolio.models import (
    BrokerSyncRun,
    CashBalance,
    PortfolioLedgerEvent,
    PortfolioSnapshot,
    Position,
    ReconciliationRun,
)


admin.site.register([BrokerSyncRun, CashBalance, PortfolioLedgerEvent, PortfolioSnapshot, Position, ReconciliationRun])
