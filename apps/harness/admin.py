from django.contrib import admin

from apps.harness.models import WorkspaceContext


@admin.register(WorkspaceContext)
class WorkspaceContextAdmin(admin.ModelAdmin):
    list_display = ("project_name", "workspace_id", "path_hash", "git_branch", "last_seen_at")
    search_fields = ("project_name", "workspace_id", "path", "path_hash", "git_remote", "git_branch")
    readonly_fields = ("workspace_id", "path_hash", "active_profile", "created_at", "last_seen_at")
