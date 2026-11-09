"""The filter tree (nested AND/OR, stored) + relative periods.

The invariant under test is the one the v0.21.11 fail-open bug taught: a stored
filter either narrows the rows exactly as written or raises — it never drops a
condition and returns MORE rows. So every test that applies a tree asserts the
count actually narrowed, across every read path (rows / count / series /
scalar / REST / MCP), and every malformed tree must raise, not widen.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.activity.models import RequestLog
from apps.datasets.capabilities import DATE, DIMENSION, MEASURE, capabilities, missing_for
from apps.datasets.core import get_dataset
from apps.datasets.dateranges import is_period, period_label, relative_dates, relative_range
from apps.datasets.filter_tree import (
    FilterTreeError,
    and_trees,
    compile_filter_tree,
    describe_filter_tree,
    normalize_op,
    tree_fields,
)
from apps.datasets.registry import dataset

pytestmark = pytest.mark.django_db

User = get_user_model()


@dataset(
    "t_tree_log",
    label="Tree Log",
    columns=["method", "path", "status_code", "response_time_ms", "timestamp", "user"],
    filterable=["method", "path", "status_code", "response_time_ms", "timestamp", "user"],
    enable_api=True,
    enable_mcp=True,
    mcp_access="readonly",
)
def _t_tree_log(request=None):
    return RequestLog.objects.all()


def _seed():
    """GET/200 ×3 (10, 11, 12 ms) · POST/201 (40 ms) · DELETE/500 (90 ms, 40 days old)."""
    for i in range(3):
        RequestLog.objects.create(path=f"/a/{i}", method="GET", status_code=200, response_time_ms=10 + i)
    RequestLog.objects.create(path="/b", method="POST", status_code=201, response_time_ms=40)
    old = RequestLog.objects.create(path="/c", method="DELETE", status_code=500, response_time_ms=90)
    RequestLog.objects.filter(pk=old.pk).update(timestamp=timezone.now() - timedelta(days=40))


def _ds():
    ds = get_dataset("t_tree_log")
    assert ds is not None
    return ds


# -- periods (pure) -----------------------------------------------------------


def test_every_listed_period_resolves():
    from apps.datasets.dateranges import RELATIVE_PERIODS

    for key, _label in RELATIVE_PERIODS:
        since, until = relative_dates(key, date(2026, 5, 14))
        assert since < until, key


def test_a_key_from_the_original_vocabulary_still_resolves():
    """call_stats stored "previous" before the port renamed it "yesterday"."""
    from apps.datasets.dateranges import RELATIVE_PERIODS

    today = date(2026, 5, 14)
    assert is_period("previous") and period_label("previous") == "Yesterday"
    assert relative_dates("previous", today) == relative_dates("yesterday", today)
    assert relative_range("previous") == relative_range("yesterday")
    assert "previous" not in dict(RELATIVE_PERIODS)  # read, never offered
    assert is_period("last_60")  # dropped from the list, still resolved as last_<N>


def test_the_renamed_dataset_members_still_answer():
    import warnings

    ds = get_dataset("smallstack_requests")
    assert ds is not None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert ds.has_detail == ds.has_links()
        assert ds._fk_label_map("method", []) == ds.value_labels("method", [])
    assert [w.category for w in caught] == [DeprecationWarning, DeprecationWarning]


def test_month_and_quarter_boundaries_wrap_the_year():
    assert relative_dates("pmtd", date(2026, 1, 9)) == (date(2025, 12, 1), date(2026, 1, 1))
    assert relative_dates("pqtr", date(2026, 2, 9)) == (date(2025, 10, 1), date(2026, 1, 1))
    assert relative_dates("qtd", date(2026, 8, 9)) == (date(2026, 7, 1), date(2026, 8, 10))


def test_to_date_periods_include_all_of_today():
    today = date(2026, 5, 14)
    assert relative_dates("today", today) == (today, today + timedelta(days=1))
    assert relative_dates("mtd", today) == (date(2026, 5, 1), date(2026, 5, 15))


def test_previous_week_abuts_this_week():
    today = date(2026, 5, 14)  # a Thursday
    wtd_since, _ = relative_dates("wtd", today)
    p_since, p_until = relative_dates("pwtd", today)
    assert wtd_since == date(2026, 5, 11) and p_until == wtd_since
    assert (p_until - p_since).days == 7


def test_rolling_periods_are_generic():
    today = date(2026, 5, 14)
    assert relative_dates("last_45", today) == (today - timedelta(days=44), today + timedelta(days=1))
    assert relative_dates("next_10", today) == (today, today + timedelta(days=10))
    assert period_label("last_45") == "Last 45 days"
    assert is_period("next_3") and not is_period("last_0") and not is_period("bogus")


def test_unknown_period_is_none_not_unbounded():
    assert relative_dates("bogus") is None
    assert relative_range("bogus") is None


def test_relative_range_is_aware_local_midnight():
    since, until = relative_range("today")
    assert timezone.is_aware(since)
    assert timezone.localtime(since).hour == 0 and (until - since) == timedelta(days=1)


# -- the compiler (pure) --------------------------------------------------------

COLS = {"method": "string", "status_code": "integer", "timestamp": "datetime", "user": "fk", "flag": "boolean"}


def _compile(tree):
    return compile_filter_tree(tree, columns=COLS, filterable=set(COLS))


def test_empty_tree_is_no_filter():
    assert _compile(None) is None
    assert _compile({}) is None


@pytest.mark.parametrize(
    "tree, fragment",
    [
        ({"field": "stauts", "op": "=", "value": 1}, "unknown field 'stauts'"),
        ({"field": "method", "op": "~", "value": "GET"}, "unknown operator"),
        ({"field": "method", "op": ">", "value": "GET"}, "does not apply"),
        ({"field": "status_code", "op": "=", "value": "abc"}, "expected a number"),
        ({"field": "timestamp", "op": "period", "value": "someday"}, "unknown period"),
        ({"field": "method", "op": "in", "value": []}, "non-empty list"),
        ({"field": "method", "op": "=", "value": None}, "isnull"),
        ({"and": []}, "non-empty list"),
        ({"and": [{"field": "method", "op": "=", "value": "GET"}], "or": []}, "not several"),
        ({"field": "method", "op": "=", "value": "GET", "extra": 1}, "unexpected key"),
        ("method = GET", "expected an object"),
    ],
)
def test_malformed_trees_raise_never_drop(tree, fragment):
    with pytest.raises(FilterTreeError) as exc:
        _compile(tree)
    assert fragment in str(exc.value)


def test_every_problem_is_reported_with_its_path():
    with pytest.raises(FilterTreeError) as exc:
        _compile({"and": [{"field": "nope", "op": "=", "value": 1}, {"or": [{"field": "method", "op": "?"}]}]})
    problems = exc.value.problems
    assert len(problems) == 2
    assert problems[0].startswith("and[0].field") and problems[1].startswith("and[1].or[0].op")


def test_not_filterable_field_is_rejected():
    with pytest.raises(FilterTreeError, match="not filterable"):
        compile_filter_tree({"field": "method", "op": "=", "value": "x"}, columns=COLS, filterable={"status_code"})


def test_aliases_normalise():
    assert normalize_op("ne") == "!=" and normalize_op("Before") == "<" and normalize_op("relative") == "period"
    assert normalize_op("bogus") is None


def test_depth_and_size_guards():
    deep: dict = {"field": "method", "op": "=", "value": "GET"}
    for _ in range(12):
        deep = {"not": deep}
    with pytest.raises(FilterTreeError, match="deeper"):
        _compile(deep)
    wide = {"or": [{"field": "method", "op": "=", "value": str(i)} for i in range(150)]}
    with pytest.raises(FilterTreeError, match="more than"):
        _compile(wide)


def test_describe_reads_like_a_sentence():
    tree = {
        "and": [
            {"field": "method", "op": "=", "value": "GET"},
            {"or": [{"field": "status_code", "op": ">=", "value": 500}, {"field": "flag", "op": "isnull"}]},
            {"field": "timestamp", "op": "period", "value": "mtd"},
        ]
    }
    text = describe_filter_tree(tree, {"method": "Method", "timestamp": "Logged"})
    assert text == "Method = GET AND (status_code ≥ 500 OR flag is empty) AND Logged: Month to date"
    assert describe_filter_tree({}) == "All rows"
    assert "?" in describe_filter_tree({"and": ["junk"]})  # broken filters still display


def test_and_trees_and_fields():
    a = {"field": "method", "op": "=", "value": "GET"}
    assert and_trees({}, None) == {}
    assert and_trees(a, {}) == a
    assert and_trees(a, a) == {"and": [a, a]}
    assert and_trees({"and": [a, a]}, a) == {"and": [a, a, a]}  # flattened, not nested
    assert tree_fields({"or": [a, {"not": {"field": "user", "op": "isnull"}}]}) == {"method", "user"}


# -- every read path narrows identically -----------------------------------------

GET_OR_POST = {"or": [{"field": "method", "op": "=", "value": "GET"}, {"field": "method", "op": "=", "value": "POST"}]}


def test_or_tree_narrows_rows_count_series_scalar():
    _seed()
    ds = _ds()
    assert ds.count() == 5
    assert ds.count(filter_tree=GET_OR_POST) == 4
    assert len(ds.rows(filter_tree=GET_OR_POST, limit=None)) == 4
    assert ds.scalar(filter_tree=GET_OR_POST) == 4
    assert ds.scalar(measure="response_time_ms", agg="sum", filter_tree=GET_OR_POST) == 10 + 11 + 12 + 40
    series = {r["label"]: r["value"] for r in ds.series("method", filter_tree=GET_OR_POST)}
    assert series == {"GET": 3, "POST": 1}
    assert ds.queryset(filter_tree=GET_OR_POST).count() == 4


def test_tree_ands_with_flat_filters():
    _seed()
    assert _ds().count(filters={"status_code": "200"}, filter_tree=GET_OR_POST) == 3


def test_numeric_between_in_and_not():
    _seed()
    ds = _ds()
    assert ds.count(filter_tree={"field": "response_time_ms", "op": "between", "value": 11, "value2": 40}) == 3
    assert ds.count(filter_tree={"field": "status_code", "op": "in", "value": ["201", 500]}) == 2
    assert ds.count(filter_tree={"not": {"field": "method", "op": "=", "value": "GET"}}) == 2
    assert ds.count(filter_tree={"field": "path", "op": "contains", "value": "/A/"}) == 3


def test_period_leaf_narrows_by_date():
    _seed()
    ds = _ds()
    assert ds.count(filter_tree={"field": "timestamp", "op": "period", "value": "last_30"}) == 4
    assert ds.count(filter_tree={"field": "timestamp", "op": "period", "value": "last_90"}) == 5


def test_fk_and_isnull():
    _seed()
    user = User.objects.create_user("treeuser", password="x")
    RequestLog.objects.filter(method="POST").update(user=user)
    ds = _ds()
    assert ds.count(filter_tree={"field": "user", "op": "=", "value": user.pk}) == 1
    assert ds.count(filter_tree={"field": "user", "op": "isnull", "value": False}) == 1
    assert ds.count(filter_tree={"field": "user", "op": "isnull"}) == 4


def test_bad_tree_raises_on_every_read_path():
    _seed()
    ds = _ds()
    bad = {"field": "renamed_column", "op": "=", "value": "x"}
    for call in (
        lambda: ds.count(filter_tree=bad),
        lambda: ds.rows(filter_tree=bad),
        lambda: ds.scalar(filter_tree=bad),
        lambda: ds.series("method", filter_tree=bad),
    ):
        with pytest.raises(FilterTreeError):
            call()
    assert ds.validate_filter_tree(bad) == ["filter.field: unknown field 'renamed_column'"]
    assert ds.validate_filter_tree(GET_OR_POST) == []


def test_distinct_agg_counts_distinct_values():
    _seed()
    assert _ds().scalar(measure="method", agg="distinct") == 3


# -- schema advertises what a builder needs ---------------------------------------


def test_schema_carries_ops_periods_aggs_and_capabilities():
    schema = _ds().schema()
    by_name = {f["name"]: f for f in schema["filters"]}
    assert "period" in by_name["timestamp"]["ops"]
    assert {"key": "mtd", "label": "Month to date"} in by_name["timestamp"]["periods"]
    assert "contains" in by_name["method"]["ops"] and "period" not in by_name["method"]["ops"]
    assert "distinct" in schema["aggs"]
    assert {MEASURE, DIMENSION, DATE} <= set(schema["capabilities"])


def test_capabilities_and_missing_for():
    caps = capabilities({"columns": [{"role": "dimension", "type": "string"}]})
    assert caps == {DIMENSION}
    assert missing_for({DATE, DIMENSION}, caps) == {DATE}


# -- REST + MCP -------------------------------------------------------------------


@pytest.fixture
def staff_client(client):
    client.force_login(User.objects.create_user("treestaff", password="x", is_staff=True))
    return client


def test_rest_filter_tree_param_narrows_and_reports_total(staff_client):
    _seed()
    # Exclude the request log rows these very calls create (activity middleware).
    own = {"not": {"field": "path", "op": "contains", "value": reverse("datasets:list")}}
    tree = json.dumps({"and": [GET_OR_POST, own]})
    data = staff_client.get(reverse("datasets:rows", args=["t_tree_log"]), {"filter_tree": tree}).json()
    assert data["total"] == 4 and data["count"] == 4
    scalar = staff_client.get(reverse("datasets:scalar", args=["t_tree_log"]), {"filter_tree": tree}).json()
    assert scalar["value"] == 4


def test_rest_bad_tree_is_400_not_everything(staff_client):
    _seed()
    bad = json.dumps({"field": "nope", "op": "=", "value": 1})
    rows = reverse("datasets:rows", args=["t_tree_log"])
    for url in (rows, reverse("datasets:scalar", args=["t_tree_log"])):
        resp = staff_client.get(url, {"filter_tree": bad})
        assert resp.status_code == 400 and "unknown field" in resp.json()["error"]
    assert staff_client.get(rows, {"filter_tree": "{not json"}).status_code == 400


def _call(name, args, user=None):
    from apps.datasets.mcp_tools import register_dataset_tools
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    register_dataset_tools()
    token = set_context(ToolContext(user=user, token=None))
    try:
        handler = TOOL_HANDLERS[name]
        if asyncio.iscoroutinefunction(handler):
            return async_to_sync(lambda: handler(args))()
        return handler(args)
    finally:
        reset_context(token)


def test_mcp_query_tool_takes_filter_tree():
    _seed()
    out = _call("query_dataset_t_tree_log", {"scalar": True, "filter_tree": GET_OR_POST})
    assert out["value"] == 4
    err = _call("query_dataset_t_tree_log", {"scalar": True, "filter_tree": {"field": "x", "op": "=", "value": 1}})
    assert "unknown field" in err["error"]


def test_mcp_describe_dataset():
    user = User.objects.create_user("treeagent", password="x")
    schema = _call("describe_dataset", {"key": "t_tree_log"}, user=user)
    assert schema["key"] == "t_tree_log" and schema["filters"]
    assert "error" in _call("describe_dataset", {"key": "no_such"}, user=user)


def test_mcp_describe_dataset_respects_staff_tier():
    """A staff-tier dataset is invisible to a non-staff caller of describe_dataset —
    the same gate its own query tool enforces."""

    @dataset("t_tree_staff_only", columns=["method"], enable_mcp=True, mcp_access="staff")
    def _staff_only(request=None):
        return RequestLog.objects.all()

    try:
        plain = User.objects.create_user("treeplain", password="x")
        staff = User.objects.create_user("treeboss", password="x", is_staff=True)
        assert "error" in _call("describe_dataset", {"key": "t_tree_staff_only"}, user=plain)
        assert _call("describe_dataset", {"key": "t_tree_staff_only"}, user=staff)["key"] == "t_tree_staff_only"
    finally:
        from apps.datasets.registry import unregister

        unregister("t_tree_staff_only")


def test_the_whole_month_and_year_periods_run_past_today():
    assert relative_dates("this_month", date(2026, 5, 14)) == (date(2026, 5, 1), date(2026, 6, 1))
    assert relative_dates("this_month", date(2026, 12, 14)) == (date(2026, 12, 1), date(2027, 1, 1))
    assert relative_dates("this_year", date(2026, 5, 14)) == (date(2026, 1, 1), date(2027, 1, 1))
