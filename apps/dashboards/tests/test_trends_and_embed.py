"""A metric over time (``trends``), the time grain under it, and the
``{% dashboard %}`` embed — plus the reference chart card a project registers
from its own app (``apps/website/dashboard_cards.py``)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory
from django.utils import timezone

from apps.activity.models import RequestLog
from apps.dashboards.metrics import request_for
from apps.dashboards.models import Dashboard
from apps.dashboards.tests.test_dashboards import DS_STAFF, _call, _metric
from apps.dashboards.trends import default_grain, metric_trend
from apps.datasets.core import get_dataset
from apps.datasets.filter_tree import describe_filter_tree

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff():
    return get_user_model().objects.create_user("tstaff", password="x", is_staff=True)


@pytest.fixture
def member():
    return get_user_model().objects.create_user("tmember", password="x")


def _at(days_ago: int, n: int = 1, ms: int = 10) -> None:
    """*n* GET rows timestamped noon, *days_ago* days back (local time)."""
    noon = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    for _ in range(n):
        row = RequestLog.objects.create(path=f"/t/{days_ago}", method="GET", status_code=200, response_time_ms=ms)
        RequestLog.objects.filter(pk=row.pk).update(timestamp=noon)


@pytest.fixture
def history():
    """Today ×2, 2 days ago ×3, 5 days ago ×1; nothing on the days between."""
    _at(0, 2, ms=10)
    _at(2, 3, ms=30)
    _at(5, 1, ms=50)


# -- the grain: Dataset.series(grain=…) -------------------------------------------------------


def test_series_grain_groups_by_calendar_bucket(history):
    ds = get_dataset(DS_STAFF)
    days = ds.series("timestamp", grain="day")
    assert [r["value"] for r in days] == [1, 3, 2]  # chronological, empty days absent
    assert all(r["lo"] < r["hi"] for r in days)
    # A bucket is one calendar day, which is 23 or 25 hours when the clocks change.
    first = datetime.fromisoformat(days[0]["lo"])
    assert datetime.fromisoformat(days[0]["hi"]).date() - first.date() == timedelta(days=1)
    assert days[-1]["label"].startswith(timezone.localtime().strftime("%b"))


def test_series_grain_rejects_unknown_and_ignores_non_dates(history):
    ds = get_dataset(DS_STAFF)
    with pytest.raises(ValueError, match="unknown grain"):
        ds.series("timestamp", grain="fortnight")
    # A grain on a non-date column is ignored (the call_stats rule): plain grouping.
    assert {r["label"] for r in ds.series("method", grain="week")} == {"GET"}


# -- metric_trend ---------------------------------------------------------------------------


def test_trend_has_every_bucket_and_flags_the_running_one(staff, history):
    m = _metric(key="m_t", period_field="timestamp")
    t = metric_trend(m, request_for(staff), "last_7")
    assert t["ok"] and t["grain"] == "day" and len(t["points"]) == 7
    assert [p["value"] for p in t["points"]] == [0, 1, 0, 0, 3, 0, 2]  # empty days read 0 for a count
    assert [p["partial"] for p in t["points"]] == [False] * 6 + [True]


def test_trend_bucket_drill_matches_its_value(staff, history):
    from apps.dashboards.metrics import drill_rows

    m = _metric(key="m_t", period_field="timestamp")
    req = request_for(staff)
    for p in metric_trend(m, req, "last_7")["points"]:
        assert drill_rows(m, req, extra_tree=p["narrow"])["total"] == p["value"]


def test_trend_gaps_for_averages_and_explains_what_it_cannot_do(staff, member, history):
    avg = _metric(key="m_avg", agg="avg", measure="response_time_ms", period_field="timestamp")
    values = [p["value"] for p in metric_trend(avg, request_for(staff), "last_7")["points"]]
    assert values[1] == 50 and values[0] is None  # an empty day is a gap, not an average of 0
    no_period = _metric(key="m_np")
    assert "no period field" in metric_trend(no_period, request_for(staff), "last_7")["error"]
    m = _metric(key="m_t", period_field="timestamp")
    assert metric_trend(m, request_for(member), "last_7")["restricted"]  # staff dataset


def test_default_grain_fits_the_span():
    d = datetime(2026, 1, 1).date()
    assert default_grain(d, d + timedelta(days=7)) == "day"
    assert default_grain(d, d + timedelta(days=90)) == "week"
    assert default_grain(d, d + timedelta(days=365)) == "month"
    assert default_grain(d, d + timedelta(days=1000)) == "quarter"
    assert default_grain(None, None) == "month"


def test_all_time_fits_its_buckets_to_the_data(staff, history):
    """No period has no span to fit, so the trend fits the data's: a week of
    rows reads by day (3 buckets with data, not one month bar); a chosen grain
    still wins; a metric whose filter matches nothing keeps the month default."""
    m = _metric(key="m_all", period_field="timestamp")
    t = metric_trend(m, request_for(staff))
    assert t["ok"] and t["grain"] == "day" and [p["value"] for p in t["points"]] == [1, 3, 2]
    assert metric_trend(m, request_for(staff), grain="week")["grain"] == "week"
    _at(400, 1)
    assert metric_trend(m, request_for(staff))["grain"] == "month"  # a year and change of data
    m.filter_tree = {"field": "method", "op": "eq", "value": "DELETE"}
    assert metric_trend(m, request_for(staff))["grain"] == "month"


def test_trend_over_rest_and_mcp(client, staff, history):
    _metric(key="m_t", period_field="timestamp")
    client.force_login(staff)
    data = client.get("/smallstack/dashboards/api/metrics/m_t/trend/", {"period": "last_7", "grain": "week"}).json()
    assert data["key"] == "m_t" and data["grain"] == "week" and sum(p["value"] for p in data["points"]) == 6
    out = _call("metric_trend", {"key": "m_t", "period": "last_7"}, staff)
    assert out["grain"] == "day" and [p["value"] for p in out["points"]][-1] == 2
    assert "error" in _call("metric_trend", {"key": "nope"}, staff)


def test_iso_datetimes_read_as_dates_in_a_filter_description():
    tree = {"and": [{"field": "ts", "op": ">=", "value": "2026-10-19T00:00:00+00:00"}]}
    with timezone.override("UTC"):
        assert describe_filter_tree(tree, {"ts": "Timestamp"}) == "Timestamp ≥ 2026-10-19"


def test_rows_for_a_time_bucket_have_no_period_links(client, staff, history):
    m = _metric(key="m_t", period_field="timestamp")
    narrow = metric_trend(m, request_for(staff), "last_7")["points"][-1]["narrow"]
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/m/m_t/rows/", {"narrow": json.dumps(narrow)}).content.decode()
    assert "<strong>2 rows</strong>" in html and "md-period" not in html


# -- {% dashboard %} ----------------------------------------------------------------------------


def _render(user, source: str) -> str:
    request = RequestFactory().get("/somewhere/")
    request.user = user
    return Template("{% load dashboard_tags %}" + source).render(Context({"request": request}))


@pytest.fixture
def board(staff):
    _metric(key="m_t", name="Requests", period_field="timestamp")
    d = Dashboard(
        name="Embed me",
        slug="embed-me",
        owner=staff,
        default_period="mtd",
        layout=[
            {"id": "b", "type": "metric", "metric": "m_t", "x": 6, "y": 0, "w": 6, "h": 2},
            {"id": "a", "type": "text", "options": {"markdown": "**Hi**"}, "x": 0, "y": 0, "w": 6, "h": 2},
            {"id": "c", "type": "metric", "metric": "m_t", "x": 0, "y": 2, "w": 4, "h": 2},
        ],
    )
    d.save()
    return d


def test_embed_lays_out_cells_in_reading_order_at_the_dashboards_period(staff, board):
    html = _render(staff, '{% dashboard "embed-me" %}')
    urls = [part.split('"')[0] for part in html.split('hx-get="')[1:]]
    assert urls == [f"/smallstack/dashboards/d/embed-me/cells/{c}/?period=mtd" for c in ("a", "b", "c")]
    assert "--x: 7; --y: 1; --w: 6; --h: 2;" in html  # cell b, 1-based grid lines
    assert 'class="dash-embed"' in html and "Embed me" in html and "This month so far" in html


def test_embed_period_title_and_eager_rendering(staff, board, history):
    html = _render(staff, '{% dashboard "embed-me" period="all" title=False lazy=False %}')
    assert "/cells/" not in html and "dash-cell-loading" not in html  # rendered now, nothing lazy
    assert "<strong>Hi</strong>" in html and 'class="sr-only"' in html  # no visible heading
    assert '<div class="stat-card-value">6</div>' in html  # the six seeded rows, all time


def test_embed_renders_nothing_for_who_may_not_see_it(member, board):
    from django.contrib.auth.models import AnonymousUser

    assert "dash-embed" not in _render(member, '{% dashboard "embed-me" %}')  # personal board, not theirs
    board.owner = None
    board.save()
    assert "dash-embed" in _render(member, '{% dashboard "embed-me" %}')  # shared
    assert "dash-embed" not in _render(AnonymousUser(), '{% dashboard "embed-me" %}')
    assert _render(member, '{% dashboard "no-such" %}').strip() == ""
