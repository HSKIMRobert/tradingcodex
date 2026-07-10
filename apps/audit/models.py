from django.db import models
from django.core.exceptions import ValidationError


class AuditEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    actor_principal = models.CharField(max_length=128, default="system")
    source = models.CharField(max_length=32, default="service")
    action = models.CharField(max_length=160)
    resource = models.CharField(max_length=255, blank=True)
    decision = models.CharField(max_length=32, default="recorded")
    request_hash = models.CharField(max_length=64, blank=True)
    result_hash = models.CharField(max_length=64, blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Audit event"
        verbose_name_plural = "Audit events"

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action}"

    def save(self, *args, **kwargs) -> None:
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("audit events are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> None:
        raise ValidationError("audit events are append-only")
