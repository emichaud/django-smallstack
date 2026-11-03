"""Hand-entered metrics and rates: one number, whichever surface reads it."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.dashboards.entries import delete_entry, parse_entry, record_entry
from apps.dashboards.metrics import drill_rows, evaluate, request_for
from apps.dashboards.models import GoalList, Metric, MetricEntry, metric_usage
from apps.dashboards.trends import metric_trend
from apps.dashboards.weeks import _masked, take_snapshot, week_of, weekly_values

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def staff():
    return User.objects.create_user("ms-staff", password="x", is_staff=True)


@pytest.fixture
def member():
    return User.objects.create_user("ms-member", password="x")


def manual(key="csat", agg="latest", owner=None, **extra):
    m = Metric(key=key, name=key.title(), source="manual", agg=agg, owner=owner, **extra)
    m.save()
    return m


def rate(top, bottom, key="the_rate", fmt="percent", owner=None):
    m = Metric(
        key=key, name="The rate", source="rate", numerator=top.key, denominator=bottom.key, format=fmt, owner=owner
    )
    m.save()
    return m


def monday(weeks_ago):
    return week_of(timezone.localdate()) - timedelta(weeks=weeks_ago)


def week_page_snapshot(g, week):
    from apps.dashboards.weeks import weekly_captures

    return weekly_captures(g, [week])[week]


def goal_list(*metrics, **extra):
    g = GoalList(
        name="Ops",
        slug="ops",
        sections=[
            {
                "title": "Numbers",
                "goals": [
                    {"id": f"g{i}", "metric": m.key, "target": {"op": ">=", "value": 50}} for i, m in enumerate(metrics)
                ],
            }
        ],
        **extra,
    )
    g.save()
    return g


class TestManual:
    def test_it_reads_as_an_ordinary_metric_fixed_to_its_own_entries(self, staff):
        m, other = manual(), manual(key="other")
        assert m.filter_tree == {"field": "metric", "op": "=", "value": m.pk}
        assert (m.dataset, m.measure, m.period_field) == ("metric_entries", "value", "date")
        record_entry(other, date(2026, 1, 5), Decimal(999), by=staff)
        assert evaluate(m, request_for(staff)).value is None  # another metric's entries never count

    @pytest.mark.parametrize("agg, expected", [("latest", 30), ("sum", 60), ("avg", 20), ("min", 10), ("max", 30)])
    def test_entries_roll_up_by_its_aggregation(self, staff, agg, expected):
        m = manual(agg=agg)
        for offset, value in ((0, 10), (1, 20), (2, 30)):
            record_entry(m, date(2026, 1, 5) + timedelta(days=offset), Decimal(value), by=staff)
        assert float(evaluate(m, request_for(staff)).value) == expected

    def test_latest_goes_by_the_date_not_the_order_typed(self, staff):
        m = manual()
        record_entry(m, date(2026, 1, 12), Decimal(5), by=staff)
        record_entry(m, date(2026, 1, 5), Decimal(9), by=staff)  # a late backfill
        assert float(evaluate(m, request_for(staff)).value) == 5

    @pytest.mark.parametrize("agg", ["sum", "latest", "avg"])
    def test_nothing_entered_is_unknown_never_zero(self, staff, agg):
        result = evaluate(manual(agg=agg), request_for(staff))
        assert result.value is None and result.display == "—" and result.ok

    def test_the_same_date_replaces_its_value(self, staff):
        m = manual()
        record_entry(m, date(2026, 1, 5), Decimal(1), by=staff)
        record_entry(m, date(2026, 1, 5), Decimal(2), by=staff)
        assert MetricEntry.objects.get(metric=m).value == 2

    def test_a_period_narrows_entries(self, staff):
        m = manual(agg="sum")
        today = timezone.localdate()
        record_entry(m, today, Decimal(5), by=staff)
        record_entry(m, today - timedelta(days=400), Decimal(100), by=staff)
        assert float(evaluate(m, request_for(staff), period="last_30").value) == 5
        assert float(evaluate(m, request_for(staff)).value) == 105

    @pytest.mark.parametrize(
        "raw_date, raw_value, field",
        [
            ("nope", "1", "date"),
            ("2026-01-05", "abc", "value"),
            ("2026-01-05", "", "value"),
            ("2026-01-05", "NaN", "value"),
            ("2026-01-05", "1e30", "value"),
            ("2999-01-01", "1", "date"),
        ],
    )
    def test_bad_input_is_refused_never_read_as_zero(self, raw_date, raw_value, field):
        assert field in parse_entry(raw_date, raw_value)[2]

    def test_pasted_numbers_are_read(self):
        assert parse_entry("2026-01-05", "1,234.5%")[1] == Decimal("1234.5")

    def test_weeks_and_trends_leave_an_empty_week_blank(self, staff):
        m = manual(agg="sum")
        record_entry(m, monday(1) + timedelta(days=2), Decimal(7), by=staff)
        values = weekly_values(m, request_for(staff), monday(2), 2)["values"]
        assert values[monday(2)] is None and float(values[monday(1)]) == 7
        points = metric_trend(m, request_for(staff), "last_30", "week")["points"]
        assert {p["value"] for p in points} - {None} == {7}

    def test_the_rows_behind_it_are_its_entries_newest_first(self, staff):
        m = manual()
        record_entry(m, date(2026, 1, 5), Decimal(1), by=staff)
        record_entry(m, date(2026, 1, 12), Decimal(2), by=staff)
        drill = drill_rows(m, request_for(staff))
        assert drill["total"] == 2 and drill["rows"][0]["cells"][0].startswith("2026-01-12")

    def test_a_personal_metrics_entries_stay_with_its_owner(self, staff, member):
        theirs = manual(key="theirs", owner=member)
        record_entry(theirs, date(2026, 1, 5), Decimal(5), by=member)
        other = User.objects.create_user("ms-other", password="x")
        assert evaluate(theirs, request_for(other)).value is None
        assert float(evaluate(theirs, request_for(member)).value) == 5

    def test_a_shared_one_shows_to_non_staff(self, staff, member):
        m = manual()
        record_entry(m, date(2026, 1, 5), Decimal(5), by=staff)
        assert float(evaluate(m, request_for(member)).value) == 5

    def test_latest_is_only_for_hand_entered_metrics(self):
        with pytest.raises(ValidationError) as err:
            Metric(key="x", name="X", dataset="smallstack_requests", agg="latest").save()
        assert "agg" in err.value.message_dict

    def test_recording_on_a_dataset_metric_is_refused(self, staff):
        m = Metric(key="d", name="D", dataset="smallstack_requests")
        m.save()
        with pytest.raises(ValueError):
            record_entry(m, date(2026, 1, 5), Decimal(1), by=staff)


class TestRate:
    def test_it_divides_for_the_same_period(self, staff):
        top, bottom = manual(key="top", agg="sum"), manual(key="bottom", agg="sum")
        today = timezone.localdate()
        record_entry(top, today, Decimal(5), by=staff)
        record_entry(bottom, today, Decimal(50), by=staff)
        record_entry(top, today - timedelta(days=400), Decimal(100), by=staff)
        record_entry(bottom, today - timedelta(days=400), Decimal(100), by=staff)
        r = rate(top, bottom)
        assert evaluate(r, request_for(staff), period="last_30").display == "10.0%"
        assert float(evaluate(r, request_for(staff)).value) == pytest.approx(105 / 150 * 100, abs=0.01)

    def test_only_percent_multiplies_by_100(self, staff):
        top, bottom = manual(key="top", agg="sum"), manual(key="bottom", agg="sum")
        record_entry(top, date(2026, 1, 5), Decimal(1), by=staff)
        record_entry(bottom, date(2026, 1, 5), Decimal(4), by=staff)
        assert float(evaluate(rate(top, bottom, fmt="decimal"), request_for(staff)).value) == 0.25

    def test_a_zero_or_missing_bottom_has_no_value(self, staff):
        top, bottom = manual(key="top", agg="sum"), manual(key="bottom", agg="sum")
        record_entry(top, date(2026, 1, 5), Decimal(1), by=staff)
        r = rate(top, bottom)
        assert evaluate(r, request_for(staff)).value is None
        record_entry(bottom, date(2026, 1, 5), Decimal(0), by=staff)
        result = evaluate(r, request_for(staff))
        assert result.value is None and result.ok

    def test_weeks_divide_each_weeks_own_numbers(self, staff):
        top, bottom = manual(key="top", agg="sum"), manual(key="bottom", agg="sum")
        record_entry(top, monday(2), Decimal(1), by=staff)
        record_entry(bottom, monday(2), Decimal(10), by=staff)
        record_entry(top, monday(1), Decimal(5), by=staff)
        record_entry(bottom, monday(1), Decimal(10), by=staff)
        values = weekly_values(rate(top, bottom), request_for(staff), monday(2), 2)["values"]
        assert (values[monday(2)], values[monday(1)]) == (10, 50)

    def test_trend_divides_each_bucket(self, staff):
        top, bottom = manual(key="top", agg="sum"), manual(key="bottom", agg="sum")
        record_entry(top, monday(1), Decimal(1), by=staff)
        record_entry(bottom, monday(1), Decimal(4), by=staff)
        series = metric_trend(rate(top, bottom), request_for(staff), "last_30", "week")
        assert series["ok"] and 25 in {p["value"] for p in series["points"]}

    @pytest.mark.parametrize(
        "numerator, denominator, field",
        [
            ("", "b", "numerator"),
            ("a", "", "denominator"),
            ("nope", "b", "numerator"),
            ("a", "a", "denominator"),
            ("a", "r", "denominator"),
        ],
    )
    def test_bad_parts_are_refused(self, numerator, denominator, field):
        a, b = manual(key="a"), manual(key="b")
        rate(a, b, key="r")
        with pytest.raises(ValidationError) as err:
            Metric(key="new", name="New", source="rate", numerator=numerator, denominator=denominator).save()
        assert field in err.value.message_dict

    def test_a_shared_rate_cant_use_a_personal_metric(self, member):
        mine, shared = manual(key="mine", owner=member), manual(key="shared")
        with pytest.raises(ValidationError):
            rate(mine, shared)

    def test_parts_that_dont_share_a_period_are_refused(self):
        timeless = Metric(key="timeless", name="T", dataset="smallstack_requests")
        timeless.save()
        with pytest.raises(ValidationError) as err:
            rate(manual(key="timed"), timeless)
        assert "denominator" in err.value.message_dict

    def test_parts_that_later_stop_matching_give_an_error_not_a_wrong_number(self, staff):
        top = Metric(key="top", name="T", dataset="smallstack_requests", period_field="timestamp")
        bottom = Metric(key="bottom", name="B", dataset="smallstack_requests", period_field="timestamp")
        top.save()
        bottom.save()
        r = rate(top, bottom)
        bottom.period_field = ""
        bottom.save()
        result = evaluate(r, request_for(staff), period="last_30")
        assert result.value is None and "can't be compared" in result.error
        assert weekly_values(r, request_for(staff), monday(1), 1)["values"] == {}

    def test_a_deleted_part_is_an_error_not_a_number(self, staff):
        top, bottom = manual(key="top"), manual(key="bottom")
        r = rate(top, bottom)
        bottom.delete()
        result = evaluate(Metric.objects.get(pk=r.pk), request_for(staff))
        assert result.value is None and "no longer exists" in result.error

    def test_it_takes_both_parts_to_read_it(self, staff, member):
        requests = Metric(key="req", name="R", dataset="smallstack_requests", period_field="timestamp")
        requests.save()
        other = Metric(key="req2", name="R2", dataset="smallstack_requests", period_field="timestamp")
        other.save()
        r = rate(requests, other)
        assert evaluate(r, request_for(member)).restricted is True  # staff-only data
        assert evaluate(r, request_for(staff)).restricted is False

    def test_a_personal_part_someone_else_cant_open_restricts_it(self, member):
        other = User.objects.create_user("ms-other", password="x")
        r = rate(manual(key="a", owner=member), manual(key="b", owner=member), owner=member)
        r_for_other = Metric.objects.get(pk=r.pk)
        assert evaluate(r_for_other, request_for(other)).restricted is True

    def test_it_has_no_rows_and_says_so(self, staff):
        r = rate(manual(key="a"), manual(key="b"))
        with pytest.raises(ValueError, match="no rows of its own"):
            drill_rows(r, request_for(staff))

    def test_usage_lists_the_rates_built_on_a_metric(self, staff):
        a, b = manual(key="a"), manual(key="b")
        r = rate(a, b)
        assert metric_usage(b, staff)["rates"] == [r]


class TestSavedWeeks:
    @staticmethod
    def newest(g, week):
        return week_page_snapshot(g, week)

    def test_a_value_entered_after_the_snapshot_adds_a_capture(self, staff):
        """The schedule saves last week before anyone has typed its numbers."""
        m = manual()
        g = goal_list(m, created_by=staff)
        week = monday(1)
        first = take_snapshot(g, week)
        assert first.rows[0]["value"] is None and first.summary["pass"] == 0

        record_entry(m, week + timedelta(days=1), Decimal(80), by=staff)
        newest = self.newest(g, week)
        assert newest.pk != first.pk and newest.reason == "A value changed" and newest.taken_by == staff
        assert newest.rows[0]["value"] == 80 and newest.rows[0]["status"] == "pass" and newest.summary["pass"] == 1
        first.refresh_from_db()
        assert first.rows[0]["value"] is None  # the earlier capture is untouched

        delete_entry(m, week + timedelta(days=1))
        assert self.newest(g, week).rows[0]["value"] is None

    def test_it_keeps_the_target_the_week_was_saved_with(self, staff):
        m = manual()
        g = goal_list(m, created_by=staff)
        week = monday(1)
        take_snapshot(g, week)
        g.sections[0]["goals"][0]["target"] = {"op": ">=", "value": 90}
        g.save()
        record_entry(m, week, Decimal(80), by=staff)
        row = self.newest(g, week).rows[0]
        assert row["target"] == {"op": ">=", "value": 50} and row["status"] == "pass"

    def test_other_weeks_are_left_alone(self, staff):
        m = manual()
        g = goal_list(m, created_by=staff)
        take_snapshot(g, monday(2))
        record_entry(m, monday(1), Decimal(80), by=staff)
        assert g.snapshots.count() == 1 and self.newest(g, monday(2)).rows[0]["value"] is None

    def test_a_rate_on_the_metric_follows(self, staff):
        top, bottom = manual(key="top", agg="sum"), manual(key="bottom", agg="sum")
        r = rate(top, bottom)
        g = goal_list(r, created_by=staff)
        week = monday(1)
        take_snapshot(g, week)
        record_entry(bottom, week, Decimal(10), by=staff)
        record_entry(top, week, Decimal(6), by=staff)
        assert self.newest(g, week).rows[0]["value"] == 60

    def test_a_saved_rate_over_staff_data_stays_hidden_from_non_staff(self, staff, member):
        """A rate has no dataset of its own, so masking on row["dataset"] alone would show it."""
        requests = Metric(key="req", name="R", dataset="smallstack_requests", period_field="timestamp")
        requests.save()
        other = Metric(key="req2", name="R2", dataset="smallstack_requests", period_field="timestamp")
        other.save()
        g = goal_list(rate(requests, other), created_by=staff)
        snapshot = take_snapshot(g, monday(1))
        assert snapshot.rows[0]["datasets"] == ["smallstack_requests"]
        assert _masked(snapshot.rows, member)[0]["restricted"] is True
        assert not _masked(snapshot.rows, staff)[0].get("restricted")


class TestPages:
    def test_only_an_editor_can_enter_values(self, client, staff, member):
        m = manual()
        url = reverse("dashboards_metric_entry_save", kwargs={"key": m.key})
        client.force_login(member)
        assert client.post(url, {"date": "2026-01-05", "value": "5"}).status_code == 403
        assert not MetricEntry.objects.exists()
        page = client.get(m.get_absolute_url()).content.decode()
        assert 'name="value"' not in page
        client.force_login(staff)
        assert client.post(url, {"date": "2026-01-05", "value": "5", "note": "survey"}).status_code == 302
        entry = MetricEntry.objects.get()
        assert (entry.value, entry.note, entry.entered_by) == (5, "survey", staff)

    def test_a_bad_value_saves_nothing(self, client, staff):
        m = manual()
        client.force_login(staff)
        client.post(
            reverse("dashboards_metric_entry_save", kwargs={"key": m.key}), {"date": "2026-01-05", "value": "x"}
        )
        assert not MetricEntry.objects.exists()

    def test_entering_needs_a_post(self, client, staff):
        m = manual()
        client.force_login(staff)
        assert client.get(reverse("dashboards_metric_entry_save", kwargs={"key": m.key})).status_code == 405

    def test_remove_a_value(self, client, staff):
        m = manual()
        record_entry(m, date(2026, 1, 5), Decimal(5), by=staff)
        client.force_login(staff)
        url = reverse("dashboards_metric_entry_delete", kwargs={"key": m.key, "day": "2026-01-05"})
        assert client.post(url).status_code == 302
        assert not MetricEntry.objects.exists()
        assert client.post(url).status_code == 404

    def test_edit_fills_the_form(self, client, staff):
        m = manual()
        record_entry(m, date(2026, 1, 5), Decimal("5.5"), "survey", by=staff)
        client.force_login(staff)
        page = client.get(m.get_absolute_url() + "?edit=2026-01-05").content.decode()
        assert 'value="2026-01-05"' in page and 'value="5.5"' in page and 'value="survey"' in page

    def test_a_rate_page_shows_its_parts(self, client, staff):
        a, b = manual(key="aa"), manual(key="bb")
        r = rate(a, b)
        client.force_login(staff)
        response = client.get(r.get_absolute_url())
        page = response.content.decode()
        assert response.status_code == 200 and "What it's made of" in page and a.get_absolute_url() in page

    def test_the_rows_modal_explains_a_rate(self, client, staff):
        r = rate(manual(key="aa"), manual(key="bb"))
        client.force_login(staff)
        response = client.get(reverse("dashboards_metric_rows", kwargs={"key": r.key}))
        assert response.status_code == 200 and "no rows of its own" in response.content.decode()

    def test_the_builder_makes_each_source(self, client, staff):
        client.force_login(staff)
        url = reverse("dashboards/metrics-create")
        base = {"format": "number", "visibility": "shared", "filter_tree": "{}", "thresholds": "[]"}
        response = client.post(url, {**base, "name": "CSAT", "source": "manual", "agg": "latest"})
        assert response.status_code == 302, response.context["form"].errors
        client.post(url, {**base, "name": "Tickets", "source": "manual", "agg": "sum"})
        response = client.post(
            url,
            {
                **base,
                "name": "Per ticket",
                "source": "rate",
                "numerator": "csat",
                "denominator": "tickets",
                "agg": "count",
            },
        )
        assert response.status_code == 302, response.context["form"].errors
        assert Metric.objects.get(key="csat").is_manual and Metric.objects.get(key="per_ticket").is_rate
        assert client.get(url).status_code == 200
        assert (
            client.get(
                reverse("dashboards/metrics-update", kwargs={"pk": Metric.objects.get(key="per_ticket").pk})
            ).status_code
            == 200
        )

    def test_a_dataset_metric_still_needs_a_dataset(self, client, staff):
        client.force_login(staff)
        response = client.post(
            reverse("dashboards/metrics-create"),
            {"name": "X", "format": "number", "agg": "count", "visibility": "shared"},
        )
        assert response.status_code == 200 and "dataset" in response.context["form"].errors

    def test_a_form_cant_build_on_the_entries_dataset(self, client, staff):
        client.force_login(staff)
        response = client.post(
            reverse("dashboards/metrics-create"),
            {
                "name": "X",
                "source": "dataset",
                "dataset": "metric_entries",
                "format": "number",
                "agg": "count",
                "visibility": "shared",
            },
        )
        assert "dataset" in response.context["form"].errors


class TestApi:
    def test_rest_round_trip(self, client, staff):
        m = manual()
        client.force_login(staff)
        url = reverse("dashboards_api_metric_entries", kwargs={"key": m.key})
        assert client.get(url).json()["entries"] == []
        body = '{"date": "2026-01-05", "value": 12.5, "note": "api"}'
        assert client.post(url, data=body, content_type="application/json").json()["value"] == 12.5
        assert client.get(url).json()["entries"] == [{"date": "2026-01-05", "value": 12.5, "note": "api"}]
        bad = client.post(url, data='{"date": "2026-01-05", "value": "x"}', content_type="application/json")
        assert bad.status_code == 400 and "value" in bad.json()["errors"]

    def test_a_session_write_needs_the_csrf_header(self, staff):
        from django.test import Client

        m = manual()
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(staff)
        url = reverse("dashboards_api_metric_entries", kwargs={"key": m.key})
        response = strict.post(url, data='{"date": "2026-01-05", "value": 1}', content_type="application/json")
        assert response.status_code == 403 and not MetricEntry.objects.exists()

    def test_mcp_tools_record_and_delete(self, staff, member):
        from apps.dashboards import mcp_tools

        m = manual()
        from unittest import mock

        with mock.patch.object(mcp_tools, "_user", return_value=member):
            assert "can't edit" in mcp_tools._record_value({"key": m.key, "date": "2026-01-05", "value": 1})["error"]
        with mock.patch.object(mcp_tools, "_user", return_value=staff):
            assert mcp_tools._record_value({"key": m.key, "date": "2026-01-05", "value": 3})["value"] == 3
            assert "error" in mcp_tools._record_value({"key": m.key, "date": "nope", "value": 3})
            assert mcp_tools._delete_value({"key": m.key, "date": "2026-01-05"})["deleted"] is True
            d = Metric(key="d", name="D", dataset="smallstack_requests")
            d.save()
            assert (
                "isn't entered by hand"
                in mcp_tools._record_value({"key": "d", "date": "2026-01-05", "value": 3})["error"]
            )

    def test_preview_covers_each_source(self, staff):
        from apps.dashboards.previews import preview_metric

        a, b = manual(key="a"), manual(key="b")
        ok = preview_metric(staff, {"source": "rate", "numerator": a.key, "denominator": b.key, "format": "percent"})
        assert ok["problems"] == []
        bad = preview_metric(staff, {"source": "rate", "numerator": a.key, "denominator": a.key})
        assert bad["problems"]
        assert preview_metric(staff, {"source": "manual"})["result"]["value"] is None
        assert preview_metric(staff, {"source": "bogus"})["ok"] is False


class TestEverySurface:
    """Sources are new to code written for dataset metrics, so walk what reads them."""

    @pytest.fixture
    def metrics(self, staff):
        m = manual(key="hand", agg="sum")
        other = manual(key="other", agg="sum")
        for w in (1, 2):
            record_entry(m, monday(w), Decimal(5), by=staff)
            record_entry(other, monday(w), Decimal(20), by=staff)
        return {"manual": m, "rate": rate(m, other)}

    @pytest.mark.parametrize("source", ["manual", "rate"])
    def test_every_card_type_draws_or_refuses_cleanly(self, staff, metrics, source):
        from apps.dashboards.components import describe_types
        from apps.dashboards.previews import preview_card

        drawn = 0
        for card in describe_types():
            if not card.get("uses_metric", True):
                continue
            payload = {"type": card["type"], "metric": metrics[source].key, "options": {}, "visibility": "shared"}
            out = preview_card(staff, payload, request_for(staff))
            assert "html" in out or out.get("problems"), card["type"]
            assert "Traceback" not in out.get("html", ""), card["type"]
            drawn += 1
        assert drawn

    @pytest.mark.parametrize("source", ["manual", "rate"])
    def test_pages_that_read_a_metric_open(self, client, staff, metrics, source):
        m = metrics[source]
        g = goal_list(m, created_by=staff)
        take_snapshot(g, monday(1))
        client.force_login(staff)
        week = monday(1).isoformat()
        for url in (
            m.get_absolute_url(),
            m.get_absolute_url() + "?period=last_30",
            reverse("dashboards/metrics-delete", kwargs={"pk": m.pk}),
            reverse("dashboards/metrics-update", kwargs={"pk": m.pk}),
            reverse("dashboards/metrics-list"),
            reverse("goals_index"),
            g.get_absolute_url(),
            reverse("dashboards_goal_weeks", kwargs={"slug": g.slug}),
            reverse("dashboards_goal_weeks", kwargs={"slug": g.slug}) + "?view=grid",
            reverse("dashboards_goal_week_trends", kwargs={"slug": g.slug, "week": week}),
            reverse("dashboards_metric_rows", kwargs={"key": m.key}),
            reverse("dashboards_api_metric_value", kwargs={"key": m.key}),
            reverse("dashboards_api_metric_trend", kwargs={"key": m.key}),
            reverse("dashboards_api_goal_values", kwargs={"slug": g.slug}),
        ):
            assert client.get(url).status_code == 200, url

    def test_a_deleted_manual_metric_takes_its_values(self, client, staff, metrics):
        client.force_login(staff)
        client.post(reverse("dashboards/metrics-delete", kwargs={"pk": metrics["manual"].pk}))
        assert not Metric.objects.filter(key="hand").exists()
        assert not MetricEntry.objects.filter(metric__key="hand").exists()
