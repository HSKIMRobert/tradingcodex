from django.contrib import admin

from apps.mcp.models import (
    McpConnector,
    McpExternalTool,
    McpExternalToolCall,
    McpExternalToolPermission,
    McpToolCall,
    McpToolDefinition,
)


admin.site.register([
    McpToolDefinition,
    McpToolCall,
    McpConnector,
    McpExternalTool,
    McpExternalToolPermission,
    McpExternalToolCall,
])
