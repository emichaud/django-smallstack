"""``/smallstack/`` as a dashboard: the system dashboard of published widgets.

Apps keep publishing cards the way they always have (``dashboard.register`` or
``explorer_dashboard_widgets``); the page is now a ``Dashboard`` row
(``system_key="smallstack"``) that staff can rearrange, and each newly
published widget lands on it once.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.dashboards.boards import publishable_widgets, sync_widgets, system_dashboard
from apps.dashboards.components import _widget_key
from apps.dashboards.models import ADMIN_HOME_KEY, Dashboard
from apps.smallstack import dashboard as widget_registry
from apps.smallstack.displays import DashboardWidget

pytestmark = pytest.mark.django_db

User = get_user_model()


class PulseWidget(DashboardWidget):
    title = "Pulse"
    order = 1
    span = 2

    def get_data(self, model_class=None):
        return {"headline": "7 beats", "detail": "in the last minute"}


class QuietWidget(DashboardWidget):
    title = "Quiet"
    on_dashboard = False

    def get_data(self, model_class=None):
        return {"headline": "shh", "detail": ""}


PULSE = _widget_key(PulseWidget())
QUIET = _widget_key(QuietWidget())


@pytest.fixture
def widgets(monkeypatch):
    """A registry we can add to and take from without leaking into other tests."""
    registered = list(widget_registry._standalone_widgets)
    monkeypatch.setattr(widget_registry, "_standalone_widgets", registered)
    return registered


@pytest.fixture
def staff(client):
    user = User.objects.create_user("home-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def _home() -> Dashboard:
    return Dashboard.objects.get(system_key=ADMIN_HOME_KEY)


def _widget_keys(board: Dashboard) -> list[str]:
    return [c["options"]["widget"] for c in board.layout if c["type"] == "widget"]


def test_the_page_is_a_dashboard_of_every_published_widget(client, staff):
    html = client.get("/smallstack/").content.decode()
    board = _home()
    assert board.is_shared and board.get_absolute_url() == "/smallstack/"
    assert _widget_keys(board) == [k for k, _w in publishable_widgets()]  # in the widgets' own order
    assert set(board.offered_widgets) == set(_widget_keys(board))
    # Staff without accounts.view_user don't get the account cards (Access,
    # Users): the shared board leaves out what a viewer can't read (eval 45 T5-9).
    from apps.dashboards.components import widget_refused

    refused = [(c.get("options") or {}).get("widget", "") for c in board.layout if widget_refused(c, staff)]
    assert refused and all("Access" in k or "Users" in k for k in refused), refused
    assert html.count('class="grid-stack-item"') == len(board.layout) - len(refused) > 0
    assert 'id="dash-edit"' in html and "Edit layout" in html
    assert "<h1>Dashboard</h1>" in html


def test_a_widget_card_renders_through_the_cell_endpoint(client, staff, widgets):
    widgets.append(PulseWidget())
    client.get("/smallstack/")
    board = _home()
    cell = next(c for c in board.layout if c["type"] == "widget" and c["options"]["widget"] == PULSE)
    body = client.get(f"/smallstack/dashboards/d/{board.slug}/cells/{cell['id']}/").content.decode()
    assert "7 beats" in body and "in the last minute" in body


def test_new_widgets_are_placed_once_and_a_removed_card_stays_removed(client, staff, widgets):
    client.get("/smallstack/")
    before = len(_home().layout)

    widgets.append(PulseWidget())
    widgets.append(QuietWidget())
    client.get("/smallstack/")
    board = _home()
    pulse = [c for c in board.layout if c["options"].get("widget") == PULSE]
    assert len(pulse) == 1 and pulse[0]["w"] == 6  # span 2 → six of twelve columns
    assert QUIET not in _widget_keys(board)  # on_dashboard=False: offered in Add card only
    assert len(board.layout) == before + 1

    board.layout = [c for c in board.layout if c["options"].get("widget") != PULSE]
    board.save()
    client.get("/smallstack/")
    assert PULSE not in _widget_keys(_home())


def test_a_widget_whose_app_goes_away_leaves_and_comes_back(client, staff, widgets):
    pulse = PulseWidget()
    widgets.append(pulse)
    client.get("/smallstack/")
    assert PULSE in _widget_keys(_home())

    widgets.remove(pulse)  # the app was disabled
    client.get("/smallstack/")
    assert PULSE not in _widget_keys(_home()) and PULSE not in _home().offered_widgets

    widgets.append(pulse)  # and enabled again
    client.get("/smallstack/")
    assert PULSE in _widget_keys(_home())


def test_new_cards_fill_rows_below_the_existing_ones(monkeypatch):
    mine = [type(f"W{i}", (PulseWidget,), {"span": 1, "order": i})() for i in range(5)]
    found: list = []
    monkeypatch.setattr("apps.dashboards.components.available_widgets", lambda: list(found))
    board = system_dashboard("t-rows", name="Rows")
    board.layout = [{"type": "text", "x": 0, "y": 0, "w": 12, "h": 1, "options": {"markdown": "Top"}}]
    board.save()
    found.extend((_widget_key(w), w, None) for w in mine)
    sync_widgets(board)
    board.refresh_from_db()
    placed = [(c["x"], c["y"], c["w"]) for c in board.layout if c["type"] == "widget"]
    assert placed == [(0, 1, 3), (3, 1, 3), (6, 1, 3), (9, 1, 3), (0, 3, 3)]


def test_sync_is_a_no_op_when_nothing_changed(staff, client, django_assert_max_num_queries):
    client.get("/smallstack/")
    board = _home()
    with django_assert_max_num_queries(0):
        assert sync_widgets(board) == []


def test_staff_only(client):
    member = User.objects.create_user("home-member", password="x")
    system_dashboard(ADMIN_HOME_KEY, name="SmallStack")
    board = _home()
    client.force_login(member)
    assert client.get("/smallstack/").status_code in (302, 403)
    assert client.get(f"/smallstack/dashboards/d/{board.slug}/").status_code == 404
    assert 'class="ix-board" href="/smallstack/"' not in client.get("/smallstack/dashboards/").content.decode()
    assert client.get(f"/smallstack/api/dashboards/boards/{board.pk}/").status_code == 404


def test_it_cant_be_deleted_or_made_personal(client, staff):
    client.get("/smallstack/")
    board = _home()
    assert (
        f"/smallstack/dashboards/boards/{board.pk}/delete/"
        not in client.get("/smallstack/dashboards/boards/").content.decode()
    )
    client.post(f"/smallstack/dashboards/boards/{board.pk}/delete/")
    assert client.delete(f"/smallstack/api/dashboards/boards/{board.pk}/").status_code in (403, 404)
    assert Dashboard.objects.filter(pk=board.pk).exists()

    response = client.post(
        f"/smallstack/dashboards/boards/{board.pk}/edit/",
        {
            "name": "Ops home",
            "slug": board.slug,
            "description": "",
            "cover_alt": "",
            "default_period": "",
            "refresh_seconds": "",
            "layout": json.dumps(board.layout),
            "visibility": "personal",
        },
    )
    assert response.status_code == 302
    board.refresh_from_db()
    assert board.name == "Ops home" and board.owner_id is None


def test_the_period_bar_shows_only_when_a_card_reads_a_period(client, staff):
    from apps.dashboards.models import Metric

    html = client.get("/smallstack/").content.decode()
    assert 'aria-label="Period"' not in html  # widgets don't read one

    Metric(key="home_m", name="Home metric", dataset="smallstack_requests").save()
    board = _home()
    board.layout = [*board.layout, {"type": "metric", "metric": "home_m", "x": 0, "y": 99, "w": 3, "h": 2}]
    board.save()
    assert 'aria-label="Period"' in client.get("/smallstack/").content.decode()


def test_without_the_dashboards_page_the_fixed_grid_still_renders(client, staff):
    page = widget_registry.get_dashboard_page()
    widget_registry.set_dashboard_page(None)
    try:
        html = client.get("/smallstack/").content.decode()
    finally:
        widget_registry.set_dashboard_page(page)
    assert "dashboard-widget-grid" in html and "grid-stack" not in html
    assert not Dashboard.objects.filter(system_key=ADMIN_HOME_KEY).exists()
