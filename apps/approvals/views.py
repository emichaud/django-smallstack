"""Approvals views — the queue CRUDView and the decide/cancel actions.

The CRUDView is read-only (LIST/DETAIL): requests are FILED through
``services.request_approval`` (Python/REST/MCP), never a CRUD form — a form
create would bypass signals, audit sourcing, and kind defaults. All state
changes route through the services layer, where eligibility lives.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import StatsAccessory
from apps.smallstack.mixins import StaffRequiredMixin

from . import services
from .models import ApprovalRequest
from .registry import get_kind

_STATUS_COLORS = {
    "pending": "var(--warning-fg)",
    "approved": "var(--success-fg)",
    "rejected": "var(--error-fg)",
    "canceled": "var(--body-quiet-color)",
    "expired": "var(--error-fg)",
}


def _status_badge(value: Any, obj: ApprovalRequest) -> Any:
    from django.utils.html import format_html

    color = _STATUS_COLORS.get(obj.status, "var(--body-quiet-color)")
    return format_html('<span style="color: {}; font-weight: 600;">{}</span>', color, value)


def _kind_label(value: Any, obj: ApprovalRequest) -> Any:
    kind = get_kind(obj.kind)
    return kind.label if kind else obj.kind


def _compact_dt(value: Any, obj: Any) -> Any:
    from datetime import datetime as _dt

    if not isinstance(value, _dt):
        return value
    return timezone.localtime(value).strftime("%b %-d, %-I:%M %p")


class ApprovalRequestCRUDView(CRUDView):
    """The approval queue + decision console host (staff pages).

    Non-staff assignees don't browse here — they decide via the
    {% approval_card %} embed or an emailed console link (the decide POST
    endpoint itself is eligibility-gated, not staff-gated).
    """

    model = ApprovalRequest
    # Writable fields (a CRUD form is never exposed — actions below — but the
    # REST serializer derives from this list): state fields deliberately absent.
    fields = ["kind", "title", "description", "context", "expires_at"]
    list_fields = ["title", "kind", "status", "requested_by", "expires_at", "created_at"]
    detail_fields = [
        "kind",
        "title",
        "description",
        "target_repr",
        "requested_by",
        "status",
        "decided_by",
        "decided_at",
        "decision_note",
        "expires_at",
        "created_at",
    ]
    link_field = "title"
    field_transforms = {
        "status": _status_badge,
        "kind": _kind_label,
        "created_at": _compact_dt,
        "expires_at": _compact_dt,
    }
    column_widths = {"title": "30%", "kind": "16%", "status": "11%"}
    url_base = "approvals/requests"
    paginate_by = 25
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]
    filter_fields = ["status", "kind"]
    search_fields = ["title", "description", "kind"]

    enable_search = True
    search_display = "title"
    search_subtitle = "kind"

    enable_api = True
    api_extra_fields = [
        "status",
        "decided_by",
        "decided_at",
        "decision_note",
        "target_repr",
        "callback_error",
        "created_at",
        "updated_at",
    ]
    api_expand_fields = ["requested_by", "decided_by"]

    enable_mcp = True
    mcp_description = (
        "a human-approval request — the side-car gate apps file before doing "
        "something sensitive. status: pending/approved/rejected/canceled/expired. "
        "File one with the request_approval tool; decide with decide_approval."
    )
    mcp_singular = "approval"
    mcp_plural = "approvals"

    enable_webhooks = True
    webhook_events = ["created", "updated"]  # decisions ride .updated (data.status)

    list_accessories = [
        StatsAccessory(
            stats=[
                {
                    "label": "Pending",
                    "value": lambda qs: qs.filter(status="pending").count(),
                    "color": "var(--warning-fg)",
                },
                {
                    "label": "Approved · 7d",
                    "value": lambda qs: qs.filter(
                        status="approved",
                        decided_at__gte=timezone.now() - timedelta(days=7),
                    ).count(),
                    "color": "var(--success-fg)",
                },
                {
                    "label": "Rejected · 7d",
                    "value": lambda qs: qs.filter(
                        status="rejected",
                        decided_at__gte=timezone.now() - timedelta(days=7),
                    ).count(),
                    "color": "var(--error-fg)",
                },
            ]
        )
    ]

    @classmethod
    def can_update(cls, obj: ApprovalRequest, request: HttpRequest) -> bool:
        return False  # defense in depth — no UPDATE action exists either

    @classmethod
    def can_delete(cls, obj: ApprovalRequest, request: HttpRequest) -> bool:
        return False

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        # Lazy expiry keeps the queue truthful even without the sweep worker.
        services.mark_expired(qs)
        return qs.select_related("requested_by", "decided_by")


@require_POST
def decide_request(request: HttpRequest, pk: int) -> HttpResponse:
    """Approve/reject. Authenticated-only here; ELIGIBILITY lives in the
    service (assignees may be non-staff — that's why this isn't staff-gated).
    """
    if not request.user.is_authenticated:
        return HttpResponse(status=403)
    req = get_object_or_404(ApprovalRequest, pk=pk)
    approved = request.POST.get("decision") == "approve"
    try:
        services.decide(
            req,
            actor=request.user,
            approved=approved,
            note=request.POST.get("note", "").strip(),
            source="web",
        )
        messages.success(
            request, f"“{req.title}” {'approved' if approved else 'rejected'}."
        )
    except services.NotEligible:
        return HttpResponse(status=403)
    except services.NotPending as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect("approvals/requests-detail", pk=pk)


@require_POST
def cancel_request(request: HttpRequest, pk: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return HttpResponse(status=403)
    req = get_object_or_404(ApprovalRequest, pk=pk)
    try:
        services.cancel(
            req, actor=request.user, note=request.POST.get("note", "").strip(), source="web"
        )
        messages.success(request, f"“{req.title}” canceled.")
    except services.NotEligible:
        return HttpResponse(status=403)
    except services.NotPending as exc:
        messages.error(request, str(exc))
    return redirect("approvals/requests-detail", pk=pk)
