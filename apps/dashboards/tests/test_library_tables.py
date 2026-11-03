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
