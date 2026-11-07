"""Metrics, dashboards and reports.

Source data is apps.activity.RequestLog through two test datasets: a staff-only
one (the secure default) and an ``access="auth"`` one, so the access rules can
be exercised both ways. Every value assertion is an exact count — the point of
a stored filter is that it narrows exactly as written.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import RequestFactory

from apps.activity.models import RequestLog
from apps.dashboards.components import (
    ComponentType,
    describe_types,
    get_component_type,
    normalize_layout,
    register_component_type,
)
from apps.dashboards.metrics import evaluate, format_value, request_for, state_for, validate_thresholds
from apps.dashboards.models import Dashboard, Metric, Report
from apps.dashboards.tests.support import own
from apps.datasets.registry import dataset

pytestmark = pytest.mark.django_db

User = get_user_model()

DS_STAFF = "t_dash_log"
DS_AUTH = "t_dash_log_auth"
COLUMNS = ["method", "path", "status_code", "response_time_ms", "timestamp"]


@dataset(DS_STAFF, label="Dash log", columns=COLUMNS)
def _staff_log(request=None):
    return RequestLog.objects.exclude(path__startswith="/smallstack/")


@dataset(DS_AUTH, label="Dash log (members)", columns=COLUMNS, access="auth")
def _auth_log(request=None):
    return RequestLog.objects.exclude(path__startswith="/smallstack/")


def _seed():
    """GET/200 ×3 (10, 20, 30 ms) · POST/201 (40) · DELETE/500 (90)."""
    for ms in (10, 20, 30):
        RequestLog.objects.create(path=f"/a/{ms}", method="GET", status_code=200, response_time_ms=ms)
    RequestLog.objects.create(path="/b", method="POST", status_code=201, response_time_ms=40)
    RequestLog.objects.create(path="/c", method="DELETE", status_code=500, response_time_ms=90)


@pytest.fixture
def staff():
    return User.objects.create_user("dstaff", password="x", is_staff=True)


@pytest.fixture
def member():
    return User.objects.create_user("dmember", password="x")


def _metric(**kw) -> Metric:
    defaults = {"key": "m_all", "name": "All", "dataset": DS_STAFF}
    defaults.update(kw)
    m = Metric(**defaults)
    m.save()
    return m


# -- formatting + thresholds (pure) ------------------------------------------------


@pytest.mark.parametrize(
    "value, fmt, unit, expected",
    [
        (9481, "number", "", "9,481"),
        (9481.5, "number", "", "9,481.50"),
        (9481, "compact", "", "9.5K"),
        (2_300_000, "compact", "", "2.3M"),
        (12, "compact", "", "12"),
        (94.25, "percent", "", "94.2%"),
        (9481, "currency", "€", "€9,481.00"),
        (-5, "currency", "", "-$5.00"),
        (139, "duration", "", "2m 19s"),
        (3725, "duration", "", "1h 02m"),
        (None, "number", "", "—"),
    ],
)
def test_format_value(value, fmt, unit, expected):
    assert format_value(value, fmt, unit) == expected


def test_thresholds_first_match_wins():
    rules = [{"op": ">=", "value": 10, "state": "danger"}, {"op": ">=", "value": 5, "state": "warning"}]
    assert state_for(12, rules) == "danger"
    assert state_for(7, rules) == "warning"
    assert state_for(1, rules) is None
    assert state_for(5, [{"op": "between", "value": [1, 5], "state": "success"}]) == "success"


def test_threshold_validation():
    assert validate_thresholds([]) == []
    assert validate_thresholds([{"op": ">=", "value": 1, "state": "danger"}]) == []
    problems = validate_thresholds([{"op": "~", "value": "x", "state": "red"}])
    assert len(problems) == 3
    assert validate_thresholds("nope") == ["thresholds must be a list of {op, value, state} rules"]


# -- the Metric model is the write gate -----------------------------------------------


def test_metric_rejects_unknown_dataset_and_bad_filter():
    with pytest.raises(ValidationError) as exc:
        _metric(dataset="no_such_dataset")
    assert "dataset" in exc.value.message_dict
    with pytest.raises(ValidationError) as exc:
        _metric(filter_tree={"field": "renamed", "op": "=", "value": 1})
    assert "unknown field 'renamed'" in str(exc.value.message_dict["filter_tree"])


def test_metric_requires_measure_for_sum_and_numeric_for_avg():
    with pytest.raises(ValidationError) as exc:
        _metric(agg="sum")
    assert "measure" in exc.value.message_dict
    with pytest.raises(ValidationError) as exc:
        _metric(agg="avg", measure="method")
    assert "numeric" in str(exc.value.message_dict["measure"])


def test_metric_period_field_must_be_a_date():
    with pytest.raises(ValidationError) as exc:
        _metric(period_field="method")
    assert "period_field" in exc.value.message_dict
    assert _metric(period_field="timestamp").period_field == "timestamp"


# -- evaluation ----------------------------------------------------------------------


def test_evaluate_count_sum_avg_and_filters(staff):
    _seed()
    req = request_for(staff)
    assert evaluate(_metric(), req).value == 5
    gets = _metric(key="m_get", filter_tree={"field": "method", "op": "=", "value": "GET"})
    assert evaluate(gets, req).value == 3
    total_ms = _metric(key="m_ms", agg="sum", measure="response_time_ms")
    assert evaluate(total_ms, req).value == 190
    avg_get = _metric(
        key="m_avg", agg="avg", measure="response_time_ms", filter_tree={"field": "method", "op": "=", "value": "GET"}
    )
    assert evaluate(avg_get, req).value == 20


def test_evaluate_applies_thresholds_and_format(staff):
    _seed()
    m = _metric(
        key="m_err",
        filter_tree={"field": "status_code", "op": ">=", "value": 500},
        thresholds=[{"op": ">", "value": 0, "state": "danger"}],
        unit="errors",
    )
    result = evaluate(m, request_for(staff))
    assert (result.value, result.display, result.state, result.unit) == (1, "1", "danger", "errors")
    assert result.summary == "Status code ≥ 500"


def test_period_only_narrows_period_aware_metrics(staff):
    _seed()
    old = RequestLog.objects.create(path="/old", method="GET", status_code=200, response_time_ms=1)
    from datetime import timedelta

    from django.utils import timezone

    RequestLog.objects.filter(pk=old.pk).update(timestamp=timezone.now() - timedelta(days=60))
    req = request_for(staff)
    aware = _metric(key="m_aware", period_field="timestamp")
    plain = _metric(key="m_plain")
    assert evaluate(aware, req).value == 6
    assert evaluate(aware, req, period="last_30").value == 5
    assert evaluate(aware, req, period="last_30").period_label == "Last 30 days"
    assert evaluate(plain, req, period="last_30").value == 6  # not period-aware: unchanged
    assert evaluate(plain, req, period="last_30").period is None


def test_broken_stored_filter_errors_never_widens(staff):
    """A column renamed after the metric was saved: the card shows an error,
    not the unfiltered count (the fail-open shape)."""
    _seed()
    m = _metric(key="m_get2", filter_tree={"field": "method", "op": "=", "value": "GET"})
    Metric.objects.filter(pk=m.pk).update(filter_tree={"field": "verb", "op": "=", "value": "GET"})
    m.refresh_from_db()
    result = evaluate(m, request_for(staff))
    assert result.value is None and result.error and not result.ok
    assert result.problems == ["filter.field: unknown field 'verb'"]


def test_dataset_access_tier_gates_the_number(staff, member):
    _seed()
    staff_metric = _metric(key="m_staffds")
    auth_metric = _metric(key="m_authds", dataset=DS_AUTH)
    assert evaluate(staff_metric, request_for(member)).restricted
    assert evaluate(staff_metric, request_for(member)).value is None
    assert evaluate(auth_metric, request_for(member)).value == 5
    assert evaluate(staff_metric, request_for(staff)).value == 5


# -- ownership ----------------------------------------------------------------------------


def test_ownership_rules(staff, member):
    other = User.objects.create_user("dother", password="x")
    shared = _metric(key="m_shared", dataset=DS_AUTH)
    mine = _metric(key="m_mine", dataset=DS_AUTH, owner=member)
    assert shared.can_view(member) and not shared.can_edit(member) and shared.can_edit(staff)
    assert mine.can_view(member) and mine.can_edit(member)
    assert not mine.can_view(other) and mine.can_view(staff) and not mine.can_edit(staff)
    assert set(Metric.objects.visible_to(member)) == {shared, mine}
    assert set(Metric.objects.visible_to(other)) == {shared}


# -- layout validation -----------------------------------------------------------------------


def test_layout_normalises_and_validates(staff):
    _metric(key="m_l")
    cells, problems = normalize_layout(
        [{"type": "metric", "metric": "m_l"}, {"type": "text", "options": {"markdown": "hi"}}]
    )
    assert problems == []
    assert cells[0]["id"] and cells[0]["w"] == 3 and cells[0]["h"] == 2 and cells[1]["w"] == 4
    _, problems = normalize_layout(
        [
            {"type": "chart"},
            {"type": "metric", "metric": "nope"},
            {"type": "metric", "metric": "m_l", "x": 10, "w": 6},
            {"type": "text", "metric": "m_l", "options": {"markdown": "x"}},
            {"id": "a", "type": "text", "options": {"markdown": "x"}},
            {"id": "a", "type": "text", "options": {"markdown": "y"}},
            {"type": "metric_group", **own("m_l"), "options": {}},
            {"type": "metric_group", "metric": "m_l", "options": {"dimension": "level"}},
            {"type": "metric_group", "dataset": "nope", "options": {"dimension": "level"}},
        ]
    )
    text = " | ".join(problems)
    assert "unknown component type 'chart'" in text
    assert "no metric with key 'nope'" in text
    assert "must fit in 12 columns" in text
    assert "takes no metric" in text
    assert "duplicate id 'a'" in text
    assert "'dimension'" in text
    # A split or a chart filters a dataset of its own: a metric is refused there, and its dataset is checked.
    assert "a Grouped stat card filters a dataset of its own" in text
    assert "No dataset named 'nope'" in text


def test_dashboard_save_is_the_gate():
    with pytest.raises(ValidationError) as exc:
        Dashboard(name="D", slug="d", layout=[{"type": "metric", "metric": "ghost"}]).save()
    assert "layout" in exc.value.message_dict
    with pytest.raises(ValidationError):
        Dashboard(name="D", slug="d2", default_period="someday").save()


def test_personal_dashboard_cannot_use_another_users_personal_metric(member):
    other = User.objects.create_user("dother2", password="x")
    _metric(key="m_theirs", dataset=DS_AUTH, owner=other)
    _metric(key="m_own", dataset=DS_AUTH, owner=member)
    _metric(key="m_pub", dataset=DS_AUTH)
    ok = Dashboard(
        name="Mine",
        slug="mine",
        owner=member,
        layout=[{"type": "metric", "metric": "m_own"}, {"type": "metric", "metric": "m_pub"}],
    )
    ok.save()
    with pytest.raises(ValidationError) as exc:
        Dashboard(name="Bad", slug="bad", owner=member, layout=[{"type": "metric", "metric": "m_theirs"}]).save()
    assert "another user's personal metric" in str(exc.value)


def test_component_registry_is_extensible(staff, client):
    def build(cell, ctx):
        return {"msg": "hello from a plugin"}

    register_component_type(
        ComponentType(
            key="t_plugin",
            label="Plugin",
            template="dashboards/cells/error.html",
            build=lambda c, x: {"message": "plugin says hi"},
        )
    )
    try:
        assert any(t["type"] == "t_plugin" for t in describe_types())
        d = Dashboard(name="P", slug="plug", layout=[{"id": "p1", "type": "t_plugin"}])
        d.save()
        client.force_login(staff)
        html = client.get("/smallstack/dashboards/d/plug/cells/p1/").content.decode()
        assert "plugin says hi" in html
    finally:
        from apps.dashboards import components

        components._TYPES.pop("t_plugin", None)
    assert get_component_type("t_plugin") is None


# -- pages + cells ----------------------------------------------------------------------------


@pytest.fixture
def board(staff):
    _seed()
    _metric(key="m_req", name="Requests", period_field="timestamp")
    _metric(key="m_req_auth", name="Member requests", dataset=DS_AUTH)
    d = Dashboard(
        name="Board",
        slug="board",
        layout=[
            {"id": "a", "type": "metric", "metric": "m_req"},
            {"id": "b", "type": "metric_group", **own("m_req"), "options": {"dimension": "method", "limit": 2}},
            {"id": "c", "type": "text", "options": {"markdown": "# Hello\n\n<script>x</script>"}},
            {"id": "d", "type": "metric", "metric": "m_req_auth"},
        ],
    )
    d.save()
    return d


def test_dashboard_page_and_cells_render(client, staff, board):
    client.force_login(staff)
    page = client.get("/smallstack/dashboards/d/board/")
    assert page.status_code == 200 and b'gs-id="a"' in page.content and b"dash-editor-data" in page.content
    a = client.get("/smallstack/dashboards/d/board/cells/a/").content.decode()
    assert "stat-card" in a and ">5<" in a.replace(" ", "")
    b = client.get("/smallstack/dashboards/d/board/cells/b/").content.decode()
    assert "GET" in b and "Other" in b  # 3 methods, limit 2 → GET, then the tail folded
    c = client.get("/smallstack/dashboards/d/board/cells/c/").content.decode()
    assert "<h1" in c and "<script>" not in c  # markdown rendered, raw HTML escaped
    assert client.get("/smallstack/dashboards/d/board/cells/zzz/").status_code == 404


def test_group_counts_reconcile_with_total(staff, board):
    from apps.dashboards.metrics import group_values

    groups = group_values(Metric.objects.get(key="m_req"), request_for(staff), "method", limit=2)
    assert [g["label"] for g in groups] == ["GET", groups[1]["label"], "Other"]
    assert sum(g["value"] for g in groups) == 5


def test_member_sees_restricted_card_for_staff_dataset(client, member, board):
    client.force_login(member)
    assert client.get("/smallstack/dashboards/d/board/").status_code == 200  # shared board
    a = client.get("/smallstack/dashboards/d/board/cells/a/").content.decode()
    assert "access" in a and ">5<" not in a.replace(" ", "")
    d = client.get("/smallstack/dashboards/d/board/cells/d/").content.decode()
    assert "stat-card" in d  # the auth-tier dataset shows
    rows = client.get("/smallstack/dashboards/m/m_req/rows/")
    assert rows.status_code == 404


def test_personal_dashboard_is_private(client, member, staff):
    other = User.objects.create_user("dother3", password="x")
    Dashboard(name="Private", slug="private", owner=member).save()
    client.force_login(other)
    assert client.get("/smallstack/dashboards/d/private/").status_code == 404
    client.force_login(staff)
    assert client.get("/smallstack/dashboards/d/private/").status_code == 200


def test_layout_save_endpoint(client, staff, member, board):
    client.force_login(staff)
    layout = [dict(c) for c in board.layout]
    layout[0]["x"], layout[0]["y"], layout[0]["w"] = 6, 50, 6
    resp = client.post(
        "/smallstack/dashboards/d/board/layout/", json.dumps({"layout": layout}), content_type="application/json"
    )
    assert resp.status_code == 200
    board.refresh_from_db()
    assert board.layout[0]["x"] == 6
    bad = client.post(
        "/smallstack/dashboards/d/board/layout/",
        json.dumps({"layout": [{"type": "metric", "metric": "ghost"}]}),
        content_type="application/json",
    )
    assert bad.status_code == 400 and "ghost" in bad.json()["errors"][0]
    client.force_login(member)
    denied = client.post(
        "/smallstack/dashboards/d/board/layout/", json.dumps({"layout": []}), content_type="application/json"
    )
    assert denied.status_code == 403


def test_drill_rows_match_the_value_and_narrow(client, staff, board):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/m/m_req/rows/").content.decode()
    assert "<strong>5 rows</strong> in Dash log" in html
    narrow = json.dumps({"field": "method", "op": "=", "value": "GET"})
    html = client.get("/smallstack/dashboards/m/m_req/rows/", {"narrow": narrow}).content.decode()
    assert "<strong>3 rows</strong>" in html and "Narrowed to <span>Method = GET</span>" in html
    assert 'class="stat-modal' not in html and 'class="dm-table crud-table"' in html  # a fragment, neutral scoped table
    bad = client.get(
        "/smallstack/dashboards/m/m_req/rows/", {"narrow": json.dumps({"field": "x", "op": "=", "value": 1})}
    )
    assert bad.status_code == 400


def test_index_and_metric_detail(client, staff, board):
    client.force_login(staff)
    assert b"Board" in client.get("/smallstack/dashboards/").content
    detail = client.get("/smallstack/dashboards/m/m_req/").content.decode()
    assert "Requests" in detail and "Board" in detail  # "used on"


# -- forms / CRUD -------------------------------------------------------------------------------


def test_member_creates_personal_metric_but_cannot_share(client, member):
    client.force_login(member)
    data = {
        "name": "Mine",
        "key": "m_form",
        "dataset": DS_AUTH,
        "filter_tree": "{}",
        "agg": "count",
        "format": "number",
        "thresholds": "[]",
    }
    resp = client.post("/smallstack/dashboards/metrics/new/", {**data, "visibility": "shared"})
    assert resp.status_code == 200 and not Metric.objects.filter(key="m_form").exists()
    resp = client.post("/smallstack/dashboards/metrics/new/", {**data, "visibility": "personal"})
    assert resp.status_code == 302
    assert Metric.objects.get(key="m_form").owner == member


def test_member_cannot_build_on_staff_dataset(client, member):
    client.force_login(member)
    data = {
        "name": "Sneaky",
        "key": "m_sneak",
        "dataset": DS_STAFF,
        "filter_tree": "{}",
        "agg": "count",
        "format": "number",
        "thresholds": "[]",
        "visibility": "personal",
    }
    resp = client.post("/smallstack/dashboards/metrics/new/", data)
    assert resp.status_code == 200 and not Metric.objects.filter(key="m_sneak").exists()


def test_rest_create_metric_and_partial_update_keeps_sharing(client, staff):
    client.force_login(staff)
    resp = client.post(
        "/smallstack/api/dashboards/metrics/",
        json.dumps(
            {
                "name": "API",
                "key": "m_api",
                "dataset": DS_STAFF,
                "filter_tree": {"field": "method", "op": "=", "value": "GET"},
                "visibility": "shared",
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code in (200, 201), resp.content
    m = Metric.objects.get(key="m_api")
    assert m.owner_id is None and m.filter_tree["value"] == "GET"
    resp = client.patch(
        f"/smallstack/api/dashboards/metrics/{m.pk}/",
        json.dumps({"name": "API renamed"}),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    m.refresh_from_db()
    assert m.name == "API renamed" and m.owner_id is None  # omitted visibility → unchanged
    bad = client.post(
        "/smallstack/api/dashboards/metrics/",
        json.dumps(
            {
                "name": "Bad",
                "key": "m_bad",
                "dataset": DS_STAFF,
                "filter_tree": {"field": "nope", "op": "=", "value": 1},
            }
        ),
        content_type="application/json",
    )
    assert bad.status_code == 400 and not Metric.objects.filter(key="m_bad").exists()


# -- JSON API ------------------------------------------------------------------------------------------


def test_preview_api_reports_value_and_problems(client, staff):
    _seed()
    client.force_login(staff)
    ok = client.post(
        "/smallstack/dashboards/api/preview/",
        json.dumps({"dataset": DS_STAFF, "filter_tree": {"field": "method", "op": "in", "value": ["GET", "POST"]}}),
        content_type="application/json",
    ).json()
    assert ok["ok"] and ok["result"]["value"] == 4 and ok["row_count"] == 4
    bad = client.post(
        "/smallstack/dashboards/api/preview/",
        json.dumps({"dataset": DS_STAFF, "agg": "sum", "filter_tree": {"field": "zzz", "op": "=", "value": 1}}),
        content_type="application/json",
    ).json()
    assert not bad["ok"] and any("zzz" in p for p in bad["problems"]) and any("measure" in p for p in bad["problems"])
    assert not Metric.objects.filter(key="preview").exists()  # a dry run never saves


def test_board_and_report_values_api(client, staff, board):
    client.force_login(staff)
    data = client.get("/smallstack/dashboards/api/boards/board/values/").json()
    by_id = {c["id"]: c for c in data["cells"]}
    assert by_id["a"]["result"]["value"] == 5
    assert by_id["b"]["groups"][0]["label"] == "GET"
    Report(name="R", slug="rep", items=[{"metric": "m_req"}], periods=["mtd", "pmtd"]).save()
    rep = client.get("/smallstack/dashboards/api/reports/rep/values/").json()
    assert rep["columns"][0]["key"] == "mtd" and rep["rows"][0]["values"][0]["value"] == 5
    assert rep["rows"][0]["values"][1]["value"] == 0  # nothing last month


def test_report_validation_and_csv(client, staff, board):
    with pytest.raises(ValidationError):
        Report(name="R", slug="rbad", items=[{"metric": "ghost"}]).save()
    with pytest.raises(ValidationError):
        Report(name="R", slug="rbad2", items=["m_req"], periods=["someday"]).save()
    r = Report(
        name="R", slug="rcsv", items=["m_req", {"metric": "m_req_auth", "label": "Members"}], periods=["mtd", "ytd"]
    )
    r.save()
    assert r.items[0] == {"metric": "m_req"}  # bare keys normalised
    client.force_login(staff)
    resp = client.get("/smallstack/dashboards/r/rcsv/?format=csv")
    lines = resp.content.decode().strip().splitlines()
    assert lines[0] == "Metric,Month to date,Year to date"
    assert lines[1] == "Requests,5,5"
    assert lines[2].startswith("Members,5,")  # not period-aware → first column only
    assert client.get("/smallstack/dashboards/r/rcsv/").status_code == 200


# -- template tag ------------------------------------------------------------------------------------------


def test_metric_card_tag(staff, member, board):
    rf = RequestFactory()
    tpl = Template('{% load dashboard_tags %}{% metric_card "m_req" %}{% metric_card "ghost" %}')
    req = rf.get("/")
    req.user = staff
    html = tpl.render(Context({"request": req}))
    assert "stat-card" in html and "/smallstack/dashboards/m/m_req/rows/" in html and "ghost" in html
    req.user = member
    html = tpl.render(Context({"request": req}))
    assert "stat-card--muted" in html and "/rows/" not in html  # staff dataset: no number, no drill


# -- MCP ---------------------------------------------------------------------------------------------------


def _call(name, args, user):
    from apps.dashboards.mcp_tools import register_dashboard_tools
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    register_dashboard_tools()
    token = set_context(ToolContext(user=user, token=None))
    try:
        handler = TOOL_HANDLERS[name]
        if asyncio.iscoroutinefunction(handler):
            return async_to_sync(lambda: handler(args))()
        return handler(args)
    finally:
        reset_context(token)


def test_mcp_agent_loop_builds_a_dashboard(staff):
    """The documented agent loop, end to end: preview → create → add cards → snapshot."""
    _seed()
    comps = _call("list_dashboard_components", {}, staff)
    assert {"metric", "metric_group", "text"} <= {t["type"] for t in comps["types"]}
    preview = _call(
        "metric_preview",
        {"dataset": DS_STAFF, "filter_tree": {"field": "status_code", "op": ">=", "value": 500}},
        staff,
    )
    assert preview["ok"] and preview["result"]["value"] == 1
    _metric(key="m_errs", filter_tree={"field": "status_code", "op": ">=", "value": 500})
    Dashboard(name="Agent board", slug="agent").save()
    added = _call("dashboard_add_card", {"dashboard": "agent", "type": "metric", "metric": "m_errs"}, staff)
    assert added["ok"], added
    _call("dashboard_add_card", {"dashboard": "agent", "type": "text", "options": {"markdown": "hi"}}, staff)
    bad = _call("dashboard_add_card", {"dashboard": "agent", "type": "metric", "metric": "ghost"}, staff)
    assert "problems" in bad
    snap = _call("dashboard_snapshot", {"dashboard": "agent"}, staff)
    assert snap["cells"][0]["result"]["value"] == 1 and len(snap["cells"]) == 2
    first, second = snap["cells"]
    apart = second["x"] >= first["x"] + first["w"] or second["y"] >= first["y"] + first["h"]
    assert apart  # beside or below, never on top of it
    assert _call("metric_value", {"key": "m_errs"}, staff)["value"] == 1
    removed = _call("dashboard_remove_card", {"dashboard": "agent", "cell_id": added["cell"]["id"]}, staff)
    assert removed["cells"] == 1


def test_mcp_tools_respect_ownership_and_access(staff, member):
    _seed()
    _metric(key="m_staffonly")
    Dashboard(name="Shared", slug="shared-board").save()
    assert _call("metric_value", {"key": "m_staffonly"}, member)["restricted"] is True
    assert "error" in _call(
        "dashboard_add_card", {"dashboard": "shared-board", "type": "text", "options": {"markdown": "x"}}, member
    )
    assert not _call("metric_preview", {"dataset": DS_STAFF}, member)["ok"]
    assert _call("metric_preview", {"dataset": DS_AUTH}, member)["result"]["value"] == 5


# -- the dashboard settings page ------------------------------------------------------------------


def test_dashboard_form_page_creates_and_edits(client, staff, board):
    client.force_login(staff)
    new = client.get("/smallstack/dashboards/boards/new/").content.decode()
    assert 'name="default_period"' in new and 'value="shared"' in new and "df-mini-empty" in new
    resp = client.post(
        "/smallstack/dashboards/boards/new/",
        {
            "name": "Support",
            "slug": "support",
            "default_period": "mtd",
            "refresh_seconds": "300",
            "visibility": "shared",
            "layout": "[]",
        },
    )
    assert resp.status_code == 302
    d = Dashboard.objects.get(slug="support")
    assert (d.default_period, d.refresh_seconds, d.owner_id) == ("mtd", 300, None)
    edit = client.get(f"/smallstack/dashboards/boards/{board.pk}/edit/").content.decode()
    assert edit.count('class="df-mini-cell') == 4  # the miniature shows every card
    assert "Requests" in edit  # labelled with the metric's name


def test_dashboard_form_hides_sharing_from_members(client, member):
    client.force_login(member)
    html = client.get("/smallstack/dashboards/boards/new/").content.decode()
    assert 'value="shared" disabled' in html and "Only staff can share" in html


# -- the report form page ---------------------------------------------------------------------------


def test_report_form_page_creates_and_edits(client, staff, board):
    client.force_login(staff)
    new = client.get("/smallstack/dashboards/reports/new/").content.decode()
    assert 'id="rf-metrics"' in new and '"m_req"' in new and 'name="periods"' in new
    resp = client.post(
        "/smallstack/dashboards/reports/new/",
        {
            "name": "Weekly",
            "slug": "weekly",
            "items": json.dumps([{"metric": "m_req", "label": "Reqs"}]),
            "periods": ["wtd", "pwtd"],
            "visibility": "shared",
        },
    )
    assert resp.status_code == 302
    r = Report.objects.get(slug="weekly")
    assert r.items == [{"metric": "m_req", "label": "Reqs"}] and r.periods == ["wtd", "pwtd"] and r.owner_id is None


def test_report_form_keeps_generic_periods_and_scopes_metric_picker(client, member):
    other = User.objects.create_user("dother4", password="x")
    _metric(key="m_pub2", dataset=DS_AUTH)
    _metric(key="m_theirs2", dataset=DS_AUTH, owner=other)
    r = Report(name="Mine", slug="mine-rep", owner=member, items=["m_pub2"], periods=["last_45"])
    r.save()
    client.force_login(member)
    html = client.get(f"/smallstack/dashboards/reports/{r.pk}/edit/").content.decode()
    # An agent's generic column survives an edit: still ticked, with the report's heading.
    assert 'value="last_45" aria-label="Last 45 days" data-heading="Last 45 days" checked' in html
    assert '"m_pub2"' in html and "m_theirs2" not in html
    assert 'value="shared" disabled' in html


# -- the metric form page ----------------------------------------------------------------------------


def test_metric_form_page_renders_chips_and_saves(client, staff):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/metrics/new/").content.decode()
    assert 'type="radio" class="sr-only" name="agg" value="count" checked' in html
    assert 'name="format" value="number" checked' in html and "9.5K" in html
    resp = client.post(
        "/smallstack/dashboards/metrics/new/",
        {
            "name": "Avg",
            "key": "m_avg_form",
            "dataset": DS_STAFF,
            "filter_tree": "{}",
            "agg": "avg",
            "measure": "response_time_ms",
            "format": "duration",
            "thresholds": "[]",
            "visibility": "shared",
        },
    )
    assert resp.status_code == 302
    m = Metric.objects.get(key="m_avg_form")
    assert (m.agg, m.format, m.owner_id) == ("avg", "duration", None)
    edit = client.get(f"/smallstack/dashboards/metrics/{m.pk}/edit/").content.decode()
    assert 'name="agg" value="avg" checked' in edit and 'name="format" value="duration" checked' in edit


# -- the metric page ---------------------------------------------------------------------------------


def test_metric_page_reads_as_a_sentence(client, staff, board):
    _metric(
        key="m_sentence",
        filter_tree={
            "or": [{"field": "method", "op": "=", "value": "GET"}, {"field": "method", "op": "=", "value": "POST"}]
        },
        period_field="timestamp",
        thresholds=[{"op": ">=", "value": 3, "state": "warning"}],
    )
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/m/m_sentence/", {"period": "last_30"}).content.decode()
    assert "Count of rows in" in html and "Method = GET or Method = POST" in html
    assert "in the last 30 days" in html
    # The period links swap the page body in place (no reload, no jump); the href is the no-JS fallback.
    assert (
        'href="?period=last_30" class="md-period" hx-get="?period=last_30" hx-select="#md-page" '
        'hx-target="#md-page" hx-swap="outerHTML" hx-push-url="true" aria-current="true"'
    ) in html
    assert html.count('id="md-page"') == 1
    assert "md-hero--warning" in html and "≥ 3 is warning" in html
    assert "4 rows" in html  # 3 GET + 1 POST, matching the value
    plain = client.get("/smallstack/dashboards/m/m_req_auth/").content.decode()
    assert "doesn't depend on time" in plain and "md-period" not in plain


# -- the report page -----------------------------------------------------------------------------


def test_report_page_compares_and_merges(client, staff, board):
    Report(name="Cmp", slug="cmp", items=["m_req", "m_req_auth"], periods=["mtd", "pmtd"]).save()
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/r/cmp/").content.decode()
    assert "2 metrics, compared across this month so far and last month." in html
    assert "This month so far" in html and "Last month" in html
    assert "Up from 0 in all of last month" in html  # 5 now, 0 last month; partial period said out loud
    assert "Same in every period" in html  # the non-period-aware metric gets one merged cell
    csv = client.get("/smallstack/dashboards/r/cmp/?format=csv").content.decode().splitlines()
    assert csv[1] == "Requests,5,0"  # the CSV keeps the raw matrix


def test_report_delta_math():
    from apps.dashboards.comparison import delta as _delta
    from apps.dashboards.metrics import MetricResult

    r = lambda v: MetricResult(value=v, display=str(v))  # noqa: E731
    assert _delta(r(150), r(100), "last month") == {"dir": "up", "text": "50% vs last month"}
    assert _delta(r(50), r(100), "last month")["dir"] == "down"
    assert _delta(r(10), r(10), "last month")["dir"] == "flat"
    assert _delta(r(None), r(10), "last month") is None
    assert _delta(MetricResult(error="x"), r(10), "last month") is None


# -- the index ------------------------------------------------------------------------------------------


def test_index_first_run_and_library(client, staff):
    client.force_login(staff)
    empty = client.get("/smallstack/dashboards/").content.decode()
    assert "Build your first dashboard" in empty and "ix-steps" in empty
    _seed()
    _metric(key="m_ix", name="Index metric", thresholds=[{"op": ">", "value": 0, "state": "danger"}])
    Dashboard(name="Ix board", slug="ix-board", layout=[{"type": "metric", "metric": "m_ix"}]).save()
    Report(name="Ix report", slug="ix-report", items=["m_ix"]).save()
    html = client.get("/smallstack/dashboards/").content.decode()
    assert "Build your first dashboard" not in html
    assert "board-cover" in html and "1 card" in html  # the board tile shows its cover
    # Metrics and reports live in the Goals area.
    goals = client.get("/smallstack/goals/").content.decode()
    assert 'rp-value rp-value--danger">5<' in goals  # live value in its rule colour
    assert "1 metric, all time" in goals


# -- the dashboard page -------------------------------------------------------------------------------


def test_dashboard_page_chrome_and_quiet_labels(client, staff, board):
    board.default_period = "last_30"
    board.layout = [*board.layout, {"id": "pin", "type": "metric", "metric": "m_req", "use_period": False}]
    board.save()
    client.force_login(staff)
    page = client.get("/smallstack/dashboards/d/board/").content.decode()
    assert 'href="?period=last_30" class="md-period" aria-current="true"' in page
    assert "dash-edit-band" in page and 'id="dash-refresh"' in page
    assert "load, dash-refresh" in page  # Refresh re-fires every cell's own trigger
    assert "dash-cell--text" in page
    a = client.get("/smallstack/dashboards/d/board/cells/a/").content.decode()
    # The period bar says it once; the card's label doesn't repeat it (the
    # drill-down modal's title still does — that's where it's needed).
    assert '<div class="stat-card-label">Requests</div>' in a
    pin = client.get("/smallstack/dashboards/d/board/cells/pin/").content.decode()
    assert "Requests (all time)" in pin  # the one card that differs from the bar says so


# -- the metrics list -----------------------------------------------------------------------------------


def test_metrics_list_library_display(client, staff, member, board):
    Report(name="R", slug="ml-rep", items=["m_req"]).save()
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/metrics/").content.decode()
    assert "ml-table" in html and "Counts rows, by period" in html
    assert "1 dashboard, 1 report" in html  # m_req: on the board and in the report
    assert 'rp-value">5<' in html  # live value
    assert "/smallstack/dashboards/metrics/" in html and "Edit Requests" in html
    client.force_login(member)
    html = client.get("/smallstack/dashboards/metrics/").content.decode()
    assert "Restricted" in html  # staff dataset, member viewer: no number
    assert "Edit Requests" not in html  # shared metric: members can't edit


# -- the reports list -----------------------------------------------------------------------------------


def test_reports_list_library_display(client, staff, member, board):
    Report(name="Monthly", slug="rl-rep", items=["m_req", "m_req_auth"], periods=["mtd", "pmtd"]).save()
    Metric.objects.filter(key="m_req_auth").delete()  # leaves a dangling row
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/reports/").content.decode()
    assert "2 metrics: Requests" in html
    assert 'rl-col rl-col--current">This month so far' in html and ">Last month<" in html
    assert "1 row points at a deleted metric" in html
    assert "/smallstack/dashboards/r/rl-rep/?format=csv" in html and "Edit Monthly" in html
    client.force_login(member)
    assert "Edit Monthly" not in client.get("/smallstack/dashboards/reports/").content.decode()


# -- the dashboards list --------------------------------------------------------------------------------


def test_dashboards_list_library_display(client, staff, member, board):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/boards/").content.decode()
    assert "board-cover" in html and "2 single stats, 1 grouped stat, 1 note" in html
    assert "Opens on all time" in html and "Settings for Board" in html
    Metric.objects.filter(key="m_req_auth").delete()
    html = client.get("/smallstack/dashboards/boards/").content.decode()
    assert "1 card can&#x27;t show" in html or "1 card can't show" in html
    client.force_login(member)
    assert "Settings for Board" not in client.get("/smallstack/dashboards/boards/").content.decode()


# -- the metric delete page -----------------------------------------------------------------------------


def test_metric_delete_page_shows_impact_and_can_detach(client, staff, board):
    Report(name="Rep", slug="del-rep", items=["m_req", "m_req_auth"]).save()
    m = Metric.objects.get(key="m_req")
    client.force_login(staff)
    html = client.get(f"/smallstack/dashboards/metrics/{m.pk}/delete/").content.decode()
    assert "Deleting it breaks" in html and "1 card on 1 dashboard and 1 row in 1 report" in html
    assert 'name="detach" value="1" checked' in html and "Delete Requests" in html
    assert "in <strong>Dash log</strong>" in html
    resp = client.post(f"/smallstack/dashboards/metrics/{m.pk}/delete/", {"detach": "1"})
    assert resp.status_code == 302 and not Metric.objects.filter(key="m_req").exists()
    board.refresh_from_db()
    # Card "a" went with the metric; the grouped card, with a source of its own, stays.
    assert all(c.get("metric") != "m_req" for c in board.layout) and len(board.layout) == 3
    assert Report.objects.get(slug="del-rep").metric_keys() == ["m_req_auth"]


def test_metric_delete_without_detach_leaves_references(client, staff, board):
    m = Metric.objects.get(key="m_req_auth")
    client.force_login(staff)
    # The delete page with its box unticked: the form says a choice was made.
    client.post(f"/smallstack/dashboards/metrics/{m.pk}/delete/", {"detach_choice": "1"})
    board.refresh_from_db()
    assert any(c.get("metric") == "m_req_auth" for c in board.layout)  # left in place, renders as broken
    unused = _metric(key="m_unused")
    html = client.get(f"/smallstack/dashboards/metrics/{unused.pk}/delete/").content.decode()
    assert "Nothing uses this metric" in html


# -- the report delete page -----------------------------------------------------------------------------


def test_report_delete_page_shows_shape_and_offers_csv(client, staff, board):
    r = Report(name="Monthly", slug="del-r", items=[{"metric": "m_req", "label": "Reqs"}], periods=["mtd", "pmtd"])
    r.save()
    client.force_login(staff)
    html = client.get(f"/smallstack/dashboards/reports/{r.pk}/delete/").content.decode()
    assert "Delete Monthly?" in html and ">This month so far<" in html and ">Reqs<" in html
    assert "Its metrics stay" in html and "/smallstack/dashboards/r/del-r/?format=csv" in html
    resp = client.post(f"/smallstack/dashboards/reports/{r.pk}/delete/")
    assert resp.status_code == 302 and not Report.objects.filter(pk=r.pk).exists()
    assert Metric.objects.filter(key="m_req").exists()  # the metrics stay


# -- the dashboard delete page --------------------------------------------------------------------------


def test_dashboard_delete_page_counts_loss_and_offers_layout(client, staff, board):
    client.force_login(staff)
    html = client.get(f"/smallstack/dashboards/boards/{board.pk}/delete/").content.decode()
    assert "Delete Board?" in html and "df-mini-cell" in html
    assert "Its 4 cards go with it; the 2 metrics behind them stay" in html
    assert "1 note written on this dashboard will be lost" in html
    assert "Keep a copy of the layout" in html and "&quot;metric&quot;: &quot;m_req&quot;" in html
    resp = client.post(f"/smallstack/dashboards/boards/{board.pk}/delete/")
    assert resp.status_code == 302 and not Dashboard.objects.filter(pk=board.pk).exists()
    assert Metric.objects.filter(key="m_req").exists()


def test_metric_delete_modal_fragment_from_the_list(client, staff, board):
    m = Metric.objects.get(key="m_req")
    client.force_login(staff)
    listing = client.get("/smallstack/dashboards/metrics/").content.decode()
    assert (
        f'hx-get="/smallstack/dashboards/metrics/{m.pk}/delete/"' in listing
        and 'data-stat-modal="Delete Requests?"' in listing
    )
    frag = client.get(f"/smallstack/dashboards/metrics/{m.pk}/delete/", HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in frag and "dl--modal" in frag and "data-stat-modal-close" in frag
    assert "1 card on 1 dashboard" in frag and f'action="/smallstack/dashboards/metrics/{m.pk}/delete/"' in frag
    resp = client.post(f"/smallstack/dashboards/metrics/{m.pk}/delete/", {"detach": "1"})
    assert resp.status_code == 302 and not Metric.objects.filter(pk=m.pk).exists()


def test_report_delete_modal_fragment_from_the_list(client, staff, board):
    r = Report(name="Monthly", slug="rdm", items=["m_req"], periods=["mtd"])
    r.save()
    client.force_login(staff)
    listing = client.get("/smallstack/dashboards/reports/").content.decode()
    assert (
        f'hx-get="/smallstack/dashboards/reports/{r.pk}/delete/"' in listing
        and 'data-stat-modal="Delete Monthly?"' in listing
    )
    frag = client.get(f"/smallstack/dashboards/reports/{r.pk}/delete/", HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in frag and "dl--modal" in frag and "Its metrics stay" in frag and "?format=csv" in frag
    assert f'action="/smallstack/dashboards/reports/{r.pk}/delete/"' in frag
    assert client.post(f"/smallstack/dashboards/reports/{r.pk}/delete/").status_code == 302
    assert not Report.objects.filter(pk=r.pk).exists()


def test_dashboard_delete_modal_fragment_from_the_list(client, staff, board):
    client.force_login(staff)
    listing = client.get("/smallstack/dashboards/boards/").content.decode()
    assert (
        f'hx-get="/smallstack/dashboards/boards/{board.pk}/delete/"' in listing
        and 'data-stat-modal="Delete Board?"' in listing
    )
    frag = client.get(f"/smallstack/dashboards/boards/{board.pk}/delete/", HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in frag and "dl--modal" in frag and "Its 4 cards go with it" in frag
    assert 'data-copy="dl-layout"' in frag and f'action="/smallstack/dashboards/boards/{board.pk}/delete/"' in frag
    assert client.post(f"/smallstack/dashboards/boards/{board.pk}/delete/").status_code == 302
    assert not Dashboard.objects.filter(pk=board.pk).exists()


def test_metric_table_view_delete_uses_the_impact_modal(client, staff, board):
    m = Metric.objects.get(key="m_req")
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/metrics/", {"display": "table"}).content.decode()
    assert f'hx-get="/smallstack/dashboards/metrics/{m.pk}/delete/"' in html
    assert 'data-stat-modal="Delete Requests?"' in html
    assert "crudDeleteModal(this,'Requests')" not in html


def test_report_table_view_delete_uses_the_report_modal(client, staff):
    r = Report(name="Plain", slug="plain-r")
    r.save()
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/reports/", {"display": "table"}).content.decode()
    assert f'hx-get="/smallstack/dashboards/reports/{r.pk}/delete/"' in html
    assert 'data-stat-modal="Delete Plain?"' in html
    assert "crudDeleteModal(this,'Plain')" not in html


def test_dashboard_table_view_delete_uses_the_dashboard_modal(client, staff, board):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/boards/", {"display": "table"}).content.decode()
    assert f'hx-get="/smallstack/dashboards/boards/{board.pk}/delete/"' in html
    assert 'data-stat-modal="Delete Board?"' in html
    assert "crudDeleteModal(this,'Board')" not in html


def test_other_tables_keep_the_generic_delete_modal(client, staff):
    """confirm_modal is opt-in: a CRUDView elsewhere that doesn't set it is unchanged."""
    from apps.webhooks.models import WebhookEndpoint

    WebhookEndpoint.objects.create(name="Hook", target_url="https://hooks.example.com/x")
    client.force_login(staff)
    html = client.get("/smallstack/webhooks/endpoints/").content.decode()
    assert 'data-ss-action="crudDeleteModal"' in html and "data-stat-modal=" not in html


