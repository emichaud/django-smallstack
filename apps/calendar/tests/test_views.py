"""The calendar page, saved views (HTML + REST + MCP), and the events API."""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone as dt_tz

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.calendar import calendar_dataset
from apps.calendar.models import SavedCalendarView
from apps.calendar.registry import unregister
from apps.datasets.registry import unregister as unregister_dataset
from apps.heartbeat.models import MaintenanceWindow
from apps.smallstack.models import BackupRecord

pytestmark = pytest.mark.django_db

User = get_user_model()
PAGE = reverse("calendar_index")
API_LIST = reverse("calendar_api_list")
API_EVENTS = reverse("calendar_api_events")
API_ICS = reverse("calendar_api_ics")
VIEWS_LIST = reverse("calendar/views-list")
VIEWS_CREATE = reverse("calendar/views-create")
MW = "smallstack_maintenance_windows"
BK = "smallstack_backups"


def _aware(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=dt_tz.utc)


def _backup(filename: str, status: str, created_at: datetime) -> BackupRecord:
    """``created_at`` is auto_now_add, so a create() kwarg is ignored — set it after."""
    rec = BackupRecord.objects.create(filename=filename, status=status)
    BackupRecord.objects.filter(pk=rec.pk).update(created_at=created_at)
    rec.refresh_from_db()
    return rec


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="cal-staff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def plain(client):
    user = User.objects.create_user(username="cal-plain", password="pw-123456")
    client.force_login(user)
    return user


@pytest.fixture
def seeded():
    MaintenanceWindow.objects.create(
        monitor_key="site", title="DB upgrade", start=_aware(2026, 4, 3), end=_aware(2026, 4, 4)
    )
    _backup("nightly.sqlite3", "success", _aware(2026, 4, 3, 9))
    _backup("failed", "failed", _aware(2026, 4, 20, 9))


# -- page ---------------------------------------------------------------------


def test_page_requires_login(client):
    resp = client.get(PAGE)
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_page_lists_calendars_and_starts_empty(client, staff):
    resp = client.get(PAGE)
    assert resp.status_code == 200
    keys = {p["key"] for p in resp.context["picker"]}
    assert {MW, BK} <= keys
    assert resp.context["selected_keys"] == [] and resp.context["event_count"] == 0
    assert "Nothing selected" in resp.content.decode()


def test_toggling_calendars_is_additive(client, staff, seeded):
    resp = client.get(PAGE, {"ds": MW, "month": "2026-04"})
    assert resp.context["selected_keys"] == [MW] and resp.context["event_count"] == 1
    picker = {p["key"]: p for p in resp.context["picker"]}
    assert picker[MW]["selected"] and picker[MW]["count"] == 1
    # The toggle link for an unselected calendar ADDS it; for a selected one REMOVES it.
    assert f"ds={MW}" in picker[BK]["toggle_url"] and f"ds={BK}" in picker[BK]["toggle_url"]
    assert f"ds={MW}" not in picker[MW]["toggle_url"] and "ds=" in picker[MW]["toggle_url"]
    resp = client.get(PAGE, {"ds": [MW, BK], "month": "2026-04"})
    assert resp.context["selected_keys"] == [MW, BK] and resp.context["event_count"] == 3
    # Comma-separated works too, and unknown keys are dropped silently.
    resp = client.get(PAGE, {"ds": f"{MW},{BK},bogus", "month": "2026-04"})
    assert resp.context["selected_keys"] == [MW, BK]
    # Month navigation carries the selection.
    assert f"ds={MW}" in resp.context["next_url"] and "month=2026-05" in resp.context["next_url"]
    assert "month=2026-03" in resp.context["prev_url"]


def test_day_panel_lists_that_days_events(client, staff, seeded):
    resp = client.get(PAGE, {"ds": [MW, BK], "month": "2026-04", "day": "2026-04-03"})
    assert resp.status_code == 200
    titles = sorted(ev.title for ev in resp.context["day_events"])
    assert titles == ["DB upgrade", "nightly.sqlite3"]
    html = resp.content.decode()
    assert "Friday, April 3" in html and "Maintenance windows" in html
    # A day outside the month is ignored; garbage too.
    assert client.get(PAGE, {"ds": MW, "month": "2026-04", "day": "2026-05-01"}).context["selected_day"] is None
    assert client.get(PAGE, {"ds": MW, "day": "nope"}).context["selected_day"] is None
    # Every cell links to its day.
    cell = next(c for w in resp.context["weeks"] for c in w if c and c["day"] == 20)
    assert "day=2026-04-20" in cell["url"] and f"ds={BK}" in cell["url"]


