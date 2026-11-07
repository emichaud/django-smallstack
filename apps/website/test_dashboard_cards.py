"""This project's dashboard card types (``dashboard_cards.py``) and the
dashboard starter page — the downstream side of the dashboards seam."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.activity.models import RequestLog
from apps.dashboards.components import describe_types, get_component_type
from apps.dashboards.models import Dashboard, Metric
from apps.dashboards.tests.support import own
from apps.datasets.registry import dataset

pytestmark = pytest.mark.django_db

DS = "t_website_cards"


@dataset(DS, label="Website cards log", columns=["method", "status_code", "timestamp"])
def _log(request=None):
    return RequestLog.objects.all()


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("wc-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def metric():
    for _ in range(3):
        RequestLog.objects.create(path="/x", method="GET", status_code=200, response_time_ms=5)
    m = Metric(key="wc_req", name="Requests", dataset=DS, period_field="timestamp")
    m.save()
    return m


def _board(cell_options: dict) -> Dashboard:
    # A chart filters a dataset of its own: the metric's definition, as the card's.
    d = Dashboard(
        name="Trends",
        slug="wc-trends",
        default_period="last_7",
        layout=[
            {"id": "t", "type": "trend", **own("wc_req"), "title": "Requests", "w": 6, "h": 3, "options": cell_options}
        ],
    )
    d.save()
    return d


def test_the_trend_type_is_registered_from_this_app():
    ct = get_component_type("trend")
    assert ct is not None and ct.template == "website/cells/trend.html" and ct.requires == frozenset({"date"})
    described = next(t for t in describe_types() if t["type"] == "trend")
    assert [o["name"] for o in described["options"]] == ["kind", "grain"]  # what the Add card dialog renders


def test_trend_card_renders_bars_that_open_their_rows(client, staff, metric):
    _board({"kind": "bars"})
    html = client.get("/smallstack/dashboards/d/wc-trends/cells/t/").content.decode()
    assert html.count('<button type="button" class="trend-col') == 7  # last 7 days, one button per day
    assert "trend-col--partial" in html and 'data-stat-modal="Requests, ' in html
    assert "/smallstack/dashboards/d/wc-trends/cards/t/rows/?narrow=" in html  # its own rows, by its place
    assert "<caption>Requests, last 7 days, by day</caption>" in html  # the screen-reader table


def test_trend_card_line_and_grain(client, staff, metric):
    _board({"kind": "line", "grain": "week"})
    html = client.get("/smallstack/dashboards/d/wc-trends/cells/t/").content.decode()
    assert "<polyline points=" in html and "by week" in html


def test_trend_cell_is_validated_on_save(metric):
    with pytest.raises(ValidationError, match="kind"):
        _board({"kind": "pie"})
    with pytest.raises(ValidationError, match="grain"):
        _board({"grain": "hourly"})


def test_trend_card_needs_a_period_column(client, staff, metric):
    """A trend buckets its rows by the card's period column (the date column it
    is read over): without one the save is refused, saying so, and a card that
    already exists says the same rather than drawing nothing."""
    Metric.objects.filter(key="wc_req").update(period_field="")
    with pytest.raises(ValidationError, match="needs a period column: the date column it is read over"):
        _board({})
    Metric.objects.filter(key="wc_req").update(period_field="timestamp")
    board = _board({})
    board.layout[0]["period_field"] = ""
    Dashboard.objects.filter(pk=board.pk).update(layout=board.layout)
    html = client.get("/smallstack/dashboards/d/wc-trends/cells/t/").content.decode()
    assert "no period field, so it can&#x27;t be read over time" in html


def test_trend_card_draws_a_hand_entered_metric_as_it_is(client, staff, metric):
    """A chart filters a dataset of its own — except over a metric with no
    dataset to filter (entered by hand, a rate), whose values are the only rows
    there are. Over a metric read from a dataset it's refused."""
    Metric.objects.create(key="wc_manual", name="Signups", source="manual", period_field="date")
    board = _board({})
    board.layout[0] = {"id": "t", "type": "trend", "metric": "wc_manual", "w": 6, "h": 3, "options": {}}
    board.full_clean()
    board.layout[0]["metric"] = "wc_req"
    with pytest.raises(ValidationError, match="filters a dataset of its own"):
        board.full_clean()


def test_dashboard_starter_page_embeds_a_dashboard(client, staff, metric):
    board = _board({})
    board.owner = None
    board.save()
    html = client.get("/starter/dashboard/").content.decode()
    assert 'class="dash-embed"' in html and "/smallstack/dashboards/d/wc-trends/cells/t/" in html
    assert 'metric_card "wc_req" period="mtd"' in html


def test_dashboard_starter_page_needs_a_login(client):
    assert client.get("/starter/dashboard/").status_code == 302


# -- thresholds and styling (the trend card is a ``stylable`` type) ---------------------


def test_the_trend_card_opts_into_card_styling():
    assert get_component_type("trend").stylable is True
    described = next(t for t in describe_types() if t["type"] == "trend")
    assert described["stylable"] is True and described["group"] == "Charts"


def test_trend_buckets_take_the_cards_own_rules_and_style(client, staff, metric):
    _board(
        {
            "kind": "bars",
            "thresholds": [{"op": ">=", "value": 3, "state": "danger"}],
            "style": {"format": "decimal", "unit": "hits", "size": "xl", "color": "state", "align": "center"},
        }
    )
    html = client.get("/smallstack/dashboards/d/wc-trends/cells/t/").content.decode()
    assert 'class="trend card-style cs-size-xl cs-color-state cs-title-m cs-title-color-quiet cs-align-center"' in html
    assert html.count("trend-col--danger") == 1  # today's bucket (3 rows) matches; the empty days don't
    assert "3.00" in html and '<span class="trend-unit">hits</span>' in html
    assert "trend-latest--danger" in html


def test_trend_line_marks_each_bucket_and_a_chosen_colour_paints_the_series(client, staff, metric):
    _board({"kind": "line", "style": {"color": "accent"}})
    html = client.get("/smallstack/dashboards/d/wc-trends/cells/t/").content.decode()
    assert html.count('class="trend-dot"') == 7 and "cs-color-accent" in html


def test_trend_style_is_validated_like_any_stylable_card(metric):
    with pytest.raises(ValidationError, match="style"):
        _board({"style": {"color": "#00ff00"}})
