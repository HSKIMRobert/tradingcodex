from django.contrib import admin

from apps.mcp.models import McpToolCall, McpToolDefinition


admin.site.register([McpToolDefinition, McpToolCall])
