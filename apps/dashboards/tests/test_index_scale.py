"""The dashboards overview at size: a few of each, links to the paged lists,
and a cost that doesn't grow with the number of dashboards, reports or
playlists."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.dashboards.models import Dashboard, Playlist, Report

pytestmark = pytest.mark.django_db

INDEX = "/smallstack/dashboards/"
GOALS = "/smallstack/goals/"


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("ix-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def _make(n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        Dashboard(name=f"Board {i:03d}", slug=f"board-{i:03d}").save()
        Report(name=f"Report {i:03d}", slug=f"report-{i:03d}").save()
        Playlist(name=f"Playlist {i:03d}", slug=f"pl-{i:03d}", items=[f"board-{i:03d}"]).save()


def _queries(client, url: str = INDEX) -> int:
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(url).status_code == 200
    return len(ctx.captured_queries)


@pytest.mark.parametrize("url", [INDEX, GOALS])
def test_the_overviews_cost_the_same_at_ten_or_forty(client, staff, url):
    _make(10)
    client.get(url)  # warm-up: a first-request hook (one a downstream adds, say) isn't the page's cost
    small = _queries(client, url)
    _make(30, start=10)
    assert _queries(client, url) == small


def test_each_section_shows_a_few_and_links_to_the_rest(client, staff):
    _make(30)
    html = client.get(INDEX).content.decode()
    assert html.count('class="ix-board" href=') == 8 and "30, 8 most recently changed" in html
    assert 'href="/smallstack/dashboards/boards/" class="md-link">All 30 dashboards' in html
    assert 'href="/smallstack/dashboards/playlists/" class="md-link">All 30 playlists' in html
    goals = client.get(GOALS).content.decode()  # reports live in the Goals area
    assert 'href="/smallstack/dashboards/reports/" class="md-link">All 30 reports' in goals
    reports = goals[goals.index('id="ix-report-title"') :]
    assert reports.count("?format=csv") == 8
    # Most recently changed first.
    assert html.index("Board 029") < html.index("Board 028")


def test_dashboards_as_a_list(client, staff):
    _make(30)
    html = client.get(INDEX + "?boards=list").content.decode()
    section = html[html.index('id="ix-dash-section"') : html.index('id="ix-playlist-title"')]
    assert section.count('class="ix-board-list-pic"') == 20 and 'class="ix-board" href=' not in section
    assert 'aria-current="true" hx-get="?boards=list"' in section


def test_small_counts_need_no_all_link(client, staff):
    _make(3)
    html = client.get(INDEX).content.decode()
    assert "All 3 dashboards" not in html and html.count('class="ix-board" href=') == 3


def test_the_overview_tables_sort_on_their_own_and_resize(client, staff):
    from apps.dashboards.models import Component, Metric

    Metric(key="ix_m", name="Requests", dataset="smallstack_requests").save()
    Dashboard(name="zed", slug="zed", layout=[{"type": "text", "options": {"markdown": "x"}}]).save()
    Dashboard(name="Alpha", slug="alpha").save()
    Playlist(name="zebra", slug="zebra", items=["zed"], seconds=300).save()
    Playlist(name="Apple", slug="apple", items=["alpha"], seconds=5).save()
    Component(name="zoom", type="metric", metric="ix_m").save()
    Component(name="Note", type="text", options={"markdown": "x"}).save()

    def page(query: str = "") -> str:
        return client.get(f"{INDEX}?{query}").content.decode()

    def in_order(html: str, first: str, second: str) -> bool:
        return html.index(first) < html.index(second)

    listed = page("boards=list")
    for key in (
        "boards:picture,name,cards,opens,updated_at",
        "playlists:slides,name,round,updated_at",
        "components:name,type,metric,updated_at",
    ):
        assert f'data-table-key="dashboards/overview-{key}"' in listed, key
    assert listed.count('class="col-resizer"') == 13 and listed.count('hx-select="#dx-page"') >= 11

    assert in_order(page("boards=list&dash=name"), 'class="gx-name">Alpha<', 'class="gx-name">zed<')  # ignoring case
    assert in_order(page("boards=list&dash=-cards"), 'class="gx-name">zed<', 'class="gx-name">Alpha<')
    assert in_order(page("playlists=name"), 'class="gx-name">Apple<', 'class="gx-name">zebra<')
    assert in_order(page("playlists=-round"), 'class="gx-name">zebra<', 'class="gx-name">Apple<')  # 5 min, then 5 s
    assert in_order(page("components=name"), 'class="gx-name">Note<', 'class="gx-name">zoom<')
    assert in_order(page("components=type"), 'class="gx-name">Note<', 'class="gx-name">zoom<')  # Note, Single stat

    # The cards view sorts with a select, and keeps the other tables' sorts.
    cards = page("dash=name&playlists=name")
    assert 'id="dx-sort"' in cards and '<option value="name" selected>' in cards
    assert in_order(cards, 'class="ix-board-name">Alpha<', 'class="ix-board-name">zed<')
    assert '<input type="hidden" name="playlists" value="name">' in cards
    assert "dash=name" in cards[cards.index('id="ix-comp-section"') :]
    # Cards leaves the list view: an empty querystring must not mean "this URL".
    assert 'href="/smallstack/dashboards/" class="ix-view-btn"' in page("boards=list")
    assert page("dash=bogus&playlists=bogus&components=bogus")


def test_the_overview_only_links_cards_you_can_open(client, staff):
    """Staff see someone's personal card, but its page is a builder they can't use."""
    from apps.dashboards.models import Component, Metric

    other = get_user_model().objects.create_user("ix-other", password="x")
    Metric(key="ix_p", name="Theirs", dataset="smallstack_requests", owner=other).save()
    card = Component(name="Their card", type="metric", metric="ix_p", owner=other)
    card.save()
    Component(name="Shared note", type="text", options={"markdown": "x"}).save()
    html = client.get(INDEX).content.decode()
    assert f'href="{card.get_absolute_url()}"' not in html and 'class="gx-name-plain">Their card<' in html
    assert 'class="gx-name">Shared note<' in html
    assert client.get(card.get_absolute_url()).status_code == 403  # why it isn't a link
