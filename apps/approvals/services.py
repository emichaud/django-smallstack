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

from apps.smallstack.audit import ADDITION, CHANGE, log_system_write, log_write
from apps.smallstack.exceptions import FeatureDisabled

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


class TooManyPending(ApprovalError):
    """The requester already has the maximum pending requests for this kind
    (→ 429 on REST/MCP). The abuse model is an agent token in a loop: without a
    cap one identity can bury every approver's bell and mailbox, which defeats
    the gate by fatigue rather than by a bug. (F-18.)"""


class ApprovalsDisabled(ApprovalError, FeatureDisabled):
    """SMALLSTACK_APPROVALS_ENABLED is off — the app is dark (→ 503).

    Also a :class:`~apps.smallstack.exceptions.FeatureDisabled`, so **any**
    ``@api_view`` endpoint that calls into approvals degrades to a 503 with the
    standard envelope instead of a 500. Approvals' own routes are unmounted when
    the switch is off, so this is the only way the 503 is ever observable. (F-31.)
    """


def enabled() -> bool:
    """The master switch. When off, the URLs are not mounted (see
    ``apps/smallstack/site_urls.py``), the sweep job is not registered, and
    every state-changing service call raises :class:`ApprovalsDisabled` rather
    than half-working with the fan-out silently dead. (F-11.)"""
    return bool(getattr(settings, "SMALLSTACK_APPROVALS_ENABLED", True))


def _require_enabled() -> None:
    if not enabled():
        raise ApprovalsDisabled(
            "Approvals is disabled (SMALLSTACK_APPROVALS_ENABLED=False): no "
            "request can be filed or decided, and nothing would be notified."
        )


def _check_pending_cap(*, kind: str, actor: Actor) -> None:
    cap = int(getattr(settings, "SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER", 50))
    actor_pk = getattr(actor, "pk", None)
    if cap <= 0 or actor_pk is None:  # 0 = no cap
        return
    outstanding = ApprovalRequest.objects.actionable().filter(
        requested_by_id=actor_pk, kind=kind
    ).count()
    if outstanding >= cap:
        raise TooManyPending(
            f"You already have {outstanding} pending {kind!r} requests "
            f"(limit {cap}). Wait for them to be decided or raise "
            "SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER."
        )


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
    _require_enabled()
    _check_pending_cap(kind=kind, actor=actor)
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
    if getattr(actor, "pk", None) is None:
        # Expiry has no human actor; without this the one terminal outcome
        # nobody caused was also the one with no audit row. (F-15.)
        log_system_write(req, CHANGE, source)
    else:
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
    _require_enabled()
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
    _require_enabled()
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


def lazy_expire_limit() -> int:
    """How many overdue rows an interactive page-load may expire itself.

    Expiring a row is not free: it runs the kind callback, re-saves, audits,
    fires ``approval_decided``, writes in-app notifications, queues an email and
    fans out a webhook delivery — roughly 20 queries per row. Unbounded, the
    first visitor after a backlog paid the whole bill inside their GET
    (200 overdue rows = 4,017 queries / 0.57 s; 1,000 rows = 2.8 s). Bounded, the
    page stays responsive and the scheduled sweep drains the remainder. (F-12.)
    """
    return int(getattr(settings, "SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT", 25))


def mark_expired(qs: models.QuerySet | None = None, *, limit: int | None = None) -> int:
    """Expire overdue pending requests. Race-safe per row; the kind callback
    and the decided signal fire for each (with actor=None, source='expiry').

    ``limit`` caps how many rows this call processes (oldest expiry first) — the
    interactive surfaces pass :func:`lazy_expire_limit`; the scheduled sweep
    passes nothing and drains everything. When a bounded call leaves rows
    behind it logs a warning naming the backlog, because a silently-truncated
    sweep is exactly the state an operator needs to know about.
    """
    if qs is None:
        qs = ApprovalRequest.objects.all()
    now = timezone.now()
    overdue = qs.filter(
        status=ApprovalRequest.Status.PENDING,
        expires_at__isnull=False,
        expires_at__lte=now,
    ).order_by("expires_at")
    if limit is not None and limit >= 0:
        overdue_ids = list(overdue.values_list("pk", flat=True)[: limit + 1])
        truncated = len(overdue_ids) > limit
        overdue_ids = overdue_ids[:limit]
    else:
        overdue_ids = list(overdue.values_list("pk", flat=True))
        truncated = False
    expired = 0
    for pk in overdue_ids:
        updated = ApprovalRequest.objects.filter(
            pk=pk, status=ApprovalRequest.Status.PENDING
        ).update(status=ApprovalRequest.Status.EXPIRED, decided_at=now)
        if updated:
            expired += 1
            req = ApprovalRequest.objects.get(pk=pk)
            _finish(req, actor=None, source="expiry")
    if truncated:
        logger.warning(
            "approvals: lazy expiry capped at %s rows — overdue requests remain. "
            "Run the 'Approvals: expire overdue requests' job (a db_worker on the "
            "default queue) or raise SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT.",
            limit,
        )
    return expired


def pending_for(user: Actor) -> models.QuerySet:
    """The user's decision queue.

    Reads the *actionable* set (pending minus overdue) so the answer is correct
    without paying for a sweep; the scheduled job and the queue view flip the
    overdue rows' stored status.
    """
    return permissions.viewable_requests(user, ApprovalRequest.objects.actionable())
