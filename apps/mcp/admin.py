from django.contrib import admin

from apps.mcp.models import McpToolCall, McpToolDefinition
from apps.mcp.services import set_mcp_tools_enabled, sync_builtin_mcp_registry


@admin.register(McpToolDefinition)
class McpToolDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "risk_level", "requires_approval", "audit_required", "experimental", "enabled", "updated_at")
    list_filter = ("enabled", "category", "risk_level", "requires_approval", "audit_required", "experimental")
    search_fields = ("name", "description", "capability_required")
    readonly_fields = ("updated_at",)
    actions = ["enable_tools", "disable_tools", "sync_builtin_tools"]

    @admin.action(description="Enable selected MCP tools")
    def enable_tools(self, request, queryset):
        set_mcp_tools_enabled(queryset, True, str(request.user or "admin"))

    @admin.action(description="Disable selected MCP tools")
    def disable_tools(self, request, queryset):
        set_mcp_tools_enabled(queryset, False, str(request.user or "admin"))

    @admin.action(description="Sync built-in MCP tool registry")
    def sync_builtin_tools(self, request, queryset):
        sync_builtin_mcp_registry(str(request.user or "admin"))


@admin.register(McpToolCall)
class McpToolCallAdmin(admin.ModelAdmin):
    list_display = ("created_at", "tool_name", "principal_id", "status", "duration_ms")
    list_filter = ("tool_name", "status", "principal_id")
    search_fields = ("tool_name", "principal_id", "request_hash", "result_hash", "error")
    readonly_fields = ("created_at", "tool_name", "principal_id", "status", "request", "response", "workspace_context", "request_hash", "result_hash", "error", "duration_ms")
