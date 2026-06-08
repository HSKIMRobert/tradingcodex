from django.contrib import admin

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_principal", "source", "action", "decision", "resource")
    list_filter = ("source", "decision", "action")
    search_fields = ("actor_principal", "action", "resource", "request_hash", "result_hash")
    readonly_fields = ("created_at", "workspace_context", "request_hash", "result_hash")
