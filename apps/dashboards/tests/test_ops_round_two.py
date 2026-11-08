"""Second ops round: what a person or an agent would get wrong or be misled by in
rates, hand-entered numbers, captures and per-cadence targets."""

from __future__ import annotations

import csv
import importlib
import io
import json
from datetime import timedelta
from unittest import mock

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.migrations.exceptions import IrreversibleError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.dashboards import snapshots
from apps.dashboards.models import Dashboard, GoalList, Metric, Snapshot
from apps.dashboards.snapshots import capture, capture_due, captures_of, current_period, fill, set_tracking
from apps.dashboards.templatetags.dashboard_tags import change_in_words
from apps.dashboards.weeks import take_snapshot
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff():
    return User.objects.create_user("r2-staff", password="x", is_staff=True)


@pytest.fixture
def call(staff):
    _obj, raw = APIToken.create_token(user=staff, name="r2", access_level="staff")
    client = Client(headers={"authorization": f"Bearer {raw}"})

    def _call(tool, **arguments):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        reply = client.post("/mcp", json.dumps(body), content_type="application/json").json()["result"]
        return json.loads(reply["content"][0]["text"])

    return _call


@pytest.fixture
def web(staff):
    client = Client()
    client.force_login(staff)
    return client


@pytest.fixture
def timed():
    return Metric.objects.create(key="r2_total", name="Total", dataset=DS, agg="count", period_field="timestamp")


@pytest.fixture
def undated():
    return Metric.objects.create(key="r2_all", name="All", dataset=DS, agg="count")


def goals(metric, **extra):
    return [{"title": "S", "goals": [{"id": "g1", "metric": metric.key, "target": {"op": ">=", "value": 1}, **extra}]}]


@pytest.fixture
def goal_list(staff, timed):
    return GoalList.objects.create(name="R2", slug="r2", created_by=staff, sections=goals(timed))


class TestPartWayCaptures:
    def _midweek(self, goal_list, staff):
        period = current_period("weekly")
        with mock.patch.object(timezone, "now", return_value=period.start + timedelta(days=2)):
            part = capture(goal_list, period, by=staff)
        assert part.complete is False
        return period

    def test_one_saved_midweek_doesnt_stand_for_the_whole_week(self, goal_list, staff):
        period = self._midweek(goal_list, staff)
        set_tracking(goal_list, ["weekly"])
        with mock.patch.object(timezone, "now", return_value=period.end + timedelta(hours=1)):
            assert capture_due() == 1
            assert capture_due() == 0  # and only once
            newest = captures_of(goal_list, period)[0]
        assert newest.complete is True

    def test_filling_in_counts_it_as_missing_too(self, goal_list, staff):
        period = self._midweek(goal_list, staff)
        with mock.patch.object(timezone, "now", return_value=period.end + timedelta(hours=1)):
            assert fill(goal_list, "weekly", 1, by=staff) == 1
            assert fill(goal_list, "weekly", 1, by=staff) == 0
            assert captures_of(goal_list, period)[0].complete is True


class TestSavingAnOldWeek:
    def test_a_number_that_doesnt_depend_on_time_isnt_todays_value_back_then(self, staff, undated):
        goal_list = GoalList.objects.create(name="U", slug="u", created_by=staff, sections=goals(undated))
        monday = timezone.localtime(current_period("weekly").shifted(-5).start).date()
        row = take_snapshot(goal_list, monday, by=staff).rows[0]
        assert row["value"] is None and row["error"] == snapshots.NO_PAST_VALUE
        fill(goal_list, "weekly", 2, by=staff)
        assert Snapshot.objects.filter(cadence="weekly").first().rows[0]["error"] == snapshots.NO_PAST_VALUE

    def test_the_week_just_ended_still_reads_it(self, staff, undated):
        goal_list = GoalList.objects.create(name="U", slug="u", created_by=staff, sections=goals(undated))
        monday = timezone.localtime(current_period("weekly").shifted(-1).start).date()
        assert take_snapshot(goal_list, monday, by=staff).rows[0]["error"] == ""