def test_day_column_defaults_to_today_in_the_current_month(client, staff):
    from django.utils import timezone

    today = timezone.localdate()
    resp = client.get(PAGE, {"ds": MW})
    assert resp.context["selected_day"] is None  # nothing clicked → no outlined cell
    assert resp.context["panel_day"] == today and resp.context["panel_day_is_today"]
    assert "Showing today" in resp.content.decode()
    # Another month has no "today" → the column asks for a click.
    resp = client.get(PAGE, {"ds": MW, "month": "2020-01"})
    assert resp.context["panel_day"] is None
    assert "Click a day to see its events" in resp.content.decode()


def test_non_staff_sees_only_authenticated_calendars(client, plain, seeded):
    key = "t_cal_mine"
    try:

        @calendar_dataset(key, start="start", end="end", title="title", access="authenticated", label="Mine")
        def mine(request):
            return MaintenanceWindow.objects.all()

        resp = client.get(PAGE, {"ds": [key, MW], "month": "2026-04"})
        assert resp.status_code == 200
        assert {p["key"] for p in resp.context["picker"]} == {key}
        assert resp.context["selected_keys"] == [key]  # the staff key was dropped
        assert resp.context["event_count"] == 1
    finally:
        unregister(key)
        unregister_dataset(key)


# -- saved views --------------------------------------------------------------


def test_save_view_prefills_from_selection_and_stamps_owner(client, staff, seeded):
    resp = client.get(VIEWS_CREATE, {"datasets": f"{MW},{BK}"})
    assert resp.status_code == 200
    form = resp.context["form"]
    assert form.initial["datasets"] == [MW, BK]
    assert dict(form.fields["datasets"].choices)[MW] == "Maintenance windows"
    resp = client.post(VIEWS_CREATE, {"name": "Ops", "datasets": [MW, BK], "is_default": "on"})
    assert resp.status_code == 302
    view = SavedCalendarView.objects.get(name="Ops")
    assert view.owner == staff and view.keys == [MW, BK] and view.is_default
    # No params → the default view loads.
    resp = client.get(PAGE)
    assert resp.context["selected_keys"] == [MW, BK]
    assert resp.context["current_view"] == view
    assert resp.context["saved_views"][0]["active"]
    # ?view= loads it explicitly; ds overrides it (and the view is then "modified").
    assert client.get(PAGE, {"view": view.pk}).context["current_view"] == view
    resp = client.get(PAGE, {"view": view.pk, "ds": MW})
    assert resp.context["selected_keys"] == [MW] and resp.context["current_view"] is None
    # An explicit empty ds means none, even with a default view.
    assert client.get(PAGE, {"ds": ""}).context["selected_keys"] == []


def test_one_default_per_owner(staff):
    a = SavedCalendarView.objects.create(owner=staff, name="A", datasets=[MW], is_default=True)
    b = SavedCalendarView.objects.create(owner=staff, name="B", datasets=[BK], is_default=True)
    a.refresh_from_db()
    assert not a.is_default and b.is_default


def test_views_are_owner_scoped(client, staff):
    other = User.objects.create_user(username="other", password="pw-123456")
    theirs = SavedCalendarView.objects.create(owner=other, name="Theirs", datasets=[MW])
    mine = SavedCalendarView.objects.create(owner=staff, name="Mine", datasets=[MW], is_default=True)
    resp = client.get(VIEWS_LIST)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Mine" in html and "Theirs" not in html
    assert "Default" in html and "Maintenance windows" in html  # the transformed cells render
    assert client.get(reverse("calendar/views-update", kwargs={"pk": theirs.pk})).status_code == 404
    assert client.get(reverse("calendar/views-update", kwargs={"pk": mine.pk})).status_code == 200
    # Loading someone else's view by pk is ignored.
    assert client.get(PAGE, {"view": theirs.pk}).context["current_view"] is None
    # REST is scoped the same way.
    resp = client.get("/smallstack/api/calendar/views/")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"Mine"}


