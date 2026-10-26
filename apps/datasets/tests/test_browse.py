"""The staff dataset browser at /smallstack/datasets/browse/."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.activity.models import RequestLog
from apps.datasets.registry import dataset, unregister

pytestmark = pytest.mark.django_db

User = get_user_model()
INDEX = reverse("datasets:browse-index")


def _browse(key: str) -> str:
    return reverse("datasets:browse", kwargs={"key": key})


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="ds-staff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


# The activity middleware logs the test client's own requests into RequestLog,
# so every seeded row carries a marker address and the assertions filter on it.
IP = "10.9.9.9"
SEEDED = {"ip_address": IP}


def _seed() -> None:
    for i in range(3):
        RequestLog.objects.create(path=f"/a/{i}", method="GET", status_code=200, response_time_ms=10 + i, ip_address=IP)
    RequestLog.objects.create(path="/b", method="POST", status_code=500, response_time_ms=40, ip_address=IP)


def _paths(resp) -> set[str]:
    return {next(c["value"] for c in row["cells"] if c["name"] == "path") for row in resp.context["rows"]}


def test_index_requires_staff(client):
    assert client.get(INDEX).status_code == 302  # anonymous → login
    client.force_login(User.objects.create_user(username="plain", password="pw-123456"))
    assert client.get(INDEX).status_code == 403


def test_index_lists_framework_and_project_datasets(client, staff):
    key = "t_browse_project"
    try:
        dataset(key, label="Project thing", description="A downstream dataset")(lambda: RequestLog.objects.all())
        resp = client.get(INDEX)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Framework datasets" in html and "Project datasets" in html
        assert "smallstack_requests" in html and "Project thing" in html
        assert _browse("smallstack_requests") in html and _browse(key) in html
    finally:
        unregister(key)


def test_browse_unknown_key_is_404(client, staff):
    assert client.get(_browse("no_such_dataset")).status_code == 404


def test_browse_renders_schema_driven_filters_and_rows(client, staff):
    _seed()
    resp = client.get(_browse("smallstack_requests"))
    assert resp.status_code == 200
    html = resp.content.decode()
    # Widgets come from schema()["filters"]: a choice select for method, a date
    # preset + range for timestamp, a text box for path.
    assert 'name="method"' in html and 'name="timestamp__gte"' in html and 'name="path"' in html
    assert _paths(resp) >= {"/a/0", "/b"}
    # Column headers are sortable links.
    assert "ordering=response_time_ms" in html
    # CSV export deep-links the REST route (the dataset publishes REST).
    assert reverse("datasets:rows", kwargs={"key": "smallstack_requests"}) + "?format=csv" in html


def test_browse_applies_filters_ordering_and_csv_link(client, staff):
    _seed()
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "method": "POST", "ordering": "-response_time_ms"})
    assert resp.status_code == 200
    assert _paths(resp) == {"/b"}
    html = resp.content.decode()
    assert "format=csv" in html and "method=POST" in html and f"ip_address={IP}" in html
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "ordering": "-response_time_ms"})
    assert [next(c["value"] for c in row["cells"] if c["name"] == "path") for row in resp.context["rows"]] == [
        "/b",
        "/a/2",
        "/a/1",
        "/a/0",
    ]
    # Unknown/garbage params are ignored, not errors.
    assert (
        client.get(_browse("smallstack_requests"), {"nope": "x", "page": "zzz", "ordering": "bogus"}).status_code == 200
    )


def test_browse_rollup_groups_and_aggregates(client, staff):
    _seed()
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "group_by": "method"})
    assert resp.status_code == 200
    series = {s["label"]: s["value"] for s in resp.context["series"]}
    assert series == {"GET": 3, "POST": 1}
    assert resp.context["group_by_label"] == "Method"
    # Numeric columns are groupable too, and a measure + agg applies.
    resp = client.get(
        _browse("smallstack_requests"),
        {**SEEDED, "group_by": "status_code", "measure": "response_time_ms", "agg": "avg", "method": "GET"},
    )
    series = {s["label"]: s["value"] for s in resp.context["series"]}
    assert series == {"200": 11.0}
    # The bar is relative to the largest bucket.
    assert resp.context["series"][0]["pct"] == 100.0
    # A bad group_by is ignored, a bad agg falls back to count.
    resp = client.get(_browse("smallstack_requests"), {"group_by": "nope", "agg": "median"})
    assert resp.status_code == 200 and resp.context["group_by"] == "" and resp.context["agg"] == "count"


def test_browse_pages_with_stable_ordering(client, staff):
    from apps.datasets.views import PAGE_SIZE

    for i in range(PAGE_SIZE + 5):
        RequestLog.objects.create(path=f"/p/{i}", method="GET", status_code=200, response_time_ms=1, ip_address=IP)
    first = client.get(_browse("smallstack_requests"), SEEDED)
    second = client.get(_browse("smallstack_requests"), {**SEEDED, "page": 2})
    assert first.context["page_obj"].paginator.num_pages == 2
    assert len(first.context["rows"]) == PAGE_SIZE and len(second.context["rows"]) == 5
    assert not _paths(first) & _paths(second)


def test_browse_hides_csv_for_a_dataset_without_rest(client, staff):
    key = "t_browse_norest"
    try:
        dataset(key, label="No REST")(lambda: RequestLog.objects.all())
        resp = client.get(_browse(key))
        assert resp.status_code == 200
        assert resp.context["csv_url"] == ""
        assert "Download CSV" not in resp.content.decode()
    finally:
        unregister(key)


def test_nav_has_a_datasets_entry(client, staff):
    html = client.get(INDEX).content.decode()
    assert 'href="/smallstack/datasets/browse/"' in html
