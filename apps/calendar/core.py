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
    # Presentation: the calendar's human label and its 1-based ``--series-N``
    # colour index. Set by ``collect_events`` / ``assign_series``; defaults keep
    # a hand-built event renderable.
    calendar_label: str = ""
    series: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "calendar": self.calendar,
            "calendar_label": self.calendar_label,
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
        """Rows touching the half-open day range ``[lower, upper)`` — see
        :func:`window_filter` for the rule."""
        self.validate()
        return window_filter(self.dataset.queryset(request, filters), self.spec.start, self.spec.end, lower, upper)

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
        qs = self.window_queryset(lower, upper, request, filters).order_by(self.spec.start, "pk")
        if limit is not None:
            qs = qs[: max(1, int(limit))]
        return events_from_objects(
            qs,
            start=self.spec.start,
            end=self.spec.end,
            title=self.spec.title,
            subtitle=self.spec.subtitle,
            status=self.spec.status,
            url_for=self.dataset.link_for,
            calendar=self.key,
            calendar_label=self.label,
        )


def window_filter(qs: QuerySet, start: str, end: Optional[str], lower: date, upper: date) -> QuerySet:
    """Narrow ``qs`` to rows touching the half-open day range ``[lower, upper)``.

    Ranged rows (an ``end`` column) match on overlap (``start < upper and
    end >= lower``); point rows on ``lower <= start < upper``. Bounds are
    coerced to the type each column expects (aware midnight for datetimes,
    the plain date for dates) — the same rule ``CalendarDisplay`` applies.
    Shared by :class:`CalendarDataset` and :class:`~apps.calendar.displays.RangeBoardDisplay`.
    """
    from apps.smallstack.displays import _day_boundary, _is_datetime_field

    model = qs.model
    upper_bound = _day_boundary(upper, _is_datetime_field(model, start))
    if end:
        return qs.filter(
            **{f"{start}__lt": upper_bound},
            **{f"{end}__gte": _day_boundary(lower, _is_datetime_field(model, end))},
        )
    return qs.filter(
        **{f"{start}__gte": _day_boundary(lower, _is_datetime_field(model, start))},
        **{f"{start}__lt": upper_bound},
    )


