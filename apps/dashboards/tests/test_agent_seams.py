"""What an agent working over MCP/REST depends on and can't see around: a number
is the number it asked for, a refusal says why, and it can find and read back
everything it builds. Found by a cold-start agent given only the tool list."""

from __future__ import annotations

import json
import os

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.activity.models import RequestLog
from apps.calendar.models import Event, SavedCalendarView
from apps.dashboards.goals import judge
from apps.dashboards.metrics import evaluate, request_for
from apps.dashboards.models import Component, Dashboard, GoalList, Metric, Report, Snapshot
from apps.dashboards.tests.support import own
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff():
    return User.objects.create_user("seam-staff", password="x", is_staff=True)


@pytest.fixture
def token(staff):
    _obj, raw = APIToken.create_token(user=staff, name="seam", access_level="staff")
    return raw


@pytest.fixture
def rest(token):
    return Client(headers={"authorization": f"Bearer {token}"})


@pytest.fixture
def call(token):
    client = Client(headers={"authorization": f"Bearer {token}"})

    def _call(tool, /, **arguments):
        params = {"name": tool, "arguments": arguments}
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
        resp = client.post("/mcp", json.dumps(body), content_type="application/json")
        body = resp.json()
        assert "result" in body, body  # never a raw -32603: a refusal is a tool result
        return body["result"]["isError"], json.loads(body["result"]["content"][0]["text"])

    return _call


@pytest.fixture
def metric():
    RequestLog.objects.create(path="/a", method="GET", status_code=500, response_time_ms=10)
    m = Metric(key="seam_errors", name="Errors", dataset=DS, period_field="timestamp")
    m.save()
    return m


def test_a_successful_call_is_not_flagged_as_an_error(call, metric):
    is_error, out = call("metric_value", key="seam_errors")
    assert is_error is False and out["value"] >= 1 and out["error"] is None


def test_a_real_refusal_is_still_flagged(call):
    is_error, out = call("metric_value", key="nope")
    assert is_error is True and "no metric" in out["error"]


def test_an_unknown_argument_is_refused_not_dropped(call, metric):
    is_error, out = call("metric_value", key="seam_errors", perod="wtd")
    assert is_error is True
    assert "perod" in out["error"]["message"] and "period" in out["error"]["message"]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("metric_value", {"key": "seam_errors"}),
        ("metric_trend", {"key": "seam_errors"}),
        ("metric_rows", {"key": "seam_errors"}),
        ("metric_preview", {"dataset": DS}),
    ],
)
def test_a_misnamed_period_is_refused_rather_than_answered_with_all_time(call, metric, tool, args):
    is_error, out = call(tool, period="this_week", **args)
    assert "this_week" in json.dumps(out)
    assert is_error or out.get("ok") is False


def test_snapshot_refuses_a_misnamed_period(call):
    Dashboard(name="D", slug="seam-d").save()
    assert call("dashboard_snapshot", dashboard="seam-d", period="this_week")[0] is True


@pytest.mark.parametrize(
    "path",
    [
        "metrics/seam_errors/value/",
        "metrics/seam_errors/trend/",
        "metrics/seam_errors/rows/",
    ],
)
def test_rest_refuses_a_misnamed_period_in_json(rest, metric, path):
    resp = rest.get(f"/smallstack/dashboards/api/{path}?period=this_week")
    assert resp.status_code == 400 and "this_week" in resp.json()["error"]


def test_rest_missing_object_is_a_json_404(rest):
    resp = rest.get("/smallstack/dashboards/api/metrics/nope/value/")
    assert resp.status_code == 404 and resp["Content-Type"] == "application/json"


def test_period_ignored_by_a_metric_with_no_period_field_says_so(call):
    Metric(key="seam_flat", name="Flat", dataset=DS).save()
    _err, out = call("metric_value", key="seam_flat", period="mtd")
    assert "period_field" in out["note"]