class TestHistoryPage:
    def test_the_csv_names_its_own_periods(self, web, goal_list, staff):
        fill(goal_list, "monthly", 2, by=staff)
        url = reverse("dashboards_goal_history", kwargs={"slug": goal_list.slug})
        head = next(csv.reader(io.StringIO(web.get(url, {"cadence": "monthly", "format": "csv"}).content.decode())))
        assert not any("Week of" in h for h in head)
        last_month = timezone.localtime(current_period("monthly").shifted(-1).start)
        assert f"{last_month:%B %Y}" in head

    def test_a_value_with_no_target_isnt_no_data_in_the_csv(self, web, goal_list, staff):
        capture(goal_list, current_period("hourly"), by=staff)  # a count has no hourly target
        url = reverse("dashboards_goal_history", kwargs={"slug": goal_list.slug})
        lines = list(csv.reader(io.StringIO(web.get(url, {"cadence": "hourly", "format": "csv"}).content.decode())))
        assert "No target" in lines[1] and "No data" not in lines[1]

    def test_a_number_that_cant_exist_isnt_shown_as_a_fault(self, web, staff, undated):
        goal_list = GoalList.objects.create(name="U", slug="u", created_by=staff, sections=goals(undated))
        fill(goal_list, "hourly", 1, by=staff)
        html = web.get(reverse("dashboards_goal_history", kwargs={"slug": "u"}), {"cadence": "hourly"}).content.decode()
        assert ">n/a<" in html and 'class="gl-error"' not in html

    def test_filling_nothing_says_so(self, web, goal_list, staff):
        fill(goal_list, "weekly", 2, by=staff)
        reply = web.post(
            reverse("dashboards_goal_capture", kwargs={"slug": goal_list.slug}),
            {"cadence": "weekly", "fill": "2"},
            follow=True,
        )
        assert "already have captures" in reply.content.decode()


class TestAtRiskLine:
    @pytest.mark.parametrize(
        "target, warn",
        [
            ({"op": "<", "value": 1}, {"op": ">", "value": 0.5}),  # the other way
            ({"op": ">=", "value": 90}, {"op": "<", "value": 85}),  # the other way
            ({"op": "<", "value": 1}, {"op": "<", "value": 0.5}),  # harder than the target
            ({"op": ">=", "value": 90}, {"op": ">=", "value": 95}),  # harder than the target
        ],
    )
    def test_one_that_scores_bad_above_good_is_refused(self, staff, timed, target, warn):
        goal_list = GoalList(
            name="W",
            slug="w",
            created_by=staff,
            sections=[{"title": "S", "goals": [{"metric": timed.key, "target": target, "warn": warn}]}],
        )
        with pytest.raises(ValidationError, match="easier target"):
            goal_list.full_clean()

    @pytest.mark.parametrize(
        "target, warn",
        [
            ({"op": "<", "value": 1}, {"op": "<", "value": 2}),
            ({"op": ">=", "value": 90}, {"op": ">=", "value": 85}),
            ({"op": "<=", "value": 1}, {"op": "<", "value": 1}),
            ({"op": "between", "value": [1, 2]}, {"op": ">", "value": 0}),
        ],
    )
    def test_a_sensible_one_is_kept(self, staff, timed, target, warn):
        GoalList(
            name="W",
            slug="w",
            created_by=staff,
            sections=[{"title": "S", "goals": [{"metric": timed.key, "target": target, "warn": warn}]}],
        ).full_clean()


class TestTools:
    def test_add_goal_keeps_targets(self, call, goal_list, timed):
        hourly = {"hourly": {"target": {"op": ">=", "value": 5}}}
        rule = {"op": ">", "value": 1}
        got = call("goal_list_add_goal", goal_list="r2", metric=timed.key, target=rule, targets=hourly)
        assert got["goal"]["targets"] == hourly
        assert GoalList.objects.get(slug="r2").goals()[-1]["targets"] == hourly

    def test_add_goal_refuses_bad_targets(self, call, goal_list, timed):
        got = call(
            "goal_list_add_goal",
            goal_list="r2",
            metric=timed.key,
            target={"op": ">", "value": 1},
            targets={"hourly": {"op": ">=", "value": 5}},
        )
        assert "error" in got

    def test_no_python_reprs_in_a_goal_list(self, call, goal_list):
        got = call("get_goal_list", slug="r2")
        assert "snapshots" not in got and "trackers" not in got
        assert "object at 0x" not in json.dumps(got)

    def test_fill_zero_is_refused_not_a_capture_of_now(self, call, goal_list):
        got = call("goal_list_capture", goal_list="r2", cadence="weekly", fill=0)
        assert "1 or more" in got["error"]
        assert not Snapshot.objects.exists()

    def test_deleting_a_value_of_a_dataset_metric_is_refused(self, call, timed):
        got = call("metric_delete_value", key=timed.key, date="2026-01-01")
        assert "isn't entered by hand" in got["error"]

    def test_a_rate_can_be_previewed_without_a_dataset(self, call, timed):
        other = Metric.objects.create(key="r2_other", name="O", dataset=DS, agg="count", period_field="timestamp")
        got = call("metric_preview", source="rate", numerator=other.key, denominator=timed.key)
        assert "unknown argument" not in json.dumps(got) and "required" not in json.dumps(got)


