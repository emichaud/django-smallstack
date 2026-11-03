"""Background tasks for dashboards. The scheduler autodiscovers this module.

``capture_snapshots`` runs hourly: each tracked hour, day, week, month or quarter
that has ended gets its capture, however long the job was paused (the latest ended
period, once). Its cadence lands in a ``ScheduledJob`` row ops can pause from the
scheduler UI. Old hourly and daily captures are pruned here too.
"""

from __future__ import annotations

from django.conf import settings
from django.tasks import task

from apps.scheduler import scheduled


@scheduled(cron="5 * * * *", name="Snapshots: capture what's due")
@task()
def capture_snapshots() -> int:
    # @scheduled registers at import, whatever the switch says.
    if not getattr(settings, "SMALLSTACK_DASHBOARDS_ENABLED", True):
        return 0

    from .snapshots import capture_due, prune

    done = capture_due()
    prune()
    return done
