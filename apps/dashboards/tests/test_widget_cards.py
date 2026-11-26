"""A widget's own card body (template_name, media, default_size), and the
widget pickers listing the project's widgets apart from SmallStack's."""

from __future__ import annotations

import copy

import pytest
from django.contrib.auth import get_user_model

from apps.dashboards.boards import sync_widgets, system_dashboard
from apps.dashboards.components import (
    APP_WIDGETS,
    SYSTEM_WIDGETS,
    _widget_key,
    component_media,
    is_framework_widget,
    widget_choices,
)
from apps.dashboards.models import ADMIN_HOME_KEY, Dashboard
from apps.smallstack import dashboard as widget_registry
from apps.smallstack.displays import DashboardWidget, widget_size

pytestmark = pytest.mark.django_db

User = get_user_model()


class LeadersWidget(DashboardWidget):
    title = "Leaders"
    template_name = "widget_test/leaders.html"
    media = {"css": ["widget_test/leaders.css"], "js": ["widget_test/leaders.js"]}
    default_size = (4, 5)
    on_dashboard = False

    def get_data(self, model_class=None):
        return {"headline": "1,098", "detail": "Top three", "rows": [("Gibbs", "1,098"), ("Cook", "1,060")]}


class BrokenWidget(DashboardWidget):
    title = "Broken"
    template_name = "widget_test/broken.html"

    def get_data(self, model_class=None):
        return {"headline": "1"}


class PlainWidget(DashboardWidget):
    title = "Plain"

    def get_data(self, model_class=None):
        return {"headline": "7 beats", "detail": "in the last minute"}


# Widgets defined here live in apps.dashboards (a framework app); the project's
# own are told apart by module, so give one a project module.
class ProjectWidget(PlainWidget):
    title = "Project"


ProjectWidget.__module__ = "apps.website.dashboard_widgets"


@pytest.fixture
def templates(settings, tmp_path):
    folder = tmp_path / "widget_test"
    folder.mkdir()
    (folder / "leaders.html").write_text(
        '<ol class="leaders">{% for name, value in data.rows %}<li>{{ name }} {{ value }}</li>{% endfor %}</ol>'
        "<p>{{ widget.title }}</p>"
        '<a href="/people/gibbs/">Gibbs</a>'
    )
    (folder / "broken.html").write_text("{% load no_such_library %}")
    engines = copy.deepcopy(settings.TEMPLATES)
    engines[0]["DIRS"] = [*engines[0].get("DIRS", []), str(tmp_path)]
    settings.TEMPLATES = engines


@pytest.fixture
def widgets(monkeypatch):
    registered = list(widget_registry._standalone_widgets)
    monkeypatch.setattr(widget_registry, "_standalone_widgets", registered)
    return registered


