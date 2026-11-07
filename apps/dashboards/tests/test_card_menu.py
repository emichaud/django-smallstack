"""A dashboard page's controls (in its header), each card's menu, and Edit card:
the component builder for one card, in a dialog on the dashboard."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse

from apps.dashboards.models import Component, Dashboard, Metric
from apps.dashboards.tests.support import own_post

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff(client):
    user = User.objects.create_user("cm-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def board(staff):
    """A shared dashboard: a card of its own (c1), a placed saved card over the
    metric (c2: a single stat, the design that may draw one), a note (c3)."""
    Metric(key="cm_requests", name="Requests", dataset=DS).save()
    card = Component(name="By method", type="metric", metric="cm_requests", options={})
    card.save()
    d = Dashboard(
        name="Ops",
        slug="cm-ops",
        layout=[
            {"type": "metric", "metric": "cm_requests", "x": 0, "y": 0, "w": 3, "h": 2},
            {"component": card.key, "x": 3, "y": 0, "w": 5, "h": 2},
            {"type": "text", "x": 8, "y": 0, "w": 4, "h": 2, "options": {"markdown": "hello"}},
        ],
    )
    d.save()
    return d


def _edit_url(cell: str = "c1") -> str:
    return reverse("dashboards_card_edit", kwargs={"slug": "cm-ops", "cell_id": cell})


# -- the page: controls in the header, the cards below --------------------------------


def test_the_controls_are_in_the_header_and_only_the_period_stays_with_the_cards(client, staff, board):
    html = client.get("/smallstack/dashboards/d/cm-ops/").content.decode()
    header, cards = html.split('<div id="dash-page"', 1)
    for control in ('id="dash-refresh"', 'id="dash-updated"', 'id="dash-edit"', ">Settings<", ">Duplicate<"):
        assert control in header and control not in cards, control
    assert 'class="dash-header-actions"' in header
    assert 'aria-label="Period"' in cards and 'aria-label="Period"' not in header


def test_an_embedded_dashboard_has_cards_and_no_controls(staff, board):
    request = RequestFactory().get("/")
    request.user = staff
    html = Template('{% load dashboard_tags %}{% dashboard "cm-ops" %}').render(Context({"request": request}))
    assert 'class="dash-embed-grid"' in html and html.count("dash-embed-cell") == 3
    for control in ("dash-refresh", "dash-edit", "dash-cell-more", "dash-card-menu", "Settings"):
        assert control not in html, control


# -- each card's menu ------------------------------------------------------------------


def test_every_card_has_a_menu_whose_entries_follow_the_card(client, staff, board):
    html = client.get("/smallstack/dashboards/d/cm-ops/").content.decode()
    assert html.count('class="dash-cell-more"') == 3 and html.count('id="dash-card-menu"') == 1
    buttons = {b.split('"', 1)[0]: b.split(">", 1)[0] for b in html.split('data-cell-menu="')[1:]}
    assert f'data-edit-url="{_edit_url("c1")}"' in buttons["c1"]
    assert 'data-metric-url="/smallstack/dashboards/m/cm_requests/"' in buttons["c1"]
    assert 'aria-label="Actions for By method"' in buttons["c2"] and 'aria-haspopup="menu"' in buttons["c2"]
    assert "data-metric-url" not in buttons["c3"]  # a note draws no metric
    for action in ("edit", "arrange", "metric", "metric-edit", "refresh", "remove", "unique", "own-metric", "yes"):
        assert f'data-card-action="{action}"' in html, action
    assert 'id="dash-card-dialog"' in html and "component-builder.js" in html


def test_someone_who_cant_edit_gets_a_menu_without_the_edits(client, board):
    client.force_login(User.objects.create_user("cm-member", password="x"))
    html = client.get("/smallstack/dashboards/d/cm-ops/").content.decode()
    assert html.count('class="dash-cell-more"') == 3
    assert 'data-card-action="metric"' in html and 'data-card-action="refresh"' in html
    for missing in ('data-card-action="edit"', 'data-card-action="remove"', "data-edit-url", 'id="dash-card-dialog"'):
        assert missing not in html, missing
    for missing in ('data-card-action="unique"', "data-copy-url", "dash-cell-linked", "data-metric-edit-url"):
        assert missing not in html, missing
    assert "component-builder.js" not in html and 'id="dash-edit"' not in html


def test_a_saved_card_is_edited_in_place_only_by_someone_who_may_edit_the_card(client, board):
    owner = User.objects.create_user("cm-owner", password="x")
    Dashboard(name="Mine", slug="cm-mine", owner=owner, layout=[{"component": "by_method", "x": 0, "y": 0}]).save()
    client.force_login(owner)
    html = client.get("/smallstack/dashboards/d/cm-mine/").content.decode()
    assert 'data-card-action="remove"' in html and "data-edit-url" not in html  # their dashboard, staff's card
    assert client.get(reverse("dashboards_card_edit", kwargs={"slug": "cm-mine", "cell_id": "c1"})).status_code == 403


# -- Edit card ------------------------------------------------------------------------


def test_a_card_of_the_dashboard_opens_in_the_builder_with_a_title_only(client, staff, board):
    html = client.get(_edit_url("c1")).content.decode()
    assert "<html" not in html and f'action="{_edit_url("c1")}"' in html and 'id="cb-data"' in html
    assert 'value="metric" checked' in html and '<option value="cm_requests" data-shared="1" selected>' in html
    assert "Title it" in html and '<input type="hidden" name="visibility" value="shared">' in html
    assert 'type="radio" name="visibility"' not in html and 'name="tags"' not in html
    assert 'id="cb-frame" inert' in html and "data-card-cancel" in html  # a tap in the preview opens nothing


def test_saving_it_rewrites_that_card_in_the_layout_and_nothing_else(client, staff, board):
    options = json.dumps({"dimension": "method"})
    posted = {"type": "metric_group", **own_post("cm_requests"), "options": options, "name": "Split"}
    response = client.post(_edit_url("c1"), posted)
    assert response.status_code == 200 and response.json() == {"ok": True}
    board.refresh_from_db()
    c1, c2, c3 = board.layout
    assert (c1["type"], c1["dataset"], c1["title"]) == ("metric_group", DS, "Split")
    assert "metric" not in c1 and c1["agg"] == "count"  # the split's source is its own
    assert c1["options"]["dimension"] == "method"
    assert (c1["id"], c1["x"], c1["w"], c1["h"]) == ("c1", 0, 3, 2)  # it keeps its place and size
    assert c2["component"] == "by_method" and c3["options"] == {"markdown": "hello"}
    assert Component.objects.count() == 1  # no saved card was made of it
    # A blank title goes back to the metric's name.
    client.post(_edit_url("c1"), {**posted, "name": ""})
    board.refresh_from_db()
    assert "title" not in board.layout[0]


def test_a_card_the_layout_wouldnt_take_comes_back_with_what_was_wrong(client, staff, board):
    posted = {"type": "metric_group", **own_post("cm_requests"), "options": "{}", "name": "Split"}
    response = client.post(_edit_url("c1"), posted)
    html = response.content.decode()
    assert response.status_code == 422 and "(the column to group by) is required" in html
    assert 'class="crud-form-errors" role="alert"' in html and "layout[" not in html  # no "layout[0]." in front
    assert 'value="metric_group" checked' in html and 'value="Split"' in html  # what was typed is still there
    board.refresh_from_db()
    assert board.layout[0]["type"] == "metric"
    assert client.post(_edit_url("c1"), {**posted, "type": "nope"}).status_code == 422


def test_a_saved_card_opens_as_itself_and_saving_reaches_every_dashboard(client, staff, board):
    Dashboard(name="Second", slug="cm-second", layout=[{"component": "by_method", "x": 0, "y": 0}]).save()
    html = client.get(_edit_url("c2")).content.decode()
    assert "Name it" in html and 'type="radio" name="visibility"' in html and "On 2 dashboards" in html
    posted = {
        "name": "By verb",
        "type": "metric_group",
        **own_post("cm_requests"),
        "options": json.dumps({"dimension": "method", "limit": 3}),
        "visibility": "shared",
        "description": "",
        "tags": "",
    }
    assert client.post(_edit_url("c2"), posted).json() == {"ok": True}
    card = Component.objects.get(key="by_method")
    assert card.name == "By verb" and card.options["limit"] == 3
    assert (card.type, card.metric, card.dataset) == ("metric_group", "", DS)  # now a split, with its own source
    for slug, at in (("cm-ops", 1), ("cm-second", 0)):
        cell = Dashboard.objects.get(slug=slug).layout[at]
        assert cell["name"] == "By verb" and cell["options"]["limit"] == 3
    bad = client.post(_edit_url("c2"), {**posted, "name": ""})
    assert bad.status_code == 422 and "This field is required" in bad.content.decode()


def test_only_someone_who_can_edit_the_dashboard_reaches_a_cards_editor(client, staff, board):
    assert client.get(_edit_url("c9")).status_code == 404
    client.force_login(User.objects.create_user("cm-reader", password="x"))
    assert client.get(_edit_url("c1")).status_code == 403
    assert client.post(_edit_url("c1"), {"type": "text", "options": "{}"}).status_code == 403
    client.logout()
    assert client.get(_edit_url("c1")).status_code == 302


# -- a card other dashboards show too: marked, and a way to make this one unique -------


def _copy_url(slug: str = "cm-ops", cell: str = "c2") -> str:
    return reverse("dashboards_card_copy", kwargs={"slug": slug, "cell_id": cell})


def _buttons(html: str) -> dict[str, str]:
    return {b.split('"', 1)[0]: b.split(">", 1)[0] for b in html.split('data-cell-menu="')[1:]}


def test_a_saved_card_on_one_dashboard_isnt_marked_and_a_card_of_the_dashboard_can_own_its_metric(client, staff, board):
    html = client.get("/smallstack/dashboards/d/cm-ops/").content.decode()
    buttons = _buttons(html)
    assert "dash-cell-linked" not in html and "dash-cell--linked" not in html
    assert "data-copy-url" not in buttons["c2"]  # nobody else shows it: nothing to separate it from
    # c1 is this dashboard's own card over a metric others may draw: it can be given its own.
    assert f'data-copy-url="{_copy_url(cell="c1")}"' in buttons["c1"] and 'data-metric-name="Requests"' in buttons["c1"]
    assert "data-saved-name" not in buttons["c1"] and "data-copy-url" not in buttons["c3"]
    assert 'data-metric-edit-url="/smallstack/dashboards/metrics/' in buttons["c1"]


def test_a_saved_card_shown_elsewhere_is_marked_and_offers_a_unique_copy(client, staff, board):
    Dashboard(name="Second", slug="cm-second", layout=[{"component": "by_method", "x": 0, "y": 0}]).save()
    Dashboard(name="Third", slug="cm-third", layout=[{"component": "by_method", "x": 0, "y": 0}]).save()
    html = client.get("/smallstack/dashboards/d/cm-ops/").content.decode()
    assert html.count('class="dash-cell-linked"') == 1 and html.count("dash-cell--linked") == 1
    assert "shown on 3 dashboards" in html and "3<span" in html
    c2 = _buttons(html)["c2"]
    assert f'data-copy-url="{_copy_url()}"' in c2
    assert 'data-saved-name="By method" data-saved-count="3"' in c2 and 'data-metric-name="Requests"' in c2


def test_a_unique_copy_keeps_the_design_and_stops_following_the_saved_card(client, staff, board):
    Dashboard(name="Second", slug="cm-second", layout=[{"component": "by_method", "x": 0, "y": 0}]).save()
    assert client.post(_copy_url()).json() == {"ok": True, "metric": ""}
    board.refresh_from_db()
    cell = board.layout[1]
    assert "component" not in cell and "name" not in cell
    assert (cell["type"], cell["metric"], cell["title"]) == ("metric", "cm_requests", "By method")
    assert (cell["id"], cell["x"], cell["w"]) == ("c2", 3, 5)
    # The saved card goes on, for the dashboard still showing it, and this one no longer listens.
    card = Component.objects.get(key="by_method")
    card.options = {"style": {"unit": "req"}}
    card.save()
    board.refresh_from_db()
    assert "style" not in board.layout[1]["options"]
    assert Dashboard.objects.get(slug="cm-second").layout[0]["options"]["style"]["unit"] == "req"
    html = client.get("/smallstack/dashboards/d/cm-ops/").content.decode()
    assert "dash-cell-linked" not in html and f'data-edit-url="{_edit_url("c2")}"' in html


def test_copying_the_metric_too_lets_its_filter_change_here_alone(client, staff, board):
    original = Metric.objects.get(key="cm_requests")
    original.filter_tree = {"and": [{"field": "method", "op": "=", "value": "GET"}]}
    original.thresholds = [{"op": ">=", "value": 5, "state": "warning"}]
    original.save()
    Dashboard(name="Second", slug="cm-second", layout=[{"component": "by_method", "x": 0, "y": 0}]).save()
    made = client.post(_copy_url(), {"metric": "1"}).json()
    assert made["ok"] and made["metric"] == "requests_ops"
    copy = Metric.objects.get(key="requests_ops")
    # Named after the dashboard, and shared like it.
    assert copy.name == "Requests (Ops)" and copy.owner_id is None and copy.created_by == staff
    assert (copy.dataset, copy.filter_tree, copy.thresholds) == (DS, original.filter_tree, original.thresholds)
    board.refresh_from_db()
    assert board.layout[1]["metric"] == "requests_ops" and board.layout[0]["metric"] == "cm_requests"
    # Changing the copy's filter leaves the original as it was.
    copy.filter_tree = {"and": [{"field": "method", "op": "=", "value": "POST"}]}
    copy.save()
    assert Metric.objects.get(key="cm_requests").filter_tree["and"][0]["value"] == "GET"


def test_a_card_of_the_dashboard_can_be_given_its_own_metric(client, staff, board):
    made = client.post(_copy_url(cell="c1"), {"metric": "1"}).json()
    board.refresh_from_db()
    assert made["metric"] and board.layout[0]["metric"] == made["metric"] and board.layout[0]["type"] == "metric"
    assert Metric.objects.count() == 2


def test_a_metric_entered_by_hand_isnt_copied(client, staff, board):
    Metric(key="cm_csat", name="CSAT", source="manual").save()
    board.layout = [*board.layout, {"type": "metric", "metric": "cm_csat", "x": 0, "y": 2}]
    board.save()
    cell = board.layout[-1]["id"]
    html = client.get("/smallstack/dashboards/d/cm-ops/").content.decode()
    assert "data-copy-url" not in _buttons(html)[cell]  # its values are typed against that metric
    assert client.post(_copy_url(cell=cell), {"metric": "1"}).json() == {"ok": True, "metric": ""}
    assert Metric.objects.count() == 2


def test_only_someone_who_can_edit_the_dashboard_makes_a_copy(client, staff, board):
    assert client.post(_copy_url(cell="c9")).status_code == 404
    assert client.get(_copy_url()).status_code == 405
    client.force_login(User.objects.create_user("cm-reader2", password="x"))
    assert client.post(_copy_url(), {"metric": "1"}).status_code == 403
    assert Metric.objects.count() == 1 and Dashboard.objects.get(slug="cm-ops").layout[1]["component"] == "by_method"
