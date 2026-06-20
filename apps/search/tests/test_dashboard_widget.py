"""SearchDashboardWidget — shape + status flips."""

from __future__ import annotations

import pytest

from apps.search.dashboard_widgets import SearchDashboardWidget

pytestmark = pytest.mark.django_db


def test_widget_metadata():
    w = SearchDashboardWidget()
    assert w.title == "Search"
    assert w.url_name == "search:page"
    assert w.order == 33


def test_get_data_returns_required_keys():
    w = SearchDashboardWidget()
    data = w.get_data()
    assert {"headline", "detail", "status"} <= set(data)


def test_api_extras_shape():
    w = SearchDashboardWidget()
    extras = w.get_api_extras()
    assert "indexed_model_count" in extras
    assert "backend" in extras
    assert isinstance(extras["models"], list)
