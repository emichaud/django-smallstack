"""Signal receivers — fan a request/decision out to the in-app bell and email.

Connected by ApprovalsConfig.ready() (import side effect). Runbook triple:
signal → receiver enqueues a task on the ``email`` queue. Both channels are
best-effort by construction.

**Email needs a worker.** ``enqueue()`` on the shipped ``DatabaseBackend``
inserts a row and returns; it does not raise, so an exception-triggered "inline
fallback" never fired and a default install sent *no* approval email at all,
silently. The queue is the right design — a decision must not wait on SMTP —
so the fix is to make the dependency visible instead of guessing: this module
logs a warning the first time it queues mail on a backend that needs a worker,
``apps/approvals/monitors.py`` exposes the backlog as a status monitor, and the
docs say plainly that mail requires a ``db_worker`` on the ``email`` queue.
Set ``SMALLSTACK_APPROVALS_EMAILS_INLINE = True`` to send in the request path
instead (the default in DEBUG). (F-07.)
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.dispatch import receiver

from . import signals

logger = logging.getLogger("smallstack.approvals")

# One warning per process, not per request — this is an operator-configuration
# fact, so repeating it per decision would just be noise.
_warned_about_worker = False


def subject_key(req: Any) -> str:
    """The notifications handle for one request, so its rows can be retired."""
    return f"approvals.request:{req.pk}"


def _emails_inline() -> bool:
    """Send mail in the request path instead of queueing it.

    Defaults to ``DEBUG`` so ``make run`` demos and test settings actually
    deliver; production keeps the queue (and needs the worker).
    """
    configured = getattr(settings, "SMALLSTACK_APPROVALS_EMAILS_INLINE", None)
    if configured is None:
        return bool(getattr(settings, "DEBUG", False))
    return bool(configured)


def _warn_needs_worker() -> None:
    global _warned_about_worker
    if _warned_about_worker:
        return
    _warned_about_worker = True
    logger.warning(
        "approvals: approval email queued on the 'email' task queue — nothing is "
        "sent until a worker drains it (`manage.py db_worker --queue-name email`). "
        "Set SMALLSTACK_APPROVALS_EMAILS_INLINE=True to send in-process instead."
    )


def _enqueue(task: Any, inline: Any, pk: int) -> None:
    """Queue the mail, or send it inline when configured to.

    Note the fallback is *capability-based*, not exception-based: with a
    database-backed queue ``enqueue()`` succeeds whether or not a worker will
    ever run it, so "it didn't raise" proves nothing about delivery.
    """
    # The email channel being OFF has to be decided here, not only inside
    # send_requested/send_decided. Those run on the worker, so with the channel
    # off and no worker the tasks pile up READY forever — and the fanout monitor
    # counts exactly those rows, so it sat permanently DOWN telling an operator
    # to start a mail worker they had deliberately chosen not to run. Worse,
    # UPGRADING.md offers EMAILS_ENABLED=False as the remedy for that very
    # symptom. Nothing to send ⇒ nothing to queue. (Test round 2026-09-26, E1.)
    if not getattr(settings, "SMALLSTACK_APPROVALS_EMAILS_ENABLED", True):
        return

    if _emails_inline():
        try:
            inline(pk)
        except Exception:  # noqa: BLE001 — email must never break the transition
            logger.exception("approvals: inline email failed for %s", pk)
        return
    try:
        task.enqueue(pk)
    except Exception:  # noqa: BLE001 — no queue at all ⇒ run inline
        try:
            inline(pk)
        except Exception:  # noqa: BLE001
            logger.exception("approvals: notify fan-out failed for %s", pk)
    else:
        _warn_needs_worker()


@receiver(signals.approval_requested, dispatch_uid="approvals_notify_on_request")
def notify_on_request(sender: Any, request: Any, actor: Any, **kwargs: Any) -> None:
    # In-app bell for the eligible deciders (synchronous — one bulk INSERT,
    # and notify() never raises).
    try:
        from apps.notifications import notify

        from . import emails
        from .registry import get_kind

        kind = get_kind(request.kind)
        notify(
            emails.approver_users(request),
            # Same prefix as the email subject: a staff user who suddenly gets a
            # bell for a request they were never assigned must be able to tell
            # why. (F-32.)
            title=f"Approval needed: {emails.subject_prefix(request)}{request.title}",
            message=(kind.label if kind else request.kind),
            url=emails.landing_path(request),
            kind="approvals.requested",
            actor=actor,
            # Addressable so the decision can retire these rows (F-13).
            subject_key=subject_key(request),
        )
    except Exception:  # noqa: BLE001
        logger.exception("approvals: in-app notify (request) failed")

    from . import emails as _emails
    from .tasks import notify_requested_task

    _enqueue(notify_requested_task, _emails.send_requested, request.pk)


@receiver(signals.approval_decided, dispatch_uid="approvals_notify_on_decision")
def notify_on_decision(sender: Any, request: Any, actor: Any, source: str, **kwargs: Any) -> None:
    try:
        from apps.notifications import notify, resolve

        from . import emails

        # 1. The "Approval needed" rows are no longer actionable — for the
        #    decider and for every other approver. Retire them first, or every
        #    approver's badge over-counts forever and clicking one is a wasted
        #    trip to a decided row. (F-13.)
        resolve(subject_key(request), kind="approvals.requested")

        # 2. Tell the requester AND the other approvers the outcome. Multi-
        #    approver queues are the normal case; the second approver used to
        #    get nothing at all. notify() skips the actor and de-duplicates.
        audience = list(emails.approver_users(request))
        if request.requested_by is not None:
            audience.append(request.requested_by)
        notify(
            audience,
            title=f"{request.get_status_display()}: {request.title}",
            message=request.decision_note,
            url=emails.landing_path(request),
            kind="approvals.decided",
            actor=actor,
            subject_key=subject_key(request),
        )
    except Exception:  # noqa: BLE001
        logger.exception("approvals: in-app notify (decision) failed")

    from . import emails as _emails
    from .tasks import notify_decided_task

    _enqueue(notify_decided_task, _emails.send_decided, request.pk)
