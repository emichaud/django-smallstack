"""Bundled datasets for heartbeat: raw checks, the daily rollup, maintenance windows."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.calendar import register_calendar
from apps.datasets.framework import framework_dataset

from .models import Heartbeat, HeartbeatDaily, MaintenanceWindow


@framework_dataset(
    "smallstack_heartbeats",
    label="Heartbeats",
    description=(
        "Every individual health check: monitor, time, up/down status, latency and whether it fell in a "
        "maintenance window."
    ),
    columns=["monitor_key", "timestamp", "status", "response_time_ms", "maintenance", "note"],
    filterable=["monitor_key", "timestamp", "status", "maintenance"],
)
def heartbeats() -> QuerySet[Heartbeat]:
    return Heartbeat.objects.all()


@framework_dataset(
    "smallstack_heartbeat_daily",
    label="Heartbeat daily rollup",
    description=(
        "One row per monitor per day: ok/fail/maintenance check counts, the prorated expected "
        "count the SLA is measured against, average latency and that day's uptime percentage."
    ),
    columns=[
        "monitor_key",
        "date",
        "ok_count",
        "fail_count",
        "maintenance_count",
        "expected_count",
        "avg_response_ms",
        "uptime_pct",
    ],
    filterable=["monitor_key", "date"],
)
def heartbeat_daily() -> QuerySet[HeartbeatDaily]:
    return HeartbeatDaily.objects.all()


@framework_dataset(
    "smallstack_maintenance_windows",
    label="Maintenance windows",
    description=(
        "Declared maintenance windows per monitor, with their span and whether they are excluded from SLA math."
    ),
    columns=["monitor_key", "title", "start", "end", "exclude_from_sla", "created_at"],
    filterable=["monitor_key", "start", "end", "exclude_from_sla", "created_at"],
)
def maintenance_windows() -> QuerySet[MaintenanceWindow]:
    return MaintenanceWindow.objects.all()


# ---------------------------------------------------------------------------
# Calendar protocol — the bundled calendars this module contributes
# ---------------------------------------------------------------------------

register_calendar(
    "smallstack_maintenance_windows",
    start="start",
    end="end",
    title="title",
    subtitle="monitor_key",
    label="Maintenance windows",
    description="Declared maintenance windows, spanning every day they cover.",
)

register_calendar(
    "smallstack_heartbeat_daily",
    start="date",
    title=lambda d: f"{d.monitor_key} · {float(d.uptime_pct):.2f}%",
    status="sla_status",
    label="Daily uptime",
    description="One entry per monitor per day, tinted by how the day measured against the SLA.",
)
