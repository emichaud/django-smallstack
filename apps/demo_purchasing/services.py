"""Scenario A services — filing the approval, transport-agnostic.

``submit_for_approval`` is the ONLY way a PurchaseRequest leaves draft. Web,
REST and the harness all call it, so the tiered routing (and the audit source)
behaves identically everywhere.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest

from .models import FINANCE_GROUP, PurchaseRequest

logger = logging.getLogger("smallstack.demo_purchasing")


class AlreadySubmitted(Exception):
    """The request is not a draft any more."""


def finance_approvers() -> QuerySet:
    """Tier-2 approvers: members of the finance group (NON-staff in the demo).

    Deliberately a Group lookup rather than a settings constant — routing rules
    that name people belong in data, not in code.
    """
    return get_user_model().objects.filter(
        groups__name=FINANCE_GROUP, is_active=True
    ).order_by("username")


def submit_for_approval(
    pr: PurchaseRequest, *, actor: Any, source: str = "web"
) -> ApprovalRequest:
    """File the side-car approval for ``pr`` and move it to PENDING.

    Tiered routing happens here, at request time: high-value requests name the
    finance approvers as ``assignees`` (which narrows who may decide); anything
    below the threshold names nobody, so the default "any staff" policy applies.
    """
    if pr.state != PurchaseRequest.State.DRAFT:
        raise AlreadySubmitted(f"“{pr.description}” is already {pr.get_state_display().lower()}.")

    assignees = list(finance_approvers()) if pr.is_high_value else []
    if pr.is_high_value and not assignees:
        # Fail loudly rather than silently widening a $50k request to "any staff".
        logger.warning(
            "demo_purchasing: no members in %r — high-value request %s falls back "
            "to the any-staff policy",
            FINANCE_GROUP,
            pr.pk,
        )

    req = approvals.request_approval(
        kind="purchasing.approve",
        title=f"Purchase: {pr.description} (${pr.amount})",
        actor=actor,
        description=pr.justification,
        target=pr,
        context={
            "vendor": pr.vendor,
            "amount": f"{pr.amount:.2f}",
            "category": pr.get_category_display(),
            "justification": pr.justification,
            "tier": pr.tier,
            "requested_by": getattr(pr.requested_by, "username", ""),
        },
        assignees=assignees,
        source=source,
    )
    pr.approval = req
    pr.state = PurchaseRequest.State.PENDING
    pr.save(update_fields=["approval", "state", "updated_at"])
    return req


def can_review(user: Any, pr: PurchaseRequest) -> bool:
    """Who may open the requester-facing review page for ``pr``.

    Staff, the requester, or (the point of the page) an assignee of the linked
    approval — who may well be non-staff.
    """
    pk = getattr(user, "pk", None)
    if pk is None:
        return False
    if getattr(user, "is_staff", False) or pr.requested_by_id == pk:
        return True
    if pr.approval_id is None:
        return False
    return ApprovalRequest.objects.filter(pk=pr.approval_id, assignees__pk=pk).exists()
