"""Django-admin registration — the operator escape hatch.

There is deliberately no CRUDView: notifications are per-user rows served by
the inbox page, not an admin-managed dataset. Django admin gives staff a
debugging window without inviting day-to-day management.
"""

from __future__ import annotations

from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "kind", "read_at", "created_at")
    list_filter = ("kind",)
    search_fields = ("title", "message", "recipient__username")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
