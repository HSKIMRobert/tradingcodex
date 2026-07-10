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


class AppendOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


admin.site.register(ApprovalReceipt, AppendOnlyAdmin)
admin.site.register(ExecutionResult, AppendOnlyAdmin)
admin.site.register([BrokerOrder, Fill, OrderCheckRun, OrderEvent, OrderTicket])