# -- the report form: column order + live preview -----------------------------------------------------


def test_report_form_keeps_column_order(client, staff, board):
    """The grouped period chips sit in group order (This, Previous, Rolling);
    the saved column order must survive an edit — first column = "now"."""
    r = Report(name="Order", slug="ord", items=["m_req"], periods=["mtd", "pmtd", "ytd"])
    r.save()
    client.force_login(staff)
    html = client.get(f"/smallstack/dashboards/reports/{r.pk}/edit/").content.decode()
    assert '<script id="rf-period-order" type="application/json">["mtd", "pmtd", "ytd"]</script>' in html
    # What the JS submits: hidden inputs in the chosen order.
    resp = client.post(
        f"/smallstack/dashboards/reports/{r.pk}/edit/",
        {
            "name": "Order",
            "slug": "ord",
            "items": '["m_req"]',
            "periods": ["mtd", "pmtd", "ytd"],
            "visibility": "shared",
        },
    )
    assert resp.status_code == 302
    r.refresh_from_db()
    assert r.periods == ["mtd", "pmtd", "ytd"]


def test_report_preview_api_matches_the_page(client, staff, member, board):
    client.force_login(staff)
    data = client.post(
        "/smallstack/dashboards/api/report-preview/",
        json.dumps({"items": [{"metric": "m_req", "label": "Reqs"}, "m_req_auth"], "periods": ["mtd", "pmtd"]}),
        content_type="application/json",
    ).json()
    assert [c["heading"] for c in data["columns"]] == ["This month so far", "Last month"]
    reqs = data["rows"][0]
    assert reqs["label"] == "Reqs" and reqs["cells"][0]["value"] == 5 and reqs["delta"]["dir"] == "up"
    assert data["rows"][1]["cells"][0]["span"] is True  # not period-aware: one merged value
    assert not Report.objects.filter(name="preview").exists()  # never saved
    client.force_login(member)
    data = client.post(
        "/smallstack/dashboards/api/report-preview/",
        json.dumps({"items": ["m_req"], "periods": []}),
        content_type="application/json",
    ).json()
    assert data["rows"][0]["cells"][0]["restricted"] is True  # staff dataset, member viewer