def test_bad_integers_are_refusals_not_exceptions(call):
    Dashboard(name="D", slug="seam-d").save()
    GoalList(name="G", slug="seam-g").save()
    assert call("dashboard_add_card", dashboard="seam-d", type="text", options={"markdown": "x"}, w="abc")[0]
    assert call("goal_list_weeks", goal_list="seam-g", weeks="abc")[0]
    assert call("goal_list_weeks", goal_list="seam-g", week="last week")[0]


def test_an_empty_average_has_no_value_and_no_verdict(staff):
    """avg of nothing was 0, which reads as "0 ms, on target"."""
    m = Metric(
        key="seam_avg",
        name="Avg",
        dataset=DS,
        agg="avg",
        measure="response_time_ms",
        period_field="timestamp",
        filter_tree={"field": "path", "op": "=", "value": "/never"},
    )
    result = evaluate(m, request_for(staff), period="wtd")
    assert result.value is None and result.display == "—" and result.ok
    assert judge(result.value, {"op": "<=", "value": 300}) == "none"


def test_a_count_of_nothing_is_still_zero(staff):
    m = Metric(key="seam_c", name="C", dataset=DS, filter_tree={"field": "path", "op": "=", "value": "/never"})
    assert evaluate(m, request_for(staff)).value == 0


def test_discovery_lists_what_the_metric_tools_accept(call):
    _err, out = call("list_datasets")
    row = next(d for d in out["results"] if d["key"] == DS)
    assert row["query_tool"] is None  # bundled query tools are off by default; metrics still work
    assert call("describe_dataset", key=DS)[1]["key"] == DS


def test_discovery_for_a_member_hides_staff_datasets(db):
    member = User.objects.create_user("seam-member", password="x")
    _obj, raw = APIToken.create_token(user=member, name="m", access_level="auth")
    client = Client(headers={"authorization": f"Bearer {raw}"})
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_datasets", "arguments": {}}}
    resp = client.post("/mcp", json.dumps(body), content_type="application/json").json()
    keys = {d["key"] for d in json.loads(resp["result"]["content"][0]["text"])["results"]}
    assert DS not in keys


def test_everything_built_can_be_read_back_by_id_or_name(call, metric):
    _err, by_key = call("get_metric", key="seam_errors")
    assert by_key["filter_tree"] == metric.filter_tree and by_key["id"] == metric.pk
    assert call("get_metric", id=metric.pk)[1]["key"] == "seam_errors"
    GoalList(name="G", slug="seam-g", sections=[]).save()
    assert call("get_goal_list", slug="seam-g")[1]["slug"] == "seam-g"
    Dashboard(name="D", slug="seam-d").save()
    assert call("get_dashboard", slug="seam-d")[1]["layout"] == []
    assert call("get_metric", key="nope")[0] is True


def test_get_is_scoped_like_the_list(token):
    other = User.objects.create_user("seam-other", password="x")
    Metric(key="seam_private", name="P", dataset=DS, owner=other).save()
    member = User.objects.create_user("seam-m2", password="x")
    _obj, raw = APIToken.create_token(user=member, name="m", access_level="auth")
    client = Client(headers={"authorization": f"Bearer {raw}"})
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_metric", "arguments": {"key": "seam_private"}},
    }
    result = client.post("/mcp", json.dumps(body), content_type="application/json").json()["result"]
    assert result["isError"] is True


def test_update_finds_the_row_by_its_name(call, metric):
    is_error, out = call("update_metric", key="seam_errors", name="Server errors")
    assert is_error is False and out["name"] == "Server errors"


def test_delete_says_what_went_with_it(call, metric):
    Dashboard(name="D", slug="seam-d", layout=[{"id": "c", "type": "metric", "metric": metric.key}]).save()
    Report(name="R", slug="seam-r", items=[{"metric": metric.key}], periods=["mtd"]).save()
    Component(name="Card", type="metric", metric=metric.key).save()
    goals = [{"title": "S", "goals": [{"metric": metric.key, "target": {"op": "<=", "value": 1}}]}]
    GoalList(name="G", slug="seam-g", sections=goals).save()
    _err, out = call("delete_metric", key=metric.key)
    assert out["deleted"] is True
    assert out["also_removed"]["cards"] == 1 and out["also_removed"]["report_rows_and_goals"] == 2
    assert out["also_removed"]["saved_cards"] == ["card"]
    assert not Component.objects.filter(metric=metric.key).exists()  # no card left drawing a missing metric


