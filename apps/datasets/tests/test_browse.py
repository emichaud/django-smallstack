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
        assert "smallstack_api_tokens" in html and "Project thing" in html  # page 1 of each section
        assert _browse("smallstack_api_tokens") in html and _browse(key) in html
        assert {d["key"] for d in resp.context["framework_datasets"]} >= {"smallstack_requests"}
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


def test_browse_apply_and_rollup_share_one_form(client, staff):
    """Apply and Roll up submit the same form, so neither drops the other's
    live edits. Before, each form carried a hidden *snapshot* of the other's
    state: pick a new group-by then click Apply and the roll-up reverted;
    change a filter then click Roll up and the filter reverted."""
    _seed()
    resp = client.get(
        _browse("smallstack_requests"),
        {**SEEDED, "method": "GET", "group_by": "method", "ordering": "-status_code"},
    )
    html = resp.content.decode()
    assert html.count('action="' + _browse("smallstack_requests") + '"') == 1
    # The roll-up controls are attached to the one form, not hidden-copied.
    assert 'name="group_by" form="ds-form"' in html
    assert 'name="measure" form="ds-form"' in html
    assert 'name="agg" form="ds-form"' in html
    assert 'form="ds-form" class="btn-outline btn-sm">Roll up' in html
    assert 'type="hidden" name="group_by"' not in html
    assert 'type="hidden" name="method"' not in html
    # The current sort survives a re-submit; the page number does not.
    assert '<input type="hidden" name="ordering" value="-status_code">' in html
    assert 'name="page"' not in html
    # Clear drops the filters but keeps the roll-up.
    assert f'href="{_browse("smallstack_requests")}?group_by=method"' in html


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


def test_browse_shows_15_rows_by_default_and_the_size_is_selectable(client, staff):
    from apps.datasets.views import PAGE_SIZE, PAGE_SIZES

    assert PAGE_SIZE == 15 and PAGE_SIZES[0] == 15
    for i in range(30):
        RequestLog.objects.create(path=f"/s/{i}", method="GET", status_code=200, response_time_ms=1, ip_address=IP)
    first = client.get(_browse("smallstack_requests"), SEEDED)
    assert len(first.context["rows"]) == 15 and first.context["page_obj"].paginator.num_pages == 2
    html = first.content.decode()
    assert 'name="per_page"' in html and '<option value="15" selected>' in html
    # The size form keeps the filters but not the page: a new size starts at page 1.
    assert 'name="ip_address"' in html and 'type="hidden" name="page"' not in html

    wider = client.get(_browse("smallstack_requests"), {**SEEDED, "per_page": 25, "page": 2})
    assert wider.context["per_page"] == 25 and len(wider.context["rows"]) == 5
    assert client.get(_browse("smallstack_requests"), {**SEEDED, "per_page": 7}).context["per_page"] == 15
    # per_page is the page's own parameter, never a dataset filter.
    assert "per_page" not in wider.context["filters"]


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


def test_index_pages_each_section_with_a_selectable_size(client, staff):
    from apps.datasets.views import INDEX_PAGE_SIZES, PAGE_SIZES

    assert INDEX_PAGE_SIZES == PAGE_SIZES and PAGE_SIZES[0] == 15  # pages like the browse page
    resp = client.get(INDEX)
    fw = resp.context["framework_page"]
    assert fw.paginator.per_page == 15
    assert len(fw.object_list) == 15 and fw.paginator.num_pages >= 2
    html = resp.content.decode()
    # The framework pager, paging in place under the section's own param.
    assert 'id="ds-sections"' in html and 'aria-label="Framework datasets pagination"' in html
    assert 'href="?fpage=2"' in html and 'hx-select="#ds-sections"' in html and 'hx-push-url="true"' in html
    assert 'id="paginator-per-page-ds-sections-fpage"' in html and '<option value="15" selected>' in html
    # Page 2 of the framework section, other params preserved in its links.
    resp = client.get(INDEX, {"fpage": 2, "per_page": 15})
    assert resp.context["framework_page"].number == 2
    html = resp.content.decode()
    assert 'href="?fpage=1&amp;per_page=15"' in html
    # A new size starts every section again at page 1.
    assert 'hx-get="/smallstack/datasets/browse/"' in html and 'type="hidden" name="fpage"' not in html
    # A larger page size; a bogus one falls back to the default.
    assert client.get(INDEX, {"per_page": 50}).context["per_page"] == 50
    assert client.get(INDEX, {"per_page": 10}).context["per_page"] == 15
    assert client.get(INDEX, {"per_page": "x", "fpage": "zz"}).status_code == 200


def test_browse_headers_sort_in_place_and_stay_resizable(client, staff):
    html = client.get(_browse("smallstack_requests"), SEEDED).content.decode()
    assert 'hx-select="#ds-rows" hx-target="#ds-rows" hx-swap="outerHTML" hx-push-url="true"' in html
    assert "ordering=method" in html and 'class="col-resizer"' in html  # sort links + table-resize.js handles
    sorted_html = client.get(_browse("smallstack_requests"), {**SEEDED, "ordering": "method"}).content.decode()
    assert 'aria-sort="ascending"' in sorted_html and "ordering=-method" in sorted_html  # a second click flips it
