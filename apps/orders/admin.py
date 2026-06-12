from django.contrib import admin

from apps.orders.models import ApprovalReceipt, ExecutionResult, OrderIntent


admin.site.register([ApprovalReceipt, ExecutionResult, OrderIntent])
