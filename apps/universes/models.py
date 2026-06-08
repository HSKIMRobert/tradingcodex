from django.db import models


class UniversePlugin(models.Model):
    universe_id = models.CharField(max_length=120, unique=True)
    display_name = models.CharField(max_length=160)
    enabled = models.BooleanField(default=True)
    research_only_default = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Universe plugin"
        verbose_name_plural = "Universe plugins"

    def __str__(self) -> str:
        return self.display_name
