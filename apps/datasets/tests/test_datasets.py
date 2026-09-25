"""Tests for the @dataset primitive: registry, schema roles, rows, series, MCP.

Uses apps.activity.RequestLog as the source model — it has numeric measures
(response_time_ms, status_code) and categorical dimensions (method, path),
which exercises the dimension/measure classification cleanly.
"""

from __future__ import annotations

import asyncio

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum

from apps.activity.models import RequestLog
from apps.datasets.core import get_dataset, list_datasets
from apps.datasets.registry import dataset

pytestmark = pytest.mark.django_db

User = get_user_model()


# A test dataset registered at import time (unique key, harmless if it lingers).
@dataset(
    "t_requestlog",
    label="Test Request Log",
    description="Request rows for dataset tests.",
    enable_api=True,
    enable_mcp=True,
    mcp_access="readonly",
)
def _t_requestlog(request=None):
    return RequestLog.objects.all()


# A computed/annotated dataset (.values().annotate()) — the shape that used to
# crash .rows() (values-queryset dicts have no .pk).
@dataset(
    "t_by_method",
    label="Requests by method",
    description="Computed rollup for dataset tests.",
    enable_api=True,
    columns=[("method", "text"), ("hits", "integer"), ("total_ms", "integer")],
)
def _t_by_method(request=None):
    return RequestLog.objects.values("method").annotate(
        hits=Count("id"), total_ms=Sum("response_time_ms")
    )


def _seed():
    """3 GET rows + 1 POST row."""
    for i in range(3):
        RequestLog.objects.create(
            path=f"/a/{i}", method="GET", status_code=200, response_time_ms=10 + i
        )
    RequestLog.objects.create(
        path="/b", method="POST", status_code=201, response_time_ms=40
    )


# --- registry + schema ------------------------------------------------------


def test_dataset_is_registered_and_listed():
    keys = {d["key"] for d in list_datasets()}
    assert "t_requestlog" in keys
    api_keys = {d["key"] for d in list_datasets(api_only=True)}
    assert "t_requestlog" in api_keys


def test_schema_classifies_dimension_and_measure():
    schema = get_dataset("t_requestlog").schema()
    roles = {c["name"]: c["role"] for c in schema["columns"]}
    # Numeric fields → measures; text/date/fk → dimensions.
    assert roles["response_time_ms"] == "measure"
    assert roles["status_code"] == "measure"
    assert roles["method"] == "dimension"
    assert roles["timestamp"] == "dimension"
    # Filters carry widget metadata for the builder.
    assert any(f["name"] == "method" for f in schema["filters"])


# --- rows (sub-filtering reduces the row count) -----------------------------


def test_rows_returns_typed_dicts():
    _seed()
    rows = get_dataset("t_requestlog").rows(limit=100)
    assert len(rows) == 4
    assert {"id", "method", "response_time_ms"} <= set(rows[0].keys())


def test_rows_subfilter_reduces_count():
    _seed()
    ds = get_dataset("t_requestlog")
    all_rows = ds.rows(limit=100)
    filtered = ds.rows(filters={"method": "GET"}, limit=100)
    assert len(all_rows) == 4
    assert len(filtered) == 3
    assert all(r["method"] == "GET" for r in filtered)


def test_rows_ordering_applies():
    _seed()
    rows = get_dataset("t_requestlog").rows(ordering="-response_time_ms", limit=100)
    times = [r["response_time_ms"] for r in rows]
    assert times == sorted(times, reverse=True)


# --- series (group-by rollup → [{label, value}]) ----------------------------


def test_series_counts_by_dimension():
    _seed()
    series = get_dataset("t_requestlog").series("method")
    as_dict = {s["label"]: s["value"] for s in series}
    assert as_dict == {"GET": 3, "POST": 1}


def test_series_sum_measure():
    _seed()
    series = get_dataset("t_requestlog").series("method", measure="response_time_ms", agg="sum")
    as_dict = {s["label"]: s["value"] for s in series}
    # GET rows: 10+11+12 = 33; POST: 40
    assert as_dict == {"GET": 33, "POST": 40}


