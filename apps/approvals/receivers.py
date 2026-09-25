"""Signal receivers — fan a request/decision out to the in-app bell and email.

Connected by ApprovalsConfig.ready() (import side effect). Runbook triple:
signal → receiver enqueues a task, falling back to inline when no task
backend is available. Both channels are best-effort by construction.
"""

from __future__ import annotations

import logging
from typing import Any

from django.dispatch import receiver

from . import signals

logger = logging.getLogger("smallstack.approvals")


def _enqueue(task: Any, inline: Any, pk: int) -> None:
    try:
        task.enqueue(pk)
    except Exception:  # noqa: BLE001 — no broker ⇒ run inline, still best-effort
        try:
            inline(pk)
        except Exception:  # noqa: BLE001
            logger.exception("approvals: notify fan-out failed for %s", pk)


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
            title=f"Approval needed: {request.title}",
            message=(kind.label if kind else request.kind),
            url=emails._console_path(request),
            kind="approvals.requested",
            actor=actor,
        )
    except Exception:  # noqa: BLE001
        logger.exception("approvals: in-app notify (request) failed")

    from . import emails as _emails
    from .tasks import notify_requested_task

    _enqueue(notify_requested_task, _emails.send_requested, request.pk)


@receiver(signals.approval_decided, dispatch_uid="approvals_notify_on_decision")
def notify_on_decision(sender: Any, request: Any, actor: Any, source: str, **kwargs: Any) -> None:
    try:
        from apps.notifications import notify

        from . import emails

        if request.requested_by is not None:
            notify(
                [request.requested_by],
                title=f"{request.get_status_display()}: {request.title}",
                message=request.decision_note,
                url=emails._console_path(request),
                kind="approvals.decided",
                actor=actor,
            )
    except Exception:  # noqa: BLE001
        logger.exception("approvals: in-app notify (decision) failed")

    from . import emails as _emails
    from .tasks import notify_decided_task

    _enqueue(notify_decided_task, _emails.send_decided, request.pk)
