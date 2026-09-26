"""MCP tools — the agent-facing half of the human-in-the-loop gate.

Exactly TWO custom tools (house tool-count discipline; the enable_mcp factory
already provides list/get from the CRUDView's LIST/DETAIL actions):

- ``request_approval`` — an agent files a request and then polls
  ``get_approval`` (or listens on a webhook) until a human decides. This is
  the canonical HITL pattern: the agent asks, a person answers.
- ``decide_approval`` — any authenticated identity may *call* it; eligibility
  (assignee / staff / the kind's ``can_decide`` hook / no self-approval) is
  enforced in the service, exactly as on the web and REST surfaces. It used to
  be additionally staff-tier, which made MCP the one surface where a non-staff
  assignee could not do what the documented model says they can — and where a
  staff user's own login token was refused.

Errors are returned as ``{"error": {"code": …, "message": …}}``. The MCP view
turns any top-level ``error`` key into ``isError: true``, so a refusal is
distinguishable from a success at the protocol level and ``code`` is branchable
without parsing prose.

Registration is recorded AND performed so the MCP test suite's
``clear_registry_for_tests()`` can be undone by ``register_approvals_tools()``
(telemetry precedent; see tests/conftest.py).
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from apps.mcp.server import current_context, tool

from .resolvers import resolve_assignees, resolve_target

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


def _err(code: str, message: str) -> dict[str, Any]:
    """A structured refusal. ``code`` is the stable, branchable part."""
    return {"error": {"code": code, "message": message}}


def _serialize(req: Any) -> dict[str, Any]:
    """Everything an agent needs to close its loop without a second call.

    ``target``/``target_repr`` say what the request points at, ``context`` is the
    payload the agent itself supplied, ``decided_at`` times the outcome, and
    ``callback_error`` is the only way an agent can learn that the approved side
    effect *failed* — without it a broken callback came back as a clean
    ``{"status": "approved"}``. (F-21.)
    """
    return {
        "id": req.pk,
        "kind": req.kind,
        "title": req.title,
        "description": req.description,
        "status": req.status,
        "terminal": req.status != "pending",
        "context": req.context,
        # Both read from the model properties rather than recomputing the dotted
        # identity here, so this payload and the REST serializer (which exposes
        # the same two properties) cannot drift apart. The keys stay short —
        # `target`/`assignees` — because this payload is hand-built and flat;
        # REST reaches the same values as `target_ref`/`assignee_usernames`,
        # since `target` and `assignees` are already taken there by the instance
        # and the M2M. (F-35.)
        "target": req.target_ref,
        "target_repr": req.target_repr,
        "assignees": req.assignee_usernames,
        "requested_by": getattr(req.requested_by, "username", None),
        "decided_by": getattr(req.decided_by, "username", None),
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
        "decision_note": req.decision_note,
        # Non-empty ⇒ the decision stands but the kind's side effect raised.
        "callback_error": req.callback_error,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "created_at": req.created_at.isoformat(),
    }


@_register(
    "request_approval",
    (
        "File a human-approval request and return its id and status. A human "
        "decides it in the SmallStack console (or an app's own review page). "
        "Then poll get_approval, passing that value as 'id' — roughly every 30 "
        "seconds — until "
        "'terminal' is true; the statuses are pending / approved / rejected / "
        "canceled / expired, and only 'approved' means go ahead. The reply's "
        "'expires_at' is the loop's deadline; when it is null the request never "
        "expires on its own, so cap your own polling and stop. After approval, "
        "check 'callback_error' — non-empty means the approved side effect "
        "itself failed. kind must be a registered approval kind; the error lists "
        "the known kinds. Optional target ('app_label.model:pk') attaches the "
        "request to a business row so the human sees what it is about."
    ),
    {
        "type": "object",
        "required": ["kind", "title"],
        "properties": {
            "kind": {"type": "string", "description": "Registered approval kind key."},
            "title": {"type": "string", "description": "What needs approving, for the human."},
            "description": {"type": "string"},
            "context": {"type": "object", "description": "Kind-specific card payload."},
            "target": {
                "type": "string",
                "description": "Business row this is about, as 'app_label.model:pk'.",
            },
            "assignees": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Usernames who should decide. Only accepted for kinds that "
                    "declare an `assignable` allowlist."
                ),
            },
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
        kind_key = str(args["kind"])
        target, terr = resolve_target(args.get("target"))
        if terr:
            return _err("bad_target", terr)
        assignees, aerr = resolve_assignees(args.get("assignees"), kind_key=kind_key)
        if aerr:
            return _err("bad_assignees", aerr)
        try:
            req = services.request_approval(
                kind=kind_key,
                title=str(args["title"]),
                actor=user,
                description=str(args.get("description") or ""),
                context=args.get("context") or {},
                target=target,
                assignees=assignees,
                expires_in=expires_in,
                require_known_kind=True,
                source="MCP",
            )
        except services.UnknownKind as exc:
            return _err("unknown_kind", str(exc))
        except services.TooManyPending as exc:
            return _err("too_many_pending", str(exc))
        except services.ApprovalsDisabled as exc:
            return _err("disabled", str(exc))
        return _serialize(req)

    return await sync_to_async(_file)()


@_register(
    "decide_approval",
    (
        "Approve or reject a pending approval request as the calling user. "
        "Returns the decided request. On failure the reply has an 'error' with a "
        "code: 'not_found' (no such request, or not visible to you), "
        "'not_eligible' (you may not decide this one — e.g. it is your own "
        "request), or 'conflict' (someone or something already decided it; read "
        "'status' from get_approval instead of retrying)."
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
            return _err(
                "not_found", f"No approval request {args['id']} (or not visible to you)."
            )
        try:
            req = services.decide(
                req,
                actor=user,
                approved=bool(args["approved"]),
                note=str(args.get("note") or ""),
                source="MCP",
            )
        except services.NotEligible as exc:
            return _err("not_eligible", str(exc))
        except services.NotPending as exc:
            return _err("conflict", str(exc))
        except services.ApprovalsDisabled as exc:
            return _err("disabled", str(exc))
        return _serialize(req)

    return await sync_to_async(_decide)()
