"""Template tags — kind-card resolution and the downstream embed.

{% approval_context req %} renders the kind-specific context card:
    1. the kind's explicit ``context_template``,
    2. ``approvals/kinds/<key with dots as dashes>.html`` (a downstream app's
       template dir wins by loader order),
    3. the shipped ``approvals/kinds/default.html`` (pretty JSON + target).

{% approval_card req %} is the embeddable decision card for downstream pages —
the calendar app drops it next to its schedule so an assignee (who may not be
staff) can decide without visiting the admin console.
"""

from __future__ import annotations

import json
from typing import Any

from django import template
from django.template.loader import select_template
from django.utils.safestring import mark_safe

from ..models import ApprovalRequest
from ..registry import get_kind

register = template.Library()


def _kind_templates(req: ApprovalRequest) -> list[str]:
    names: list[str] = []
    kind = get_kind(req.kind)
    if kind is not None and kind.context_template:
        names.append(kind.context_template)
    names.append(f"approvals/kinds/{req.kind.replace('.', '-')}.html")
    names.append("approvals/kinds/default.html")
    return names


@register.simple_tag(takes_context=True)
def approval_context(context: template.Context, req: ApprovalRequest) -> Any:
    tpl = select_template(_kind_templates(req))
    kind = get_kind(req.kind)
    pretty = json.dumps(req.context, indent=2, ensure_ascii=False) if req.context else ""
    return mark_safe(  # noqa: S308 — rendered template output
        tpl.render(
            {
                "req": req,
                "kind": kind,
                "context": req.context,
                "context_pretty": pretty,
                "target": req.target,
                "request": context.get("request"),
            }
        )
    )


@register.inclusion_tag("approvals/partials/request_card.html", takes_context=True)
def approval_card(context: template.Context, req: ApprovalRequest) -> dict[str, Any]:
    from .. import permissions

    user = getattr(context.get("request"), "user", None)
    return {
        "req": req,
        "can_decide": permissions.can_decide(user, req) if user else False,
        "can_cancel": permissions.can_cancel(user, req) if user else False,
        "request": context.get("request"),
        "csrf_token": context.get("csrf_token"),
    }


@register.simple_tag
def approval_can_decide(user: Any, req: ApprovalRequest) -> bool:
    from .. import permissions

    return permissions.can_decide(user, req)


@register.simple_tag
def approval_can_cancel(user: Any, req: ApprovalRequest) -> bool:
    from .. import permissions

    return permissions.can_cancel(user, req)
