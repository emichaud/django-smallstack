"""Provider-backed calendars, the cancelled/image fields, colour pinning, the
weekends default and the board's two honesty rules."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from apps.calendar import calendar_provider, register_calendar
from apps.calendar.core import (
    CalendarEvent,
    CalendarProtocolError,
    assign_series,
    build_range_board,
    events_from_objects,
    get_calendar,
    iter_calendars,
    parse_weekends,
    visible_calendars,
    weekend_entries,
)
from apps.calendar.registry import unregister
from apps.heartbeat.models import MaintenanceWindow

pytestmark = pytest.mark.django_db

User = get_user_model()
PAGE = reverse("calendar_index")


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="prov-staff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


def _aware(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=dt_tz.utc)


@pytest.fixture
def holidays():
    """A computed calendar: no dataset, no model — the function is the source."""
    key = "t_holidays"

    @calendar_provider(key, label="Company holidays", description="Rule-generated", access="authenticated", color=5)
    def provider(lower, upper, request):
        for year in range(lower.year, upper.year + 1):
            yield CalendarEvent.make(key, f"xmas:{year}", "Christmas Day", date(year, 12, 25))
            yield CalendarEvent.make(key, f"ny:{year}", "New Year's Day", date(year, 1, 1))
            # Deliberately over-reads: an event outside the window is filtered out by core.
            yield CalendarEvent.make(key, f"far:{year}", "Far away", date(year, 6, 1) + timedelta(days=3650))
        yield CalendarEvent.make(
            key, "offsite", "Offsite", _aware(2026, 12, 3, 9), _aware(2026, 12, 4, 17),
            subtitle="Grand Rapids", cancelled=True, image="/static/brand/icon.png",
        )

    yield key
    unregister(key)


# -- the provider seam ----------------------------------------------------------


def test_provider_calendar_needs_no_dataset(staff, holidays):
    cal = get_calendar(holidays)
    assert cal is not None and cal.is_provider and cal.dataset is None
    cal.validate()  # nothing to validate, never raises
    assert cal.label == "Company holidays" and cal.describe()["provider"] is True
    assert holidays in {c.key for c in iter_calendars()}
    events = cal.events(date(2026, 12, 1), date(2027, 1, 2))
    assert [e.title for e in events] == ["Offsite", "Christmas Day", "New Year's Day"]  # sorted, window-clipped
    xmas = events[1]
    assert xmas.calendar == holidays and xmas.calendar_label == "Company holidays" and xmas.all_day
    assert xmas.start_date == date(2026, 12, 25) and xmas.id == "xmas:2026"
    assert cal.count(date(2026, 12, 1), date(2027, 1, 2)) == 3
    with pytest.raises(CalendarProtocolError):
        cal.window_queryset(date(2026, 12, 1), date(2027, 1, 2))


def test_provider_calendar_on_every_surface(client, staff, holidays):
    # The page, with the picker hint, the chip and the day column.
    resp = client.get(PAGE, {"ds": holidays, "month": "2026-12", "day": "2026-12-25"})
    assert resp.status_code == 200
    html = resp.content.decode()
    pick = next(p for p in resp.context["picker"] if p["key"] == holidays)
    assert pick["provider"] and pick["series"] == 5  # pinned colour
    assert "Christmas Day" in html and 'cal-day-group-title">Company holidays' in html
    # Events API + ICS.
    window = {"ds": holidays, "start": "2026-12-01", "end": "2027-01-02"}
    body = client.get(reverse("calendar_api_events"), window).json()
    assert body["count"] == 3
    assert {r["title"] for r in body["results"]} == {"Offsite", "Christmas Day", "New Year's Day"}
    off = next(r for r in body["results"] if r["title"] == "Offsite")
    assert off["cancelled"] is True and off["image"].endswith("icon.png") and off["all_day"] is False
    ics = client.get(reverse("calendar_api_ics"), window).content.decode()
    assert "SUMMARY:CANCELLED: Offsite" in ics and "STATUS:CANCELLED" in ics
    assert f"UID:{holidays}-xmas:2026@" in ics and "DTSTART;VALUE=DATE:20261225" in ics
    # MCP.
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=staff, token=None))
    try:
        assert holidays in {c["key"] for c in TOOL_HANDLERS["list_calendars"]({})["results"]}
        out = TOOL_HANDLERS["calendar_events"]({"calendars": [holidays], "start": "2026-12-20", "end": "2026-12-31"})
        assert [r["title"] for r in out["results"]] == ["Christmas Day"]
    finally:
        reset_context(token)


def test_provider_access_and_bad_providers(holidays):
    plain = User.objects.create_user(username="prov-plain", password="pw-123456")
    assert holidays in {c.key for c in visible_calendars(plain)}  # access="authenticated"
    with pytest.raises(ValueError):
        register_calendar("t_bad_both", start="start", provider=lambda lo, up, r: [])
    with pytest.raises(ValueError):
        register_calendar("t_bad_neither")
    with pytest.raises(ValueError):
        register_calendar("t_bad_color", provider=lambda lo, up, r: [], color=9)
    key = "t_bad_yield"
    try:
        register_calendar(key, provider=lambda lo, up, r: [{"title": "not an event"}])
        with pytest.raises(CalendarProtocolError):
            get_calendar(key).events(date(2026, 1, 1), date(2026, 2, 1))
    finally:
        unregister(key)


# -- cancelled / image through the column protocol -------------------------------


def test_cancelled_and_image_resolvers_on_rows(staff):
    MaintenanceWindow.objects.create(monitor_key="site", title="Kept", start=_aware(2026, 4, 3), end=_aware(2026, 4, 4))
    MaintenanceWindow.objects.create(
        monitor_key="mcp", title="Dropped", start=_aware(2026, 4, 5), end=_aware(2026, 4, 5, 15), exclude_from_sla=False
    )
    events = events_from_objects(
        MaintenanceWindow.objects.order_by("start"),
        start="start",
        end="end",
        title="title",
        cancelled=lambda w: not w.exclude_from_sla,
        image=lambda w: f"/img/{w.monitor_key}.png",
    )
    assert [(e.title, e.cancelled, e.image) for e in events] == [
        ("Kept", False, "/img/site.png"),
        ("Dropped", True, "/img/mcp.png"),
    ]
    assert events[1].as_dict()["cancelled"] is True


# -- colour pinning ---------------------------------------------------------------


def test_pinned_colours_win_and_others_fill_around_them(staff, holidays):
    cals = visible_calendars(staff)
    series = assign_series(cals)
    assert series[holidays] == 5
    others = [v for k, v in series.items() if k != holidays]
    # Eleven bundled calendars + one pinned: the unpinned ones use the seven free slots first.
    assert 5 not in others[:7] and set(others) <= set(range(1, 9))


# -- weekends: default setting, the note, the empty-column rule ------------------


def test_parse_weekends_and_site_default():
    assert parse_weekends(None) is True and parse_weekends("0") is False and parse_weekends("on") is True
    with override_settings(SMALLSTACK_CALENDAR_WEEKENDS_DEFAULT=False):
        assert parse_weekends(None) is False and parse_weekends("1") is True


@override_settings(SMALLSTACK_CALENDAR_WEEKENDS_DEFAULT=False)
def test_work_week_default_runs_through_the_page(client, staff):
    MaintenanceWindow.objects.create(
        monitor_key="site", title="Sat job", start=_aware(2026, 4, 4), end=_aware(2026, 4, 4, 15)
    )
    MW = "smallstack_maintenance_windows"
    resp = client.get(PAGE, {"ds": MW, "month": "2026-04"})
    assert resp.context["weekends"] is False and len(resp.context["weekday_headers"]) == 5
    # The hidden Saturday entry is announced, and the toggle turns weekends ON explicitly.
    assert resp.context["weekend_hidden"] == 1
    assert "1 entry falls at the weekend" in resp.content.decode()
    assert "weekends=1" in resp.context["weekends_url"] and "weekends=0" not in resp.context["next_url"]
    resp = client.get(PAGE, {"ds": MW, "month": "2026-04", "weekends": "1"})
    assert resp.context["weekends"] is True and resp.context["weekend_hidden"] == 0


def test_weekend_entries_and_empty_week_columns(staff):
    key = "t_wk"
    try:

        @calendar_provider(key, label="Weekend things")
        def provider(lower, upper, request):
            yield CalendarEvent.make(key, "a", "Saturday thing", date(2026, 4, 4))
            yield CalendarEvent.make(key, "b", "Sunday thing", date(2026, 4, 5))
            yield CalendarEvent.make(key, "c", "Weekday thing", date(2026, 4, 7))

        events = get_calendar(key).events(date(2026, 4, 1), date(2026, 5, 1))
        assert weekend_entries(events, date(2026, 4, 1), date(2026, 5, 1)) == 2
        # A window opening on Sunday Apr 5 with weekends hidden: the Mar 30–Apr 5
        # column has no visible day and is dropped; Apr 6–12 keeps its entry.
        board = build_range_board(date(2026, 4, 5), date(2026, 4, 20), events, today=date(2026, 4, 1), weekends=False)
        assert [c["label"] for c in board] == ["Apr 6–12", "Apr 13–19"]  # Apr 20 is the exclusive upper bound
        assert board[0]["count"] == 1 and board[1]["count"] == 0  # a week in range with nothing stays
        with_weekends = build_range_board(date(2026, 4, 5), date(2026, 4, 20), events, today=date(2026, 4, 1))
        assert with_weekends[0]["label"] == "Mar 30–Apr 5" and with_weekends[0]["count"] == 1
    finally:
        unregister(key)


def test_board_component_announces_hidden_weekend_entries(client, staff):
    MaintenanceWindow.objects.create(
        monitor_key="site", title="Sat job", start=_aware(2026, 4, 4), end=_aware(2026, 4, 4, 15)
    )
    MW = "smallstack_maintenance_windows"
    resp = client.get(PAGE, {"ds": MW, "range": "30", "from": "2026-04-01", "weekends": "0"})
    assert resp.context["weekend_hidden"] == 1 and "turn on Weekends to see" in resp.content.decode()
    # The CRUDView display reads the same rule through RangeWindow.
    resp = client.get(
        reverse("scheduler/runs-list"), {"display": "board", "range": "30", "from": "2026-04-01", "weekends": "0"}
    )
    assert resp.status_code == 200 and resp.context["weekends"] is False
