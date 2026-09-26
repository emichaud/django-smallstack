"""Shared fixtures — the user matrix and a recording sample kind."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.approvals.registry import ApprovalKind, register_kind, unregister

User = get_user_model()


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff", password="p", is_staff=True)


@pytest.fixture
def staff2(db):
    return User.objects.create_user("staff2", password="p", is_staff=True)


@pytest.fixture
def requester(db):
    return User.objects.create_user("requester", password="p")


@pytest.fixture
def assignee(db):
    """A NON-STAFF assignee — the case the eligibility rules exist for."""
    return User.objects.create_user("assignee", password="p")


@pytest.fixture
def bystander(db):
    return User.objects.create_user("bystander", password="p")


@pytest.fixture
def sample_kind():
    """A registered kind whose callback records every invocation."""
    calls: list = []

    kind = ApprovalKind(
        key="test.sample",
        label="Sample approval",
        on_decision=lambda req: calls.append((req.pk, req.status)),
    )
    register_kind(kind)
    kind.calls = calls  # type: ignore[attr-defined]
    yield kind
    unregister("test.sample")


@pytest.fixture(autouse=True)
def _reregister_mcp_tools():
    """The MCP suite calls clear_registry_for_tests(), wiping tools registered
    at import time — whether ours exist would depend on test ordering
    (telemetry conftest precedent). Re-apply before every test."""
    try:
        from apps.approvals.mcp_tools import register_approvals_tools

        register_approvals_tools()
    except Exception:
        pass
    try:
        # The CRUDView-derived read tools (get_approval / list_approvals) are the
        # other half of the documented polling loop, so they must be present here
        # regardless of test ordering too.
        from apps.approvals.views import ApprovalRequestCRUDView
        from apps.mcp.factory import register_mcp_tools_from_crudview

        register_mcp_tools_from_crudview(ApprovalRequestCRUDView)
    except Exception:
        pass
    yield
