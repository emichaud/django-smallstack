"""Bundled dataset for approvals: every request filed through the gate."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import ApprovalRequest


@framework_dataset(
    "smallstack_approval_requests",
    label="Approval requests",
    description=(
        "Every approval request: kind, title, target, who asked, who decided, the decision and its "
        "timing. The context payload is left out."
    ),
    columns=[
        "created_at",
        "kind",
        "title",
        "target_repr",
        "requested_by",
        "status",
        "decided_by",
        "decided_at",
        "expires_at",
        "updated_at",
    ],
    filterable=["created_at", "kind", "requested_by", "status", "decided_by", "decided_at", "expires_at"],
)
def approval_requests() -> QuerySet[ApprovalRequest]:
    return ApprovalRequest.objects.select_related("requested_by", "decided_by")
