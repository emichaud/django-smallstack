"""View tests for the activity drilldowns: user detail, resources, probes, the window.

The pre-existing page tests live in test_pages.py; these cover what the 2026-10
rework added — the window selector threading through tabs, the per-user and
per-resource pages, the Probes tab and banner, the middleware's route stamp,
and the dashboard regression where the request count was shadowed to 1.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from .middleware import ActivityMiddleware
from .models import RequestLog

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="staff", password="pw", is_staff=True)
    client.login(username="staff", password="pw")
    return user


@pytest.fixture
def member():
    return User.objects.create_user(username="member", email="m@example.com", password="pw")


def _log(path, *, route="", status=200, user=None, ip="10.0.0.1", ua="Mozilla/5.0", ms=10):
    return RequestLog.objects.create(
        path=path,
        route=route,
        method="GET",
        status_code=status,
        user=user,
        ip_address=ip,
        user_agent=ua,
        response_time_ms=ms,
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def test_middleware_stamps_the_matched_route(client, staff):
    client.get(reverse("activity:user_detail", args=[staff.pk]))
    row = RequestLog.objects.filter(path=f"/smallstack/activity/users/{staff.pk}/").get()
    assert row.route == "/smallstack/activity/users/<int:pk>/"
    assert row.resource_key == row.route


def test_middleware_leaves_route_empty_for_unmatched_paths(client):
    client.get("/wp-login.php")
    row = RequestLog.objects.get(path="/wp-login.php")
    assert row.status_code == 404
    assert row.route == ""
    assert row.resource_key == "/wp-login.php"


def test_route_helper_handles_root_and_missing_match(rf):
    request = rf.get("/")
    assert ActivityMiddleware._route(request) == ""
    request.resolver_match = type("M", (), {"route": ""})()
    assert ActivityMiddleware._route(request) == "/"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_total_is_not_shadowed_by_theme_loop(client, staff, member):
    """Regression: the theme-usage loop reused `total` and the card showed 1."""
    for _ in range(7):
        _log("/", user=member)
    resp = client.get(reverse("activity:dashboard"))
    assert resp.context["total_requests"] == 7
    assert resp.context["summary"].total == 7
    assert "7 requests in the last 7 days" in resp.content.decode()


def test_dashboard_window_scopes_everything(client, staff):
    _log("/a/")
    resp = client.get(reverse("activity:dashboard") + "?window=1h")
    assert resp.context["window"].key == "1h"
    assert resp.context["total_requests"] == 1
    html = resp.content.decode()
    assert 'href="?window=24h"' in html  # the picker keeps the page, swaps the window
    assert "/smallstack/activity/resources/?window=1h" in html


def test_stat_detail_reads_window_from_hx_current_url(client, staff):
    _log("/recent/")
    resp = client.get(
        reverse("activity:stat_detail", args=["requests"]),
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL="http://testserver/smallstack/activity/?window=1h",
    )
    assert resp.status_code == 200
    assert "/recent/" in resp.content.decode()
    resp = client.get(reverse("activity:stat_detail", args=["active_users"]), HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    resp = client.get(reverse("activity:stat_detail", args=["probes"]), HTTP_HX_REQUEST="true")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Requests page
# ---------------------------------------------------------------------------


def test_requests_tabs_carry_the_window(client, staff):
    _log("/x/", status=404)
    resp = client.get(reverse("activity:requests") + "?window=24h&tab=errors")
    html = resp.content.decode()
    assert resp.context["active_tab"] == "errors"
    assert "?tab=probes&window=24h" in html
    assert 'name="window" value="24h"' in html  # the filter bar keeps it too


def test_requests_filters(client, staff, member):
    _log("/api/a/", status=404, ip="10.9.9.9")
    _log("/api/b/", status=200, user=member)
    _log("/web/", status=404)
    base = reverse("activity:requests") + "?window=all&tab=recent"
    assert client.get(base + "&status=4xx").context["page_obj"].total_count == 2
    assert client.get(base + "&q=api").context["page_obj"].total_count == 2
    assert client.get(base + "&ip=10.9.9.9").context["page_obj"].total_count == 1
    assert client.get(base + "&anon=1&status=404").context["page_obj"].total_count == 2
    assert client.get(base + "&path=/web/").context["page_obj"].total_count == 1


def test_probes_tab_and_banner(client, staff):
    for p in ("/wp-login.php", "/.env", "/.git/config"):
        _log(p, status=404, ip="203.0.113.3", ua="masscan/1.0")
    _log("/", status=200)
    resp = client.get(reverse("activity:requests") + "?window=24h")
    html = resp.content.decode()
    assert resp.context["probe_banner"].any
    assert "Probing &amp; noise" in html
    assert "203.0.113.3" in html
    assert "scanner user agent" in html
    resp = client.get(reverse("activity:requests") + "?window=24h&tab=probes")
    assert resp.context["active_tab"] == "probes"
    assert resp.context["probe_requests"].total_count == 3
    assert 'class="probe-flag"' in resp.content.decode()


def test_probes_quiet_state(client, staff):
    _log("/", status=200)
    resp = client.get(reverse("activity:requests") + "?window=24h")
    assert not resp.context["probe_banner"].any
    assert "No probing detected" in resp.content.decode()


def test_recent_rows_link_into_drilldowns(client, staff, member):
    _log("/things/5/", route="/things/<int:pk>/", user=member, ip="10.4.4.4")
    html = client.get(reverse("activity:requests") + "?window=all").content.decode()
    assert f"/smallstack/activity/users/{member.pk}/?window=all" in html
    assert "/smallstack/activity/resources/detail/?r=/things/%3Cint%3Apk%3E/&window=all" in html
    assert "ip=10.4.4.4" in html


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def test_users_page_links_to_user_detail_and_has_new_tabs(client, staff, member):
    _log("/a/", user=member)
    resp = client.get(reverse("activity:users") + "?window=all")
    html = resp.content.decode()
    assert resp.context["active_user_count"] == 1
    assert f"/smallstack/activity/users/{member.pk}/?window=all" in html
    for tab in ("preferences", "inactive", "signups"):
        assert f"?tab={tab}&window=all" in html
    resp = client.get(reverse("activity:users") + "?tab=preferences", HTTP_HX_REQUEST="true")
    assert "Theme usage" in resp.content.decode()


def test_inactive_means_no_request_and_no_login_in_window(client, staff, member):
    active = User.objects.create_user("active", password="pw")
    _log("/a/", user=active)
    resp = client.get(reverse("activity:users") + "?tab=inactive&window=7d")
    names = {u.username for u in resp.context["inactive_users"]}
    assert "member" in names and "active" not in names
    # staff just logged in → not inactive even without a logged request
    assert "staff" not in names


def test_user_detail_page(client, staff, member):
    _log("/things/1/", route="/things/<int:pk>/", user=member, ip="10.7.7.7", ua="Mozilla/5.0 (X11)")
    _log("/things/2/", route="/things/<int:pk>/", user=member, status=500)
    _log("/other/", route="/other/", user=staff)
    resp = client.get(reverse("activity:user_detail", args=[member.pk]) + "?window=all")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert resp.context["summary"].total == 2
    assert resp.context["summary"].c5xx == 1
    assert resp.context["top_resources"][0]["resource"] == "/things/<int:pk>/"
    assert "10.7.7.7" in html and "member" in html
    assert reverse("manage/users-update", args=[member.pk]) in html
    # tabs
    detail = reverse("activity:user_detail", args=[member.pk])
    resp = client.get(detail + "?window=all&tab=errors", HTTP_HX_REQUEST="true")
    assert resp.context["page_obj"].total_count == 1
    resp = client.get(detail + "?window=all&tab=resources", HTTP_HX_REQUEST="true")
    assert resp.context["resources"].total_count == 1
    assert 'data-field="user__username"' not in resp.content.decode()  # own page: no User column


def test_user_detail_404_and_staff_only(client, member):
    client.login(username="member", password="pw")
    assert client.get(reverse("activity:user_detail", args=[member.pk])).status_code == 403
    client.logout()
    User.objects.create_user("s2", password="pw", is_staff=True)
    client.login(username="s2", password="pw")
    assert client.get(reverse("activity:user_detail", args=[999999])).status_code == 404


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def test_resources_page_groups_and_filters(client, staff, member):
    for pk in (1, 2, 3):
        _log(f"/things/{pk}/", route="/things/<int:pk>/", user=member)
    _log("/nope/", status=404)
    base = reverse("activity:resources") + "?window=all"
    resp = client.get(base)
    rows = {r["resource"]: r for r in resp.context["resources"]}
    assert rows["/things/<int:pk>/"]["hits"] == 3 and rows["/things/<int:pk>/"]["users"] == 1
    assert rows["/nope/"]["resolved"] == 0
    assert resp.context["route_count"] == 1 and resp.context["unmatched_count"] == 1
    # The test client's own page loads are logged too (they resolve to activity routes),
    # so narrow with q= when counting routes.
    assert client.get(base + "&kind=unmatched").context["resources"].total_count == 1
    assert client.get(base + "&kind=routes&q=things").context["resources"].total_count == 1
    assert client.get(base + "&kind=unmatched&q=things").context["resources"].total_count == 0
    assert client.get(base + "&q=thing").context["resources"].total_count == 1
    html = resp.content.decode()
    assert "r=/things/%3Cint%3Apk%3E/" in html


def test_resource_detail_page(client, staff, member):
    _log("/things/1/", route="/things/<int:pk>/", user=member, ms=5)
    _log("/things/2/", route="/things/<int:pk>/", ms=900)
    url = reverse("activity:resource_detail") + "?r=%2Fthings%2F%3Cint%3Apk%3E%2F&window=all"
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["is_route"] is True
    assert resp.context["summary"].total == 2 and resp.context["summary"].users == 1
    assert resp.context["top_users"][0]["user__username"] == "member"
    html = resp.content.decode()
    assert "/things/1/" in html  # sample paths
    assert "tab=slowest&window=all&r=%2Fthings%2F%3Cint%3Apk%3E%2F" in html
    resp = client.get(url + "&tab=slowest", HTTP_HX_REQUEST="true")
    assert resp.context["rows"][0].response_time_ms == 900
    resp = client.get(url + "&tab=users", HTTP_HX_REQUEST="true")
    assert resp.context["top_users"].total_count == 1


def test_resource_detail_unmatched_path_and_missing_key(client, staff):
    _log("/wp-login.php", status=404)
    resp = client.get(reverse("activity:resource_detail") + "?r=%2Fwp-login.php&window=all")
    assert resp.status_code == 200
    assert resp.context["is_route"] is False
    assert "unmatched path" in resp.content.decode()
    assert client.get(reverse("activity:resource_detail")).status_code == 404


def test_sidebar_registers_activity_children():
    from apps.smallstack.navigation import nav

    labels = {item.label for item in nav._items if getattr(item, "parent", None) == "Activity"}
    assert labels == {"Requests", "Users", "Resources"}
