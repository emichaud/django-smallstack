"""Dashboard playlists: the model rules, the slides a viewer gets, what a link
asks the player to do, and the surfaces built on them (page, slide fragment,
REST, MCP, ``{% playlist %}``)."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import RequestFactory

from apps.dashboards.models import ADMIN_HOME_KEY, Dashboard, Playlist
from apps.dashboards.playlists import normalize_items, player_options, playlist_payload, playlist_slides

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def staff():
    return User.objects.create_user("pl-staff", password="x", is_staff=True)


@pytest.fixture
def member():
    return User.objects.create_user("pl-member", password="x")


def _board(slug: str, owner=None, **kw) -> Dashboard:
    d = Dashboard(name=kw.pop("name", slug.replace("-", " ").title()), slug=slug, owner=owner, **kw)
    d.save()
    return d


def _playlist(items, owner=None, **kw) -> Playlist:
    p = Playlist(name=kw.pop("name", "Wall"), slug=kw.pop("slug", "wall"), owner=owner, items=items, **kw)
    p.save()
    return p


# -- the rules ---------------------------------------------------------------------


def test_items_are_tidied_and_checked(member):
    _board("ops")
    mine = _board("mine", owner=member)
    items, problems = normalize_items(
        ["ops", {"dashboard": "mine", "seconds": "45", "period": "last_7"}], owner_id=member.pk
    )
    assert problems == [] and items == [
        {"dashboard": "ops"},
        {"dashboard": mine.slug, "seconds": 45, "period": "last_7"},
    ]


@pytest.mark.parametrize(
    ("item", "problem"),
    [
        ({"dashboard": "ghost"}, "no dashboard 'ghost'"),
        ({"dashboard": "ops", "colour": "red"}, "unknown key(s) colour"),
        ({"dashboard": "ops", "seconds": 2}, "between 5 and 3600"),
        ({"dashboard": "ops", "seconds": True}, "whole number"),
        ({"dashboard": "ops", "period": "fortnight"}, "not a known period"),
        (7, "must be a dashboard slug or an object"),
    ],
)
def test_bad_items_are_refused(item, problem):
    _board("ops")
    _items, problems = normalize_items([item], owner_id=None)
    assert any(problem in p for p in problems), problems


def test_a_shared_playlist_cant_carry_a_personal_dashboard(member, staff):
    _board("mine", owner=member)
    with pytest.raises(ValidationError, match="personal dashboard"):
        _playlist(["mine"])  # shared
    with pytest.raises(ValidationError, match="personal dashboard"):
        _playlist(["mine"], owner=staff)  # someone else's
    assert _playlist(["mine"], owner=member).items == [{"dashboard": "mine"}]


def test_items_have_a_ceiling():
    _board("ops")
    _items, problems = normalize_items(["ops"] * 51, owner_id=None)
    assert problems == ["a playlist holds at most 50 dashboards"]


# -- what a viewer gets ------------------------------------------------------------


def test_slides_skip_what_the_viewer_cant_open(member, staff):
    from apps.dashboards.boards import system_dashboard

    _board("ops", default_period="mtd")
    home = system_dashboard(ADMIN_HOME_KEY, name="SmallStack")  # staff-only
    p = _playlist([{"dashboard": "ops", "period": "last_7", "seconds": 12}, home.slug], seconds=40)

    member_slides = playlist_slides(p, member)
    assert [s["slug"] for s in member_slides] == ["ops"]
    assert (
        member_slides[0]["seconds"] == 12 and member_slides[0]["url"] == "/smallstack/dashboards/d/ops/?period=last_7"
    )
    staff_slides = playlist_slides(p, staff)
    assert [s["position"] for s in staff_slides] == [1, 2] and staff_slides[1]["seconds"] == 40
    assert staff_slides[1]["url"] == "/smallstack/"


def test_link_options():
    p = Playlist(seconds=30, loop=True, auto_start=False)
    assert player_options({}, p, 3) == {"start": 0, "play": False, "loop": True, "seconds": None, "kiosk": False}
    got = player_options({"slide": "9", "play": "1", "seconds": "2", "loop": "0", "kiosk": "1"}, p, 3)
    assert got == {"start": 2, "play": True, "loop": False, "seconds": 5, "kiosk": True}  # clamped
    assert player_options({"slide": "nope", "seconds": "99999"}, p, 3)["seconds"] == 3600
    p.auto_start = True
    assert player_options({}, p, 3)["play"] is True
    assert player_options({"play": "0"}, p, 3)["play"] is False
    assert player_options({"play": "1"}, p, 1)["play"] is False  # nothing to rotate


# -- the player page and its slides ------------------------------------------------


def test_the_player_page_renders_the_starting_slide(client, staff):
    _board("ops", layout=[{"id": "n", "type": "text", "x": 0, "y": 0, "w": 3, "h": 2, "options": {"markdown": "hi"}}])
    _board("sales")
    _playlist(["ops", "sales"], auto_start=True)
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/p/wall/?slide=2&seconds=20").content.decode()
    assert 'data-playlist="wall"' in html and 'data-start="1"' in html and 'data-play="1"' in html
    assert 'data-seconds="20"' in html and "data-sync-url" in html
    assert 'data-slide-url="/smallstack/dashboards/p/wall/slides/0/"' in html
    assert "<b data-pl-pos>2</b> of 2" in html and ">Sales</a>" in html
    # Works without JavaScript: the controls are links, and the options survive.
    assert 'href="?slide=1&amp;seconds=20"' in html


def test_the_slide_fragment(client, staff):
    _board("ops", layout=[{"id": "n", "type": "text", "x": 0, "y": 0, "w": 3, "h": 2, "options": {"markdown": "hi"}}])
    _playlist(["ops"])
    client.force_login(staff)
    body = client.get("/smallstack/dashboards/p/wall/slides/1/").content.decode()
    assert 'class="pl-slide" data-position="1"' in body and "/smallstack/dashboards/d/ops/cells/n/" in body
    assert client.get("/smallstack/dashboards/p/wall/slides/2/").status_code == 404
    assert client.get("/smallstack/dashboards/p/wall/slides/0/").status_code == 404


def test_kiosk_drops_the_chrome(client, staff):
    _board("ops")
    _playlist(["ops"])
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/p/wall/?kiosk=1").content.decode()
    assert 'data-sidebar-state="disabled"' in html and "pl-kiosk" in html
    assert "page-header-bleed" not in html and "Exit wall screen" in html
    assert "Wall screen" in client.get("/smallstack/dashboards/p/wall/").content.decode()


def test_a_personal_playlist_is_private(client, member, staff):
    _board("ops")
    _playlist(["ops"], owner=staff)
    client.force_login(member)
    assert client.get("/smallstack/dashboards/p/wall/").status_code == 404
    assert client.get("/smallstack/dashboards/p/wall/slides/1/").status_code == 404


def test_an_empty_playlist_explains_itself(client, member):
    _playlist([])
    client.force_login(member)
    assert "has no dashboards yet" in client.get("/smallstack/dashboards/p/wall/").content.decode()


# -- following its dashboards -----------------------------------------------------


def test_a_renamed_dashboard_is_renamed_in_playlists_and_a_deleted_one_leaves():
    ops = _board("ops")
    _board("sales")
    p = _playlist(["ops", {"dashboard": "sales", "seconds": 9}])
    ops.slug = "operations"
    ops.save()
    p.refresh_from_db()
    assert p.items == [{"dashboard": "operations"}, {"dashboard": "sales", "seconds": 9}]
    ops.delete()
    p.refresh_from_db()
    assert p.items == [{"dashboard": "sales", "seconds": 9}]


# -- REST, MCP, the tag, the list --------------------------------------------------


def test_rest_creates_one_and_reads_its_slides(client, staff):
    _board("ops")
    client.force_login(staff)
    response = client.post(
        "/smallstack/api/dashboards/playlists/",
        data=json.dumps({"name": "Wall", "slug": "wall", "items": ["ops"], "seconds": 20, "visibility": "shared"}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert response.json()["items"] == [{"dashboard": "ops"}]
    out = client.get("/smallstack/dashboards/api/playlists/wall/slides/").json()
    assert out["url"] == "/smallstack/dashboards/p/wall/"
    assert out["slides"] == [
        {
            "position": 1,
            "kind": "dashboard",
            "slug": "ops",
            "name": "Ops",
            "seconds": 20,
            "period": None,
            "url": "/smallstack/dashboards/d/ops/",
        }
    ]
    bad = client.post(
        "/smallstack/api/dashboards/playlists/",
        data=json.dumps({"name": "X", "slug": "x", "items": ["ghost"]}),
        content_type="application/json",
    )
    assert bad.status_code == 400 and "ghost" in json.dumps(bad.json())


def test_mcp_builds_and_reads_a_playlist(staff):
    from apps.dashboards.tests.test_dashboards import _call

    _board("ops")
    _call(
        "create_playlist",
        {"name": "Wall", "slug": "wall", "items": [{"dashboard": "ops"}], "visibility": "shared"},
        staff,
    )
    out = _call("playlist_slides", {"playlist": "wall"}, staff)
    assert [s["slug"] for s in out["slides"]] == ["ops"]
    assert "error" in _call("playlist_slides", {"playlist": "ghost"}, staff)
    assert playlist_payload(Playlist.objects.get(slug="wall"), staff) == out


def test_the_tag_embeds_a_player_without_taking_over_the_address(staff, member):
    _board("ops")
    _board("sales")
    _playlist(["ops", "sales"], owner=staff)
    request = RequestFactory().get("/somewhere/")
    request.user = staff
    html = Template('{% load dashboard_tags %}{% playlist "wall" play=True seconds=15 %}').render(
        Context({"request": request})
    )
    assert 'data-playlist="wall"' in html and 'data-play="1"' in html and 'data-seconds="15"' in html
    assert "data-sync-url" not in html
    assert 'href="/smallstack/dashboards/p/wall/?slide=2&amp;seconds=15"' in html  # links go to the playlist page
    request.user = member
    assert "data-playlist" not in Template('{% load dashboard_tags %}{% playlist "wall" %}').render(
        Context({"request": request})
    )


def test_the_list_offers_play(client, staff):
    _board("ops")
    _playlist(["ops"], auto_start=True)
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/playlists/").content.decode()
    assert 'href="/smallstack/dashboards/p/wall/?play=1"' in html and "plays on open" in html


def test_dashboards_has_a_submenu(client, member):
    client.force_login(member)
    html = client.get("/smallstack/dashboards/").content.decode()
    for href in (
        "/smallstack/dashboards/mine/",
        "/smallstack/dashboards/components/",
        "/smallstack/dashboards/playlists/",
        "/smallstack/goals/",
        "/smallstack/dashboards/metrics/",
        "/smallstack/dashboards/goals/",
        "/smallstack/dashboards/reports/",
    ):
        assert f'href="{href}"' in html


def test_the_dashboards_index_lists_playlists(client, member, staff):
    _board("ops")
    _board("sales")
    _playlist(["ops", {"dashboard": "sales", "seconds": 45}], seconds=30)
    _playlist(["ops"], owner=staff, name="Staff only", slug="staff-only")
    client.force_login(member)
    html = client.get("/smallstack/dashboards/").content.decode()
    section = html[html.index('id="ix-playlist-title"') : html.index('id="ix-comp-title"')]
    assert "Wall" in section and "2 slides, about 1 min 15 s a round, loops" in section
    assert 'href="/smallstack/dashboards/p/wall/?play=1"' in section
    assert "Staff only" not in section  # someone else's personal playlist
    assert section.count('class="pll-frame"') == 2


def test_every_dashboards_list_pages_15_with_a_size_choice(client, staff):
    for i in range(20):
        _board(f"b-{i:02d}")
    _playlist(["b-00"])
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/boards/").content.decode()
    assert html.count('<td class="bl-pic-cell">') == 15 and '<option value="15" selected>' in html
    wide = client.get("/smallstack/dashboards/boards/?per_page=25").content.decode()
    assert wide.count('<td class="bl-pic-cell">') == 20 and '<option value="25" selected>' in wide
    for url in ("playlists", "metrics", "reports"):
        lists = client.get(f"/smallstack/dashboards/{url}/")
        assert lists.context["per_page"] == 15 and lists.context["page_sizes"] == (15, 25, 50, 100), url


def test_the_metrics_list_pages_and_keeps_its_size_control(client, staff):
    from apps.dashboards.models import Metric

    for i in range(18):
        Metric(key=f"pm_{i:02d}", name=f"Paged metric {i:02d}", dataset="smallstack_requests").save()
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/metrics/").content.decode()
    assert "Showing 1&ndash;15 of 18" in html and '<option value="15" selected>' in html
    wide = client.get("/smallstack/dashboards/metrics/?per_page=25").content.decode()
    assert "Showing 1&ndash;18 of 18" in wide and 'name="per_page"' in wide  # one page, control kept


def test_the_playlists_list_is_a_sortable_resizable_table(client, staff):
    _board("ops")
    _playlist(["ops"], name="Bravo", slug="bravo", seconds=60)
    _playlist(["ops"], name="Alpha", slug="alpha", seconds=10)
    _playlist(["ops"], name="Charlie", slug="charlie", seconds=30)
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/playlists/").content.decode()
    assert 'class="crud-table pll-table" data-table-key="dashboards/playlists:' in html
    assert html.count('class="col-resizer"') == 5  # every column but the actions
    assert 'data-field="name"' in html and "ordering=name" in html and 'hx-target="#crud-list-content"' in html

    def order(query: str) -> list[str]:
        page = client.get(f"/smallstack/dashboards/playlists/?{query}").content.decode()
        return sorted(("Alpha", "Bravo", "Charlie"), key=lambda n: page.index(f'class="pll-name">{n}<'))

    assert order("ordering=name") == ["Alpha", "Bravo", "Charlie"]
    assert order("ordering=-name") == ["Charlie", "Bravo", "Alpha"]
    assert order("ordering=seconds") == ["Alpha", "Charlie", "Bravo"]
    assert order("ordering=-seconds") == ["Bravo", "Charlie", "Alpha"]
    sorted_page = client.get("/smallstack/dashboards/playlists/?ordering=-seconds").content.decode()
    assert 'aria-sort="descending"' in sorted_page


def test_the_form_lays_slides_out_as_a_sortable_resizable_table(client, staff):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/playlists/new/").content.decode()
    assert 'data-table-key="dashboards/playlist-form:name,seconds,period"' in html
    assert html.count('class="col-resizer"') == 3 and html.count('class="plf-sort"') == 3
    assert '<tbody id="plf-items"></tbody>' in html
    # Sorting rewrites the play order, so the way back is on the page.
    assert 'id="plf-undo"' in html
