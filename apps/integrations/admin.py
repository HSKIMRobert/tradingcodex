from django.contrib import admin

from apps.integrations.models import AdapterDefinition
from apps.integrations.services import disable_adapters, disable_live_adapters, enable_non_live_adapters


@admin.register(AdapterDefinition)
class AdapterDefinitionAdmin(admin.ModelAdmin):
    list_display = ("adapter_id", "kind", "enabled", "live")
    list_filter = ("enabled", "live", "kind")
    search_fields = ("adapter_id", "kind")
    actions = ["enable_non_live_adapters", "disable_adapters", "disable_live_adapters"]

    @admin.action(description="Enable selected non-live adapters")
    def enable_non_live_adapters(self, request, queryset):
        enable_non_live_adapters(queryset, str(request.user or "admin"))

    @admin.action(description="Disable selected adapters")
    def disable_adapters(self, request, queryset):
        disable_adapters(queryset, str(request.user or "admin"))

    @admin.action(description="Disable all selected live adapters")
    def disable_live_adapters(self, request, queryset):
        disable_live_adapters(queryset, str(request.user or "admin"))
