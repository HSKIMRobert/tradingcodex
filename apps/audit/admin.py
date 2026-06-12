from django.contrib import admin

from apps.audit.models import AuditEvent


admin.site.register(AuditEvent)
