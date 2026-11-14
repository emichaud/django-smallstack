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


# -- the bar chart, the gauge and the table -------------------------------------------


def _cell_board(cell: dict) -> Dashboard:
    d = Dashboard(name="Cards", slug="wc-cards", default_period="last_7", layout=[{"id": "c", "w": 6, "h": 4, **cell}])
    d.save()
    return d


def _cell(client, query: str = "") -> str:
    return client.get(f"/smallstack/dashboards/d/wc-cards/cells/c/{query}").content.decode()


def test_the_three_designs_are_registered_with_their_rules():
    bars, gauge, table = (get_component_type(k) for k in ("bars", "gauge", "table"))
    assert bars is not None and bars.requires == frozenset({"dimension"}) and bars.group == "Charts"
    assert gauge is not None and gauge.single_value and gauge.stylable and gauge.drillable
    assert table is not None and table.shows_rows and table.drillable and not table.single_value
    described = {t["type"]: t for t in describe_types()}
    assert [o["name"] for o in described["table"]["options"]] == ["rows", "totals"]
    assert described["table"]["shows_rows"] and not described["trend"]["shows_rows"]


def test_bar_chart_draws_columns_or_bars_by_size_or_by_name(client, staff, metric):
    RequestLog.objects.create(path="/y", method="POST", status_code=201, response_time_ms=5)
    _cell_board({"type": "bars", **own("wc_req"), "options": {"dimension": "method"}})
    html = _cell(client)
    assert 'class="bars bars--vertical' in html and html.count('class="bars-item') == 2
    assert html.index('title="GET: 3"') < html.index('title="POST: 1"')  # largest first
    assert 'style="--share: 1.0000;"' in html and 'style="--share: 0.3333;"' in html
    assert "d/wc-cards/cards/c/rows/?narrow=" in html  # each bar opens its rows
    d = Dashboard.objects.get(slug="wc-cards")
    d.layout[0]["options"].update(direction="horizontal", order="label")
    d.save()
    html = _cell(client)  # (each GET here is itself logged, so GET's count grows; POST's doesn't)
    assert 'class="bars bars--horizontal' in html and html.index('title="GET: ') < html.index('title="POST: 1"')
    with pytest.raises(ValidationError, match="direction"):
        _cell_board({"type": "bars", **own("wc_req"), "options": {"dimension": "method", "direction": "diagonal"}})


def test_gauge_puts_the_value_on_a_dial_with_the_rules_as_bands(client, staff, metric):
    rules = [{"op": ">=", "value": 2, "state": "warning"}, {"op": "between", "value": [0, 1], "state": "success"}]
    _cell_board({"type": "gauge", "metric": "wc_req", "options": {"min": 0, "max": 4, "thresholds": rules}})
    html = _cell(client)
    assert 'class="gauge-dial gauge-dial--warning"' in html  # 3 of 0–4, ≥ 2 is a warning
    assert 'class="gauge-fill" d="M10 50 A40 40 0 0 1 90 50" pathLength="100" stroke-dasharray="75.00 100"' in html
    assert 'gauge-band--warning" d=' in html and 'stroke-dasharray="50.00 100" stroke-dashoffset="-50.00"' in html
    assert 'gauge-band--success" d=' in html and 'stroke-dasharray="25.00 100" stroke-dashoffset="-0.00"' in html
    assert ">0<" in html and ">4<" in html and '<span class="gauge-value">3' in html
    assert 'hx-get="/smallstack/dashboards/m/wc_req/rows/?period=last_7"' in html  # taps open the metric's rows
    with pytest.raises(ValidationError, match="above"):
        _cell_board({"type": "gauge", "metric": "wc_req", "options": {"min": 5, "max": 4}})


def test_table_shows_the_rows_in_its_columns_sorted_and_paged_with_totals(client, staff, metric):
    for n in range(4):
        RequestLog.objects.create(path=f"/p{n}", method="POST", status_code=201 + n, response_time_ms=5)
    columns = [{"field": "method", "label": "Verb"}, {"field": "status_code"}]
    # The card's own filter: the POSTs (the GETs this test makes are logged too).
    posts = {"field": "method", "op": "eq", "value": "POST"}
    _cell_board(
        {
            "type": "table",
            **{**own("wc_req"), "filter_tree": posts},
            "options": {"rows": 3, "totals": True, "drilldown": {"columns": columns, "sort": "-status_code"}},
        }
    )
    html = _cell(client)
    assert ">Verb<" in html and html.count("<tr>") == 1 + 3 + 1  # head, a page of 3, totals
    assert "1–3 of 4" in html and 'aria-label="Next page"' in html and 'class="tbl-off" aria-hidden="true">‹' in html
    assert 'data-table-key="card/c:method,status_code"' in html and 'class="col-resizer"' in html
    assert '<tfoot><tr><td class="tbl-totals-label">Total</td><td class="tbl-num">810</td>' in html  # 201+…+204
    assert html.index(">204<") < html.index(">203<") < html.index(">202<")  # the design's sort
    assert 'hx-target="closest .dash-cell-body"' in html and "?order=status_code" in html  # headers sort in place
    assert "d/wc-cards/cards/c/rows/?drill=" in html  # All rows: the same columns, in the window
    page = _cell(client, "?page=2&order=status_code")
    assert "4–4 of 4" in page and ">204<" in page and 'aria-label="Previous page"' in page
    assert _cell(client, "?page=9").count("<tr>") == 1 + 1 + 1  # past the end: the last page
    with pytest.raises(ValidationError, match="rows"):
        _cell_board({"type": "table", **own("wc_req"), "options": {"rows": 0}})
    with pytest.raises(ValidationError, match="no column"):
        _cell_board({"type": "table", **own("wc_req"), "options": {"drilldown": {"columns": ["ghost"]}}})


def test_gauge_takes_a_ceiling_of_zero(client, staff, metric):
    # `max or 100` turned a ceiling of 0 into 100: a dial from -10 to 0 drew to 100.
    client.force_login(staff)
    _cell_board({"type": "gauge", "metric": "wc_req", "options": {"min": -10, "max": 0}})
    html = _cell(client)
    assert ">-10<" in html and ">0<" in html and ">100<" not in html
