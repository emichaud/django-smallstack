"""
Register Django's built-in LogEntry model in admin for browsing audit logs.

This gives you a read-only activity log at /admin/admin/logentry/ showing
all actions recorded by Django admin and by log_action().
"""

from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry

from .models import APIToken


@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):
    """Browse + revoke API tokens. Exposed via Explorer for non-admin staff."""

    list_display = [
        "name",
        "user",
        "token_type",
        "access_level",
        "created_at",
        "last_used_at",
        "is_active",
    ]
    list_filter = ["token_type", "access_level", "is_active"]
    search_fields = ["name", "user__username", "prefix"]
    readonly_fields = [
        "prefix",
        "hashed_key",
        "created_at",
        "last_used_at",
        "revoked_at",
        "request_count",
    ]
    actions = ["revoke_tokens"]

    # Explorer integration: surfaces APIToken under the "Auth" group so the
    # MCP consent page can deep-link users here for token management.
    explorer_enabled = True
    explorer_group = "Auth"
    explorer_list_fields = ("name", "user", "token_type", "access_level", "is_active")

    @admin.action(description="Revoke selected tokens")
    def revoke_tokens(self, request, queryset):
        count = 0
        for token in queryset.filter(is_active=True):
            token.revoke()
            count += 1
        self.message_user(request, f"Revoked {count} token(s).", level=messages.SUCCESS)


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