class TestCards:
    @pytest.fixture
    def rate(self, timed):
        other = Metric.objects.create(key="r2_bad", name="Bad", dataset=DS, agg="count", period_field="timestamp")
        return Metric.objects.create(
            key="r2_rate", name="Rate", source="rate", numerator=other.key, denominator=timed.key, format="percent"
        )

    @pytest.fixture
    def board(self, call):
        call("create_dashboard", name="R2 board", slug="r2-board", layout=[])
        return "r2-board"

    def test_a_trend_chart_takes_a_rate_or_a_hand_entered_metric(self, call, board, rate):
        manual = Metric.objects.create(key="r2_manual", name="By hand", source="manual")
        for metric in (rate, manual):
            got = call("dashboard_add_card", dashboard=board, type="trend", metric=metric.key)
            assert "error" not in got, got
        assert "error" not in call("dashboard_snapshot", dashboard=board)

    @pytest.mark.parametrize("card", ["pie", "ranked", "metric_group"])
    def test_a_grouped_card_still_says_why_not(self, call, board, rate, card):
        got = call("dashboard_add_card", dashboard=board, type=card, metric=rate.key, options={"dimension": "path"})
        assert "split it into groups" in json.dumps(got)

    def test_a_rate_that_doesnt_change_over_time_has_no_trend(self, call, board, undated):
        other = Metric.objects.create(key="r2_all2", name="All 2", dataset=DS, agg="count")
        parts = {"numerator": other.key, "denominator": undated.key}
        flat = Metric.objects.create(key="r2_flat", name="Flat", source="rate", **parts)
        got = call("dashboard_add_card", dashboard=board, type="trend", metric=flat.key)
        assert "needs a period field" in json.dumps(got)  # main words it as the trend refusal does

    def test_an_option_the_card_doesnt_read_is_refused(self, call, board, timed):
        got = call("dashboard_add_card", dashboard=board, type="metric", metric=timed.key, options={"period": "pmtd"})
        assert "doesn't read this" in json.dumps(got) and "use_period" in json.dumps(got)
        assert not Dashboard.objects.get(slug=board).layout

    def test_a_card_keeps_its_styling(self, call, board, timed):
        options = {"style": {"size": "l"}, "thresholds": [{"op": ">=", "value": 1, "state": "danger"}]}
        got = call("dashboard_add_card", dashboard=board, type="metric", metric=timed.key, options=options)
        assert "error" not in got


class TestHandEnteredTrend:
    def test_its_points_are_numbers_so_a_chart_can_draw_them(self, call, staff, web):
        Metric.objects.create(key="r2_csat", name="CSAT", source="manual")
        day = timezone.localdate() - timedelta(days=1)
        assert "error" not in call("metric_record_value", key="r2_csat", date=day.isoformat(), value=88)
        got = call("metric_trend", key="r2_csat", period="last_7", grain="day")
        assert 88.0 in [p["value"] for p in got["points"]]
        call("create_dashboard", name="T", slug="r2-t", layout=[])
        call("dashboard_add_card", dashboard="r2-t", type="trend", metric="r2_csat")
        html = call("card_preview", type="trend", metric="r2_csat", period="last_7", options={"grain": "day"})
        assert "88" in json.dumps(html)


class TestRejudging:
    def test_fill_with_replace_judges_saved_periods_again(self, call, goal_list, staff):
        assert call("goal_list_capture", goal_list="r2", cadence="weekly", fill=2)["captured"] == 2
        assert call("goal_list_capture", goal_list="r2", cadence="weekly", fill=2)["captured"] == 0
        assert call("goal_list_capture", goal_list="r2", cadence="weekly", fill=2, replace=True)["captured"] == 2
        assert Snapshot.objects.filter(cadence="weekly").count() == 4  # earlier captures stay


class TestReversingTheMigration:
    def test_it_wont_silently_lose_captures(self, goal_list, staff):
        module = importlib.import_module("apps.dashboards.migrations.0010_snapshot_engine")
        module.refuse_to_lose_captures(apps, None)  # nothing to lose: fine
        capture(goal_list, current_period("weekly"), by=staff)
        with pytest.raises(IrreversibleError, match="1 captures"):
            module.refuse_to_lose_captures(apps, None)


class TestPrint:
    @pytest.mark.parametrize(
        "change, words",
        [
            ({"dir": "up", "text": "20% vs the week before"}, "Up 20% vs the week before"),
            ({"dir": "down", "text": "7% vs the week before"}, "Down 7% vs the week before"),
            ({"dir": "up", "text": "Up from 0 in the week before"}, "Up from 0 in the week before"),
            ({"dir": "flat", "text": "No change vs the week before"}, "No change vs the week before"),
            (None, ""),
        ],
    )
    def test_a_change_says_which_way(self, change, words):
        assert change_in_words(change) == words
