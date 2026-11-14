"""The dashboard starter page: a page of your own over the dashboards' template tags,
drawing the trend card ``apps/website/dashboard_cards.py`` registers."""

from __future__ import annotations

import pytest

from apps.website.tests.test_dashboard_cards import _board, metric, staff  # noqa: F401 — fixtures

pytestmark = [pytest.mark.django_db, pytest.mark.starter_content]


def test_dashboard_starter_page_embeds_a_dashboard(client, staff, metric):  # noqa: F811
    board = _board({})
    board.owner = None
    board.save()
    html = client.get("/starter/dashboard/").content.decode()
    assert 'class="dash-embed"' in html and "/smallstack/dashboards/d/wc-trends/cells/t/" in html
    assert 'metric_card "wc_req" period="mtd"' in html


def test_dashboard_starter_page_needs_a_login(client):
    assert client.get("/starter/dashboard/").status_code == 302
