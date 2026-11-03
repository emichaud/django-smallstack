"""The snapshot engine: periods, captures, tracking and the hourly job."""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.dashboards.entries import record_entry
from apps.dashboards.goals import goal_at, scales_with_time
from apps.dashboards.metrics import request_for
from apps.dashboards.models import GoalList, Metric, Snapshot, SnapshotTracker
from apps.dashboards.snapshots import (
    DAILY,
    HOURLY,
    MONTHLY,
    QUARTERLY,
    WEEKLY,
    capture,
    capture_due,
    captures_of,
    current_period,
    fill,
    history_grid,
    history_payload,
    last_closed,
    parse_period,
    period_at,
    prune,
    set_tracking,
    tracked_cadences,
    window_value,
)
from apps.dashboards.tasks import capture_snapshots

pytestmark = pytest.mark.django_db
User = get_user_model()
UTC = ZoneInfo("UTC")


@pytest.fixture
def staff():
    return User.objects.create_user("sn-staff", password="x", is_staff=True)


@pytest.fixture
def csat():
    m = Metric(key="csat", name="CSAT", source="manual", agg="sum")
    m.save()
    return m


def make_list(*metrics, owner=None, created_by=None, slug="ops"):
    g = GoalList(
        name="Ops",
        slug=slug,
        owner=owner,
        created_by=created_by,
        sections=[
            {
                "title": "All",
                "goals": [{"id": m.key, "metric": m.key, "target": {"op": ">=", "value": 50}} for m in metrics],
            }
        ],
    )
    g.save()
    return g


