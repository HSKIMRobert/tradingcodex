from django.contrib import admin

from apps.integrations.models import (
    AdapterDefinition,
    BrokerAccount,
    BrokerConnection,
    BrokerProviderSourceApproval,
    InstrumentMap,
)


class BrokerProviderSourceApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "provider_id",
        "workspace_id",
        "source_sha256",
        "bundle_sha256",
        "status",
        "approved_at",
        "revoked_at",
    )
    readonly_fields = (
        "workspace_id",
        "workspace_path_hash",
        "provider_id",
        "relative_path",
        "source_sha256",
        "bundle_sha256",
        "snapshot_relative_path",
        "status",
        "approved_by",
        "approved_at",
        "revoked_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([AdapterDefinition, BrokerAccount, BrokerConnection, InstrumentMap])
admin.site.register(BrokerProviderSourceApproval, BrokerProviderSourceApprovalAdmin)
