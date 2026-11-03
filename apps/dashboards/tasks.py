"""Background tasks for dashboards. The scheduler autodiscovers this module.

``snapshot_goal_lists`` saves the week just ended for every goal list, early
each Monday — the weekly tab a spreadsheet would gain. Its cadence lands in a
``ScheduledJob`` row ops can pause or retune from the scheduler UI. Runs the
same ``weeks.snapshot_last_week()`` as ``manage.py snapshot_goals``.
"""

from __future__ import annotations

from django.tasks import task

from apps.scheduler import scheduled


@scheduled(cron="15 0 * * 1", name="Goal lists: save last week")
@task()
def snapshot_goal_lists() -> int:
    from .weeks import snapshot_last_week

    return snapshot_last_week()
