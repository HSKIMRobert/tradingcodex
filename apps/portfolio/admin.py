from django.contrib import admin

from apps.portfolio.models import (
    BrokerSyncRun,
    CashBalance,
    PortfolioLedgerEvent,
    PaperPortfolioState,
    PortfolioSnapshot,
    Position,
    ReconciliationRun,
)


admin.site.register([BrokerSyncRun, CashBalance, PaperPortfolioState, PortfolioLedgerEvent, PortfolioSnapshot, Position, ReconciliationRun])
