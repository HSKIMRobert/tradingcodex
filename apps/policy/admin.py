from django.contrib import admin

from apps.policy.models import Capability, PolicyDecision, Principal, RestrictedSymbol
from apps.policy.services import set_capability_effect, set_principal_active, set_restricted_symbols_active


@admin.register(Principal)
class PrincipalAdmin(admin.ModelAdmin):
    list_display = ("principal_id", "role", "active")
    search_fields = ("principal_id", "role")
    list_filter = ("active", "role")
    actions = ["activate_principals", "deactivate_principals"]

    @admin.action(description="Activate selected principals")
    def activate_principals(self, request, queryset):
        set_principal_active(queryset, True, str(request.user or "admin"))

    @admin.action(description="Deactivate selected principals")
    def deactivate_principals(self, request, queryset):
        set_principal_active(queryset, False, str(request.user or "admin"))


@admin.register(Capability)
class CapabilityAdmin(admin.ModelAdmin):
    list_display = ("principal", "effect", "action", "resource_pattern")
    list_filter = ("effect", "action")
    search_fields = ("principal__principal_id", "action", "resource_pattern")
    actions = ["allow_capabilities", "deny_capabilities"]

    @admin.action(description="Set selected capabilities to allow")
    def allow_capabilities(self, request, queryset):
        set_capability_effect(queryset, "allow", str(request.user or "admin"))

    @admin.action(description="Set selected capabilities to deny")
    def deny_capabilities(self, request, queryset):
        set_capability_effect(queryset, "deny", str(request.user or "admin"))


@admin.register(RestrictedSymbol)
class RestrictedSymbolAdmin(admin.ModelAdmin):
    list_display = ("symbol", "active", "reason", "created_at")
    list_filter = ("active",)
    search_fields = ("symbol", "reason")
    actions = ["activate_restrictions", "deactivate_restrictions"]

    @admin.action(description="Activate selected restricted symbols")
    def activate_restrictions(self, request, queryset):
        set_restricted_symbols_active(queryset, True, str(request.user or "admin"))

    @admin.action(description="Deactivate selected restricted symbols")
    def deactivate_restrictions(self, request, queryset):
        set_restricted_symbols_active(queryset, False, str(request.user or "admin"))


@admin.register(PolicyDecision)
class PolicyDecisionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "principal_id", "action", "decision", "resource")
    list_filter = ("decision", "action")
    search_fields = ("principal_id", "action", "resource")
    readonly_fields = ("workspace_context",)
