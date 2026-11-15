"""The staff dataset browser at /smallstack/datasets/browse/."""

from __future__ import annotations

import json

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
    from django.contrib.auth.models import Permission

    # The tokens dataset needs smallstack.view_apitoken (B6).
    staff.user_permissions.add(Permission.objects.get(codename="view_apitoken"))
    client.force_login(User.objects.get(pk=staff.pk))
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
    assert f'href="{INDEX}"' in html


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
    assert f'hx-get="{INDEX}"' in html and 'type="hidden" name="fpage"' not in html
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


# -- More conditions: the filter tree -----------------------------------------


def _tree(**params):
    import json

    return json.dumps(params.pop("tree")), params


def test_browse_filter_tree_narrows_rows_rollup_and_csv(client, staff):
    _seed()
    tree = {
        "or": [
            {"field": "method", "op": "=", "value": "POST"},
            {"field": "response_time_ms", "op": ">", "value": 11},
        ]
    }
    tree_json, _ = _tree(tree=tree)
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "filter_tree": tree_json})
    assert resp.status_code == 200
    assert _paths(resp) == {"/b", "/a/2"}
    assert resp.context["has_filters"] and resp.context["tree_error"] == ""
    assert resp.context["tree_reading"] == "Method = POST OR Response time ms > 11"
    html = resp.content.decode()
    assert "Reads as:" in html and 'id="ds-tree"' in html and 'id="ds-schema"' in html
    # The CSV deep link carries the tree to REST, which takes the same parameter.
    assert "filter_tree=" in resp.context["csv_url"] and "format=csv" in resp.context["csv_url"]
    # The quick filters and the tree AND together; the roll-up sees both.
    resp = client.get(
        _browse("smallstack_requests"), {**SEEDED, "filter_tree": tree_json, "method": "GET", "group_by": "method"}
    )
    assert _paths(resp) == {"/a/2"}
    assert {s["label"]: s["value"] for s in resp.context["series"]} == {"GET": 1}
    # An empty tree is no filter at all.
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "filter_tree": "{}"})
    assert len(_paths(resp)) == 4 and not resp.context["tree_json"]


def test_browse_bad_filter_tree_shows_no_rows_not_all_of_them(client, staff):
    """A condition that can't be applied must never widen the result (the
    fail-open shape): the page says why and shows nothing, in the table, the
    roll-up and the CSV link alike."""
    _seed()
    bad = {"and": [{"field": "method", "op": "=", "value": "GET"}, {"field": "nope", "op": "=", "value": 1}]}
    tree_json, _ = _tree(tree=bad)
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "filter_tree": tree_json, "group_by": "method"})
    assert resp.status_code == 200
    assert "nope" in resp.context["tree_error"]
    assert resp.context["rows"] == [] and resp.context["page_obj"].total_count == 0
    assert resp.context["series"] == [] and resp.context["csv_url"] == ""
    assert resp.context["tree_json"]  # kept in the editor so it can be fixed
    html = resp.content.decode()
    assert "can't be applied" in html and "No rows shown" in html
    # Malformed JSON is the same story.
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "filter_tree": "{not json"})
    assert resp.status_code == 200 and "JSON" in resp.context["tree_error"] and resp.context["rows"] == []


def test_browse_mounts_the_shared_filter_tree_editor(client, staff):
    resp = client.get(_browse("smallstack_requests"))
    html = resp.content.decode()
    assert "datasets/css/filter-tree.css" in html
    assert "datasets/js/filter-tree.js" in html and "datasets/js/browse.js" in html
    assert html.index("datasets/js/filter-tree.js") < html.index("datasets/js/browse.js")
    assert '<input type="hidden" name="filter_tree" value="">' in html
    assert "More conditions" in html


# -- Keep it: Save as metric, keep the roll-up as a card -----------------------


def _query(url: str) -> dict:
    from urllib.parse import parse_qs, urlsplit

    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_browse_save_as_metric_carries_every_condition_and_the_rollup(client, staff):
    import json

    _seed()
    tree = {"field": "response_time_ms", "op": ">", "value": 11}
    resp = client.get(
        _browse("smallstack_requests"),
        {
            **SEEDED,
            "method": "POST",
            "path": "/b",
            "timestamp": "month",
            "filter_tree": json.dumps(tree),
            "group_by": "status_code",
            "measure": "response_time_ms",
            "agg": "avg",
        },
    )
    assert resp.status_code == 200
    q = _query(resp.context["metric_url"])
    assert resp.context["metric_url"].startswith(reverse("dashboards_metric_quick"))
    assert q["dataset"] == "smallstack_requests" and q["agg"] == "avg" and q["measure"] == "response_time_ms"
    kept = json.loads(q["filter_tree"])
    leaves = {(leaf["field"], leaf["op"]): leaf["value"] for leaf in kept["and"]}
    # The quick filters become leaves (choice =, text contains, date preset → period) AND the tree.
    assert leaves[("ip_address", "=")] == IP
    assert leaves[("method", "=")] == "POST"
    # (Few distinct paths in a test database make Path a dropdown, so it's "=" there, "contains" as a text box.)
    assert leaves.get(("path", "contains"), leaves.get(("path", "="))) == "/b"
    assert leaves[("timestamp", "period")] == "this_month"
    assert leaves[("response_time_ms", ">")] == 11
    # A grouped roll-up offers the grouped cards; an average has no pie.
    labels = [c["label"] for c in resp.context["card_links"]]
    assert labels == ["Grouped stat", "Ranked bars"]
    cq = _query(resp.context["card_links"][0]["url"])
    assert cq["then"] == "card" and cq["card_type"] == "metric_group" and cq["dimension"] == "status_code"
    assert cq["filter_tree"] == q["filter_tree"] and cq["agg"] == "avg"
    html = resp.content.decode()
    assert "Make a metric" in html and "Keep this roll-up as a card" in html
    # Each choice sketches its card from the roll-up: the total with its groups, bars; no pie for an average.
    assert html.count('class="ds-tile"') == 2 and 'class="ds-art-total"' in html and 'class="ds-art-bar"' in html
    sketch = resp.context["sketch"]
    assert sketch["bars"][0]["pct"] == 100 and sketch["pie"].startswith("conic-gradient(") and "#" not in sketch["pie"]


