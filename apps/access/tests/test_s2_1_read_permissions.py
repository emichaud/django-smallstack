"""S2-1: reading accounts, access and other accounts' tokens needs ``view_*``,
not just the staff flag (2026-11-14 access-control round).

Before the fix a staff account holding no permission at all read the whole
Access area (every account's permissions, the change log, the review), the
User Manager's list and pages, ``/api/auth/users/`` and every account's API
tokens, while Explorer and the datasets refused the same rows. The *Access
reviewer* group added nothing there.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()


def _perm(app_label, codename):
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _client(user):
    c = Client()
    c.force_login(user)
    return c


def _run_tool(name, args, *, user):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=user, token=None))
    try:
        return TOOL_HANDLERS[name](args)
    finally:
        reset_context(token)


@pytest.fixture
def olaf():
    """Staff with no permissions."""
    return User.objects.create_user("olaf", password="pw", email="olaf@acme.test", is_staff=True)


@pytest.fixture
def rita():
    """Staff in the shipped Access reviewer group."""
    user = User.objects.create_user("rita", password="pw", is_staff=True)
    user.groups.add(Group.objects.get(name="Access reviewer"))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def tara():
    """Staff in the shipped Token manager group."""
    user = User.objects.create_user("tara", password="pw", is_staff=True)
    user.groups.add(Group.objects.get(name="Token manager"))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def lee():
    return User.objects.create_user("lee", password="pw", email="lee@acme.test")


@pytest.fixture
def lees_token(lee):
    token, _ = APIToken.create_token(lee, name="lee-ci", token_type="manual", access_level="readonly")
    return token


ACCESS_PAGES = ["access:index", "access:users", "access:events", "access:groups", "access:events_csv",
                "access:matrix_csv", "access:snapshot_json"]


# --- The Access area -----------------------------------------------------------


@pytest.mark.parametrize("name", ACCESS_PAGES)
def test_s2_1_access_pages_refuse_staff_without_view_user(olaf, name):
    assert _client(olaf).get(reverse(name)).status_code == 403


def test_s2_1_access_user_page_refuses_staff_without_view_user(olaf, lee):
    assert _client(olaf).get(reverse("access:user_detail", args=[lee.pk])).status_code == 403


@pytest.mark.parametrize("name", ACCESS_PAGES)
def test_s2_1_access_reviewer_reads_the_access_pages(rita, name):
    assert _client(rita).get(reverse(name)).status_code == 200


@pytest.mark.parametrize("path", ["users/", "users/lee/", "users/lee/check/?perm=accounts.view_user",
                                  "groups/", "findings/", "events/"])
def test_s2_1_access_rest_reads_refuse_staff_without_view_user(olaf, rita, lee, path):
    url = f"/smallstack/api/access/{path}"
    resp = _client(olaf).get(url)
    assert resp.status_code == 403
    assert "accounts.view_user" in json.dumps(resp.json())
    assert _client(rita).get(url).status_code == 200


def test_s2_1_access_mcp_reads_refuse_staff_without_view_user(olaf, rita, lee):
    assert _run_tool("access_explain_user", {"username": "lee"}, user=olaf)["error"]["code"] == "forbidden"
    assert _run_tool("access_findings", {}, user=olaf)["error"]["code"] == "forbidden"
    check = _run_tool("access_check_permission", {"username": "lee", "permission": "accounts.view_user"}, user=olaf)
    assert check["error"]["code"] == "forbidden"
    assert _run_tool("access_explain_user", {"username": "lee"}, user=rita)["username"] == "lee"


def test_s2_1_dashboard_still_opens_and_drops_the_access_widget_and_links(olaf, rita):
    from apps.smallstack.dashboard import get_widget_contexts

    page = _client(olaf).get("/smallstack/")
    assert page.status_code == 200
    body = page.content.decode()
    assert reverse("access:index") not in body  # neither the sidebar link nor the widget
    # href=: the Timezones link (open to staff, E-dec 3) shares the prefix.
    assert f'href="{reverse("manage/users-list")}"' not in body
    assert "Access" not in [c["widget"].title for c in get_widget_contexts(user=olaf)]
    assert "Access" in [c["widget"].title for c in get_widget_contexts(user=rita)]
    assert reverse("access:index") in _client(rita).get("/smallstack/").content.decode()


# --- The User Manager and /api/auth/users/ ------------------------------------


# The Timezones dashboard is open to all staff again (E-dec 3); see
# apps/usermanager/tests/test_timezones_for_staff.py.
@pytest.mark.parametrize("name,args", [("manage/users-list", []), ("manage/users-stat-detail", ["total"])])
def test_s2_1_user_manager_lists_refuse_staff_without_view_user(olaf, rita, name, args):
    assert _client(olaf).get(reverse(name, args=args)).status_code == 403
    assert _client(rita).get(reverse(name, args=args)).status_code == 200


def test_s2_1_user_manager_page_refuses_staff_without_view_user(olaf, rita, lee):
    url = reverse("manage/users-update", args=[lee.pk])
    assert _client(olaf).get(url).status_code == 403
    assert _client(rita).get(url).status_code == 200


def test_s2_1_auth_users_api_reads_need_view_user(olaf, lee):
    _, raw = APIToken.create_token(olaf, name="auth", token_type="manual", access_level="auth")
    hdr = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    assert Client().get("/api/auth/users/", **hdr).status_code == 403
    assert Client().get(f"/api/auth/users/{lee.pk}/", **hdr).status_code == 403
    olaf.user_permissions.add(_perm("accounts", "view_user"))
    assert Client().get("/api/auth/users/", **hdr).status_code == 200


def test_s2_1_user_search_hits_need_view_user(olaf, rita, lee):
    from apps.search.backends import get_backend
    from apps.search.registry import all_views, search_all

    for view in all_views():
        get_backend().rebuild(view)

    def users_found(user):
        return [h.display for h in search_all("lee", user=user) if h.model_label.lower().endswith(".user")]

    assert "lee" not in users_found(olaf)
    assert "lee" in users_found(rita)


# --- The Token Manager ---------------------------------------------------------


def test_s2_1_token_list_shows_staff_only_their_own(olaf, tara, lees_token):
    own, _ = APIToken.create_token(olaf, name="olaf-own", token_type="manual", access_level="readonly")
    page = _client(olaf).get(reverse("tokenmgr:tokens-list")).content.decode()
    assert "olaf-own" in page
    assert "lee-ci" not in page
    assert "lee-ci" in _client(tara).get(reverse("tokenmgr:tokens-list")).content.decode()


def test_s2_1_token_detail_of_another_account_needs_view_apitoken(olaf, tara, lees_token):
    url = reverse("tokenmgr:tokens-detail", kwargs={"pk": lees_token.pk})
    assert _client(olaf).get(url).status_code == 403
    assert _client(tara).get(url).status_code == 200


def test_s2_1_token_stat_modal_and_counts_are_scoped(olaf, lees_token):
    body = _client(olaf).get(reverse("tokenmgr:token-stat-detail", args=["total"])).content.decode()
    assert "lee-ci" not in body
    from apps.tokenmgr.stats import get_overview_stats

    assert get_overview_stats(olaf)["total_tokens"] == 0


def test_s2_1_token_search_hits_are_scoped_for_staff(olaf, tara, lees_token):
    from apps.search.backends import get_backend
    from apps.search.registry import all_views, search_all

    for view in all_views():
        get_backend().rebuild(view)

    def tokens_found(user):
        return [h.display for h in search_all("lee-ci", user=user) if h.model_label.lower().endswith(".apitoken")]

    assert tokens_found(olaf) == []
    assert "lee-ci" in tokens_found(tara)


# --- The shipped roles keep working -------------------------------------------


def test_s2_1_shipped_roles_grant_the_view_permissions_they_read_with():
    from apps.access.registry import declared_groups

    perms = {g.name: set(g.permissions) for g in declared_groups()}
    assert "accounts.view_user" in perms["Access reviewer"]
    assert "accounts.view_user" in perms["User manager"]
    assert "smallstack.view_apitoken" in perms["Token manager"]

