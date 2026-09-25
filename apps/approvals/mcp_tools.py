"""MCP tools — the agent-facing half of the human-in-the-loop gate.

Exactly TWO custom tools (house tool-count discipline; the enable_mcp factory
already provides list/get from the CRUDView's LIST/DETAIL actions):

- ``request_approval`` — an agent files a request and then polls
  ``get_approval`` (or listens on a webhook) until a human decides. This is
  the canonical HITL pattern: the agent asks, a person answers.
- ``decide_approval`` — staff-tier by design in v1 (non-staff assignees decide
  through the web embed); eligibility still runs in the service.

Registration is recorded AND performed so the MCP test suite's
``clear_registry_for_tests()`` can be undone by ``register_approvals_tools()``
(telemetry precedent; see tests/conftest.py).
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from apps.mcp.server import current_context, tool

logger = logging.getLogger("smallstack.approvals")

_SPECS: list[tuple] = []


def _register(name: str, description: str, schema: dict, **opts: Any):
    def decorator(fn):
        _SPECS.append((name, description, schema, opts, fn))
        tool(name, description, schema, **opts)(fn)
        return fn

    return decorator


def register_approvals_tools() -> int:
    """Re-apply every registration. Idempotent; returns the tool count."""
    for name, description, schema, opts, fn in _SPECS:
        tool(name, description, schema, **opts)(fn)
    return len(_SPECS)


def _staff_only(user: Any) -> bool:
    return bool(getattr(user, "is_staff", False))


def _serialize(req: Any) -> dict[str, Any]:
    return {
        "id": req.pk,
        "kind": req.kind,
        "title": req.title,
        "status": req.status,
        "requested_by": getattr(req.requested_by, "username", None),
        "decided_by": getattr(req.decided_by, "username", None),
        "decision_note": req.decision_note,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "created_at": req.created_at.isoformat(),
    }


@_register(
    "request_approval",
    (
        "File a human-approval request and return its id. A human decides it in "
        "the SmallStack console; poll get_approval until status is no longer "
        "'pending' (statuses: pending/approved/rejected/canceled/expired). "
        "kind must be a registered approval kind — the error lists known kinds."
    ),
    {
        "type": "object",
        "required": ["kind", "title"],
        "properties": {
            "kind": {"type": "string", "description": "Registered approval kind key."},
            "title": {"type": "string", "description": "What needs approving, for the human."},
            "description": {"type": "string"},
            "context": {"type": "object", "description": "Kind-specific card payload."},
            "expires_in_minutes": {"type": "integer"},
        },
        "additionalProperties": False,
    },
    write=True,
)
async def request_approval_tool(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import timedelta

    from . import services

    user = current_context().user
    expires_in = None
    if args.get("expires_in_minutes") is not None:
        expires_in = timedelta(minutes=int(args["expires_in_minutes"]))

    def _file():
        return services.request_approval(
            kind=str(args["kind"]),
            title=str(args["title"]),
            actor=user,
            description=str(args.get("description") or ""),
            context=args.get("context") or {},
            expires_in=expires_in,
            require_known_kind=True,
            source="MCP",
        )

    try:
        req = await sync_to_async(_file)()
    except services.UnknownKind as exc:
        return {"error": str(exc)}
    return await sync_to_async(_serialize)(req)


@_register(
    "decide_approval",
    (
        "Approve or reject a pending approval request as the calling (staff) "
        "user. Returns the decided request, or an error if it was already "
        "decided ('conflict') or the caller is not eligible."
    ),
    {
        "type": "object",
        "required": ["id", "approved"],
        "properties": {
            "id": {"type": "integer"},
            "approved": {"type": "boolean"},
            "note": {"type": "string"},
        },
        "additionalProperties": False,
    },
    write=True,
    requires_access="staff",
    visible_to=_staff_only,
)
async def decide_approval_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import permissions, services
    from .models import ApprovalRequest

    user = current_context().user

    def _decide():
        req = (
            permissions.viewable_requests(user, ApprovalRequest.objects.all())
            .filter(pk=int(args["id"]))
            .first()
        )
        if req is None:
            return {"error": f"No approval request {args['id']} (or not visible to you)."}
        try:
            req = services.decide(
                req,
                actor=user,
                approved=bool(args["approved"]),
                note=str(args.get("note") or ""),
                source="MCP",
            )
        except services.NotEligible as exc:
            return {"error": str(exc)}
        except services.NotPending as exc:
            return {"error": f"conflict: {exc}"}
        return _serialize(req)

    return await sync_to_async(_decide)()
