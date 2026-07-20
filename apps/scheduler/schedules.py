"""Next-run math + interval parsing for the scheduler.

Three schedule types:

- ``once``     — fire a single time at ``run_at``; no next run after it fires.
- ``interval`` — repeat on a fixed ``interval_spec`` (``5m``, ``2h``, ``1d``,
  ``90d``, ``1mo``, ``1y``), optionally phase-locked to an ``anchor_at`` so
  "every 90d from date X" / "every 1y from Dec 25" land on the anchor's cadence.
- ``cron``     — a standard 5-field cron expression evaluated in the job's
  timezone via ``croniter``.

Everything here is pure (no DB, no ``timezone.now()`` reached implicitly) so the
next-run rules are trivially unit-testable: callers pass ``after`` explicitly.

``croniter`` (and its ``python-dateutil`` dependency, which powers month/year
intervals) is only imported when a cron/calendar schedule actually needs it, so
``once`` and second-based intervals stay dependency-light.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, tzinfo
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol, Union

if TYPE_CHECKING:
    from dateutil.relativedelta import relativedelta

# Either a fixed-length delta (s/m/h/d/w) or a calendar delta (mo/y).
IntervalDelta = Union[timedelta, "relativedelta"]


class ScheduleLike(Protocol):
    """The duck-typed surface next_run() needs — a ScheduledJob or any stand-in.

    Kept as a Protocol so the pure math stays callable on an unsaved model
    instance (validation) or a lightweight test double, without importing the
    model (which would create an apps-not-ready import cycle).
    """

    schedule_type: str
    interval_spec: str
    anchor_at: datetime | None
    cron_expression: str
    run_at: datetime | None
    timezone: str

# Fixed-length units resolve straight to a timedelta. Month/year are *calendar*
# units (variable length) and are handled with dateutil.relativedelta so that
# "1mo from Jan 31" and "1y from Feb 29" behave like a human expects.
_FIXED_UNITS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}
_CALENDAR_UNITS = {"mo": "months", "y": "years"}

# Order matters: match the two-letter "mo" before the single-letter units.
_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*(mo|[smhdwy])\s*$", re.IGNORECASE)


class ScheduleConfigError(ValueError):
    """Raised when a schedule's fields don't describe a valid cadence."""


def parse_interval(spec: str) -> IntervalDelta:
    """Parse an interval spec into a ``timedelta`` or ``relativedelta``.

    Fixed units (``s/m/h/d/w``) return a ``timedelta``; calendar units
    (``mo/y``) return a ``dateutil.relativedelta`` so month/year stepping is
    calendar-correct. Raises :class:`ScheduleConfigError` on a malformed spec.
    """
    match = _INTERVAL_RE.match(spec or "")
    if not match:
        raise ScheduleConfigError(
            f"Bad interval {spec!r}. Use forms like 5m, 2h, 1d, 90d, 1mo, 1y."
        )
    count, unit = int(match.group(1)), match.group(2).lower()
    if count <= 0:
        raise ScheduleConfigError(f"Interval count must be positive, got {spec!r}.")
    if unit in _FIXED_UNITS:
        return timedelta(**{_FIXED_UNITS[unit]: count})
    # Calendar unit — needs dateutil (ships transitively with croniter).
    try:
        from dateutil.relativedelta import relativedelta
    except ImportError as exc:  # pragma: no cover - dateutil is a croniter dep
        raise ScheduleConfigError(
            "Month/year intervals require python-dateutil (installed with croniter)."
        ) from exc
    return relativedelta(**{_CALENDAR_UNITS[unit]: count})


def _step_interval(anchor: datetime, spec: str, after: datetime) -> datetime:
    """Smallest ``anchor + k*delta`` (k >= 1 minimum enforced by caller) > ``after``.

    Walks forward from ``anchor`` by the interval until strictly past ``after``.
    For fixed intervals we jump straight to the right multiple in O(1); for
    calendar intervals we step (bounded) because relativedelta isn't linear.
    """
    delta = parse_interval(spec)
    if isinstance(delta, timedelta):
        # O(1): how many whole periods fit between anchor and `after`, then +1.
        gap = (after - anchor).total_seconds()
        period = delta.total_seconds()
        if gap < 0:
            # anchor is already in the future — it is itself the next fire.
            return anchor
        steps = int(gap // period) + 1
        return anchor + steps * delta
    # Calendar interval — step forward until strictly after `after`.
    nxt = anchor
    # Bound the loop so a misconfigured anchor far in the past can't spin forever.
    for _ in range(10_000):
        if nxt > after:
            return nxt
        nxt = nxt + delta
    return nxt  # pragma: no cover - only reachable with absurd anchors


def next_run(schedule: ScheduleLike, *, after: datetime) -> datetime | None:
    """Return the next fire time strictly after ``after``, or ``None``.

    ``None`` means "never again" — a ``once`` job whose time has passed. The
    caller (``run_due_jobs``) treats ``None`` as "retire this schedule".

    ``schedule`` is duck-typed: any object exposing ``schedule_type`` and the
    matching fields works, so this is callable on an unsaved model instance
    during validation.
    """
    stype = schedule.schedule_type
    if stype == "once":
        run_at = schedule.run_at
        if run_at is None:
            raise ScheduleConfigError("A 'once' schedule needs run_at.")
        return run_at if run_at > after else None

    if stype == "interval":
        spec = schedule.interval_spec
        if not spec:
            raise ScheduleConfigError("An 'interval' schedule needs interval_spec.")
        anchor = schedule.anchor_at
        if anchor is None:
            # Unanchored: next run is simply `after + one interval`.
            return _step_interval(after, spec, after)
        return _step_interval(anchor, spec, after)

    if stype == "cron":
        expr = schedule.cron_expression
        if not expr:
            raise ScheduleConfigError("A 'cron' schedule needs cron_expression.")
        return _cron_next(expr, schedule_tz(schedule), after)

    raise ScheduleConfigError(f"Unknown schedule_type {stype!r}.")


@lru_cache(maxsize=1)
def _tz_canonical_map() -> dict[str, str]:
    """lowercased IANA name -> canonical name, built once from the tz database.

    ``available_timezones()`` returns canonical keys identically on every OS, so
    resolving through this map is platform-independent — unlike ``ZoneInfo(name)``,
    whose filesystem lookup is *case-insensitive on macOS* but case-sensitive on
    Linux. (``tzdata`` is a hard dependency so the set is populated in slim
    containers that ship no system zoneinfo.)
    """
    from zoneinfo import available_timezones

    return {name.lower(): name for name in available_timezones()}


def canonical_timezone(name: str) -> str | None:
    """Return the canonical IANA name for ``name`` (case-insensitive), or None.

    Closes a dev/prod footgun: ``"america/new_york"`` silently works on a macOS
    dev box but raises ``ZoneInfoNotFoundError`` on case-sensitive Linux prod.
    Normalizing here makes both behave the same.
    """
    if not name:
        return None
    return _tz_canonical_map().get(name.strip().lower())


def schedule_tz(schedule: ScheduleLike) -> tzinfo:
    """Resolve the schedule's evaluation timezone (falls back to Django's)."""
    from django.utils import timezone as djtz

    name = getattr(schedule, "timezone", "") or ""
    if not name:
        return djtz.get_current_timezone()
    canonical = canonical_timezone(name)
    if canonical is None:
        raise ScheduleConfigError(f"Unknown timezone {name!r}.")
    from zoneinfo import ZoneInfo

    return ZoneInfo(canonical)


def _cron_next(expr: str, tz: tzinfo, after: datetime) -> datetime:
    """Next cron fire strictly after ``after``, timezone-aware.

    ``croniter`` does the cron arithmetic in the target timezone; we hand back
    an aware datetime in that same zone so the DB stores a correct UTC instant.
    """
    from croniter import CroniterError, croniter

    # Evaluate in the schedule's own timezone so "0 6 * * *" means 6am *there*,
    # crossing DST correctly, regardless of the server's zone.
    local_after = after.astimezone(tz)
    try:
        # get_next() must be inside the try: an *impossible* cron (e.g. "0 0 30 2 *"
        # — Feb 30) parses fine but raises CroniterBadDateError only when advanced,
        # which would otherwise escape as a 500 on save/clean/PATCH.
        return croniter(expr, local_after).get_next(datetime)
    except (CroniterError, ValueError) as exc:
        raise ScheduleConfigError(f"Bad cron expression {expr!r}: {exc}") from exc


def missed_periods(schedule: ScheduleLike, *, scheduled_for: datetime, now: datetime) -> int:
    """How many whole periods elapsed between ``scheduled_for`` and ``now``.

    ``0`` means the tick is on time (fired within one period of its due time);
    ``>= 1`` means the scheduler was down/slow and at least one additional fire
    was skipped — used by the catch-up policy to decide fire-once vs skip.
    """
    if scheduled_for is None or now <= scheduled_for:
        return 0
    if schedule.schedule_type == "interval" and schedule.interval_spec:
        delta = parse_interval(schedule.interval_spec)
        if isinstance(delta, timedelta):
            return int((now - scheduled_for).total_seconds() // delta.total_seconds())
        # Calendar interval: count forward steps that fit before `now`.
        from dateutil.relativedelta import relativedelta  # noqa: F401

        count, cursor = 0, scheduled_for
        for _ in range(10_000):
            cursor = cursor + delta
            if cursor > now:
                break
            count += 1
        return count
    if schedule.schedule_type == "cron" and schedule.cron_expression:
        tz = schedule_tz(schedule)
        count, cursor = 0, scheduled_for
        for _ in range(10_000):
            cursor = _cron_next(schedule.cron_expression, tz, cursor)
            if cursor > now:
                break
            count += 1
        return count
    return 0