class TestPeriods:
    MOMENT = datetime(2026, 11, 4, 14, 37, tzinfo=UTC)  # a Wednesday

    @pytest.mark.parametrize(
        "cadence, start, end",
        [
            (HOURLY, (2026, 11, 4, 14), (2026, 11, 4, 15)),
            (DAILY, (2026, 11, 4), (2026, 11, 5)),
            (WEEKLY, (2026, 11, 2), (2026, 11, 9)),
            (MONTHLY, (2026, 11, 1), (2026, 12, 1)),
            (QUARTERLY, (2026, 10, 1), (2027, 1, 1)),
        ],
    )
    @override_settings(TIME_ZONE="UTC")
    def test_boundaries(self, cadence, start, end):
        with timezone.override("UTC"):
            period = period_at(cadence, self.MOMENT)
            assert period.start == datetime(*start, tzinfo=UTC) and period.end == datetime(*end, tzinfo=UTC)
            assert period.shifted(1).start == period.end and period.shifted(-1).end == period.start
            assert period.shifted(1).shifted(-1) == period

    def test_they_follow_the_sites_time_zone(self):
        with timezone.override("America/New_York"):
            period = period_at(DAILY, datetime(2026, 11, 4, 2, 0, tzinfo=UTC))  # still Nov 3 in New York
            assert period.label == "Nov 3, 2026"
            assert period.start == datetime(2026, 11, 3, 5, 0, tzinfo=UTC)

    def test_a_day_across_a_clock_change_has_its_real_length(self):
        with timezone.override("America/New_York"):
            day = period_at(DAILY, datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
            assert day.end.astimezone(UTC) - day.start.astimezone(UTC) == timedelta(hours=25)
            assert day.shifted(1).start == day.end

    def test_hours_across_a_clock_change_never_repeat_or_skip(self):
        with timezone.override("America/New_York"):
            hour = period_at(HOURLY, datetime(2026, 11, 1, 4, 0, tzinfo=UTC))
            starts = [hour.shifted(i).start.astimezone(UTC) for i in range(5)]
            assert len({timezone.localtime(s).hour for s in starts}) == 4  # 1 a.m. happens twice
            assert [b - a for a, b in zip(starts, starts[1:])] == [timedelta(hours=1)] * 4

    def test_a_quarter_rolls_over_the_year(self):
        with timezone.override("UTC"):
            q4 = period_at(QUARTERLY, self.MOMENT)
            assert q4.shifted(1).label == "Q1 2027" and q4.shifted(-4).label == "Q4 2025"

    def test_keys_round_trip_and_future_is_refused(self):
        period = last_closed(HOURLY)
        assert parse_period(HOURLY, period.key) == period
        assert "+" not in period.key
        assert parse_period(DAILY, current_period(DAILY).shifted(2).key) is None
        assert parse_period(DAILY, "junk") is None


class TestValues:
    def test_each_cadence_reads_its_own_span(self, staff, csat):
        today = timezone.localdate()
        record_entry(csat, today, Decimal(5), by=staff)
        record_entry(csat, today - timedelta(days=400), Decimal(100), by=staff)
        request = request_for(staff)
        assert window_value(csat, request, current_period(DAILY))["value"] == 5
        assert window_value(csat, request, current_period(QUARTERLY))["value"] == 5

    def test_a_date_only_metric_has_no_hourly_value(self, staff, csat):
        record_entry(csat, timezone.localdate(), Decimal(5), by=staff)
        got = window_value(csat, request_for(staff), current_period(HOURLY))
        assert got["value"] is None and "one hour" in got["error"]

    def test_hourly_narrows_a_datetime_column(self, staff):
        from apps.activity.models import RequestLog

        m = Metric(key="req", name="Requests", dataset="smallstack_requests", period_field="timestamp")
        m.save()
        hour = last_closed(HOURLY)
        inside = RequestLog.objects.create(path="/in", method="GET", status_code=200, response_time_ms=1)
        outside = RequestLog.objects.create(path="/out", method="GET", status_code=200, response_time_ms=1)
        RequestLog.objects.filter(pk=inside.pk).update(timestamp=hour.start + timedelta(minutes=5))
        RequestLog.objects.filter(pk=outside.pk).update(timestamp=hour.start - timedelta(minutes=5))
        assert window_value(m, request_for(staff), hour)["value"] == 1

    def test_a_rate_divides_that_periods_numbers(self, staff):
        top, bottom = (Metric(key=k, name=k, source="manual", agg="sum") for k in ("top", "bottom"))
        top.save()
        bottom.save()
        rate = Metric(key="r", name="R", source="rate", numerator="top", denominator="bottom", format="percent")
        rate.save()
        today = timezone.localdate()
        record_entry(top, today, Decimal(1), by=staff)
        record_entry(bottom, today, Decimal(4), by=staff)
        assert window_value(rate, request_for(staff), current_period(DAILY))["value"] == 25

    def test_a_timeless_number_is_captured_now_but_never_filled_in(self, staff):
        m = Metric(key="now", name="Open", dataset="smallstack_requests")
        m.save()
        request = request_for(staff)
        assert window_value(m, request, last_closed(DAILY))["error"] == ""
        assert "can't be worked out" in window_value(m, request, last_closed(DAILY), past=True)["error"]


class TestCapture:
    def test_a_capture_keeps_values_and_targets_as_they_were(self, staff, csat):
        g = make_list(csat, created_by=staff)
        record_entry(csat, timezone.localdate(), Decimal(80), by=staff)
        snapshot = capture(g, current_period(WEEKLY), by=staff)
        g.sections[0]["goals"][0]["target"] = {"op": ">=", "value": 99}
        g.save()
        assert snapshot.rows[0]["value"] == 80 and snapshot.rows[0]["status"] == "pass"
        assert snapshot.summary["pass"] == 1 and snapshot.complete is False and snapshot.subject == g

    def test_capturing_again_adds_rather_than_replaces(self, staff, csat):
        g = make_list(csat, created_by=staff)
        period = current_period(DAILY)
        first = capture(g, period)
        second = capture(g, period)
        assert [c.pk for c in captures_of(g, period)] == [second.pk, first.pk]

    def test_a_future_period_is_refused(self, staff, csat):
        with pytest.raises(ValueError, match="hasn't started"):
            capture(make_list(csat, created_by=staff), current_period(DAILY).shifted(1))

    def test_an_unregistered_subject_is_refused(self, csat):
        with pytest.raises(ValueError, match="registered subject"):
            capture(csat, current_period(DAILY))

    def test_a_snapshot_stays_hidden_from_who_cant_read_its_data(self, staff):
        m = Metric(key="req", name="R", dataset="smallstack_requests", period_field="timestamp")
        m.save()
        g = make_list(m, created_by=staff)
        capture(g, last_closed(DAILY))
        member = User.objects.create_user("sn-member", password="x")
        cell = history_grid(g, request_for(member), DAILY)["rows"][0]["cells"][1]
        assert cell["restricted"] is True and cell["value"] is None

    def test_deleting_the_list_takes_its_captures_and_trackers(self, staff, csat):
        g = make_list(csat, created_by=staff)
        capture(g, current_period(DAILY))
        g.delete()
        assert not Snapshot.objects.exists() and not SnapshotTracker.objects.exists()

    def test_fill_skips_what_exists_and_respects_the_cap(self, staff, csat):
        g = make_list(csat, created_by=staff)
        capture(g, last_closed(MONTHLY))
        assert fill(g, MONTHLY, 3) == 2
        assert fill(g, MONTHLY, 3) == 0
        assert fill(g, QUARTERLY, 500) == 12


class TestTracking:
    def test_a_new_list_tracks_the_default_and_it_can_be_changed(self, staff, csat):
        g = make_list(csat, created_by=staff)
        assert tracked_cadences(g) == [WEEKLY]
        assert set_tracking(g, [HOURLY, QUARTERLY]) == [HOURLY, QUARTERLY]
        assert set_tracking(g, []) == []

    @override_settings(SMALLSTACK_SNAPSHOT_DEFAULT_CADENCES=[])
    def test_the_default_can_be_nothing(self, staff, csat):
        assert tracked_cadences(make_list(csat, created_by=staff)) == []

    def test_an_unknown_cadence_is_refused(self, staff, csat):
        g = make_list(csat, created_by=staff)
        with pytest.raises(ValueError, match="unknown cadence"):
            set_tracking(g, ["fortnightly"])
        assert tracked_cadences(g) == [WEEKLY]

    def test_turning_one_off_keeps_what_it_captured(self, staff, csat):
        g = make_list(csat, created_by=staff)
        capture(g, last_closed(WEEKLY))
        set_tracking(g, [])
        assert g.snapshots.count() == 1


class TestTheJob:
    def test_it_captures_each_tracked_cadence_once(self, staff, csat):
        g = make_list(csat, created_by=staff)
        set_tracking(g, [HOURLY, DAILY, WEEKLY, MONTHLY, QUARTERLY])
        assert capture_due() == 5
        assert capture_due() == 0
        assert {s.cadence for s in g.snapshots.all()} == {HOURLY, DAILY, WEEKLY, MONTHLY, QUARTERLY}
        assert all(s.complete and s.taken_by is None for s in g.snapshots.all())
        assert g.snapshots.get(cadence=DAILY).period_start == last_closed(DAILY).start

    def test_an_untracked_list_is_left_alone(self, staff, csat):
        g = make_list(csat, created_by=staff)
        set_tracking(g, [])
        assert capture_due() == 0 and not g.snapshots.exists()

    def test_a_list_with_no_goals_or_no_one_to_read_as_is_skipped(self, staff, csat):
        empty = GoalList(name="Empty", slug="empty", created_by=staff, sections=[])
        empty.save()
        assert capture_due() == 0

    def test_one_failure_doesnt_stop_the_rest(self, staff, csat, monkeypatch):
        bad, good = make_list(csat, created_by=staff, slug="bad"), make_list(csat, created_by=staff, slug="good")
        real = capture

        def flaky(subject, period, **kw):
            if subject.slug == "bad":
                raise RuntimeError("boom")
            return real(subject, period, **kw)

        monkeypatch.setattr("apps.dashboards.snapshots.capture", flaky)
        assert capture_due() == 1
        assert good.snapshots.count() == 1 and bad.snapshots.count() == 0

    def test_a_switched_off_feature_captures_nothing(self, staff, csat):
        make_list(csat, created_by=staff)
        with override_settings(SMALLSTACK_DASHBOARDS_ENABLED=False):
            assert capture_snapshots.func() == 0
        assert not Snapshot.objects.exists()

    def test_prune_follows_each_cadences_retention(self, staff, csat):
        g = make_list(csat, created_by=staff)
        old_hour = capture(g, last_closed(HOURLY).shifted(-24 * 100))
        recent = capture(g, last_closed(HOURLY))
        old_quarter = capture(g, last_closed(QUARTERLY).shifted(-40))
        assert prune() == 1
        assert not Snapshot.objects.filter(pk=old_hour.pk).exists()
        assert Snapshot.objects.filter(pk__in=[recent.pk, old_quarter.pk]).count() == 2

    def test_the_command(self, staff, csat):
        make_list(csat, created_by=staff)
        out = io.StringIO()
        call_command("snapshot_goals", "--due", stdout=out)
        assert "Took 1 capture" in out.getvalue()


class TestHistoryGrid:
    def test_only_captures_show_and_a_late_one_wins(self, staff, csat):
        g = make_list(csat, created_by=staff)
        period = current_period(DAILY)
        record_entry(csat, timezone.localdate(), Decimal(1), by=staff)
        capture(g, period)
        record_entry(csat, timezone.localdate(), Decimal(90), by=staff)  # adds another capture
        grid = history_grid(g, request_for(staff), DAILY)
        assert grid["rows"][0]["cells"][0]["value"] == 90
        assert grid["rows"][0]["cells"][1].get("absent")
        assert len(grid["columns"]) == 14 and grid["columns"][0]["state"] == "current"

    def test_a_goal_since_removed_stays_visible(self, staff, csat):
        g = make_list(csat, created_by=staff)
        capture(g, current_period(DAILY))
        g.sections = []
        g.save()
        grid = history_grid(g, request_for(staff), DAILY)
        assert grid["rows"][0]["section"] == "No longer on the list"

    def test_the_payload_is_json_safe(self, staff, csat):
        g = make_list(csat, created_by=staff)
        record_entry(csat, timezone.localdate(), Decimal("1.5"), by=staff)
        capture(g, current_period(MONTHLY))
        payload = history_payload(g, history_grid(g, request_for(staff), MONTHLY))
        assert json.loads(json.dumps(payload))["goals"][0]["periods"][0]["value"] == 1.5


class TestPagesAndApi:
    @pytest.mark.parametrize("cadence", [HOURLY, DAILY, WEEKLY, MONTHLY, QUARTERLY])
    def test_the_page_for_each_cadence(self, client, staff, csat, cadence):
        g = make_list(csat, created_by=staff)
        capture(g, last_closed(cadence))
        client.force_login(staff)
        url = reverse("dashboards_goal_history", kwargs={"slug": g.slug})
        html = client.get(f"{url}?cadence={cadence}").content.decode()
        assert "What's tracked" in html and 'class="gw-grid crud-table"' in html and "Open" in html
        period = last_closed(cadence)
        html = client.get(f"{url}?cadence={cadence}&at={period.key}").content.decode()
        assert period.label in html and "Print this capture" in html
        assert client.get(f"{url}?cadence={cadence}&format=csv").status_code == 200
        grid_order = client.get(f"{url}?cadence={cadence}&order=-w{period.key}")
        assert grid_order.status_code == 200 and grid_order.context["order"] == f"-w{period.key}"

    def test_a_chosen_capture_shows_its_own_values(self, client, staff, csat):
        g = make_list(csat, created_by=staff)
        period = current_period(DAILY)
        record_entry(csat, timezone.localdate(), Decimal(11), by=staff)
        first = capture(g, period)
        record_entry(csat, timezone.localdate(), Decimal(22), by=staff)
        client.force_login(staff)
        url = reverse("dashboards_goal_history", kwargs={"slug": g.slug}) + f"?cadence=daily&at={period.key}"
        assert client.get(url).context["detail_rows"][0]["value"] == 22
        assert client.get(f"{url}&capture={first.pk}").context["detail_rows"][0]["value"] == 11

    def test_a_capture_from_another_list_cant_be_opened_or_printed(self, client, staff, csat):
        g, other = make_list(csat, created_by=staff), make_list(csat, created_by=staff, slug="other")
        foreign = capture(other, current_period(DAILY))
        client.force_login(staff)
        response = client.get(reverse("dashboards_goals_print", kwargs={"slug": g.slug}) + f"?snapshot={foreign.pk}")
        assert response.status_code == 200 and "as captured" not in response.content.decode()

    def test_printing_a_capture(self, client, staff, csat):
        g = make_list(csat, created_by=staff)
        snapshot = capture(g, current_period(DAILY))
        client.force_login(staff)
        html = client.get(
            reverse("dashboards_goals_print", kwargs={"slug": g.slug}) + f"?snapshot={snapshot.pk}"
        ).content.decode()
        assert "as captured" in html

    def test_only_editors_change_tracking_or_capture(self, client, staff, csat):
        g = make_list(csat, created_by=staff)
        member = User.objects.create_user("sn-member", password="x")
        client.force_login(member)
        slug = {"slug": g.slug}
        assert client.get(reverse("dashboards_goal_history", kwargs=slug)).status_code == 200
        assert client.post(reverse("dashboards_goal_tracking", kwargs=slug), {"cadence": "daily"}).status_code == 403
        assert client.post(reverse("dashboards_goal_capture", kwargs=slug), {"cadence": "daily"}).status_code == 403
        assert tracked_cadences(g) == [WEEKLY] and not g.snapshots.exists()

    def test_editors_change_tracking_and_capture(self, client, staff, csat):
        g = make_list(csat, created_by=staff)
        client.force_login(staff)
        slug = {"slug": g.slug}
        client.post(reverse("dashboards_goal_tracking", kwargs=slug), {"cadence": ["hourly", "monthly"]})
        assert tracked_cadences(g) == [HOURLY, MONTHLY]
        client.post(reverse("dashboards_goal_capture", kwargs=slug), {"cadence": "monthly"})
        client.post(reverse("dashboards_goal_capture", kwargs=slug), {"cadence": "monthly", "fill": "2"})
        assert g.snapshots.filter(cadence=MONTHLY).count() == 3
        assert client.post(reverse("dashboards_goal_capture", kwargs=slug), {"cadence": "nope"}).status_code == 404

    def test_rest(self, client, staff, csat):
        g = make_list(csat, created_by=staff)
        client.force_login(staff)
        slug = {"slug": g.slug}
        tracking = reverse("dashboards_api_goal_tracking", kwargs=slug)
        body = json.dumps({"cadences": ["daily"]})
        assert client.post(tracking, body, content_type="application/json").json()["tracked"] == [DAILY]
        assert client.get(tracking).json()["tracked"] == [DAILY]
        assert client.post(tracking, '{"cadences": ["x"]}', content_type="application/json").status_code == 400
        shots = reverse("dashboards_api_goal_snapshots", kwargs=slug)
        assert client.post(shots, '{"cadence": "daily"}', content_type="application/json").json()["ok"]
        assert client.post(shots, '{"cadence": "x"}', content_type="application/json").status_code == 400
        assert client.get(f"{shots}?cadence=daily").json()["periods"][0]["captured"] is True
        assert client.get(f"{shots}?cadence=x").status_code == 400

    def test_a_session_write_needs_the_csrf_header(self, staff, csat):
        from django.test import Client

        g = make_list(csat, created_by=staff)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(staff)
        url = reverse("dashboards_api_goal_tracking", kwargs={"slug": g.slug})
        assert strict.post(url, '{"cadences": []}', content_type="application/json").status_code == 403
        assert tracked_cadences(g) == [WEEKLY]

    def test_mcp(self, staff, csat):
        from unittest import mock

        from apps.dashboards import mcp_tools

        g = make_list(csat, created_by=staff)
        with mock.patch.object(mcp_tools, "_user", return_value=staff):
            assert mcp_tools._goal_list_tracking({"goal_list": g.slug})["tracked"] == [WEEKLY]
            assert mcp_tools._goal_list_tracking({"goal_list": g.slug, "cadences": ["daily"]})["tracked"] == [DAILY]
            assert "error" in mcp_tools._goal_list_tracking({"goal_list": g.slug, "cadences": ["x"]})
            assert mcp_tools._goal_list_capture({"goal_list": g.slug, "cadence": "daily"})["ok"]
            assert "error" in mcp_tools._goal_list_capture({"goal_list": g.slug, "cadence": "x"})
            assert mcp_tools._goal_list_history({"goal_list": g.slug, "cadence": "daily"})["periods"][0]["captured"]
            assert "error" in mcp_tools._goal_list_history({"goal_list": g.slug, "cadence": "x"})
        member = User.objects.create_user("sn-member", password="x")
        with mock.patch.object(mcp_tools, "_user", return_value=member):
            assert "not edit" in mcp_tools._goal_list_tracking({"goal_list": g.slug, "cadences": []})["error"]


@pytest.mark.django_db(transaction=True)
def test_the_migration_carries_saved_weeks_and_keeps_the_monday_save():
    """Old weeks become weekly captures keeping when they were taken; every list keeps a weekly tracker."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    app = "smallstack_dashboards"
    executor = MigrationExecutor(connection)
    executor.migrate([(app, "0009_metric_sources")])
    old = executor.loader.project_state([(app, "0009_metric_sources")]).apps
    goal_list = old.get_model(app, "GoalList").objects.create(name="Old", slug="old", sections=[])
    taken = datetime(2026, 1, 13, 9, 0, tzinfo=UTC)
    saved = old.get_model(app, "GoalSnapshot").objects.create(
        goal_list=goal_list,
        week_start=date(2026, 1, 5),
        rows=[{"id": "a", "value": 1}],
        summary={"pass": 1},
        complete=True,
    )
    old.get_model(app, "GoalSnapshot").objects.filter(pk=saved.pk).update(taken_at=taken)
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes(app))

    moved = Snapshot.objects.get(subject_id=goal_list.pk)
    assert moved.subject == GoalList.objects.get(pk=goal_list.pk)
    assert moved.cadence == WEEKLY and moved.week_start == date(2026, 1, 5) and moved.complete
    assert moved.taken_at == taken and moved.rows == [{"id": "a", "value": 1}]
    assert moved.period_end - moved.period_start == timedelta(weeks=1)
    assert tracked_cadences(moved.subject) == [WEEKLY]


class TestCadenceTargets:
    RULE = {"op": ">=", "value": 10}

    def goal_with(self, metric, **extra):
        maker, _created = User.objects.get_or_create(username="sn-maker", defaults={"is_staff": True})
        g = make_list(metric, created_by=maker, slug="judged")
        g.sections[0]["goals"][0].update(extra)
        g.save()
        return GoalList.objects.get(pk=g.pk)

    def counting(self):
        m = Metric(key="tickets", name="Tickets", source="manual", agg="sum")
        m.save()
        return m

    @pytest.mark.parametrize(
        "agg, period_field, scales",
        [
            ("count", "timestamp", True),
            ("sum", "timestamp", True),
            ("avg", "timestamp", False),
            ("max", "timestamp", False),
            ("count", "", False),
        ],
    )
    def test_what_grows_with_time(self, agg, period_field, scales):
        m = Metric(key="m", name="M", dataset="smallstack_requests", agg=agg, period_field=period_field)
        if agg != "count":
            m.measure = "response_time_ms"
        assert scales_with_time(m) is scales

    def test_a_rate_and_a_latest_reading_dont_grow_with_time(self):
        assert not scales_with_time(Metric(source="rate"))
        assert not scales_with_time(Metric(source="manual", agg="latest", period_field="date"))
        assert scales_with_time(Metric(source="manual", agg="sum", period_field="date", dataset="metric_entries"))

    def test_which_rule_applies(self):
        count = Metric(source="manual", agg="sum", period_field="date", dataset="metric_entries")
        average = Metric(source="manual", agg="avg", period_field="date", dataset="metric_entries")
        goal = {"target": {"op": ">=", "value": 1000}, "targets": {"hourly": {"target": self.RULE, "warn": self.RULE}}}
        assert goal_at(goal, HOURLY, count)["target"] == self.RULE and goal_at(goal, HOURLY, count)["warn"] == self.RULE
        assert goal_at(goal, WEEKLY, count)["target"]["value"] == 1000
        assert goal_at(goal, DAILY, count)["target"] is None
        assert goal_at(goal, DAILY, average)["target"]["value"] == 1000

    def test_a_weekly_override_wins(self):
        goal = {"target": {"op": ">=", "value": 1000}, "targets": {"weekly": {"target": self.RULE}}}
        assert goal_at(goal, WEEKLY, None)["target"] == self.RULE

    def test_validation_keeps_good_rows_and_refuses_bad_ones(self):
        m = self.counting()
        g = self.goal_with(m, targets={"daily": {"target": self.RULE, "warn": {"op": ">=", "value": 5}}})
        assert g.goals()[0]["targets"]["daily"]["warn"]["value"] == 5
        for bad in ({"fortnightly": {"target": self.RULE}}, {"daily": {"warn": self.RULE}}, {"daily": "x"}, "x"):
            g.sections[0]["goals"][0]["targets"] = bad
            with pytest.raises(ValidationError):
                g.save()

    def test_a_count_with_no_target_for_the_cadence_shows_its_value_unjudged(self, staff):
        m = self.counting()
        g = self.goal_with(m)
        record_entry(m, timezone.localdate(), Decimal(3), by=staff)
        row = capture(g, current_period(DAILY)).rows[0]
        assert row["value"] == 3 and row["status"] == "none" and row["target"] is None and row["gap_text"] == ""
        snapshot = capture(g, current_period(DAILY))
        assert snapshot.summary["fail"] == 0 and snapshot.summary["scored"] == 0
        cell = history_grid(g, request_for(staff), DAILY)["rows"][0]["cells"][0]
        assert cell["status_label"] == "No target" and cell["display"] == "3"

    def test_a_missing_value_with_no_target_still_says_no_data(self, staff):
        m = self.counting()
        g = self.goal_with(m)
        capture(g, current_period(DAILY))
        cell = history_grid(g, request_for(staff), DAILY)["rows"][0]["cells"][0]
        assert cell["status_label"] != "No target"

    def test_its_own_target_judges_the_capture(self, staff):
        m = self.counting()
        g = self.goal_with(m, targets={"daily": {"target": self.RULE}})
        record_entry(m, timezone.localdate(), Decimal(30), by=staff)
        row = capture(g, current_period(DAILY)).rows[0]
        assert row["status"] == "pass" and row["target"] == self.RULE and row["target_text"] == "≥ 10"
        assert history_grid(g, request_for(staff), DAILY)["rows"][0]["target_text"] == "≥ 10"
        assert history_grid(g, request_for(staff), MONTHLY)["rows"][0]["target_text"] == ""

    def test_a_late_value_keeps_the_cadence_target_it_was_captured_with(self, staff):
        m = self.counting()
        g = self.goal_with(m, targets={"daily": {"target": self.RULE}})
        period = current_period(DAILY)
        capture(g, period)
        g.sections[0]["goals"][0]["targets"]["daily"]["target"]["value"] = 999
        g.save()
        record_entry(m, timezone.localdate(), Decimal(30), by=staff)
        newest = captures_of(g, period)[0].rows[0]
        assert newest["target"] == self.RULE and newest["status"] == "pass"

    def test_a_late_value_on_an_unjudged_capture_stays_unjudged(self, staff):
        m = self.counting()
        g = self.goal_with(m)
        period = current_period(DAILY)
        capture(g, period)
        record_entry(m, timezone.localdate(), Decimal(30), by=staff)
        newest = captures_of(g, period)[0].rows[0]
        assert newest["value"] == 30 and newest["status"] == "none"

    def test_the_weekly_pages_use_a_weekly_override(self, staff):
        from apps.dashboards.weeks import take_snapshot, this_week, week_grid, week_page

        m = self.counting()
        g = self.goal_with(m, targets={"weekly": {"target": self.RULE}})
        week = this_week()
        record_entry(m, timezone.localdate(), Decimal(30), by=staff)
        request = request_for(staff)
        assert week_page(g, request, week)["rows"][0]["status"] == "pass"
        assert week_grid(g, request, week)["rows"][0]["target_text"] == "≥ 10"
        assert take_snapshot(g, week).rows[0]["target"] == self.RULE

    def test_the_meeting_view_keeps_the_main_target(self, staff):
        from apps.dashboards.goals import evaluate_goals

        m = self.counting()
        g = self.goal_with(m, targets={"weekly": {"target": self.RULE}})
        record_entry(m, timezone.localdate(), Decimal(30), by=staff)
        assert evaluate_goals(g, request_for(staff))["rows"][0]["status"] == "fail"  # main target is >= 50

    def test_pages_and_print_show_it(self, client, staff):
        m = self.counting()
        g = self.goal_with(m)
        record_entry(m, timezone.localdate(), Decimal(3), by=staff)
        snapshot = capture(g, current_period(DAILY))
        client.force_login(staff)
        url = reverse("dashboards_goal_history", kwargs={"slug": g.slug})
        html = client.get(f"{url}?cadence=daily").content.decode()
        assert "No target" in html
        html = client.get(f"{url}?cadence=daily&at={current_period(DAILY).key}").content.decode()
        assert "No target" in html and "No targets for this period" in html
        html = client.get(
            reverse("dashboards_goals_print", kwargs={"slug": g.slug}) + f"?snapshot={snapshot.pk}"
        ).content.decode()
        assert "No target" in html and "was judged for this period" in html

    def test_the_editor_payload_says_what_scales(self, staff):
        from apps.dashboards.forms import goal_editor_data

        self.counting()
        found = {m["key"]: m["scales"] for m in goal_editor_data(staff, None)["metrics"]}
        assert found["tickets"] is True
