"""Background tasks — the daily access-review cadence.

Dogfoods the scheduler primitive: :func:`apps.access.cadence.tick` is a plain
``@task``, promoted to a recurring job by ``@scheduled`` when the scheduler app
is present. Reviews never *depend* on the worker: ``manage.py access cadence``
runs the same tick from a cron line, and a review opened by hand is reminded
about like any other.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.tasks import task

from . import cadence


@task()
def review_cadence() -> dict[str, Any]:
    """Open the review for a closed quarter, store its evidence pack, remind or
    escalate every open review, apply bundle retention."""
    return cadence.tick()


try:
    from apps.scheduler import scheduled

    # Opt-in: the job exists only when SMALLSTACK_ACCESS_REVIEW_CADENCE is set.
    # Off, nothing is scheduled and nothing is sent; attestation stays on
    # demand. 06:10 local, after the day's other prunes.
    if getattr(settings, "SMALLSTACK_SCHEDULER_ENABLED", True) and cadence.enabled():
        review_cadence = scheduled(cron="10 6 * * *", name="Access: review cadence")(review_cadence)
except ImportError:  # scheduler app not installed — `manage.py access cadence` from cron
    pass