def test_dashboard_form_miniature_is_live(client, staff, board):
    client.force_login(staff)
    html = client.get(f"/smallstack/dashboards/boards/{board.pk}/edit/").content.decode()
    assert 'data-values-url="/smallstack/dashboards/api/boards/board/values/"' in html
    assert 'data-cell-id="a"' in html and "df-mini-value" in html
    assert 'value="mtd" aria-label="Month to date" data-heading="This month so far"' in html
    new = client.get("/smallstack/dashboards/boards/new/").content.decode()
    assert "data-values-url" not in new  # nothing to evaluate before it exists


def test_metric_form_preview_wording_and_usage_note(client, staff, board):
    m = Metric.objects.get(key="m_req")
    client.force_login(staff)
    html = client.get(f"/smallstack/dashboards/metrics/{m.pk}/edit/").content.decode()
    assert '<optgroup label="This">' in html and 'data-heading="This month so far">This month so far</option>' in html
    assert '"mtd": ["pmtd", "last month"]' in html  # what the preview compares with
    assert "Saving changes it everywhere it" in html and "1 card on 1 dashboard" in html
    new = client.get("/smallstack/dashboards/metrics/new/").content.decode()
    assert "Saving changes it everywhere" not in new


def test_metric_page_compares_with_the_previous_period(client, staff, board):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/m/m_req/", {"period": "mtd"}).content.decode()
    assert "Up from 0 in all of last month" in html  # 5 this month, 0 last month
    assert "dashboard, 1 card" in html  # usage with counts: the grouped card has a source of its own
    plain = client.get("/smallstack/dashboards/m/m_req/", {"period": "last_30"}).content.decode()
    assert "md-compare" not in plain  # a rolling window has no defined predecessor


