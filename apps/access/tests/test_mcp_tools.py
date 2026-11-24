"""The MCP tools: reads answer as the pages do; the write only *proposes*,
and a person holding accounts.change_user approves before anything changes."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.access.models import AccessEvent
from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest

pytestmark = pytest.mark.django_db

User = get_user_model()


def run_tool(name, args, *, user):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=user, token=None))
    try:
        return TOOL_HANDLERS[name](args)
    finally:
        reset_context(token)


def test_registration_and_gating():
    from apps.mcp.server import TOOL_REGISTRY

    for name in ("access_explain_user", "access_check_permission", "access_findings"):
        assert TOOL_REGISTRY[name].requires_access == "readonly" and not TOOL_REGISTRY[name].write  # T2-9
    write = TOOL_REGISTRY["access_request_membership"]
    assert write.write and write.requires_access == "staff"


def test_the_write_tool_is_absent_when_the_setting_is_off(settings):
    from apps.access.mcp_tools import register_access_tools
    from apps.mcp.server import TOOL_HANDLERS, TOOL_REGISTRY

    settings.SMALLSTACK_ACCESS_MCP_WRITES = False
    TOOL_REGISTRY.pop("access_request_membership", None)
    TOOL_HANDLERS.pop("access_request_membership", None)
    assert register_access_tools() == 3
    assert "access_request_membership" not in TOOL_REGISTRY
    assert "access_explain_user" in TOOL_REGISTRY


def test_read_tools(staffer, alice, readers):
    alice.groups.add(readers)
    data = run_tool("access_explain_user", {"username": "alice"}, user=staffer)
    assert data["groups"][0]["name"] == "Readers"
    assert data["permissions"][0]["sources"] == ["group:Readers"]
    check = run_tool("access_check_permission", {"username": "alice", "permission": "accounts.view_user"}, user=staffer)
    assert check["allowed"] is True and check["reasons"]
    assert (
        run_tool("access_check_permission", {"username": "alice", "permission": "x"}, user=staffer)["error"]["code"]
        == "bad_permission"
    )
    assert run_tool("access_explain_user", {"username": "nobody"}, user=staffer)["error"]["code"] == "not_found"
    findings = run_tool("access_findings", {}, user=staffer)
    assert "findings" in findings and findings["worst"] in ("ok", "info", "warning", "danger")


# --- the approval gate --------------------------------------------------------------


def _propose(agent, member=True):
    return run_tool(
        "access_request_membership",
        {"username": "alice", "group": "Readers", "member": member, "reason": "Onboarding to the readers rota."},
        user=agent,
    )


def test_a_proposal_changes_nothing_until_a_person_approves(staffer, manager, alice, readers):
    reply = _propose(staffer)
    assert reply["status"] == "pending" and reply["terminal"] is False
    req = ApprovalRequest.objects.get(pk=reply["approval_id"])
    assert req.kind == "access.membership" and req.target == alice and req.requested_by == staffer
    assert req.context["group"] == "Readers" and req.context["member"] is True and req.context["reason"]
    assert req.expires_at is not None
    assert not alice.groups.exists()
    assert not AccessEvent.objects.filter(kind="group_added").exists()

    approvals.approve(req, actor=manager, note="ok", source="web")
    req.refresh_from_db()
    assert req.status == "approved" and req.callback_error == ""
    assert alice.groups.filter(pk=readers.pk).exists()
    event = AccessEvent.objects.get(kind="group_added", subject=alice)
    # In the approver's name, traceable to the agent's request.
    assert event.actor == manager and event.source == f"mcp:approval:{req.pk}"
    # The agent's polling loop sees it as done.
    polled = run_tool("get_approval", {"id": req.pk}, user=staffer)
    assert polled["status"] == "approved" and polled["callback_error"] == ""


def test_only_someone_who_could_make_the_change_by_hand_may_approve(staffer, alice, readers):
    other_staff = User.objects.create_user("other", password="p", is_staff=True)
    req = ApprovalRequest.objects.get(pk=_propose(staffer)["approval_id"])
    with pytest.raises(approvals.NotEligible):
        approvals.approve(req, actor=other_staff, source="web")
    assert not alice.groups.exists()


def test_a_rejection_changes_nothing(staffer, manager, alice, readers):
    req = ApprovalRequest.objects.get(pk=_propose(staffer)["approval_id"])
    approvals.reject(req, actor=manager, source="web")
    assert not alice.groups.exists()
    assert not AccessEvent.objects.filter(kind="group_added").exists()


def test_a_removal_proposal_and_an_unchanged_one(staffer, manager, alice, readers):
    assert _propose(staffer, member=False)["error"]["code"] == "unchanged"
    alice.groups.add(readers)
    assert _propose(staffer)["error"]["code"] == "unchanged"
    req = ApprovalRequest.objects.get(pk=_propose(staffer, member=False)["approval_id"])
    assert req.title == "Remove alice from Readers"
    approvals.approve(req, actor=manager, source="web")
    assert not alice.groups.exists()
    assert AccessEvent.objects.filter(kind="group_removed", actor=manager).exists()


def test_a_vanished_group_is_refused_at_decision(staffer, manager, alice, readers):
    # G1-3: refused when deciding, so the request never reads "approved".
    req = ApprovalRequest.objects.get(pk=_propose(staffer)["approval_id"])
    readers.delete()
    with pytest.raises(approvals.ApprovalRefused, match="no longer exists"):
        approvals.approve(req, actor=manager, source="web")
    req.refresh_from_db()
    assert req.status == "pending" and req.callback_error == ""
    assert not alice.groups.exists()


def test_a_reason_is_required(staffer, alice, readers):
    reply = run_tool(
        "access_request_membership",
        {"username": "alice", "group": "Readers", "member": True, "reason": " "},
        user=staffer,
    )
    assert reply["error"]["code"] == "reason_required"
    assert not ApprovalRequest.objects.exists()
