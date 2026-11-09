"""What call_stats carried on top of datasets/core.py, taken upstream.

- ``cells()``: two dimensions → a complete x × y grid (heatmaps, punch cards).
- ``series(sort=…)``: rank by value (a top N), the time-grain window kept apart.
- ``median``: in the database, grouped or not, on SQLite and Postgres alike.
- ``@dataset(units=…)``: a column's semantic unit in the schema.
- More flat lookups: ``__gt`` / ``__lte`` and numeric comparisons, ``__ne``,
  ``__icontains``, ``__period``. A value that won't parse is refused, never
  dropped: a dropped narrowing returns more rows than the caller asked for.

Every dataset here reads only rows under ``/x/``: the activity middleware logs
the test client's own requests into the same table.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.activity.models import RequestLog
from apps.datasets import core
from apps.datasets.core import get_dataset
from apps.datasets.registry import dataset

pytestmark = pytest.mark.django_db

User = get_user_model()
KEY = "t_ports_log"


@dataset(
    KEY,
    enable_api=True,
    enable_mcp=True,
    columns=["path", "method", "status_code", "response_time_ms", "timestamp"],
    measures=[("ok_pct", "status_code", "response_time_ms", "percent")],
    units={"response_time_ms": "milliseconds"},
)
def _t_ports_log(request=None):
    return RequestLog.objects.filter(path__startswith="/x/")


def _log(path: str, method: str = "GET", status: int = 200, ms: int = 10, days_ago: int = 0) -> RequestLog:
    row = RequestLog.objects.create(path=f"/x/{path}", method=method, status_code=status, response_time_ms=ms)
    if days_ago:
        RequestLog.objects.filter(pk=row.pk).update(timestamp=timezone.now() - timedelta(days=days_ago))
    return row


@pytest.fixture
def seeded():
    # GET 10 / 20 / 100 (median 20, mean 43.33); POST 40 / 60 (median 50); PUT 5.
    _log("a", ms=10)
    _log("b", ms=20, status=404)
    _log("c", ms=100, days_ago=40)
    _log("d", "POST", 201, 40)
    _log("e", "POST", 500, 60, days_ago=40)
    _log("f", "PUT", 200, 5)
    return get_dataset(KEY)


# -- median --------------------------------------------------------------------------------------


def test_median_is_the_middle_value_not_the_mean(seeded):
    assert seeded.scalar(measure="response_time_ms", agg="median") == 30.0  # 5 10 [20 40] 60 100
    assert seeded.scalar(measure="response_time_ms", agg="median", filters={"method": "GET"}) == 20.0


def test_median_groups_in_the_database(seeded):
    by_method = {r["label"]: r["value"] for r in seeded.series("method", measure="response_time_ms", agg="median")}
    assert by_method == {"GET": 20.0, "POST": 50.0, "PUT": 5.0}  # GET's mean would be 43.33


def test_median_of_nothing_has_no_value_and_needs_a_measure(seeded):
    assert seeded.scalar(measure="response_time_ms", agg="median", filters={"method": "DELETE"}) is None
    with pytest.raises(ValueError, match="needs a measure"):
        seeded.scalar(agg="median")


def test_median_is_refused_where_the_database_has_none(seeded, monkeypatch):
    monkeypatch.setattr(core, "median_supported", lambda using="default": False)
    with pytest.raises(ValueError, match="isn't available on this database"):
        seeded.scalar(measure="response_time_ms", agg="median")
    assert "median" not in seeded.schema()["aggs"]


# -- series sort ---------------------------------------------------------------------------------


def test_value_desc_ranks_before_the_limit_applies(seeded):
    top = seeded.series("method", sort={"by": "value", "dir": "desc"}, limit=2)
    assert [(r["label"], r["value"]) for r in top] == [("GET", 3), ("POST", 2)]
    # The default is unchanged: the dimension's order, so the first two alphabetically.
    assert [r["label"] for r in seeded.series("method", limit=2)] == ["GET", "POST"]
    assert [r["label"] for r in seeded.series("method", sort={"by": "category", "dir": "desc"})] == [
        "PUT",
        "POST",
        "GET",
    ]


def test_ties_on_value_read_in_the_dimensions_order(seeded):
    _log("g", "PUT", ms=7)  # PUT now ties POST at 2
    ranked = seeded.series("method", sort={"by": "value", "dir": "desc"})
    assert [r["label"] for r in ranked] == ["GET", "POST", "PUT"]


def test_a_grain_keeps_its_window_then_sorts_for_display(seeded):
    # Two periods (today, 40 days ago). limit=1 keeps the most recent one whatever the sort.
    recent = seeded.series("timestamp", grain="month", limit=1, sort={"by": "value", "dir": "asc"})
    assert len(recent) == 1 and recent[0]["value"] == 4
    both = seeded.series("timestamp", grain="day", sort={"by": "value", "dir": "desc"})
    assert [r["value"] for r in both] == [4, 2]
    chrono = seeded.series("timestamp", grain="day", sort={"by": "category", "dir": "desc"})
    assert chrono[0]["lo"] > chrono[1]["lo"]


def test_an_unknown_sort_is_refused(seeded):
    with pytest.raises(ValueError, match="unknown sort"):
        seeded.series("method", sort={"by": "size"})


# -- cells ---------------------------------------------------------------------------------------


def test_cells_is_a_complete_grid(seeded):
    cells = seeded.cells("method", "status_code")
    assert len(cells) == 3 * 4  # 3 methods × 4 statuses (200 201 404 500), every combination
    grid = {(c["x"], c["y"]): c["value"] for c in cells}
    assert grid[("GET", 200)] == 2 and grid[("POST", 500)] == 1
    assert grid[("PUT", 404)] == 0  # no rows: a count of nothing is 0
    # Row-major by y, then x, both in value order.
    assert [(c["x"], c["y"]) for c in cells[:4]] == [("GET", 200), ("POST", 200), ("PUT", 200), ("GET", 201)]
    assert cells[0]["x_label"] == "GET" and cells[0]["y_label"] == "200"


def test_an_empty_cell_has_no_average(seeded):
    grid = {
        (c["x"], c["y"]): c["value"]
        for c in seeded.cells("method", "status_code", measure="response_time_ms", agg="avg")
    }
    assert grid[("PUT", 404)] is None and grid[("GET", 200)] == 55.0


def test_cells_takes_a_median_and_the_filters(seeded):
    cells = seeded.cells(
        "method", "status_code", measure="response_time_ms", agg="median", filters={"method__ne": "PUT"}
    )
    assert {c["x"] for c in cells} == {"GET", "POST"}
    assert {(c["x"], c["y"]): c["value"] for c in cells}[("GET", 200)] == 55.0


def test_cells_refuses_a_crowded_axis_instead_of_cutting_it(seeded):
    with pytest.raises(ValueError, match="'path' has 6 distinct values"):
        seeded.cells("path", "method", axis_limit=5)
    with pytest.raises(ValueError, match="must be different"):
        seeded.cells("method", "method")
    with pytest.raises(ValueError, match="unknown dimension2"):
        seeded.cells("method", "nope")


# -- units ---------------------------------------------------------------------------------------


def test_schema_columns_carry_their_unit(seeded):
    units = {c["name"]: c["unit"] for c in seeded.schema()["columns"]}
    assert units["response_time_ms"] == "milliseconds"  # declared
    assert units["ok_pct"] == "percent"  # a percent ratio
    assert units["method"] is None
    assert core._infer_unit("talk_seconds") == "seconds" and core._infer_unit("wait_minutes") == "minutes"


# -- flat lookups --------------------------------------------------------------------------------


def _paths(ds, **filters) -> list[str]:
    return sorted(r["path"] for r in ds.rows(filters=filters, limit=None))


def test_numeric_comparisons(seeded):
    assert _paths(seeded, response_time_ms__gt="40") == ["/x/c", "/x/e"]
    assert _paths(seeded, response_time_ms__lte="10") == ["/x/a", "/x/f"]
    assert _paths(seeded, status_code__gte="400", status_code__lt="500") == ["/x/b"]


def test_text_is_not_and_contains(seeded):
    assert _paths(seeded, method__ne="GET") == ["/x/d", "/x/e", "/x/f"]
    assert _paths(seeded, path__icontains="/X/A") == ["/x/a"]
    # A lookup on a column wins over its bare key.
    assert _paths(seeded, method="GET", method__ne="GET") == ["/x/d", "/x/e", "/x/f"]


def test_a_relative_period_as_a_flat_key(seeded):
    assert len(_paths(seeded, timestamp__period="last_7")) == 4
    assert len(_paths(seeded, timestamp__period="mtd")) == len(_paths(seeded, timestamp__period="this_month"))
    assert _paths(seeded, timestamp__period="previous") == _paths(seeded, timestamp__period="yesterday")


@pytest.mark.parametrize(
    "key,value,why",
    [
        ("timestamp__period", "lastweek", "unknown period"),
        ("timestamp__gte", "2026-13-45", "isn't an ISO date"),
        ("response_time_ms__gt", "fast", "isn't a whole number"),
        ("status_code__gte", "1.5", "isn't a whole number"),  # an integer column would truncate it to >= 1
    ],
)
def test_a_value_that_wont_parse_is_refused_not_dropped(seeded, key, value, why):
    with pytest.raises(ValueError, match=why):
        seeded.rows(filters={key: value})
    assert any(why in p for p in seeded.filter_problems({key: value}))


def test_a_blank_lookup_is_absent(seeded):
    assert len(_paths(seeded, response_time_ms__gt="", timestamp__period="")) == 6
    assert seeded.filter_problems({"response_time_ms__gt": ""}) == []


def test_the_schema_advertises_each_columns_lookups(seeded):
    lookups = {f["name"]: f["lookups"] for f in seeded.schema()["filters"]}
    assert lookups["timestamp"] == ["gte", "gt", "lte", "lt", "period"]
    assert lookups["response_time_ms"] == ["gte", "gt", "lte", "lt"]
    assert lookups["method"] == ["ne", "icontains"]


# -- REST + MCP ----------------------------------------------------------------------------------


@pytest.fixture
def staff_client(client):
    client.force_login(User.objects.create_user("ports-staff", password="x", is_staff=True))
    return client


def test_rest_sort_cells_median_and_a_refused_value(staff_client, seeded):
    series = staff_client.get(reverse("datasets:series", args=[KEY]), {"dimension": "method", "sort": "-value"})
    assert [r["label"] for r in series.json()["series"]] == ["GET", "POST", "PUT"]
    assert (
        staff_client.get(reverse("datasets:series", args=[KEY]), {"dimension": "method", "sort": "big"}).status_code
        == 400
    )

    cells = staff_client.get(
        reverse("datasets:cells", args=[KEY]), {"dimension": "method", "dimension2": "status_code"}
    )
    assert cells.status_code == 200 and len(cells.json()["cells"]) == 12
    assert staff_client.get(reverse("datasets:cells", args=[KEY]), {"dimension": "method"}).status_code == 400

    median = staff_client.get(reverse("datasets:scalar", args=[KEY]), {"agg": "median", "measure": "response_time_ms"})
    assert median.json()["value"] == 30.0
    bad = staff_client.get(reverse("datasets:rows", args=[KEY]), {"timestamp__period": "lastweek"})
    assert bad.status_code == 400 and "unknown period" in bad.json()["error"]


def test_mcp_tool_takes_the_new_arguments(seeded):
    from apps.datasets.mcp_tools import _input_schema
    from apps.datasets.registry import get_def

    props = _input_schema(get_def(KEY))["properties"]
    assert {"timestamp__period", "response_time_ms__gt", "method__ne", "group_by2", "sort"} <= set(props)
    assert "median" in props["agg"]["enum"]


def test_mcp_cells_and_sort(seeded):
    from apps.datasets.tests.test_datasets import _call_handler

    grid = _call_handler(f"query_dataset_{KEY}", {"group_by": "method", "group_by2": "status_code"})
    assert grid["mode"] == "cells" and grid["count"] == 12
    ranked = _call_handler(f"query_dataset_{KEY}", {"group_by": "method", "sort": "-value", "limit": 1})
    assert [r["label"] for r in ranked["series"]] == ["GET"]


# -- the browser ---------------------------------------------------------------------------------


def test_the_browser_shows_a_bound_it_cant_apply(staff_client, seeded):
    resp = staff_client.get(reverse("datasets:browse", args=[KEY]), {"timestamp__gte": "2026-13-45"})
    assert resp.status_code == 200
    assert "can't be applied" in resp.context["filter_error"] and "timestamp__gte" in resp.context["filter_error"]
    assert resp.context["tree_error"] == ""  # it's a filter above, not More conditions
    assert resp.context["page_obj"].paginator.count == 0  # nothing, rather than every row
    html = resp.content.decode()
    assert 'role="alert">These filters can&#x27;t be applied' in html and "a filter above can't be applied" in html
