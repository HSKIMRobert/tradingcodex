from django.db import models


class WorkspaceContext(models.Model):
    workspace_id = models.CharField(max_length=80, unique=True)
    path_hash = models.CharField(max_length=64, unique=True)
    project_name = models.CharField(max_length=180)
    path = models.CharField(max_length=1024)
    git_remote = models.CharField(max_length=512, blank=True)
    git_branch = models.CharField(max_length=180, blank=True)
    active_profile = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project_name", "id"]
        verbose_name = "Workspace context"
        verbose_name_plural = "Workspace contexts"

    def __str__(self) -> str:
        return f"{self.project_name} {self.workspace_id}"
