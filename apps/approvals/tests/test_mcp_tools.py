"""The MCP tools — registration gating and transport agreement with services.

transaction=True for the same reason as telemetry's MCP tests: the handlers
are async and reach the ORM via sync_to_async (another thread), which can't
see rows inside pytest-django's default wrapping transaction on SQLite.
"""

from __future__ import annotations

import asyncio

import pytest

from apps.approvals import services
from apps.approvals.models import ApprovalRequest

pytestmark = pytest.mark.django_db(transaction=True)


def run_tool(name: str, args: dict, *, user):
    """Dispatch a registered MCP tool the way the server does."""
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=user, token=None))
    try:
        return asyncio.run(TOOL_HANDLERS[name](args))
    finally:
        reset_context(token)


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


# --- registration -----------------------------------------------------------


def test_tools_registered_with_the_right_gating():
    """Both tools are write-gated and open to ANY token tier; ELIGIBILITY — not
    the tier — decides who may actually act.

    decide_approval used to be additionally staff-tier with staff-only
    visibility, which made MCP the one surface where a non-staff assignee could
    not do what the documented model says they can, and where a real staff user's
    own /api/auth/token/ login token was refused outright. (F-02, F-14.)
    """
    import apps.approvals.mcp_tools  # noqa: F401  (registers on import)
    from apps.mcp.server import TOOL_REGISTRY

    req_tool = TOOL_REGISTRY["request_approval"]
    assert req_tool.write is True
    assert req_tool.requires_access is None

    dec_tool = TOOL_REGISTRY["decide_approval"]
    assert dec_tool.write is True
    assert dec_tool.requires_access is None
    assert dec_tool.visible_to is None  # discoverable, then eligibility-gated


def test_read_tools_are_visible_to_a_non_staff_agent():
    """F-02: the polling tool request_approval's description names must be in
    tools/list for the identity that filed the request, or the HITL loop that
    the docs advertise cannot close."""
    from apps.mcp.server import TOOL_REGISTRY

    for name in ("get_approval", "list_approvals"):
        spec = TOOL_REGISTRY[name]
        assert spec.requires_access is None, name
        assert spec.visible_to is None, name


def test_factory_tools_are_read_only():
    """enable_mcp with actions=[LIST, DETAIL] must NOT have emitted any
    factory write tools (create/update/delete) for approvals."""
    from apps.mcp.server import TOOL_REGISTRY

    write_factory = [
        name
        for name, spec in TOOL_REGISTRY.items()
        if "approval" in name
        and spec.write
        and name not in ("request_approval", "decide_approval")
    ]
    assert write_factory == []


# --- request_approval -------------------------------------------------------


def test_request_approval_files_and_serializes(requester, sample_kind):
    result = run_tool(
        "request_approval",
        {"kind": "test.sample", "title": "Ship it", "context": {"n": 1},
         "expires_in_minutes": 30},
        user=requester,
    )
    assert result["status"] == "pending"
    assert result["requested_by"] == requester.username
    assert result["expires_at"] is not None
    req = ApprovalRequest.objects.get(pk=result["id"])
    assert req.context == {"n": 1}


def test_request_approval_unknown_kind_returns_error(requester, sample_kind):
    result = run_tool("request_approval", {"kind": "tpyo.kind", "title": "x"}, user=requester)
    # Structured: `code` is branchable without parsing prose (F-20).
    assert result["error"]["code"] == "unknown_kind"
    assert "tpyo.kind" in result["error"]["message"]
    assert "test.sample" in result["error"]["message"]  # the error teaches the fix


# --- decide_approval --------------------------------------------------------


def test_decide_approval_full_loop(requester, staff, sample_kind):
    req = _file(requester)
    result = run_tool(
        "decide_approval", {"id": req.pk, "approved": True, "note": "ok"}, user=staff
    )
    assert result["status"] == "approved"
    assert result["decided_by"] == staff.username
    # transport agreement: the DB row matches what the tool reported
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.APPROVED
    assert sample_kind.calls == [(req.pk, "approved")]


def test_decide_approval_conflict_and_ineligible(requester, staff, staff2, sample_kind):
    req = _file(requester)
    services.approve(req, actor=staff2)
    result = run_tool("decide_approval", {"id": req.pk, "approved": False}, user=staff)
    assert result["error"]["code"] == "conflict"

    own = _file(staff)  # self-approval blocked
    result = run_tool("decide_approval", {"id": own.pk, "approved": True}, user=staff)
    assert result["error"]["code"] == "not_eligible"


def test_decide_approval_hides_missing_rows(staff, sample_kind):
    result = run_tool("decide_approval", {"id": 999999, "approved": True}, user=staff)
    assert "error" in result
