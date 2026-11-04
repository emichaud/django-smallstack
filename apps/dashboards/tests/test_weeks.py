"""Targets on reports, trends on goal lists, and goal lists week by week:
snapshots, moving between weeks, the week-over-week grid (and its CSV), the
trends around a week, the Monday schedule and the agent surfaces."""

from __future__ import annotations

import csv
import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory
from django.utils import timezone

from apps.activity.models import RequestLog
from apps.dashboards.goals import evaluate_goals, trend_grain
from apps.dashboards.models import GoalList, Metric, Report, Snapshot
from apps.dashboards.reports import report_matrix, report_values, write_report_csv
from apps.dashboards.weeks import (
    parse_week,
    snapshot_last_week,
    take_snapshot,
    this_week,
    week_grid,
    week_label,
    week_of,
    week_page,
    week_trends,
)

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"
SEEDED = {"field": "path", "op": "in", "value": ["/w"]}


@pytest.fixture
def staff(client):
    user = User.objects.create_user("wk-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def _log(weeks_ago: int, n: int) -> None:
    """*n* requests to /w in the week *weeks_ago* weeks back (local midnight)."""
    from apps.dashboards.weeks import today

    # Mid-week, but never in the future: this week's rows land today at the latest.
    day = this_week() - timedelta(weeks=weeks_ago) + timedelta(days=2 if weeks_ago else min(2, today().weekday()))
    when = timezone.make_aware(timezone.datetime(day.year, day.month, day.day, 0, 5))
    for _ in range(n):
        log = RequestLog.objects.create(path="/w", method="GET", status_code=200, response_time_ms=10)
        RequestLog.objects.filter(pk=log.pk).update(timestamp=when)


@pytest.fixture
def metric():
    # 3 weeks ago: 2; 2 weeks ago: 6; last week: 4; this week: 1.
    for weeks_ago, n in ((3, 2), (2, 6), (1, 4), (0, 1)):
        _log(weeks_ago, n)
    m = Metric(key="wk_req", name="Requests", dataset=DS, period_field="timestamp", filter_tree=SEEDED)
    m.save()
    return m


@pytest.fixture
def goal_list(metric, staff):
    g = GoalList(
        name="Weekly",
        slug="weekly",
        sections=[{"title": "Traffic", "goals": [{"metric": "wk_req", "target": {"op": ">=", "value": 4}}]}],
    )
    g.created_by = staff
    g.save()
    return g


@pytest.fixture
def rf(staff):
    request = RequestFactory().get("/")
    request.user = staff
    return request


# -- week arithmetic -------------------------------------------------------------------


def test_weeks_run_monday_to_sunday():
    from datetime import date

    assert week_of(date(2026, 11, 5)) == date(2026, 11, 2)
    assert parse_week("2026-11-08") == date(2026, 11, 2) and parse_week("2026-W45") == date(2026, 11, 2)
    assert parse_week("soon") is None
    assert week_label(date(2026, 11, 2)) == "Nov 2 – 8, 2026"
    assert week_label(date(2026, 10, 26)) == "Oct 26 – Nov 1, 2026"
    assert week_label(date(2025, 12, 29)) == "Dec 29, 2025 – Jan 4, 2026"


# -- reports get targets ------------------------------------------------------------------


def test_a_report_row_takes_a_target(rf, metric):
    report = Report(
        name="KPIs",
        slug="kpis",
        periods=["wtd", "pwtd"],
        items=[{"metric": "wk_req", "target": {"op": ">=", "value": 4}, "warn": {"op": ">=", "value": 2}}],
    )
    report.save()
    matrix = report_matrix(report, rf)
    row = matrix["rows"][0]
    assert matrix["has_targets"] and row["target_text"] == "≥ 4" and row["warn_text"] == "≥ 2"
    this, last = row["cells"]
    assert (this["status"], last["status"]) == ("fail", "pass")  # 1 this week, 4 last week
    assert last["result"].state == "success" and this["result"].state == "danger"  # the target colours them
    out = io.StringIO()
    write_report_csv(matrix, out)
    head, line = list(csv.reader(io.StringIO(out.getvalue())))
    assert head[:4] == ["Metric", "Target", "At risk", "Week to date"] and head[4] == "Week to date status"
    assert line[:6] == ["Requests", "≥ 4", "≥ 2", "1", "Missed", "4"]
    assert report_values(report, rf)["rows"][0]["values"][1]["status"] == "pass"


def test_a_report_target_is_checked(metric):
    with pytest.raises(ValidationError, match="target.op"):
        Report(name="Bad", slug="bad", items=[{"metric": "wk_req", "target": {"op": "~", "value": 1}}]).save()
    with pytest.raises(ValidationError, match="needs a target"):
        Report(name="Bad", slug="bad", items=[{"metric": "wk_req", "warn": {"op": ">=", "value": 1}}]).save()


def test_the_report_page_shows_targets(client, staff, metric):
    Report(
        name="KPIs", slug="kpis", periods=["pwtd"], items=[{"metric": "wk_req", "target": {"op": ">=", "value": 4}}]
    ).save()
    html = client.get("/smallstack/dashboards/r/kpis/").content.decode()
    assert 'data-field="target"' in html and "≥ 4" in html and "gl-icon--pass" in html


# -- trends on goal lists --------------------------------------------------------------


def test_a_goal_trend_judges_each_period(rf, goal_list):
    assert trend_grain("wtd") == "week" and trend_grain("mtd") == "month" and trend_grain(None) == "month"
    row = evaluate_goals(goal_list, rf, period="wtd", trend=True)["rows"][0]
    points = row["trend"]["points"]
    assert len(points) == 6 and points[-1]["partial"]
    assert [p["display"] for p in points[-4:]] == ["2", "6", "4", "1"]
    assert [p["status"] for p in points[-4:]] == ["fail", "pass", "pass", "fail"]
    assert row["trend"]["streak"] == "On target 2 weeks running"


def test_the_meeting_view_has_a_trend_column(client, goal_list):
    html = client.get("/smallstack/dashboards/g/weekly/?period=wtd").content.decode()
    assert 'data-field="trend"' in html and 'class="gl-spark"' in html and "On target 2 weeks running" in html


# -- weeks --------------------------------------------------------------------------


def test_a_week_is_worked_out_live_until_it_is_saved(rf, goal_list, staff):
    last = this_week() - timedelta(weeks=1)
    page = week_page(goal_list, rf, last)
    assert page["live"] and page["rows"][0]["display"] == "4" and page["rows"][0]["status"] == "pass"
    assert page["rows"][0]["change"]["text"] == "33% vs the week before"  # 6 → 4
    snapshot = take_snapshot(goal_list, last, by=staff)
    assert snapshot.complete and snapshot.summary["headline"] == "1 of 1 on target"
    # Raising the target later doesn't rewrite the saved week.
    goal_list.sections[0]["goals"][0]["target"] = {"op": ">=", "value": 100}
    goal_list.save()
    saved = week_page(goal_list, rf, last)
    assert not saved["live"] and saved["rows"][0]["status"] == "pass" and saved["rows"][0]["target_text"] == "≥ 4"
    assert week_page(goal_list, rf, last - timedelta(weeks=1))["rows"][0]["status"] == "fail"  # live: today's target
    with pytest.raises(ValueError, match="hasn't started"):
        take_snapshot(goal_list, this_week() + timedelta(weeks=1))


def test_the_week_over_week_grid_and_its_csv(client, rf, goal_list, staff):
    take_snapshot(goal_list, this_week() - timedelta(weeks=2), by=staff)
    grid = week_grid(goal_list, rf, this_week(), count=4)
    assert [c["snapshot"] is not None for c in grid["columns"]] == [False, True, False, False]
    assert [c["display"] for c in grid["rows"][0]["cells"]] == ["2", "6", "4", "1"]
    assert grid["columns"][-1]["state"] == "current" and grid["next"] is None
    response = client.get("/smallstack/dashboards/g/weekly/weeks/?view=grid&format=csv")
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][:5] == [
        "Section",
        "Goal",
        "Target",
        f"Week of {grid['columns'][0]['start'] - timedelta(weeks=4):%Y-%m-%d}",
        rows[0][4],
    ]
    assert rows[1][:3] == ["Traffic", "Requests", "≥ 4"] and rows[1][-2:] == ["1", "Missed"]


