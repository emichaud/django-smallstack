"""``{% access_membership_proposal req as plan %}``: the decision card's data,
read from the database rather than the request's free-form context."""

from __future__ import annotations

from typing import Any

from django import template

register = template.Library()


@register.simple_tag
def access_membership_proposal(req: Any) -> dict[str, Any]:
    from ..approvals import proposal

    return proposal(req)
