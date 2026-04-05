"""
Register Django's built-in LogEntry model in admin for browsing audit logs.

This gives you a read-only activity log at /admin/admin/logentry/ showing
all actions recorded by Django admin and by log_action().
"""

from django.contrib import admin
from django.contrib.admin.models import LogEntry


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ["action_time", "user", "content_type", "object_repr", "action_flag", "change_message"]
    list_filter = ["action_flag", "content_type", "user"]
    search_fields = ["object_repr", "change_message"]
    date_hierarchy = "action_time"

    # Explorer overrides: drop change_message + object_repr, widen the timestamp.
    explorer_list_fields = ("action_time", "user", "content_type", "action_flag")
    explorer_column_widths = {
        "action_time": "25%",
        "user": "25%",
        "content_type": "25%",
        "action_flag": "25%",
    }
    readonly_fields = [
        "action_time",
        "user",
        "content_type",
        "object_id",
        "object_repr",
        "action_flag",
        "change_message",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