def test_report_values_open_their_rows(client, staff, board):
    Report(name="Drill", slug="drill-r", items=["m_req", "m_req_auth"], periods=["mtd", "pmtd"]).save()
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/r/drill-r/").content.decode()
    assert 'hx-get="/smallstack/dashboards/m/m_req/rows/?period=mtd"' in html
    assert 'hx-get="/smallstack/dashboards/m/m_req/rows/?period=pmtd"' in html
    assert (
        'data-stat-modal="Requests, this month so far"' in html
    )
    # A metric without a period field drills into all its rows (no period).
    assert 'hx-get="/smallstack/dashboards/m/m_req_auth/rows/"' in html
    frag = client.get("/smallstack/dashboards/m/m_req/rows/", {"period": "mtd"}).content.decode()
    assert "<strong>5 rows</strong>" in frag  # the drill-down count matches the cell


def test_dashboard_metric_cells_compare_with_the_previous_period(client, staff, board):
    client.force_login(staff)
    a = client.get("/smallstack/dashboards/d/board/cells/a/", {"period": "mtd"}).content.decode()
    assert "dash-compare" in a and "Up from 0 in all of last month" in a
    rolling = client.get("/smallstack/dashboards/d/board/cells/a/", {"period": "last_30"}).content.decode()
    assert "dash-compare" not in rolling
    d = client.get("/smallstack/dashboards/d/board/cells/d/", {"period": "mtd"}).content.decode()
    assert "dash-compare" not in d  # not period-aware: nothing to compare