def test_non_staff_cannot_save_a_staff_calendar(client, plain):
    resp = client.post(VIEWS_CREATE, {"name": "Sneaky", "datasets": [MW]})
    assert resp.status_code == 200  # re-rendered with errors
    assert "datasets" in resp.context["form"].errors
    assert not SavedCalendarView.objects.filter(name="Sneaky").exists()


def test_rest_create_stamps_owner_and_validates_keys(client, staff):
    resp = client.post(
        "/smallstack/api/calendar/views/",
        data=json.dumps({"name": "Via REST", "datasets": [MW], "is_default": False}),
        content_type="application/json",
    )
    assert resp.status_code in (200, 201), resp.content
    view = SavedCalendarView.objects.get(name="Via REST")
    assert view.owner == staff and view.keys == [MW]
    resp = client.post(
        "/smallstack/api/calendar/views/",
        data=json.dumps({"name": "Bad", "datasets": ["nope"]}),
        content_type="application/json",
    )
    assert resp.status_code == 400


# -- events API ---------------------------------------------------------------


def test_api_requires_auth_as_json(client):
    resp = client.get(API_EVENTS, {"ds": MW})
    assert resp.status_code == 401 and resp["Content-Type"].startswith("application/json")


def test_api_list_and_events(client, staff, seeded):
    resp = client.get(API_LIST)
    assert resp.status_code == 200
    by_key = {c["key"]: c for c in resp.json()["results"]}
    assert by_key[MW]["ranged"] and by_key[MW]["start"] == "start" and by_key[MW]["end"] == "end"
    assert by_key[BK]["ranged"] is False

    resp = client.get(API_EVENTS, {"ds": [MW, BK], "start": "2026-04-01", "end": "2026-05-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3 and body["counts"] == {MW: 1, BK: 2} and body["calendars"] == [MW, BK]
    first = body["results"][0]
    assert set(first) == {
        "calendar", "calendar_label", "id", "title", "subtitle", "start", "end", "all_day", "status",
        "cancelled", "image", "url",
    }
    assert first["calendar_label"] == "Backups"
    assert [r["title"] for r in body["results"]] == ["nightly.sqlite3", "DB upgrade", "failed"]
    assert body["results"][2]["status"] == "danger"

    # Per-calendar route, and a default window (this month) when no dates are given.
    one = reverse("calendar_api_dataset_events", kwargs={"key": BK})
    resp = client.get(one, {"start": "2026-04-01", "end": "2026-05-01"})
    assert resp.status_code == 200 and resp.json()["count"] == 2
    assert client.get(API_EVENTS, {"ds": MW}).status_code == 200

    # Validation: unknown key, bad date, inverted and oversized windows → 400; unknown single key → 404.
    assert client.get(API_EVENTS, {"ds": "nope"}).status_code == 400
    assert client.get(API_EVENTS, {"ds": MW, "start": "yesterday"}).status_code == 400
    assert client.get(API_EVENTS, {"ds": MW, "start": "2026-04-02", "end": "2026-04-01"}).status_code == 400
    assert client.get(API_EVENTS, {"ds": MW, "start": "2020-01-01", "end": "2026-01-01"}).status_code == 400
    assert client.get(reverse("calendar_api_dataset_events", kwargs={"key": "nope"})).status_code == 404


def test_api_view_param_and_non_staff_scope(client, plain, seeded):
    resp = client.get(API_LIST)
    assert resp.status_code == 200 and resp.json()["results"] == []
    assert client.get(API_EVENTS, {"ds": MW}).status_code == 400  # unknown to a non-staff caller
    view = SavedCalendarView.objects.create(owner=plain, name="Empty", datasets=[])
    resp = client.get(API_EVENTS, {"view": view.pk, "start": "2026-04-01", "end": "2026-05-01"})
    assert resp.status_code == 200 and resp.json()["count"] == 0
    assert client.get(API_EVENTS, {"view": 999999}).status_code == 404


def test_ics_feed(client, staff, seeded):
    resp = client.get(API_ICS, {"ds": [MW, BK], "start": "2026-04-01", "end": "2026-05-01"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/calendar")
    body = resp.content.decode()
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.count("BEGIN:VEVENT") == 3
    assert "SUMMARY:DB upgrade" in body and f"UID:{MW}-" in body
    assert "DTSTART:20260403T120000Z" in body and "DTEND:20260404T120000Z" in body
    assert "CATEGORIES:Maintenance windows" in body and "X-SMALLSTACK-STATUS:danger" in body
    assert "URL:http://testserver/" in body
    # Default window needs no dates.
    assert client.get(API_ICS, {"ds": MW}).status_code == 200


# -- MCP ----------------------------------------------------------------------


def test_mcp_tools_registered_and_scoped(staff, seeded):
    from apps.mcp.server import TOOL_HANDLERS, TOOL_REGISTRY, ToolContext, reset_context, set_context

    assert "list_calendars" in TOOL_REGISTRY and "calendar_events" in TOOL_REGISTRY
    assert "list_calendar_views" in TOOL_REGISTRY  # the saved-view CRUDView's generated tools
    token = set_context(ToolContext(user=staff, token=None))
    try:
        listed = TOOL_HANDLERS["list_calendars"]({})
        assert MW in {c["key"] for c in listed["results"]}
        body = TOOL_HANDLERS["calendar_events"]({"calendars": [MW, BK], "start": "2026-04-01", "end": "2026-05-01"})
        assert body["total"] == 3 and body["results"][1]["title"] == "DB upgrade"
        assert "error" in TOOL_HANDLERS["calendar_events"]({"calendars": ["nope"]})
        assert "error" in TOOL_HANDLERS["calendar_events"]({})
        plain = User.objects.create_user(username="mcp-plain", password="pw-123456")
        reset_context(token)
        token = set_context(ToolContext(user=plain, token=None))
        assert TOOL_HANDLERS["list_calendars"]({})["results"] == []
        assert "error" in TOOL_HANDLERS["calendar_events"]({"calendars": [MW]})
    finally:
        reset_context(token)


def test_bundled_dataset_over_saved_views(staff):
    from apps.datasets.core import get_dataset

    SavedCalendarView.objects.create(owner=staff, name="Ops", datasets=[MW])
    ds = get_dataset("smallstack_calendar_views")
    assert ds is not None
    rows = ds.rows(expand=["owner"])
    assert rows[0]["name"] == "Ops" and rows[0]["owner"]["name"] == "cal-staff"


def test_dashboard_widget(staff, seeded):
    from apps.calendar.dashboard_widgets import CalendarDashboardWidget

    data = CalendarDashboardWidget().get_data()
    assert data["status"] == "operational" and "calendars" in data["headline"]


def test_ics_folds_long_lines_and_escapes_text(client, staff):
    from apps.calendar.api import _fold, _ics_text

    long = "x" * 200
    folded = _fold(f"SUMMARY:{long}")
    assert len(folded) > 1 and all(len(line.encode()) <= 75 for line in folded)
    assert all(line.startswith(" ") for line in folded[1:])
    assert "".join(folded[:1] + [line[1:] for line in folded[1:]]) == f"SUMMARY:{long}"
    assert _ics_text("a, b; c\\d\nnext") == "a\\, b\\; c\\\\d\\nnext"
    MaintenanceWindow.objects.create(
        monitor_key="site", title="Semi; colon, comma " + "y" * 120, start=_aware(2026, 4, 3), end=_aware(2026, 4, 4)
    )
    body = client.get(API_ICS, {"ds": MW, "start": "2026-04-01", "end": "2026-05-01"}).content.decode()
    assert "SUMMARY:Semi\\; colon\\, comma" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))


def test_mcp_calendar_events_validates_window_and_limit(staff, seeded):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=staff, token=None))
    try:
        call = TOOL_HANDLERS["calendar_events"]
        assert "error" in call({"calendars": [MW], "start": "not-a-date"})
        assert "error" in call({"calendars": [MW], "start": "2026-04-02", "end": "2026-04-01"})
        assert "error" in call({"calendars": [MW], "start": "2020-01-01", "end": "2026-01-01"})
        # A comma-separated string works like a list; limit trims results but reports the total.
        body = call({"calendars": f"{MW},{BK}", "start": "2026-04-01", "end": "2026-05-01", "limit": 1})
        assert body["total"] == 3 and body["count"] == 1 and len(body["results"]) == 1
        # Default window (this month) when no dates are given.
        assert call({"calendars": [BK]})["start"].endswith("-01")
    finally:
        reset_context(token)