# --- scalar / KPI (ungrouped aggregate → a single number) -------------------


def test_scalar_counts_rows():
    """Round-2 regression: scalar() returns one number, no GROUP BY."""
    _seed()
    assert get_dataset("t_requestlog").scalar() == 4


def test_scalar_sum_measure():
    _seed()
    total = get_dataset("t_requestlog").scalar(measure="response_time_ms", agg="sum")
    assert total == 10 + 11 + 12 + 40  # 73


def test_series_none_dimension_is_scalar():
    """series(None) collapses to a single ungrouped [{label, value}] row."""
    _seed()
    out = get_dataset("t_requestlog").series(None, measure="response_time_ms", agg="sum")
    assert out == [{"label": "sum", "value": 73}]


def test_scalar_empty_dataset_returns_zero():
    """No rows → 0, not None (a KPI tile should show a number)."""
    assert get_dataset("t_requestlog").scalar(measure="response_time_ms", agg="sum") == 0


# --- one filter contract across rows / series / scalar (Round-3 regression) --


def test_scalar_applies_filters():
    """Round-3 regression: scalar(filters=) matches the filtered row count."""
    _seed()
    ds = get_dataset("t_requestlog")
    assert ds.scalar(agg="count") == 4
    # Filtered scalar == count of the filtered rows.
    filtered_rows = ds.rows(filters={"method": "GET"}, limit=100)
    assert ds.scalar(agg="count", filters={"method": "GET"}) == len(filtered_rows) == 3


def test_series_applies_filters():
    """Round-3 regression: a filter reduces the series total."""
    _seed()
    ds = get_dataset("t_requestlog")
    unfiltered = ds.series("status_code")
    filtered = ds.series("status_code", filters={"method": "GET"})
    assert sum(s["value"] for s in unfiltered) == 4
    assert sum(s["value"] for s in filtered) == 3  # POST row dropped
    assert sum(s["value"] for s in filtered) < sum(s["value"] for s in unfiltered)


def test_series_scalar_filters_match_rows_contract():
    """The same filter dict reduces rows, series and scalar identically."""
    _seed()
    ds = get_dataset("t_requestlog")
    flt = {"method": "GET"}
    n_rows = len(ds.rows(filters=flt, limit=100))
    n_series = sum(s["value"] for s in ds.series("status_code", filters=flt))
    n_scalar = ds.scalar(agg="count", filters=flt)
    assert n_rows == n_series == n_scalar == 3


# --- computed (.values().annotate()) datasets -------------------------------


def test_rows_on_values_annotate_dataset():
    """Round-1 regression: .rows() on a values-queryset returns the dicts, no crash."""
    _seed()
    rows = get_dataset("t_by_method").rows(limit=10)
    by_method = {r["method"]: r for r in rows}
    assert by_method["GET"]["hits"] == 3
    assert by_method["GET"]["total_ms"] == 33  # 10+11+12
    assert by_method["POST"]["hits"] == 1
    # Declared columns are present and in order.
    assert set(rows[0].keys()) >= {"method", "hits", "total_ms"}


# --- FK expand (rows) + FK label resolution (series) ------------------------


def _seed_with_user():
    u = User.objects.create(username="alice")
    for i in range(3):
        RequestLog.objects.create(
            path=f"/a/{i}", method="GET", status_code=200,
            response_time_ms=10 + i, user=u,
        )
    RequestLog.objects.create(
        path="/b", method="POST", status_code=201, response_time_ms=40, user=u
    )
    return u


def test_rows_fk_default_is_bare_pk():
    u = _seed_with_user()
    rows = get_dataset("t_requestlog").rows(limit=1)
    assert rows[0]["user"] == u.pk


def test_rows_fk_expand_returns_id_name():
    u = _seed_with_user()
    rows = get_dataset("t_requestlog").rows(limit=1, expand=["user"])
    assert rows[0]["user"] == {"id": u.pk, "name": "alice"}


