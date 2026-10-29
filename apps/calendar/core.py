"""The calendar runtime: validate a spec, pull a window of events, build a grid.

Everything here composes on the dataset contract — rows come through
``Dataset.queryset()`` (so a dataset's per-user scoping and filter pipeline
apply) and links through ``Dataset.link_for``. The date helpers are the ones
``CalendarDisplay`` already uses, so a chip lands on the same local day here as
it does on a CRUDView's calendar display.

The normalised event is the contract every surface shares — the page, the REST
``/events/`` route, the ICS feed and the MCP tool all emit the same dict:

    {"calendar": key, "id": pk, "title": …, "subtitle": …,
     "start": ISO, "end": ISO | None, "all_day": bool,
     "status": "success" | "warning" | "danger" | None, "url": str | None}
"""

from __future__ import annotations

import calendar as pycal
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterator, Optional

from django.db.models import QuerySet
from django.http import HttpRequest

from apps.datasets.core import Dataset, get_dataset
from apps.datasets.registry import get_def

from .registry import (
    ACCESS_AUTHENTICATED,
    ACCESS_STAFF,
    STATUS_VALUES,
    CalendarSpec,
    all_specs,
    get_spec,
)

#: Rows pulled per calendar per window. A month of a busy log-like dataset is
#: capped rather than materialised; the page shows the cap was hit.
WINDOW_LIMIT = 2000

#: Number of categorical colour tokens the theme defines (``--series-1`` …).
SERIES_COUNT = 8

_DATE_TYPES = ("date", "datetime")


class CalendarProtocolError(ValueError):
    """The spec names columns the dataset does not provide as dates."""


@dataclass
class CalendarEvent:
    calendar: str
    id: Any
    title: str
    subtitle: str
    start: date | datetime
    end: date | datetime | None
    all_day: bool
    status: Optional[str]
    url: Optional[str]
    start_date: date
    end_date: date

    def as_dict(self) -> dict[str, Any]:
        return {
            "calendar": self.calendar,
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end is not None else None,
            "all_day": self.all_day,
            "status": self.status,
            "url": self.url,
        }


