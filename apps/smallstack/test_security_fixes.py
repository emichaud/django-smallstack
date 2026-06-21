"""Regression tests for the v0.11.13 security audit batch (H1/H2/H3/H4/H5).

H1/H2/H3 live with their subsystems (apps/mcp/tests/test_oauth.py,
apps/smallstack/test_api.py). This module covers the two cross-cutting ones:
H4 (Postgres backup false-assurance) and H5 (health check bypasses Host
validation so ALLOWED_HOSTS=* isn't needed).
"""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()
pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# H5 — HealthCheckMiddleware answers /health/ before Host validation
# ---------------------------------------------------------------------------


def test_health_check_bypasses_host_validation():
    """A proxy/LB probe hits the container by IP, sending a Host not in
    ALLOWED_HOSTS. /health/ must still return 200 — that's what lets us drop
    the dangerous ALLOWED_HOSTS=* default."""
    client = Client()
    resp = client.get("/health/", HTTP_HOST="10.11.12.13:8000")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_middleware_is_scoped_to_health_path():
    """The bypass must apply ONLY to /health/ — other paths flow through the
    normal stack (so removing ALLOWED_HOSTS=* still protects the rest of the
    site, which validates Host whenever get_host() is reached)."""
    client = Client()
    resp = client.get("/", HTTP_HOST="testserver")  # allowed host, normal request
    # The middleware did not hijack a non-health path with the health payload.
    assert b'"database"' not in resp.content


# ---------------------------------------------------------------------------
# H4 — backups dashboard does not show green "Scheduled" on non-SQLite
# ---------------------------------------------------------------------------


def _staff(username="bkstaff"):
    return User.objects.create_user(username=username, password="p", is_staff=True)


def test_backups_page_warns_on_non_sqlite():
    """On a non-SQLite engine the page must warn that the built-in backup
    system does not protect the database (the bundled backup is SQLite-only),
    instead of showing a green 'Scheduled / Cron enabled' status."""
    client = Client()
    client.force_login(_staff())
    fake = {"engine": "postgresql", "is_sqlite": False, "db_path": "", "db_size": 0}
    with mock.patch("apps.smallstack.views._get_db_info", return_value=fake):
        resp = client.get(reverse("smallstack:backups"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "not protected by the built-in backup system" in body
    assert "Not Protected" in body  # the status card, not a green "Scheduled"


def test_backups_page_normal_on_sqlite():
    """On SQLite (the default), the false-assurance warning must NOT appear."""
    client = Client()
    client.force_login(_staff("bkstaff2"))
    resp = client.get(reverse("smallstack:backups"))
    assert resp.status_code == 200
    assert "not protected by the built-in backup system" not in resp.content.decode()
