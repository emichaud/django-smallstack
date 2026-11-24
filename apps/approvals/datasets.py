"""Bundled dataset for approvals: every request filed through the gate."""

from __future__ import annotations

from django.db.models import QuerySet
from django.http import HttpRequest

from apps.calendar import register_calendar
from apps.datasets.framework import framework_dataset

from .models import ApprovalRequest
from .permissions import viewable_requests


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
def approval_requests(request: HttpRequest | None = None) -> QuerySet[ApprovalRequest]:
    qs = ApprovalRequest.objects.select_related("requested_by", "decided_by")
    user = getattr(request, "user", None)
    if user is None:
        return qs  # an internal caller (a report, a test), not a person
    # The rows a person may see: the same scoper as every approvals read,
    # so a kind's view_permission holds here and on the calendar (G3-2).
    return viewable_requests(user, qs)


# ---------------------------------------------------------------------------
# Calendar protocol
# ---------------------------------------------------------------------------

register_calendar(
    "smallstack_approval_requests",
    start="expires_at",
    title="title",
    subtitle="kind",
    status=lambda r: {
        ApprovalRequest.Status.PENDING: "warning",
        ApprovalRequest.Status.APPROVED: "success",
        ApprovalRequest.Status.REJECTED: "danger",
        ApprovalRequest.Status.EXPIRED: "danger",
    }.get(r.status),
    label="Approval deadlines",
    description="Approval requests on the day they expire — amber while pending, green/red once decided.",
)
