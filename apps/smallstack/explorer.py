"""Explorer registration for third-party models (axes)."""

from django.contrib import admin

from apps.explorer.registry import explorer


class AccessLogExplorerAdmin(admin.ModelAdmin):
    list_display = (
        "attempt_time",
        "ip_address",
        "username",
        "user_agent",
        "path_info",
    )
    explorer_list_fields = (
        "attempt_time",
        "ip_address",
        "username",
        "user_agent",
        "path_info",
    )
    explorer_field_transforms = {
        "attempt_time": ("localtime", {"fmt": "M d, Y g:i A"}),
    }
    explorer_column_widths = {
        "attempt_time": "22%",
    }


class AccessAttemptExplorerAdmin(admin.ModelAdmin):
    list_display = (
        "attempt_time",
        "ip_address",
        "user_agent",
        "username",
        "path_info",
        "failures_since_start",
    )
    explorer_field_transforms = {
        "attempt_time": ("localtime", {"fmt": "M d, Y g:i A"}),
    }


try:
    from axes.models import AccessAttempt, AccessLog

    explorer.register(AccessLog, AccessLogExplorerAdmin, group="Axes")
    explorer.register(AccessAttempt, AccessAttemptExplorerAdmin, group="Axes")
except ImportError:
    pass
