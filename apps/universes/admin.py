from django.contrib import admin

from apps.universes.models import UniversePlugin


@admin.register(UniversePlugin)
class UniversePluginAdmin(admin.ModelAdmin):
    list_display = ("universe_id", "display_name", "enabled", "research_only_default")
    list_filter = ("enabled", "research_only_default")
    search_fields = ("universe_id", "display_name")
