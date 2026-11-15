"""The resource detail page: a readable URL pattern, and links to the real pages behind it.

The title marks a pattern's converters and wraps only after a slash. "Open
page" and each path's ↗ link go to a real path this pattern served, and only
one that answered a GET without an error: a POST-only endpoint or a 404 is
nothing you can open.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.activity.models import RequestLog
from apps.activity.views import route_segments

pytestmark = pytest.mark.django_db

User = get_user_model()
PATTERN = "/d/<slug:slug>/cells/<str:cell_id>/"


def test_a_pattern_splits_at_slashes_and_marks_its_converters():
    assert route_segments(PATTERN) == [
        ("/", False), ("d/", False), ("<slug:slug>", True), ("/", False),
        ("cells/", False), ("<str:cell_id>", True), ("/", False),
    ]
    assert route_segments("/about/") == [("/", False), ("about/", False)]
    assert route_segments("/static/a.css") == [("/", False), ("static/", False), ("a.css", False)]


def _hit(path: str, *, method: str = "GET", status: int = 200, n: int = 1) -> None:
    for _ in range(n):
        RequestLog.objects.create(
            path=path, route=PATTERN, method=method, status_code=status, response_time_ms=5
        )


def test_only_paths_that_answered_a_get_are_offered_as_links(client):
    _hit("/d/ops/cells/c1/", n=3)  # most used, opens: the header's "Open page"
    _hit("/d/ops/cells/c2/", method="POST", n=2)  # POST only
    _hit("/d/ops/cells/c3/", status=404)  # never answered
    _hit("//evil.example/cells/c4/")  # not a path on this site
    client.force_login(User.objects.create_user("res-staff", password="p", is_staff=True))
    page = client.get(reverse("activity:resource_detail") + "?r=" + quote(PATTERN, safe="") + "&window=7d")
    paths = {p["path"]: p["open_url"] for p in page.context["sample_paths"]}
    assert paths == {
        "/d/ops/cells/c1/": "/d/ops/cells/c1/",
        "/d/ops/cells/c2/": "",
        "/d/ops/cells/c3/": "",
        "//evil.example/cells/c4/": "",
    }
    assert page.context["open_url"] == "/d/ops/cells/c1/"
    html = page.content.decode()
    assert 'class="resource-route-param">&lt;slug:slug&gt;</span>' in html
    assert 'href="/d/ops/cells/c1/" class="btn-outline btn-sm resource-open"' in html


def test_a_long_path_keeps_its_end(client):
    long_path = "/d/a-very-long-dashboard-slug-indeed/cells/c9/"
    _hit(long_path)
    client.force_login(User.objects.create_user("res-staff2", password="p", is_staff=True))
    page = client.get(reverse("activity:resource_detail") + "?r=" + quote(PATTERN, safe=""))
    label = page.context["sample_paths"][0]["label"]
    assert label.startswith("…") and label.endswith("/cells/c9/")
