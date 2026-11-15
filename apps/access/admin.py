"""Access events in Django admin: readable, never editable (evidence)."""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import AccessEvent, ManagedGroup


@admin.register(AccessEvent)
class AccessEventAdmin(admin.ModelAdmin):
    list_display = ("at", "kind", "actor_label", "subject_label", "group_label", "permission", "source")
    list_filter = ("kind",)
    search_fields = ("actor_label", "subject_label", "group_label", "permission", "request_id")
    date_hierarchy = "at"
    readonly_fields = [f.name for f in AccessEvent._meta.fields]
    # Evidence: Explorer checks model permissions here whatever the site setting.
    explorer_model_permissions = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(ManagedGroup)
class ManagedGroupAdmin(admin.ModelAdmin):
    list_display = ("group", "app_label", "description", "synced_at")
    readonly_fields = ("group", "app_label", "description", "declared_permissions", "synced_at")
    explorer_model_permissions = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
