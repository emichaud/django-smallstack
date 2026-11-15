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

from django.contrib.auth.models import Group

from apps.approvals.registry import ApprovalKind, register_kind

from .services import CHANGE_MEMBERSHIP, set_membership

KIND = "access.membership"


def _can_decide(user: Any, req: Any) -> bool:
    """Narrows the default (staff) rule: the approver must be able to make the
    change by hand."""
    return bool(user.has_perm(CHANGE_MEMBERSHIP))


def on_membership_decision(req: Any) -> None:
    """Apply an approved change. Anything else (rejected, canceled, expired)
    leaves membership as it was. A missing user or group raises, which the
    approvals app stores as ``callback_error`` for the requester to read."""
    if req.status != req.Status.APPROVED:
        return
    user = req.target
    context = req.context or {}
    group = Group.objects.filter(name=context.get("group", "")).first()
    if user is None:
        raise LookupError(f"The account {req.target_repr!r} no longer exists; nothing changed.")
    if group is None:
        raise LookupError(f"The group {context.get('group')!r} no longer exists; nothing changed.")
    set_membership(
        user,
        group,
        bool(context.get("member")),
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
    default_expires_in=timedelta(days=3),
)
# Registered at import (the approvals app autodiscovers this module); a test
# that clears the kind registry re-registers it the same way.
register_kind(MEMBERSHIP_KIND)


def request_membership_change(
    user: Any, group: Group, member: bool, *, actor: Any, reason: str, source: str = "MCP"
) -> Any:
    """File the approval request for ``actor`` (the agent's user). Raises what
    :func:`apps.approvals.services.request_approval` raises (``ApprovalsDisabled``,
    ``TooManyPending``)."""
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
            "group_permissions": group.permissions.count(),
        },
        require_known_kind=True,
        source=source,
    )