def test_a_goal_on_a_saved_card_leaves_with_its_metric(call, metric):
    card = Component(name="Card", type="metric", metric=metric.key)
    card.save()
    goals = [{"title": "S", "goals": [{"component": card.key, "target": {"op": "<=", "value": 1}}]}]
    GoalList(name="G", slug="seam-g", sections=goals).save()
    call("delete_metric", key=metric.key)
    assert GoalList.objects.get(slug="seam-g").goals() == []


def test_a_misspelt_card_column_is_refused_on_save_and_in_preview(call, metric):
    source = own(metric.key)  # a split filters a dataset of its own
    is_error, out = call("card_preview", type="metric_group", **source, options={"dimension": "nope"})
    assert out["problems"] and "nope" in out["problems"][0]
    assert call("create_component", name="X", type="metric_group", **source, options={"dimension": "nope"})[0]


def test_an_agent_gives_a_chart_its_own_source_and_a_stat_a_metric(call, metric):
    """The rule over MCP: a metric goes on a single stat only; a split or a
    chart carries dataset + filter_tree + agg/measure/period_field, and
    card_preview says so when an agent sends the one the other way round."""
    is_error, out = call("card_preview", type="metric_group", metric=metric.key, options={"dimension": "method"})
    assert out["problems"] and "filters a dataset of its own" in out["problems"][0]
    is_error, out = call("card_preview", type="metric", **own(metric.key), name="Own")
    assert not out["problems"] and "Own" in out["html"]
    split = {"type": "metric_group", **own(metric.key), "options": {"dimension": "method"}}
    is_error, out = call("create_component", name="Split", **split)
    assert not is_error and Component.objects.get(key="split").dataset == metric.dataset
    Dashboard(name="Agent", slug="seam-agent", layout=[]).save()
    is_error, out = call("dashboard_add_card", dashboard="seam-agent", **split)
    assert not is_error, out
    assert Dashboard.objects.get(slug="seam-agent").layout[0]["dataset"] == metric.dataset


def test_a_note_needs_its_text(call):
    _err, out = call("card_preview", type="text")
    assert "markdown" in out["problems"][0]


def test_a_week_can_be_saved_over_mcp_and_rest(call, rest, metric):
    goals = [{"title": "S", "goals": [{"metric": metric.key, "target": {"op": "<=", "value": 1}}]}]
    GoalList(name="G", slug="seam-g", sections=goals).save()
    is_error, out = call("goal_list_save_week", goal_list="seam-g")
    assert is_error is False and out["ok"] and Snapshot.objects.count() == 1
    resp = rest.post("/smallstack/dashboards/api/goals/seam-g/weeks/2026-W40/save/")
    assert resp.status_code == 200 and Snapshot.objects.count() == 2


def test_a_readonly_token_cannot_save_a_week_over_rest(staff, metric):
    GoalList(name="G", slug="seam-g", sections=[]).save()
    _obj, raw = APIToken.create_token(user=staff, name="ro", access_level="readonly")
    client = Client(headers={"authorization": f"Bearer {raw}"})
    assert client.post("/smallstack/dashboards/api/goals/seam-g/weeks/2026-W40/save/").status_code == 403
    assert Snapshot.objects.count() == 0


def test_rows_behind_a_number_reconcile_with_it(call, metric):
    # Only the seeded row: the request log also records these calls.
    metric.filter_tree = {"field": "path", "op": "=", "value": "/a"}
    metric.save()
    _err, value = call("metric_value", key=metric.key)
    _err, rows = call("metric_rows", key=metric.key, limit=5)
    assert rows["total"] == value["value"] and rows["columns"] and len(rows["rows"]) <= 5


