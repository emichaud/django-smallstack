"""Status computation for heartbeat monitors.

All uptime / SLA / timeline math, extracted from ``views.py`` and parameterized by
``monitor_key`` so every monitor computes against its own timeseries. Every helper
defaults ``monitor_key="site"`` to preserve the original single-monitor behavior.

Consumed by the views and by the visualization layer
(:mod:`apps.heartbeat.visualizations`).

NOTE on overall/7d uptime and *coverage*: these blend pruned ``HeartbeatDaily``
summaries (older span) with raw beats (recent span). An in-epoch span that has
*neither* raw beats *nor* a daily summary contributes nothing — it is treated as
"no data", not downtime, so overall uptime is only as complete as daily-summary
coverage. ``_uptime_over_window`` therefore also reports ``coverage`` (the
fraction of the window we have any information for), which the SLA page surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils.timezone import localtime, now

from .models import Heartbeat, HeartbeatDaily, HeartbeatEpoch, MaintenanceWindow

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class UptimeResult:
    """Outcome of an uptime-over-window computation plus its data coverage."""

    uptime: float | None  # ok / expected %, or None when there's no usable sample
    covered_seconds: float  # window seconds we have ANY data for (up or down)
    window_seconds: float  # total window seconds

    @property
    def coverage(self) -> float | None:
        """Fraction of the window with data (0–1), or None for an empty window."""
        if self.window_seconds <= 0:
            return None
        return min(self.covered_seconds / self.window_seconds, 1.0)


def _get_epoch(monitor_key: str = "site") -> datetime | None:
    """Return the monitor's monitoring epoch, or None."""
    return HeartbeatEpoch.get_epoch(monitor_key)


def _last_beat_age_seconds() -> int | None:
    """Age in seconds of the most-recent heartbeat across *all* monitors, or None.

    Powers the stale-runner self-diagnostic: if the freshest beat anywhere is far
    older than the expected interval, the per-minute runner probably isn't being
    called at all (no cron ping / ``manage.py heartbeat``) — which would make
    every monitor read "down"/"warming up" regardless of real health. Returns
    None when no beats have ever been recorded.
    """
    last = Heartbeat.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()
    if last is None:
        return None
    return int((now() - last).total_seconds())


def _get_sla_targets(monitor_key: str = "site") -> tuple[float, float]:
    """Return (service_target, service_minimum) for the monitor as floats."""
    return HeartbeatEpoch.get_sla_targets(monitor_key)


def _sla_color(uptime_pct: float | None, use_target: bool = False, monitor_key: str = "site") -> str:
    """Return a CSS color variable based on uptime vs SLA thresholds.

    With use_target=True (dashboard): green >= target, yellow >= minimum, red < minimum.
    With use_target=False (default): green >= minimum, red < minimum.
    """
    if uptime_pct is None:
        return "var(--body-quiet-color)"
    target, minimum = _get_sla_targets(monitor_key)
    if use_target:
        if uptime_pct >= target:
            return "var(--success-fg)"
        elif uptime_pct >= minimum:
            return "var(--warning-fg)"
        else:
            return "var(--error-fg)"
    else:
        if uptime_pct >= minimum:
            return "var(--success-fg)"
        else:
            return "var(--error-fg)"


def _sla_state(uptime_pct: float | None, use_target: bool = False, monitor_key: str = "site") -> str | None:
    """Stat-card state name (success/warning/danger/muted) for an uptime value.

    The discrete sibling of :func:`_sla_color` — feeds ``{% stat_card state=… %}``.
    """
    if uptime_pct is None:
        return "muted"
    target, minimum = _get_sla_targets(monitor_key)
    if use_target:
        if uptime_pct >= target:
            return "success"
        if uptime_pct >= minimum:
            return "warning"
        return "danger"
    return "success" if uptime_pct >= minimum else "danger"


