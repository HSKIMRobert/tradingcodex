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
    path("harness/agents/<str:role>/skills/", web.agent_skills, name="web-agent-skills"),
    path("harness/roles/<str:role>/", web.role_inspector, name="web-role-inspector"),
    path("research/", web.research, name="web-research"),
    path("portfolio/", web.portfolio, name="web-portfolio"),
    path("orders/", web.orders, name="web-orders"),
    path("policy/", web.policy, name="web-policy"),
    path("activity/", web.activity, name="web-activity"),
    path("workflow/starter-prompt/", web.starter_prompt, name="web-starter-prompt"),
    path("workflow/starter-prompt/preview/", web.starter_prompt_fragment, name="web-starter-prompt-preview"),
    path("favicon.ico", RedirectView.as_view(url=static("tradingcodex_admin/favicon.svg"), permanent=False)),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("mcp", mcp_endpoint, name="mcp-endpoint"),
]
