"""MCP tools: an agent reads access the way the pages show it, and may
*propose* a membership change that a person approves.

- ``access_explain_user`` — flags, groups, every permission with its sources.
- ``access_check_permission`` — ``has_perm`` plus the reasons.
- ``access_findings`` — the least-privilege review.

The three read tools need a staff caller holding ``accounts.view_user``
(superusers pass), as the Access pages do; they're hidden from others.
- ``access_request_membership`` — files an ``access.membership`` approval
  (see :mod:`apps.access.approvals`). The agent never writes membership: a
  person holding ``accounts.change_user`` approves, the change runs in their
  name, and the record carries the agent's request. Off when
  ``SMALLSTACK_ACCESS_MCP_WRITES`` is False.

Errors come back as ``{"error": {"code", "message"}}`` (approvals' shape).
Registration is recorded and performed, so the MCP suite's registry reset can
be undone by :func:`register_access_tools` (approvals/telemetry precedent).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.conf import settings

from apps.mcp.server import current_context, tool

from . import services
from .registry import run_checks

Handler = Callable[..., Any]
_SPECS: list[tuple[str, str, dict[str, Any], dict[str, Any], Handler]] = []


def _writes_enabled() -> bool:
    return bool(getattr(settings, "SMALLSTACK_ACCESS_MCP_WRITES", True))


def _register(
    name: str, description: str, schema: dict[str, Any], *, when: Callable[[], bool] | None = None, **opts: Any
) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        _SPECS.append((name, description, schema, {**opts, "_when": when}, fn))
        if when is None or when():
            tool(name, description, schema, **opts)(fn)
        return fn

    return decorator


def register_access_tools() -> int:
    """Re-apply every registration the current settings allow. Idempotent;
    returns the count registered."""
    count = 0
    for name, description, schema, opts, fn in _SPECS:
        opts = dict(opts)
        when = opts.pop("_when")
        if when is None or when():
            tool(name, description, schema, **opts)(fn)
            count += 1
    return count


def _err(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _read_refusal() -> dict[str, Any] | None:
    """The read tools need ``accounts.view_user`` (``services.can_read_access``)."""
    if services.can_read_access(getattr(current_context(), "user", None)):
        return None
    return _err("forbidden", services.READ_ACCESS_REFUSAL)


@_register(
    "access_explain_user",
    (
        "What an account can do and why: its flags, groups (since when, added by whom), "
        "direct permissions, every effective permission with its sources (superuser / "
        "group:<name> / direct), live API tokens and recent access changes. Use it before "
        "proposing a change, or to answer 'what can X do'."
    ),
    {
        "type": "object",
        "required": ["username"],
        "properties": {"username": {"type": "string", "description": "Username, email or id."}},
        "additionalProperties": False,
    },
    requires_access="staff",
    visible_to=services.can_read_access,
)
def access_explain_user(args: dict[str, Any]) -> dict[str, Any]:
    refused = _read_refusal()
    if refused:
        return refused
    try:
        user = services.resolve_user(args.get("username"))
    except LookupError as exc:
        return _err("not_found", str(exc))
    return services.user_payload(user)


@_register(
    "access_check_permission",
    (
        "Whether an account holds one permission ('app_label.codename', e.g. "
        "'accounts.change_user') — the answer user.has_perm() gives every page, API "
        "route and tool — with the reasons (which group grants it, direct, superuser)."
    ),
    {
        "type": "object",
        "required": ["username", "permission"],
        "properties": {
            "username": {"type": "string"},
            "permission": {"type": "string", "description": "app_label.codename"},
        },
        "additionalProperties": False,
    },
    requires_access="staff",
    visible_to=services.can_read_access,
)
def access_check_permission(args: dict[str, Any]) -> dict[str, Any]:
    refused = _read_refusal()
    if refused:
        return refused
    perm = str(args.get("permission") or "").strip()
    if "." not in perm:
        return _err("bad_permission", "permission must be app_label.codename.")
    try:
        user = services.resolve_user(args.get("username"))
    except LookupError as exc:
        return _err("not_found", str(exc))
    return services.explanation_payload(user, perm)


@_register(
    "access_findings",
    (
        "The least-privilege review: superusers, dormant privileged accounts, direct "
        "permissions, deactivated accounts with live tokens, groups drifted from their "
        "declaration, and more — each with a severity, a count and the rows behind it."
    ),
    {"type": "object", "properties": {}, "additionalProperties": False},
    requires_access="staff",
    visible_to=services.can_read_access,
)
def access_findings(args: dict[str, Any]) -> dict[str, Any]:
    refused = _read_refusal()
    if refused:
        return refused
    findings = run_checks()
    order = {"danger": 3, "warning": 2, "info": 1, "ok": 0}
    worst = max(findings, key=lambda f: order[f.severity], default=None)
    return {"worst": worst.severity if worst else "ok", "findings": [f.as_dict() for f in findings]}


@_register(
    "access_request_membership",
    (
        "Propose adding an account to a group (member=true) or removing it (false). "
        "This does NOT change anything itself: it files an approval request that a "
        "person with accounts.change_user (and every permission the group grants) "
        "decides in the SmallStack console; only an "
        "approval makes the change, in that person's name. Give a reason the approver "
        "can act on. Then poll get_approval with the returned 'approval_id' until "
        "'status' is no longer 'pending': 'approved' means it was applied (check "
        "'callback_error' is empty); rejected, canceled or expired means it was not. "
        "If you can call access_explain_user, call it first so you do not propose what "
        "already holds."
    ),
    {
        "type": "object",
        "required": ["username", "group", "member", "reason"],
        "properties": {
            "username": {"type": "string", "description": "Username, email or id."},
            "group": {"type": "string", "description": "Group name."},
            "member": {"type": "boolean", "description": "true to add, false to remove."},
            "reason": {"type": "string", "description": "Why, for the approver and the record."},
        },
        "additionalProperties": False,
    },
    when=_writes_enabled,
    write=True,
    requires_access="staff",
)
def access_request_membership(args: dict[str, Any]) -> dict[str, Any]:
    from apps.approvals import services as approvals

    from .approvals import request_membership_change

    reason = str(args.get("reason") or "").strip()
    if not reason:
        return _err("reason_required", "Give the approver a reason.")
    caller = current_context().user
    # A caller who may not read access (no accounts.view_user) learns nothing
    # about membership here: "already a member" is filed like any other
    # request (the approver's decide-time check refuses a request that would
    # change nothing), a miss doesn't list the groups, and an email isn't
    # looked up (it would answer "whose address is this"). E-dec 2.
    reads_access = services.can_read_access(caller)
    try:
        user = services.resolve_user(args.get("username"), by_email=reads_access)
        group = services.resolve_group(args.get("group"), list_known=reads_access)
    except LookupError as exc:
        return _err("not_found", str(exc))
    member = bool(args.get("member"))
    if reads_access and user.groups.filter(pk=group.pk).exists() == member:
        state = "already in" if member else "not in"
        return _err("unchanged", f"{user.get_username()} is {state} {group.name}; nothing to approve.")
    try:
        req = request_membership_change(
            user, group, member, actor=caller, reason=reason, source="MCP", describe_group=reads_access
        )
    except approvals.ApprovalsDisabled as exc:
        return _err("disabled", str(exc))
    except approvals.TooManyPending as exc:
        return _err("too_many_pending", str(exc))
    return {
        "approval_id": req.pk,
        "status": req.status,
        "terminal": False,
        "title": req.title,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "next": (
            "Poll get_approval with id=approval_id until status leaves 'pending'; "
            "only 'approved' means the change was made."
        ),
    }
