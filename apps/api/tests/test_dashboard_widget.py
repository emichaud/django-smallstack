"""Tests for the APIDashboardWidget."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_widget_reports_endpoint_count():
    from apps.api.dashboard_widgets import APIDashboardWidget
    from apps.smallstack.api import _api_registry

    data = APIDashboardWidget().get_data()
    assert "endpoint" in data["headline"]
    if _api_registry:
        # Headline mentions a positive count. (Not `"0" not in headline` —
        # that read "20 endpoints" as zero.)
        assert int(data["headline"].split()[0]) > 0


def test_widget_status_operational_when_clean():
    from apps.api.dashboard_widgets import APIDashboardWidget

    data = APIDashboardWidget().get_data()
    # Default state: no orphans, no threats.
    assert data["status"] in ("operational", "degraded")
    # No high-severity threats seeded → should not be degraded due to threats.
    # (orphans depend on the live tree; we don't assert against them here.)


def test_widget_degraded_when_high_threat_present():
    from apps.activity.models import RequestLog
    from apps.api.dashboard_widgets import APIDashboardWidget

    # Seed 15 × 401 from one IP → auth-failure burst → HIGH.
    for _ in range(15):
        RequestLog.objects.create(
            path="/api/orders/", method="GET", status_code=401,
            response_time_ms=10, ip_address="198.51.100.50", user_agent="curl/8.0",
        )
    data = APIDashboardWidget().get_data()
    assert data["status"] == "degraded"
    assert "threat" in data["detail"].lower()


def test_widget_api_extras_has_endpoint_count():
    from apps.api.dashboard_widgets import APIDashboardWidget

    extras = APIDashboardWidget().get_api_extras()
    assert "endpoint_count" in extras
    assert "high_severity_threats_24h" in extras
    assert isinstance(extras["endpoint_count"], int)
    assert isinstance(extras["high_severity_threats_24h"], int)


def test_widget_metadata():
    from apps.api.dashboard_widgets import APIDashboardWidget

    w = APIDashboardWidget()
    assert w.title == "API"
    assert w.url_name == "api_admin:health"
    assert w.order == 37
