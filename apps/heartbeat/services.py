"""Shared monitor check + pruning logic.

Used by the management command and the HTTP ping endpoint. ``run_all_monitors()``
iterates every registered monitor (:mod:`apps.smallstack.monitors`) and records
one ``Heartbeat`` per monitor per minute; ``run_heartbeat_check()`` is a
back-compat shim for just the built-in "site" monitor.
"""

import logging
import random
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Avg, Count, Q, QuerySet
from django.utils.timezone import now

from apps.smallstack.monitors import Monitor

from .models import Heartbeat, HeartbeatDaily, HeartbeatEpoch, MaintenanceWindow

logger = logging.getLogger(__name__)


def _probe(monitor: Monitor) -> tuple[str, int, str]:
    """Run ``monitor.check()`` and reduce it to ``(status, response_ms, note)``.

    Never raises: a monitor that raises is a "fail" with its exception as the
    note. Touches no ORM itself, so it is safe on a worker thread whenever the
    monitor's own ``check()`` is (see ``Monitor.concurrent_check``).
    """
    try:
        result = monitor.check()
        status = "ok" if result.ok else "fail"
        return status, int(result.response_time_ms or 0), (result.note or "")[:255]
    except Exception as e:  # noqa: BLE001 — any failure is a "down" beat
        return "fail", 0, str(e)[:255]


def _record(monitor: Monitor, minute: datetime, probe: tuple[str, int, str]) -> dict[str, Any]:
    """Write one Heartbeat row for ``probe`` at ``minute``. Calling thread only."""
    status, response_ms, note = probe
    in_maintenance = MaintenanceWindow.is_in_maintenance(minute, monitor.key)
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


def _recording_failed(monitor: Monitor, exc: Exception) -> dict[str, Any]:
    # The result says "fail", but the traceback is the only clue to why a probe
    # that ran couldn't be saved (a migration, a locked database).
    logger.error("Couldn't record heartbeat for monitor %s", monitor.key, exc_info=exc)
    return {
        "monitor": monitor.key,
        "status": "fail",
        "response_time_ms": 0,
        "maintenance": False,
        "created": False,
        "note": str(exc)[:255],
    }


def _current_minute() -> datetime:
    return now().replace(second=0, microsecond=0)


def run_monitor_check(monitor: Monitor) -> dict[str, Any]:
    """Run one monitor's cheap ``check()`` and record a Heartbeat row.

    A monitor that raises is recorded as a failure (its exception as the note),
    so one broken probe can't crash the per-minute run. Returns
    {"monitor": str, "status": "ok"|"fail", "response_time_ms": int,
     "maintenance": bool, "created": bool, "note": str|None}.
    """
    return _record(monitor, _current_minute(), _probe(monitor))


def _pool_size() -> int:
    return max(1, int(getattr(settings, "HEARTBEAT_MAX_CONCURRENT_CHECKS", 8)))


def _run_deadline() -> float:
    return max(1.0, float(getattr(settings, "HEARTBEAT_RUN_DEADLINE_SECONDS", 50)))


