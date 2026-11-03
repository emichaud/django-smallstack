"""People use the visual editors; agents write the JSON over REST/MCP.

The forms keep every field (they are the REST and MCP forms too), but the HTML
pages carry the JSON as hidden fields — no textarea to get wrong — and the
metric key is made from the name, then fixed.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.dashboards.models import Dashboard, Metric, metric_key_from_name

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff(client):
    user = User.objects.create_user("nj-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


def _metric_post(**extra) -> dict:
    data = {
        "name": "Open urgent tickets",
        "description": "",
        "dataset": DS,
        "filter_tree": "{}",
        "agg": "count",
        "measure": "",
        "period_field": "",
        "format": "number",
        "unit": "",
        "thresholds": "[]",
        "visibility": "shared",
    }
    data.update(extra)
    return data


def test_a_key_is_made_from_the_name():
    assert metric_key_from_name("Open urgent tickets") == "open_urgent_tickets"
    assert metric_key_from_name("Ünïcode & co.") == "unicode_co"
    assert metric_key_from_name("—") == "metric"
    Metric(key="open_urgent_tickets", name="x", dataset=DS).save()
    assert metric_key_from_name("Open urgent tickets") == "open_urgent_tickets_2"


def test_the_builder_saves_without_a_key_field(client, staff):
    response = client.post("/smallstack/dashboards/metrics/new/", _metric_post())
    assert response.status_code == 302, response.content.decode()[:2000]
    assert Metric.objects.get(name="Open urgent tickets").key == "open_urgent_tickets"


def test_the_key_never_changes(client, staff):
    m = Metric(key="kept", name="Kept", dataset=DS)
    m.save()
    # The edit page posts no key: it stays.
    client.post(f"/smallstack/dashboards/metrics/{m.pk}/edit/", _metric_post(name="Renamed"))
    m.refresh_from_db()
    assert (m.name, m.key) == ("Renamed", "kept")
    # The API says why instead of quietly breaking every reference.
    bad = client.patch(
        f"/smallstack/api/dashboards/metrics/{m.pk}/",
        data=json.dumps({"key": "other"}),
        content_type="application/json",
    )
    assert bad.status_code == 400 and "can't change" in json.dumps(bad.json())


def test_the_api_can_still_choose_a_key_or_leave_it_out(client, staff):
    made = client.post(
        "/smallstack/api/dashboards/metrics/",
        data=json.dumps({"name": "Error rate", "dataset": DS, "visibility": "shared"}),
        content_type="application/json",
    )
    assert made.status_code == 201 and made.json()["key"] == "error_rate"
    chosen = client.post(
        "/smallstack/api/dashboards/metrics/",
        data=json.dumps({"key": "errs", "name": "Errors", "dataset": DS, "visibility": "shared"}),
        content_type="application/json",
    )
    assert chosen.status_code == 201 and chosen.json()["key"] == "errs"


def test_saving_dashboard_settings_leaves_the_layout_alone(client, staff):
    layout = [{"id": "n", "type": "text", "x": 0, "y": 0, "w": 3, "h": 2, "options": {"markdown": "hi"}}]
    board = Dashboard(name="Ops", slug="ops", layout=layout)
    board.save()
    client.post(
        f"/smallstack/dashboards/boards/{board.pk}/edit/",
        {
            "name": "Ops renamed",
            "slug": "ops",
            "description": "",
            "cover_alt": "",
            "default_period": "",
            "refresh_seconds": "",
            "visibility": "shared",
        },
    )  # no layout field, as the page posts it
    board.refresh_from_db()
    assert board.name == "Ops renamed" and board.layout[0]["options"] == {"markdown": "hi"}


@pytest.mark.parametrize(
    ("url", "hidden"),
    [
        ("/smallstack/dashboards/metrics/new/", ["filter_tree", "thresholds"]),
        ("/smallstack/dashboards/reports/new/", ["items"]),
        ("/smallstack/dashboards/playlists/new/", ["items"]),
        ("/smallstack/dashboards/boards/new/", []),
    ],
)
def test_the_forms_show_no_json(client, staff, url, hidden):
    html = client.get(url).content.decode()
    assert "dash-json" not in html and "as JSON" not in html and '<textarea name="layout"' not in html
    for name in hidden:
        assert f'<input type="hidden" name="{name}"' in html
    assert 'name="key"' not in html and 'metric_card "</span>' not in html
