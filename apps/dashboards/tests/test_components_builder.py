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
from apps.dashboards.tests.support import own, own_post

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
    # A split filters a dataset of its own; a card given a metric (or a dataset) keeps that.
    source = {} if "metric" in kw or "dataset" in kw else own("cb_requests")
    c = Component(
        **{
            "name": "Requests by method",
            "type": "metric_group",
            **source,
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
        # cards.js first: it fires dashboards:card-drawn and holds the option-editor
        # registry, so a type's own script can register before the builder runs.
        assert html.index('src="/static/dashboards/js/cards.js" defer') < html.index("echarts.min.js")
    finally:
        _TYPES.pop("t_echart", None)


def test_every_surface_that_shows_cards_loads_their_files(client, staff, metric):
    """A scripted card mounts where its HTML lands: the components page (gallery
    and table) now loads card files in its head like a dashboard does, rather
    than styles alone in the swapped block."""
    _card()
    for url in (
        "/smallstack/dashboards/components/",
        "/smallstack/dashboards/components/?display=library",
        "/smallstack/dashboards/components/new/",
    ):
        html = client.get(url).content.decode()
        assert html.count('src="/static/dashboards/js/cards.js"') == 1, url
        link = '<link rel="stylesheet" href="/static/website/css/dashboard-cards.css">'
        assert html.count(link) == 1, url  # the app's chart styles, once
    swapped = client.get("/smallstack/dashboards/components/", HTTP_HX_REQUEST="true").content.decode()
    assert "cards.js" not in swapped  # the in-place swap brings no scripts


# -- the saved card ------------------------------------------------------------------


def test_a_card_gets_a_key_from_its_name_and_is_checked_like_a_cell(metric):
    card = _card()
    assert card.key == "requests_by_method" and card.options["dimension"] == "method"
    with pytest.raises(ValidationError, match="type"):
        _card(name="x", type="sparkle")
    with pytest.raises(ValidationError, match="no metric"):
        _card(name="y", type="metric", metric="ghost")
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
    assert (cell["type"], cell["dataset"], cell["options"]["dimension"]) == ("metric_group", DS, "method")
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
    assert data["reasons"]["date"] == "needs a date column"
    assert data["metrics"][0]["edit_url"].endswith("/edit/")  # staff may edit a shared metric
    assert '<input type="hidden" name="options"' in html and "dash-json" not in html
    assert 'value="trend"' in html  # an app's chart type is in the palette with no builder changes


def test_the_builder_says_where_a_period_field_is_set(client, staff, metric):
    """A metric with no period field can't be drawn over time, however many date
    columns its dataset has. The builder dims the trend chart for it and the page
    carries the note that points at the metric's form, since the card has no
    such field."""

    def payload():
        html = client.get("/smallstack/dashboards/components/new/").content.decode()
        return html, json.loads(html.split('id="cb-data" type="application/json">', 1)[1].split("</script>", 1)[0])

    html, data = payload()  # the fixture's metric has no period field
    assert "date" not in data["metrics"][0]["caps"] and data["metrics"][0]["no_period"] is True
    assert 'id="cb-metric-period" hidden' in html and "Set one in the metric's settings" in html
    Metric.objects.filter(key="cb_requests").update(period_field="timestamp")
    html, data = payload()
    assert "date" in data["metrics"][0]["caps"] and data["metrics"][0]["no_period"] is False


def test_the_builder_saves_a_card(client, staff, metric):
    response = client.post(
        "/smallstack/dashboards/components/new/",
        {
            "name": "Requests by method",
            "description": "",
            "type": "metric_group",
            **own_post("cb_requests"),
            "options": json.dumps({"dimension": "method", "limit": 4}),
            "visibility": "shared",
        },
    )
    assert response.status_code == 302, response.content.decode()[:1500]
    card = Component.objects.get()
    assert (card.key, card.options["limit"], card.created_by) == ("requests_by_method", 4, staff)
    assert (card.metric, card.dataset, card.agg) == ("", DS, "count")


def test_a_split_or_a_chart_filters_a_dataset_of_its_own(client, staff, metric):
    """The rule: a metric is one number, so only a single-value design may draw
    one; a grouped stat or a chart carries its own dataset and filter. The
    builder refuses the other way round, saying so, and a card's own source is
    checked as a metric is (the dataset must exist, the columns be real)."""
    bad = client.post(
        "/smallstack/dashboards/components/new/",
        {"name": "By method", "type": "metric_group", "metric": "cb_requests", "options": '{"dimension": "method"}'},
    ).content.decode()
    assert "a Grouped stat card filters a dataset of its own" in bad
    bad = client.post(
        "/smallstack/dashboards/components/new/",
        {"name": "By method", "type": "metric_group", "dataset": DS, "agg": "sum", "measure": "nope", "options": "{}"},
    ).content.decode()
    assert "not a column of this dataset" in bad
    # A single stat may draw a metric, or a dataset of its own; it can't have both.
    with_both = Component(name="Both", type="metric", metric="cb_requests", **own("cb_requests"))
    with_both.save()
    assert with_both.metric == "cb_requests" and with_both.dataset == ""
    own_stat = Component(name="Mine", type="metric", **own("cb_requests"), options={"style": {"unit": "req"}})
    own_stat.save()
    assert own_stat.as_cell()["dataset"] == DS and "metric" not in own_stat.as_cell()
    with pytest.raises(ValidationError, match="needs a source"):
        Component(name="Nothing", type="metric").save()
    # A note draws nothing: a saved card drops either, a layout refuses it.
    assert Component(name="Note", type="text", dataset=DS, options={"markdown": "x"}).as_cell().get("dataset") == DS
    _, problems = normalize_layout([{"type": "text", "dataset": DS, "options": {"markdown": "x"}}])
    assert any("draws no data, so it takes no dataset" in p for p in problems)


def test_a_card_with_its_own_source_draws_and_opens_its_rows(client, staff, metric):
    """Placed on a dashboard, a card with its own source renders through the
    same build as one over a metric, formats itself from its style, and opens
    its rows by its place on the dashboard (it has no metric page)."""
    board = Dashboard(
        name="Own",
        slug="own",
        layout=[
            {"id": "s", "type": "metric", **own("cb_requests"), "options": {"style": {"unit": "req"}}, "title": "Hits"},
            {"id": "g", "type": "metric_group", **own("cb_requests"), "options": {"dimension": "method"}},
        ],
    )
    board.save()
    stat = client.get("/smallstack/dashboards/d/own/cells/s/").content.decode()
    assert "Hits" in stat and "req" in stat and "/smallstack/dashboards/d/own/cards/s/rows/" in stat
    group = client.get("/smallstack/dashboards/d/own/cells/g/").content.decode()
    rows_url = "/smallstack/dashboards/d/own/cards/g/rows/"
    assert f"{rows_url}?narrow=" in group and 'class="dash-cell-title">Requests<' in group
    rows = client.get(rows_url, {"narrow": '{"field": "method", "op": "=", "value": "GET"}'})
    html = rows.content.decode()
    assert rows.status_code == 200 and "Narrowed to" in html and "Open the metric" not in html
    assert client.get(rows_url, {"format": "csv"})["Content-Disposition"].endswith('"card-rows.csv"')
    assert client.get("/smallstack/dashboards/d/own/cards/nope/rows/").status_code == 404
    values = client.get("/smallstack/dashboards/api/boards/own/values/").json()["cells"]
    assert values[0]["dataset"] == DS and values[0]["result"]["display"]


def test_the_preview_renders_the_card_and_explains_problems(client, staff, metric):
    ok = client.post(
        "/smallstack/dashboards/api/card-preview/",
        data=json.dumps(
            {"type": "metric_group", **own("cb_requests"), "options": {"dimension": "method"}, "name": "By method"}
        ),
        content_type="application/json",
    ).json()
    assert ok["problems"] == [] and "By method" in ok["html"]
    # Its rows open through the preview route: the builder posts the definition.
    stat = client.post(
        "/smallstack/dashboards/api/card-preview/",
        data=json.dumps({"type": "metric", **own("cb_requests"), "name": "Hits"}),
        content_type="application/json",
    ).json()
    assert "/smallstack/dashboards/preview-rows/" in stat["html"]
    bad = client.post(
        "/smallstack/dashboards/api/card-preview/",
        data=json.dumps({"type": "metric_group", **own("cb_requests")}),
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


def test_the_components_list_narrows_by_dashboard_dataset_and_design(client, staff, metric):
    """A library of hundreds is found by where its numbers come from and where
    it's shown: a dataset (the card's own, or its metric's), a design, a
    dashboard — three dropdowns of the page's own, and the same params on REST."""
    by_method = _card(name="By method")
    stat = _card(name="Requests stat", type="metric", metric=metric.key, options={})
    Metric(key="cb_logs", name="Log lines", dataset="smallstack_log_records").save()
    logs = _card(name="Log lines", type="metric", metric="cb_logs", options={})
    Dashboard(
        name="Ops", slug="ops", layout=[{"component": by_method.key}, {"type": "metric", "metric": metric.key}]
    ).save()
    Dashboard(name="Quiet", slug="quiet", layout=[]).save()
    url = "/smallstack/dashboards/components/?display=library"

    html = " ".join(client.get(url).content.decode().split())
    assert (
        '<select name="dashboard"' in html and '<option value="ops"> Ops <' in html and '<option value="quiet"' in html
    )
    assert '<select name="dataset"' in html and "> Requests </option>" in html and "> Log records </option>" in html
    assert '<select name="type"' in html and "> Grouped stat </option>" in html and "> Single stat </option>" in html
    assert "> Trend chart </option>" not in html  # a design none of the cards use isn't offered

    def names(query: str) -> set[str]:
        page = client.get(f"{url}&{query}").content.decode()
        return {n for n in ("By method", "Requests stat", "Log lines") if f'class="cl-name">{n}<' in page}

    assert names("dashboard=ops") == {"By method"}  # the metric placed directly isn't a saved card
    assert names("dashboard=quiet") == set() and names("dashboard=nope") == set()
    assert names("dataset=smallstack_requests") == {"By method", "Requests stat"}  # its own, or its metric's
    assert names("dataset=smallstack_log_records") == {"Log lines"}
    assert names("type=metric") == {"Requests stat", "Log lines"}
    assert names("type=metric&dataset=smallstack_requests") == {"Requests stat"}

    page = client.get(f"{url}&dashboard=ops").content.decode()
    assert "The 1 saved card on" in page and 'href="/smallstack/dashboards/d/ops/"' in page and "All components" in page
    page = client.get(f"{url}&dashboard=quiet").content.decode()
    assert "No saved cards on" in page and "No components" not in page
    assert (
        'href="/smallstack/dashboards/components/?dashboard=ops"'
        in client.get("/smallstack/dashboards/d/ops/").content.decode()
    )

    # REST: the same three params.
    rows = client.get("/smallstack/api/dashboards/components/?dashboard=ops").json()["results"]
    assert [r["name"] for r in rows] == ["By method"]
    rows = client.get("/smallstack/api/dashboards/components/?dataset=smallstack_requests&type=metric").json()[
        "results"
    ]
    assert [r["name"] for r in rows] == ["Requests stat"]
    assert stat.pk and logs.pk


def test_the_components_list_is_a_sortable_resizable_table(client, staff, metric):
    _card(name="Bravo", type="metric", metric="cb_requests", options={})  # a single stat over the saved metric
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
    assert order("ordering=-metric")[0] == "Bravo"  # the only card over a metric
    assert 'Requests <span class="dash-muted">(filtered here)</span>' in html  # Charlie's source: its dataset


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


def test_a_menu_card_is_links_in_order_across_or_down(client, staff):
    """A way around, on the dashboard: links as given, a new window where
    asked, nothing that runs; the layout by choice or by the card's shape."""
    items = [
        {"label": "Runbook", "url": "/smallstack/runbook/"},
        {"label": "Status", "url": "https://status.example.com", "new_window": True},
        {"label": "Top", "url": "#top"},
    ]
    cell = {"id": "m", "type": "menu", "title": "Go to", "w": 3, "h": 3, "options": {"items": items}}
    Dashboard(name="Nav", slug="nav", layout=[cell]).save()
    html = client.get("/smallstack/dashboards/d/nav/cells/m/").content.decode()
    assert 'class="nav-card nav-card--auto" aria-label="Go to"' in html and html.count("<li>") == 3
    assert html.index(">Runbook<") < html.index(">Status<") < html.index(">Top<")
    assert '<a href="https://status.example.com" target="_blank" rel="noopener">' in html
    assert "opens in a new window" in html
    assert '<a href="/smallstack/runbook/"><span>Runbook</span></a>' in html  # the site's own page: plain
    d = Dashboard.objects.get(slug="nav")
    d.layout[0]["options"]["layout"] = "horizontal"
    d.save()
    html = client.get("/smallstack/dashboards/d/nav/cells/m/").content.decode()
    assert 'class="nav-card nav-card--horizontal"' in html
    for bad, reason in (
        ([], "required"),
        ([{"label": "x", "url": "javascript:alert(1)"}], "url must be"),
        ([{"label": "x", "url": "//evil.example.com"}], "url must be"),
        ([{"label": "", "url": "/a"}], "label"),
        ([{"label": "x", "url": "/a", "new_window": "yes"}], "new_window"),
        ([{"label": "x", "url": "/a", "icon": "star"}], "unknown key"),
    ):
        with pytest.raises(ValidationError, match=reason):
            Dashboard(name="Bad", slug="bad", layout=[{"type": "menu", "options": {"items": bad}}]).full_clean()
    with pytest.raises(ValidationError, match="layout"):
        bad_layout = {"type": "menu", "options": {"items": items, "layout": "diagonal"}}
        Dashboard(name="Bad", slug="bad", layout=[bad_layout]).full_clean()
    # A menu draws no data, so it takes no source — and the builder knows the links option.
    described = next(t for t in describe_types() if t["type"] == "menu")
    assert not described["needs_metric"] and [o["type"] for o in described["options"]] == ["links", "choice"]


def test_a_note_has_a_look_of_its_own(client, staff):
    """Size, alignment, text colour and a background, all as theme tokens; the
    background is off unless asked for."""
    Dashboard(name="N", slug="n", layout=[{"id": "t", "type": "text", "options": {"markdown": "**Hi**"}}]).save()
    html = client.get("/smallstack/dashboards/d/n/cells/t/").content.decode()
    assert 'class="dash-text tx-size-m tx-align-start tx-color-plain"' in html and "tx-background" not in html
    d = Dashboard.objects.get(slug="n")
    d.layout[0]["options"].update(size="xl", align="center", color="accent", background="band")
    d.save()
    html = client.get("/smallstack/dashboards/d/n/cells/t/").content.decode()
    assert 'class="dash-text tx-size-xl tx-align-center tx-color-accent tx-background-band"' in html
    for bad in ({"size": "huge"}, {"color": "#ff0000"}, {"background": "red"}, {"align": "justify"}):
        with pytest.raises(ValidationError, match=next(iter(bad))):
            Dashboard(name="B", slug="b", layout=[{"type": "text", "options": {"markdown": "x", **bad}}]).full_clean()
    described = next(t for t in describe_types() if t["type"] == "text")
    assert [o["name"] for o in described["options"]] == ["markdown", "size", "align", "color", "background"]


def test_the_palette_opens_full_for_a_new_card_and_compact_for_an_existing_one(client, staff, metric):
    """Full (each design with its description) when choosing; compact (a chip
    each, the description on hover) when editing, where the page is long
    enough already. The switch is on the page either way."""
    new = client.get("/smallstack/dashboards/components/new/").content.decode()
    assert 'id="cb-palette"' in new and 'data-default-view="full"' in new and 'id="cb-palette-mini"' in new
    card = _card()
    edit = client.get(f"/smallstack/dashboards/components/{card.pk}/edit/").content.decode()
    assert 'data-default-view="mini"' in edit
    assert 'class="cb-tile" data-type="pie" title="A count or total split by a column' in edit  # the chip's tooltip
    board = Dashboard(name="D", slug="d", layout=[{"id": "c1", "type": "text", "options": {"markdown": "x"}}])
    board.save()
    dialog = client.get("/smallstack/dashboards/d/d/cards/c1/edit/", HTTP_HX_REQUEST="true").content.decode()
    assert 'data-default-view="mini"' in dialog  # editing in the dialog, too


def test_a_notes_colour_and_size_hold_on_the_dashboard(client, staff):
    """The dashboard draws a note flat and quiet by default; a colour the note
    chose must still win there, as it does in the builder's preview (the
    cell's wrapper class used to outrank it)."""
    Dashboard(
        name="N2", slug="n2",
        layout=[{"id": "t", "type": "text", "options": {"markdown": "## Hi", "size": "xl", "color": "success"}}],
    ).save()
    html = client.get("/smallstack/dashboards/d/n2/cells/t/").content.decode()
    assert 'class="dash-text tx-size-xl tx-align-start tx-color-success"' in html and "<h2>Hi</h2>" in html
    css = open("apps/dashboards/static/dashboards/css/dashboards.css").read()
    assert ".dash-cell--text .dash-text { padding: 0.4rem 0.25rem; }" in css  # no colour on the wrapper rule any more
    assert ".dash-text.tx-color-success { color: var(--success-fg); }" in css