@pytest.fixture
def staff(client):
    user = User.objects.create_user("widget-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def _cell(client, widget_cls):
    key = _widget_key(widget_cls())
    board = Dashboard.objects.create(
        slug="w",
        name="W",
        layout=[{"id": "c", "type": "widget", "x": 0, "y": 0, "w": 4, "h": 4, "options": {"widget": key}}],
    )
    return client.get(f"/smallstack/dashboards/d/{board.slug}/cells/c/").content.decode()


def test_a_widget_brings_its_own_body_inside_the_standard_frame(client, staff, widgets, templates):
    widgets.append(LeadersWidget())
    html = _cell(client, LeadersWidget)
    assert 'class="dashboard-widget' in html and '<div class="widget-body">' in html
    assert "<li>Gibbs 1,098</li>" in html and "<p>Leaders</p>" in html
    assert "widget-headline" not in html  # the body replaces the headline and detail


def test_links_in_a_body_are_not_nested_inside_the_cards_link(client, staff, widgets, templates):
    widgets.append(LeadersWidget())
    html = _cell(client, LeadersWidget)
    # The frame is a div; the title is the card's link, and the body's own link stands apart.
    assert '<div class="dashboard-widget dashboard-widget--custom' in html
    assert '<a class="widget-title widget-link" href="' in html and "Leaders</a>" in html
    assert '<a href="/people/gibbs/">Gibbs</a>' in html
    before = html.split('<a href="/people/gibbs/">', 1)[0]
    assert before.count("<a ") == before.count("</a>")  # no link is still open around it


def test_a_plain_widget_is_still_one_link(client, staff, widgets):
    widgets.append(PlainWidget())
    html = _cell(client, PlainWidget)
    assert 'class="dashboard-widget"' in html and "dashboard-widget--custom" not in html
    assert "widget-link" not in html


def test_media_defaults_to_none_so_no_widget_shares_a_dict():
    assert DashboardWidget.media is None and PlainWidget().media is None


def test_a_plain_widget_keeps_the_headline_and_detail(client, staff, widgets):
    widgets.append(PlainWidget())
    html = _cell(client, PlainWidget)
    assert "7 beats" in html and "in the last minute" in html and "widget-body" not in html


def test_a_body_that_fails_says_so_and_the_page_carries_on(client, staff, widgets, templates):
    widgets.append(BrokenWidget())
    html = _cell(client, BrokenWidget)
    assert "This widget failed to load." in html and 'class="dashboard-widget' in html


def test_the_fallback_grid_renders_the_body_too(client, staff, widgets, templates):
    leaders = LeadersWidget()
    leaders.on_dashboard = True
    widgets.append(leaders)
    page = widget_registry.get_dashboard_page()
    widget_registry.set_dashboard_page(None)
    try:
        html = client.get("/smallstack/").content.decode()
    finally:
        widget_registry.set_dashboard_page(page)
    assert "<li>Gibbs 1,098</li>" in html


def test_widget_media_loads_with_the_card_types(widgets):
    widgets.append(LeadersWidget())
    media = component_media()
    assert "widget_test/leaders.css" in media["css"] and "widget_test/leaders.js" in media["js"]


def test_default_size_is_held_to_the_grid():
    assert widget_size(LeadersWidget()) == (4, 5)
    assert widget_size(PlainWidget()) == (3, 2)
    wide = PlainWidget()
    wide.span = 2
    assert widget_size(wide) == (6, 2)
    huge = PlainWidget()
    huge.default_size = (40, 0)
    assert widget_size(huge) == (12, 1)


def test_the_smallstack_board_places_a_widget_at_its_size(widgets, templates):
    sized = LeadersWidget()
    sized.on_dashboard = True
    board = system_dashboard(ADMIN_HOME_KEY, name="SmallStack", description="")
    widgets.append(sized)
    sync_widgets(board)
    board.refresh_from_db()
    cell = next(c for c in board.layout if c["options"].get("widget") == _widget_key(sized))
    assert (cell["w"], cell["h"]) == (4, 5)


def test_pickers_list_the_projects_widgets_before_smallstacks(widgets):
    widgets.append(ProjectWidget())
    assert is_framework_widget(PlainWidget()) and not is_framework_widget(ProjectWidget())
    choices = widget_choices()
    groups = [c["group"] for c in choices]
    assert set(groups) == {APP_WIDGETS, SYSTEM_WIDGETS}
    assert groups == sorted(groups, key=lambda g: g != APP_WIDGETS)  # the project's first (a downstream may add more)
    project = next(c for c in choices if c["title"] == "Project")
    assert project["group"] == APP_WIDGETS and project["size"] == {"w": 3, "h": 2}


def test_one_kind_of_widget_needs_no_headings(monkeypatch):
    from apps.dashboards import components

    framework_only = [item for item in components.available_widgets() if is_framework_widget(item[1])]
    monkeypatch.setattr(components, "available_widgets", lambda: framework_only)
    assert {c["group"] for c in widget_choices()} == {""}


def test_the_add_card_dialog_gets_grouped_widgets(client, staff, widgets):
    widgets.append(ProjectWidget())
    html = client.get("/smallstack/").content.decode()
    assert APP_WIDGETS in html and SYSTEM_WIDGETS in html
