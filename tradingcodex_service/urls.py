from django.contrib import admin
from django.templatetags.static import static
from django.urls import path, re_path
from django.views.generic import RedirectView

from tradingcodex_service import web, workbench_api
from tradingcodex_service.api import api


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/workbench/", workbench_api.snapshot, name="workbench-snapshot"),
    path("api/workbench/skills/<str:skill_id>/", workbench_api.skill_detail, name="workbench-skill-detail"),
    path("api/workbench/artifacts/<path:artifact_id>/", workbench_api.artifact_detail, name="workbench-artifact-detail"),
    path("api/workbench/preview/", workbench_api.run_preview, name="workbench-run-preview"),
    path("api/workbench/runs/", workbench_api.run_start, name="workbench-run-start"),
    path("api/workbench/runs/<str:run_id>/follow-up/", workbench_api.run_follow_up, name="workbench-run-follow-up"),
    path("api/workbench/runs/<str:run_id>/", workbench_api.run_detail, name="workbench-run-detail"),
    path("api/", api.urls),
    path("favicon.ico", RedirectView.as_view(url=static("tradingcodex_admin/favicon.svg"), permanent=False)),
    re_path(r"^(?!api(?:/|$)|admin(?:/|$)|static(?:/|$)|favicon\.ico$)(?P<path>.*)$", web.spa_index, name="web-spa"),
]