def run_all_monitors() -> dict[str, dict[str, Any]]:
    """Run every registered monitor, recording one Heartbeat each.

    Failures are isolated in both senses. A raising monitor is a "fail" beat
    that can't stop the rest. A *slow* one can't hold up the others either:
    monitors that set ``concurrent_check`` (outbound HTTP probes) run on a
    bounded thread pool while the database-backed monitors run here, so a run
    with N unreachable endpoints costs one timeout instead of N. Every probe
    still unfinished at ``HEARTBEAT_RUN_DEADLINE_SECONDS`` is recorded as a
    fail, which keeps the run inside its minute and well inside gunicorn's
    request timeout; the straggling thread is abandoned, not waited on.

    All database work — the maintenance lookup and the Heartbeat write — stays
    on the calling thread, on its connection. Every beat in one run is stamped
    with the minute the run *started*, so a slow run can't straddle two
    minutes. Returns a ``{monitor_key: result}`` map in registry order.
    """
    from apps.smallstack import monitors

    started = time.monotonic()
    minute = _current_minute()
    # Orphaned Site Monitors (their surface was deregistered) are a config
    # change, not an outage — skip recording so they neither log fail beats nor
    # dent their SLA. The overview surfaces them muted with a "Remove" prompt.
    active = [m for m in monitors.get_monitors() if not getattr(m, "orphaned", False)]
    pooled = [m for m in active if getattr(m, "concurrent_check", False)]

    probes: dict[int, tuple[str, int, str]] = {}
    pool: ThreadPoolExecutor | None = None
    futures: dict[Future[tuple[str, int, str]], Monitor] = {}
    # Zero or one pooled monitor isn't worth a pool; it runs inline below.
    if len(pooled) > 1 and _pool_size() > 1:
        pool = ThreadPoolExecutor(max_workers=min(_pool_size(), len(pooled)), thread_name_prefix="heartbeat-check")
        # Submitted in a different order each run, so the ones a deadline leaves
        # unreached aren't the same every minute.
        futures = {pool.submit(_probe, m): m for m in random.sample(pooled, len(pooled))}
    pooled_ids = {id(m) for m in futures.values()}  # empty unless the pool started
    not_reached: set[int] = set()

    try:
        # The ORM-backed monitors run here while the pool waits on the network.
        for monitor in active:
            if id(monitor) not in pooled_ids:
                probes[id(monitor)] = _probe(monitor)
        if futures:
            remaining = max(0.0, _run_deadline() - (time.monotonic() - started))
            done, _ = wait(futures, timeout=remaining)
            for future, monitor in futures.items():
                if future in done:
                    probes[id(monitor)] = future.result()  # _probe never raises
                elif future.cancel():
                    # Never started: queued behind slow checks. No data isn't
                    # "down", so nothing is recorded (a fail beat here was a
                    # false outage, on the same endpoints every run).
                    not_reached.add(id(monitor))
                else:
                    probes[id(monitor)] = (
                        "fail",
                        0,
                        f"check still running after the {_run_deadline():g}s run deadline",
                    )
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    results: dict[str, dict[str, Any]] = {}
    for monitor in active:
        if id(monitor) in not_reached:
            results[monitor.key] = {
                "monitor": monitor.key,
                "status": "skipped",
                "response_time_ms": 0,
                "maintenance": False,
                "created": False,
                "note": f"not reached before the {_run_deadline():g}s run deadline; nothing recorded",
            }
            continue
        try:
            results[monitor.key] = _record(monitor, minute, probes[id(monitor)])
        except Exception as e:  # noqa: BLE001 — even a recording failure can't stop the rest
            results[monitor.key] = _recording_failed(monitor, e)
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
    """Prune expired records, folding them into daily summaries first.

    Returns the deleted count. Runs inside one transaction so the
    aggregate-then-delete pair can't be torn by a concurrent prune (the ping
    view calls this every minute).
    """
    from django.db import transaction

    retention_days = getattr(settings, "HEARTBEAT_RETENTION_DAYS", 7)
    interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    cutoff = now() - timedelta(days=retention_days)

    with transaction.atomic():
        old_records = Heartbeat.objects.filter(timestamp__lt=cutoff)
        if not old_records.exists():
            return 0
        _write_daily_summaries(old_records, interval)
        deleted, _ = old_records.delete()
    return deleted


def _day_bounds(day) -> tuple:
    """Aware [start, end) of a calendar date in the CURRENT timezone — the same
    zone ``timestamp__date`` truncates in."""
    from datetime import datetime as _dt
    from datetime import time as _time

    from django.utils.timezone import make_aware

    start = make_aware(_dt.combine(day, _time.min))
    return start, start + timedelta(days=1)


