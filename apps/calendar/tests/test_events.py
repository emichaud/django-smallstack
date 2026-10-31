"""The Events calendar — the one a person types into."""

from __future__ import annotations

import json
from datetime import date, time

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.calendar.core import get_calendar
from apps.calendar.datasets import EVENTS_KEY, visible_events
from apps.calendar.models import Event

pytestmark = pytest.mark.django_db

User = get_user_model()
PAGE = reverse("calendar_index")
LIST = reverse("calendar/events-list")
CREATE = reverse("calendar/events-create")


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="ev-staff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def plain():
    return User.objects.create_user(username="ev-plain", password="pw-123456")


def test_model_validation():
    ev = Event(title="Backwards", start_date=date(2026, 4, 5), end_date=date(2026, 4, 4))
    with pytest.raises(ValidationError):
        ev.full_clean()
    ev = Event(title="Timed, no time", start_date=date(2026, 4, 5), all_day=False)
    with pytest.raises(ValidationError):
        ev.full_clean()
    ev = Event(title="Fine", start_date=date(2026, 4, 5), all_day=False, start_time=time(9), end_time=time(10))
    ev.full_clean()
    assert ev.last_day == date(2026, 4, 5)


def test_visibility_scoping_and_provider(staff, plain):
    mine = Event.objects.create(title="Private plan", start_date=date(2026, 4, 3), created_by=plain,
                                visibility=Event.Visibility.PRIVATE)
    theirs = Event.objects.create(title="Staff secret", start_date=date(2026, 4, 3), created_by=staff,
                                  visibility=Event.Visibility.PRIVATE)
    shared = Event.objects.create(title="Release day", start_date=date(2026, 4, 3), end_date=date(2026, 4, 4),
                                  category="Release", all_day=False, start_time=time(9, 30), end_time=time(17),
                                  created_by=staff, cancelled=True)
    assert set(visible_events(plain)) == {mine, shared}
    assert set(visible_events(staff)) == {mine, theirs, shared}
    assert not visible_events(None).exists()

    cal = get_calendar(EVENTS_KEY)
    assert cal is not None and cal.is_provider and cal.spec.access == "authenticated"

    class R:  # a request-shaped object with a user
        def __init__(self, user):
            self.user = user

    events = cal.events(date(2026, 4, 1), date(2026, 5, 1), R(plain))
    assert sorted(e.title for e in events) == ["Private plan", "Release day"]
    release = next(e for e in events if e.title == "Release day")
    assert release.all_day is False and release.start.hour == 9 and release.end.hour == 17
    assert release.start_date == date(2026, 4, 3) and release.end_date == date(2026, 4, 4)
    assert release.subtitle == "Release" and release.cancelled and release.url == shared.get_absolute_url()
    private = next(e for e in events if e.title == "Private plan")
    assert private.all_day is True and private.end is None
    # The dataset under the same key scopes identically.
    from apps.datasets.core import get_dataset

    ds = get_dataset(EVENTS_KEY)
    assert ds is not None and {r["title"] for r in ds.rows(request=R(plain))} == {"Private plan", "Release day"}


def test_html_create_stamps_author_and_shows_on_the_calendar(client, staff):
    resp = client.get(PAGE)
    assert CREATE in resp.content.decode()  # the Add event action
    resp = client.post(CREATE, {
        "title": "Office closed", "start_date": "2026-04-10", "end_date": "2026-04-11", "all_day": "on",
        "category": "Closure", "visibility": "members", "description": "", "location": "", "url": "",
    })
    assert resp.status_code == 302, resp.content[:500]
    ev = Event.objects.get(title="Office closed")
    assert ev.created_by == staff and ev.end_date == date(2026, 4, 11)
    resp = client.get(PAGE, {"ds": EVENTS_KEY, "month": "2026-04", "day": "2026-04-11"})
    html = resp.content.decode()
    assert "Office closed" in html and 'cal-day-group-title">Events' in html
    assert next(p for p in resp.context["picker"] if p["key"] == EVENTS_KEY)["count"] == 1
    # The entries page offers table, calendar and board.
    html = client.get(LIST).content.decode()
    assert "Office closed" in html and 'data-display="board"' in html and 'data-display="calendar"' in html
    assert client.get(LIST, {"display": "board", "range": "30", "from": "2026-04-01"}).status_code == 200


def test_edit_rights_author_or_staff(client, staff, plain):
    other = Event.objects.create(title="Theirs", start_date=date(2026, 4, 3), created_by=plain)
    assert client.get(reverse("calendar/events-update", kwargs={"pk": other.pk})).status_code == 200  # staff may
    client.logout()
    second = User.objects.create_user(username="ev-second", password="pw-123456")
    client.force_login(second)
    assert client.get(reverse("calendar/events-detail", kwargs={"pk": other.pk})).status_code == 200  # members-visible
    resp = client.post(reverse("calendar/events-update", kwargs={"pk": other.pk}), {
        "title": "Hijacked", "start_date": "2026-04-03", "all_day": "on", "visibility": "members",
    })
    assert resp.status_code == 403
    other.refresh_from_db()
    assert other.title == "Theirs"
    # Nor may they even open the edit form or the delete confirmation.
    assert client.get(reverse("calendar/events-update", kwargs={"pk": other.pk})).status_code == 403
    assert client.get(reverse("calendar/events-delete", kwargs={"pk": other.pk})).status_code == 403
    # REST update by a non-author is refused the same way.
    resp = client.patch(f"/smallstack/api/calendar/events/{other.pk}/", data=json.dumps({"title": "Nope"}),
                        content_type="application/json")
    assert resp.status_code in (403, 404)
    private = Event.objects.create(title="Hidden", start_date=date(2026, 4, 3), created_by=plain,
                                   visibility=Event.Visibility.PRIVATE)
    assert client.get(reverse("calendar/events-detail", kwargs={"pk": private.pk})).status_code == 404


