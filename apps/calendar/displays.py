"""``RangeBoardDisplay`` — the 30/60/90-day board as a CRUDView list display.

A sibling of :class:`~apps.smallstack.displays.CalendarDisplay`: list it in a
CRUDView's ``displays`` (or an admin's ``explorer_displays``) and the list
page grows a Table ⇄ Calendar ⇄ Board toggle::

    from apps.calendar.displays import RangeBoardDisplay

    displays = [
        TableDisplay,
        CalendarDisplay(date_field="scheduled_for", title_field="job_name", status_field="calendar_status"),
        RangeBoardDisplay(date_field="scheduled_for", title_field="job_name", status_field="calendar_status"),
    ]

URL state (all optional): ``?display=board&range=30|60|90&from=YYYY-MM-DD&day=YYYY-MM-DD&weekends=0``.
The rows become :class:`~apps.calendar.core.CalendarEvent` through the same
builder the shared calendar page uses, so a chip means the same thing on both.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from apps.smallstack.displays import CardDisplay, FieldRef, ListDisplay

from .core import (
    RANGE_DAYS,
    build_range_board,
    day_url,
    events_from_objects,
    events_on,
    group_by_calendar,
    parse_day,
    parse_range,
    window_filter,
)


class RangeBoardDisplay(ListDisplay):
    """Week-column board over a date (or date-range) field, N days from an anchor."""

    name = "board"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">'
        '<path d="M3 4h5v16H3zm6.5 0h5v10h-5zM16 4h5v13h-5z"/></svg>'
    )
    template_name = "calendar/displays/range_board.html"
    supports_bulk = False

    def __init__(
        self,
        date_field: str,
        end_field: str | None = None,
        title_field: FieldRef = None,
        subtitle_field: FieldRef = None,
        status_field: FieldRef = None,
        days: int = 30,
        range_param: str = "range",
        from_param: str = "from",
        day_param: str = "day",
    ) -> None:
        self.date_field = date_field
        self.end_field = end_field
        self.title_field = title_field
        self.subtitle_field = subtitle_field
        self.status_field = status_field
        self.days = days if days in RANGE_DAYS else RANGE_DAYS[0]
        self.range_param = range_param
        self.from_param = from_param
        self.day_param = day_param

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        today = timezone.localdate()
        days = parse_range(request.GET.get(self.range_param, "")) or self.days
        anchor = parse_day(request.GET.get(self.from_param, "")) or today
        weekends = request.GET.get("weekends", "1") not in ("0", "false", "off")
        lower, upper = anchor, anchor + timedelta(days=days)
        selected_day = parse_day(request.GET.get(self.day_param, ""))
        if selected_day is not None and not (lower <= selected_day < upper):
            selected_day = None

        has_detail = Action.DETAIL in crud_config.actions
        label = str(crud_config.model._meta.verbose_name_plural).capitalize()
        events = events_from_objects(
            window_filter(queryset, self.date_field, self.end_field, lower, upper).order_by(self.date_field, "pk"),
            start=self.date_field,
            end=self.end_field,
            title=self.title_field,
            subtitle=self.subtitle_field,
            status=self.status_field,
            url_for=(lambda obj: CardDisplay._resolve_detail_url(obj, crud_config)) if has_detail else None,
            calendar=crud_config._get_url_base(),
            calendar_label=label,
        )
        board = build_range_board(lower, upper, events, today, weekends=weekends, selected_day=selected_day)
        for col in board:
            for d in col["days"]:
                d["url"] = day_url(request, d["date"], self.day_param)

        panel_day = selected_day if selected_day is not None else (today if lower <= today < upper else None)
        day_events = events_on(events, panel_day) if panel_day else []

        def url(**changes: Any) -> str:
            params = request.GET.copy()
            params["display"] = self.name
            for key, value in changes.items():
                params.pop(key, None)
                if value is not None:
                    params[key] = str(value)
            return request.path + "?" + params.urlencode()

        last = upper - timedelta(days=1)
        return {
            "board": board,
            "board_weeks": len(board),
            "event_count": len(events),
            "range_days": days,
            "range_choices": [
                {
                    "days": n,
                    "label": f"{n} days",
                    "url": url(**{self.range_param: n, self.from_param: None, self.day_param: None}),
                    "active": n == days,
                }
                for n in RANGE_DAYS
            ],
            "weekends": weekends,
            "weekends_url": url(weekends="0") if weekends else url(weekends=None),
            "period_label": (
                f"{lower:%-d %b} – {last:%-d %b %Y}"
                if lower.year == last.year
                else f"{lower:%-d %b %Y} – {last:%-d %b %Y}"
            ),
            "is_now": anchor == today,
            "prev_url": url(**{self.from_param: (anchor - timedelta(days=days)).isoformat(), self.day_param: None}),
            "next_url": url(**{self.from_param: (anchor + timedelta(days=days)).isoformat(), self.day_param: None}),
            "today_url": url(**{self.from_param: None, self.day_param: None}),
            "panel_day": panel_day,
            "selected_day": selected_day,
            "selected_day_label": panel_day.strftime("%A, %B %-d") if panel_day else "",
            "day_groups": group_by_calendar(day_events),
            "day_events": day_events,
            "close_url": url(**{self.day_param: None}),
        }
