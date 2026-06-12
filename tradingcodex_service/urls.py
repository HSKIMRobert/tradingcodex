from django.contrib import admin
from django.templatetags.static import static
from django.urls import path
from django.views.generic import RedirectView

import tradingcodex_service.admin
from tradingcodex_service.api import api
from tradingcodex_service.mcp_http import mcp_endpoint
from tradingcodex_service import web

urlpatterns = [
    path("", web.dashboard, name="web-dashboard"),
    path("harness/", web.harness, name="web-harness"),
    path("harness/agents/", web.agents_index, name="web-agents"),
    path("harness/agents/<str:role>/instructions/update/", web.agent_instruction_update, name="web-agent-instruction-update"),
    path("harness/agents/<str:role>/optional-skills/create/", web.optional_skill_create, name="web-optional-skill-create"),
    path("harness/agents/<str:role>/optional-skills/<str:name>/update/", web.optional_skill_update, name="web-optional-skill-update"),
    path("harness/agents/<str:role>/optional-skills/<str:name>/activate/", web.optional_skill_activate, name="web-optional-skill-activate"),
    path("harness/agents/<str:role>/optional-skills/<str:name>/archive/", web.optional_skill_archive, name="web-optional-skill-archive"),
    path("harness/agents/<str:role>/optional-skills/<str:name>/delete/", web.optional_skill_delete, name="web-optional-skill-delete"),
    path("harness/strategies/", web.strategies_index, name="web-strategies"),
    path("harness/roles/<str:role>/", web.role_inspector, name="web-role-inspector"),
    path("workspaces/open/", web.workspace_open, name="web-workspace-open"),
    path("workspaces/browse/", web.workspace_browse, name="web-workspace-browse"),
    path("workspaces/<str:workspace_id>/remove/", web.workspace_remove, name="web-workspace-remove"),
    path("research/", web.research, name="web-research"),
    path("portfolio/", web.portfolio, name="web-portfolio"),
    path("orders/", web.orders, name="web-orders"),
    path("policy/", web.policy, name="web-policy"),
    path("activity/", web.activity, name="web-activity"),
    path("integrations/mcp/", web.mcp_router, name="web-mcp-router"),
    path("integrations/mcp/routers/create/", web.mcp_router_create, name="web-mcp-router-create"),
    path("integrations/mcp/routers/<int:router_id>/import/", web.mcp_router_import, name="web-mcp-router-import"),
    path("integrations/mcp/tools/<int:tool_id>/update/", web.mcp_external_tool_update, name="web-mcp-external-tool-update"),
    path("integrations/mcp/tools/<int:tool_id>/check/", web.mcp_external_tool_check, name="web-mcp-external-tool-check"),
    path("workflow/starter-prompt/", web.starter_prompt, name="web-starter-prompt"),
    path("workflow/starter-prompt/preview/", web.starter_prompt_fragment, name="web-starter-prompt-preview"),
    path("favicon.ico", RedirectView.as_view(url=static("tradingcodex_admin/favicon.svg"), permanent=False)),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("mcp", mcp_endpoint, name="mcp-endpoint"),
]
