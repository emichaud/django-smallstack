"""Scenario B services — an agent proposes; a human decides.

One entry point, shared by the MCP tool and the harness, so the MCP surface has
no behaviour of its own.
"""

from __future__ import annotations

from typing import Any

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest

from .actions import TOOL_NAMES
from .models import AgentAction


def propose(
    *,
    tool_name: str,
    payload: dict[str, Any] | None,
    risk: str,
    actor: Any,
    agent: str = "",
    source: str = "MCP",
) -> tuple[AgentAction, ApprovalRequest]:
    """Record the proposed action and file the human gate for it.

    Returns ``(action, approval_request)``. The action is PENDING and nothing has
    run: execution happens only in the kind callback, on approval.
    """
    if risk not in AgentAction.Risk.values:
        raise ValueError(f"risk must be one of {', '.join(AgentAction.Risk.values)}")

    action = AgentAction.objects.create(
        tool_name=tool_name,
        payload=payload or {},
        risk=risk,
        requested_by_agent=agent or getattr(actor, "username", "") or "unknown-agent",
        state=AgentAction.State.PROPOSED,
    )
    req = approvals.request_approval(
        kind="agentops.action",
        title=f"Agent action: {tool_name} ({risk} risk)",
        actor=actor,
        description=(
            f"Agent “{action.requested_by_agent}” proposes to run {tool_name}. "
            "It will not run unless a human approves."
        ),
        target=action,
        context={
            "tool_name": tool_name,
            "risk": risk,
            "agent": action.requested_by_agent,
            "payload": payload or {},
            "known_tools": TOOL_NAMES,
        },
        source=source,
    )
    action.approval = req
    action.state = AgentAction.State.PENDING
    action.save(update_fields=["approval", "state", "updated_at"])
    return action, req
