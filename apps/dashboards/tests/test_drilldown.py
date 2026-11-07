"""Drill-downs (a card's rows modal: columns, formats, sort, rows, CSV export)
and the info card's thresholds and styling."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model

from apps.activity.models import RequestLog
from apps.dashboards.boards import render_cell
from apps.dashboards.components import drill_params, normalize_layout, widget_number
from apps.dashboards.metrics import drill_rows, format_cell, request_for, validate_drilldown
from apps.dashboards.models import Dashboard, Metric
from apps.dashboards.tests.support import own

pytestmark = pytest.mark.django_db

DS = "smallstack_requests"
SPEC = {
    "columns": [
        {"field": "path"},
        {"field": "status_code", "label": "Status"},
        {"field": "timestamp", "format": "date"},
    ],
    "sort": "-response_time_ms",
    "limit": 2,
}


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("dd-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def metric():
    for path, ms in (("/a", 10), ("/b", 90), ("/c", 50)):
        RequestLog.objects.create(path=path, method="GET", status_code=200, response_time_ms=ms)
    # Only the seeded rows: the request log also records this test client's own requests.
    m = Metric(
        key="dd_req",
        name="Requests",
        dataset=DS,
        period_field="timestamp",
        filter_tree={"field": "path", "op": "in", "value": ["/a", "/b", "/c"]},
    )
    m.save()
    return m


def _rows_url(spec=SPEC, **extra) -> str:
    url = f"/smallstack/dashboards/m/dd_req/rows/?drill={quote(json.dumps(spec))}"
    return url + "".join(f"&{k}={v}" for k, v in extra.items())


# -- the design ----------------------------------------------------------------------


def test_a_drilldown_design_is_validated():
    names = ["path", "status_code", "timestamp", "response_time_ms"]
    assert validate_drilldown(SPEC, names) == []
    assert validate_drilldown({"columns": ["path"]}, names) == []  # a bare field is shorthand
    assert any("no column 'secret'" in p for p in validate_drilldown({"columns": [{"field": "secret"}]}, names))
    assert any("format" in p for p in validate_drilldown({"columns": [{"field": "path", "format": "bold"}]}, names))
    assert any("sort" in p for p in validate_drilldown({"sort": "-nope"}, names))
    assert any("limit" in p for p in validate_drilldown({"limit": 5000}, names))
    assert any("unknown key" in p for p in validate_drilldown({"chart": "pie"}, names))


def test_cells_are_formatted_per_column():
    assert format_cell("2026-11-02T14:05:00+00:00", "date") == "2026-11-02"
    assert format_cell(9481.24, "compact") == "9.5K" and format_cell(True, "yesno") == "Yes"
    assert format_cell(None, "number") == "" and format_cell({"id": 3, "name": "Ann"}, "") == "Ann"


def test_drill_rows_follow_the_design(staff, metric):
    drill = drill_rows(metric, request_for(staff), spec=SPEC)
    assert [c["label"] for c in drill["columns"]] == ["Path", "Status", "Timestamp"]
    assert [r["cells"][0] for r in drill["rows"]] == ["/b", "/c"]  # slowest first, 2 rows
    assert len(drill["rows"][0]["cells"][2]) == 10 and drill["total"] == 3  # a date; the total is all rows


def test_the_json_rows_follow_a_design_too(client, staff, metric):
    """What the builder's dialog draws: the rows a design opens, before it's saved."""
    url = "/smallstack/dashboards/api/metrics/dd_req/rows/"
    plain = client.get(url).json()
    assert len(plain["columns"]) == 6 and plain["total"] == 3  # no design: the first six columns
    out = client.get(url, {"drill": json.dumps(SPEC)}).json()
    assert [c["label"] for c in out["columns"]] == ["Path", "Status", "Timestamp"]
    assert [r["cells"][0] for r in out["rows"]] == ["/b", "/c"] and out["sort"] == "-response_time_ms"
    assert len(out["rows"][0]["cells"][2]) == 10 and out["total"] == 3  # formatted; the total is all rows
    # Without a limit of its own, a design takes the route's (the dialog asks for a sample).
    sample = client.get(url, {"drill": json.dumps({"columns": ["path"]}), "limit": 1}).json()
    assert len(sample["rows"]) == 1 and [c["name"] for c in sample["columns"]] == ["path"]
    bad = client.get(url, {"drill": json.dumps({"columns": ["nope"]})})
    assert bad.status_code == 400 and "no column 'nope'" in bad.json()["error"]
    assert client.get(url, {"drill": "{not json"}).status_code == 400


# -- where it's set, and how a card carries it ----------------------------------------


def test_drillable_cards_take_a_design_and_others_dont(metric):
    layout, problems = normalize_layout([{"type": "metric", "metric": "dd_req", "options": {"drilldown": SPEC}}])
    assert problems == [] and layout[0]["options"]["drilldown"] == SPEC
    _, problems = normalize_layout(
        [{"type": "metric", "metric": "dd_req", "options": {"drilldown": {"columns": ["nope"]}}}]
    )
    assert any("no column 'nope'" in p for p in problems)  # checked against the metric's dataset
    _, problems = normalize_layout([{"type": "text", "options": {"markdown": "x", "drilldown": SPEC}}])
    assert problems == ["layout[0].options: a Note card has no drill-down"]


def test_every_rows_link_a_card_draws_carries_its_design(staff, metric):
    params = drill_params({"options": {"drilldown": SPEC}})
    assert json.loads(params["drill"]) == SPEC and drill_params({"options": {}}) == {}
    board = Dashboard(name="x", slug="x")
    request = request_for(staff)
    for cell in (
        {"type": "metric", "metric": "dd_req", "options": {"drilldown": SPEC}},
        {"type": "metric_group", **own("dd_req"), "options": {"dimension": "method", "drilldown": SPEC}},
        {"type": "trend", **own("dd_req"), "options": {"drilldown": SPEC}},
    ):
        layout, problems = normalize_layout([cell])
        assert problems == [], problems
        html = render_cell(board, layout[0], request, None)
        assert "drill=%7B%22columns%22" in html or "drill=%7B&quot;columns" in html, cell["type"]


# -- the modal and its export -------------------------------------------------------


def test_the_modal_shows_the_cards_columns_and_offers_csv(client, staff, metric):
    html = client.get(_rows_url()).content.decode()
    assert 'title="Sort by Status">Status' in html and html.index('title="/b"') < html.index('title="/c"')
    assert "First 2 shown." in html and "Download CSV (all 3)" in html and "format=csv" in html


def test_the_export_has_the_same_columns(client, staff, metric):
    response = client.get(_rows_url(format="csv"))
    assert response["Content-Type"] == "text/csv" and 'filename="dd_req-rows.csv"' in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["Path", "Status", "Timestamp"] and [r[0] for r in rows[1:]] == ["/b", "/c", "/a"]  # all rows


def test_a_modal_without_a_design_keeps_its_defaults_and_can_export(client, staff, metric):
    html = client.get("/smallstack/dashboards/m/dd_req/rows/").content.decode()
    assert "Download CSV" in html
    response = client.get("/smallstack/dashboards/m/dd_req/rows/?format=csv")
    assert response.status_code == 200 and len(response.content.decode().splitlines()) == 4


def test_a_bad_design_is_refused(client, staff, metric):
    assert client.get(_rows_url({"columns": [{"field": "secret"}]})).status_code == 400
    assert client.get("/smallstack/dashboards/m/dd_req/rows/?drill=%7Bnot-json").status_code == 400


def test_period_links_keep_the_design(client, staff, metric):
    html = client.get(_rows_url()).content.decode()
    assert html.count("drill=") >= 3  # the period links and the export


# -- info cards: thresholds and styling ----------------------------------------------


def test_the_info_card_number_comes_from_value_or_the_headline():
    assert widget_number({"value": 7, "headline": "99 things"}) == 7.0
    assert widget_number({"headline": "46,849 requests"}) == 46849.0
    assert widget_number({"headline": "Down"}) is None


def test_info_cards_take_rules_and_text_styling(staff):
    from apps.dashboards.components import available_widgets

    key, widget, _info = next((k, w, i) for k, w, i in available_widgets() if i is None)
    number = widget_number(widget.get_data())
    rules = [{"op": ">=", "value": -1e12, "state": "danger"}]
    layout, problems = normalize_layout(
        [
            {
                "type": "widget",
                "title": "Watched",
                "options": {
                    "widget": key,
                    "thresholds": rules,
                    "style": {"size": "l", "align": "center", "title_color": "accent"},
                },
            }
        ]
    )
    assert problems == []
    html = render_cell(Dashboard(name="x", slug="x"), layout[0], request_for(staff), None)
    assert "cs-size-l" in html and "cs-align-center" in html and "cs-title-color-accent" in html
    assert '<span class="widget-title">Watched</span>' in html  # a placement's title shows
    if number is not None:
        assert "cs-state-danger" in html and "widget-status-down" in html
    _, problems = normalize_layout([{"type": "widget", "options": {"widget": key, "style": {"format": "compact"}}}])
    assert any("unknown setting 'format'" in p for p in problems)  # a text headline has no number format


def test_the_builder_knows_what_each_type_takes(client, staff, metric):
    html = client.get("/smallstack/dashboards/components/new/").content.decode()
    data = json.loads(html.split('id="cb-data" type="application/json">', 1)[1].split("</script>", 1)[0])
    types = {t["type"]: t for t in data["types"]}
    assert types["metric"]["drillable"] and types["trend"]["drillable"] and not types["widget"]["drillable"]
    assert types["widget"]["style_settings"] == ["size", "color", "title_size", "title_color", "align"]
    assert "format" in types["metric"]["style_settings"]
    assert ["date", "Date — 2026-11-02"] in data["drilldown"]["formats"]
    # Ticking "Choose the columns" starts from what the drill-down shows without a design.
    assert data["drilldown"]["default_columns"] == 6 and data["drilldown"]["default_rows"] == 50
    assert 'id="cb-drill-card"' in html


# -- clickable headers (server-side sort) and resizable columns ------------------------


def test_a_header_sorts_the_rows_and_a_second_click_flips_it(client, staff, metric):
    import re

    html = client.get(_rows_url()).content.decode()
    # Each header links to the same rows ordered by it; the design's sort is marked.
    assert re.search(r'aria-sort="descending" data-field="response_time_ms"|data-field="path"', html)
    link_re = r'data-field="path">\s*<a class="dm-sort" href="([^"]+)"'
    path_link = re.search(link_re, html).group(1).replace("&amp;", "&")
    assert "order=path" in path_link and "drill=" in path_link  # the design and filters ride along
    asc = client.get(path_link).content.decode()
    assert asc.index('title="/a"') < asc.index('title="/b"')
    assert 'aria-sort="ascending" data-field="path"' in asc and "▲" in asc
    flip = re.search(r'data-field="path">\s*<a class="dm-sort" href="([^"]+)"', asc).group(1).replace("&amp;", "&")
    assert "order=-path" in flip
    desc = client.get(flip).content.decode()
    assert desc.index('title="/c"') < desc.index('title="/b"') and 'aria-sort="descending" data-field="path"' in desc


def test_dates_and_numbers_sort_newest_or_largest_first(client, staff, metric):
    import re

    html = client.get("/smallstack/dashboards/m/dd_req/rows/").content.decode()
    ts = re.search(r'data-field="timestamp">\s*<a class="dm-sort" href="([^"]+)"', html).group(1)
    assert "order=-timestamp" in ts


def test_the_export_follows_the_clicked_order_and_a_bad_order_is_ignored(client, staff, metric):
    rows = list(csv.reader(io.StringIO(client.get(_rows_url(order="path", format="csv")).content.decode())))
    assert [r[0] for r in rows[1:]] == ["/a", "/b", "/c"]
    html = client.get(_rows_url(order="secret")).content.decode()  # not a column: the design's sort stands
    assert html.index('title="/b"') < html.index('title="/c"')


def test_columns_carry_resize_handles_and_a_widths_key(client, staff, metric):
    html = client.get(_rows_url()).content.decode()
    # The framework's table-resize.js: crud-table + data-table-key + th[data-field] + col_resizer.
    assert 'class="dm-table crud-table" data-table-key="drill/dd_req:path,status_code,timestamp"' in html
    assert html.count('class="col-resizer" role="separator"') == 3 and 'data-field="path"' in html


# -- the metric page's rows table: the same sorting, the framework resizer -------------


def test_the_metric_page_rows_sort_in_place_and_resize(client, staff, metric):
    import re

    html = client.get("/smallstack/dashboards/m/dd_req/").content.decode()
    assert 'class="table-plain md-table crud-table" data-table-key="metric/dd_req:' in html
    assert 'class="col-resizer" role="separator"' in html and 'id="md-rows"' in html
    link = re.search(r'data-field="path">\s*<a class="dm-sort" href="([^"]+)"', html).group(1)
    assert 'hx-select="#md-page" hx-target="#md-page"' in html and "order=path" in link
    asc = client.get("/smallstack/dashboards/m/dd_req/?order=path").content.decode()
    assert 'aria-sort="ascending" data-field="path"' in asc
    assert asc.index('title="/a"') < asc.index('title="/b"') < asc.index('title="/c"')
    desc = client.get("/smallstack/dashboards/m/dd_req/?order=-path").content.decode()
    assert desc.index('title="/c"') < desc.index('title="/a"')


def test_a_period_change_keeps_the_sort(client, staff, metric):
    html = client.get("/smallstack/dashboards/m/dd_req/?order=path").content.decode()
    assert 'href="?order=path&amp;period=today"' in html  # the quick period links
    assert '<input type="hidden" name="order" value="path">' in html  # the More… form
