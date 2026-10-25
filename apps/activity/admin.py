"""Admin configuration for RequestLog model."""

from django.contrib import admin
from django.http import HttpRequest

from .models import RequestLog


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    """Read-only admin for viewing request logs."""

    list_display = ("timestamp", "method", "path", "status_code", "user", "response_time_ms", "ip_address")
    list_filter = ("method", "status_code")
    search_fields = ("path", "route", "ip_address", "user__username")
    readonly_fields = (
        "path",
        "route",
        "method",
        "status_code",
        "user",
        "timestamp",
        "response_time_ms",
        "ip_address",
        "user_agent",
    )
    date_hierarchy = "timestamp"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: RequestLog | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: RequestLog | None = None) -> bool:
        return bool(request.user.is_superuser)