def test_goals_overview_metric_values_follow_the_period(client, staff, board):
    client.force_login(staff)
    html = client.get("/smallstack/goals/").content.decode()
    assert (
        "values for all time" in html
        and 'href="?period=all" class="md-period" hx-get="?period=all" hx-select="#gx-page"' in html
    )
    # Swapped in place, with no anchor jump:
    assert 'hx-swap="outerHTML" hx-push-url="true" aria-current="true">All time' in html
    assert "ix-compare" not in html  # all time: no comparisons, no extra queries
    html = client.get("/smallstack/goals/", {"period": "mtd"}).content.decode()
    assert "values for this month so far" in html
    assert "Up from 0 in all of last month" in html  # m_req, period-aware
    assert ">all time</span>" in html  # m_req_auth has no period field
    assert ">Dash log<" in html  # dataset by its name, not its key
    today = client.get("/smallstack/goals/", {"period": "today"}).content.decode()
    assert "all of yesterday" in today  # today is still running, too


def test_metrics_list_values_follow_the_period(client, staff, board):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/metrics/").content.decode()
    assert "Values for all time" in html and "ix-compare" not in html
    html = client.get("/smallstack/dashboards/metrics/", {"period": "mtd", "q": "Req"}).content.decode()
    assert "Values for this month so far" in html and "Up from 0 in all of last month" in html
    assert "q=Req" in html and "period=today" in html  # links keep the search