def test_openapi_advertises_detail_get_and_the_evaluation_routes(rest):
    paths = rest.get("/api/schema/openapi.json").json()["paths"]
    assert "get" in paths["/smallstack/api/dashboards/metrics/{id}/"]
    assert "get" in paths["/smallstack/dashboards/api/metrics/{key}/value/"]
    assert "post" in paths["/smallstack/dashboards/api/goals/{slug}/weeks/{week}/save/"]


def test_a_time_makes_an_event_timed_over_mcp(call):
    is_error, out = call("create_event", title="Patch", start_date="2026-11-14", start_time="22:00", end_time="23:59")
    assert is_error is False and out["all_day"] is False
    assert Event.objects.get(pk=out["id"]).all_day is False


def test_duplicate_saved_view_name_is_a_validation_error(call, staff):
    SavedCalendarView.objects.create(owner=staff, name="Ops", datasets=[])
    is_error, out = call("create_calendar_view", name="Ops", datasets=[])
    assert is_error is True and "already" in json.dumps(out)
    assert SavedCalendarView.objects.filter(owner=staff).count() == 1


def test_cards_added_one_by_one_fill_the_row(call, metric):
    Dashboard(name="D", slug="seam-d").save()
    for _ in range(5):
        call("dashboard_add_card", dashboard="seam-d", type="metric", metric=metric.key, w=3, h=2)
    positions = [(c["x"], c["y"]) for c in Dashboard.objects.get(slug="seam-d").layout]
    assert positions == [(0, 0), (3, 0), (6, 0), (9, 0), (0, 2)]


def test_a_card_never_lands_on_a_tall_one_beside_it():
    from apps.dashboards.components import next_position

    layout = [{"x": 0, "y": 0, "w": 6, "h": 5}, {"x": 6, "y": 2, "w": 3, "h": 1}]
    assert next_position(layout, 3) == (9, 2)
    assert next_position(layout, 4) == (0, 5)


def test_csv_cells_a_spreadsheet_would_run_are_neutralised():
    from apps.datasets.core import csv_safe

    assert csv_safe("=cmd|calc") == "'=cmd|calc"
    assert csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert csv_safe("-1+2") == "'-1+2"
    assert csv_safe("-12.5") == "-12.5" and csv_safe(-3) == -3 and csv_safe("plain") == "plain"


def test_a_report_csv_neutralises_its_labels(rest, metric, staff):
    Report(name="R", slug="seam-csv", items=[{"metric": metric.key, "label": "=cmd|calc"}], periods=["mtd"]).save()
    client = Client()
    client.force_login(staff)
    body = client.get("/smallstack/dashboards/r/seam-csv/?format=csv", SERVER_NAME="localhost").content.decode()
    assert "'=cmd|calc" in body


def test_a_period_on_a_metric_that_cant_have_one_is_refused(call):
    Metric(key="seam_flat", name="Flat", dataset=DS).save()
    GoalList(name="G", slug="seam-g", sections=[]).save()
    is_error, out = call(
        "goal_list_add_goal", goal_list="seam-g", metric="seam_flat", period="pwtd", target={"op": "<=", "value": 1}
    )
    assert is_error is True and "period" in json.dumps(out)


def test_a_value_a_choices_column_cant_hold_is_refused(call):
    _err, out = call(
        "metric_preview",
        dataset="smallstack_heartbeats",
        filter_tree={"and": [{"field": "status", "op": "=", "value": "failure"}]},
    )
    assert out["ok"] is False and "failure" in out["problems"][0] and "fail" in out["problems"][0]
    _err, ok = call(
        "metric_preview",
        dataset="smallstack_heartbeats",
        filter_tree={"and": [{"field": "status", "op": "in", "value": ["fail", "ok"]}]},
    )
    assert ok["ok"] is True


def test_last_week_compares_with_the_week_before(call, metric):
    _err, out = call("metric_value", key=metric.key, period="pwtd")
    # Only a difference in numbers can make this null: there's a week to compare with.
    assert out["comparison"] is None or "the week before" in out["comparison"]["text"]
    from apps.datasets.dateranges import is_period, relative_dates

    assert is_period("ppwtd")
    lo, hi = relative_dates("pwtd")
    plo, phi = relative_dates("ppwtd")
    assert phi == lo and (hi - lo) == (phi - plo)