def test_goals_that_left_the_list_still_show_in_saved_weeks(rf, goal_list, staff):
    take_snapshot(goal_list, this_week() - timedelta(weeks=1), by=staff)
    goal_list.sections = [{"title": "New", "goals": []}]
    goal_list.save()
    grid = week_grid(goal_list, rf, this_week(), count=2)
    assert [(r["section"], r["label"]) for r in grid["rows"]] == [("No longer on the list", "Requests")]
    assert grid["rows"][0]["cells"][1].get("absent")


def test_the_trends_around_a_week(rf, goal_list):
    trends = week_trends(goal_list, rf, this_week() - timedelta(weeks=1))
    row = trends["rows"][0]
    assert [p["display"] for p in row["points"][-4:]] == ["2", "6", "4", "1"]
    assert [p["focus"] for p in row["points"][-2:]] == [True, False]
    assert row["change"]["text"] == "33% vs the week before"
    assert row["streak"] == "On target 2 weeks running" and row["best"] and row["worst"]


def test_the_weeks_pages(client, goal_list, staff):
    last = this_week() - timedelta(weeks=1)
    html = client.get(f"/smallstack/dashboards/g/weekly/weeks/?week={last:%Y-%m-%d}").content.decode()
    assert "Not saved: worked out now" in html and "Save this week" in html and 'aria-label="Next week"' in html
    client.post(f"/smallstack/dashboards/g/weekly/weeks/{last:%Y-%m-%d}/snapshot/")
    html = client.get(f"/smallstack/dashboards/g/weekly/weeks/?week={last:%Y-%m-%d}").content.decode()
    assert "Saved" in html and f"by {staff}" in html and "Save again" in html
    grid = client.get("/smallstack/dashboards/g/weekly/weeks/?view=grid").content.decode()
    assert 'class="gw-grid crud-table"' in grid and "Trends" in grid
    assert 'title="1 of 1 goals on target">1/1<' in grid
    modal = client.get(f"/smallstack/dashboards/g/weekly/weeks/{last:%Y-%m-%d}/trends/", HTTP_HX_REQUEST="true")
    assert 'class="gwt"' in modal.content.decode()
    client.post(f"/smallstack/dashboards/g/weekly/weeks/{this_week():%Y-%m-%d}/snapshot/", {"fill": "3"})
    assert goal_list.snapshots.count() == 3  # last week already saved