def test_reports_list_digest_counts_movement(client, staff, board):
    Report(name="Mv", slug="mv", items=["m_req", "m_req_auth"], periods=["mtd", "pmtd"]).save()
    Report(name="One", slug="one-col", items=["m_req"], periods=["mtd"]).save()
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/reports/").content.decode()
    assert 'hx-get="/smallstack/dashboards/r/mv/digest/" hx-trigger="revealed"' in html
    assert "/r/one-col/digest/" not in html  # one column: nothing to compare
    frag = client.get("/smallstack/dashboards/r/mv/digest/").content.decode()
    assert "1 up" in frag and "this month so far vs all of last month" in frag  # m_req_auth spans: not compared
    assert client.get("/smallstack/dashboards/r/one-col/digest/").content == b""


def test_dashboards_list_digest_flags_attention(client, staff, board):
    Metric.objects.filter(key="m_req").update(thresholds=[{"op": ">", "value": 3, "state": "danger"}])
    Metric.objects.filter(key="m_req_auth").update(
        thresholds=[{"op": ">", "value": 100, "state": "danger"}, {"op": ">=", "value": 0, "state": "success"}]
    )
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/boards/").content.decode()
    assert 'hx-get="/smallstack/dashboards/d/board/digest/" hx-trigger="revealed"' in html
    frag = client.get("/smallstack/dashboards/d/board/digest/").content.decode()
    assert "1 needs attention: Requests" in frag and "1 fine" in frag and "on all time" in frag
    Metric.objects.filter(key="m_req").update(thresholds=[])
    frag = client.get("/smallstack/dashboards/d/board/digest/").content.decode()
    assert "All clear" in frag