def test_rows_expand_ignores_non_fk_and_unknown():
    """A bad/non-FK expand param is silently dropped, never raises."""
    _seed_with_user()
    rows = get_dataset("t_requestlog").rows(limit=1, expand=["method", "nope"])
    assert isinstance(rows[0]["method"], str)  # unchanged, not expanded


def test_series_fk_dimension_labels_resolve_to_name():
    _seed_with_user()
    series = get_dataset("t_requestlog").series("user")
    assert series == [{"label": "alice", "value": 4}]


# --- series validation (unknown dimension/measure → ValueError) -------------


def test_series_unknown_dimension_raises_valueerror():
    _seed()
    with pytest.raises(ValueError):
        get_dataset("t_requestlog").series("nope")


def test_series_unknown_measure_raises_valueerror():
    _seed()
    with pytest.raises(ValueError):
        get_dataset("t_requestlog").series("method", measure="nope", agg="sum")


# --- MCP tools --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_dataset_tools_registered():
    """Re-register dataset MCP tools each test (the MCP suite wipes the registry)."""
    from apps.datasets.mcp_tools import register_dataset_tools

    register_dataset_tools()


def _call_handler(name, args, *, user=None):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=user, token=None))
    try:
        handler = TOOL_HANDLERS[name]
        if asyncio.iscoroutinefunction(handler):
            return async_to_sync(lambda: handler(args))()
        return handler(args)
    finally:
        reset_context(token)


def test_mcp_tools_registered():
    from apps.mcp.server import TOOL_REGISTRY

    assert "list_datasets" in TOOL_REGISTRY
    assert "query_dataset_t_requestlog" in TOOL_REGISTRY
    td = TOOL_REGISTRY["query_dataset_t_requestlog"]
    assert td.requires_access == "readonly"
    # Filter fields surface as input properties.
    assert "method" in td.input_schema["properties"]
    assert "group_by" in td.input_schema["properties"]


def test_list_datasets_tool_returns_key():
    out = _call_handler("list_datasets", {})
    keys = {d["key"] for d in out["results"]}
    assert "t_requestlog" in keys


def test_query_dataset_tool_returns_rows():
    _seed()
    out = _call_handler("query_dataset_t_requestlog", {"method": "GET", "limit": 100})
    assert out["mode"] == "rows"
    assert out["count"] == 3
    assert all(r["method"] == "GET" for r in out["results"])


def test_query_dataset_tool_series_mode():
    _seed()
    out = _call_handler("query_dataset_t_requestlog", {"group_by": "method"})
    assert out["mode"] == "series"
    as_dict = {s["label"]: s["value"] for s in out["series"]}
    assert as_dict == {"GET": 3, "POST": 1}


def test_query_dataset_tool_bad_group_by_returns_error():
    """Round-1 regression: bad group_by → clean {error}, not an uncaught FieldError."""
    _seed()
    out = _call_handler("query_dataset_t_requestlog", {"group_by": "nope"})
    assert "error" in out


def test_query_dataset_tool_scalar_mode():
    """Round-2 regression: scalar=true → one KPI number (no group_by)."""
    _seed()
    out = _call_handler(
        "query_dataset_t_requestlog",
        {"scalar": True, "agg": "sum", "measure": "response_time_ms"},
    )
    assert out["mode"] == "scalar"
    assert out["value"] == 10 + 11 + 12 + 40  # 73


def test_query_dataset_tool_scalar_input_advertised():
    from apps.mcp.server import TOOL_REGISTRY

    props = TOOL_REGISTRY["query_dataset_t_requestlog"].input_schema["properties"]
    assert "scalar" in props


def test_query_dataset_tool_series_honors_filters():
    """Round-3 regression: filter args reduce the series in group_by mode."""
    _seed()
    out = _call_handler(
        "query_dataset_t_requestlog", {"group_by": "status_code", "method": "GET"}
    )
    assert out["mode"] == "series"
    assert sum(s["value"] for s in out["series"]) == 3  # only the 3 GET rows