def test_saved_view_schema_is_an_array_of_keys_everywhere(client, staff):
    """An agent builds a saved view from text: a name plus a list of calendar
    keys. Every schema that describes the field must say "array"."""
    from apps.mcp.server import TOOL_HANDLERS, TOOL_REGISTRY, ToolContext, reset_context, set_context

    prop = TOOL_REGISTRY["create_calendar_view"].input_schema["properties"]["datasets"]
    assert prop["type"] == "array" and prop["items"]["type"] == "string"
    assert MW in prop["items"]["enum"]
    # REST OPTIONS and the OpenAPI document agree.
    fields = client.options("/smallstack/api/calendar/views/").json()["fields"]
    assert fields["datasets"]["type"] == "multichoice" and [MW, "Maintenance windows"] in fields["datasets"]["choices"]
    spec = client.get("/api/schema/openapi.json").json()
    schema = next(v for k, v in spec["components"]["schemas"].items() if "SavedCalendarView" in k)
    assert schema["properties"]["datasets"]["type"] == "array"
    assert MW in schema["properties"]["datasets"]["items"]["enum"]
    # The tool accepts a list, a comma-separated string, or one bare key.
    token = set_context(ToolContext(user=staff, token=None))
    try:
        create = TOOL_HANDLERS["create_calendar_view"]
        assert create({"name": "list", "datasets": [MW, BK]})["datasets"] == [MW, BK]
        assert create({"name": "csv", "datasets": f"{MW}, {BK}"})["datasets"] == [MW, BK]
        assert create({"name": "one", "datasets": MW, "is_default": True})["datasets"] == [MW]
        assert "error" in create({"name": "bad", "datasets": "nope"})
    finally:
        reset_context(token)
    assert SavedCalendarView.objects.filter(owner=staff).count() == 3
    assert SavedCalendarView.objects.get(name="one").is_default


