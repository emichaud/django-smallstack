"""Explorer registration for heartbeat models."""

from django.contrib import admin

from apps.explorer.registry import explorer
from apps.smallstack.displays import (
    DashboardWidget,
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


class StatusDashboardWidget(DashboardWidget):
    title = "Status"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 '
        "7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 "
        '5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>'
    )
    order = 10
    url_name = "heartbeat:dashboard"

    def get_data(self, model_class=None):
        from .views import _calc_uptime, _get_status_data

        status_data = _get_status_data()
        uptime_24h = _calc_uptime(24)
        return {
            "headline": status_data.get("status_label", "Unknown"),
            "detail": f"{uptime_24h}% uptime (24h)" if uptime_24h is not None else "No data",
            "status": status_data.get("status", "unknown"),
        }


HeartbeatAdmin.explorer_dashboard_widgets = [StatusDashboardWidget()]

explorer.register(Heartbeat, HeartbeatAdmin, group="Monitoring")
explorer.register(HeartbeatEpoch, HeartbeatEpochAdmin, group="Monitoring")
explorer.register(HeartbeatDaily, HeartbeatDailyExplorerAdmin, group="Monitoring")
explorer.register(MaintenanceWindow, MaintenanceWindowAdmin, group="Monitoring")
