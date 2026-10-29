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
``backward=True`` makes the window end today (the last N days) for history-shaped models.
The rows become :class:`~apps.calendar.core.CalendarEvent` through the same
builder the shared calendar page uses, so a chip means the same thing on both.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from apps.smallstack.displays import CardDisplay, FieldRef, ListDisplay

from .core import RANGE_DAYS, RangeWindow, events_from_objects, window_filter


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
        backward: bool = False,
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
        # True → the window ENDS today (the last N days: activity, history);
        # False → it STARTS today (the next N days: schedules, deadlines).
        self.backward = backward
        self.range_param = range_param
        self.from_param = from_param
        self.day_param = day_param

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        win = RangeWindow.from_request(
            request,
            days=self.days,
            backward=self.backward,
            range_param=self.range_param,
            from_param=self.from_param,
            day_param=self.day_param,
        )
        has_detail = Action.DETAIL in crud_config.actions
        label = str(crud_config.model._meta.verbose_name_plural).capitalize()
        rows = window_filter(queryset, self.date_field, self.end_field, win.lower, win.upper)
        events = events_from_objects(
            rows.order_by(self.date_field, "pk"),
            start=self.date_field,
            end=self.end_field,
            title=self.title_field,
            subtitle=self.subtitle_field,
            status=self.status_field,
            url_for=(lambda obj: CardDisplay._resolve_detail_url(obj, crud_config)) if has_detail else None,
            calendar=crud_config._get_url_base(),
            calendar_label=label,
        )
        return {**win.context(events), "count_label": label.lower()}