def test_range_board_modes(client, staff, seeded):
    from django.utils import timezone

    today = timezone.localdate()
    # Anchored on today by default; ``from`` moves it; invalid range → month.
    resp = client.get(PAGE, {"ds": [MW, BK], "range": "30"})
    assert resp.context["range_days"] == 30 and resp.context["window_lower"] == today
    assert resp.context["weeks"] == [] and resp.context["board"]
    assert [c["active"] for c in resp.context["range_choices"]] == [False, True, False, False]
    assert client.get(PAGE, {"ds": MW, "range": "45"}).context["range_days"] is None
    resp = client.get(PAGE, {"ds": [MW, BK], "range": "30", "from": "2026-04-01"})
    board = resp.context["board"]
    assert resp.context["window_lower"].isoformat() == "2026-04-01" and len(board) == 5  # 30 days → 5 Monday weeks
    assert board[0]["label"] == "Mar 30–Apr 5" and board[0]["count"] == 3  # window Apr 3+4, backup Apr 3
    assert [d["date"].isoformat() for d in board[0]["days"]] == ["2026-04-03", "2026-04-04"]
    assert resp.context["event_count"] == 3 and resp.context["period_label"] == "1 Apr – 30 Apr 2026"
    # Navigation shifts by the range; the day links keep the range.
    assert "from=2026-05-01" in resp.context["next_url"] and "from=2026-03-02" in resp.context["prev_url"]
    assert "range=30" in board[0]["days"][0]["url"] and "day=2026-04-03" in board[0]["days"][0]["url"]
    # 90 days spans 14 weeks.
    assert len(client.get(PAGE, {"ds": MW, "range": "90", "from": "2026-04-01"}).context["board"]) == 14


