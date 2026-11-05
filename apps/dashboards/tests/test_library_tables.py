"""The metrics, dashboards and reports lists are crud-tables: their stored
columns sort through the CRUD list's ``?ordering=`` ({% sortable_th %}), and
every column resizes with the framework's table-resize.js."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.dashboards.models import Dashboard, Metric, Report

pytestmark = pytest.mark.django_db
DS = "smallstack_requests"
NAMES = ("Alpha", "Bravo", "Charlie")


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("lt-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def rows():
    for name, ds in (("Bravo", DS), ("Alpha", "smallstack_heartbeats"), ("Charlie", "smallstack_api_tokens")):
        Metric(key=name.lower(), name=name, dataset=ds).save()
        Dashboard(name=name, slug=name.lower()).save()
        Report(name=name, slug=name.lower(), items=[{"metric": name.lower()}]).save()


def _order(client, url: str) -> list[str]:
    html = client.get(url).content.decode()
    return sorted(NAMES, key=lambda n: html.index(f'class="lib-name">{n}<'))


@pytest.mark.parametrize(
    ("path", "table", "resizers"),
    [("metrics", "ml-table", 5), ("boards", "bl-table", 5), ("reports", "rl-table", 4)],
)
def test_each_list_is_a_sortable_resizable_table(client, staff, rows, path, table, resizers):
    url = f"/smallstack/dashboards/{path}/"
    html = client.get(url).content.decode()
    assert f'class="crud-table lib-table {table}" data-table-key="dashboards/' in html
    assert html.count('class="col-resizer"') == resizers  # every column but the actions
    assert 'hx-target="#crud-list-content"' in html and "ordering=name" in html
    assert _order(client, url + "?ordering=name") == ["Alpha", "Bravo", "Charlie"]
    assert _order(client, url + "?ordering=-name") == ["Charlie", "Bravo", "Alpha"]
    assert 'aria-sort="descending"' in client.get(url + "?ordering=-name").content.decode()


def test_metrics_sort_by_their_data_and_the_period_bar_keeps_it(client, staff, rows):
    url = "/smallstack/dashboards/metrics/"
    # smallstack_api_tokens < smallstack_heartbeats < smallstack_requests
    assert _order(client, url + "?ordering=dataset") == ["Charlie", "Alpha", "Bravo"]
    html = client.get(url + "?ordering=dataset").content.decode()
    assert "ordering=dataset&amp;period=today" in html  # a period link keeps the sort
    sorted_by_period = client.get(url + "?period=today").content.decode()
    assert "period=today" in sorted_by_period.split('data-field="name"', 1)[1].split("</th>", 1)[0]  # and vice versa


def test_the_overview_says_where_each_metric_is_used(client, staff):
    from apps.dashboards.models import GoalList, usage_index

    for key in ("drawn", "listed", "idle"):
        Metric(key=key, name=key.title(), dataset="smallstack_requests").save()
    Dashboard(
        name="Board",
        slug="board",
        layout=[{"type": "metric", "metric": "drawn"}, {"type": "metric", "metric": "drawn"}],
    ).save()
    Report(name="Rep", slug="rep", items=[{"metric": "drawn"}, {"metric": "listed"}]).save()
    goals = [{"metric": "drawn", "target": {"op": ">=", "value": 1}}]
    GoalList(name="Goals", slug="goals", sections=[{"title": "", "goals": goals}]).save()
    index = usage_index(staff)
    assert index["drawn"] == {"boards": 1, "reports": 1, "goal_lists": 1, "components": 0, "rates": 0, "total": 3}
    assert index["listed"]["total"] == 1 and "idle" not in index
    resp = client.get("/smallstack/goals/")
    html = resp.content.decode()
    rows = {r["metric"].key: r for r in resp.context["metric_rows"]}
    assert rows["drawn"]["used_in"] == "1 board, 1 report, 1 goal list"
    assert rows["listed"]["used_in"] == "1 report" and rows["idle"]["used_in"] == ""
    assert '<span class="ix-unused">Not used</span>' in html and "1 used nowhere" in html
    # Most used first, then only the unused.
    resp = client.get("/smallstack/goals/?metrics=-used")
    assert [r["metric"].key for r in resp.context["metric_rows"]][:2] == ["drawn", "listed"]
    resp = client.get("/smallstack/goals/?unused=1")
    assert [r["metric"].key for r in resp.context["metric_rows"]] == ["idle"]
    assert "1 used nowhere, values for" in resp.content.decode() and "Show every metric" in resp.content.decode()
