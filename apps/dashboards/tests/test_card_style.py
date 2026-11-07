"""Card styling and a card's own colour rules.

A metric's thresholds colour it everywhere; a saved card (or any cell) of a
``stylable`` type may override them and restyle the number and title — size,
colour, alignment, format, unit — from a fixed vocabulary of theme tokens.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.activity.models import RequestLog
from apps.dashboards.boards import render_cell
from apps.dashboards.components import CARD_STYLE, card_style, normalize_layout, validate_card_style
from apps.dashboards.metrics import request_for
from apps.dashboards.models import Component, Dashboard, Metric
from apps.dashboards.tests.support import own

pytestmark = pytest.mark.django_db

DS = "smallstack_requests"


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("cs-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def metric():
    for method in ("GET", "GET", "GET", "POST"):
        RequestLog.objects.create(path="/x", method=method, status_code=200, response_time_ms=5)
    m = Metric(key="cs_req", name="Requests", dataset=DS, thresholds=[{"op": ">=", "value": 1, "state": "success"}])
    m.save()
    return m


def _render(staff, cell: dict) -> str:
    layout, problems = normalize_layout([cell])
    assert problems == [], problems
    return render_cell(Dashboard(name="x", slug="x"), layout[0], request_for(staff), None)


def test_the_style_vocabulary_is_validated():
    assert validate_card_style({"style": {"size": "xl", "color": "accent", "align": "center", "unit": "req"}}) == []
    assert any("one of" in p for p in validate_card_style({"style": {"color": "#ff0000"}}))  # never a literal
    assert any("unknown setting" in p for p in validate_card_style({"style": {"font": "Comic"}}))
    assert any("thresholds" in p for p in validate_card_style({"thresholds": [{"op": "~", "value": 1}]}))
    assert {s["name"] for s in CARD_STYLE} == {"format", "unit", "size", "color", "title_size", "title_color", "align"}


def test_card_style_fills_defaults_and_builds_the_css_hooks():
    style = card_style({"options": {"style": {"size": "l"}}})
    assert style["size"] == "l" and style["color"] == "state" and style["thresholds"] is None
    assert style["classes"].split() == [
        "card-style",
        "cs-size-l",
        "cs-color-state",
        "cs-title-m",
        "cs-title-color-quiet",
        "cs-align-start",
    ]


def test_only_stylable_types_take_style(metric):
    _, problems = normalize_layout([{"type": "text", "options": {"markdown": "hi", "style": {"size": "l"}}}])
    assert problems == ["layout[0].options: a Note card takes no style or thresholds"]
    layout, problems = normalize_layout(
        [{"type": "metric", "metric": "cs_req", "options": {"style": {"size": "", "align": "end"}}}]
    )
    assert problems == [] and layout[0]["options"]["style"] == {"align": "end"}  # blanks mean "the default"


def test_a_single_stat_takes_its_own_rules_format_and_unit(staff, metric):
    plain = _render(staff, {"type": "metric", "metric": "cs_req"})
    assert "stat-card--success" in plain  # the metric's rule
    styled = _render(
        staff,
        {
            "type": "metric",
            "metric": "cs_req",
            "options": {
                "thresholds": [{"op": ">=", "value": 3, "state": "danger"}],
                "style": {"format": "decimal", "unit": "hits", "size": "xl", "color": "state", "align": "center"},
            },
        },
    )
    assert "stat-card--danger" in styled and "stat-card--success" not in styled
    assert "4.00" in styled and ">hits<" in styled
    assert 'class="card-style cs-size-xl cs-color-state cs-title-m cs-title-color-quiet cs-align-center"' in styled


def test_a_grouped_stat_colours_each_group_by_the_cards_rules(staff, metric):
    html = _render(
        staff,
        {
            "type": "metric_group",
            **own("cs_req"),
            "options": {
                "dimension": "method",
                "thresholds": [{"op": ">=", "value": 3, "state": "warning"}],
                "style": {"color": "state", "size": "l"},
            },
        },
    )
    get_button = html[html.index("dash-group") : html.index("GET")]
    assert "dash-group--warning" in get_button  # GET (3) matches the card's rule
    assert html.count("dash-group--warning") == 1  # POST (1) doesn't
    assert "cs-size-l" in html and "cs-group" in html


def test_an_empty_rule_list_means_no_colouring(staff, metric):
    html = _render(staff, {"type": "metric", "metric": "cs_req", "options": {"thresholds": []}})
    assert "stat-card--success" not in html  # the card switched the metric's rules off


def test_a_saved_card_carries_its_style_to_every_dashboard(staff, metric):
    card = Component(
        name="Big requests",
        type="metric",
        metric="cs_req",
        options={"style": {"size": "xl"}, "thresholds": [{"op": ">", "value": 0, "state": "warning"}]},
    )
    card.save()
    board = Dashboard(name="Ops", slug="ops", layout=[{"component": card.key}])
    board.save()
    assert board.layout[0]["options"]["style"] == {"size": "xl"}
    card.options = {"style": {"size": "s"}}
    card.save()
    board.refresh_from_db()
    assert board.layout[0]["options"] == {"style": {"size": "s"}}
    with pytest.raises(ValidationError, match="style"):
        Component(name="Bad", type="metric", metric="cs_req", options={"style": {"color": "chartreuse"}}).save()


def test_the_builder_and_agents_see_the_styling(client, staff, metric):
    html = client.get("/smallstack/dashboards/components/new/").content.decode()
    data = json.loads(html.split('id="cb-data" type="application/json">', 1)[1].split("</script>", 1)[0])
    assert [s["name"] for s in data["style"]][:3] == ["format", "unit", "size"]
    assert data["thresholds"]["states"] == ["success", "warning", "danger", "muted"]
    types = {t["type"]: t for t in data["types"]}
    assert types["metric"]["stylable"] and types["metric_group"]["stylable"] and not types["text"]["stylable"]
    assert data["metrics"][0]["thresholds"] == [{"op": ">=", "value": 1, "state": "success"}]
    assert 'id="cb-style-card"' in html
    preview = client.post(
        "/smallstack/dashboards/api/card-preview/",
        data=json.dumps({"type": "metric", "metric": "cs_req", "options": {"style": {"color": "accent"}}}),
        content_type="application/json",
    ).json()
    assert preview["problems"] == [] and "cs-color-accent" in preview["html"]
    payload = client.get("/smallstack/dashboards/api/components/").json()
    assert payload["style"] == CARD_STYLE
