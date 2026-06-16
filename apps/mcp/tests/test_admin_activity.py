"""MCPAdminActivityView tests."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()


def _staff():
    return User.objects.create_user(username="activity_admin", password="x", is_staff=True)


def _log(method: str, path: str, status: int, **kwargs):
    from apps.activity.models import RequestLog

    return RequestLog.objects.create(
        method=method, path=path, status_code=status,
        response_time_ms=kwargs.get("ms", 5),
    )


def test_anonymous_redirects():
    resp = Client().get(reverse("mcp_admin:activity"), HTTP_HOST="localhost")
    assert resp.status_code in (301, 302)


def test_non_staff_is_forbidden():
    u = User.objects.create_user(username="ordinary_a", password="x")
    c = Client()
    c.force_login(u)
    resp = c.get(reverse("mcp_admin:activity"), HTTP_HOST="localhost")
    assert resp.status_code == 403


def test_only_mcp_paths_are_shown():
    _log("POST", "/mcp", 200)
    _log("GET", "/mcp/", 200)
    _log("GET", "/health/", 200)  # NOT /mcp — should be filtered out
    _log("POST", "/api/widgets/", 200)  # also irrelevant
    c = Client()
    c.force_login(_staff())
    resp = c.get(reverse("mcp_admin:activity") + "?since=all", HTTP_HOST="localhost")
    assert resp.status_code == 200
    paths = [r.path for r in resp.context["entries"]]
    assert "/mcp" in paths
    assert "/mcp/" in paths
    assert "/health/" not in paths
    assert "/api/widgets/" not in paths


def test_status_filter_narrows_results():
    _log("POST", "/mcp", 200)
    _log("POST", "/mcp", 401)
    _log("POST", "/mcp", 500)
    c = Client()
    c.force_login(_staff())
    resp = c.get(
        reverse("mcp_admin:activity") + "?since=all&status_class=4xx",
        HTTP_HOST="localhost",
    )
    statuses = {r.status_code for r in resp.context["entries"]}
    assert statuses == {401}


def test_method_filter_narrows_results():
    _log("POST", "/mcp", 200)
    _log("GET", "/mcp", 200)
    c = Client()
    c.force_login(_staff())
    resp = c.get(
        reverse("mcp_admin:activity") + "?since=all&method=GET",
        HTTP_HOST="localhost",
    )
    methods = {r.method for r in resp.context["entries"]}
    assert methods == {"GET"}


def test_user_filter_icontains_matches_username():
    bob = User.objects.create_user(username="bob_dev", password="x")
    other = User.objects.create_user(username="alice", password="x")
    _log("POST", "/mcp", 200).user = bob
    rl = _log("POST", "/mcp", 200)
    rl.user = bob
    rl.save()
    rl2 = _log("POST", "/mcp", 200)
    rl2.user = other
    rl2.save()
    c = Client()
    c.force_login(_staff())
    resp = c.get(
        reverse("mcp_admin:activity") + "?since=all&user=bob",
        HTTP_HOST="localhost",
    )
    users = {r.user.username for r in resp.context["entries"] if r.user}
    assert users == {"bob_dev"}


def test_filter_form_round_trips():
    c = Client()
    c.force_login(_staff())
    resp = c.get(
        reverse("mcp_admin:activity") + "?method=POST&status_class=4xx&since=7d&user=alice",
        HTTP_HOST="localhost",
    )
    current = resp.context["current"]
    assert current["method"] == "POST"
    assert current["status_class"] == "4xx"
    assert current["since"] == "7d"
    assert current["user"] == "alice"