def _get_status_data(monitor_key: str = "site") -> dict[str, Any]:
    """Compute current status from the monitor's recent heartbeats."""
    expected_interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    recent = list(Heartbeat.objects.filter(monitor_key=monitor_key)[:5])

    if not recent:
        return {
            "status": "unknown",
            "status_label": "No Data",
            "last_heartbeat": None,
            "response_time_ms": 0,
        }

    last = recent[0]
    age_seconds = (now() - last.timestamp).total_seconds()

    # Determine status
    if last.status == "fail" or age_seconds > expected_interval * 5:
        status = "down"
        status_label = "Down"
    elif any(h.status == "fail" for h in recent):
        status = "degraded"
        status_label = "Degraded"
    else:
        status = "operational"
        status_label = "Operational"

    return {
        "status": status,
        "status_label": status_label,
        "last_heartbeat": last.timestamp,
        "response_time_ms": last.response_time_ms,
        "age_seconds": int(age_seconds),
    }


def _get_non_maintenance_ok_count(window_start, window_end, monitor_key: str = "site") -> int:
    """Count OK beats excluding those within SLA-excluded maintenance windows."""
    excluded_ranges = MaintenanceWindow.get_excluded_ranges(window_start, window_end, monitor_key)
    qs = Heartbeat.objects.filter(
        monitor_key=monitor_key, timestamp__gte=window_start, timestamp__lt=window_end, status="ok"
    )
    for s, e in excluded_ranges:
        qs = qs.exclude(timestamp__gte=s, timestamp__lt=e)
    return qs.count()


