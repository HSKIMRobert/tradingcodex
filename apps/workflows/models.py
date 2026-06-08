from django.db import models


class WorkflowRun(models.Model):
    run_id = models.CharField(max_length=180, unique=True)
    lane = models.CharField(max_length=80)
    universe = models.CharField(max_length=80, default="public_equity")
    readiness_label = models.CharField(max_length=80, default="factual-baseline")
    status = models.CharField(max_length=32, default="open")
    original_request = models.TextField(blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Workflow run"
        verbose_name_plural = "Workflow runs"

    def __str__(self) -> str:
        return self.run_id


class ArtifactRef(models.Model):
    workflow = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="artifacts")
    path = models.CharField(max_length=512)
    artifact_type = models.CharField(max_length=80)
    role = models.CharField(max_length=128, blank=True)
    hero = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Artifact reference"
        verbose_name_plural = "Artifact references"

    def __str__(self) -> str:
        return self.path