def test_cells_with_no_position_are_placed_and_overlaps_refused(staff):
    from apps.dashboards.components import normalize_layout

    note = {"type": "text", "options": {"markdown": "x"}, "w": 6, "h": 2}
    placed, problems = normalize_layout([note, dict(note)], owner_id=None)
    assert not problems and [(c["x"], c["y"]) for c in placed] == [(0, 0), (6, 0)]
    a = {**note, "id": "a", "x": 0, "y": 0}
    b = {**note, "id": "b", "x": 2, "y": 1}
    _out, problems = normalize_layout([a, b], owner_id=None)
    assert any("overlap" in p for p in problems)


def test_list_tools_say_how_many_there_are_and_refuse_a_silly_limit(call, metric):
    Metric(key="seam_two", name="Two", dataset=DS).save()
    _err, out = call("list_metrics", limit=1)
    assert out["count"] == 1 and out["total"] == 2
    assert call("list_metrics", limit=0)[0] is True and call("list_metrics", limit=-1)[0] is True


def test_rows_refuse_a_bad_limit_and_order(call, metric):
    assert call("metric_rows", key=metric.key, limit=-1)[0] is True
    assert call("metric_rows", key=metric.key, order="-nosuch")[0] is True


def test_usage_can_be_read_before_a_delete_and_delete_names_it(call, metric):
    Dashboard(name="Board", slug="seam-d", layout=[{"id": "c", "type": "metric", "metric": metric.key}]).save()
    _err, usage = call("metric_usage", key=metric.key)
    assert usage["dashboards"][0]["slug"] == "seam-d"
    _err, out = call("delete_metric", key=metric.key)
    assert out["also_removed"]["dashboards"] == ["Board"]


def test_report_csv_over_rest_with_a_token(rest, metric):
    Report(name="R", slug="seam-r", items=[{"metric": metric.key}], periods=["mtd"]).save()
    resp = rest.get("/smallstack/dashboards/api/reports/seam-r/values/?format=csv")
    assert resp.status_code == 200 and resp["Content-Type"] == "text/csv"


def test_own_personal_metric_on_something_shared_is_explained(call):
    Metric(key="seam_mine", name="Mine", dataset=DS, owner=User.objects.get(username="seam-staff")).save()
    _err, out = call(
        "create_goal_list",
        name="G",
        slug="seam-shared",
        visibility="shared",
        sections=[{"title": "S", "goals": [{"metric": "seam_mine", "target": {"op": "<=", "value": 1}}]}],
    )
    assert "share it first" in json.dumps(out)


@pytest.mark.parametrize(
    ("setting", "module", "probe"),
    [
        ("SMALLSTACK_CALENDAR_ENABLED", "apps/calendar/views.py", "create_event"),
        ("SMALLSTACK_DASHBOARDS_ENABLED", "apps/dashboards/views.py", "create_metric"),
        ("SMALLSTACK_BLOG_ENABLED", "apps/blog/views.py", "create_blog"),
        ("SMALLSTACK_BLOG_ENABLED", "apps/blog/mcp_tools.py", "blog_draft_post"),
    ],
)
def test_a_switched_off_feature_has_no_mcp_tools(setting, module, probe):
    """The switch is read when the class is defined, so this takes a fresh process:
    override_settings can't reach it. The URLconf and the tools must agree."""
    import subprocess
    import sys

    code = (
        "import django; django.setup();"
        "from apps.mcp.server import TOOL_REGISTRY;"
        f"print('LEAK' if {probe!r} in TOOL_REGISTRY else 'CLEAN')"
    )
    env = {**os.environ, setting: "False", "DJANGO_SETTINGS_MODULE": "config.settings.test"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    assert out.stdout.strip().endswith("CLEAN"), out.stdout + out.stderr
