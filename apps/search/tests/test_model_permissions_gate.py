"""Search honours a CRUDView's ``model_permissions`` (B5, finding R2-3).

A view with ``model_permissions`` on refuses its list page to a staff account
without ``view``; search, the indexed-sources preview, the MCP search tools and
``sc search`` must refuse its hits the same way.
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command

from apps.search.registry import _user_can_see, get_indexed_sources, get_view_by_label, search_all

pytestmark = pytest.mark.django_db
User = get_user_model()
NEEDLE = "zzqb5needle"


@pytest.fixture
def users_checked(monkeypatch):
    from apps.smallstack.crud import CRUDView
    from apps.usermanager.views import UserCRUDView

    # The User Manager now checks ``view`` itself (S2-1); the patch pins that
    # these tests keep meaning "a view that checks view the CRUDView way".
    monkeypatch.setattr(UserCRUDView, "model_permissions", True)
    monkeypatch.setattr(UserCRUDView, "has_model_permission", classmethod(CRUDView.has_model_permission.__func__))
    return UserCRUDView


@pytest.fixture
def staff():
    return User.objects.create_user("b5-staff", password="p", is_staff=True)


@pytest.fixture
def needle():
    return User.objects.create_user(NEEDLE, email=f"{NEEDLE}@example.com", first_name=NEEDLE.title())


def _user_hits(user):
    return [h for h in search_all(NEEDLE, user=user) if h.model_label == "accounts.User"]


def test_staff_without_view_gets_no_hits(users_checked, staff, needle, client):
    view = get_view_by_label("accounts.User")
    assert view is not None
    assert not _user_can_see(view, staff)
    assert _user_hits(staff) == []
    assert not [s for s in get_indexed_sources(staff) if s.get("model_label") == "accounts.User"]
    client.force_login(staff)
    r = client.get(f"/search/?q={NEEDLE}")
    assert f"{NEEDLE}@example.com".encode() not in r.content.lower()  # the query itself is echoed
    out = StringIO()
    call_command("sc", "search", NEEDLE, "--user", staff.username, "--json", stdout=out)
    assert NEEDLE not in out.getvalue().lower()


def test_staff_with_view_still_finds(users_checked, staff, needle):
    staff.user_permissions.add(Permission.objects.get(codename="view_user", content_type__app_label="accounts"))
    staff = User.objects.get(pk=staff.pk)
    assert _user_hits(staff)


def test_staff_holding_view_user_gets_the_hits(staff, needle):
    # Was "views without model_permissions keep the staff rule", with the User
    # Manager as the example; since S2-1 it checks view_user like the rest.
    assert not _user_hits(staff)
    staff.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
    assert _user_hits(User.objects.get(pk=staff.pk))


def test_trusted_internal_caller_still_bypasses(users_checked, needle):
    assert [h for h in search_all(NEEDLE, user=None) if h.model_label == "accounts.User"]


def test_mcp_search_tool_refuses(users_checked, staff, needle):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context
    from apps.search.mcp_tools import register_search_tools

    register_search_tools()
    if "search_users" not in TOOL_HANDLERS:
        pytest.skip("search_users not registered")
    ctx = set_context(ToolContext(user=staff, token=None))
    try:
        result = TOOL_HANDLERS["search_users"]({"query": NEEDLE})
    finally:
        reset_context(ctx)
    assert result.get("denied") is True
    assert NEEDLE not in json.dumps(result, default=str).lower()
