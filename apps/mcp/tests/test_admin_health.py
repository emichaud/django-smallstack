"""MCPAdminHealthView tests."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()


def _staff():
    u = User.objects.create_user(username="health_admin", password="x", is_staff=True)
    return u


def test_anonymous_redirects_to_login():
    resp = Client().get(reverse("mcp_admin:health"), HTTP_HOST="localhost")
    assert resp.status_code in (301, 302)


def test_non_staff_user_is_forbidden():
    u = User.objects.create_user(username="ordinary", password="x", is_staff=False)
    c = Client()
    c.force_login(u)
    resp = c.get(reverse("mcp_admin:health"), HTTP_HOST="localhost")
    assert resp.status_code == 403


def test_staff_renders_with_report_context():
    c = Client()
    c.force_login(_staff())
    resp = c.get(reverse("mcp_admin:health"), HTTP_HOST="localhost")
    assert resp.status_code == 200
    # Context exposes the report list + summary counts.
    assert "report" in resp.context
    assert isinstance(resp.context["report"], list)
    assert len(resp.context["report"]) >= 5  # mcp pkg, settings, registry, urls, tokens, admin
    assert resp.context["pass_count"] + resp.context["warn_count"] + resp.context["fail_count"] == len(
        resp.context["report"]
    )


def test_staff_html_contains_known_check_names():
    c = Client()
    c.force_login(_staff())
    resp = c.get(reverse("mcp_admin:health"), HTTP_HOST="localhost")
    body = resp.content.decode()
    # Several check names should appear regardless of registry state.
    for needle in ("mcp package", "Settings", "Server registry", "URL conf"):
        assert needle in body, f"expected {needle!r} in Health HTML"


def test_self_test_button_form_present():
    c = Client()
    c.force_login(_staff())
    resp = c.get(reverse("mcp_admin:health"), HTTP_HOST="localhost")
    body = resp.content.decode()
    assert "Run self-test now" in body
    assert reverse("mcp_admin:self_test") in body
