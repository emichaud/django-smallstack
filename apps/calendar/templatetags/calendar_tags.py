"""Template tags that render the calendar components from a list of events.

Give any page a month grid, a day-range board or a day column in one line —
the same partials the shared calendar page uses, driven only by
:class:`~apps.calendar.core.CalendarEvent` rows (from ``collect_events``,
``events_from_objects`` or your own code)::

    {% load calendar_tags %}
    <link rel="stylesheet" href="{% static 'calendar/css/calendar.css' %}">

    {% calendar_month events cursor %}                 month grid for the month of `cursor`
    {% calendar_board events lower upper %}            week columns for [lower, upper)
    {% calendar_day events day %}                      one day's events, grouped by calendar

Or skip the event building entirely — name the calendars and let the embed
endpoint do the rest, navigation included::

    {% calendar_card "smallstack_events" %}                       this month, lazily
    {% calendar_card "a,b" mode="upcoming" days=7 title="Soon" %}  the next week as a list
    {% calendar_card view mode="board" lazy=False %}             a saved view, rendered now

Day selection is a link: cells and headings point at the current URL with
``?day=YYYY-MM-DD`` (``day_param`` to rename), so the host page reads the
chosen day from its own query string and passes it back as ``selected_day``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from django import template
from django.utils import timezone

from ..core import (
    CalendarEvent,
    build_month_grid,
    build_range_board,
    day_url,
    events_on,
    group_by_calendar,
    parse_day,
    weekends_default,
)

register = template.Library()


def _request(context: Any) -> Any:
    return context.get("request")


@register.inclusion_tag("calendar/components/month_grid.html", takes_context=True)
def calendar_month(
    context: Any,
    events: list[CalendarEvent],
    cursor: date,
    selected_day: Optional[date] = None,
    weekends: Optional[bool] = None,
    max_per_day: int = 4,
    day_param: str = "day",
) -> dict[str, Any]:
    """Render the month containing ``cursor`` with ``events`` on its cells.
    ``weekends`` defaults to the site setting."""
    today = timezone.localdate()
    if weekends is None:
        weekends = weekends_default()
    weeks = build_month_grid(cursor, events, today, selected_day, max_per_day=max_per_day)
    if not weekends:
        weeks = [([c for c in week if c is None or not c["is_weekend"]] + [None] * 5)[:5] for week in weeks]
        weeks = [w for w in weeks if any(w)]
    request = _request(context)
    for week in weeks:
        for cell in week:
            if cell:
                cell["url"] = day_url(request, cell["date"], day_param)
    headers = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {"weeks": weeks, "weekday_headers": headers if weekends else headers[:5], "weekends": weekends}


@register.inclusion_tag("calendar/components/range_board.html", takes_context=True)
def calendar_board(
    context: Any,
    events: list[CalendarEvent],
    lower: date,
    upper: date,
    selected_day: Optional[date] = None,
    weekends: Optional[bool] = None,
    day_param: str = "day",
) -> dict[str, Any]:
    """Render ``[lower, upper)`` as week columns with an entry card per event.
    ``weekends`` defaults to the site setting."""
    today = timezone.localdate()
    if weekends is None:
        weekends = weekends_default()
    board = build_range_board(lower, upper, events, today, weekends=weekends, selected_day=selected_day)
    request = _request(context)
    for col in board:
        for d in col["days"]:
            d["url"] = day_url(request, d["date"], day_param)
    return {"board": board}


@register.inclusion_tag("calendar/components/day_column.html", takes_context=True)
def calendar_day(
    context: Any,
    events: list[CalendarEvent],
    day: Optional[date],
    explicit: bool = True,
    hint: str = "",
    empty_text: str = "",
    day_param: str = "day",
) -> dict[str, Any]:
    """Render the events of ``day`` (from ``events``) grouped by calendar.
    ``explicit=False`` marks a defaulted day (no close link, optional hint)."""
    day_events = events_on(events, day) if day else []
    return {
        "panel_day": day,
        "selected_day_label": day.strftime("%A, %B %-d") if day else "",
        "day_groups": group_by_calendar(day_events),
        "day_events": day_events,
        "close_url": day_url(_request(context), None, day_param),
        "explicit": explicit,
        "hint": hint,
        "empty_text": empty_text,
    }


@register.inclusion_tag("calendar/includes/embed.html", takes_context=True)
def calendar_card(
    context: Any,
    calendars: Any,
    mode: str = "month",
    title: Any = None,
    subtitle: str = "",
    lazy: bool = True,
    days: Optional[int] = None,
    limit: Optional[int] = None,
    weekends: Optional[bool] = None,
    month: Any = None,
) -> dict[str, Any]:
    """A calendar on any page, by key — the ``{% metric_card %}`` of calendars.

    ``calendars`` is a key, a comma-separated list of keys, a list, or a
    ``SavedCalendarView``. ``mode`` is ``month`` (default), ``board`` or
    ``upcoming``. ``title`` defaults to the calendar's label (``False`` for a
    screen-reader-only heading). ``lazy=False`` renders the fragment now
    instead of loading it over htmx. ``days``/``limit`` size the upcoming list
    (and ``days`` the board), ``weekends`` and ``month`` (a date or ``YYYY-MM``)
    seed the month grid. Needs ``request`` in the context; renders nothing
    for a viewer who may see none of the calendars.
    """
    from ..embed import calendar_embed

    request = _request(context)
    if request is None:
        return {"embed": None}
    if isinstance(month, date):
        month = month.strftime("%Y-%m")
    embed = calendar_embed(
        request, calendars, mode=mode, lazy=lazy, days=days, limit=limit, weekends=weekends, month=month or None
    )
    if embed is None:
        return {"embed": None}
    heading = embed["label"] if title is None else title
    return {
        "embed": embed,
        "title": heading if heading is not False else "",
        "subtitle": subtitle,
        "heading_id": "cal-embed-" + "-".join(embed["keys"]).replace("_", "-") + "-" + embed["mode"],
        "request": request,
    }


@register.inclusion_tag("calendar/crud/_leaf.html")
def event_leaf(obj: Any, size: str = "") -> dict[str, Any]:
    """The tear-off leaf for an Event — month over the day number, the end of
    a span underneath. ``size="lg"`` for the detail and delete pages."""
    from ..displays import event_leaf as _leaf

    return {"leaf": _leaf(obj), "cancelled": obj.cancelled, "size": size}


@register.filter(name="clock")
def clock_filter(value: Any) -> str:
    """``14:00`` → ``2:00 pm`` (the agenda's spelling, not Django's "p.m.")."""
    from ..displays import clock

    return clock(value) if value else ""


@register.simple_tag
def event_occurrence(event: Any, raw: Any) -> Optional[date]:
    """The date in a repeating event's ``?on=`` when it really is one of its
    dates, else None, so a page never talks about a date that isn't in the series."""
    from ..recurrence import is_occurrence

    day = parse_day(str(raw or ""))
    return day if day is not None and is_occurrence(event, day) else None
