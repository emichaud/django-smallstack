"""The calendar page and the saved-view CRUD.

``/smallstack/calendar/`` is a user app in the runbook/blog sense: any
signed-in user may open it, and sees the calendars their access level allows
(see ``core.can_view``). Everything the page shows is derived from the query
string — ``ds`` (repeatable) picks calendars, ``month`` moves the grid, ``day``
opens one day, ``view`` loads a saved selection — so every state is a link:
bookmarkable, shareable with a colleague who has the same access, and
testable without JavaScript.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional, cast
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.generic import TemplateView

from apps.smallstack.crud import Action, CRUDView, _CRUDCreateBase

from .core import (
    CalendarDataset,
    assign_series,
    build_month_grid,
    collect_events,
    events_on,
    month_bounds,
    parse_day,
    parse_month,
    resolve_keys,
    visible_calendars,
)
from .forms import SavedCalendarViewForm
from .models import SavedCalendarView

#: Chips per day cell on the month grid; the day panel shows the rest.
MAX_PER_DAY = 4


def requested_keys(request: HttpRequest) -> list[str]:
    """Calendar keys from ``?ds=`` — repeatable and/or comma-separated.
    Order is preserved, duplicates dropped."""
    keys: list[str] = []
    for raw in request.GET.getlist("ds"):
        for part in raw.split(","):
            part = part.strip()
            if part and part not in keys:
                keys.append(part)
    return keys


def _owned_view(request: HttpRequest, raw: Optional[str]) -> Optional[SavedCalendarView]:
    try:
        pk = int(raw or "")
    except (TypeError, ValueError):
        return None
    return SavedCalendarView.objects.filter(owner=cast(Any, request.user), pk=pk).first()


class CalendarPageView(LoginRequiredMixin, TemplateView):
    template_name = "calendar/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        user = cast(Any, request.user)  # LoginRequiredMixin: never anonymous here
        today = timezone.localdate()

        cals = visible_calendars(user)
        series = assign_series(cals)
        cursor = parse_month(request.GET.get("month", ""), today)
        lower, upper = month_bounds(cursor)
        selected_day = parse_day(request.GET.get("day", ""))
        if selected_day is not None and not (lower <= selected_day < upper):
            selected_day = None

        views = list(SavedCalendarView.objects.filter(owner=user))
        current_view = _owned_view(request, request.GET.get("view"))
        explicit = "ds" in request.GET
        if explicit:
            keys = requested_keys(request)
        elif current_view is not None:
            keys = current_view.keys
        elif "view" not in request.GET:
            # No parameters at all → the user's default view, if any.
            current_view = next((v for v in views if v.is_default), None)
            keys = current_view.keys if current_view is not None else []
        else:
            keys = []
        selected, _rejected = resolve_keys(keys, user)
        selected_keys = [c.key for c in selected]
        modified = current_view is not None and set(selected_keys) != set(k for k in current_view.keys if k in series)
        if modified:
            current_view = None  # the links below carry ``ds`` explicitly instead

        events, counts, capped = collect_events(selected, lower, upper, request)
        weeks = build_month_grid(cursor, events, today, selected_day, max_per_day=MAX_PER_DAY)
        # The right column always shows a day: the one clicked, else today
        # when it is in the visible month. Only an explicit click outlines a cell.
        panel_day = selected_day if selected_day is not None else (today if lower <= today < upper else None)
        day_events = events_on(events, panel_day) if panel_day else []

        def link(
            *,
            keys: Optional[list[str]] = None,
            month: Optional[date] = None,
            day: Optional[date] = None,
            view: Optional[SavedCalendarView] = current_view,
        ) -> str:
            params: list[tuple[str, str]] = []
            use_keys = selected_keys if keys is None else keys
            if view is not None and keys is None:
                params.append(("view", str(view.pk)))
            else:
                # An explicit empty ``ds=`` means "none" (vs. "no parameters" →
                # the default view). Emitted so the state round-trips.
                params.extend(("ds", k) for k in use_keys)
                if not use_keys:
                    params.append(("ds", ""))
            m = cursor if month is None else month
            if m.replace(day=1) != today.replace(day=1):
                params.append(("month", m.strftime("%Y-%m")))
            if day is not None:
                params.append(("day", day.isoformat()))
            return reverse("calendar_index") + ("?" + urlencode(params) if params else "")

        picker = []
        for cal in cals:
            on = cal.key in selected_keys
            toggled = [k for k in selected_keys if k != cal.key] if on else selected_keys + [cal.key]
            picker.append(
                {
                    "key": cal.key,
                    "label": cal.label,
                    "description": cal.description,
                    "series": series[cal.key],
                    "selected": on,
                    "count": counts.get(cal.key) if on else None,
                    "capped": cal.key in capped,
                    "ranged": cal.ranged,
                    "access": cal.spec.access,
                    "toggle_url": link(keys=toggled),
                }
            )

        prev_month = (cursor - timedelta(days=1)).replace(day=1)
        next_month = upper
        for week in weeks:
            for cell in week:
                if cell:
                    cell["url"] = link(day=cell["date"])
        for ev in events:
            ev.series = series.get(ev.calendar, 1)  # type: ignore[attr-defined]
        labels = {c.key: c.label for c in cals}
        for ev in day_events:
            ev.calendar_label = labels.get(ev.calendar, ev.calendar)  # type: ignore[attr-defined]

        save_params = {"datasets": ",".join(selected_keys)} if selected_keys else {}
        context.update(
            {
                "today": today,
                "cursor": cursor,
                "month_label": cursor.strftime("%B %Y"),
                "is_current_month": cursor == today.replace(day=1),
                "prev_url": link(month=prev_month, day=None),
                "next_url": link(month=next_month, day=None),
                "today_url": link(month=today, day=None),
                "weekday_headers": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                "weeks": weeks,
                "picker": picker,
                "selected": selected,
                "selected_keys": selected_keys,
                "selected_count": len(selected_keys),
                "all_url": link(keys=[c.key for c in cals]),
                "none_url": link(keys=[]),
                "event_count": len(events),
                "capped": sorted(labels[k] for k in capped),
                "selected_day": selected_day,
                "panel_day": panel_day,
                "panel_day_is_today": panel_day == today,
                "selected_day_label": panel_day.strftime("%A, %B %-d") if panel_day else "",
                "day_events": day_events,
                "close_day_url": link(day=None),
                "saved_views": [
                    {
                        "obj": v,
                        "url": v.get_absolute_url(),
                        "active": current_view is not None and v.pk == current_view.pk,
                    }
                    for v in views
                ],
                "current_view": current_view,
                "save_url": reverse("calendar/views-create") + ("?" + urlencode(save_params) if save_params else ""),
                "views_url": reverse("calendar/views-list"),
                "has_calendars": bool(cals),
                "ics_url": (
                    reverse("calendar_api_ics") + "?" + urlencode([("ds", k) for k in selected_keys])
                    if selected_keys
                    else ""
                ),
            }
        )
        return context


# ---------------------------------------------------------------------------
# Saved views — a per-user CRUDView (HTML + REST + MCP from one class)
# ---------------------------------------------------------------------------


def _datasets_cell(value: Any, obj: SavedCalendarView) -> Any:
    from .core import get_calendar

    labels = []
    for key in obj.keys:
        cal = get_calendar(key)
        labels.append(cal.label if cal is not None else key)
    if not labels:
        return "—"
    return format_html("{}", ", ".join(labels))


def _default_cell(value: Any, obj: SavedCalendarView) -> Any:
    if not obj.is_default:
        return ""
    return format_html('<span style="color: var(--primary); font-weight: 600;">{}</span>', "Default")


class SavedCalendarViewCRUDView(CRUDView):
    """A user's saved calendar selections. Owner-scoped on every surface:
    the HTML list, the REST routes and the generated MCP tools all read
    through ``get_list_queryset``, and a create stamps the signed-in owner."""

    model = SavedCalendarView
    form_class = SavedCalendarViewForm
    fields = ["name", "datasets", "is_default"]
    list_fields = ["name", "datasets", "is_default", "updated_at"]
    link_field = "name"
    field_transforms = {
        "datasets": _datasets_cell,
        "is_default": _default_cell,
        "updated_at": "localtime",
    }
    column_widths = {"name": "26%", "is_default": "12%", "updated_at": "20%"}
    url_base = "calendar/views"
    paginate_by = 25
    mixins = [LoginRequiredMixin]
    bulk_actions: list = []
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
    breadcrumb_parent = ("Calendar", "calendar_index")
    ordering_fields = ["name", "updated_at"]

    enable_api = True
    api_extra_fields = ["owner", "created_at", "updated_at"]
    api_expand_fields = ["owner"]

    enable_mcp = True
    mcp_singular = "calendar_view"
    mcp_plural = "calendar_views"
    mcp_description = (
        "a saved calendar view: a named list of calendar dataset keys the user shows together on "
        "/smallstack/calendar/ (see list_calendars for the keys); one per user may be the default"
    )

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return qs.none()
        return qs.filter(owner=user)

    @classmethod
    def row_link_url(cls, obj: SavedCalendarView, request: HttpRequest) -> str:
        return obj.get_absolute_url()

    @classmethod
    def _make_view(cls, base_class: Any) -> Any:
        """Hand the form the signed-in user (its choices are per-user), and let
        the calendar page prefill a new view with ``?datasets=a,b``."""
        view = super()._make_view(base_class)
        if hasattr(view, "get_form_kwargs"):
            inherited_kwargs = view.get_form_kwargs

            def get_form_kwargs(self: Any) -> dict:
                kwargs = inherited_kwargs(self)
                kwargs["user"] = getattr(self.request, "user", None)
                return kwargs

            view.get_form_kwargs = get_form_kwargs
        if base_class is _CRUDCreateBase:
            inherited_initial = view.get_initial

            def get_initial(self: Any) -> dict:
                initial = dict(inherited_initial(self))
                raw = self.request.GET.get("datasets")
                if raw:
                    initial["datasets"] = raw
                return initial

            view.get_initial = get_initial
        return view


def view_or_none(user: Any, raw: Any) -> Optional[SavedCalendarView]:
    """A saved view by pk if ``user`` owns it (shared by the API routes)."""
    try:
        pk = int(raw)
    except (TypeError, ValueError):
        return None
    return SavedCalendarView.objects.filter(owner=user, pk=pk).first()


__all__ = ["CalendarDataset", "CalendarPageView", "SavedCalendarViewCRUDView", "requested_keys", "view_or_none"]
