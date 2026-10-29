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
    weekends: bool = True,
    max_per_day: int = 4,
    day_param: str = "day",
) -> dict[str, Any]:
    """Render the month containing ``cursor`` with ``events`` on its cells."""
    today = timezone.localdate()
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
    weekends: bool = True,
    day_param: str = "day",
) -> dict[str, Any]:
    """Render ``[lower, upper)`` as week columns with an entry card per event."""
    today = timezone.localdate()
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