def events_from_objects(
    objs: Any,
    *,
    start: str,
    end: Optional[str] = None,
    title: Any = None,
    subtitle: Any = None,
    status: Any = None,
    url_for: Any = None,
    calendar: str = "",
    calendar_label: str = "",
) -> list[CalendarEvent]:
    """Normalise model instances into :class:`CalendarEvent` rows.

    ``start``/``end`` are attribute names (or dotted paths); ``title``,
    ``subtitle`` and ``status`` are resolvers (attribute, dotted path, or
    callable); ``url_for(obj)`` supplies the link. This is the one place a
    row becomes an event — the dataset path and the CRUDView display both go
    through it, so a chip means the same thing everywhere.
    """
    from apps.smallstack.displays import _resolve_field, _to_local_date

    out: list[CalendarEvent] = []
    for obj in objs:
        raw_start = _resolve_field(obj, start)
        start_date = _to_local_date(raw_start)
        if start_date is None:
            continue
        raw_end = _resolve_field(obj, end) if end else None
        end_date = _to_local_date(raw_end) if raw_end is not None else start_date
        if end_date < start_date:
            end_date = start_date
        title_v = _resolve_field(obj, title) if title else None
        subtitle_v = _resolve_field(obj, subtitle) if subtitle else None
        status_v = _resolve_field(obj, status) if status else None
        url = None
        if url_for is not None:
            try:
                url = url_for(obj) or None
            except Exception:  # noqa: BLE001 — a bad link must not break the row
                url = None
        out.append(
            CalendarEvent(
                calendar=calendar,
                id=obj.pk,
                title=str(title_v) if title_v not in (None, "") else str(obj),
                subtitle=str(subtitle_v) if subtitle_v not in (None, "") else "",
                start=_localised(raw_start),
                end=_localised(raw_end) if raw_end is not None else None,
                all_day=not isinstance(raw_start, datetime),
                status=status_v if status_v in STATUS_VALUES else None,
                url=url,
                start_date=start_date,
                end_date=end_date,
                calendar_label=calendar_label,
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


def colourise(events: list[CalendarEvent], series: dict[str, int]) -> None:
    """Stamp each event's ``series`` from a key → index map (in place)."""
    for ev in events:
        ev.series = series.get(ev.calendar, 1)


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


#: Day-range board sizes offered beside the month grid.
RANGE_DAYS = (30, 60, 90)


def parse_range(raw: str) -> Optional[int]:
    """``?range=30|60|90`` → the number of days, or None for the month grid."""
    try:
        value = int(raw or "")
    except (TypeError, ValueError):
        return None
    return value if value in RANGE_DAYS else None


def build_range_board(
    lower: date,
    upper: date,
    events: list[CalendarEvent],
    today: date,
    *,
    weekends: bool = True,
    selected_day: Optional[date] = None,
) -> list[dict[str, Any]]:
    """The day-range board: one column per Monday-start week touching
    ``[lower, upper)``, each listing the days (inside the window) that have
    events, with the events placed on every day they touch.

    Days without events are omitted — a sparse calendar reads as a short list,
    not a wall of empty headings — but a week with nothing at all still gets
    its column so the timeline keeps its shape. ``weekends=False`` drops
    Saturday and Sunday entries (the events stay in the totals).
    """
    by_day: dict[date, list[CalendarEvent]] = {}
    last = upper - timedelta(days=1)
    for ev in events:
        day = max(ev.start_date, lower)
        stop = min(ev.end_date, last)
        while day <= stop:
            if weekends or day.weekday() < 5:
                by_day.setdefault(day, []).append(ev)
            day += timedelta(days=1)

    columns: list[dict[str, Any]] = []
    week_start = lower - timedelta(days=lower.weekday())
    while week_start < upper:
        week_end = week_start + timedelta(days=6)
        first = max(week_start, lower)
        final = min(week_end, last)
        days: list[dict[str, Any]] = []
        count = 0
        d = first
        while d <= final:
            todays = by_day.get(d, [])
            if todays:
                days.append(
                    {
                        "date": d,
                        "date_iso": d.isoformat(),
                        "is_today": d == today,
                        "is_selected": d == selected_day,
                        "events": todays,
                    }
                )
                count += len(todays)
            d += timedelta(days=1)
        same_month = week_start.month == week_end.month
        label = (
            f"{week_start:%b} {week_start.day}–{week_end.day}"
            if same_month
            else f"{week_start:%b} {week_start.day}–{week_end:%b} {week_end.day}"
        )
        columns.append(
            {
                "start": week_start,
                "end": week_end,
                "label": label,
                "count": count,
                "days": days,
                "is_current": week_start <= today <= week_end,
            }
        )
        week_start += timedelta(days=7)
    return columns


def group_by_calendar(events: list[CalendarEvent]) -> list[dict[str, Any]]:
    """Group a day's events by calendar (series order, then label) for the
    day column. Reads each event's own ``calendar_label`` / ``series``."""
    groups: dict[str, dict[str, Any]] = {}
    for ev in events:
        group = groups.setdefault(
            ev.calendar,
            {"key": ev.calendar, "label": ev.calendar_label or ev.calendar, "series": ev.series, "events": []},
        )
        group["events"].append(ev)
    return sorted(groups.values(), key=lambda g: (g["series"], g["label"]))


def day_url(request: HttpRequest | None, day: Optional[date], day_param: str = "day") -> str:
    """The current URL with ``day_param`` set to ``day`` (or removed when
    ``None``) — the link a grid cell / board heading uses to select a day.
    Every other query parameter is preserved, so the page's state survives."""
    if request is None:
        return f"?{day_param}={day.isoformat()}" if day else "?"
    params = request.GET.copy()
    params.pop(day_param, None)
    if day is not None:
        params[day_param] = day.isoformat()
    encoded = params.urlencode()
    return request.path + ("?" + encoded if encoded else "")


def access_label(level: str) -> str:
    return "Staff" if level == ACCESS_STAFF else "Signed-in users"


# ---------------------------------------------------------------------------
# RangeWindow — the board's URL state, shared by every page that hosts one
# ---------------------------------------------------------------------------


@dataclass
class RangeWindow:
    """A day-range board's state, read from a request's query string.

    ``range`` (30/60/90), ``from`` (the anchor date), ``day`` (the selected
    day) and ``weekends`` are the parameters; names are configurable so a
    page with its own ``from`` can rename them. ``backward=True`` anchors the
    window to END today (the last N days — right for activity logs), the
    default anchors it to START today (the next N days — right for schedules).

    Build the events for ``[lower, upper)`` however you like, then
    :meth:`context` returns everything ``calendar/components/board.html``
    needs: the week columns, the day column, and the toolbar/navigation URLs
    (each a copy of the current query string with one parameter changed).
    """

    request: Any
    days: int
    anchor: date
    today: date
    weekends: bool
    selected_day: Optional[date]
    backward: bool = False
    range_param: str = "range"
    from_param: str = "from"
    day_param: str = "day"
    weekends_param: str = "weekends"

    @classmethod
    def from_request(
        cls,
        request: Any,
        *,
        days: int = 30,
        backward: bool = False,
        range_param: str = "range",
        from_param: str = "from",
        day_param: str = "day",
        weekends_param: str = "weekends",
    ) -> "RangeWindow":
        from django.utils import timezone

        today = timezone.localdate()
        get = getattr(request, "GET", {})
        chosen = parse_range(get.get(range_param, "")) or (days if days in RANGE_DAYS else RANGE_DAYS[0])
        anchor = parse_day(get.get(from_param, "")) or today
        weekends = get.get(weekends_param, "1") not in ("0", "false", "off")
        win = cls(
            request=request,
            days=chosen,
            anchor=anchor,
            today=today,
            weekends=weekends,
            selected_day=None,
            backward=backward,
            range_param=range_param,
            from_param=from_param,
            day_param=day_param,
            weekends_param=weekends_param,
        )
        selected = parse_day(get.get(day_param, ""))
        if selected is not None and win.lower <= selected < win.upper:
            win.selected_day = selected
        return win

    @property
    def lower(self) -> date:
        return self.anchor - timedelta(days=self.days - 1) if self.backward else self.anchor

    @property
    def upper(self) -> date:
        return self.anchor + timedelta(days=1) if self.backward else self.anchor + timedelta(days=self.days)

    @property
    def panel_day(self) -> Optional[date]:
        if self.selected_day is not None:
            return self.selected_day
        return self.today if self.lower <= self.today < self.upper else None

    def url(self, **changes: Any) -> str:
        """The current URL with the given query parameters changed; a value
        of ``None`` removes the parameter."""
        params = self.request.GET.copy()
        for key, value in changes.items():
            params.pop(key, None)
            if value is not None:
                params[key] = str(value)
        encoded = params.urlencode()
        return self.request.path + ("?" + encoded if encoded else "")

    def context(self, events: list[CalendarEvent]) -> dict[str, Any]:
        """Template context for ``calendar/components/board.html``."""
        board = build_range_board(
            self.lower, self.upper, events, self.today, weekends=self.weekends, selected_day=self.selected_day
        )
        for col in board:
            for d in col["days"]:
                d["url"] = day_url(self.request, d["date"], self.day_param)
        panel_day = self.panel_day
        day_events = events_on(events, panel_day) if panel_day else []
        last = self.upper - timedelta(days=1)
        if self.lower.year == last.year:
            period_label = f"{self.lower:%-d %b} – {last:%-d %b %Y}"
        else:
            period_label = f"{self.lower:%-d %b %Y} – {last:%-d %b %Y}"
        step = timedelta(days=self.days)
        return {
            "board": board,
            "board_weeks": len(board),
            "event_count": len(events),
            "range_days": self.days,
            "range_choices": [
                {
                    "days": n,
                    "label": f"{n} days",
                    "url": self.url(**{self.range_param: n, self.from_param: None, self.day_param: None}),
                    "active": n == self.days,
                }
                for n in RANGE_DAYS
            ],
            "weekends": self.weekends,
            "weekends_url": self.url(**{self.weekends_param: "0" if self.weekends else None}),
            "period_label": period_label,
            "is_now": self.anchor == self.today,
            "prev_url": self.url(**{self.from_param: (self.anchor - step).isoformat(), self.day_param: None}),
            "next_url": self.url(**{self.from_param: (self.anchor + step).isoformat(), self.day_param: None}),
            "today_url": self.url(**{self.from_param: None, self.day_param: None}),
            "panel_day": panel_day,
            "selected_day": self.selected_day,
            "selected_day_label": panel_day.strftime("%A, %B %-d") if panel_day else "",
            "day_groups": group_by_calendar(day_events),
            "day_events": day_events,
            "close_url": self.url(**{self.day_param: None}),
        }

