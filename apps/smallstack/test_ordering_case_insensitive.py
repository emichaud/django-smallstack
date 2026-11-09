"""Text columns sort case-insensitively on every list.

``crud._apply_ordering_fields`` is the one place a ``?ordering=`` becomes a
query — the HTML CRUD lists, the REST API and MCP, and dataset rows all go
through it — so "alpha" sorts beside "Alpha", not after "Zeta" as a byte-order
sort puts it. Non-text columns sort exactly as before.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db.models import CharField, Value
from django.db.models.functions import Concat
from django.urls import reverse

from apps.smallstack.crud import _apply_ordering_fields
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def tokens():
    user = get_user_model().objects.create_user("ci-owner", password="x")
    for name in ("charlie", "Bravo", "alpha", "Alpha", "Zeta"):
        APIToken.create_token(user=user, name=name)
    return user


def _names(qs) -> list[str]:
    return list(qs.values_list("name", flat=True))


def test_a_text_field_sorts_case_insensitively_both_ways(tokens):
    qs = APIToken.objects.all()
    asc = _names(_apply_ordering_fields(qs, "name", {"name"}))
    assert [n.lower() for n in asc] == ["alpha", "alpha", "bravo", "charlie", "zeta"]
    # The raw value breaks the tie, so the order is stable. Which of the two comes
    # first is the database's collation (SQLite: "Alpha"; Postgres: "alpha").
    assert set(asc[:2]) == {"Alpha", "alpha"}
    assert _names(_apply_ordering_fields(qs, "name", {"name"})) == asc
    desc = _names(_apply_ordering_fields(qs, "-name", {"name"}))
    assert desc == asc[::-1]


def test_text_through_a_relation_and_text_annotations_too(tokens):
    User = get_user_model()
    for username in ("Bee", "apple"):  # byte order: "Bee" < "apple"; case-insensitive: apple < Bee
        APIToken.create_token(user=User.objects.create_user(username, password="x"), name=f"t-{username}")
    qs = APIToken.objects.filter(name__startswith="t-")
    owners = _apply_ordering_fields(qs, "user__username", {"user__username"})
    assert list(owners.values_list("user__username", flat=True)) == ["apple", "Bee"]
    labelled = APIToken.objects.annotate(label=Concat(Value(""), "name", output_field=CharField()))
    assert [n.lower() for n in _names(_apply_ordering_fields(labelled, "label", {"label"}))][:3] == [
        "alpha",
        "alpha",
        "bravo",
    ]


def test_non_text_fields_sort_as_before(tokens):
    qs = APIToken.objects.all()
    assert list(_apply_ordering_fields(qs, "-created_at", {"created_at"})) == list(qs.order_by("-created_at"))
    assert list(_apply_ordering_fields(qs, "user", {"user"})) == list(qs.order_by("user"))  # an FK: by id


def test_the_rest_api_sorts_case_insensitively(client, tokens):
    from apps.dashboards.models import Metric

    staff = get_user_model().objects.create_user("ci-staff", password="x", is_staff=True)
    client.force_login(staff)
    for name in ("charlie", "Bravo", "alpha"):
        Metric(key=f"ci_{name.lower()}", name=name, dataset="smallstack_requests").save()
    rows = client.get("/smallstack/api/dashboards/metrics/?ordering=name").json()["results"]
    assert [r["name"] for r in rows] == ["alpha", "Bravo", "charlie"]


def test_an_html_crud_list_and_the_dataset_browser_too(client, tokens):
    from apps.activity.models import RequestLog
    from apps.dashboards.models import Metric

    staff = get_user_model().objects.create_user("ci-staff2", password="x", is_staff=True)
    client.force_login(staff)
    for name in ("charlie", "Bravo", "alpha"):
        Metric(key=f"ci2_{name.lower()}", name=name, dataset="smallstack_requests").save()
    html = client.get(reverse("dashboards/metrics-list"), {"ordering": "name"}).content.decode()
    assert (
        html.index('class="lib-name">alpha<')
        < html.index('class="lib-name">Bravo<')
        < html.index('class="lib-name">charlie<')
    )

    for path in ("/ci-b", "/CI-A", "/ci-c"):
        RequestLog.objects.create(path=path, method="GET", status_code=200, response_time_ms=1, ip_address="10.7.7.7")
    browse = client.get(
        reverse("datasets:browse", args=["smallstack_requests"]), {"ip_address": "10.7.7.7", "ordering": "path"}
    ).content.decode()
    assert browse.index(">/CI-A<") < browse.index(">/ci-b<") < browse.index(">/ci-c<")
