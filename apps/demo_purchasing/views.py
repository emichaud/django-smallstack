"""Scenario A views — the staff console, the submit action, and the embed page.

Two surfaces on purpose:

* ``PurchaseRequestCRUDView`` — the staff-facing list/detail (StaffRequiredMixin).
* ``PurchaseRequestReviewView`` — LoginRequired, NOT staff-gated. This is the
  page a non-staff finance approver opens to decide in place via
  ``{% approval_card req %}`` (docs/skills/approvals.md §5).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from django.views.generic import DetailView

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import StatsAccessory
from apps.smallstack.mixins import StaffRequiredMixin

from . import services
from .models import HIGH_VALUE_THRESHOLD, PurchaseRequest

_STATE_COLORS = {
    "draft": "var(--body-quiet-color)",
    "pending": "var(--warning-fg)",
    "approved": "var(--success-fg)",
    "rejected": "var(--error-fg)",
    "expired": "var(--error-fg)",
    "canceled": "var(--body-quiet-color)",
}


def _state_badge(value: Any, obj: PurchaseRequest) -> Any:
    color = _STATE_COLORS.get(obj.state, "var(--body-quiet-color)")
    return format_html('<span style="color: {}; font-weight: 600;">{}</span>', color, value)


def _money(value: Any, obj: PurchaseRequest) -> Any:
    return f"${value:,.2f}" if value is not None else ""


def _compact_dt(value: Any, obj: Any) -> Any:
    """Short local timestamp — the approvals-console convention."""
    from datetime import datetime as _dt

    if not isinstance(value, _dt):
        return value
    return timezone.localtime(value).strftime("%b %-d, %-I:%M %p")


class PurchaseRequestCRUDView(CRUDView):
    """Staff console for the purchasing demo.

    CREATE/UPDATE stay enabled so a staff member can raise a draft in the UI,
    but the state machine is not editable here: ``fields`` deliberately omits
    ``state`` / ``po_number`` / ``decided_note`` — only the approval callback
    writes those.
    """

    model = PurchaseRequest
    fields = ["vendor", "description", "amount", "category", "justification", "requested_by"]
    list_fields = ["description", "vendor", "amount", "category", "state", "po_number", "created_at"]
    detail_fields = [
        "vendor",
        "description",
        "amount",
        "category",
        "justification",
        "state",
        "requested_by",
        "approval",
        "po_number",
        "decided_note",
        "created_at",
    ]
    link_field = "description"
    field_transforms = {"state": _state_badge, "amount": _money, "created_at": _compact_dt}
    column_widths = {
        "description": "22%",
        "vendor": "14%",
        "amount": "12%",
        "category": "11%",
        "state": "11%",
        "po_number": "11%",
        "created_at": "15%",
    }
    url_base = "demo/purchasing/requests"
    paginate_by = 25
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE]
    filter_fields = ["state", "category"]
    search_fields = ["vendor", "description", "justification"]

    enable_api = True
    api_extra_fields = ["state", "po_number", "decided_note", "is_high_value", "tier", "updated_at"]
    api_expand_fields = ["requested_by", "approval"]

    enable_webhooks = True
    webhook_events = ["created", "updated"]

    breadcrumb_parent = None

    list_accessories = [
        StatsAccessory(
            stats=[
                {
                    "label": "Drafts",
                    "value": lambda qs: qs.filter(state="draft").count(),
                    "color": "var(--body-quiet-color)",
                },
                {
                    "label": "Pending",
                    "value": lambda qs: qs.filter(state="pending").count(),
                    "color": "var(--warning-fg)",
                },
                {
                    "label": "Approved · 7d",
                    "value": lambda qs: qs.filter(
                        state="approved", updated_at__gte=timezone.now() - timedelta(days=7)
                    ).count(),
                    "color": "var(--success-fg)",
                },
                {
                    "label": f"≥ ${HIGH_VALUE_THRESHOLD:,.0f} pending",
                    "value": lambda qs: qs.filter(
                        state="pending", amount__gte=HIGH_VALUE_THRESHOLD
                    ).count(),
                    "color": "var(--primary)",
                },
            ]
        )
    ]

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        return qs.select_related("requested_by", "approval")

    @classmethod
    def on_form_valid(cls, request: Any, form: Any, obj: Any, is_create: Any = False) -> None:
        """Default the requester to the caller when they didn't name one.

        This hook now fires on EVERY create/update path. It used to be called
        only from REST / MCP / bulk-update / `sc` — the HTML CreateView and
        UpdateView never did, so a field set everywhere else was silently
        dropped in the UI (F-05, fixed in `apps/smallstack/crud.py`).
        `requested_by` is kept in `fields` so the web form can still name
        someone else explicitly.
        """
        if is_create and obj.requested_by_id is None:
            obj.requested_by_id = getattr(request.user, "pk", None)
            obj.save(update_fields=["requested_by"])


@require_POST
def submit_purchase_request(request: HttpRequest, pk: int) -> HttpResponse:
    """"Send for approval" — files the ApprovalRequest through the service.

    The scenario app NEVER constructs an ApprovalRequest itself; routing and
    expiry defaults live in ``services.submit_for_approval``.
    """
    if not request.user.is_authenticated:
        return HttpResponse(status=403)
    pr = get_object_or_404(PurchaseRequest, pk=pk)
    if not (request.user.is_staff or pr.requested_by_id == request.user.pk):
        return HttpResponse(status=403)
    try:
        req = services.submit_for_approval(pr, actor=request.user, source="web")
    except services.AlreadySubmitted as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Sent for approval (#{req.pk}) — routed to "
            f"{'the finance approvers' if pr.is_high_value else 'any staff approver'}.",
        )
    return redirect("demo_purchasing_review", pk=pr.pk)


class PurchaseRequestReviewView(LoginRequiredMixin, DetailView):
    """Requester/assignee-facing page that embeds the decision card.

    LoginRequired but NOT staff-gated: a non-staff finance approver decides
    here. Per-object access is ``services.can_review``.
    """

    model = PurchaseRequest
    template_name = "demo_purchasing/purchaserequest_review.html"
    context_object_name = "pr"

    def get_object(self, queryset: Any = None) -> Any:
        pr = super().get_object(queryset)
        if not services.can_review(self.request.user, pr):
            raise PermissionDenied("You may not review this purchase request.")
        return pr

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["approval"] = self.object.approval
        return ctx
