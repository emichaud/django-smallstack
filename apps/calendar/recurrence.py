"""Working out the dates of a repeating event.

A series is one ``Event`` row with a rule, expanded when a window is read: never
stored per occurrence, so an open-ended series costs nothing and an edit reaches
every date. Pure date arithmetic, no database.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Iterator, Optional

DAILY = "daily"
WEEKDAYS = "weekdays"
WEEKLY = "weekly"
BIWEEKLY = "biweekly"
MONTHLY = "monthly"
MONTHLY_WEEKDAY = "monthly_weekday"
YEARLY = "yearly"

REPEAT_CHOICES = [
    (DAILY, "Every day"),
    (WEEKDAYS, "Every weekday (Monday to Friday)"),
    (WEEKLY, "Every week"),
    (BIWEEKLY, "Every 2 weeks"),
    (MONTHLY, "Every month, on the same date"),
    (MONTHLY_WEEKDAY, "Every month, on the same weekday (like the 2nd Tuesday)"),
    (YEARLY, "Every year"),
]

#: The fewest days between two occurrences: a span must fit inside it.
SHORTEST_GAP = {DAILY: 1, WEEKDAYS: 1, WEEKLY: 7, BIWEEKLY: 14, MONTHLY: 28, MONTHLY_WEEKDAY: 28, YEARLY: 365}

_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "last"}


def _month(start: date, months: int) -> tuple[int, int]:
    index = start.year * 12 + (start.month - 1) + months
    return index // 12, index % 12 + 1


def _on_date(start: date, months: int) -> date:
    """The same date *months* on. The 31st falls on the last day of a shorter month."""
    year, month = _month(start, months)
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _on_weekday(start: date, months: int) -> date:
    """The same nth weekday *months* on. A 5th Friday is "the last Friday" where
    a month has only four."""
    year, month = _month(start, months)
    first_weekday, days = calendar.monthrange(year, month)
    first = 1 + (start.weekday() - first_weekday) % 7
    nth = (start.day - 1) // 7
    day = first + nth * 7
    return date(year, month, day if day <= days else day - 7)


def occurrence_starts(
    start: date,
    repeat: str,
    lower: date,
    upper: date,
    *,
    until: Optional[date] = None,
    span_days: int = 0,
    skip: frozenset[date] = frozenset(),
) -> Iterator[date]:
    """Each start date whose occurrence (``span_days`` long) touches ``[lower,
    upper)``, oldest first. *until* is the last date one may start."""
    earliest = lower - timedelta(days=span_days)

    def wanted(day: date) -> bool:
        return day >= earliest and day not in skip

    def ended(day: date) -> bool:
        return day >= upper or (until is not None and day > until)

    if repeat in (DAILY, WEEKDAYS, WEEKLY, BIWEEKLY):
        step = {DAILY: 1, WEEKDAYS: 1, WEEKLY: 7, BIWEEKLY: 14}[repeat]
        # Jump to the window: a daily series may be years old.
        day = start + timedelta(days=max(0, (earliest - start).days // step) * step)
        while not ended(day):
            if wanted(day) and (repeat != WEEKDAYS or day.weekday() < 5):
                yield day
            day += timedelta(days=step)
        return
    if repeat in (MONTHLY, MONTHLY_WEEKDAY, YEARLY):
        unit = 12 if repeat == YEARLY else 1
        place = _on_weekday if repeat == MONTHLY_WEEKDAY else _on_date
        behind = (earliest.year - start.year) * 12 + earliest.month - start.month
        # One step back: a clamped date can sit just before the month it stands for.
        k = max(0, behind // unit - 1)
        while True:
            day = place(start, k * unit)
            if ended(day):
                return
            if wanted(day):
                yield day
            k += 1
        return
    yield from ()


def is_occurrence(event: Any, day: date, *, ignore_skips: bool = False) -> bool:
    """Whether a series really has an occurrence starting on *day*. A skipped date
    doesn't, unless *ignore_skips*."""
    if not event.repeat:
        return False
    return (
        day
        in occurrence_starts(
            event.start_date,
            event.repeat,
            day,
            day + timedelta(days=1),
            until=event.repeat_until,
            skip=frozenset() if ignore_skips else event.skipped,
        )
        and day >= event.start_date
    )


def skip_problem(event: Any, day: date, restore: bool) -> str:
    """Why this date can't be skipped or put back, or "" when it can."""
    if not event.repeat:
        return "This event doesn't repeat, so it has no dates to skip. Delete it or mark it cancelled."
    if restore:
        return "" if day in event.skipped else f"{day.isoformat()} isn't skipped, so there's nothing to put back."
    if day in event.skipped:
        return f"{day.isoformat()} is already skipped."
    return "" if is_occurrence(event, day) else f"{day.isoformat()} isn't a date of this series."


def describe(event: Any) -> str:
    """The rule in words: "Every month on the 2nd Tuesday, until Mar 3, 2027"."""
    start: date = event.start_date
    words = {
        DAILY: "Every day",
        WEEKDAYS: "Every weekday",
        WEEKLY: f"Every week on {start:%A}",
        BIWEEKLY: f"Every 2 weeks on {start:%A}",
        MONTHLY: f"Every month on day {start.day}",
        MONTHLY_WEEKDAY: f"Every month on the {_ORDINALS[(start.day - 1) // 7 + 1]} {start:%A}",
        YEARLY: f"Every year on {start:%B} {start.day}",
    }.get(event.repeat, "")
    if words and event.repeat_until:
        until: date = event.repeat_until
        return f"{words}, until {until:%b} {until.day}, {until.year}"
    return words