def test_browse_save_as_metric_counts_rows_without_a_measure_and_offers_pie(client, staff):
    _seed()
    resp = client.get(_browse("smallstack_requests"), {**SEEDED, "group_by": "method", "agg": "avg"})
    q = _query(resp.context["metric_url"])
    assert q["agg"] == "count" and "measure" not in q
    assert [c["label"] for c in resp.context["card_links"]] == ["Grouped stat", "Ranked bars", "Pie chart"]
    # No filters at all: a metric over the whole dataset, no tree.
    resp = client.get(_browse("smallstack_requests"))
    q = _query(resp.context["metric_url"])
    assert q == {"dataset": "smallstack_requests", "agg": "count"}
    assert resp.context["card_links"] == []
    # An explicit date bound drops that column's preset, as the table applies it.
    resp = client.get(_browse("smallstack_requests"), {"timestamp": "month", "timestamp__gte": "2026-01-01"})
    kept = json.loads(_query(resp.context["metric_url"])["filter_tree"])
    assert kept == {"field": "timestamp", "op": ">=", "value": "2026-01-01"}


def test_browse_offers_no_metric_when_the_tree_cannot_be_applied(client, staff):
    resp = client.get(_browse("smallstack_requests"), {"filter_tree": '{"field": "nope", "op": "=", "value": 1}'})
    assert resp.context["metric_url"] == "" and resp.context["card_links"] == []
    assert "Make a metric" not in resp.content.decode()


def test_browse_filters_apply_as_they_change(client, staff):
    _seed()
    html = client.get(_browse("smallstack_requests"), {**SEEDED, "group_by": "method"}).content.decode()
    # The form hx-gets the page as it changes, taking the rows card and swapping in the rest.
    assert 'hx-trigger="submit, change, ds-change"' in html
    assert 'hx-select-oob="#ds-rollup,#ds-live,#ds-csv"' in html and 'hx-push-url="true"' in html
    assert 'id="ds-rollup"' in html and 'id="ds-live"' in html and 'id="ds-csv"' in html
    # The live count and the way to keep the rows sit together at the filters' right edge.
    live = html.split('id="ds-live"')[1].split("</div>")[0]
    assert "row" in live and 'data-stat-modal="Make a metric"' in live and 'hx-target="#stat-modal-body"' in live
    # Apply is only for a browser without scripts; the card links open the same modal.
    assert "<noscript><button" in html and 'data-stat-modal="Grouped stat card: first, the metric"' in html


def test_the_quick_date_presets_and_the_periods_cover_the_same_days(client, staff):
    """A metric made from the browser counts what the browser showed: each
    preset ("Past 7 days", "This month"…) and the period it becomes draw
    the same boundary, to the day."""
    from datetime import timedelta

    from django.utils import timezone

    today = timezone.localdate()
    noon = timezone.make_aware(timezone.datetime(today.year, today.month, today.day, 12))
    stamps = {
        "today": noon,
        "six_ago": noon - timedelta(days=6),
        "seven_ago": noon - timedelta(days=7),
        "month_start": noon.replace(day=1),
        "month_end": (noon.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1),
        "year_end": noon.replace(month=12, day=31),
        "last_year": noon.replace(year=today.year - 1, month=12, day=31),
    }
    for path, when in stamps.items():
        log = RequestLog.objects.create(
            path=f"/{path}", method="GET", status_code=200, response_time_ms=1, ip_address=IP
        )
        RequestLog.objects.filter(pk=log.pk).update(timestamp=when)

    def counts(preset: str) -> tuple[int, int, str]:
        shown = client.get(_browse("smallstack_requests"), {**SEEDED, "timestamp": preset})
        leaf = json.loads(_query(shown.context["metric_url"])["filter_tree"])
        period = next(x for x in leaf["and"] if x["field"] == "timestamp")["value"]
        tree = {
            "and": [
                {"field": "ip_address", "op": "=", "value": IP},
                {"field": "timestamp", "op": "period", "value": period},
            ]
        }
        kept = client.get(_browse("smallstack_requests"), {"filter_tree": json.dumps(tree)})
        return shown.context["page_obj"].total_count, kept.context["page_obj"].total_count, period

    week = counts("week")
    assert week[2] == "last_7" and week[0] == week[1]
    # Past 7 days is the 7 days ending today: six days ago is in, seven is out.
    shown = client.get(_browse("smallstack_requests"), {**SEEDED, "timestamp": "week"})
    assert "/six_ago" in _paths(shown) and "/seven_ago" not in _paths(shown)
    month = counts("month")
    assert month[2] == "this_month" and month[0] == month[1]
    year = counts("year")
    assert year[2] == "this_year" and year[0] == year[1]
    # The whole month and the whole year: days still to come count, last year doesn't.
    shown = client.get(_browse("smallstack_requests"), {**SEEDED, "timestamp": "year"})
    assert "/year_end" in _paths(shown) and "/last_year" not in _paths(shown)
    for preset in ("today", "yesterday"):
        assert counts(preset)[0] == counts(preset)[1]