def test_only_editors_save_weeks(client, goal_list):
    member = User.objects.create_user("wk-member", password="x")
    client.force_login(member)
    assert client.get("/smallstack/dashboards/g/weekly/weeks/").status_code == 200  # a shared list: viewable
    assert client.post(f"/smallstack/dashboards/g/weekly/weeks/{this_week():%Y-%m-%d}/snapshot/").status_code == 404


def test_a_saved_value_stays_hidden_from_a_viewer_who_cannot_read_its_dataset(goal_list, staff, monkeypatch):
    take_snapshot(goal_list, this_week() - timedelta(weeks=1), by=staff)
    member = User.objects.create_user("wk-member", password="x")
    request = RequestFactory().get("/")
    request.user = member
    monkeypatch.setattr("apps.datasets.registry.user_may_read", lambda dfn, user: user.is_staff)
    row = week_page(goal_list, request, this_week() - timedelta(weeks=1))["rows"][0]
    assert row["restricted"] and row["display"] == "—" and row["value"] is None


def test_the_monday_schedule_and_the_command(goal_list):
    assert snapshot_last_week() == 1
    assert Snapshot.objects.get().week_start == this_week() - timedelta(weeks=1)
    call_command("snapshot_goals", "--list", "weekly", "--fill", "3", stdout=io.StringIO())
    assert Snapshot.objects.count() == 3
    from apps.dashboards.tasks import capture_snapshots
    from apps.scheduler.decorators import _SCHEDULE_REGISTRY

    assert any(
        spec.name == "Snapshots: capture what's due" and spec.cron_expression == "5 * * * *"
        for spec in _SCHEDULE_REGISTRY
    )
    assert capture_snapshots is not None


def test_agents_read_weeks(client, goal_list, staff):
    from apps.dashboards.tests.test_dashboards import _call

    take_snapshot(goal_list, this_week() - timedelta(weeks=1), by=staff)
    api = client.get("/smallstack/dashboards/api/goals/weekly/weeks/?weeks=3").json()
    assert [w["snapshot"] for w in api["weeks"]] == [False, True, False]
    assert [c["display"] for c in api["goals"][0]["weeks"]] == ["6", "4", "1"]
    out = _call("goal_list_weeks", {"goal_list": "weekly", "weeks": 2}, staff)
    assert out["goals"][0]["weeks"][0]["status"] == "pass"


