from django.contrib import admin

from apps.research.models import EvidencePack, ResearchArtifact, ResearchArtifactVersion, SourceSnapshot


class ResearchArtifactVersionInline(admin.TabularInline):
    model = ResearchArtifactVersion
    extra = 0
    fields = ("version", "created_by", "created_at", "content_hash")
    readonly_fields = ("version", "created_by", "created_at", "content_hash")
    can_delete = False


@admin.register(ResearchArtifact)
class ResearchArtifactAdmin(admin.ModelAdmin):
    list_display = ("artifact_id", "artifact_type", "universe", "symbol", "readiness_label", "version", "updated_at")
    list_filter = ("artifact_type", "universe", "workflow_type", "readiness_label", "created_by")
    search_fields = ("artifact_id", "title", "symbol", "markdown", "content_hash")
    readonly_fields = ("content_hash", "version", "workspace_context", "created_at", "updated_at")
    inlines = [ResearchArtifactVersionInline]


@admin.register(ResearchArtifactVersion)
class ResearchArtifactVersionAdmin(admin.ModelAdmin):
    list_display = ("artifact", "version", "created_by", "created_at", "content_hash")
    list_filter = ("created_by",)
    search_fields = ("artifact__artifact_id", "markdown", "content_hash")
    readonly_fields = ("artifact", "version", "markdown", "metadata", "content_hash", "created_by", "created_at")


@admin.register(SourceSnapshot)
class SourceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("created_at", "provider", "source_category", "as_of", "artifact_id")
    list_filter = ("provider", "source_category")
    search_fields = ("provider", "source_category", "as_of", "artifact_id")


@admin.register(EvidencePack)
class EvidencePackAdmin(admin.ModelAdmin):
    list_display = ("path", "universe", "workflow_type", "created_at")
    list_filter = ("universe", "workflow_type")
    search_fields = ("path", "universe", "workflow_type")