def test_weekends_toggle(client, staff, seeded):
    resp = client.get(PAGE, {"ds": [MW, BK], "month": "2026-04", "weekends": "0"})
    assert resp.context["weekends"] is False and resp.context["weekday_headers"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert all(len(w) == 5 for w in resp.context["weeks"])
    assert not any(c and c["is_weekend"] for w in resp.context["weeks"] for c in w)
    assert "weekends=0" in resp.context["next_url"] and "weekends=0" not in resp.context["weekends_url"]
    # Saturday Apr 4 (the window's end day) drops off the board too; the count is unchanged.
    resp = client.get(PAGE, {"ds": [MW, BK], "range": "30", "from": "2026-04-01", "weekends": "0"})
    assert [d["date"].isoformat() for d in resp.context["board"][0]["days"]] == ["2026-04-03"]
    assert resp.context["event_count"] == 3


def test_day_column_groups_by_calendar_and_views_dropdown(client, staff, seeded):
    SavedCalendarView.objects.create(owner=staff, name="Zeta", datasets=[MW])
    SavedCalendarView.objects.create(owner=staff, name="Alpha", datasets=[BK])
    resp = client.get(PAGE, {"ds": [MW, BK], "month": "2026-04", "day": "2026-04-03"})
    groups = resp.context["day_groups"]
    assert [g["label"] for g in groups] == ["Backups", "Maintenance windows"]  # series order
    assert [len(g["events"]) for g in groups] == [1, 1]
    html = resp.content.decode()
    assert 'id="cal-view-select"' in html
    assert html.index(">Alpha<") < html.index(">Zeta<")  # alphabetical
    assert "month=2026-04" in [v["url"] for v in resp.context["saved_views"]][0]  # keeps the window




def test_components_render_from_events_via_template_tags(client, staff, seeded):
    """Another page can render the grid, the board and the day column from a
    list of events in one tag each — no view context required."""
    from datetime import date

    from django.template import Context, Template
    from django.test import RequestFactory

    from apps.calendar.core import collect_events, get_calendar

    cal = get_calendar(BK)
    assert cal is not None
    events, _, _ = collect_events([cal], date(2026, 4, 1), date(2026, 5, 1))
    request = RequestFactory().get("/anywhere/", {"foo": "bar", "day": "2026-04-03"})
    html = Template(
        "{% load calendar_tags %}"
        "{% calendar_month events cursor selected_day=day weekends=False %}"
        "{% calendar_board events lower upper selected_day=day %}"
        "{% calendar_day events day %}"
    ).render(Context({
        "request": request, "events": events, "cursor": date(2026, 4, 1),
        "lower": date(2026, 4, 1), "upper": date(2026, 5, 1), "day": date(2026, 4, 3),
    }))
    assert html.count('class="calendar-weekday"') == 5                     # weekday-only grid
    assert 'href="/anywhere/?foo=bar&amp;day=2026-04-20"' in html          # cell links keep the page's own params
    assert 'class="cal-col-label">Mar 30–Apr 5' in html and "FRI 3" in html  # the board
    assert "Friday, April 3" in html and 'cal-day-group-title">Backups' in html  # the day column
    assert "nightly.sqlite3" in html


def test_range_board_display_on_a_crudview(client, staff):
    """The scheduler's run history grows a Board display with the same board."""
    from datetime import timedelta

    from apps.scheduler.models import ScheduledJob, ScheduledJobRun

    job = ScheduledJob.objects.create(name="Nightly demo", task_path="apps.tasks.tasks.noop", schedule_type="interval",
                                      interval_spec="1d")
    first = _aware(2026, 4, 1, 9)
    for offset, status in ((2, "success"), (3, "failed"), (39, "success")):  # Apr 3, Apr 4, May 10
        ScheduledJobRun.objects.create(
            job=job, status=status, scheduled_for=first + timedelta(days=offset), message="demo"
        )
    url = reverse("scheduler/runs-list")
    resp = client.get(url, {"display": "board", "range": "30", "from": "2026-04-01", "day": "2026-04-04"})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Nightly demo" in html and 'class="cal-col-label">Mar 30–Apr 5' in html
    assert "cal-bcard--danger" in html                                     # status_field tints the card
    assert "Saturday, April 4" in html and 'cal-day-group-title">Scheduled job runs' in html
    assert "1 Apr – 30 Apr 2026" in html
    # Entries beyond the window are left out; 60 days pulls them in.
    assert html.count("cal-bcard ") == 2
    resp = client.get(url, {"display": "board", "range": "60", "from": "2026-04-01"})
    assert resp.content.decode().count("cal-bcard ") == 3
    # The display palette now offers table, calendar and board.
    assert 'data-display="board"' in resp.content.decode()