def test_rows_modal_switches_period_in_place(client, staff, board):
    client.force_login(staff)
    frag = client.get("/smallstack/dashboards/m/m_req/rows/", {"period": "mtd"}).content.decode()
    assert 'hx-get="/smallstack/dashboards/m/m_req/rows/?period=today&amp;retitle=1"' in frag
    assert 'hx-target="#stat-modal-body"' in frag
    assert "Up from 0 in all of last month" in frag  # count metric: rows = value, so the count compares
    narrow = json.dumps({"field": "method", "op": "=", "value": "GET"})
    frag = client.get("/smallstack/dashboards/m/m_req/rows/", {"period": "mtd", "narrow": narrow}).content.decode()
    assert "dm-compare" not in frag  # a group isn't the metric's value
    assert "narrow=" in frag  # period links keep the group
    plain = client.get("/smallstack/dashboards/m/m_req_auth/rows/").content.decode()
    assert "dm-periods" not in plain  # no period field, nothing to switch


def test_rows_modal_period_switch_retitles_the_modal(client, staff, board):
    client.force_login(staff)
    frag = client.get("/smallstack/dashboards/m/m_req/rows/", {"period": "mtd"}).content.decode()
    assert "retitle=1" in frag and "hx-swap-oob" not in frag  # first open keeps the card's title
    frag = client.get("/smallstack/dashboards/m/m_req/rows/", {"period": "today", "retitle": "1"}).content.decode()
    assert '<span id="stat-modal-title" hx-swap-oob="innerHTML">Requests, today</span>' in frag


def test_report_preview_carries_what_drill_and_digest_need(client, staff, board):
    client.force_login(staff)
    data = client.post(
        "/smallstack/dashboards/api/report-preview/",
        json.dumps({"items": ["m_req", "m_req_auth"], "periods": ["mtd", "pmtd"]}),
        content_type="application/json",
    ).json()
    assert data["rows"][0]["metric"] == "m_req" and data["rows"][0]["period_aware"] is True
    assert data["rows"][1]["period_aware"] is False
    page = client.get("/smallstack/dashboards/reports/new/").content.decode()
    assert 'data-rows-url="/smallstack/dashboards/m/METRIC/rows/"' in page and 'id="rf-digest"' in page


def test_rows_modal_shows_an_unlisted_period(client, staff, board):
    client.force_login(staff)
    frag = client.get("/smallstack/dashboards/m/m_req/rows/", {"period": "pmtd"}).content.decode()
    assert 'aria-current="true">Last month</a>' in frag


def test_dashboard_form_miniature_cards_open_rows(client, staff, board):
    client.force_login(staff)
    html = client.get(f"/smallstack/dashboards/boards/{board.pk}/edit/").content.decode()
    assert 'data-rows-url="/smallstack/dashboards/m/METRIC/rows/"' in html and 'id="df-digest"' in html
    assert 'data-cell-id="a" data-label="Requests" data-metric="m_req"' in html and 'role="button"' in html
    assert 'data-cell-id="c" data-metric' not in html  # a text card has no rows


# -- round wrap-up: preview rows, agent parity ------------------------------------------------------


def test_preview_rows_shows_an_unsaved_metrics_rows(client, staff, member):
    _seed()
    client.force_login(staff)
    body = {"dataset": DS_STAFF, "filter_tree": {"field": "method", "op": "=", "value": "GET"}}
    frag = client.post("/smallstack/dashboards/preview-rows/", json.dumps(body), content_type="application/json")
    html = frag.content.decode()
    assert frag.status_code == 200 and "<strong>3 rows</strong>" in html
    assert "Open the metric" not in html  # unsaved: there's no metric page yet
    bad = client.post(
        "/smallstack/dashboards/preview-rows/",
        json.dumps({"dataset": DS_STAFF, "filter_tree": {"field": "nope", "op": "=", "value": 1}}),
        content_type="application/json",
    )
    assert bad.status_code == 400 and "unknown field" in bad.content.decode()
    client.force_login(member)
    denied = client.post("/smallstack/dashboards/preview-rows/", json.dumps(body), content_type="application/json")
    assert denied.status_code == 400  # a staff dataset is unknown to a member
    page = client.get("/smallstack/dashboards/metrics/new/").content.decode()
    assert 'id="mb-see-rows"' in page


def test_metric_value_carries_the_comparison_for_agents(client, staff, board):
    client.force_login(staff)
    data = client.get("/smallstack/dashboards/api/metrics/m_req/value/", {"period": "mtd"}).json()
    assert data["value"] == 5 and data["comparison"]["dir"] == "up"
    assert client.get("/smallstack/dashboards/api/metrics/m_req/value/").json()["comparison"] is None
    out = _call("metric_value", {"key": "m_req", "period": "mtd"}, staff)
    assert out["comparison"]["text"] == "Up from 0 in all of last month"
    assert _call("metric_value", {"key": "m_req", "period": "last_30"}, staff)["comparison"] is None


