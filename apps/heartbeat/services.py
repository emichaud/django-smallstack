"""Shared heartbeat check and pruning logic.

Used by both the management command and the HTTP ping endpoint.
"""

import time
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Avg, Count, Q
from django.utils.timezone import now

from .models import Heartbeat, HeartbeatDaily, HeartbeatEpoch, MaintenanceWindow


def run_heartbeat_check() -> dict:
    """Run a heartbeat check and return the result.

    Returns {"status": "ok"|"fail", "response_time_ms": int,
             "maintenance": bool, "created": bool, "note": str|None}
    """
    minute = now().replace(second=0, microsecond=0)
    in_maintenance = MaintenanceWindow.is_in_maintenance(minute)
    start = time.monotonic()

    try:
        connection.ensure_connection()
        elapsed = int((time.monotonic() - start) * 1000)
        _, created = Heartbeat.objects.update_or_create(
            timestamp=minute,
            defaults={"status": "ok", "response_time_ms": elapsed, "maintenance": in_maintenance},
        )
        HeartbeatEpoch.ensure_epoch()
        return {
            "status": "ok",
            "response_time_ms": elapsed,
            "maintenance": in_maintenance,
            "created": created,
            "note": None,
        }
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        note = str(e)[:255]
        Heartbeat.objects.update_or_create(
            timestamp=minute,
            defaults={
                "status": "fail",
                "response_time_ms": elapsed,
                "note": note,
                "maintenance": in_maintenance,
            },
        )
        HeartbeatEpoch.ensure_epoch()
        return {
            "status": "fail",
            "response_time_ms": elapsed,
            "maintenance": in_maintenance,
            "created": True,
            "note": note,
        }


def prune_old_heartbeats() -> int:
    """Prune expired records, writing daily summaries first. Returns deleted count."""
    retention_days = getattr(settings, "HEARTBEAT_RETENTION_DAYS", 7)
    interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    cutoff = now() - timedelta(days=retention_days)
    old_records = Heartbeat.objects.filter(timestamp__lt=cutoff)

    if not old_records.exists():
        return 0

    _write_daily_summaries(old_records, interval)
    deleted, _ = old_records.delete()
    return deleted


def _write_daily_summaries(queryset, interval):
    """Aggregate about-to-be-pruned records into daily summaries."""
    daily_stats = (
        queryset.values("timestamp__date")
        .annotate(
            ok_count=Count("pk", filter=Q(status="ok")),
            fail_count=Count("pk", filter=Q(status="fail")),
            maintenance_count=Count("pk", filter=Q(maintenance=True)),
            total=Count("pk"),
            avg_ms=Avg("response_time_ms"),
        )
        .order_by("timestamp__date")
    )

    expected_per_day = (24 * 3600) // interval

    for day in daily_stats:
        date = day["timestamp__date"]
        ok = day["ok_count"]
        fail = day["fail_count"]
        total = day["total"]
        avg_ms = int(day["avg_ms"] or 0)

        denominator = max(total, expected_per_day)
        uptime = round((ok / denominator) * 100, 3) if denominator > 0 else 0

        HeartbeatDaily.objects.update_or_create(
            date=date,
            defaults={
                "ok_count": ok,
                "fail_count": fail,
                "maintenance_count": day["maintenance_count"],
                "expected_count": expected_per_day,
                "avg_response_ms": avg_ms,
                "uptime_pct": uptime,
            },
        )