def test_deleting_a_list_deletes_its_weeks(goal_list, staff):
    take_snapshot(goal_list, this_week() - timedelta(weeks=1), by=staff)
    GoalList.objects.get().delete()
    assert not Snapshot.objects.exists()


# -- the weekly view in playlists ------------------------------------------------------


def test_a_playlist_shows_a_goal_list_now_last_week_or_week_over_week(client, goal_list, staff):
    from apps.dashboards.models import Playlist
    from apps.dashboards.playlists import normalize_items, playlist_slides

    items, problems = normalize_items(
        [{"goals": "weekly"}, {"goals": "weekly", "show": "week"}, {"goals": "weekly", "show": "weeks"}], owner_id=None
    )
    assert problems == [] and items[0] == {"goals": "weekly"} and items[2]["show"] == "weeks"
    _items, bad = normalize_items([{"goals": "weekly", "show": "fortnight"}], owner_id=None)
    assert "show is one of" in bad[0]
    playlist = Playlist(name="Wall", slug="wall", items=items)
    playlist.save()
    slides = playlist_slides(playlist, staff)
    assert [s["name"] for s in slides] == ["Weekly", "Weekly, last week", "Weekly, week over week"]
    assert slides[2]["url"] == "/smallstack/dashboards/g/weekly/weeks/?view=grid"
    take_snapshot(goal_list, this_week() - timedelta(weeks=1), by=staff)
    week = client.get("/smallstack/dashboards/p/wall/slides/2/").content.decode()
    assert "Week of " in week and "gw-saved" in week and 'gl-of">of 1' in week
    grid = client.get("/smallstack/dashboards/p/wall/slides/3/").content.decode()
    assert 'class="gw-grid"' in grid and "Trends" in grid


def test_an_info_card_without_its_widget_says_what_to_pick():
    from apps.dashboards.components import normalize_layout

    _layout, problems = normalize_layout([{"type": "widget", "options": {}}])
    assert problems == ["layout[0].options: pick a widget ('widget': a key from list_dashboard_components)"]
    _layout, problems = normalize_layout([{"type": "widget", "options": {"widget": "ghost"}}])
    assert "no published widget 'ghost'" in problems[0] and "apps." not in problems[0]  # no key dump


# -- sorting and resizing the weekly grid ------------------------------------------------


def test_the_weekly_grid_sorts_and_resizes(client, goal_list, metric):
    Metric(key="wk_all", name="all requests", dataset=DS, period_field="timestamp", filter_tree=SEEDED).save()
    Metric(
        key="wk_none",
        name="Zero",
        dataset=DS,
        period_field="timestamp",
        filter_tree={"field": "path", "op": "=", "value": "/none"},
    ).save()
    goal_list.sections = [
        {"title": "A", "goals": [{"metric": "wk_req", "label": "Bravo", "target": {"op": ">=", "value": 1}}]},
        {
            "title": "B",
            "goals": [
                {"metric": "wk_none", "label": "alpha", "target": {"op": ">=", "value": 1}},
                {"metric": "wk_all", "label": "Charlie", "target": {"op": ">=", "value": 1}, "period": "all"},
            ],
        },
    ]
    goal_list.save()
    last = this_week() - timedelta(weeks=2)  # Bravo 6, Charlie 6, alpha 0

    def names(query: str) -> list[str]:
        page = client.get(f"/smallstack/dashboards/g/weekly/weeks/?view=grid&{query}").content.decode()
        return sorted(("alpha", "Bravo", "Charlie"), key=lambda n: page.index(f'class="gw-goal-name">{n}<'))

    html = client.get("/smallstack/dashboards/g/weekly/weeks/?view=grid").content.decode()
    assert 'data-table-key="dashboards/goal-weeks:goal,w1,w2,w3,w4,w5,w6,w7,w8"' in html
    assert html.count('class="col-resizer"') == 9 and 'data-field="w8"' in html
    assert "gw-section" in html and "Back to the list's order" not in html
    assert names("ordering=") == ["Bravo", "alpha", "Charlie"]  # the list's own order
    assert names("order=goal") == ["alpha", "Bravo", "Charlie"]  # ignoring case
    assert names("order=-goal") == ["Charlie", "Bravo", "alpha"]
    sorted_html = client.get(
        f"/smallstack/dashboards/g/weekly/weeks/?view=grid&order=w{last:%Y-%m-%d}"
    ).content.decode()
    assert "Back to the list's order" in sorted_html and "gw-section" not in sorted_html
    assert f"order=w{last:%Y-%m-%d}" in sorted_html.split('aria-label="Previous week"')[0]  # the arrows keep the sort
    assert names(f"order=-w{last:%Y-%m-%d}")[-1] == "alpha"  # 0 sorts last, largest first
    assert names(f"order=w{last:%Y-%m-%d}")[0] == "alpha"
    assert names("order=w1999-01-04") == ["Bravo", "alpha", "Charlie"]  # a week not shown: ignored
    rows = list(
        csv.reader(
            io.StringIO(
                client.get("/smallstack/dashboards/g/weekly/weeks/?view=grid&order=goal&format=csv").content.decode()
            )
        )
    )
    assert [r[1] for r in rows[1:]] == ["alpha", "Bravo", "Charlie"]