def test_rest_and_mcp_deletes_clean_up_cards_and_rows(client, staff, board):
    """on_delete runs on every surface: a scripted delete leaves no "metric no
    longer exists" cards behind (the UI's ticked-by-default choice)."""
    Report(name="R", slug="del-api", items=["m_req", "m_req_auth"]).save()
    m = Metric.objects.get(key="m_req")
    client.force_login(staff)
    assert client.delete(f"/smallstack/api/dashboards/metrics/{m.pk}/").status_code == 204
    board.refresh_from_db()
    assert all(c.get("metric") != "m_req" for c in board.layout)
    assert Report.objects.get(slug="del-api").metric_keys() == ["m_req_auth"]

    from apps.dashboards.views import MetricCRUDView
    from apps.mcp.factory import register_mcp_tools_from_crudview
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    register_mcp_tools_from_crudview(MetricCRUDView)  # the MCP suite may have wiped the registry

    m2 = Metric.objects.get(key="m_req_auth")
    token = set_context(ToolContext(user=staff, token=None))
    try:
        out = TOOL_HANDLERS["delete_metric"]({"id": m2.pk})
    finally:
        reset_context(token)
    assert out.get("deleted") is True
    board.refresh_from_db()
    assert all(c.get("metric") != "m_req_auth" for c in board.layout)
    assert Report.objects.get(slug="del-api").metric_keys() == []


def test_on_delete_rolls_back_with_a_failed_delete(staff, board, monkeypatch):
    """The hook runs in the delete's transaction: if the delete raises, the
    cards it removed come back."""
    from django.db import transaction

    from apps.dashboards.views import MetricCRUDView

    m = Metric.objects.get(key="m_req")

    def boom(*a, **k):
        raise RuntimeError("delete failed")

    monkeypatch.setattr(Metric, "delete", boom)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            MetricCRUDView.on_delete(request_for(staff), m)
            m.delete()
    board.refresh_from_db()
    assert any(c.get("metric") == "m_req" for c in board.layout)


def test_grouped_cards_compare_groups_with_the_previous_period(client, staff, board):
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/d/board/cells/b/", {"period": "mtd"}).content.decode()
    assert "dash-group-change" in html and "new</span>" in html  # every group is new against an empty last month
    assert "Up from 0 in all of last month" in html  # the full wording, in the tooltip / aria-label
    other_block = html.split("dash-group--other")[1].split("</button>")[0]
    assert "dash-group-change" not in other_block  # "Other" isn't the same set last period
    rolling = client.get("/smallstack/dashboards/d/board/cells/b/", {"period": "last_30"}).content.decode()
    assert "dash-group-change" not in rolling


def test_dashboard_digest_counts_grouped_card_states(client, staff, board):
    Metric.objects.filter(key="m_req").update(thresholds=[{"op": ">=", "value": 3, "state": "danger"}])
    # The grouped card filters the dataset itself, so its colour rules are its own.
    for cell in board.layout:
        if cell["id"] == "b":
            cell["options"]["thresholds"] = [{"op": ">=", "value": 3, "state": "danger"}]
    board.save()
    client.force_login(staff)
    frag = client.get("/smallstack/dashboards/d/board/digest/").content.decode()
    # Card "a" (5 requests) and the grouped card's GET group (3) are both in danger.
    assert "2 need attention" in frag and "metric_group" not in frag
    assert "Dash log: GET" in frag  # a group is named by its card (untitled: its dataset) and its label


def test_preview_rows_requires_a_csrf_token(staff):
    """An HTML page route now, not a CSRF-exempt API route: a cross-site POST
    without the token is refused."""
    from django.test import Client

    _seed()
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(staff)
    body = json.dumps({"dataset": DS_STAFF})
    assert (
        browser.post("/smallstack/dashboards/preview-rows/", body, content_type="application/json").status_code == 403
    )


# -- the settings page's cards table -------------------------------------------------------


def test_the_settings_page_lists_the_cards_and_sorting_moves_nothing(client, staff):
    _seed()
    _metric(key="m_big", name="Alpha metric", thresholds=[{"op": ">", "value": 0, "state": "danger"}])
    _metric(key="m_gone", name="Going")
    board = Dashboard(
        name="Cards",
        slug="cards",
        layout=[
            {"id": "b", "type": "metric", "metric": "m_big", "x": 0, "y": 0, "w": 3, "h": 2, "title": "zeta"},
            {"id": "n", "type": "text", "options": {"markdown": "hi"}, "x": 3, "y": 0, "w": 6, "h": 4, "title": "Note"},
            {"id": "g", "type": "metric", "metric": "m_gone", "x": 0, "y": 2, "w": 3, "h": 2, "title": "Alpha"},
        ],
    )
    board.save()
    Metric.objects.filter(key="m_gone").delete()  # under the model's feet
    client.force_login(staff)
    layout = list(board.layout)

    html = client.get(f"/smallstack/dashboards/boards/{board.pk}/edit/").content.decode()
    assert 'data-table-key="dashboards/board-cards:name,design,metric,size,value"' in html
    assert 'hx-get="/smallstack/dashboards/d/cards/cards/b/value/"' in html and 'hx-trigger="revealed"' in html
    assert ">Missing<" in html and "Sorting only changes this table" in html
    assert html.count('hx-target="#df-cards"') == 5

    def names(query: str) -> list[str]:
        page = client.get(f"/smallstack/dashboards/d/cards/cards/?{query}").content.decode()
        return sorted(("zeta", "Note", "Alpha"), key=lambda n: page.index(f'title="{n}">{n}<'))

    assert names("") == ["zeta", "Note", "Alpha"]  # reading order
    assert names("order=name") == ["Alpha", "Note", "zeta"]  # ignoring case
    assert names("order=-size") == ["Note", "zeta", "Alpha"]
    assert names("order=-value") == ["zeta", "Note", "Alpha"]  # the only number, then the rest
    worked_out = client.get("/smallstack/dashboards/d/cards/cards/?order=-value").content.decode()
    assert "rp-value--danger" in worked_out and 'hx-trigger="revealed"' not in worked_out
    assert "Back to reading order" in worked_out
    assert names("order=bogus") == ["zeta", "Note", "Alpha"]

    value = client.get("/smallstack/dashboards/d/cards/cards/b/value/").content.decode()
    assert "rp-value--danger" in value
    assert "no longer exists" in client.get("/smallstack/dashboards/d/cards/cards/g/value/").content.decode()
    assert "—" in client.get("/smallstack/dashboards/d/cards/cards/n/value/").content.decode()
    assert client.get("/smallstack/dashboards/d/cards/cards/nope/value/").status_code == 404
    board.refresh_from_db()
    assert board.layout == layout  # sorting moved nothing


def test_the_cards_table_needs_access_to_the_board(client, member, staff):
    layout = [{"id": "n", "type": "text", "options": {"markdown": "x"}}]
    Dashboard(name="Mine", slug="mine-board", owner=staff, layout=layout).save()
    client.force_login(member)
    assert client.get("/smallstack/dashboards/d/mine-board/cards/").status_code == 404
    assert client.get("/smallstack/dashboards/d/mine-board/cards/n/value/").status_code == 404


def test_an_unsaved_metrics_rows_sort_by_posting_it_again(client, staff):
    _seed()
    client.force_login(staff)
    body = {"dataset": DS_STAFF, "filter_tree": {"field": "method", "op": "=", "value": "GET"}}

    def rows(**extra):
        response = client.post(
            "/smallstack/dashboards/preview-rows/", json.dumps({**body, **extra}), content_type="application/json"
        )
        assert response.status_code == 200, response.content[:500]
        return response.content.decode()

    html = rows()
    # Never a link: an unsaved metric only exists in this request's body.
    assert 'class="dm-sort dm-sort--btn" data-preview-order="' in html
    assert 'href=""' not in html and 'hx-get=""' not in html
    assert 'class="col-resizer"' in html and "crud-table" in html
    column = html.split('data-field="', 1)[1].split('"', 1)[0]
    sorted_html = rows(order=column)
    assert 'aria-sort="ascending" data-field="%s"' % column in sorted_html
    assert 'data-preview-order="-%s"' % column in sorted_html  # a second click flips it
    assert 'aria-sort="ascending"' not in rows(order="not_a_column")  # ignored, never passed through
