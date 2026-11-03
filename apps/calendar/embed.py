"""A calendar on any page — the embed service behind ``{% calendar_card %}``,
the ``/smallstack/calendar/embed/`` fragment endpoint and the ``calendar``
dashboard card.

The shape mirrors the dashboards app's ``board_embed`` / ``render_cell``
pair: :func:`calendar_embed` resolves what the viewer may see and returns a
plain structure (the fragment URL, the pre-rendered HTML when asked, the
calendars), and :func:`embed_context` builds the template context for the
fragment itself. Every nav link inside the fragment points back at the
fragment URL with one parameter changed, and the fragment's wrapper carries
``hx-boost`` so those links swap the fragment in place; without script they
still work as ordinary links to the fragment, and the host page's URL is
never touched.

Modes:

``month``    the month grid; a clicked day lists its events underneath
``board``    the 30/60/90-day board (``RangeWindow``), day column beside it
``upcoming`` the next N days as a compact list — the dashboard-card default

Access is the calendar access rule (``core.resolve_keys``): a key the viewer
may not see is dropped, indistinguishably from an unknown one.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

from django.http import HttpRequest, QueryDict
from django.urls import reverse
from django.utils import timezone

from .core import (
    CalendarDataset,
    CalendarEvent,
    RangeWindow,
    assign_series,
    build_month_grid,
    collect_events,
    colourise,
    day_url,
    events_on,
    group_by_calendar,
    month_bounds,
    parse_day,
    parse_month,
    parse_weekends,
    resolve_keys,
    visible_calendars,
)

MODES = ("month", "board", "upcoming")
DEFAULT_MODE = "month"
#: Upcoming list: how far ahead, how many rows (each capped at the max).
UPCOMING_DAYS = 14
UPCOMING_LIMIT = 8
MAX_UPCOMING_DAYS = 366
MAX_UPCOMING_LIMIT = 50
MAX_PER_DAY = 3  # month-grid chips per cell inside an embed (the page shows 4)


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


def split_keys(value: Any) -> list[str]:
    """Calendar keys from a comma-separated string, a list of strings, a
    ``SavedCalendarView`` (its keys) or ``None``. Order kept, blanks and
    duplicates dropped."""
    if value is None:
        return []
    if hasattr(value, "keys") and not isinstance(value, (str, dict)):
        raw = value.keys  # SavedCalendarView.keys is a list
        raw = raw() if callable(raw) else raw
    elif isinstance(value, str):
        raw = value.split(",")
    else:
        raw = list(value)
    keys: list[str] = []
    for item in raw:
        key = str(item).strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def requested_keys(params: Any) -> list[str]:
    """``?ds=`` — repeatable and/or comma-separated (the page's spelling)."""
    getlist = getattr(params, "getlist", None)
    values = getlist("ds") if getlist else [params.get("ds", "")]
    return split_keys(",".join(values))


def parse_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in MODES else DEFAULT_MODE


def clamp_int(raw: Any, default: int, lo: int, hi: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def embed_url(keys: list[str], mode: str = DEFAULT_MODE, **params: Any) -> str:
    """The fragment URL for ``keys`` in ``mode``; extra keyword parameters
    (``month``, ``days``, ``limit``, ``weekends`` …) ride along. ``None``
    values are skipped."""
    pairs: list[tuple[str, str]] = [("ds", k) for k in keys]
    pairs.append(("mode", parse_mode(mode)))
    for name, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "1" if value else "0"
        elif isinstance(value, date):
            value = value.isoformat()
        pairs.append((name, str(value)))
    return reverse("calendar_embed") + "?" + urlencode(pairs)


# ---------------------------------------------------------------------------
# The fragment's context
# ---------------------------------------------------------------------------


def _fragment_request(request: HttpRequest, url: str) -> HttpRequest:
    """A copy of ``request`` whose path + query string are the fragment's,
    so ``day_url`` / ``RangeWindow.url`` build links that point back at the
    fragment, while ``request.user`` (what dataset functions read) is intact."""
    path, _, query = url.partition("?")
    shim = copy.copy(request)
    shim.path = path
    shim.GET = QueryDict(query, mutable=False)
    return shim


def _month_nav(request: HttpRequest, cursor: date, today: date) -> dict[str, Any]:
    def url(month: Optional[date]) -> str:
        params = request.GET.copy()
        params.pop("day", None)
        params.pop("month", None)
        if month is not None and month.replace(day=1) != today.replace(day=1):
            params["month"] = month.strftime("%Y-%m")
        encoded = params.urlencode()
        return request.path + ("?" + encoded if encoded else "")

    first = cursor.replace(day=1)
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return {
        "prev_url": url(prev_month),
        "next_url": url(next_month),
        "today_url": url(None),
        "is_now": first == today.replace(day=1),
        "period_label": first.strftime("%B %Y"),
    }


def build_upcoming(events: list[CalendarEvent], lower: date, upper: date, today: date, limit: int) -> dict[str, Any]:
    """The next entries from ``lower`` grouped by day — at most ``limit``
    rows, the rest counted. A span already under way is listed on its first
    day in the window."""
    days: list[dict[str, Any]] = []
    by_day: dict[date, dict[str, Any]] = {}
    shown = 0
    for ev in events:
        if shown >= limit:
            break
        day = max(ev.start_date, lower)
        if not (lower <= day < upper):
            continue
        slot = by_day.get(day)
        if slot is None:
            delta = (day - today).days
            if delta == 0:
                label = "Today"
            elif delta == 1:
                label = "Tomorrow"
            elif 0 < delta < 7:
                label = day.strftime("%A")
            else:
                label = day.strftime("%a %-d %b")
            slot = {"date": day, "label": label, "is_today": delta == 0, "events": []}
            by_day[day] = slot
            days.append(slot)
        slot["events"].append(ev)
        shown += 1
    return {"days": days, "shown": shown, "more": max(0, len(events) - shown)}


def embed_context(request: HttpRequest, cals: list[CalendarDataset]) -> dict[str, Any]:
    """Template context for ``calendar/includes/embed_body.html`` — the
    fragment — from the fragment request's query string (see the module
    docstring for the vocabulary) and the calendars the viewer may see."""
    get = request.GET
    today = timezone.localdate()
    mode = parse_mode(get.get("mode"))
    series = assign_series(visible_calendars(request.user))
    selected_day = parse_day(get.get("day", ""))
    ctx: dict[str, Any] = {
        "mode": mode,
        "keys": [c.key for c in cals],
        "cals": cals,
        "fragment_url": request.get_full_path() if hasattr(request, "get_full_path") else request.path,
        "today": today,
    }

    if mode == "board":
        days = clamp_int(get.get("days"), 30, 1, 90)
        win = RangeWindow.from_request(request, days=days)
        events, _counts, capped = collect_events(cals, win.lower, win.upper, request)
        colourise(events, series)
        ctx.update(win.context(events))
        ctx.update({"capped": sorted(capped), "lower": win.lower, "upper": win.upper})
        ctx["page_url"] = _page_url(ctx["keys"], range_=win.days, from_=win.anchor, today=today)
        return ctx

    if mode == "upcoming":
        days = clamp_int(get.get("days"), UPCOMING_DAYS, 1, MAX_UPCOMING_DAYS)
        limit = clamp_int(get.get("limit"), UPCOMING_LIMIT, 1, MAX_UPCOMING_LIMIT)
        lower, upper = today, today + timedelta(days=days)
        events, _counts, capped = collect_events(cals, lower, upper, request)
        colourise(events, series)
        ctx.update(build_upcoming(events, lower, upper, today, limit))
        ctx.update(
            {
                "event_count": len(events),
                "capped": sorted(capped),
                "lower": lower,
                "upper": upper,
                "days_ahead": days,
                "period_label": f"Next {days} day{'s' if days != 1 else ''}",
            }
        )
        ctx["page_url"] = _page_url(ctx["keys"], range_=30, from_=today, today=today)
        return ctx

    # -- month (the default) ----------------------------------------------------
    cursor = parse_month(get.get("month", ""), today)
    lower, upper = month_bounds(cursor)
    weekends = parse_weekends(get.get("weekends"))
    if selected_day is not None and not (lower <= selected_day < upper):
        selected_day = None
    events, _counts, capped = collect_events(cals, lower, upper, request)
    colourise(events, series)
    weeks = build_month_grid(cursor, events, today, selected_day, max_per_day=MAX_PER_DAY)
    if not weekends:
        weeks = [([c for c in week if c is None or not c["is_weekend"]] + [None] * 5)[:5] for week in weeks]
        weeks = [w for w in weeks if any(w)]
    for week in weeks:
        for cell in week:
            if cell:
                cell["url"] = day_url(request, cell["date"])
    headers = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_events = events_on(events, selected_day) if selected_day else []
    ctx.update(_month_nav(request, cursor, today))
    ctx.update(
        {
            "weeks": weeks,
            "weekday_headers": headers if weekends else headers[:5],
            "weekends": weekends,
            "event_count": len(events),
            "capped": sorted(capped),
            "lower": lower,
            "upper": upper,
            "cursor": cursor,
            "selected_day": selected_day,
            "panel_day": selected_day,
            "selected_day_label": selected_day.strftime("%A, %B %-d") if selected_day else "",
            "day_groups": group_by_calendar(day_events),
            "day_events": day_events,
            "close_url": day_url(request, None),
        }
    )
    ctx["page_url"] = _page_url(ctx["keys"], month=cursor, today=today)
    return ctx


def _page_url(
    keys: list[str],
    *,
    month: Optional[date] = None,
    range_: Optional[int] = None,
    from_: Optional[date] = None,
    today: Optional[date] = None,
) -> str:
    """The shared calendar page opened on the same calendars and window —
    the embed's "open" link."""
    params: list[tuple[str, str]] = [("ds", k) for k in keys]
    if range_:
        params.append(("range", str(range_)))
        if from_ is not None and from_ != today:
            params.append(("from", from_.isoformat()))
    elif month is not None and today is not None and month.replace(day=1) != today.replace(day=1):
        params.append(("month", month.strftime("%Y-%m")))
    return reverse("calendar_index") + ("?" + urlencode(params) if params else "")


def render_fragment(request: HttpRequest, cals: list[CalendarDataset]) -> str:
    """The fragment's HTML for the fragment request (what the endpoint
    returns and what an eager embed inlines)."""
    from django.template.loader import render_to_string

    return render_to_string("calendar/includes/embed_body.html", embed_context(request, cals), request=request)


# ---------------------------------------------------------------------------
# The embed — what a page or a dashboard card asks for
# ---------------------------------------------------------------------------


def calendar_embed(
    request: HttpRequest,
    calendars: Any,
    *,
    mode: str = DEFAULT_MODE,
    lazy: bool = True,
    **params: Any,
) -> Optional[dict[str, Any]]:
    """Resolve ``calendars`` for ``request.user`` and describe the embed.

    Returns ``None`` when the viewer is anonymous or may see none of the
    calendars (unknown and forbidden keys are indistinguishable), so a page
    never reveals a calendar exists. Otherwise ``{keys, cals, mode, url,
    html, page_url, label}`` — ``url`` is the fragment endpoint with the
    state baked in, ``html`` the fragment rendered now (``lazy=False``) or
    ``None``. ``params`` are the fragment's query parameters (``month``,
    ``days``, ``limit``, ``weekends`` …).
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    cals, _rejected = resolve_keys(split_keys(calendars), user)
    if not cals:
        return None
    keys = [c.key for c in cals]
    mode = parse_mode(mode)
    url = embed_url(keys, mode, **params)
    html: Optional[str] = None
    if not lazy:
        html = render_fragment(_fragment_request(request, url), cals)
    label = cals[0].label if len(cals) == 1 else f"{len(cals)} calendars"
    return {
        "keys": keys,
        "cals": cals,
        "mode": mode,
        "url": url,
        "html": html,
        "page_url": _page_url(keys, today=timezone.localdate()),
        "label": label,
    }
