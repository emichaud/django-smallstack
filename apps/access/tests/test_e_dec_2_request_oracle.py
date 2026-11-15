"""``access_request_membership`` must not tell a caller who can't read access
whether an account is in a group (E-dec 2, 2026-11-14 access-control round).

A plain staff account (no ``accounts.view_user``) is refused the read tools
(S2-1), but the write tool answered ``unchanged: alice is already in Readers``
for a member and filed a request for a non-member: a membership oracle. A miss
on the group listed every group, and an email resolved to the account's
username in the reply's title.

For such a caller, "already a member" is filed like any other request, and the
approver's decide-time check refuses it ("approving would change nothing"), so
it never reads "approved". A caller holding ``view_user`` keeps the precise
``unchanged`` answer.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest

from .test_mcp_tools import run_tool

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def plain_staff(db):
    return User.objects.create_user("plain", password="p", is_staff=True)


def _ask(user, *, username="alice", group="Readers", member=True):
    return run_tool(
        "access_request_membership",
        {"username": username, "group": group, "member": member, "reason": "needs it"},
        user=user,
    )


def _shape(reply):
    """What the caller can tell apart: error code or the reply's keys, and the
    stored context's keys."""
    if "error" in reply:
        return ("error", reply["error"]["code"])
    req = ApprovalRequest.objects.get(pk=reply["approval_id"])
    return ("filed", tuple(sorted(reply)), reply["status"], tuple(sorted(req.context)))


def test_member_and_non_member_look_the_same_without_view_user(plain_staff, alice, readers):
    bob = User.objects.create_user("bob", password="p")
    alice.groups.add(readers)
    as_member = _ask(plain_staff, username="alice")
    as_non_member = _ask(plain_staff, username="bob")
    assert "error" not in as_member, as_member
    assert _shape(as_member) == _shape(as_non_member)
    # Removal: alice is in, bob is out; both answers look alike too.
    assert _shape(_ask(plain_staff, username="alice", member=False)) == _shape(
        _ask(plain_staff, username="bob", member=False)
    )
    assert bob.groups.count() == 0


def test_no_group_size_in_what_the_requester_reads_back(plain_staff, alice, readers):
    req = ApprovalRequest.objects.get(pk=_ask(plain_staff)["approval_id"])
    assert "group_permissions" not in req.context


def test_a_group_miss_does_not_list_the_groups(plain_staff, alice, readers):
    Group.objects.create(name="Secret admins")
    reply = _ask(plain_staff, group="nope")
    assert reply["error"]["code"] == "not_found"
    assert "Secret admins" not in reply["error"]["message"]
    assert "Readers" not in reply["error"]["message"]


def test_an_email_is_not_resolved_without_view_user(plain_staff, alice, readers):
    reply = _ask(plain_staff, username="alice@example.com")
    assert reply["error"]["code"] == "not_found"
    assert not ApprovalRequest.objects.filter(title__contains="alice").exists()


def test_the_pointless_request_is_refused_at_decide_time(plain_staff, manager, alice, readers):
    alice.groups.add(readers)
    req = ApprovalRequest.objects.get(pk=_ask(plain_staff)["approval_id"])
    with pytest.raises(approvals.ApprovalRefused, match="would change nothing"):
        approvals.approve(req, actor=manager, source="web")
    req.refresh_from_db()
    assert req.status == "pending" and req.callback_error == ""
    approvals.reject(req, actor=manager, source="web")
    req.refresh_from_db()
    assert req.status == "rejected"


def test_a_real_change_still_approves(plain_staff, manager, alice, readers):
    req = ApprovalRequest.objects.get(pk=_ask(plain_staff)["approval_id"])
    approvals.approve(req, actor=manager, source="web")
    assert alice.groups.filter(pk=readers.pk).exists()


def test_guard_view_user_keeps_the_precise_answer(staffer, alice, readers):
    alice.groups.add(readers)
    reply = _ask(staffer)
    assert reply["error"]["code"] == "unchanged"
    assert "already in" in reply["error"]["message"]
    miss = _ask(staffer, group="nope")
    assert "Readers" in miss["error"]["message"]
    assert "approval_id" in _ask(staffer, username="alice@example.com", member=False)
