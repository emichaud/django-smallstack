"""Admin configuration for heartbeat models."""

from django.contrib import admin

from .models import (
    Heartbeat,
    HeartbeatDaily,
    HeartbeatEpoch,
    MaintenanceWindow,
    MonitoredEndpoint,
)


@admin.register(Heartbeat)
class HeartbeatAdmin(admin.ModelAdmin):
    list_display = ("monitor_key", "timestamp", "status", "response_time_ms", "note")
    list_filter = ("monitor_key", "status", "timestamp")
    search_fields = ("monitor_key", "timestamp", "note", "status")
    explorer_enable_api = True
    explorer_export_formats = ["csv", "json"]
    explorer_api_aggregate_fields = ["response_time_ms"]


@admin.register(HeartbeatEpoch)
class HeartbeatEpochAdmin(admin.ModelAdmin):
    # NB: monitor_key intentionally NOT in list_display — the explorer derives its
    # edit form from list_display, and a required monitor_key would break the form.
    list_display = ("started_at", "note", "service_target", "service_minimum")
    list_filter = ("monitor_key",)


@admin.register(HeartbeatDaily)
class HeartbeatDailyAdmin(admin.ModelAdmin):
    list_display = ("monitor_key", "date", "ok_count", "fail_count", "uptime_pct", "avg_response_ms")
    list_filter = ("monitor_key",)


@admin.register(MaintenanceWindow)
class MaintenanceWindowAdmin(admin.ModelAdmin):
    # monitor_key omitted from list_display (see HeartbeatEpochAdmin note).
    list_display = ("title", "start", "end", "exclude_from_sla", "created_at")
    list_filter = ("monitor_key", "exclude_from_sla")


@admin.register(MonitoredEndpoint)
class MonitoredEndpointAdmin(admin.ModelAdmin):
    list_display = ("name", "service", "url", "method", "expected_status", "enabled", "public")
    list_filter = ("service", "enabled", "public", "method")
    search_fields = ("name", "slug", "url")
