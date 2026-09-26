"""Scenario A kind — ``purchasing.approve`` (autodiscovered by apps/approvals).

The callback is the ONLY place PurchaseRequest reacts to a decision, and it
handles every terminal status (approved / rejected / canceled / expired) as
docs/skills/approvals.md §1 requires: the PO is armed on approval and nothing
is armed on any other outcome.

The context card template is resolved from the kind key
("purchasing.approve" → ``approvals/kinds/purchasing-approve.html``) — the
key-derived path, not an explicit ``context_template``. Scenario B exercises the
explicit form.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from apps.approvals import approval_kind
from apps.approvals.models import ApprovalRequest

from .models import PurchaseRequest

logger = logging.getLogger("smallstack.demo_purchasing")

KIND = "purchasing.approve"

# Terminal approval status → the PurchaseRequest state it produces. Every
# terminal status is present; a missing key would silently leave a row PENDING.
_STATE_FOR_STATUS: dict[str, str] = {
    ApprovalRequest.Status.APPROVED: PurchaseRequest.State.APPROVED,
    ApprovalRequest.Status.REJECTED: PurchaseRequest.State.REJECTED,
    ApprovalRequest.Status.CANCELED: PurchaseRequest.State.CANCELED,
    ApprovalRequest.Status.EXPIRED: PurchaseRequest.State.EXPIRED,
}


@approval_kind(
    KIND,
    label="Approve purchase request",
    description=(
        "Spend gate for the purchasing demo. Requests of $5,000 or more are "
        "routed to the finance approvers group; anything below that can be "
        "decided by any staff member. Approval mints a PO number."
    ),
    default_expires_in=timedelta(days=2),
)
def on_purchase_decision(req: Any) -> None:
    """React to ANY terminal transition of a purchasing.approve request."""
    pr = req.target
    if not isinstance(pr, PurchaseRequest):
        # Target deleted, or the row was filed without one — nothing to react to.
        return

    state = _STATE_FOR_STATUS.get(req.status)
    if state is None:  # pragma: no cover — services only calls us post-terminal
        logger.warning("purchasing.approve: non-terminal status %r", req.status)
        return

    fields = ["state", "decided_note", "updated_at"]
    pr.state = state
    pr.decided_note = req.decision_note

    if state == PurchaseRequest.State.APPROVED:
        # Arm: mint the PO. Idempotent — a retried decision keeps the first one.
        if not pr.po_number:
            pr.po_number = pr.mint_po_number()
            fields.append("po_number")
    elif pr.po_number:
        # Disarm on every non-approved outcome (docs §1: "if your kind arms
        # something at request time, disarm it on every non-approved status").
        pr.po_number = ""
        fields.append("po_number")

    pr.save(update_fields=fields)
