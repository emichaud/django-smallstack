"""Finding things by tag: the tag bar on the overviews and on every list, the
lists narrowing to a tag, and My dashboards paging like the rest."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.dashboards.models import Component, Dashboard, Metric, Playlist, tag_cloud

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff(client):
    user = User.objects.create_user("tb-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def _boards(n: int, tags: str = "", prefix: str = "b", **kw) -> None:
    for i in range(n):
        Dashboard(name=f"{prefix.upper()} {i:02d}", slug=f"{prefix}-{i:02d}", tags=tags, **kw).save()


def test_the_cloud_counts_each_tag_once_a_row_whatever_its_case():
    Dashboard(name="A", slug="a", tags="Ops, weekly review").save()
    Dashboard(name="B", slug="b", tags="ops, ops").save()
    Playlist(name="P", slug="p", items=[], tags="finance").save()
    cloud = tag_cloud(Dashboard.objects.all(), Playlist.objects.all(), current="OPS")
    assert [(t["name"], t["count"], t["current"]) for t in cloud] == [
        ("finance", 1, False),
        ("Ops", 2, True),
        ("weekly review", 1, False),
    ]
    assert tag_cloud(Dashboard.objects.all(), limit=1) == [{"name": "Ops", "count": 2, "current": False}]
    # The tag a page is narrowed to is always offered, kept past the limit or gone from every row.
    kept = tag_cloud(Dashboard.objects.all(), current="weekly review", limit=1)
    assert [t["name"] for t in kept] == ["Ops", "weekly review"]
    assert tag_cloud(Dashboard.objects.all(), current="gone")[0] == {"name": "gone", "count": 0, "current": True}


def test_the_overview_offers_every_tag_not_only_those_on_the_rows_it_shows(client, staff):
    Dashboard(name="Old one", slug="old-one", tags="archive-me").save()  # the least recently changed
    _boards(9, tags="ops")
    html = client.get("/smallstack/dashboards/").content.decode()
    assert "Old one" not in html  # past the eight it shows
    bar = html.split('class="ix-tags"', 1)[1].split("</nav>", 1)[0]
    assert ">archive-me<span" in bar and '>ops<span class="dash-tag-count">9</span>' in bar
    assert 'class="dash-tag ix-tag-all is-current" aria-current="true"' in bar
    # Narrowed, the way to the full list keeps the tag.
    html = client.get("/smallstack/dashboards/?tag=ops").content.decode()
    assert 'href="/smallstack/dashboards/boards/?tag=ops" class="md-link">All 9 dashboards</a>' in html
    assert "Old one" in client.get("/smallstack/dashboards/?tag=archive-me").content.decode()


@pytest.mark.parametrize(
    ("url", "make"),
    [
        ("/smallstack/dashboards/boards/", lambda n, tags: Dashboard(name=n, slug=n.lower(), tags=tags)),
        ("/smallstack/dashboards/playlists/", lambda n, tags: Playlist(name=n, slug=n.lower(), items=[], tags=tags)),
        ("/smallstack/dashboards/metrics/", lambda n, tags: Metric(key=n.lower(), name=n, dataset=DS, tags=tags)),
        (
            "/smallstack/dashboards/components/?display=library",
            lambda n, tags: Component(name=n, type="text", options={"markdown": "x"}, tags=tags),
        ),
    ],
)
def test_every_list_shows_tags_and_narrows_to_one(client, staff, url, make):
    make("Alpha", "ops, weekly review").save()
    make("Bravo", "devops").save()
    make("Charlie", "").save()
    join = "&" if "?" in url else "?"
    html = client.get(url).content.decode()
    assert all(name in html for name in ("Alpha", "Bravo", "Charlie"))
    bar = html.split('class="ix-tags"', 1)[1].split("</nav>", 1)[0]
    assert ">devops<span" in bar and ">ops<span" in bar and ">weekly review<span" in bar
    assert html.count('class="dash-tag"') >= 6  # the bar's three, and the same three on their rows
    narrowed = client.get(f"{url}{join}tag=ops").content.decode()
    rows = narrowed.split('id="crud-list-content"', 1)[1]
    assert "Alpha" in rows and "Bravo" not in rows and "Charlie" not in rows  # the whole tag: not "devops"
    assert 'class="dash-tag is-current" aria-current="true">ops<span' in narrowed


def test_a_narrowed_list_keeps_its_tag_from_page_to_page(client, staff):
    _boards(17, tags="ops")
    _boards(3, prefix="x")
    html = client.get("/smallstack/dashboards/boards/?tag=ops").content.decode()
    assert "Showing 1&ndash;15 of 17" in html
    pager = html.split('class="paginator-nav"', 1)[1]
    assert "tag=ops" in pager and "page=2" in pager
    page2 = client.get("/smallstack/dashboards/boards/?tag=ops&page=2").content.decode()
    assert "Showing 16&ndash;17 of 17" in page2


def test_my_dashboards_pages_and_narrows_like_the_lists(client, staff):
    _boards(18, tags="ops", owner=staff, created_by=staff)
    Dashboard(name="Other", slug="other", tags="finance", owner=staff, created_by=staff).save()
    resp = client.get("/smallstack/dashboards/mine/")
    html = resp.content.decode()
    assert len(resp.context["boards"]) == 15 and resp.context["board_count"] == 19
    assert "The 19 dashboards you made" in html and "Showing 1&ndash;15 of 19" in html
    assert '<option value="15" selected>' in html and 'hx-select="#my-page"' in html
    assert len(client.get("/smallstack/dashboards/mine/?page=2").context["boards"]) == 4
    assert len(client.get("/smallstack/dashboards/mine/?per_page=25").context["boards"]) == 19
    # Sorted by something that isn't a column, it still pages what it sorted.
    by_cards = client.get("/smallstack/dashboards/mine/?ordering=cards&view=table")
    assert len(by_cards.context["boards"]) == 15 and "page=" not in by_cards.context["sort_links"]["name"]["url"]
    narrowed = client.get("/smallstack/dashboards/mine/?tag=finance")
    assert [r["dashboard"].slug for r in narrowed.context["boards"]] == ["other"]
    assert ">finance<span" in html and "tagged finance" in narrowed.content.decode()


def test_with_nothing_tagged_yet_the_bar_says_how_to_tag(client, staff):
    hint = "None yet. Add tags in the settings"
    # Nothing at all: no bar, no hint.
    for url in ("/smallstack/dashboards/", "/smallstack/dashboards/mine/", "/smallstack/dashboards/boards/"):
        assert hint not in client.get(url).content.decode(), url
    _boards(2, owner=staff, created_by=staff)
    for url in ("/smallstack/dashboards/", "/smallstack/dashboards/mine/", "/smallstack/dashboards/boards/"):
        html = client.get(url).content.decode()
        assert hint in html and 'class="ix-tags ix-tags--none"' in html, url
    assert hint not in client.get("/smallstack/dashboards/playlists/").content.decode()  # no playlists: nothing to tag
    # The first tag turns the hint into the bar.
    Dashboard.objects.filter(slug="b-00").update(tags="ops")
    html = client.get("/smallstack/dashboards/mine/").content.decode()
    assert hint not in html and '>ops<span class="dash-tag-count">1</span>' in html
    narrowed = client.get("/smallstack/dashboards/mine/?tag=ops").context["boards"]
    assert [r["dashboard"].slug for r in narrowed] == ["b-00"]