class CalendarDataset:
    """A dataset viewed through its calendar spec."""

    def __init__(self, spec: CalendarSpec, dataset: Dataset) -> None:
        self.spec = spec
        self.dataset = dataset
        self.key = spec.key
        self._validated = False

    # -- metadata -----------------------------------------------------------

    @property
    def label(self) -> str:
        return self.spec.label or self.dataset.dfn.label

    @property
    def description(self) -> str:
        return self.spec.description or self.dataset.dfn.description

    @property
    def ranged(self) -> bool:
        return self.spec.ranged

    def describe(self) -> dict[str, Any]:
        """Picker/API metadata — DB-free."""
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "start": self.spec.start,
            "end": self.spec.end,
            "ranged": self.ranged,
            "access": self.spec.access,
        }

    # -- protocol validation ------------------------------------------------

    def validate(self) -> None:
        """Raise :class:`CalendarProtocolError` unless ``start``/``end`` are
        date or datetime columns of the dataset. DB-free; cached per instance."""
        if self._validated:
            return
        cols = dict(self.dataset.columns())
        for role, name in (("start", self.spec.start), ("end", self.spec.end)):
            if name is None:
                continue
            typ = cols.get(name)
            if typ is None:
                raise CalendarProtocolError(
                    f"calendar {self.key!r}: {role} column {name!r} is not a column of the dataset "
                    f"(columns: {sorted(cols)})"
                )
            if typ not in _DATE_TYPES:
                raise CalendarProtocolError(
                    f"calendar {self.key!r}: {role} column {name!r} is {typ}, not a date/datetime column"
                )
        self._validated = True

    def _col_is_datetime(self, name: str) -> bool:
        return dict(self.dataset.columns()).get(name) == "datetime"

    # -- the window query -----------------------------------------------------

    def window_queryset(
        self,
        lower: date,
        upper: date,
        request: HttpRequest | None = None,
        filters: Optional[dict] = None,
    ) -> QuerySet:
        """Rows touching the half-open day range ``[lower, upper)``.

        Ranged calendars match on overlap (``start < upper and end >= lower``);
        point calendars on ``lower <= start < upper``. Bounds are coerced to
        the type each column expects (aware midnight for datetimes, the plain
        date for dates) — the same rule ``CalendarDisplay`` applies.
        """
        from apps.smallstack.displays import _day_boundary

        self.validate()
        qs = self.dataset.queryset(request, filters)
        start_dt = self._col_is_datetime(self.spec.start)
        upper_bound = _day_boundary(upper, start_dt)
        if self.spec.end:
            end_dt = self._col_is_datetime(self.spec.end)
            return qs.filter(
                **{f"{self.spec.start}__lt": upper_bound},
                **{f"{self.spec.end}__gte": _day_boundary(lower, end_dt)},
            )
        return qs.filter(
            **{f"{self.spec.start}__gte": _day_boundary(lower, start_dt)},
            **{f"{self.spec.start}__lt": upper_bound},
        )

    def count(self, lower: date, upper: date, request: HttpRequest | None = None) -> int:
        return self.window_queryset(lower, upper, request).count()

    def events(
        self,
        lower: date,
        upper: date,
        request: HttpRequest | None = None,
        *,
        limit: Optional[int] = WINDOW_LIMIT,
        filters: Optional[dict] = None,
    ) -> list[CalendarEvent]:
        """Normalised events in ``[lower, upper)``, ordered by start."""
        from apps.smallstack.displays import _resolve_field, _to_local_date

        qs = self.window_queryset(lower, upper, request, filters).order_by(self.spec.start, "pk")
        if limit is not None:
            qs = qs[: max(1, int(limit))]
        out: list[CalendarEvent] = []
        for obj in qs:
            raw_start = _resolve_field(obj, self.spec.start)
            start_date = _to_local_date(raw_start)
            if start_date is None:
                continue
            raw_end = _resolve_field(obj, self.spec.end) if self.spec.end else None
            end_date = _to_local_date(raw_end) if raw_end is not None else start_date
            if end_date < start_date:
                end_date = start_date
            title = _resolve_field(obj, self.spec.title) if self.spec.title else None
            subtitle = _resolve_field(obj, self.spec.subtitle) if self.spec.subtitle else None
            status = _resolve_field(obj, self.spec.status) if self.spec.status else None
            out.append(
                CalendarEvent(
                    calendar=self.key,
                    id=obj.pk,
                    title=str(title) if title not in (None, "") else str(obj),
                    subtitle=str(subtitle) if subtitle not in (None, "") else "",
                    start=_localised(raw_start),
                    end=_localised(raw_end) if raw_end is not None else None,
                    all_day=not isinstance(raw_start, datetime),
                    status=status if status in STATUS_VALUES else None,
                    url=self.dataset.link_for(obj),
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return out


def _localised(value: Any) -> Any:
    """An aware datetime in the active timezone; dates pass through."""
    if isinstance(value, datetime):
        from django.utils import timezone

        if timezone.is_aware(value):
            return timezone.localtime(value)
    return value


# ---------------------------------------------------------------------------
# Lookup + access
# ---------------------------------------------------------------------------


def get_calendar(key: str) -> Optional[CalendarDataset]:
    """The calendar dataset for ``key``, or None when either half is missing.

    A spec whose dataset never registered (the bundled set switched off, a
    typo'd key) is simply absent — it never raises here.
    """
    spec = get_spec(key)
    if spec is None or get_def(key) is None:
        return None
    ds = get_dataset(key)
    return CalendarDataset(spec, ds) if ds is not None else None


def iter_calendars() -> Iterator[CalendarDataset]:
    for spec in all_specs():
        cal = get_calendar(spec.key)
        if cal is not None:
            yield cal


def can_view(user: Any, cal: CalendarDataset) -> bool:
    """Access rule: staff see everything; signed-in users see
    ``access="authenticated"`` calendars; anonymous users see nothing."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    return cal.spec.access == ACCESS_AUTHENTICATED


def visible_calendars(user: Any) -> list[CalendarDataset]:
    """Calendars ``user`` may see — project ones first, then the bundled
    ``smallstack_*`` set, each A–Z. The position is stable per user, which is
    what keys the colour series (see :func:`assign_series`)."""
    from apps.datasets.framework import is_framework_dataset

    cals = [c for c in iter_calendars() if can_view(user, c)]
    cals.sort(key=lambda c: (is_framework_dataset(c.key), c.label.lower()))
    return cals


def assign_series(cals: list[CalendarDataset]) -> dict[str, int]:
    """Map each calendar key to a 1-based ``--series-N`` colour index."""
    return {c.key: (i % SERIES_COUNT) + 1 for i, c in enumerate(cals)}


def list_calendars(user: Any = None) -> list[dict[str, Any]]:
    """Picker/API list — metadata only, no DB."""
    cals = visible_calendars(user) if user is not None else list(iter_calendars())
    return [c.describe() for c in cals]


def resolve_keys(keys: list[str], user: Any) -> tuple[list[CalendarDataset], list[str]]:
    """Split requested keys into the calendars ``user`` may see and the
    rejected keys (unknown, or not visible to this user — the two are
    deliberately indistinguishable so a key's existence doesn't leak)."""
    visible = {c.key: c for c in visible_calendars(user)}
    ok: list[CalendarDataset] = []
    bad: list[str] = []
    for key in keys:
        cal = visible.get(key)
        if cal is None:
            bad.append(key)
        elif cal not in ok:
            ok.append(cal)
    return ok, bad


# ---------------------------------------------------------------------------
# Windows + the month grid
# ---------------------------------------------------------------------------


def month_bounds(cursor: date) -> tuple[date, date]:
    """``(first day, day after the last)`` — a half-open month window."""
    _, last = pycal.monthrange(cursor.year, cursor.month)
    first = cursor.replace(day=1)
    return first, first.replace(day=last) + timedelta(days=1)


def parse_month(raw: str, today: date) -> date:
    """``YYYY-MM`` → the first of that month; anything else → this month."""
    try:
        year, month = (int(x) for x in (raw or "").split("-"))
        return date(year, month, 1)
    except (ValueError, TypeError):
        return today.replace(day=1)


def parse_day(raw: str) -> Optional[date]:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def collect_events(
    cals: list[CalendarDataset],
    lower: date,
    upper: date,
    request: HttpRequest | None = None,
    *,
    limit: Optional[int] = WINDOW_LIMIT,
) -> tuple[list[CalendarEvent], dict[str, int], set[str]]:
    """Events from every calendar in the window, merged and sorted by start.

    Returns ``(events, counts_by_calendar, capped_keys)`` — ``capped_keys``
    names the calendars whose window exceeded ``limit`` (the page says so
    rather than silently showing a partial month).
    """
    events: list[CalendarEvent] = []
    counts: dict[str, int] = {}
    capped: set[str] = set()
    for cal in cals:
        batch = cal.events(lower, upper, request, limit=limit)
        if limit is not None and len(batch) >= limit:
            capped.add(cal.key)
        counts[cal.key] = len(batch)
        events.extend(batch)
    events.sort(key=_sort_key)
    return events, counts, capped


def _sort_key(ev: CalendarEvent) -> tuple:
    # All-day events first within a day, then by clock time, then title.
    clock = ev.start.strftime("%H:%M:%S") if isinstance(ev.start, datetime) else ""
    return (ev.start_date, 0 if ev.all_day else 1, clock, ev.title.lower())


def build_month_grid(
    cursor: date,
    events: list[CalendarEvent],
    today: date,
    selected_day: Optional[date] = None,
    max_per_day: int = 4,
) -> list[list[Optional[dict[str, Any]]]]:
    """Monday-start weeks of day cells, each holding up to ``max_per_day``
    events (the rest is an overflow count — the day panel shows them all)."""
    first, upper = month_bounds(cursor)
    last = upper - timedelta(days=1)
    by_day: dict[date, list[CalendarEvent]] = {}
    for ev in events:
        day = max(ev.start_date, first)
        stop = min(ev.end_date, last)
        while day <= stop:
            by_day.setdefault(day, []).append(ev)
            day += timedelta(days=1)

    weeks: list[list[Optional[dict[str, Any]]]] = []
    week: list[Optional[dict[str, Any]]] = [None] * first.weekday()
    for dom in range(1, last.day + 1):
        d = first.replace(day=dom)
        todays = by_day.get(d, [])
        week.append(
            {
                "day": dom,
                "date": d,
                "date_iso": d.isoformat(),
                "is_today": d == today,
                "is_selected": d == selected_day,
                "is_weekend": d.weekday() >= 5,
                "events": todays[:max_per_day],
                "overflow": max(0, len(todays) - max_per_day),
                "total": len(todays),
            }
        )
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        week.extend([None] * (7 - len(week)))
        weeks.append(week)
    return weeks


def events_on(events: list[CalendarEvent], day: date) -> list[CalendarEvent]:
    return [ev for ev in events if ev.start_date <= day <= ev.end_date]


def access_label(level: str) -> str:
    return "Staff" if level == ACCESS_STAFF else "Signed-in users"
