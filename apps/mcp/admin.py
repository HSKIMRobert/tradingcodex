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


@admin.register(McpRouter)
class McpRouterAdmin(admin.ModelAdmin):
    exclude = ("env",)
    readonly_fields = ("credential_ref",)


admin.site.register([
    McpToolDefinition,
    McpToolCall,
    McpExternalTool,
    McpExternalToolPermission,
    McpExternalPermissionRequest,
    McpExternalToolCall,
])
