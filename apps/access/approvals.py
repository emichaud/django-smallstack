"""The approval gate on membership changes an agent proposes.

An MCP client never changes group membership itself. ``access_request_membership``
files an :class:`~apps.approvals.models.ApprovalRequest` of kind
``access.membership``; a person who holds ``accounts.change_user`` (the same
permission the Access pages ask for) decides it in the approvals console, and
only then does :func:`apps.access.services.set_membership` run, attributed to
the approver with the agent's request in the record's detail.

Autodiscovered by the approvals app (``apps/<app>/approvals.py``).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.approvals.registry import ApprovalKind, register_kind

from .services import CHANGE_MEMBERSHIP, membership_refusal, set_membership

KIND = "access.membership"


def _can_decide(user: Any, req: Any) -> bool:
    """Narrows the default (staff) rule: the approver must be able to make the
    change by hand."""
    return bool(user.has_perm(CHANGE_MEMBERSHIP))


def proposal(req: Any) -> dict[str, Any]:
    """What approving ``req`` would actually do, read from the database: the
    account is ``req.target`` (never the free-form ``context.username``) and
    the group is looked up live. ``problem`` is non-empty when the request is
    malformed (a target that isn't an account, a context naming someone else),
    in which case approving changes nothing. The decision card and the
    callback both read this, so what the approver sees is what happens."""
    context = req.context or {}
    target = req.target
    user = target if isinstance(target, get_user_model()) else None
    group = Group.objects.filter(name=str(context.get("group", ""))).first()
    problem = ""
    if target is not None and user is None:
        problem = f"The request's target {req.target_repr!r} is not an account."
    elif user is not None and context.get("username") not in (None, user.get_username()):
        problem = (
            f"The request names {context.get('username')!r} but would change {user.get_username()!r}; "
            "it was not filed by the Access tool."
        )
    return {
        "user": user,
        "group": group,
        "group_name": group.name if group else str(context.get("group", "")),
        "group_permissions": group.permissions.count() if group else 0,
        "member": bool(context.get("member")),
        "problem": problem,
    }


def _check_approve(actor: Any, req: Any) -> str | None:
    """Refuse an approval that would change nothing, at decide time, so the
    request stays pending instead of reading "approved" (the approver can't
    make the change, or the request is malformed or out of date)."""
    plan = proposal(req)
    if plan["problem"]:
        return plan["problem"]
    if plan["user"] is None:
        return f"The account {req.target_repr!r} no longer exists."
    if plan["group"] is None:
        return f"The group {plan['group_name']!r} no longer exists."
    refusal = membership_refusal(actor, plan["group"], plan["member"])
    if refusal:
        return refusal
    # A requester who may not read access is never told "already a member"
    # when filing (E-dec 2), so a request that would change nothing can
    # arrive here; it is refused rather than read "approved". Reject it.
    if plan["user"].groups.filter(pk=plan["group"].pk).exists() == plan["member"]:
        state = "already in" if plan["member"] else "not in"
        return (
            f"{plan['user'].get_username()} is {state} {plan['group'].name}; approving would change "
            "nothing. Reject the request instead."
        )
    return None


def on_membership_decision(req: Any) -> None:
    """Apply an approved change. Anything else (rejected, canceled, expired)
    leaves membership as it was. A missing user or group, or a request whose
    context disagrees with its target, raises, which the approvals app stores
    as ``callback_error`` for the requester to read."""
    if req.status != req.Status.APPROVED:
        return
    plan = proposal(req)
    if plan["problem"]:
        raise ValueError(plan["problem"] + " Nothing changed.")
    user, group = plan["user"], plan["group"]
    if user is None:
        raise LookupError(f"The account {req.target_repr!r} no longer exists; nothing changed.")
    if group is None:
        raise LookupError(f"The group {plan['group_name']!r} no longer exists; nothing changed.")
    set_membership(
        user,
        group,
        plan["member"],
        actor=req.decided_by,
        source=f"mcp:approval:{req.pk}",
    )


MEMBERSHIP_KIND = ApprovalKind(
    key=KIND,
    label="Change group membership",
    description=(
        "An AI client asked to add an account to a group or remove it. Approving "
        "makes the change in your name; it is recorded like any other access change."
    ),
    on_decision=on_membership_decision,
    can_decide=_can_decide,
    check_approve=_check_approve,
    default_expires_in=timedelta(days=3),
    # Only access_request_membership files this kind: the generic REST/MCP
    # filing routes would let a caller pick a target and a card text that
    # disagree (a forged "Add someone-else" that adds the caller).
    remote_filing=False,
)
# Registered at import (the approvals app autodiscovers this module); a test
# that clears the kind registry re-registers it the same way.
register_kind(MEMBERSHIP_KIND)


def request_membership_change(
    user: Any,
    group: Group,
    member: bool,
    *,
    actor: Any,
    reason: str,
    source: str = "MCP",
    describe_group: bool = True,
) -> Any:
    """File the approval request for ``actor`` (the agent's user). Raises what
    :func:`apps.approvals.services.request_approval` raises (``ApprovalsDisabled``,
    ``TooManyPending``). ``describe_group=False`` leaves the group's permission
    count out of the stored context, which the requester reads back through
    ``get_approval`` (the decision card counts them live either way)."""
    from apps.approvals import services as approvals

    verb = "Add" if member else "Remove"
    joiner = "to" if member else "from"
    return approvals.request_approval(
        kind=KIND,
        title=f"{verb} {user.get_username()} {joiner} {group.name}",
        description=reason,
        actor=actor,
        target=user,
        context={
            "username": user.get_username(),
            "group": group.name,
            "member": member,
            "reason": reason,
            "requested_via": source,
            **({"group_permissions": group.permissions.count()} if describe_group else {}),
        },
        require_known_kind=True,
        source=source,
    )
