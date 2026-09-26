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
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import StatsAccessory

from . import permissions, services
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

    # Effective, not stored: an overdue row's column still reads "pending" until
    # a sweep flips it, and a queue badge saying "Pending" on a row nobody can
    # decide is the row-level half of F-29.
    status = obj.effective_status
    color = _STATUS_COLORS.get(status, "var(--body-quiet-color)")
    return format_html(
        '<span style="color: {}; font-weight: 600;">{}</span>',
        color,
        obj.effective_status_display,
    )


def _kind_label(value: Any, obj: ApprovalRequest) -> Any:
    kind = get_kind(obj.kind)
    return kind.label if kind else obj.kind


def _compact_dt(value: Any, obj: Any) -> Any:
    from datetime import datetime as _dt

    if not isinstance(value, _dt):
        return value
    return timezone.localtime(value).strftime("%b %-d, %-I:%M %p")


class ApprovalRequestCRUDView(CRUDView):
    """The approval queue + decision console host.

    **Login-gated, not staff-gated, and scoped by eligibility.** Every channel
    approvals owns hands a participant the same console URL — the "Approval
    needed" email, its bell row, the decision email and its bell row — and
    assignees may be non-staff by design. A staff-only console made all four of
    those links a 403 for exactly the people they were sent to (F-01), and made
    the REST/MCP surface write-without-read: a non-staff assignee could POST a
    decision but not GET the row (F-02).

    ``permissions.viewable_requests`` (existence-hiding: staff see everything,
    everyone else sees only rows they requested or are assigned) is applied in
    ``get_list_queryset``, which the HTML list, the REST list *and detail*, and
    the MCP list/get tools all route through — so one scoper governs every read.
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
    mixins = [LoginRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]
    filter_fields = ["status", "kind"]
    search_fields = ["title", "description", "kind"]

    enable_search = True
    search_display = "title"
    search_subtitle = "kind"
    # Search is the SIXTH read surface, and it was the one the eligibility scoper
    # never reached: `search_access` defaults to STAFF, so a non-staff assignee
    # standing on her own queue could open a request and decide it while global
    # search pretended it did not exist. Search is how a user with one bell row
    # and no sidebar entry actually finds anything. "One scoper governs every
    # read" has to be true of all six. (F-43.)
    search_access = "authenticated"

    @staticmethod
    def search_visibility(qs: Any, user: Any) -> Any:
        """The same eligibility scoper every other read surface uses.

        Staff and trusted-internal callers bypass this in the search engine, which
        matches ``permissions.viewable_requests``' own staff branch.
        """
        return permissions.viewable_requests(user, qs)

    enable_api = True
    api_extra_fields = [
        "status",
        "decided_by",
        "decided_at",
        "decision_note",
        # REST must show what REST accepts: `target_ref` is the same
        # "app_label.model:pk" spelling the create endpoint takes, and
        # `assignee_usernames` exposes an M2M the wire otherwise drops. Without
        # them a client could file against a row and render a label for it, but
        # never link back to it. (F-35.)
        "target_ref",
        "target_repr",
        "assignee_usernames",
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
                    # The SAME expression the ?status=pending filter uses, by
                    # construction — see ApprovalRequestQuerySet.
                    # for_effective_status. Not `status="pending"`: overdue rows
                    # are still stored as pending until a sweep flips them, so
                    # this card must agree with the dashboard widget (F-19) AND
                    # with the list beside it (F-29).
                    "value": lambda qs: qs.for_effective_status(
                        ApprovalRequest.Status.PENDING
                    ).count(),
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
    def apply_filter(cls, qs: Any, field_name: str, value: str, request: HttpRequest) -> Any:
        """``?status=`` selects the *effective* status, not the stored column.

        Expiry is lazy (§6), so an overdue row's ``status`` column still reads
        ``pending`` until a sweep flips it. With the stored column driving the
        filter, ``?status=pending`` listed 905 rows on a page whose own "Pending"
        stat card — correctly counting ``actionable()`` — said 5, and the filter
        was unusable as the "what needs a human" API it is documented to be.
        (F-29; the disagreement F-19 fixed between widget and card had simply
        moved one element to the right.)

        The card and this filter now evaluate the **same** two expressions:

        * ``?status=pending``  → ``actionable()``  (pending minus overdue)
        * ``?status=expired``  → stored ``expired`` **plus** ``overdue()``

        Everything else falls through to the generic exact-match handling. The
        stored column is left alone: flipping it here would be a write on a GET,
        and the sweep still owns the per-row fan-out.
        """
        if field_name != "status":
            return NotImplemented
        return qs.for_effective_status(value)

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        qs = permissions.viewable_requests(getattr(request, "user", None), qs)
        # Lazy expiry keeps the queue truthful even without the sweep worker —
        # BOUNDED, because the fan-out per row is expensive and an unbounded
        # backlog turned this page into a gateway timeout (F-12). The scheduled
        # sweep drains the rest and logs a warning when it is behind.
        #
        # Once per request: a single page render calls this hook several times
        # (the rows, the stat-card accessory, pagination), which multiplied the
        # bounded cost right back up.
        if not getattr(request, "_approvals_lazy_expired", False):
            try:
                request._approvals_lazy_expired = True  # type: ignore[attr-defined]
            except AttributeError:  # pragma: no cover — exotic request stand-ins
                pass
            services.mark_expired(qs, limit=services.lazy_expire_limit())
        return qs.select_related("requested_by", "decided_by")

    @classmethod
    def get_detail_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        # Same scoping, no sweep: a detail load must not pay for the whole
        # queue's expiry (decide() expires the single row it touches anyway).
        qs = permissions.viewable_requests(getattr(request, "user", None), qs)
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