def test_a_slide_grid_has_no_sorting(client, goal_list, staff):
    from apps.dashboards.models import Playlist

    Playlist(name="Wall", slug="wall", items=[{"goals": "weekly", "show": "weeks"}]).save()
    slide = client.get("/smallstack/dashboards/p/wall/slides/1/").content.decode()
    assert 'class="gw-grid"' in slide and "col-resizer" not in slide and "dm-sort" not in slide


def test_the_trends_modal_sorts_and_resizes(client, goal_list, metric):
    Metric(
        key="wk_none",
        name="Zero",
        dataset=DS,
        period_field="timestamp",
        filter_tree={"field": "path", "op": "=", "value": "/none"},
    ).save()
    goal_list.sections[0]["goals"] += [
        {"metric": "wk_none", "label": "alpha", "target": {"op": ">=", "value": 1}},
        {"metric": "wk_req", "label": "Charlie", "target": {"op": "<=", "value": 100}},
    ]
    goal_list.save()
    url = f"/smallstack/dashboards/g/weekly/weeks/{this_week() - timedelta(weeks=1):%Y-%m-%d}/trends/"

    def names(query: str = "") -> list[str]:
        page = client.get(f"{url}?{query}", HTTP_HX_REQUEST="true").content.decode()
        return sorted(("Requests", "alpha", "Charlie"), key=lambda n: page.index(f'class="gwt-name">{n}<'))

    html = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert 'class="gwt-table crud-table" data-table-key="dashboards/goal-week-trends:' in html
    assert html.count('class="col-resizer"') == 6 and 'hx-target="#stat-modal-body"' in html
    assert names() == ["Requests", "alpha", "Charlie"]
    assert names("order=goal") == ["alpha", "Charlie", "Requests"]
    assert names("order=-goal") == ["Requests", "Charlie", "alpha"]
    assert names("order=-value")[-1] == "alpha"  # 4, 4, 0
    assert names("order=value")[0] == "alpha"
    # Requests and Charlie both fell 6 → 4 (-33%); alpha has no change to sort by, so it's last.
    assert names("order=change")[-1] == "alpha" and names("order=-change")[-1] == "alpha"
    assert names("order=-run")[0] == "alpha"  # missed every week: the longest run
    assert "Back to the list's order" in client.get(f"{url}?order=goal", HTTP_HX_REQUEST="true").content.decode()
    assert names("order=bogus") == ["Requests", "alpha", "Charlie"]


# -- the reports list sorts by movement --------------------------------------------------


def test_the_reports_list_sorts_by_movement(client, staff, metric):
    # wk_req: 4 last week, 6 the week before — down. A flat metric: 0 and 0.
    Metric(
        key="wk_flat",
        name="Flat",
        dataset=DS,
        period_field="timestamp",
        filter_tree={"field": "path", "op": "=", "value": "/none"},
    ).save()
    Report(name="Falling", slug="falling", periods=["pwtd", "wtd"], items=["wk_req"]).save()  # 4 vs 1: up
    Report(name="Rising", slug="rising", periods=["wtd", "pwtd"], items=["wk_req"]).save()  # 1 vs 4: down
    Report(name="Steady", slug="steady", periods=["wtd", "pwtd"], items=["wk_flat"]).save()
    Report(name="Single", slug="single", periods=["wtd"], items=["wk_req"]).save()

    def order(query: str) -> list[str]:
        page = client.get(f"/smallstack/dashboards/reports/?{query}").content.decode()
        names = ["Falling", "Rising", "Steady", "Single"]
        return sorted(names, key=lambda n: page.index(f'class="lib-name">{n}<'))

    html = client.get("/smallstack/dashboards/reports/").content.decode()
    assert (
        'data-field="movement"' in html
        and 'data-table-key="dashboards/reports:name,columns,movement,updated_at"' in html
    )
    assert 'hx-get="/smallstack/dashboards/r/rising/digest/"' in html  # lazy unless sorted by it
    # "Rising" lists this week first: 1 vs 4 is a fall. Most fallen first; nothing to compare goes last.
    assert order("ordering=movement") == ["Rising", "Steady", "Falling", "Single"]
    assert order("ordering=-movement") == ["Falling", "Steady", "Rising", "Single"]
    sorted_html = client.get("/smallstack/dashboards/reports/?ordering=movement").content.decode()
    assert "1 down" in sorted_html and "/r/rising/digest/" not in sorted_html  # worked out inline
    assert "One column: nothing to compare" in sorted_html


