"""Scenario C services — file an access request (the REST path's only logic)."""

from __future__ import annotations

from typing import Any

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest

from .models import AccessRequest


def file_access_request(
    *,
    resource: str,
    scope: str,
    reason: str,
    duration_hours: int,
    actor: Any,
    source: str = "REST API",
) -> tuple[AccessRequest, ApprovalRequest]:
    """Create the AccessRequest and the approval that points AT it.

    The generic REST filing endpoint
    (``POST /smallstack/api/approvals/requests/create/``) has no way to attach a
    ``target``, so a remote client that wants the approval linked to a business
    object needs a thin app endpoint like this one. See the README.
    """
    if scope not in AccessRequest.Scope.values:
        raise ValueError(f"scope must be one of {', '.join(AccessRequest.Scope.values)}")
    try:
        hours = int(duration_hours)
    except (TypeError, ValueError):
        raise ValueError("duration_hours must be an integer") from None
    if not 1 <= hours <= 720:
        raise ValueError("duration_hours must be between 1 and 720")
    if not resource.strip():
        raise ValueError("resource is required")

    ar = AccessRequest.objects.create(
        resource=resource.strip(),
        scope=scope,
        reason=reason,
        duration_hours=hours,
        state=AccessRequest.State.PENDING,
        requester=actor if getattr(actor, "pk", None) is not None else None,
    )
    req = approvals.request_approval(
        kind="access.grant",
        title=f"Access: {ar.resource} ({ar.get_scope_display().lower()}) for {hours}h",
        actor=actor,
        description=reason,
        target=ar,
        context={
            "resource": ar.resource,
            "scope": ar.scope,
            "duration_hours": hours,
            "reason": reason,
            "requester": getattr(actor, "username", ""),
        },
        source=source,
    )
    ar.approval = req
    ar.save(update_fields=["approval", "updated_at"])
    return ar, req
