"""Admin configuration for RequestLog model."""

from django.contrib import admin

from .models import RequestLog


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    """Read-only admin for viewing request logs."""

    list_display = ("timestamp", "method", "path", "status_code", "user", "response_time_ms", "ip_address")
    list_filter = ("method", "status_code")
    search_fields = ("path", "ip_address", "user__username")
    readonly_fields = (
        "path", "method", "status_code", "user", "timestamp",
        "response_time_ms", "ip_address", "user_agent",
    )
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