def test_rest_and_mcp_create(client, staff):
    resp = client.post(
        "/smallstack/api/calendar/events/",
        data=json.dumps({"title": "Via REST", "start_date": "2026-05-01", "all_day": False, "start_time": "14:00",
                         "end_time": "15:30", "visibility": "members"}),
        content_type="application/json",
    )
    assert resp.status_code in (200, 201), resp.content
    ev = Event.objects.get(title="Via REST")
    assert ev.created_by == staff and ev.start_time == time(14)
    from apps.mcp.server import TOOL_HANDLERS, TOOL_REGISTRY, ToolContext, reset_context, set_context

    assert {"list_events", "create_event", "update_event", "delete_event"} <= set(TOOL_REGISTRY)
    token = set_context(ToolContext(user=staff, token=None))
    try:
        out = TOOL_HANDLERS["create_event"]({"title": "Via MCP", "start_date": "2026-05-02", "category": "Release"})
        assert out.get("title") == "Via MCP", out
        assert Event.objects.get(title="Via MCP").created_by == staff
        window = {"calendars": [EVENTS_KEY], "start": "2026-05-01", "end": "2026-06-01"}
        listed = TOOL_HANDLERS["calendar_events"](window)
        assert {r["title"] for r in listed["results"]} == {"Via REST", "Via MCP"}
    finally:
        reset_context(token)


def test_day_selection_swaps_in_place(client, staff):
    """The page and the board display mark the two swap regions and load the
    script that fetches a day link and replaces only those regions."""
    html = client.get(PAGE, {"ds": EVENTS_KEY, "month": "2026-04"}).content.decode()
    assert 'data-cal-region="main"' in html and 'data-cal-region="day"' in html
    assert "calendar/js/calendar.js" in html
    # The fetched day URL is the same page, so the regions are there to swap.
    html = client.get(PAGE, {"ds": EVENTS_KEY, "month": "2026-04", "day": "2026-04-10"}).content.decode()
    assert html.count('data-cal-region="day"') == 1 and "April 10" in html
    html = client.get(LIST, {"display": "board", "range": "30", "from": "2026-04-01"}).content.decode()
    assert 'data-cal-region="main"' in html and 'data-cal-region="day"' in html
    assert "calendar/js/calendar.js" in html


def test_entry_pages_use_the_calendar_templates(client, staff):
    """The entries pages are the calendar's own: an agenda with a leaf per
    entry, a grouped form, a leaf-led detail page, a real delete page."""
    ev = Event.objects.create(title="Vendor visit", start_date=date(2026, 4, 3), end_date=date(2026, 4, 5),
                              category="People", location="Boardroom", all_day=False, start_time=time(14),
                              end_time=time(15, 30), created_by=staff)
    html = client.get(LIST).content.decode()
    assert 'class="cal-agenda-row' in html and 'class="cal-leaf' in html
    assert "April 2026" in html and "2:00 pm to 3:30 pm" in html and ">Boardroom<" in html
    assert 'data-display="agenda"' in html and "<table" not in html.split('id="crud-list-content"')[1]
    # the form: labels above fields, grouped by question
    html = client.get(CREATE).content.decode()
    assert 'class="cal-form"' in html and ">What<" in html and ">When<" in html and ">Details<" in html
    assert ">Add to calendar<" in html and "cal-times" in html
    html = client.get(reverse("calendar/events-update", kwargs={"pk": ev.pk})).content.decode()
    assert ">Save changes<" in html and 'value="Vendor visit"' in html
    # the detail page leads with the leaf and the long date
    html = client.get(reverse("calendar/events-detail", kwargs={"pk": ev.pk})).content.decode()
    assert "cal-leaf--lg" in html and "Friday, April 3, 2026 to Sunday, April 5, 2026" in html
    assert "2:00 pm to 3:30 pm" in html and ">Show on calendar<" in html and "ds=smallstack_events" in html
    assert ">Where<" in html and ">Boardroom<" in html


def test_delete_page_renders_and_deletes(client, staff):
    """Regression: the delete view's bare Form used to be handed ``user`` and
    crash with a TypeError; it now renders the confirmation and deletes."""
    ev = Event.objects.create(title="Mistake", start_date=date(2026, 4, 3), created_by=staff)
    url = reverse("calendar/events-delete", kwargs={"pk": ev.pk})
    html = client.get(url).content.decode()
    assert ">Delete event<" in html and ">Keep it<" in html and "Mistake" in html
    resp = client.post(url)
    assert resp.status_code in (302, 200)
    assert not Event.objects.filter(pk=ev.pk).exists()
