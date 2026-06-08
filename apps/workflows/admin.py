from django.contrib import admin

from apps.workflows.models import ArtifactRef, WorkflowRun


class ArtifactRefInline(admin.TabularInline):
    model = ArtifactRef
    extra = 0


@admin.register(WorkflowRun)
class WorkflowRunAdmin(admin.ModelAdmin):
    list_display = ("run_id", "lane", "universe", "readiness_label", "status", "updated_at")
    list_filter = ("lane", "universe", "readiness_label", "status")
    search_fields = ("run_id", "original_request")
    readonly_fields = ("workspace_context",)
    inlines = [ArtifactRefInline]
