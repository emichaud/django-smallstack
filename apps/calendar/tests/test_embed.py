"""A calendar on any page: ``{% calendar_card %}``, the embed fragment
endpoint, the upcoming list, and the ``calendar`` dashboard card.

The shape mirrors the dashboards app's embed tests: the tag emits nothing
for a viewer who may see none of the calendars (a page never reveals one
exists), navigation links point back at the fragment so a card navigates in
place, and the dashboard card goes through the registry like any plugin type.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.calendar.core import CalendarEvent
from apps.calendar.embed import build_upcoming, calendar_embed, embed_url, split_keys
from apps.calendar.models import Event, SavedCalendarView
from apps.heartbeat.models import MaintenanceWindow

pytestmark = pytest.mark.django_db

User = get_user_model()
EMBED = reverse("calendar_embed")
MW = "smallstack_maintenance_windows"  # bundled, staff-only
EV = "smallstack_events"  # bundled, access="authenticated"
APP = Path(__file__).resolve().parent.parent


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="emb-staff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def member(client):
    user = User.objects.create_user(username="emb-member", password="pw-123456")
    client.force_login(user)
    return user


@pytest.fixture
def soon():
    """Two events in the coming week and one maintenance window tonight."""
    today = timezone.localdate()
    a = Event.objects.create(title="Vendor visit", start_date=today + timedelta(days=1), all_day=True)
    b = Event.objects.create(
        title="Release call",
        start_date=today + timedelta(days=3),
        end_date=today + timedelta(days=4),
        all_day=False,
        start_time=datetime(2000, 1, 1, 14, 0).time(),
    )
    now = datetime.combine(today, datetime.min.time(), tzinfo=dt_tz.utc) + timedelta(hours=23)
    MaintenanceWindow.objects.create(monitor_key="site", title="Patch window", start=now, end=now + timedelta(hours=2))
    return a, b


def _render(user, source: str) -> str:
    request = RequestFactory().get("/host/page/")
    request.user = user
    return Template("{% load calendar_tags %}" + source).render(Context({"request": request}))


# -- the tag ---------------------------------------------------------------


def test_calendar_card_renders_a_lazy_shell_the_fragment_fills(staff):
    html = _render(staff, '{% calendar_card "' + EV + "," + MW + '" %}')
    assert 'class="cal-embed cal-embed--month"' in html
    assert "calendar/css/calendar.css" in html
    # The body loads the fragment over htmx with the state baked into its URL.
    assert f'hx-get="{EMBED}?ds={EV}&amp;ds={MW}&amp;mode=month"' in html
    assert 'hx-trigger="load"' in html and "Loading…" in html
    # The default heading is the calendars' label, linking to the page on them.
    assert ">2 calendars</a>" in html and f'href="{reverse("calendar_index")}?ds={EV}&amp;ds={MW}"' in html


def test_calendar_card_takes_a_title_mode_and_sizes(staff, soon):
    html = _render(staff, '{% calendar_card "' + EV + '" mode="upcoming" days=7 limit=3 title="Soon" lazy=False %}')
    assert ">Soon</a>" in html and "cal-embed--upcoming" in html
    # Rendered now: the fragment is inline, nothing left to load.
    assert "hx-trigger" not in html and "Loading…" not in html
    assert 'hx-boost="true"' in html and "Vendor visit" in html and "Release call" in html
    assert "Next 7 days" in html
    # A screen-reader-only heading when title=False.
    html = _render(staff, '{% calendar_card "' + EV + '" title=False %}')
    assert 'class="sr-only">Events</h2>' in html


def test_calendar_card_accepts_a_saved_view_and_a_list(staff):
    view = SavedCalendarView.objects.create(owner=staff, name="Ops", datasets=[MW, EV])
    request = RequestFactory().get("/")
    request.user = staff
    html = Template("{% load calendar_tags %}{% calendar_card view mode='board' %}").render(
        Context({"request": request, "view": view})
    )
    assert f"ds={MW}&amp;ds={EV}&amp;mode=board" in html
    assert split_keys([EV, " ", MW, EV]) == [EV, MW]
    assert split_keys(f"{EV}, {MW},,") == [EV, MW]


def test_calendar_card_renders_nothing_for_who_may_not_see(member):
    # A member may not see the staff-only maintenance calendar …
    assert _render(member, '{% calendar_card "' + MW + '" %}').strip() == ""
    # … nor an unknown key — the two are indistinguishable.
    assert _render(member, '{% calendar_card "no_such_calendar" %}').strip() == ""
    # … but a calendar open to every signed-in user renders.
    assert "cal-embed" in _render(member, '{% calendar_card "' + EV + '" %}')
    # Anonymous: nothing, ever. No request: nothing.
    assert _render(AnonymousUser(), '{% calendar_card "' + EV + '" %}').strip() == ""
    assert Template("{% load calendar_tags %}{% calendar_card 'x' %}").render(Context({})).strip() == ""
    # Mixed: the forbidden key is dropped, the visible one stays.
    html = _render(member, '{% calendar_card "' + MW + "," + EV + '" %}')
    assert f"ds={EV}&amp;mode" in html and MW not in html


# -- the fragment endpoint -------------------------------------------------


def test_embed_requires_login(client):
    resp = client.get(EMBED, {"ds": EV})
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_embed_month_navigates_in_place(client, staff, soon):
    resp = client.get(EMBED, {"ds": [EV, MW], "mode": "month", "month": "2026-04"})
    assert resp.status_code == 200
    html = resp.content.decode()
    # A bare fragment (no page chrome) whose wrapper boosts its own links.
    assert not html.lstrip().startswith("<!DOCTYPE") and "<html" not in html
    assert 'hx-boost="true" hx-target="this" hx-swap="outerHTML" hx-push-url="false"' in html
    assert "April 2026" in html
    # Month arrows point back at the fragment with the calendars kept.
    prev = re.search(r'href="([^"]+)" class="calendar-nav-btn" aria-label="Previous month"', html)
    nxt = re.search(r'href="([^"]+)" class="calendar-nav-btn" aria-label="Next month"', html)
    assert prev and nxt
    assert prev.group(1).startswith(EMBED) and "month=2026-03" in prev.group(1) and f"ds={EV}" in prev.group(1)
    assert "month=2026-05" in nxt.group(1)
    # Day cells link to the fragment too; selecting one lists the day beneath the grid.
    cell = re.search(r'href="([^"]+)" class="calendar-cell cal-cell', html)
    assert cell and cell.group(1).startswith(EMBED) and "day=2026-" in cell.group(1)
    assert "cal-embed-day" not in html
    resp = client.get(EMBED, {"ds": EV, "month": "2026-04", "day": "2026-04-15"})
    assert "cal-embed-day" in resp.content.decode() and "Wednesday, April 15" in resp.content.decode()
    # "Open in Calendar" leaves the embed for the page, unboosted.
    assert f'href="{reverse("calendar_index")}?ds={EV}&amp;ds={MW}&amp;month=2026-04" hx-boost="false"' in html


def test_embed_board_and_upcoming_modes(client, staff, soon):
    resp = client.get(EMBED, {"ds": [EV, MW], "mode": "board", "days": "60"})
    html = resp.content.decode()
    assert "cal-display-board" in html and "60 days" in html
    # The board's own toolbar links stay inside the fragment.
    assert re.search(r'href="' + re.escape(EMBED) + r'[^"]*range=90[^"]*" class="cal-seg-btn', html)
    resp = client.get(EMBED, {"ds": [EV, MW], "mode": "upcoming", "days": "7", "limit": "2"})
    html = resp.content.decode()
    assert "cal-upcoming" in html and "Next 7 days" in html
    assert "Patch window" in html and "Vendor visit" in html
    assert "Release call" not in html and "+1 more" in html
    # An event's own link opens its page, never the fragment.
    assert re.search(r'<a href="/smallstack/calendar/events/\d+/" hx-boost="false">Vendor visit</a>', html)
    # A bad mode is the month; bad sizes fall back to the defaults.
    resp = client.get(EMBED, {"ds": EV, "mode": "sideways", "days": "zillions"})
    assert "calendar-nav-btn" in resp.content.decode()


def test_embed_with_nothing_visible_is_an_empty_state_not_a_404(client, member):
    resp = client.get(EMBED, {"ds": MW})
    assert resp.status_code == 200 and "No calendars you can see" in resp.content.decode()
    resp = client.get(EMBED, {"ds": "nope"})
    assert resp.status_code == 200 and "No calendars you can see" in resp.content.decode()


def test_timed_entry_ending_on_a_date_renders(client, staff):
    """A timed start with an end *date* (no end time) used to 500 both the
    page's day column and the upcoming list: ``date`` cannot be formatted
    with ``H:i``. ``CalendarEvent.timed_end`` guards it."""
    today = timezone.localdate()
    Event.objects.create(
        title="Vendor visit",
        start_date=today,
        end_date=today + timedelta(days=1),
        all_day=False,
        start_time=datetime(2000, 1, 1, 14, 0).time(),
    )
    resp = client.get(EMBED, {"ds": EV, "mode": "upcoming"})
    assert resp.status_code == 200 and "14:00" in resp.content.decode()
    resp = client.get(reverse("calendar_index"), {"ds": EV, "day": today.isoformat()})
    assert resp.status_code == 200 and "14:00" in resp.content.decode()
    ev = CalendarEvent.make("x", 1, "t", datetime(2026, 1, 1, 9, tzinfo=dt_tz.utc), date(2026, 1, 2))
    assert ev.timed_end is False and not ev.all_day


# -- the service -----------------------------------------------------------


def test_calendar_embed_and_upcoming_builder(staff):
    request = RequestFactory().get("/")
    request.user = staff
    embed = calendar_embed(request, f"{EV},bogus", mode="upcoming", days=3)
    assert embed is not None and embed["keys"] == [EV] and embed["html"] is None
    assert embed["url"] == embed_url([EV], "upcoming", days=3) == f"{EMBED}?ds={EV}&mode=upcoming&days=3"
    assert embed_url([EV], "month", weekends=False, month=date(2026, 4, 1)) == (
        f"{EMBED}?ds={EV}&mode=month&weekends=0&month=2026-04-01"
    )
    request.user = AnonymousUser()
    assert calendar_embed(request, EV) is None

    today = date(2026, 4, 1)
    mk = lambda i, d: CalendarEvent.make("c", i, f"e{i}", d)  # noqa: E731
    events = [mk(1, date(2026, 3, 30)), mk(2, today), mk(3, today), mk(4, date(2026, 4, 2)), mk(5, date(2026, 4, 9))]
    up = build_upcoming(events, today, today + timedelta(days=14), today, limit=3)
    # A span under way lists on the window's first day; the limit counts rows.
    assert [d["label"] for d in up["days"]] == ["Today"] and up["shown"] == 3 and up["more"] == 2
    up = build_upcoming(events[3:], today, today + timedelta(days=14), today, limit=10)
    assert [d["label"] for d in up["days"]] == ["Tomorrow", "Thu 9 Apr"]


# -- the dashboard card ----------------------------------------------------


@pytest.fixture
def dashboards():
    return pytest.importorskip("apps.dashboards.components")


def test_calendar_card_is_a_registered_dashboard_card_type(dashboards):
    ct = dashboards.get_component_type("calendar")
    assert ct is not None and ct.group == "Info" and ct.media == {"css": ["calendar/css/calendar.css"]}
    described = {t["type"]: t for t in dashboards.describe_types()}["calendar"]
    assert [o["name"] for o in described["options"]] == ["calendars", "mode", "days", "limit"]
    # Validation: keys must exist, the mode and sizes must be in range.
    bad = {"id": "a", "type": "calendar", "x": 0, "y": 0, "w": 4, "h": 4, "options": {"calendars": "", "mode": "x"}}
    assert any("'calendars'" in p for p in ct.validate(bad)) and any("'mode'" in p for p in ct.validate(bad))
    bad["options"] = {"calendars": f"{EV},ghost", "days": 0, "limit": 999}
    problems = ct.validate(bad)
    assert any("ghost" in p for p in problems) and any("'days'" in p for p in problems)
    assert any("'limit'" in p for p in problems)
    assert ct.validate({**bad, "options": {"calendars": EV, "mode": "month", "days": 14, "limit": 8}}) == []


def test_calendar_card_offers_the_calendars_you_may_see_rather_than_a_box_to_type_keys(dashboards, staff, member):
    def calendars(user):
        described = {t["type"]: t for t in dashboards.describe_types(user)}["calendar"]
        option = described["options"][0]
        assert option["name"] == "calendars" and option["type"] == "multichoice" and option["required"]
        return dict(option["choices"])

    assert calendars(staff)[EV] == "Events" and MW in calendars(staff)
    assert EV in calendars(member) and MW not in calendars(member)  # staff-only: not offered
    assert calendars(None) == {}  # nobody asking, nothing listed


def test_calendar_card_renders_through_the_registry(dashboards, staff, member, soon):
    from apps.dashboards.boards import render_cell
    from apps.dashboards.components import normalize_layout
    from apps.dashboards.metrics import request_for
    from apps.dashboards.models import Dashboard

    cell = {
        "id": "cal",
        "type": "calendar",
        "x": 0,
        "y": 0,
        "w": 4,
        "h": 4,
        "title": "Whats on",
        "options": {"calendars": f"{MW},{EV}", "mode": "upcoming", "days": 7},
    }
    layout, problems = normalize_layout([cell])
    assert problems == [], problems
    html = render_cell(Dashboard(name="x", slug="x"), layout[0], request_for(staff), None)
    assert "cal-embed--cell" in html and ">Whats on</a>" in html
    assert "Patch window" in html and "Vendor visit" in html
    # A member sees only the calendar they may: the maintenance window is gone.
    html = render_cell(Dashboard(name="x", slug="x"), layout[0], request_for(member), None)
    assert "Vendor visit" in html and "Patch window" not in html
    # None visible → the restricted card, not an empty box.
    layout[0]["options"]["calendars"] = MW
    html = render_cell(Dashboard(name="x", slug="x"), layout[0], request_for(member), None)
    assert "You don't have access to this card's calendars" in html and "cal-upcoming" not in html


# -- hygiene ---------------------------------------------------------------


_EMBED_TEMPLATES = sorted(
    p for sub in ("components", "includes", "cells") for p in (APP / "templates" / "calendar" / sub).rglob("*.html")
)


@pytest.mark.parametrize("path", _EMBED_TEMPLATES, ids=lambda p: str(p.relative_to(APP / "templates")))
def test_embed_templates_have_no_inline_javascript(path: Path) -> None:
    """The CSP's script-src is 'self' with no 'unsafe-inline': an embed lands
    on pages that never load the calendar's script, so its behaviour is htmx
    attributes only — never a handler or an inline block."""
    html = path.read_text()
    handlers = re.findall(r"\son[a-z]+\s*=\s*\"", html)
    assert not handlers, f"inline event handler(s) {handlers}"
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag or "application/json" in tag, f"inline <script> block: {tag}"
