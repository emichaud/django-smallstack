"""Admin configuration for heartbeat models."""

from django.contrib import admin

from .models import Heartbeat, HeartbeatDaily, HeartbeatEpoch


@admin.register(Heartbeat)
class HeartbeatAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "status", "response_time_ms", "note")
    explorer_enabled = True
    explorer_group = "Monitoring"


@admin.register(HeartbeatEpoch)
class HeartbeatEpochAdmin(admin.ModelAdmin):
    list_display = ("started_at", "note", "service_target", "service_minimum")
    explorer_enabled = True
    explorer_group = "Monitoring"


@admin.register(HeartbeatDaily)
class HeartbeatDailyAdmin(admin.ModelAdmin):
    list_display = ("date", "ok_count", "fail_count", "uptime_pct", "avg_response_ms")
    explorer_enabled = True
    explorer_group = "Monitoring"
