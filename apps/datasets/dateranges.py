"""Relative date periods — the ``(since, until)`` bounds behind a stored
"Month to date" / "Previous quarter" / "Last 30 days" filter.

A period is resolved against *now* at query time, never frozen when the filter
is authored: a saved "Month to date" metric always means the current month. That
is what makes a stored filter tree (see ``filter_tree.py``) usable for a
dashboard that is still correct next quarter.

Every bound is a **local midnight** and every range is **half-open**
``[since, until)``, so one definition serves date and datetime columns alike
(a date column compares against ``since.date()`` / ``until.date()``). The
"to date" periods run through the end of *today* — day granularity, not
"up to this second" — which is what a dashboard reader means by "MTD".

Ported from call_stats' ``apps/datasets/dateranges.py`` with the service-desk
specifics removed. What changed for a spec stored against the original:

* ``previous`` is now ``yesterday``. The old key still resolves (``PERIOD_ALIASES``).
* ``wtd`` ran Monday through Saturday; it now runs Monday through today.
  ``pwtd`` was last Monday through Friday; it is now the whole of last week.
* ``today`` / ``mtd`` / ``qtd`` / ``ytd`` ended at *now*; they now end at
  tomorrow's midnight, so a row dated later today now counts.
* ``last_<N>`` was the rolling N×24 hours before now; it is now N calendar
  days ending today, from local midnight.
* ``relative_range()`` returned ``(None, None)`` for an unknown key and could
  return an open upper bound; it now returns ``None`` or two bounds.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from django.utils import timezone

#: The vocabulary a date filter offers, as ordered ``(key, label)`` pairs. It
#: ships to builders in ``schema()["filters"][*]["periods"]`` so the dropdown and
#: the resolver share one source of truth. ``last_<N>`` / ``next_<N>`` are also
#: accepted for any positive N (only the common ones are listed).
RELATIVE_PERIODS: list[tuple[str, str]] = [
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("wtd", "Week to date"),
    ("pwtd", "Previous week"),
    ("mtd", "Month to date"),
    ("this_month", "This month, whole"),
    ("pmtd", "Previous month"),
    ("qtd", "Quarter to date"),
    ("pqtr", "Previous quarter"),
    ("ytd", "Year to date"),
    ("this_year", "This year, whole"),
    ("prev_year", "Previous year"),
    ("last_7", "Last 7 days"),
    ("last_30", "Last 30 days"),
    ("last_90", "Last 90 days"),
    ("next_7", "Next 7 days"),
    ("next_30", "Next 30 days"),
]

# Not offered in pickers: it exists so "last week" has a week to compare with.
_PERIOD_LABELS = {**dict(RELATIVE_PERIODS), "ppwtd": "The week before last"}

#: Keys an earlier vocabulary used. They still resolve, so a stored spec keeps
#: working, but no picker offers them. ``previous`` is call_stats' name for
#: yesterday, from before the port.
PERIOD_ALIASES: dict[str, str] = {"previous": "yesterday"}

#: Ceiling for the generic ``last_<N>`` / ``next_<N>`` spellings (~27 years) —
#: past it the date arithmetic overflows; nobody means it.
_MAX_ROLLING_DAYS = 10_000


def _rolling_days(key: str, prefix: str) -> Optional[int]:
    if not key.startswith(prefix):
        return None
    try:
        days = int(key[len(prefix) :])
    except ValueError:
        return None
    return days if 0 < days <= _MAX_ROLLING_DAYS else None


def is_period(key: object) -> bool:
    """True when *key* names a period :func:`relative_dates` can resolve."""
    if not isinstance(key, str):
        return False
    key = PERIOD_ALIASES.get(key, key)
    return key in _PERIOD_LABELS or _rolling_days(key, "last_") is not None or _rolling_days(key, "next_") is not None


def period_label(key: str) -> str:
    """Human label for a period key ("mtd" → "Month to date", "last_45" →
    "Last 45 days"). Unknown keys come back unchanged."""
    key = PERIOD_ALIASES.get(key, key)
    if key in _PERIOD_LABELS:
        return _PERIOD_LABELS[key]
    for prefix, word in (("last_", "Last"), ("next_", "Next")):
        days = _rolling_days(key, prefix)
        if days is not None:
            return f"{word} {days} day{'s' if days != 1 else ''}"
    return key


def _shift_month(d: date, months: int) -> date:
    """First of the month *months* away from *d*'s month (d must be a 1st)."""
    index = d.year * 12 + (d.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def relative_dates(key: str, today: Optional[date] = None) -> Optional[tuple[date, date]]:
    """``[since, until)`` as *dates* for a period key, or ``None`` if unknown.

    ``today`` defaults to the local date. Pure — no database, no settings
    beyond the active timezone.
    """
    if not isinstance(key, str):
        return None
    key = PERIOD_ALIASES.get(key, key)
    if today is None:
        today = _today()
    tomorrow = today + timedelta(days=1)

    days = _rolling_days(key, "last_")
    if days is not None:  # N days ending today, inclusive
        return today - timedelta(days=days - 1), tomorrow
    days = _rolling_days(key, "next_")
    if days is not None:  # N days starting today, inclusive
        return today, today + timedelta(days=days)

    if key == "today":
        return today, tomorrow
    if key == "yesterday":
        return today - timedelta(days=1), today

    if key in ("wtd", "pwtd", "ppwtd"):
        week_start = today - timedelta(days=today.weekday())  # Monday
        if key == "wtd":
            return week_start, tomorrow
        if key == "ppwtd":
            return week_start - timedelta(days=14), week_start - timedelta(days=7)
        return week_start - timedelta(days=7), week_start

    month_start = today.replace(day=1)
    if key == "mtd":
        return month_start, tomorrow
    if key == "this_month":  # the whole calendar month, days to come included
        return month_start, _shift_month(month_start, 1)
    if key == "pmtd":
        return _shift_month(month_start, -1), month_start

    quarter_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    if key == "qtd":
        return quarter_start, tomorrow
    if key == "pqtr":
        return _shift_month(quarter_start, -3), quarter_start

    year_start = date(today.year, 1, 1)
    if key == "ytd":
        return year_start, tomorrow
    if key == "this_year":  # the whole calendar year
        return year_start, date(today.year + 1, 1, 1)
    if key == "prev_year":
        return date(today.year - 1, 1, 1), year_start
    return None


def relative_range(key: str, now: Optional[datetime] = None) -> Optional[tuple[datetime, datetime]]:
    """``[since, until)`` as timezone-aware local-midnight datetimes, or
    ``None`` for an unknown key. ``now`` defaults to ``timezone.now()``."""
    today = _today(now)
    bounds = relative_dates(key, today)
    if bounds is None:
        return None
    since, until = bounds
    return _local_midnight(since), _local_midnight(until)


def _today(now: Optional[datetime] = None) -> date:
    """The local date of *now* (default: the current instant)."""
    from django.conf import settings

    if not settings.USE_TZ:
        return (now or datetime.now()).date()
    return timezone.localdate(now) if now is not None else timezone.localdate()


def _local_midnight(d: date) -> datetime:
    from django.conf import settings

    naive = datetime.combine(d, time.min)
    return timezone.make_aware(naive) if settings.USE_TZ else naive
