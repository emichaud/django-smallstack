"""Shared monitor check + pruning logic.

Used by the management command and the HTTP ping endpoint. ``run_all_monitors()``
iterates every registered monitor (:mod:`apps.smallstack.monitors`) and records
one ``Heartbeat`` per monitor per minute; ``run_heartbeat_check()`` is a
back-compat shim for just the built-in "site" monitor.
"""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Avg, Count, Q, QuerySet
from django.utils.timezone import now

from apps.smallstack.monitors import Monitor

from .models import Heartbeat, HeartbeatDaily, HeartbeatEpoch, MaintenanceWindow


def run_monitor_check(monitor: Monitor) -> dict[str, Any]:
    """Run one monitor's cheap ``check()`` and record a Heartbeat row.

    A monitor that raises is recorded as a failure (its exception as the note),
    so one broken probe can't crash the per-minute run. Returns
    {"monitor": str, "status": "ok"|"fail", "response_time_ms": int,
     "maintenance": bool, "created": bool, "note": str|None}.
    """
    minute = now().replace(second=0, microsecond=0)
    in_maintenance = MaintenanceWindow.is_in_maintenance(minute, monitor.key)
    try:
        result = monitor.check()
        status = "ok" if result.ok else "fail"
        response_ms = int(result.response_time_ms or 0)
        note = (result.note or "")[:255]
    except Exception as e:  # noqa: BLE001 — any failure is a "down" beat
        status, response_ms, note = "fail", 0, str(e)[:255]

    _, created = Heartbeat.objects.update_or_create(
        monitor_key=monitor.key,
        timestamp=minute,
        defaults={
            "status": status,
            "response_time_ms": response_ms,
            "note": note if status == "fail" else "",
            "maintenance": in_maintenance,
        },
    )
    HeartbeatEpoch.ensure_epoch(monitor.key)
    return {
        "monitor": monitor.key,
        "status": status,
        "response_time_ms": response_ms,
        "maintenance": in_maintenance,
        "created": created,
        "note": note or None,
    }


def run_all_monitors() -> dict[str, dict[str, Any]]:
    """Run every registered monitor, recording one Heartbeat each.

    Failures are isolated — a slow or raising monitor cannot block the others.
    Returns a ``{monitor_key: result}`` map.
    """
    from apps.smallstack import monitors

    results: dict[str, dict] = {}
    for monitor in monitors.get_monitors():
        # Orphaned Site Monitors (their surface was deregistered) are a config
        # change, not an outage — skip recording so they neither log fail beats nor
        # dent their SLA. The overview surfaces them muted with a "Remove" prompt.
        if getattr(monitor, "orphaned", False):
            continue
        try:
            results[monitor.key] = run_monitor_check(monitor)
        except Exception as e:  # noqa: BLE001 — even a recording failure can't stop the rest
            results[monitor.key] = {
                "monitor": monitor.key,
                "status": "fail",
                "response_time_ms": 0,
                "maintenance": False,
                "created": False,
                "note": str(e)[:255],
            }
    return results


def run_heartbeat_check() -> dict[str, Any]:
    """Back-compat shim: run only the built-in "site" monitor.

    Prefer :func:`run_all_monitors`. Uses the registered site monitor, or a fresh
    instance if the registry isn't populated yet.
    """
    from apps.smallstack.monitors import get_monitor

    from .monitors import SiteMonitor

    return run_monitor_check(get_monitor("site") or SiteMonitor())


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


def _write_daily_summaries(queryset: QuerySet, interval: int) -> None:
    """Aggregate about-to-be-pruned records into per-monitor daily summaries."""
    daily_stats = (
        queryset.values("monitor_key", "timestamp__date")
        .annotate(
            ok_count=Count("pk", filter=Q(status="ok")),
            fail_count=Count("pk", filter=Q(status="fail")),
            maintenance_count=Count("pk", filter=Q(maintenance=True)),
            total=Count("pk"),
            avg_ms=Avg("response_time_ms"),
        )
        .order_by("monitor_key", "timestamp__date")
    )

    expected_per_day = (24 * 3600) // interval

    for day in daily_stats:
        ok = day["ok_count"]
        total = day["total"]
        avg_ms = int(day["avg_ms"] or 0)

        denominator = max(total, expected_per_day)
        uptime = round((ok / denominator) * 100, 3) if denominator > 0 else 0

        HeartbeatDaily.objects.update_or_create(
            monitor_key=day["monitor_key"],
            date=day["timestamp__date"],
            defaults={
                "ok_count": ok,
                "fail_count": day["fail_count"],
                "maintenance_count": day["maintenance_count"],
                "expected_count": expected_per_day,
                "avg_response_ms": avg_ms,
                "uptime_pct": uptime,
            },
        )
