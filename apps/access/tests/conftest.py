"""Shared fixtures. The MCP suite clears the tool registry and the approvals
suite clears the kind registry, so whether ours exist would depend on test
ordering; re-apply before every test (approvals/telemetry precedent)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

User = get_user_model()


@pytest.fixture(autouse=True)
def _reregister():
    from apps.access.approvals import MEMBERSHIP_KIND, REVIEW_REMOVE_KIND
    from apps.access.mcp_tools import register_access_tools
    from apps.approvals.registry import register_kind

    register_access_tools()
    register_kind(MEMBERSHIP_KIND)
    register_kind(REVIEW_REMOVE_KIND)
    try:
        from apps.approvals.mcp_tools import register_approvals_tools
        from apps.approvals.views import ApprovalRequestCRUDView
        from apps.mcp.factory import register_mcp_tools_from_crudview

        register_approvals_tools()
        register_mcp_tools_from_crudview(ApprovalRequestCRUDView)
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _private_media(settings, tmp_path):
    """Stored evidence packs go to a temporary MEDIA_ROOT, not the checkout's
    media/ (G2-7)."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    yield


@pytest.fixture
def root(db):
    return User.objects.create_superuser("root", password="p")


@pytest.fixture
def staffer(db):
    """Staff holding accounts.view_user but not accounts.change_user: may read
    access (S2-1: reading needs view_user), not change it."""
    user = User.objects.create_user("staffer", password="p", is_staff=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def manager(db):
    """Staff holding accounts.change_user (and view_user, so it may add to the
    ``readers`` group, which grants it): may change membership."""
    user = User.objects.create_user("manager", password="p", is_staff=True)
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="accounts", codename__in=["change_user", "view_user"])
    )
    return user


@pytest.fixture
def alice(db):
    return User.objects.create_user("alice", email="alice@example.com", password="p")


@pytest.fixture
def readers(db):
    group = Group.objects.create(name="Readers")
    group.permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
    return group
