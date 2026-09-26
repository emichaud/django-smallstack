"""Scenario C kind — ``access.grant`` (autodiscovered by apps/approvals).

The grant is armed at decision time, not request time: ``granted_until`` is set
only on approval and is cleared on every other terminal status, which is the
"disarm on non-approval" rule from docs/skills/approvals.md §1.

``notify=[...]`` exercises the extra-email-recipient half of §4.5 recipient
assembly (kind.notify + SMALLSTACK_APPROVALS_NOTIFY_EMAILS, minus the requester).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.approvals import approval_kind
from apps.approvals.models import ApprovalRequest

from .models import AccessRequest

logger = logging.getLogger("smallstack.demo_access")

KIND = "access.grant"

# The audit mailbox that hears about every elevated-access decision.
AUDIT_MAILBOX = "access-audit@example.com"

_STATE_FOR_STATUS: dict[str, str] = {
    ApprovalRequest.Status.APPROVED: AccessRequest.State.GRANTED,
    ApprovalRequest.Status.REJECTED: AccessRequest.State.REJECTED,
    ApprovalRequest.Status.CANCELED: AccessRequest.State.CANCELED,
    ApprovalRequest.Status.EXPIRED: AccessRequest.State.EXPIRED,
}


@approval_kind(
    KIND,
    label="Grant elevated access",
    description=(
        "Time-bound elevated access to a protected resource. Approval grants "
        "the requested scope until now + duration_hours; every other outcome "
        "grants nothing."
    ),
    default_expires_in=timedelta(hours=12),
    notify=[AUDIT_MAILBOX],
)
def on_access_decision(req: Any) -> None:
    """React to ANY terminal transition of an access.grant request."""
    ar = req.target
    if not isinstance(ar, AccessRequest):
        return

    state = _STATE_FOR_STATUS.get(req.status)
    if state is None:  # pragma: no cover — services only calls us post-terminal
        logger.warning("access.grant: non-terminal status %r", req.status)
        return

    ar.state = state
    if state == AccessRequest.State.GRANTED:
        # Arm the time-bound grant.
        ar.granted_until = timezone.now() + timedelta(hours=ar.duration_hours)
    else:
        # Disarm — no grant on reject / expire / cancel.
        ar.granted_until = None
    ar.save(update_fields=["state", "granted_until", "updated_at"])
