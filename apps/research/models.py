from django.db import models


class ResearchArtifact(models.Model):
    artifact_id = models.CharField(max_length=180, unique=True)
    artifact_type = models.CharField(max_length=80, default="research_memo")
    universe = models.CharField(max_length=80, default="public_equity")
    workflow_type = models.CharField(max_length=120, blank=True)
    symbol = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=255)
    markdown = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)
    source_as_of = models.CharField(max_length=120, blank=True)
    readiness_label = models.CharField(max_length=80, blank=True)
    created_by = models.CharField(max_length=128, default="system")
    content_hash = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    export_path = models.CharField(max_length=512, blank=True)
    parent_artifact_id = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "Research artifact"
        verbose_name_plural = "Research artifacts"

    def __str__(self) -> str:
        return f"{self.artifact_id}: {self.title}"


class ResearchArtifactVersion(models.Model):
    artifact = models.ForeignKey(ResearchArtifact, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    markdown = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64)
    created_by = models.CharField(max_length=128, default="system")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-id"]
        unique_together = [("artifact", "version")]
        verbose_name = "Research artifact version"
        verbose_name_plural = "Research artifact versions"

    def __str__(self) -> str:
        return f"{self.artifact.artifact_id} v{self.version}"


class SourceSnapshot(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    provider = models.CharField(max_length=120)
    source_category = models.CharField(max_length=120)
    as_of = models.CharField(max_length=120, blank=True)
    artifact_id = models.CharField(max_length=180, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Source snapshot"
        verbose_name_plural = "Source snapshots"

    def __str__(self) -> str:
        return f"{self.provider} {self.source_category}"


class EvidencePack(models.Model):
    path = models.CharField(max_length=512, unique=True)
    universe = models.CharField(max_length=80, default="public_equity")
    workflow_type = models.CharField(max_length=120, blank=True)
    source_posture = models.JSONField(default=dict, blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Evidence pack"
        verbose_name_plural = "Evidence packs"

    def __str__(self) -> str:
        return self.path
