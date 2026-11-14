"""A metric can be a median.

Datasets have computed a median in the database since 0.30.1 (``percentile_cont``
on Postgres, a registered aggregate on SQLite); metrics, dataset cards, trends
and goals now offer it too. Response times and deal sizes are skewed, so the
average answers the wrong question: here four requests take 10, 20, 90 and
1000 ms, a median of 55 and an average of 280.

A database with no median (MySQL, MariaDB) offers none: the picker, the forms,
the card check and the agent tools all read :func:`aggs_available`.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.activity.models import RequestLog
from apps.dashboards.components import normalize_layout
from apps.dashboards.goals import evaluate_goals
from apps.dashboards.metrics import aggs_available, all_aggs_available, evaluate, request_for
from apps.dashboards.models import GoalList, Metric
from apps.dashboards.previews import preview_metric
from apps.dashboards.trends import metric_trend

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"
# Only the seeded rows: the request log also records the test client's own requests.
SEEDED = {"field": "path", "op": "in", "value": ["/a", "/b", "/c", "/d"]}


@pytest.fixture
def staff():
    return User.objects.create_user("median-staff", password="x", is_staff=True)


@pytest.fixture
def rows():
    for path, ms in (("/a", 10), ("/b", 20), ("/c", 90), ("/d", 1000)):
        RequestLog.objects.create(path=path, method="GET", status_code=200, response_time_ms=ms)


def _metric(key="md_latency", agg="median", measure="response_time_ms", **kw) -> Metric:
    m = Metric(
        key=key, name="Response time", dataset=DS, agg=agg, measure=measure, filter_tree=SEEDED,
        period_field="timestamp", **kw,
    )
    m.full_clean()
    m.save()
    return m


def test_a_median_metric_is_the_middle_value_not_the_mean(staff, rows):
    request = request_for(staff)
    assert evaluate(_metric(), request).value == 55.0  # 10 20 [ ] 90 1000
    assert evaluate(_metric("md_avg", agg="avg"), request).value == 280.0


def test_median_is_offered_where_the_database_has_one():
    assert "median" in dict(aggs_available())
    assert "median" in dict(all_aggs_available())


def test_a_median_needs_a_numeric_column(staff):
    with pytest.raises(ValidationError) as missing:
        _metric(measure="")
    assert "needs a column to aggregate" in str(missing.value)
    with pytest.raises(ValidationError) as words:
        _metric(measure="path")
    assert "isn't numeric — it has no median" in str(words.value)


def test_a_card_over_a_dataset_can_be_a_median(rows):
    cells, problems = normalize_layout(
        [{"type": "metric", "dataset": DS, "agg": "median", "measure": "response_time_ms", "filter_tree": SEEDED}]
    )
    assert problems == [] and cells[0]["agg"] == "median"


def test_a_median_trends_bucket_by_bucket(staff, rows):
    trend = metric_trend(_metric(), request_for(staff), period="last_7", grain="day")
    assert trend["ok"], trend.get("error")
    assert [p["value"] for p in trend["points"] if p["value"] is not None] == [55.0]


def test_a_goal_is_judged_on_the_median(staff, rows):
    _metric()
    goals = GoalList(
        name="Latency", slug="md-latency",
        sections=[{"title": "", "goals": [{"metric": "md_latency", "target": {"op": "<=", "value": 60}}]}],
    )
    goals.save()
    row = evaluate_goals(goals, request_for(staff))["rows"][0]
    assert (row["status"], row["value"]) == ("pass", 55.0)  # the average, 280, would miss


def test_an_agent_can_preview_a_median(staff, rows):
    out = preview_metric(
        staff,
        {"dataset": DS, "agg": "median", "measure": "response_time_ms", "filter_tree": SEEDED, "name": "p50"},
    )
    assert out["ok"], out["problems"]
    assert out["result"]["value"] == 55.0


def test_a_database_without_a_median_offers_none(monkeypatch, staff, rows):
    monkeypatch.setattr("apps.datasets.core.median_supported", lambda using="default": False)
    assert "median" not in dict(aggs_available())
    with pytest.raises(ValidationError) as refused:
        _metric()
    assert "can't compute a median" in str(refused.value)
    _cells, problems = normalize_layout(
        [{"type": "metric", "dataset": DS, "agg": "median", "measure": "response_time_ms"}]
    )
    assert any("agg: use one of" in p for p in problems)
    out = preview_metric(staff, {"dataset": DS, "agg": "median", "measure": "response_time_ms", "name": "p50"})
    assert not out["ok"]
