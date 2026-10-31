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

from datetime import date, time
from typing import Any

from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from apps.smallstack.displays import CardDisplay, FieldRef, ListDisplay, paginate_queryset

from .core import RANGE_DAYS, RangeWindow, assign_series, events_from_objects, visible_calendars, window_filter
from .models import Event


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


# ---------------------------------------------------------------------------
# The entries and saved-views pages — list displays that replace the generic
# table. The one signature element is the tear-off calendar *leaf* (month over
# a large day number); the date is an entry's identity, the rest is annotation.
# ---------------------------------------------------------------------------


def clock(value: time) -> str:
    """``14:00`` → ``2:00 pm`` — how a person says a time out loud."""
    return value.strftime("%-I:%M %p").replace("AM", "am").replace("PM", "pm")


def event_leaf(obj: Event) -> dict[str, Any]:
    """What the leaf shows for an entry: the start day, and the end of a span."""
    last: date = obj.last_day
    return {
        "month": obj.start_date.strftime("%b"),
        "day": obj.start_date.day,
        "end": None if last == obj.start_date else last,
        "same_month": (last.year, last.month) == (obj.start_date.year, obj.start_date.month),
    }


def event_when(obj: Event) -> str:
    """The time part of an entry as one short phrase."""
    if obj.all_day or not obj.start_time:
        return "All day"
    start = clock(obj.start_time)
    if obj.end_time:
        return f"{start} to {clock(obj.end_time)}"
    return f"From {start}"


def _author(obj: Event) -> str:
    user = obj.created_by
    if user is None:
        return ""
    return user.get_full_name() or user.get_username()


class AgendaDisplay(ListDisplay):
    """The Events list as an agenda: rows grouped by month, a leaf per entry.

    Replaces :class:`~apps.smallstack.displays.TableDisplay` on the Events
    CRUDView; the toolbar (search, filters, sort), pagination and the delete
    modal are the list page's own and keep working. Grouping by month is
    dropped when the viewer sorts by anything other than the date, so a
    title-sorted list is not chopped into month fragments.
    """

    name = "agenda"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">'
        '<path d="M4 5h4v4H4zm6 1h10v2H10zM4 11h4v4H4zm6 1h10v2H10zM4 17h4v4H4zm6 1h10v2H10z"/></svg>'
    )
    template_name = "calendar/displays/agenda.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        page = paginate_queryset(queryset.select_related("created_by"), crud_config._resolve_paginate_by(), request)
        items = page.pop("object_list", queryset)
        base = crud_config._get_url_base()
        has_detail = Action.DETAIL in crud_config.actions
        today = timezone.localdate()
        ordering = request.GET.get("ordering", "").strip().lstrip("-")
        grouped = ordering in ("", "start_date")

        rows: list[dict[str, Any]] = []
        for obj in items:
            rows.append(
                {
                    "obj": obj,
                    "pk": obj.pk,
                    "title": obj.title,
                    "detail_url": reverse(f"{base}-detail", kwargs={"pk": obj.pk}) if has_detail else "",
                    "edit_url": (
                        reverse(f"{base}-update", kwargs={"pk": obj.pk})
                        if Action.UPDATE in crud_config.actions and crud_config.can_update(obj, request)
                        else ""
                    ),
                    "delete_url": (
                        reverse(f"{base}-delete", kwargs={"pk": obj.pk})
                        if Action.DELETE in crud_config.actions and crud_config.can_delete(obj, request)
                        else ""
                    ),
                    "leaf": event_leaf(obj),
                    "when": event_when(obj),
                    "category": obj.category,
                    "location": obj.location,
                    "private": obj.visibility == Event.Visibility.PRIVATE,
                    "cancelled": obj.cancelled,
                    "author": _author(obj),
                    "is_past": obj.last_day < today,
                    "group": obj.start_date.strftime("%B %Y"),
                }
            )

        groups: list[dict[str, Any]] = []
        if grouped:
            for row in rows:
                if not groups or groups[-1]["label"] != row["group"]:
                    groups.append({"label": row["group"], "rows": []})
                groups[-1]["rows"].append(row)
        else:
            groups = [{"label": "", "rows": rows}]
        return {"groups": groups, "rows": rows, "object_list": items, **page}


class SavedViewsDisplay(ListDisplay):
    """A person's saved views as rows: the name opens the calendar with that
    mix, the calendars show as chips in the same series colours the calendar
    page gives them, the default is marked."""

    name = "views"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">'
        '<path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h10v2H4z"/></svg>'
    )
    template_name = "calendar/displays/saved_views.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        page = paginate_queryset(queryset, crud_config._resolve_paginate_by(), request)
        items = page.pop("object_list", queryset)
        base = crud_config._get_url_base()
        cals = visible_calendars(getattr(request, "user", None))
        series = assign_series(cals)
        labels = {c.key: c.label for c in cals}
        rows: list[dict[str, Any]] = []
        for obj in items:
            rows.append(
                {
                    "obj": obj,
                    "pk": obj.pk,
                    "name": obj.name,
                    "open_url": obj.get_absolute_url(),
                    "edit_url": (
                        reverse(f"{base}-update", kwargs={"pk": obj.pk}) if Action.UPDATE in crud_config.actions else ""
                    ),
                    "delete_url": (
                        reverse(f"{base}-delete", kwargs={"pk": obj.pk}) if Action.DELETE in crud_config.actions else ""
                    ),
                    "calendars": [
                        {"key": k, "label": labels.get(k, k), "series": series.get(k, 0), "known": k in labels}
                        for k in obj.keys
                    ],
                    "is_default": obj.is_default,
                    "updated_at": obj.updated_at,
                }
            )
        return {"rows": rows, "object_list": items, **page}
