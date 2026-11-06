"""Saved cards (``Component``), the component builder, and the extension seam.

A metric is *what* number; a component is *how it's drawn*: a registered card
type (single stat, grouped stat, info card, note — or an app's chart), the
metric, the type's options. Dashboards place it by key and keep a copy that
follows every edit.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template import Context, Template

from apps.dashboards.components import cell_title, component_media, describe_types, normalize_layout
from apps.dashboards.models import Component, Dashboard, Metric

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff(client):
    user = User.objects.create_user("cb-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def metric():
    m = Metric(key="cb_requests", name="Requests", dataset=DS)
    m.save()
    return m


def _card(**kw) -> Component:
    c = Component(
        **{
            "name": "Requests by method",
            "type": "metric_group",
            "metric": "cb_requests",
            "options": {"dimension": "method"},
            **kw,
        }
    )
    c.save()
    return c


# -- the type registry: a small framework set, open to apps ---------------------------


def test_the_framework_ships_stats_and_info_cards_and_apps_add_charts():
    by_key = {t["type"]: t for t in describe_types()}
    assert by_key["metric"]["label"] == "Single stat" and by_key["metric"]["group"] == "Stats"
    assert by_key["metric_group"]["label"] == "Grouped stat" and by_key["metric_group"]["group"] == "Stats"
    assert by_key["widget"]["label"] == "Info card" and by_key["widget"]["group"] == "Info"
    assert by_key["widget"]["staff_only"] is True
    # apps/website registers a chart the same way any downstream app would.
    assert by_key["trend"]["group"] == "Charts" and by_key["trend"]["media"] == {
        "css": ["website/css/dashboard-cards.css"]
    }
    assert all(t["icon"] for t in by_key.values())


def test_component_media_loads_each_file_once():
    from apps.dashboards.components import _TYPES, ComponentType, register_component_type

    register_component_type(
        ComponentType(
            key="t_echart",
            label="Test chart",
            template="dashboards/cells/text.html",
            build=lambda c, x: {},
            group="Charts",
            media={"js": ["vendor/echarts.min.js", "x/charts.js"], "css": ["website/css/dashboard-cards.css"]},
        )
    )
    try:
        files = component_media()
        assert files["css"].count("website/css/dashboard-cards.css") == 1
        assert files["js"][-2:] == ["vendor/echarts.min.js", "x/charts.js"]
        html = Template("{% load dashboard_tags %}{% component_media %}").render(Context({}))
        assert '<script src="/static/vendor/echarts.min.js" defer></script>' in html
        assert html.count("dashboard-cards.css") == 1
    finally:
        _TYPES.pop("t_echart", None)


# -- the saved card ------------------------------------------------------------------


def test_a_card_gets_a_key_from_its_name_and_is_checked_like_a_cell(metric):
    card = _card()
    assert card.key == "requests_by_method" and card.options["dimension"] == "method"
    with pytest.raises(ValidationError, match="type"):
        _card(name="x", type="sparkle")
    with pytest.raises(ValidationError, match="no metric"):
        _card(name="y", metric="ghost")
    with pytest.raises(ValidationError, match="dimension"):
        _card(name="z", options={})
    assert _card(name="Note", type="text", metric="cb_requests", options={"markdown": "hi"}).metric == ""


def test_a_shared_card_cant_draw_a_personal_metric(staff):
    Metric(key="mine", name="Mine", dataset=DS, owner=staff).save()
    with pytest.raises(ValidationError, match="personal metric"):
        _card(name="Shared", type="metric", metric="mine", options={})
    assert _card(name="Personal", type="metric", metric="mine", options={}, owner=staff).owner == staff


# -- placing it, and keeping placements in step ----------------------------------------


def test_a_placement_takes_its_design_from_the_card(metric):
    card = _card()
    layout, problems = normalize_layout([{"component": card.key, "w": 6}])
    assert problems == []
    cell = layout[0]
    assert (cell["type"], cell["metric"], cell["options"]["dimension"]) == ("metric_group", "cb_requests", "method")
    assert cell["component"] == card.key and cell_title(cell) == "Requests by method"
    # A placement may retitle it, but not redesign it.
    layout, _ = normalize_layout([{"component": card.key, "title": "By method", "type": "metric", "metric": "x"}])
    assert cell_title(layout[0]) == "By method" and layout[0]["type"] == "metric_group"


def test_a_placement_needs_a_card_the_dashboard_may_use(metric, staff):
    _, problems = normalize_layout([{"component": "ghost"}])
    assert problems == ["layout[0].component: no saved card 'ghost'"]
    _card(name="Theirs", owner=staff)
    _, problems = normalize_layout([{"component": "theirs"}], owner_id=None)
    assert "a personal card" in problems[0]


def test_editing_a_card_updates_every_dashboard_and_deleting_it_leaves_a_plain_card(metric):
    card = _card()
    board = Dashboard(name="Ops", slug="ops", layout=[{"component": card.key, "w": 6}])
    board.save()
    card.name = "Traffic by method"
    card.options = {"dimension": "status_code", "limit": 3}
    card.save()
    board.refresh_from_db()
    assert (
        board.layout[0]["options"]["dimension"] == "status_code" and cell_title(board.layout[0]) == "Traffic by method"
    )
    card.delete()
    board.refresh_from_db()
    assert "component" not in board.layout[0] and board.layout[0]["title"] == "Traffic by method"
    assert board.layout[0]["type"] == "metric_group"  # still a working card


# -- the builder, the preview, and the agent surfaces ----------------------------------


def test_the_builder_page(client, staff, metric):
    html = client.get("/smallstack/dashboards/components/new/").content.decode()
    data = json.loads(html.split('id="cb-data" type="application/json">', 1)[1].split("</script>", 1)[0])
    assert [g["group"] for g in data["palette"]][:3] == ["Stats", "Info", "Charts"]
    assert {"key": "cb_requests", "name": "Requests", "dataset": DS, "shared": True}.items() <= data["metrics"][
        0
    ].items()
    assert "date" in data["metrics"][0]["caps"] and data["reasons"]["date"] == "needs a date column"
    assert '<input type="hidden" name="options"' in html and "dash-json" not in html
    assert 'value="trend"' in html  # an app's chart type is in the palette with no builder changes


def test_the_builder_saves_a_card(client, staff, metric):
    response = client.post(
        "/smallstack/dashboards/components/new/",
        {
            "name": "Requests by method",
            "description": "",
            "type": "metric_group",
            "metric": "cb_requests",
            "options": json.dumps({"dimension": "method", "limit": 4}),
            "visibility": "shared",
        },
    )
    assert response.status_code == 302, response.content.decode()[:1500]
    card = Component.objects.get()
    assert (card.key, card.options["limit"], card.created_by) == ("requests_by_method", 4, staff)


def test_the_preview_renders_the_card_and_explains_problems(client, staff, metric):
    ok = client.post(
        "/smallstack/dashboards/api/card-preview/",
        data=json.dumps(
            {"type": "metric_group", "metric": "cb_requests", "options": {"dimension": "method"}, "name": "By method"}
        ),
        content_type="application/json",
    ).json()
    assert ok["problems"] == [] and "By method" in ok["html"]
    bad = client.post(
        "/smallstack/dashboards/api/card-preview/",
        data=json.dumps({"type": "metric_group", "metric": "cb_requests"}),
        content_type="application/json",
    ).json()
    assert bad["html"] == "" and any("dimension" in p for p in bad["problems"])


def test_agents_build_and_place_cards(staff, metric):
    from apps.dashboards.tests.test_dashboards import _call

    preview = _call("card_preview", {"type": "metric", "metric": "cb_requests", "name": "Requests"}, staff)
    assert preview["problems"] == [] and "Requests" in preview["html"]
    _call(
        "create_component",
        {"name": "Total requests", "type": "metric", "metric": "cb_requests", "visibility": "shared"},
        staff,
    )
    assert Component.objects.filter(key="total_requests").exists()
    Dashboard(name="Agent", slug="agent").save()
    added = _call("dashboard_add_card", {"dashboard": "agent", "component": "total_requests"}, staff)
    assert added["ok"] and added["cell"]["component"] == "total_requests" and added["cell"]["type"] == "metric"
    assert "error" in _call("dashboard_add_card", {"dashboard": "agent", "component": "ghost"}, staff)


def test_the_dashboard_editor_offers_saved_cards(client, staff, metric):
    _card()
    board = Dashboard(name="Ops", slug="ops")
    board.save()
    html = client.get("/smallstack/dashboards/d/ops/").content.decode()
    editor = json.loads(html.split('id="dash-editor-data" type="application/json">', 1)[1].split("</script>", 1)[0])
    assert editor["components"] == [{"key": "requests_by_method", "name": "Requests by method", "type": "metric_group"}]
    assert 'id="dash-add-component"' in html


def test_the_components_list(client, staff, metric):
    card = _card()
    Dashboard(name="Ops", slug="ops", layout=[{"component": card.key}]).save()
    html = client.get("/smallstack/dashboards/components/?display=library").content.decode()
    assert "Requests by method" in html and "1 dashboard<" in html and "Grouped stat" in html


def test_the_components_list_is_a_sortable_resizable_table(client, staff, metric):
    _card(name="Bravo", type="metric", options={})
    _card(name="Alpha", type="text", metric="", options={"markdown": "hi"})
    _card(name="Charlie")  # a grouped stat
    html = client.get("/smallstack/dashboards/components/?display=library").content.decode()
    assert 'class="crud-table cl-table" data-table-key="dashboards/components:' in html
    assert html.count('class="col-resizer"') == 5 and 'hx-target="#crud-list-content"' in html

    def order(query: str) -> list[str]:
        page = client.get(f"/smallstack/dashboards/components/?display=library&{query}").content.decode()
        return sorted(("Alpha", "Bravo", "Charlie"), key=lambda n: page.index(f'class="cl-name">{n}<'))

    assert order("ordering=name") == ["Alpha", "Bravo", "Charlie"]
    assert order("ordering=-name") == ["Charlie", "Bravo", "Alpha"]
    assert order("ordering=type") == ["Bravo", "Charlie", "Alpha"]  # metric, metric_group, text
    assert order("ordering=-metric")[-1] == "Alpha"  # the note has no metric


def test_the_builder_designs_a_drilldown_in_a_dialog_beside_its_rows(client, staff, metric):
    html = client.get("/smallstack/dashboards/components/new/").content.decode()
    # Every column in one list (ticked ones on top), not added one at a time.
    assert 'id="cb-drill-add"' not in html and 'id="cb-drill-add-field"' not in html
    form, dialog = html.split('<dialog class="cbd" id="cb-drill-dialog"', 1)
    dialog = dialog.split("</dialog>", 1)[0]
    assert "</form>" in form  # outside the form: Enter in a heading never saves the card
    assert 'aria-labelledby="cb-drill-title"' in dialog and 'id="cb-drill-title"' in dialog
    for part in ("cbd-shown", "cbd-hidden", "cbd-find", "cbd-preview", "cb-drill-sort", "cb-drill-limit"):
        assert f'id="{part}"' in dialog, part
    assert 'id="cb-drill-cancel"' in dialog and 'id="cb-drill-done"' in dialog
    # The form keeps the design in short, and the way back into the dialog.
    assert 'id="cb-drill-chips"' in form and 'id="cb-drill-edit"' in form
    # The rows beside the list are the real ones: the JSON rows route, given the design.
    assert 'data-rows-url="/smallstack/dashboards/api/metrics/KEY/rows/"' in form
