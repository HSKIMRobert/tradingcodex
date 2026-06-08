from django.db import models


class Principal(models.Model):
    principal_id = models.CharField(max_length=128, unique=True)
    role = models.CharField(max_length=128)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Principal"
        verbose_name_plural = "Principals"

    def __str__(self) -> str:
        return self.principal_id


class Capability(models.Model):
    principal = models.ForeignKey(Principal, on_delete=models.CASCADE, related_name="capabilities")
    action = models.CharField(max_length=160)
    resource_pattern = models.CharField(max_length=255, default="*")
    effect = models.CharField(max_length=16, choices=[("allow", "Allow"), ("deny", "Deny")], default="allow")

    class Meta:
        unique_together = [("principal", "action", "resource_pattern")]
        verbose_name = "Capability"
        verbose_name_plural = "Capabilities"

    def __str__(self) -> str:
        return f"{self.principal_id if hasattr(self, 'principal_id') else self.principal} {self.effect} {self.action}"


class RestrictedSymbol(models.Model):
    symbol = models.CharField(max_length=64, unique=True)
    reason = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Restricted symbol"
        verbose_name_plural = "Restricted symbols"

    def __str__(self) -> str:
        return self.symbol


class PolicyDecision(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    principal_id = models.CharField(max_length=128)
    action = models.CharField(max_length=160)
    resource = models.CharField(max_length=255, blank=True)
    decision = models.CharField(max_length=16)
    reasons = models.JSONField(default=list, blank=True)
    workspace_context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Policy decision"
        verbose_name_plural = "Policy decisions"

    def __str__(self) -> str:
        return f"{self.decision}: {self.principal_id} {self.action}"
