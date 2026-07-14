from django.contrib import admin

from apps.mcp.models import (
    McpExternalPermissionRequest,
    McpExternalTool,
    McpExternalToolCall,
    McpExternalToolPermission,
    McpRouter,
    McpToolCall,
    McpToolDefinition,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(McpRouter)
class McpRouterAdmin(ReadOnlyAdmin):
    pass


admin.site.register([
    McpToolDefinition,
    McpToolCall,
    McpExternalTool,
    McpExternalToolPermission,
    McpExternalPermissionRequest,
    McpExternalToolCall,
], ReadOnlyAdmin)