def _uptime_over_window(window_start, monitor_key: str = "site") -> UptimeResult:
    """Uptime + coverage over [window_start, now], blending daily summaries with raw beats.

    Raw ``Heartbeat`` rows are pruned after ``HEARTBEAT_RETENTION_DAYS`` into
    ``HeartbeatDaily``. For the span older than the oldest retained raw beat we
    use the daily summaries; for the recent span we use raw beats (maintenance-
    adjusted). Without this, a window that predates retention divides recent
    ok-counts by an epoch-length denominator and drifts far below 100%.

    Expected checks are floored to complete intervals; maintenance windows with
    exclude_from_sla=True are subtracted from the recent raw span. ``covered``
    is the slice of the window we have any data for (a missed beat still counts
    as covered — we know it was down; an in-epoch span with no raw beats and no
    summary does not).
    """
    interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    current = now()
    window_seconds = (current - window_start).total_seconds()
    if window_seconds <= 0:
        return UptimeResult(uptime=None, covered_seconds=0.0, window_seconds=max(window_seconds, 0.0))

    oldest_raw = (
        Heartbeat.objects.filter(monitor_key=monitor_key)
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
        .first()
    )

    # Span older than the oldest raw beat is covered by the daily summaries.
    summarized_ok = 0
    summarized_expected = 0
    summarized_days = 0
    raw_start = window_start
    summary_end_date = None
    if oldest_raw is None:
        raw_start = current  # no raw beats — everything comes from summaries
        summary_end_date = current.date() + timedelta(days=1)
    elif oldest_raw > window_start:
        raw_start = oldest_raw
        summary_end_date = oldest_raw.date()
    if summary_end_date is not None:
        rows = HeartbeatDaily.objects.filter(
            monitor_key=monitor_key, date__gte=window_start.date(), date__lt=summary_end_date
        ).values_list("ok_count", "expected_count")
        for ok, expected in rows:
            summarized_ok += ok
            summarized_expected += expected or 0
            summarized_days += 1

    # Recent span covered by raw beats.
    raw_ok = 0
    raw_expected = 0
    covered_recent = 0.0
    if raw_start < current:
        covered_recent = (current - raw_start).total_seconds()
        excluded = MaintenanceWindow.get_excluded_seconds(raw_start, current, monitor_key)
        effective = covered_recent - excluded
        if effective > 0:
            raw_expected = int(effective // interval)
            raw_ok = _get_non_maintenance_ok_count(raw_start, current, monitor_key)

    covered_seconds = min(covered_recent + summarized_days * _SECONDS_PER_DAY, window_seconds)
    total_expected = raw_expected + summarized_expected
    uptime = None
    if total_expected >= 1:
        uptime = min(round(((raw_ok + summarized_ok) / total_expected) * 100, 2), 100.0)
    return UptimeResult(uptime=uptime, covered_seconds=covered_seconds, window_seconds=window_seconds)


def _calc_uptime(hours: int, monitor_key: str = "site") -> float | None:
    """Uptime % over the last ``hours``, epoch-aware and retention-aware."""
    epoch = _get_epoch(monitor_key)
    window_start = now() - timedelta(hours=hours)
    if epoch and window_start < epoch:
        window_start = epoch
    return _uptime_over_window(window_start, monitor_key).uptime


def _calc_overall_uptime(monitor_key: str = "site") -> float | None:
    """Uptime % since the monitor's epoch, retention-aware (folds daily summaries)."""
    epoch = _get_epoch(monitor_key)
    if not epoch:
        return None
    return _uptime_over_window(epoch, monitor_key).uptime


def _coverage_since_epoch(monitor_key: str = "site") -> float | None:
    """Fraction (0–1) of the epoch→now span we have monitoring data for, or None.

    Surfaced on the SLA page so a low coverage (pruning never ran, partial
    restore, deleted summaries) is visible rather than silently over-reporting
    overall uptime.
    """
    epoch = _get_epoch(monitor_key)
    if not epoch:
        return None
    return _uptime_over_window(epoch, monitor_key).coverage


def _add_sla_context(context: dict, use_target: bool = False, monitor_key: str = "site") -> dict:
    """Add SLA targets and color/state info to a template context.

    use_target=True: 3-tier coloring (green/yellow/red) for dashboard.
    use_target=False: 2-tier coloring (green/red vs minimum) for public/SLA pages.
    """
    target, minimum = _get_sla_targets(monitor_key)
    context["sla_target"] = target
    context["sla_minimum"] = minimum

    # Color each uptime value (legacy inline-style pages) + a discrete state
    # name (stat-card tag on the dashboard).
    for key in ("uptime_overall", "uptime_24h", "uptime_7d"):
        val = context.get(key)
        context[f"{key}_color"] = _sla_color(val, use_target=use_target, monitor_key=monitor_key)
        context[f"{key}_state"] = _sla_state(val, use_target=use_target, monitor_key=monitor_key)

    return context


def _is_in_any_window(dt, windows) -> bool:
    """Check if a datetime falls within any of the given (start, end) tuples."""
    for ws, we in windows:
        if ws <= dt < we:
            return True
    return False


def _build_minute_timeline(minutes: int = 60, monitor_key: str = "site") -> list[dict]:
    """Build a slot-based timeline for the monitor over the last N minutes."""
    current = now()
    epoch = _get_epoch(monitor_key)
    cutoff = current - timedelta(minutes=minutes)

    beats = list(
        Heartbeat.objects.filter(monitor_key=monitor_key, timestamp__gte=cutoff)
        .order_by("timestamp")
        .values("status", "timestamp", "response_time_ms")
    )

    maint_windows = list(
        MaintenanceWindow.objects.filter(monitor_key=monitor_key, start__lt=current, end__gt=cutoff).values_list(
            "start", "end"
        )
    )

    slots = []
    for i in range(minutes):
        slot_start = cutoff + timedelta(minutes=i)
        slot_end = slot_start + timedelta(minutes=1)

        if epoch and slot_end <= epoch:
            slots.append(
                {
                    "status": "pre-epoch",
                    "timestamp": slot_start,
                    "response_time_ms": 0,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )
            continue

        in_maintenance = _is_in_any_window(slot_start, maint_windows)
        slot_beats = [b for b in beats if slot_start <= b["timestamp"] < slot_end]

        if in_maintenance:
            avg_ms = 0
            if slot_beats:
                avg_ms = sum(b["response_time_ms"] for b in slot_beats) // len(slot_beats)
            slots.append(
                {
                    "status": "maintenance",
                    "timestamp": slot_start,
                    "response_time_ms": avg_ms,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )
        elif slot_beats:
            has_fail = any(b["status"] == "fail" for b in slot_beats)
            avg_ms = sum(b["response_time_ms"] for b in slot_beats) // len(slot_beats)
            slots.append(
                {
                    "status": "fail" if has_fail else "ok",
                    "timestamp": slot_beats[0]["timestamp"],
                    "response_time_ms": avg_ms,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )
        else:
            slots.append(
                {
                    "status": "missed",
                    "timestamp": slot_start,
                    "response_time_ms": 0,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )

    return slots


def _build_24h_timeline(monitor_key: str = "site") -> list[dict]:
    """Build a 24-hour timeline for the monitor, grouped into 15-minute buckets."""
    current = now()
    epoch = _get_epoch(monitor_key)
    cutoff = current - timedelta(hours=24)

    beats = list(
        Heartbeat.objects.filter(monitor_key=monitor_key, timestamp__gte=cutoff)
        .order_by("timestamp")
        .values("status", "timestamp")
    )

    maint_windows = list(
        MaintenanceWindow.objects.filter(monitor_key=monitor_key, start__lt=current, end__gt=cutoff).values_list(
            "start", "end"
        )
    )

    slots = []
    for i in range(96):
        slot_start = cutoff + timedelta(minutes=i * 15)
        slot_end = slot_start + timedelta(minutes=15)

        if epoch and slot_end <= epoch:
            slots.append(
                {
                    "status": "pre-epoch",
                    "ok_count": 0,
                    "fail_count": 0,
                    "total": 0,
                    "hour_label": localtime(slot_start).strftime("%-I:%M %p"),
                    "timestamp": slot_start,
                }
            )
            continue

        in_maintenance = any(ws < slot_end and we > slot_start for ws, we in maint_windows)

        slot_beats = [b for b in beats if slot_start <= b["timestamp"] < slot_end]
        ok_count = sum(1 for b in slot_beats if b["status"] == "ok")
        fail_count = sum(1 for b in slot_beats if b["status"] == "fail")
        total = len(slot_beats)

        if in_maintenance:
            status = "maintenance"
        elif total == 0:
            status = "missed"
        elif fail_count > 0 and ok_count > 0:
            status = "partial"
        elif fail_count > 0:
            status = "fail"
        else:
            status = "ok"

        slots.append(
            {
                "status": status,
                "ok_count": ok_count,
                "fail_count": fail_count,
                "total": total,
                "hour_label": localtime(slot_start).strftime("%-I:%M %p"),
                "timestamp": slot_start,
            }
        )

    return slots


def _daily_uptime_map(monitor_key: str, start, end) -> dict:
    """Map each date in ``[start, end]`` (inclusive) to its uptime %, or None.

    Uses the pruned ``HeartbeatDaily`` summary when present, else raw beats (recent,
    un-pruned days). Shared by the 90-day timeline and the calendar so they agree.
    """
    from datetime import datetime as _dt
    from datetime import time as _time

    from django.db.models import Count, Q
    from django.db.models.functions import TruncDate
    from django.utils import timezone
    from django.utils.timezone import make_aware

    interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    today = timezone.localdate()

    summaries = {
        d.date: d
        for d in HeartbeatDaily.objects.filter(monitor_key=monitor_key, date__gte=start, date__lte=end)
    }
    window_start = make_aware(_dt.combine(start, _time.min))
    window_end = make_aware(_dt.combine(end + timedelta(days=1), _time.min))
    raw_rows = (
        Heartbeat.objects.filter(monitor_key=monitor_key, timestamp__gte=window_start, timestamp__lt=window_end)
        .annotate(day=TruncDate("timestamp"))
        .values("day")
        .annotate(ok=Count("id", filter=Q(status="ok")), total=Count("id"))
    )
    raw_by_date = {r["day"]: r for r in raw_rows}

    now_local = localtime(now())
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_today = max((now_local - midnight).total_seconds(), 60)
    full_day_expected = max(int(86400 // interval), 1)

    result: dict = {}
    day = start
    while day <= end:
        uptime: float | None = None
        summary = summaries.get(day)
        if summary is not None and summary.expected_count:
            uptime = float(summary.uptime_pct)
        else:
            raw = raw_by_date.get(day)
            if raw and raw["total"]:
                expected = max(int(elapsed_today // interval), 1) if day == today else full_day_expected
                uptime = min(round(raw["ok"] / expected * 100, 2), 100.0)
        result[day] = uptime
        day += timedelta(days=1)
    return result


def _classify_day(uptime: float | None, day, epoch_date, target: float, minimum: float) -> str:
    """Classify a day's uptime vs SLA: up / degraded / down / nodata (pre-epoch or no data)."""
    if epoch_date and day < epoch_date:
        return "nodata"
    if uptime is None:
        return "nodata"
    if uptime >= target:
        return "up"
    if uptime >= minimum:
        return "degraded"
    return "down"


def _maintenance_by_date(monitor_key: str | None, start, end) -> dict:
    """Map each date a maintenance window touches (within ``[start, end]``) to its windows.

    ``monitor_key=None`` includes every monitor's windows (for the all-monitor
    maintenance calendar).
    """
    from datetime import datetime as _dt
    from datetime import time as _time

    from django.utils.timezone import make_aware

    s = make_aware(_dt.combine(start, _time.min))
    e = make_aware(_dt.combine(end + timedelta(days=1), _time.min))
    qs = MaintenanceWindow.objects.filter(start__lt=e, end__gt=s)
    if monitor_key:
        qs = qs.filter(monitor_key=monitor_key)
    result: dict = {}
    for w in qs.order_by("start"):
        day = localtime(w.start).date()
        last = localtime(w.end).date()
        while day <= last:
            if start <= day <= end:
                result.setdefault(day, []).append(
                    {
                        "monitor_key": w.monitor_key,
                        "title": w.title,
                        "start": localtime(w.start).strftime("%b %-d, %-I:%M %p"),
                        "end": localtime(w.end).strftime("%b %-d, %-I:%M %p"),
                        "note": w.note,
                    }
                )
            day += timedelta(days=1)
    return result


def _build_maintenance_calendar(
    months_back: int = 2, months_forward: int = 3, monitor_key: str | None = None
) -> list[dict]:
    """A rolling calendar (oldest→newest) marking only days with maintenance windows.

    Spans ``months_back`` months before the current month through ``months_forward``
    after it (default = the recent 3 months incl. current + the next 3 → a 6-month
    window). Every in-month day is a cell; days touched by a maintenance window are
    flagged with their window details for hover, and "today" is marked.
    """
    import calendar as _cal
    from datetime import date as _date

    from django.utils import timezone

    today = timezone.localdate()
    start_idx = today.year * 12 + (today.month - 1) - months_back
    total = months_back + 1 + months_forward

    ym = [divmod(start_idx + k, 12) for k in range(total)]
    ym = [(y, m + 1) for y, m in ym]

    range_start = _date(ym[0][0], ym[0][1], 1)
    last_y, last_m = ym[-1]
    range_end = _date(last_y, last_m, _cal.monthrange(last_y, last_m)[1])
    maint_map = _maintenance_by_date(monitor_key, range_start, range_end)

    cal = _cal.Calendar(firstweekday=6)  # Sunday-first
    out: list[dict] = []
    for yy, mm in ym:
        weeks: list[list] = []
        count = 0
        for week in cal.monthdatescalendar(yy, mm):
            cells = []
            for d in week:
                if d.month != mm:
                    cells.append(None)
                    continue
                maint = maint_map.get(d)
                if maint:
                    count += 1
                    tip = f"{maint[0]['title']} · {maint[0]['start']}"
                    if len(maint) > 1:
                        tip = f"{len(maint)} maintenance windows · {d.strftime('%b %-d')}"
                else:
                    tip = ""
                cells.append(
                    {
                        "day": d.day,
                        "date": d,
                        "is_today": d == today,
                        "maintenance": maint,
                        "tip": tip,
                    }
                )
            weeks.append(cells)
        out.append(
            {
                "year": yy,
                "month": mm,
                "name": _date(yy, mm, 1).strftime("%B %Y"),
                "weeks": weeks,
                "count": count,
                "is_current": yy == today.year and mm == today.month,
            }
        )
    return out


def _build_daily_timeline(days: int = 90, monitor_key: str = "site") -> list[dict]:
    """One entry per day for the last ``days`` days — the public 90-day timeline.

    Classified against the monitor's SLA (up / degraded / down / nodata). Oldest-first
    so it renders left (90 days ago) to right (today), Claude-status style.
    """
    from django.utils import timezone

    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    epoch = _get_epoch(monitor_key)
    epoch_date = localtime(epoch).date() if epoch else None
    target, minimum = _get_sla_targets(monitor_key)
    uptime_map = _daily_uptime_map(monitor_key, start, today)

    slots: list[dict] = []
    for i in range(days):
        day = start + timedelta(days=i)
        uptime = uptime_map.get(day)
        status = _classify_day(uptime, day, epoch_date, target, minimum)
        label = day.strftime("%b %-d, %Y")
        tip = f"{label} · No data" if status == "nodata" else f"{label} · {uptime}% uptime"
        slots.append({"date": day, "status": status, "uptime": uptime, "label": label, "tip": tip})
    return slots


def _build_hourly_timeline(hours: int = 24, monitor_key: str = "site") -> list[dict]:
    """One bar per hour over the last ``hours`` hours — the short-term (1d / 7d) timeline.

    Classified from raw beats by *failures* (not data completeness), so a stalled
    runner reads as "no data" (gray), not "down": ``up`` (only ok) / ``degraded``
    (ok + fail) / ``down`` (only fail) / ``maintenance`` / ``nodata``. Same status
    vocabulary as the daily timeline, so both render through one template.
    """
    current = now()
    cutoff = current - timedelta(hours=hours)
    epoch = _get_epoch(monitor_key)
    beats = list(
        Heartbeat.objects.filter(monitor_key=monitor_key, timestamp__gte=cutoff).values("status", "timestamp")
    )
    maint = list(
        MaintenanceWindow.objects.filter(monitor_key=monitor_key, start__lt=current, end__gt=cutoff).values_list(
            "start", "end"
        )
    )

    slots: list[dict] = []
    for i in range(hours):
        bstart = cutoff + timedelta(hours=i)
        bend = bstart + timedelta(hours=1)
        label = localtime(bstart).strftime("%b %-d, %-I %p")
        if epoch and bend <= epoch:
            slots.append({"status": "nodata", "tip": f"{label} · Not monitored"})
            continue
        bucket = [b for b in beats if bstart <= b["timestamp"] < bend]
        ok = sum(1 for b in bucket if b["status"] == "ok")
        fail = sum(1 for b in bucket if b["status"] == "fail")
        if any(ws < bend and we > bstart for ws, we in maint):
            status, tip = "maintenance", f"{label} · Maintenance"
        elif not bucket:
            status, tip = "nodata", f"{label} · No data"
        elif fail and ok:
            status, tip = "degraded", f"{label} · {ok} ok, {fail} fail"
        elif fail:
            status, tip = "down", f"{label} · {fail} failure{'' if fail == 1 else 's'}"
        else:
            status, tip = "up", f"{label} · {ok} ok"
        slots.append({"status": status, "tip": tip})
    return slots


def build_stacked_timelines(monitor_key: str = "site") -> list[dict]:
    """Public-status-style stacked **1d / 7d / 90d** uptime bar rows for one monitor.

    Shared by the public board, the staff dashboard, and the per-monitor detail
    page so all three render identically through ``heartbeat/_site_timelines.html``.
    Each row is ``{window, ago, now_label, uptime, slots}``; slots come from the
    hourly builder (1d / 7d) and the daily builder (90d), both ``{status, tip}``.
    """
    return [
        {"window": "Last 24 hours", "ago": "24 hours ago", "now_label": "Now",
         "uptime": _calc_uptime(24, monitor_key), "slots": _build_hourly_timeline(24, monitor_key)},
        {"window": "Last 7 days", "ago": "7 days ago", "now_label": "Today",
         "uptime": _calc_uptime(168, monitor_key), "slots": _build_hourly_timeline(168, monitor_key)},
        {"window": "Last 90 days", "ago": "90 days ago", "now_label": "Today",
         "uptime": _calc_uptime(90 * 24, monitor_key), "slots": _build_daily_timeline(90, monitor_key)},
    ]


def _upcoming_maintenance(days: int = 90, monitor_key: str | None = None) -> list[dict]:
    """Maintenance windows that are in progress or starting within the next ``days`` days."""
    current = now()
    horizon = current + timedelta(days=days)
    qs = MaintenanceWindow.objects.filter(end__gte=current, start__lte=horizon)
    if monitor_key:
        qs = qs.filter(monitor_key=monitor_key)
    out: list[dict] = []
    for w in qs.order_by("start"):
        minutes = int((w.end - w.start).total_seconds() // 60)
        out.append(
            {
                "title": w.title,
                "monitor_key": w.monitor_key,
                "start": localtime(w.start),
                "end": localtime(w.end),
                "duration_minutes": minutes,
                "note": w.note,
                "exclude_from_sla": w.exclude_from_sla,
                "in_progress": w.start <= current <= w.end,
            }
        )
    return out


def _build_calendar_months(
    monitor_key: str = "site", end_year: int | None = None, end_month: int | None = None, months: int = 3
) -> list[dict]:
    """A rolling N-month calendar (oldest→newest) of daily cells — the Claude-status grid.

    Each month is laid out as real calendar weeks (Sunday-first). Each in-month, non-future
    day is classified against the SLA; a day touched by a maintenance window is flagged
    ``maintenance`` (striped) and carries its window details for hover. Padding days from
    adjacent months are ``None``; future days are flagged ``is_future``.
    """
    import calendar as _cal
    from datetime import date as _date

    from django.utils import timezone

    today = timezone.localdate()
    if end_year is None or end_month is None:
        end_year, end_month = today.year, today.month

    # The (year, month) pairs, oldest first.
    ym: list[tuple[int, int]] = []
    y, m = end_year, end_month
    for _ in range(months):
        ym.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    ym.reverse()

    range_start = _date(ym[0][0], ym[0][1], 1)
    last_y, last_m = ym[-1]
    range_end = _date(last_y, last_m, _cal.monthrange(last_y, last_m)[1])
    uptime_map = _daily_uptime_map(monitor_key, range_start, range_end)
    maint_map = _maintenance_by_date(monitor_key, range_start, range_end)
    epoch = _get_epoch(monitor_key)
    epoch_date = localtime(epoch).date() if epoch else None
    target, minimum = _get_sla_targets(monitor_key)

    cal = _cal.Calendar(firstweekday=6)  # Sunday-first, like the Claude grid
    out: list[dict] = []
    for yy, mm in ym:
        weeks: list[list] = []
        month_upts: list[float] = []
        for week in cal.monthdatescalendar(yy, mm):
            cells = []
            for d in week:
                if d.month != mm:
                    cells.append(None)
                elif d > today:
                    cells.append({"day": d.day, "is_future": True, "status": "future"})
                else:
                    up = uptime_map.get(d)
                    if up is not None:
                        month_upts.append(up)
                    maint = maint_map.get(d)
                    status = "maintenance" if maint else _classify_day(up, d, epoch_date, target, minimum)
                    cells.append(
                        {
                            "day": d.day,
                            "date": d,
                            "status": status,
                            "uptime": up,
                            "maintenance": maint,
                            "label": d.strftime("%b %-d, %Y"),
                        }
                    )
            weeks.append(cells)
        month_pct = round(sum(month_upts) / len(month_upts), 2) if month_upts else None
        out.append(
            {
                "year": yy,
                "month": mm,
                "name": _date(yy, mm, 1).strftime("%B %Y"),
                "uptime_pct": month_pct,
                "weeks": weeks,
            }
        )
    return out
