"""Scenario C views — the staff console for elevated-access requests.

Filing is REST-only in this scenario (see api.py); there is no CREATE action
here on purpose. Deciding happens in the shared approvals console or over
``POST /smallstack/api/approvals/requests/<id>/decide/``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import StatsAccessory
from apps.smallstack.mixins import StaffRequiredMixin

from .models import AccessRequest, WebhookEcho

_STATE_COLORS = {
    "pending": "var(--warning-fg)",
    "granted": "var(--success-fg)",
    "rejected": "var(--error-fg)",
    "expired": "var(--error-fg)",
    "revoked": "var(--error-fg)",
    "canceled": "var(--body-quiet-color)",
}


def _state_badge(value: Any, obj: AccessRequest) -> Any:
    color = _STATE_COLORS.get(obj.state, "var(--body-quiet-color)")
    return format_html('<span style="color: {}; font-weight: 600;">{}</span>', color, value)


def _compact_dt(value: Any, obj: Any) -> Any:
    """Short local timestamp — the approvals-console convention."""
    from datetime import datetime as _dt

    if not isinstance(value, _dt):
        return value
    return timezone.localtime(value).strftime("%b %-d, %-I:%M %p")


class AccessRequestCRUDView(CRUDView):
    """Staff console + REST/poll surface for elevated-access requests."""

    model = AccessRequest
    fields = ["resource", "scope", "reason", "duration_hours", "requester"]
    list_fields = ["resource", "scope", "duration_hours", "state", "granted_until", "created_at"]
    detail_fields = [
        "resource",
        "scope",
        "reason",
        "duration_hours",
        "state",
        "requester",
        "approval",
        "granted_until",
        "created_at",
    ]
    link_field = "resource"
    field_transforms = {
        "state": _state_badge,
        "created_at": _compact_dt,
        "granted_until": _compact_dt,
    }
    column_widths = {
        "resource": "26%",
        "scope": "10%",
        "duration_hours": "12%",
        "state": "12%",
        "granted_until": "18%",
        "created_at": "16%",
    }
    url_base = "demo/access/requests"
    paginate_by = 25
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]
    filter_fields = ["state", "scope"]
    search_fields = ["resource", "reason"]

    enable_api = True
    api_extra_fields = ["state", "granted_until", "is_active_grant", "updated_at"]
    api_expand_fields = ["requester", "approval"]

    enable_webhooks = True
    webhook_events = ["created", "updated"]

    list_accessories = [
        StatsAccessory(
            stats=[
                {
                    "label": "Pending",
                    "value": lambda qs: qs.filter(state="pending").count(),
                    "color": "var(--warning-fg)",
                },
                {
                    "label": "Granted",
                    "value": lambda qs: qs.filter(state="granted").count(),
                    "color": "var(--success-fg)",
                },
                {
                    "label": "Admin scope",
                    "value": lambda qs: qs.filter(scope="admin").count(),
                    "color": "var(--primary)",
                },
                {
                    "label": "Refused",
                    "value": lambda qs: qs.filter(
                        state__in=["rejected", "expired", "canceled", "revoked"]
                    ).count(),
                    "color": "var(--error-fg)",
                },
            ]
        )
    ]

    @classmethod
    def can_update(cls, obj: AccessRequest, request: HttpRequest) -> bool:
        return False

    @classmethod
    def can_delete(cls, obj: AccessRequest, request: HttpRequest) -> bool:
        return False

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        return qs.select_related("requester", "approval")


class WebhookEchoCRUDView(CRUDView):
    """The local webhook receiver's inbox — what actually arrived, in order."""

    model = WebhookEcho
    fields = ["event_type", "approval_id", "status", "title", "payload"]
    list_fields = ["received_at", "event_type", "approval_id", "status", "title"]
    detail_fields = ["event_type", "approval_id", "status", "title", "payload", "received_at"]
    link_field = "event_type"
    field_transforms = {"received_at": _compact_dt}
    column_widths = {"received_at": "16%", "event_type": "34%", "status": "12%"}
    url_base = "demo/access/webhook-echoes"
    paginate_by = 50
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]
    filter_fields = ["event_type", "status"]
    search_fields = ["event_type", "title", "status"]

    enable_api = True
    api_extra_fields = ["received_at"]

    @classmethod
    def can_update(cls, obj: WebhookEcho, request: HttpRequest) -> bool:
        return False

    @classmethod
    def can_delete(cls, obj: WebhookEcho, request: HttpRequest) -> bool:
        return False
