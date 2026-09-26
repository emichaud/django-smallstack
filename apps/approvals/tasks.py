"""Background tasks — email fan-out and the expiry sweep.

The sweep dogfoods the scheduler primitive; correctness never depends on the
worker (lazy expiry runs in the queue view and in decide()).
"""

from __future__ import annotations

from django.conf import settings
from django.tasks import task

from . import emails, services


@task(queue_name="email")
def notify_requested_task(pk: int) -> int:
    return emails.send_requested(pk)


@task(queue_name="email")
def notify_decided_task(pk: int) -> int:
    return emails.send_decided(pk)


@task()
def sweep_expired_approvals() -> int:
    """Expire overdue pending requests (runs the kind callbacks + signals)."""
    return services.mark_expired()


try:
    from apps.scheduler import scheduled

    # ANDed with the master switch: a disabled app must not keep a scheduled job
    # expiring rows behind an operator's back. (F-11.)
    if getattr(settings, "SMALLSTACK_APPROVALS_ENABLED", True) and getattr(
        settings, "SMALLSTACK_APPROVALS_SWEEP_ENABLED", True
    ):
        sweep_expired_approvals = scheduled(
            every="5m", name="Approvals: expire overdue requests"
        )(sweep_expired_approvals)
except ImportError:  # scheduler not installed — lazy expiry still applies
    pass
