from django.apps import AppConfig


class HarnessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.harness"
    label = "harness"
    verbose_name = "Harness Operations"
