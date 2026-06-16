"""MCPAdminSelfTestView tests — the htmx POST endpoint."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()


def _staff():
    return User.objects.create_user(username="selftest_admin", password="x", is_staff=True)


def test_get_method_not_allowed():
    c = Client()
    c.force_login(_staff())
    resp = c.get(reverse("mcp_admin:self_test"), HTTP_HOST="localhost")
    # http_method_names = ["post"] → Django returns 405 for GET.
    assert resp.status_code == 405


def test_anonymous_redirects():
    resp = Client().post(reverse("mcp_admin:self_test"), HTTP_HOST="localhost")
    # Anonymous hits the StaffRequiredMixin first → redirect to login (302).
    assert resp.status_code in (301, 302)


def test_non_staff_is_forbidden():
    u = User.objects.create_user(username="ordinary_st", password="x")
    c = Client()
    c.force_login(u)
    resp = c.post(reverse("mcp_admin:self_test"), HTTP_HOST="localhost")
    assert resp.status_code == 403


def test_staff_post_returns_fragment_and_cleans_up_token():
    from apps.smallstack.models import APIToken

    c = Client(enforce_csrf_checks=False)
    c.force_login(_staff())
    before = APIToken.objects.count()
    resp = c.post(reverse("mcp_admin:self_test"), HTTP_HOST="localhost")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Fragment template returns a panel with id="self-test-result".
    assert 'id="self-test-result"' in body
    assert "Self-test" in body
    # Temp APIToken minted by _self_test was deleted in the finally —
    # row count should be unchanged.
    assert APIToken.objects.count() == before