def test_query_dataset_tool_scalar_honors_filters():
    """Round-3 regression: filter args reduce the scalar count."""
    _seed()
    out = _call_handler(
        "query_dataset_t_requestlog", {"scalar": True, "agg": "count", "method": "GET"}
    )
    assert out["mode"] == "scalar"
    assert out["value"] == 3


# --- REST surface: Bearer-or-session auth (Round-1 regression) --------------


@pytest.fixture
def _api_token(db):
    from apps.smallstack.models import APIToken

    admin = User.objects.create_user(
        username="rest_admin", password="x", is_staff=True
    )
    _token, raw = APIToken.create_token(admin, name="test")
    return raw


def test_rest_rejects_anonymous_with_json_401(client):
    """No credential → JSON 401, never a 302 redirect to an HTML login page."""
    resp = client.get("/smallstack/datasets/")
    assert resp.status_code == 401
    assert resp["Content-Type"].startswith("application/json")


def test_rest_accepts_bearer_token(client, _api_token):
    """A valid Bearer token reaches the datasets surface (the headline blocker)."""
    resp = client.get(
        "/smallstack/datasets/",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    keys = {d["key"] for d in resp.json()["results"]}
    assert "t_requestlog" in keys


def test_rest_bearer_non_staff_gets_json_403(client, db):
    from apps.smallstack.models import APIToken

    user = User.objects.create_user(username="plain", password="x", is_staff=False)
    _token, raw = APIToken.create_token(user, name="t", access_level="staff")
    resp = client.get(
        "/smallstack/datasets/", HTTP_AUTHORIZATION=f"Bearer {raw}"
    )
    assert resp.status_code == 403
    assert resp["Content-Type"].startswith("application/json")


def test_rest_series_bad_dimension_returns_400(client, _api_token):
    _seed()
    resp = client.get(
        "/smallstack/datasets/t_requestlog/series/?dimension=nope",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 400


def test_rest_rows_expand_returns_id_name(client, _api_token):
    _seed_with_user()
    resp = client.get(
        "/smallstack/datasets/t_requestlog/?expand=user&limit=1",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    user_val = resp.json()["results"][0]["user"]
    assert set(user_val.keys()) == {"id", "name"}


def test_rest_rows_string_offset_paginates(client, _api_token):
    """Regression: query-string ``offset``/``limit`` arrive as strings; the view
    must int-coerce them before ``rows()`` slices with them. Before the fix,
    ``?offset=2`` crashed with a ``str + int`` TypeError (HTTP 500)."""
    # Seed rows under a unique status_code so we can filter to exactly this
    # test's data (isolating from any rows a prior transactional test left) and
    # order by response_time_ms (unique per row) for a deterministic page order.
    for i in range(4):
        RequestLog.objects.create(
            path=f"/pg/{i}", method="GET", status_code=418, response_time_ms=100 + i
        )
    q = "status_code=418&ordering=response_time_ms"
    base = client.get(
        f"/smallstack/datasets/t_requestlog/?{q}&limit=2&offset=0",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert base.status_code == 200
    paged = client.get(
        f"/smallstack/datasets/t_requestlog/?{q}&limit=2&offset=2",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert paged.status_code == 200
    assert paged.json()["offset"] == 2
    # Distinct pages — no overlap between offset=0 and offset=2.
    first_ids = {r["id"] for r in base.json()["results"]}
    second_ids = {r["id"] for r in paged.json()["results"]}
    assert len(first_ids) == 2 and len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)


def test_rest_rows_junk_offset_falls_back(client, _api_token):
    """A non-numeric ``offset`` degrades to 0 rather than 500ing."""
    _seed()
    resp = client.get(
        "/smallstack/datasets/t_requestlog/?offset=nope&limit=abc",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    assert resp.json()["offset"] == 0


# --- REST: CSV export + scalar route (Round-2 regressions) ------------------


def test_rest_rows_csv_export(client, _api_token):
    """Round-2: ?format=csv streams text/csv with a header row + attachment."""
    _seed()
    resp = client.get(
        "/smallstack/datasets/t_requestlog/?format=csv&limit=100",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"]
    assert "t_requestlog.csv" in resp["Content-Disposition"]
    lines = resp.content.decode().splitlines()
    assert "method" in lines[0].split(",")  # header carries the schema columns
    assert len(lines) >= 2  # header + at least one data row


def test_rest_rows_csv_export_is_capped_loudly(client, _api_token, settings):
    """An export over the cap is a 400, never an unbounded (or silently cut) file. (Audit C9c.)"""
    _seed()
    settings.SMALLSTACK_DATASET_CSV_MAX_ROWS = 1
    resp = client.get(
        "/smallstack/datasets/t_requestlog/?format=csv",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 400
    assert "SMALLSTACK_DATASET_CSV_MAX_ROWS" in resp.json()["error"]


def test_rest_scalar_route(client, _api_token):
    """Round-2: /<key>/scalar/ returns a single {value}, no GROUP BY."""
    _seed()
    resp = client.get(
        "/smallstack/datasets/t_requestlog/scalar/?agg=count",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agg"] == "count"
    assert isinstance(body["value"], int)


def test_rest_series_no_dimension_is_scalar(client, _api_token):
    """Round-2: /series/ with no dimension collapses to a scalar (no 400)."""
    _seed()
    resp = client.get(
        "/smallstack/datasets/t_requestlog/series/?agg=sum&measure=response_time_ms",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dimension"] is None
    assert body["series"][0]["label"] == "sum"


def test_rest_scalar_bad_measure_returns_400(client, _api_token):
    _seed()
    resp = client.get(
        "/smallstack/datasets/t_requestlog/scalar/?agg=sum&measure=nope",
        HTTP_AUTHORIZATION=f"Bearer {_api_token}",
    )
    assert resp.status_code == 400


def test_rest_series_applies_query_filters(client, _api_token):
    """Round-3 regression: ?dimension=X&<filter>=<val> changes the series.

    The seed has GET + POST rows; grouping status_code and filtering method=POST
    must return only the POST bucket (status 201), proving the filter is applied.
    (Uses relative comparison — the request-log middleware also logs the client's
    own GETs, so absolute counts aren't asserted.)
    """
    _seed()
    base = "/smallstack/datasets/t_requestlog/series/?dimension=status_code"
    auth = {"HTTP_AUTHORIZATION": f"Bearer {_api_token}"}
    all_labels = {s["label"] for s in client.get(base, **auth).json()["series"]}
    post_labels = {
        s["label"] for s in client.get(base + "&method=POST", **auth).json()["series"]
    }
    # Seeded POST row has status 201; the 200 bucket must drop out under the filter.
    assert "201" in post_labels
    assert post_labels != all_labels
    assert "200" not in post_labels


def test_rest_scalar_applies_query_filters(client, _api_token):
    """Round-3 regression: a filter on the scalar route lowers the count."""
    _seed()
    auth = {"HTTP_AUTHORIZATION": f"Bearer {_api_token}"}
    base = "/smallstack/datasets/t_requestlog/scalar/?agg=count"
    total = client.get(base, **auth).json()["value"]
    post_only = client.get(base + "&method=POST", **auth).json()["value"]
    assert post_only < total


# --- R3: filterable= (with deprecated filters= alias) -----------------------


def test_filterable_restricts_filter_fields():
    from apps.datasets.registry import dataset, unregister

    @dataset("t_filterable", filterable=["method"])
    def _t_filterable(request=None):
        return RequestLog.objects.all()

    try:
        names = {f["name"] for f in get_dataset("t_filterable").schema()["filters"]}
        assert names == {"method"}
    finally:
        unregister("t_filterable")


def test_filters_kwarg_is_deprecated_alias():
    from apps.datasets.registry import dataset, get_def, unregister

    with pytest.warns(DeprecationWarning):
        @dataset("t_legacy_filters", filters=["method"])
        def _t_legacy(request=None):
            return RequestLog.objects.all()

    try:
        # Old kwarg still maps to filterable.
        assert get_def("t_legacy_filters").filterable == ["method"]
        names = {f["name"] for f in get_dataset("t_legacy_filters").schema()["filters"]}
        assert names == {"method"}
    finally:
        unregister("t_legacy_filters")


# --- R4: public queryset() seam ---------------------------------------------


def test_queryset_seam_matches_rows_unlimited():
    _seed()
    ds = get_dataset("t_requestlog")
    flt = {"method": "GET"}
    # count parity with an unlimited rows() over the same filters
    assert ds.queryset(filters=flt).count() == len(ds.rows(filters=flt, limit=500))


def test_queryset_seam_supports_reporter_style_aggregation():
    from django.db.models import Sum

    _seed()
    ds = get_dataset("t_requestlog")
    qs = ds.queryset(filters={"method": "GET"})
    # a higher layer composes its own aggregation on the returned queryset
    total = qs.aggregate(s=Sum("response_time_ms"))["s"]
    assert total == 10 + 11 + 12  # the three seeded GET rows


# --- R5: pagination (offset + total) ----------------------------------------


def test_rows_offset_pages_through_without_overlap():
    for i in range(5):
        RequestLog.objects.create(
            path=f"/p/{i}", method="GET", status_code=200, response_time_ms=i
        )
    ds = get_dataset("t_requestlog")
    p1 = ds.rows(ordering="response_time_ms", limit=2, offset=0)
    p2 = ds.rows(ordering="response_time_ms", limit=2, offset=2)
    p3 = ds.rows(ordering="response_time_ms", limit=2, offset=4)
    ids = [r["id"] for r in p1 + p2 + p3]
    assert len(ids) == 5
    assert len(set(ids)) == 5  # disjoint, gap-free


def test_rows_limit_none_returns_whole_set():
    _seed()  # 4 rows
    ds = get_dataset("t_requestlog")
    assert len(ds.rows(limit=None)) == 4


def test_count_matches_unlimited_rows():
    _seed()
    ds = get_dataset("t_requestlog")
    flt = {"method": "GET"}
    assert ds.count(filters=flt) == len(ds.rows(filters=flt, limit=None))  # 3


def test_rest_rows_envelope_has_total_and_offset(client, _api_token):
    _seed()  # 4 rows
    auth = {"HTTP_AUTHORIZATION": f"Bearer {_api_token}"}
    body = client.get(
        "/smallstack/datasets/t_requestlog/?limit=2&offset=2", **auth
    ).json()
    assert body["total"] == 4        # full matching count
    assert body["count"] == 2        # this page
    assert body["offset"] == 2


# --- R6: declared ratio measures --------------------------------------------


@dataset(
    "t_ratio",
    label="Ratio test",
    measures=[
        ("code_ratio", "status_code", "response_time_ms", "ratio"),
        ("code_pct", "status_code", "response_time_ms", "percent"),
    ],
)
def _t_ratio(request=None):
    return RequestLog.objects.all()


def _seed_ratio():
    # GET group: (1/1) and (1/100) — avg of per-row ratios = 0.505,
    # but sum/sum = 2/101 ≈ 0.0198. They disagree, so the test proves sum/sum.
    a = RequestLog.objects.create(path="/a", method="GET", status_code=1, response_time_ms=1)
    b = RequestLog.objects.create(path="/b", method="GET", status_code=1, response_time_ms=100)
    # POST group: denominator sums to 0 → ratio must be None (empty denom).
    c = RequestLog.objects.create(path="/c", method="POST", status_code=5, response_time_ms=0)
    return a, b, c


def test_declared_ratio_is_sum_over_sum_not_average():
    _seed_ratio()
    series = get_dataset("t_ratio").series("method", measure="code_ratio")
    by = {row["label"]: row["value"] for row in series}
    assert by["GET"] == round(2 / 101, 2)   # 0.02 — NOT avg(1.0, 0.01)=0.505
    assert by["POST"] is None                # empty denominator → None, not 0


def test_declared_ratio_percent_scales_by_100():
    _seed_ratio()
    val = get_dataset("t_ratio").scalar(measure="code_pct")
    assert val == round(7 / 101 * 100, 2)    # sum(num)=7, sum(denom)=101


def test_declared_measure_appears_in_schema():
    cols = {c["name"]: c for c in get_dataset("t_ratio").schema()["columns"]}
    assert cols["code_ratio"]["role"] == "measure"
    assert cols["code_ratio"]["computed"] is True


# --- R7: explicit date-range filters ----------------------------------------


def _seed_dates():
    import datetime as _dt

    from django.utils import timezone as _tz

    days = [1, 4, 8]  # July 1, 4, 8 2026
    for d in days:
        obj = RequestLog.objects.create(
            path=f"/d{d}", method="GET", status_code=200, response_time_ms=1
        )
        # timestamp is auto_now_add — bypass it with update().
        stamp = _tz.make_aware(_dt.datetime(2026, 7, d, 12, 0))
        RequestLog.objects.filter(pk=obj.pk).update(timestamp=stamp)


def test_date_range_gte_lt_is_half_open():
    import datetime as _dt

    from django.utils import timezone as _tz

    _seed_dates()
    ds = get_dataset("t_requestlog")
    # tz-aware ISO bounds (same tz as the seed's make_aware) — string inputs, as
    # the dataset filter API expects, but offset-aware so Django doesn't warn
    # about a naive datetime against the aware timestamp field.
    lo = _tz.make_aware(_dt.datetime(2026, 7, 1)).isoformat()
    hi = _tz.make_aware(_dt.datetime(2026, 7, 8)).isoformat()
    rows = ds.rows(
        filters={"timestamp__gte": lo, "timestamp__lt": hi},
        limit=100,
    )
    # July 1 and 4 included; July 8 excluded (half-open).
    assert len(rows) == 2


def test_schema_date_filter_advertises_range():
    filt = {f["name"]: f for f in get_dataset("t_requestlog").schema()["filters"]}
    assert filt["timestamp"].get("range") is True


# --- R8: bucketed grouping (count-only) + drilldown -------------------------


def _seed_methods(counts):
    """counts: {method: n}. response_time_ms = index within method."""
    for method, n in counts.items():
        for i in range(n):
            RequestLog.objects.create(
                path="/x", method=method, status_code=200, response_time_ms=i
            )


def test_bucket_categorical_with_other_reconciles():
    _seed_methods({"GET": 3, "POST": 2, "PUT": 1})  # 6 total
    ds = get_dataset("t_requestlog")
    dim = {
        "field": "method",
        "buckets": [
            {"key": "g", "label": "GET", "value": "GET"},
            {"key": "other", "label": "Other", "other": True},
        ],
    }
    s = {b["key"]: b for b in ds.series(dim)}
    assert (s["g"]["value"], s["other"]["value"]) == (3, 3)  # POST+PUT → other
    # part-to-whole sums to the scope total (no silently dropped rows)
    assert sum(b["value"] for b in s.values()) == ds.count() == 6
    # categorical buckets carry no numeric bounds
    assert s["g"]["lo"] is None and s["g"]["hi"] is None
    # drilldown parity: rows behind each bucket == its count
    assert len(ds.rows(dimension=dim, bucket="g", limit=None)) == 3
    assert len(ds.rows(dimension=dim, bucket="other", limit=None)) == 3


def test_bucket_values_in_group():
    _seed_methods({"GET": 2, "POST": 1, "PUT": 1})
    ds = get_dataset("t_requestlog")
    dim = {
        "field": "method",
        "buckets": [
            {"key": "writes", "label": "Writes", "values": ["POST", "PUT"]},
            {"key": "other", "label": "Other", "other": True},
        ],
    }
    s = {b["key"]: b["value"] for b in ds.series(dim)}
    assert s == {"writes": 2, "other": 2}  # POST+PUT grouped; GET → other


def test_bucket_numeric_bands_half_open():
    # response_time_ms = 0,1,2 (GET), 0,1 (POST) → values 0,1,2,0,1
    _seed_methods({"GET": 3, "POST": 2})
    ds = get_dataset("t_requestlog")
    dim = {
        "field": "response_time_ms",
        "buckets": [
            {"key": "lo", "label": "0–1", "lo": 0, "hi": 1},   # [0,1): value 0 → 2 rows
            {"key": "hi", "label": "1+", "lo": 1, "hi": None},  # [1,∞): 1 and 2 → 3 rows
        ],
    }
    s = {b["key"]: b["value"] for b in ds.series(dim)}
    assert s == {"lo": 2, "hi": 3}
    # half-open: no double-count, bands sum to total
    assert s["lo"] + s["hi"] == ds.count() == 5


def test_bucket_auto_derives_capped_with_other_and_stable_keys():
    _seed_methods({"GET": 3, "POST": 2, "PUT": 1})
    ds = get_dataset("t_requestlog")
    dim = {"field": "method", "auto": {"limit": 2}}
    s = ds.series(dim)
    keys = [b["key"] for b in s]
    # top-2 by volume get value buckets, keyed v:<value>; the rest → other
    assert keys == ["v:GET", "v:POST", "other"]
    assert [b["value"] for b in s] == [3, 2, 1]
    assert sum(b["value"] for b in s) == ds.count() == 6
    # key stability: a filtered series derives buckets from the UNNARROWED scope,
    # so the same keys come back (zero-counted where the filter excludes them).
    filtered = ds.series(dim, filters={"method": "PUT"})
    assert [b["key"] for b in filtered] == ["v:GET", "v:POST", "other"]
    fvals = {b["key"]: b["value"] for b in filtered}
    assert (fvals["v:GET"], fvals["v:POST"], fvals["other"]) == (0, 0, 1)


def test_bucket_unknown_key_drilldown_raises():
    _seed_methods({"GET": 1})
    ds = get_dataset("t_requestlog")
    dim = {"field": "method", "buckets": [{"key": "g", "label": "GET", "value": "GET"}]}
    with pytest.raises(ValueError):
        ds.rows(dimension=dim, bucket="nope")


def test_rest_bucketed_series_and_drilldown(client, _api_token):
    _seed_methods({"GET": 3, "POST": 2, "PUT": 1})
    auth = {"HTTP_AUTHORIZATION": f"Bearer {_api_token}"}
    buckets = '[{"key":"g","label":"GET","value":"GET"},{"key":"other","label":"Other","other":true}]'
    from urllib.parse import quote

    url = f"/smallstack/datasets/t_requestlog/series/?dimension=method&buckets={quote(buckets)}"
    s = {b["key"]: b["value"] for b in client.get(url, **auth).json()["series"]}
    assert s == {"g": 3, "other": 3}
    # drilldown via the rows route: total reflects the bucket
    drill = client.get(
        f"/smallstack/datasets/t_requestlog/?dimension=method&buckets={quote(buckets)}&bucket=other",
        **auth,
    ).json()
    assert drill["total"] == 3


def test_mcp_bucketed_series_auto():
    _seed_methods({"GET": 3, "POST": 2, "PUT": 1})
    from apps.datasets.mcp_tools import _RESERVED, _bucket_dimension

    assert "buckets" in _RESERVED  # not treated as a filter
    dim = _bucket_dimension("method", {"auto": True, "auto_limit": 2})
    s = get_dataset("t_requestlog").series(dim)
    assert [b["key"] for b in s] == ["v:GET", "v:POST", "other"]
