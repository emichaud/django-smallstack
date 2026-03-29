"""Explorer registration for heartbeat models."""

from django.contrib import admin

from apps.explorer.registry import explorer
from apps.smallstack.displays import (
    DetailGridDisplay,
    TableDisplay,
)

from .displays import MonthGridDisplay, SLACompareDisplay, WeeklySummaryDisplay
from .models import Heartbeat, HeartbeatDaily, HeartbeatEpoch, MaintenanceWindow


class HeartbeatDailyExplorerAdmin(admin.ModelAdmin):
    """Explorer config for daily summaries with custom list displays."""

    list_display = ("date", "ok_count", "fail_count", "uptime_pct", "avg_response_ms")

    explorer_displays = [
        TableDisplay,
        WeeklySummaryDisplay(),
        MonthGridDisplay(),
    ]

    explorer_detail_displays = [
        DetailGridDisplay,
        SLACompareDisplay(),
    ]


# Re-import the original admin classes for models that keep defaults
from .admin import HeartbeatAdmin, HeartbeatEpochAdmin, MaintenanceWindowAdmin  # noqa: E402

explorer.register(Heartbeat, HeartbeatAdmin, group="Monitoring")
explorer.register(HeartbeatEpoch, HeartbeatEpochAdmin, group="Monitoring")
explorer.register(HeartbeatDaily, HeartbeatDailyExplorerAdmin, group="Monitoring")
explorer.register(MaintenanceWindow, MaintenanceWindowAdmin, group="Monitoring")
