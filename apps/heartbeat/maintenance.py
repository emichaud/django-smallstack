"""Programmatic helpers for maintenance windows.

These wrap the :class:`~apps.heartbeat.models.MaintenanceWindow` model so the
``maintenance`` management command (and any future caller — a deploy hook, an
ops script) shares one implementation. Maintenance windows mark a span of time
as *planned* downtime so the status page reads "Under maintenance" instead of
"Down" and the SLA calculation excludes it (see ``MaintenanceWindow`` in
``models.py`` and its use in ``status.py``).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.utils.timezone import get_current_timezone, is_naive, make_aware, now

from .models import MaintenanceWindow


def _aware(dt: datetime) -> datetime:
    """Coerce a naive datetime to the current timezone (mirrors the staff view)."""
    return make_aware(dt, get_current_timezone()) if is_naive(dt) else dt


def open_window(
    title: str,
    start: datetime,
    end: datetime,
    *,
    monitor_key: str = "site",
    note: str = "",
    exclude_from_sla: bool = True,
) -> MaintenanceWindow:
    """Create and return a maintenance window.

    ``start``/``end`` may be naive (interpreted in the project timezone) or
    aware. Raises ``ValueError`` if ``end`` is not after ``start``.
    """
    start = _aware(start)
    end = _aware(end)
    if end <= start:
        raise ValueError("end must be after start")
    return MaintenanceWindow.objects.create(
        monitor_key=monitor_key,
        title=title,
        start=start,
        end=end,
        note=note,
        exclude_from_sla=exclude_from_sla,
    )


def open_window_for(
    minutes: int,
    title: str,
    *,
    monitor_key: str = "site",
    note: str = "",
    exclude_from_sla: bool = True,
) -> MaintenanceWindow:
    """Open a window starting now and lasting ``minutes`` minutes.

    A bounded window is the safety net for deploys: if the matching ``close``
    never runs (a deploy aborts midway), the window simply expires on its own.
    """
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    start = now()
    return open_window(
        title,
        start,
        start + timedelta(minutes=minutes),
        monitor_key=monitor_key,
        note=note,
        exclude_from_sla=exclude_from_sla,
    )


def close_windows(*, monitor_key: str = "site", delete_future: bool = False) -> dict[str, int]:
    """End any currently-active windows for ``monitor_key`` (set ``end`` to now).

    With ``delete_future=True`` also delete windows that haven't started yet.
    Returns a dict with ``ended`` and ``deleted`` counts.
    """
    moment = now()
    active = MaintenanceWindow.objects.filter(monitor_key=monitor_key, start__lte=moment, end__gt=moment)
    ended = active.update(end=moment)

    deleted = 0
    if delete_future:
        deleted, _ = MaintenanceWindow.objects.filter(monitor_key=monitor_key, start__gt=moment).delete()

    return {"ended": ended, "deleted": deleted}


def list_windows(*, monitor_key: str | None = "site", active_only: bool = False):
    """Return a queryset of windows, optionally filtered to the active ones.

    Pass ``monitor_key=None`` to list windows across all monitors.
    """
    qs = MaintenanceWindow.objects.all()
    if monitor_key is not None:
        qs = qs.filter(monitor_key=monitor_key)
    if active_only:
        moment = now()
        qs = qs.filter(start__lte=moment, end__gt=moment)
    return qs