def expected_intervals_for_day(day, interval: int, monitor_key: str, epoch_start) -> int:
    """How many checks *should* have run on ``day`` for ``monitor_key``.

    A full day is ``86400 // interval``, but three things legitimately shrink
    it: an epoch that began mid-day, a day still in progress, and SLA-excluded
    maintenance. Time nobody agreed to monitor is not downtime, so it must not
    sit in the denominator. Missing beats INSIDE the monitored span still
    count as downtime — for a self-pinged monitor, "the cron didn't run" and
    "the host was down" are the same event, which is also why this must never
    prorate from the day's first *observed* beat (that would erase every
    outage that starts at midnight).

    ``epoch_start`` must come from an explicit :class:`HeartbeatEpoch` ROW
    (``get_config``), never ``get_epoch``'s oldest-surviving-beat fallback:
    after earlier prunes that fallback sits at the retention boundary, which
    would zero out every summarized day for an epoch-less monitor and flip a
    conservative full-day denominator into an optimistic one exactly when the
    data is least trustworthy.
    """
    day_start, day_end = _day_bounds(day)
    start = max(day_start, epoch_start) if epoch_start else day_start
    end = min(day_end, now())
    if end <= start:
        return 0
    seconds = (end - start).total_seconds()
    seconds -= MaintenanceWindow.get_excluded_seconds(start, end, monitor_key)
    return max(int(seconds // interval), 0)


def _epoch_starts_by_key(keys) -> dict:
    """Explicit epoch-row start per monitor key (None when no row exists)."""
    starts: dict = {}
    for key in keys:
        cfg = HeartbeatEpoch.get_config(key)
        starts[key] = cfg.started_at if cfg else None
    return starts


def _write_daily_summaries(queryset: QuerySet, interval: int) -> None:
    """Fold about-to-be-pruned records into per-monitor daily summaries.

    Two invariants, each the fix for a shipped bug:

    1. ACCUMULATES into any existing summary row rather than replacing it.
       The cutoff is a moving instant and the pruner runs every minute, so one
       calendar day is pruned across ~1440 separate batches; the original
       ``update_or_create`` kept only the final batch, converging every
       summarized day to its last single beat (1/1440 ⇒ 0.069% ⇒ "down").

    2. Uses the raw span's SLA semantics (mirrors ``_uptime_over_window``):
       ``ok_count``/``fail_count`` hold beats OUTSIDE SLA-excluded maintenance,
       beats inside excluded windows land in ``maintenance_count``, and
       ``expected_count`` is prorated per day (epoch start, day in progress,
       excluded windows). A flat full-day denominator painted the epoch's
       first partial day ~6% and capped an honest day with a 4h excluded
       window at 83% — and because the recorded arm of ``max(recorded,
       expected)`` also counted excluded beats, shrinking the expected side
       alone would not have fixed it.
    """
    daily_stats = (
        queryset.values("monitor_key", "timestamp__date")
        .annotate(
            ok_count=Count("pk", filter=Q(status="ok")),
            fail_count=Count("pk", filter=Q(status="fail")),
            total=Count("pk"),
            avg_ms=Avg("response_time_ms"),
        )
        .order_by("monitor_key", "timestamp__date")
    )

    epoch_starts: dict = {}

    for day in daily_stats:
        key = day["monitor_key"]
        date = day["timestamp__date"]
        if key not in epoch_starts:
            epoch_starts.update(_epoch_starts_by_key([key]))
        expected = expected_intervals_for_day(date, interval, key, epoch_starts[key])

        # Split this batch's beats at the SLA-excluded window boundaries the
        # raw path uses (the beat-level `maintenance` flag marks ANY window,
        # including non-excluded ones, so it cannot drive SLA math).
        day_start, day_end = _day_bounds(date)
        batch_qs = queryset.filter(
            monitor_key=key, timestamp__gte=day_start, timestamp__lt=day_end
        )
        excluded_ok = excluded_total = 0
        for span_start, span_end in MaintenanceWindow.get_excluded_ranges(
            day_start, day_end, key
        ):
            span = batch_qs.filter(timestamp__gte=span_start, timestamp__lt=span_end)
            excluded_total += span.count()
            excluded_ok += span.filter(status="ok").count()

        sla_ok = day["ok_count"] - excluded_ok
        sla_fail = day["fail_count"] - (excluded_total - excluded_ok)
        batch_sla_total = sla_ok + sla_fail
        batch_avg = float(day["avg_ms"] or 0)

        row, _created = HeartbeatDaily.objects.get_or_create(
            monitor_key=key, date=date, defaults={"expected_count": expected}
        )
        prior_total = row.ok_count + row.fail_count
        row.ok_count += sla_ok
        row.fail_count += sla_fail
        row.maintenance_count += excluded_total
        row.expected_count = expected

        # Weighted response-time merge across batches (by SLA-relevant beats).
        merged_total = prior_total + batch_sla_total
        if merged_total:
            row.avg_response_ms = int(
                round(
                    (row.avg_response_ms * prior_total + batch_avg * batch_sla_total)
                    / merged_total
                )
            )

        denominator = max(row.ok_count + row.fail_count, expected)
        row.uptime_pct = (
            min(round(row.ok_count / denominator * 100, 3), 100.0) if denominator else 0
        )
        row.save()
