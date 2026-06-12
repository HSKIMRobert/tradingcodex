from django.contrib import admin

from apps.mcp.models import (
    McpExternalTool,
    McpExternalToolCall,
    McpExternalToolPermission,
    McpRouter,
    McpToolCall,
    McpToolDefinition,
)


admin.site.register([
    McpToolDefinition,
    McpToolCall,
    McpRouter,
    McpExternalTool,
    McpExternalToolPermission,
    McpExternalToolCall,
])
