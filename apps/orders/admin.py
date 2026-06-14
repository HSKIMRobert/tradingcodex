from django.contrib import admin

from apps.orders.models import (
    ApprovalReceipt,
    BrokerOrder,
    ExecutionResult,
    Fill,
    OrderCheckRun,
    OrderEvent,
    OrderTicket,
)


admin.site.register([ApprovalReceipt, BrokerOrder, ExecutionResult, Fill, OrderCheckRun, OrderEvent, OrderTicket])
