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
    """request_approval: write, ANY token tier (readonly refused structurally
    by write=True). decide_approval: staff tier + staff-only visibility."""
    import apps.approvals.mcp_tools  # noqa: F401  (registers on import)
    from apps.mcp.server import TOOL_REGISTRY

    req_tool = TOOL_REGISTRY["request_approval"]
    assert req_tool.write is True
    assert req_tool.requires_access is None

    dec_tool = TOOL_REGISTRY["decide_approval"]
    assert dec_tool.write is True
    assert dec_tool.requires_access == "staff"
    assert dec_tool.visible_to is not None
    # a non-staff user never sees the decide tool in tools/list
    class _Plain:
        is_staff = False

    assert dec_tool.visible_to(_Plain()) is False


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
    assert "tpyo.kind" in result["error"]
    assert "test.sample" in result["error"]  # the error teaches the fix


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
    assert result["error"].startswith("conflict")

    own = _file(staff)  # self-approval blocked
    result = run_tool("decide_approval", {"id": own.pk, "approved": True}, user=staff)
    assert "eligible" in result["error"]


def test_decide_approval_hides_missing_rows(staff, sample_kind):
    result = run_tool("decide_approval", {"id": 999999, "approved": True}, user=staff)
    assert "error" in result
