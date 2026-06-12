from django.contrib import admin

from apps.workflows.models import ArtifactRef, WorkflowRun


admin.site.register([ArtifactRef, WorkflowRun])
