"""An approval that changes nothing must not read "approved" (G1-3, 2026-11-14 round).

A User manager approving "add X to a group granting perms they lack" got
``status: approved`` with membership unchanged and a full Python traceback (with
server paths) in ``callback_error``, shown on the request page and returned by
MCP ``get_approval``.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

from apps.access.approvals import request_membership_change
from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.approvals.registry import ApprovalKind, register_kind, unregister

pytestmark = pytest.mark.django_db
User = get_user_model()


def _perm(label):
    app, codename = label.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@pytest.fixture
def um():
    u = User.objects.create_user(username="um", password="x", is_staff=True)
    u.user_permissions.add(_perm("accounts.change_user"))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def agent():
    return User.objects.create_user(username="agent", password="x", is_staff=True)


@pytest.fixture
def alice():
    return User.objects.create_user(username="alice", password="x")


@pytest.fixture
def token_managers():
    g = Group.objects.create(name="Tokens+")
    g.permissions.add(_perm("smallstack.add_apitoken"), _perm("smallstack.change_apitoken"))
    return g


def test_g1_3_refused_at_decide_time_and_stays_pending(um, agent, alice, token_managers):
    req = request_membership_change(alice, token_managers, True, actor=agent, reason="r")
    with pytest.raises(approvals.ApprovalRefused) as exc:
        approvals.approve(req, actor=um, source="MCP")
    assert "smallstack.add_apitoken" in str(exc.value)
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.PENDING
    assert req.decided_by is None and req.callback_error == ""
    assert not alice.groups.exists()
    # Rejecting is still open to the same approver.
    approvals.reject(req, actor=um, source="MCP")
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.REJECTED


def test_g1_3_web_decide_shows_the_reason_and_keeps_it_pending(client, um, agent, alice, token_managers):
    req = request_membership_change(alice, token_managers, True, actor=agent, reason="r")
    client.force_login(um)
    resp = client.post(f"/smallstack/approvals/requests/{req.pk}/decide/", {"decision": "approve"}, follow=True)
    assert resp.status_code == 200
    assert "smallstack.add_apitoken" in resp.content.decode()
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.PENDING


def test_g1_3_callback_error_is_one_line_without_paths(client, agent):
    register_kind(ApprovalKind(key="test.g13boom", on_decision=lambda r: 1 / 0))
    try:
        root = User.objects.create_superuser(username="root", password="x", email="r@x")
        req = approvals.request_approval(kind="test.g13boom", title="t", actor=agent)
        approvals.approve(req, actor=root)
        req.refresh_from_db()
        assert req.status == ApprovalRequest.Status.APPROVED
        assert req.callback_error == "ZeroDivisionError: division by zero"
        from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

        tok = set_context(ToolContext(user=agent, token=None))
        try:
            reply = TOOL_HANDLERS["get_approval"]({"id": req.pk})
        finally:
            reset_context(tok)
        payload = reply if isinstance(reply, dict) else json.loads(reply)
        assert payload["callback_error"] == "ZeroDivisionError: division by zero"

        # A row stored before the fix (a whole traceback): the page shows its
        # last line, and the data migration shortens the row itself.
        legacy = 'Traceback (most recent call last):\n  File "/srv/app/x.py", line 3, in f\nValueError: nope'
        ApprovalRequest.objects.filter(pk=req.pk).update(callback_error=legacy)
        client.force_login(root)
        page = client.get(f"/smallstack/approvals/requests/{req.pk}/").content.decode()
        assert "/srv/app" not in page and "Traceback" not in page
        assert "ValueError: nope" in page
        from importlib import import_module

        from django.apps import apps as django_apps

        import_module("apps.approvals.migrations.0002_callback_error_one_line").shorten(django_apps, None)
        req.refresh_from_db()
        assert req.callback_error == "ValueError: nope"
    finally:
        unregister("test.g13boom")