def test_the_report_form_lays_rows_out_as_a_sortable_resizable_table(client, staff, metric):
    html = client.get("/smallstack/dashboards/reports/new/").content.decode()
    assert 'data-table-key="dashboards/report-form:metric,target,warn"' in html
    assert html.count('class="col-resizer"') == 3 and html.count('class="plf-sort"') == 3
    assert '<tbody id="rf-rows"></tbody>' in html and 'id="rf-undo"' in html


# -- one goal, week by week (the row's Trends button) ------------------------------------


def test_week_range_names_both_ends_of_the_week():
    from datetime import date

    from apps.dashboards.weeks import week_range

    assert week_range(date(2026, 11, 2)) == "Nov 2–8"
    assert week_range(date(2026, 10, 26)) == "Oct 26 – Nov 1"


def test_one_goal_over_the_weeks(rf, goal_list):
    from apps.dashboards.weeks import GOAL_TREND_WEEKS, goal_weeks_trend

    gid = goal_list.sections[0]["goals"][0]["id"]
    trend = goal_weeks_trend(goal_list, rf, gid, this_week())
    assert trend is not None and len(trend["points"]) == GOAL_TREND_WEEKS and trend["weeks"] == GOAL_TREND_WEEKS
    assert [p["display"] for p in trend["points"][-4:]] == ["2", "6", "4", "1"]
    assert trend["points"][-1]["focus"] and trend["points"][-1]["partial"]
    assert trend["points"][-1]["change"]["dir"] == "down" and trend["points"][0]["change"] is None
    assert trend["cell"]["display"] == "1" and trend["change"]["dir"] == "down"
    # A count is 0 in a week with no rows, so every week is judged.
    assert trend["on_target"] == 2 and trend["scored"] == 13 and trend["label"] == "Requests"
    assert trend["span"].endswith(f", {this_week().year}") and not any(p["saved"] for p in trend["points"])
    # Read at an earlier week, the run is judged there and later weeks aren't shown.
    earlier = goal_weeks_trend(goal_list, rf, gid, this_week() - timedelta(weeks=1))
    assert earlier is not None and earlier["points"][-1]["display"] == "4"
    assert earlier["streak"] == "On target 2 weeks running"
    assert goal_weeks_trend(goal_list, rf, "nope", this_week()) is None


def test_the_row_trends_modal(client, goal_list, staff):
    last = this_week() - timedelta(weeks=1)
    gid = goal_list.sections[0]["goals"][0]["id"]
    take_snapshot(goal_list, last, by=staff)
    grid = client.get(f"/smallstack/dashboards/g/weekly/weeks/?view=grid&week={last:%Y-%m-%d}").content.decode()
    url = f"/smallstack/dashboards/g/weekly/goals/{gid}/trends/?week={last:%Y-%m-%d}"
    assert f'class="gw-trends-btn gw-row-trends" hx-get="{url}"' in grid
    assert 'data-stat-modal="Requests, week by week"' in grid
    modal = client.get(url, HTTP_HX_REQUEST="true")
    html = modal.content.decode()
    assert modal.status_code == 200 and 'class="gwt gt"' in html
    assert 'class="gt-chart"' in html and html.count('class="gt-col') == 13
    assert "Saved</span>" in html and "On target" in html
    assert "<html" not in html  # the modal body only
    page = client.get(url).content.decode()
    assert "<html" in page and "Back to Weekly, week over week" in page
    assert client.get("/smallstack/dashboards/g/weekly/goals/nope/trends/").status_code == 404
