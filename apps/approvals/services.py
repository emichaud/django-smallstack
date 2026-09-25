"""Approval services — transport-agnostic; Web, REST, MCP, and the CLI all
call these functions, so behavior is identical everywhere (runbook service
convention).

``status`` / ``decided_*`` are written ONLY here. Every terminal transition
uses the same race-safe conditional UPDATE (the scheduler tick's claim
pattern): exactly one of two simultaneous decisions wins; the loser gets a
clean ``NotPending``.

The kind callback runs post-claim and NEVER breaks the decision — a failure
lands in ``callback_error`` for the console to surface.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta
from typing import Any, Sequence

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.smallstack.audit import ADDITION, CHANGE, log_write

from . import permissions
from .models import ApprovalRequest
from .registry import get_kind, resolve_on_decision
from .signals import approval_decided, approval_requested

logger = logging.getLogger("smallstack.approvals")

Actor = permissions.Actor


class ApprovalError(Exception):
    """Base for approval failures."""


class NotEligible(ApprovalError):
    """The actor may not perform this transition (→ 403 on HTTP surfaces)."""


class NotPending(ApprovalError):
    """The request is already decided/canceled/expired (→ 409 on REST)."""


class UnknownKind(ApprovalError):
    """Filing with a kind no app registered (→ 400 on HTTP surfaces)."""


def request_approval(
    *,
    kind: str,
    title: str,
    actor: Actor,
    description: str = "",
    context: dict[str, Any] | None = None,
    target: models.Model | None = None,
    assignees: Sequence[Any] | None = None,
    expires_at: datetime | None = None,
    expires_in: timedelta | None = None,
    require_known_kind: bool = False,
    source: str = "web",
) -> ApprovalRequest:
    """File a new approval request.

    Expiry precedence: explicit ``expires_at`` → ``expires_in`` → the kind's
    ``default_expires_in`` → SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES
    (0 = never). Unregistered kinds are allowed by default (rows must outlive
    code churn); pass ``require_known_kind=True`` on surfaces where a typo is
    likelier than a plan (REST/MCP do).
    """
    kind_def = get_kind(kind)
    if require_known_kind and kind_def is None:
        from .registry import known_keys

        known = ", ".join(known_keys()) or "(none registered)"
        raise UnknownKind(f"Unknown approval kind {kind!r}. Known kinds: {known}")

    if expires_at is None:
        if expires_in is None and kind_def is not None:
            expires_in = kind_def.default_expires_in
        if expires_in is None:
            default_minutes = int(
                getattr(settings, "SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES", 0)
            )
            if default_minutes > 0:
                expires_in = timedelta(minutes=default_minutes)
        if expires_in is not None:
            expires_at = timezone.now() + expires_in

    req = ApprovalRequest(
        kind=kind,
        title=title[:200],
        description=description,
        context=context or {},
        requested_by=actor if getattr(actor, "pk", None) is not None else None,
        expires_at=expires_at,
    )
    req.set_target(target)
    req.save()
    if assignees:
        req.assignees.set([u for u in assignees if getattr(u, "pk", None) is not None])

    log_write(actor, req, ADDITION, source)
    transaction.on_commit(
        lambda: approval_requested.send(
            sender=ApprovalRequest, request=req, actor=actor
        )
    )
    return req


def _claim(req: ApprovalRequest, **fields: Any) -> None:
    """Atomically transition a PENDING row; raise NotPending if we lost."""
    updated = ApprovalRequest.objects.filter(
        pk=req.pk, status=ApprovalRequest.Status.PENDING
    ).update(**fields)
    if not updated:
        req.refresh_from_db()
        raise NotPending(f"This request is already {req.get_status_display().lower()}.")
    req.refresh_from_db()


def _run_callback(req: ApprovalRequest) -> None:
    """Run the kind's on_decision callback; never raises. A failure is stored
    in callback_error so the console can surface it."""
    callback = resolve_on_decision(get_kind(req.kind))
    if callback is None:
        return
    try:
        callback(req)
    except Exception:  # noqa: BLE001 — the decision stands regardless
        logger.exception("approvals: on_decision failed for %s (%s)", req.pk, req.kind)
        ApprovalRequest.objects.filter(pk=req.pk).update(
            callback_error=traceback.format_exc()[-2000:]
        )
        req.refresh_from_db()


def _finish(req: ApprovalRequest, *, actor: Actor, source: str) -> ApprovalRequest:
    _run_callback(req)
    # The claim wrote via queryset .update(), which fires no post_save — but a
    # terminal transition is exactly the event outside observers exist for
    # (webhooks emit `<label>.approvalrequest.updated`, search reindexes).
    # Re-save the claimed fields so every post_save tap sees it; the race was
    # already settled by the conditional UPDATE, so this is single-winner code.
    req.save(
        update_fields=[
            "status",
            "decided_by",
            "decided_at",
            "decision_note",
            "callback_error",
            "updated_at",
        ]
    )
    log_write(actor, req, CHANGE, source)
    transaction.on_commit(
        lambda: approval_decided.send(
            sender=ApprovalRequest, request=req, actor=actor, source=source
        )
    )
    return req


def decide(
    req: ApprovalRequest,
    *,
    actor: Actor,
    approved: bool,
    note: str = "",
    source: str = "web",
) -> ApprovalRequest:
    """Approve or reject a pending request (eligibility enforced here)."""
    if req.is_overdue:
        # Lazily expire rather than letting a decision land on a dead request.
        _claim(req, status=ApprovalRequest.Status.EXPIRED, decided_at=timezone.now())
        _finish(req, actor=None, source="expiry")
        raise NotPending("This request expired before it was decided.")

    if not req.is_pending:
        # Ordering matters for the error a caller sees: "already approved" is
        # actionable; "not eligible" on a decided row would be misleading.
        raise NotPending(f"This request is already {req.get_status_display().lower()}.")
    if not permissions.can_decide(actor, req):
        raise NotEligible("You are not eligible to decide this request.")

    _claim(
        req,
        status=(
            ApprovalRequest.Status.APPROVED if approved else ApprovalRequest.Status.REJECTED
        ),
        decided_by=actor,
        decided_at=timezone.now(),
        decision_note=note,
    )
    return _finish(req, actor=actor, source=source)


def approve(req: ApprovalRequest, *, actor: Actor, note: str = "", source: str = "web") -> ApprovalRequest:
    return decide(req, actor=actor, approved=True, note=note, source=source)


def reject(req: ApprovalRequest, *, actor: Actor, note: str = "", source: str = "web") -> ApprovalRequest:
    return decide(req, actor=actor, approved=False, note=note, source=source)


def cancel(
    req: ApprovalRequest, *, actor: Actor, note: str = "", source: str = "web"
) -> ApprovalRequest:
    """Withdraw a pending request (requester or staff)."""
    if not permissions.can_cancel(actor, req):
        raise NotEligible("Only the requester or staff can cancel this request.")
    _claim(
        req,
        status=ApprovalRequest.Status.CANCELED,
        decided_by=actor,
        decided_at=timezone.now(),
        decision_note=note,
    )
    return _finish(req, actor=actor, source=source)


def mark_expired(qs: models.QuerySet | None = None) -> int:
    """Expire overdue pending requests. Race-safe per row; the kind callback
    and the decided signal fire for each (with actor=None, source='expiry')."""
    if qs is None:
        qs = ApprovalRequest.objects.all()
    now = timezone.now()
    overdue_ids = list(
        qs.filter(
            status=ApprovalRequest.Status.PENDING, expires_at__isnull=False, expires_at__lte=now
        ).values_list("pk", flat=True)
    )
    expired = 0
    for pk in overdue_ids:
        updated = ApprovalRequest.objects.filter(
            pk=pk, status=ApprovalRequest.Status.PENDING
        ).update(status=ApprovalRequest.Status.EXPIRED, decided_at=now)
        if updated:
            expired += 1
            req = ApprovalRequest.objects.get(pk=pk)
            _finish(req, actor=None, source="expiry")
    return expired


def pending_for(user: Actor) -> models.QuerySet:
    """The user's decision queue (lazily expires overdue rows first)."""
    mark_expired()
    qs = ApprovalRequest.objects.filter(status=ApprovalRequest.Status.PENDING)
    return permissions.viewable_requests(user, qs)
