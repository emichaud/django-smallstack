"""Scenario B views — the audit trail of what agents proposed.

There is deliberately NO decide surface here: the human decides in the shared
approvals console (`/smallstack/approvals/requests/`). This CRUDView is
read-mostly and exists so a staff reviewer (and an agent, over the enable_mcp
``list_agent_actions`` / ``get_agent_action`` tools) can see what was proposed,
what ran, and what it returned.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import StatsAccessory
from apps.smallstack.mixins import StaffRequiredMixin

from .models import AgentAction

_STATE_COLORS = {
    "proposed": "var(--body-quiet-color)",
    "pending": "var(--warning-fg)",
    "executed": "var(--success-fg)",
    "rejected": "var(--error-fg)",
    "expired": "var(--error-fg)",
    "canceled": "var(--body-quiet-color)",
    "failed": "var(--error-fg)",
}

_RISK_COLORS = {
    "low": "var(--body-quiet-color)",
    "medium": "var(--warning-fg)",
    "high": "var(--error-fg)",
}


def _state_badge(value: Any, obj: AgentAction) -> Any:
    color = _STATE_COLORS.get(obj.state, "var(--body-quiet-color)")
    return format_html('<span style="color: {}; font-weight: 600;">{}</span>', color, value)


def _risk_badge(value: Any, obj: AgentAction) -> Any:
    color = _RISK_COLORS.get(obj.risk, "var(--body-quiet-color)")
    return format_html(
        '<span style="color: {}; font-weight: 700; font-size: 0.78rem; '
        'letter-spacing: 0.04em; text-transform: uppercase;">{}</span>',
        color,
        value,
    )


def _compact_dt(value: Any, obj: Any) -> Any:
    """Short local timestamp — the approvals-console convention."""
    from datetime import datetime as _dt

    if not isinstance(value, _dt):
        return value
    return timezone.localtime(value).strftime("%b %-d, %-I:%M %p")


class AgentActionCRUDView(CRUDView):
    """Audit trail for agent-proposed actions (staff)."""

    model = AgentAction
    # No CREATE action: actions are proposed through the MCP tool / service, so
    # `fields` only feeds the REST serializer and the detail view.
    fields = ["tool_name", "payload", "risk", "requested_by_agent"]
    list_fields = ["tool_name", "risk", "state", "requested_by_agent", "executed_at", "created_at"]
    detail_fields = [
        "tool_name",
        "payload",
        "risk",
        "requested_by_agent",
        "state",
        "approval",
        "result",
        "executed_at",
        "created_at",
    ]
    link_field = "tool_name"
    field_transforms = {
        "state": _state_badge,
        "risk": _risk_badge,
        "created_at": _compact_dt,
        "executed_at": _compact_dt,
    }
    column_widths = {
        "tool_name": "22%",
        "risk": "10%",
        "state": "12%",
        "requested_by_agent": "20%",
        "executed_at": "14%",
        "created_at": "14%",
    }
    url_base = "demo/agentops/actions"
    paginate_by = 25
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]
    filter_fields = ["state", "risk", "tool_name"]
    search_fields = ["tool_name", "requested_by_agent", "result"]

    enable_api = True
    api_extra_fields = ["state", "result", "executed_at", "updated_at", "is_executed"]
    api_expand_fields = ["approval"]

    enable_mcp = True
    mcp_description = (
        "a privileged action an AI agent proposed, gated on human approval. "
        "state: proposed/pending/executed/rejected/expired/canceled/failed. "
        "Propose one with propose_agent_action; a human decides it in the "
        "SmallStack approvals console."
    )
    mcp_singular = "agent_action"
    mcp_plural = "agent_actions"

    enable_webhooks = True
    webhook_events = ["created", "updated"]

    list_accessories = [
        StatsAccessory(
            stats=[
                {
                    "label": "Awaiting a human",
                    "value": lambda qs: qs.filter(state="pending").count(),
                    "color": "var(--warning-fg)",
                },
                {
                    "label": "Executed",
                    "value": lambda qs: qs.filter(state="executed").count(),
                    "color": "var(--success-fg)",
                },
                {
                    "label": "Blocked",
                    "value": lambda qs: qs.filter(
                        state__in=["rejected", "expired", "canceled"]
                    ).count(),
                    "color": "var(--body-quiet-color)",
                },
                {
                    "label": "High risk",
                    "value": lambda qs: qs.filter(risk="high").count(),
                    "color": "var(--error-fg)",
                },
            ]
        )
    ]

    @classmethod
    def can_update(cls, obj: AgentAction, request: HttpRequest) -> bool:
        return False

    @classmethod
    def can_delete(cls, obj: AgentAction, request: HttpRequest) -> bool:
        return False

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        return qs.select_related("approval")
