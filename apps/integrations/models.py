from django.db import models


class AdapterDefinition(models.Model):
    adapter_id = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=64, default="execution")
    enabled = models.BooleanField(default=False)
    live = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Adapter definition"
        verbose_name_plural = "Adapter definitions"

    def __str__(self) -> str:
        return self.adapter_id
