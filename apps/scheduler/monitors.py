"""Scheduler status monitor — is the tick actually firing?

Closes the "forthcoming scheduler core monitor" noted in status-monitors.md.
The check has no dedicated tick-heartbeat state: instead it infers liveness
from the schedules themselves. If an enabled job is overdue by more than a
grace window, the tick isn't running (or is wedged); a spike in recent
failures also trips it.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.smallstack.monitors import CheckResult, Monitor, Service

SERVICE_KEY = "scheduler"


class SchedulerService(Service):
    key = SERVICE_KEY
    title = "Scheduler"
    description = "Recurring background jobs"
    category = "core"
    order = 40
    icon = (
        '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
        '<path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12'
        'S17.52 2 11.99 2zM12.5 7H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>'
    )
    detail_url_name = "scheduler_dashboard"


class SchedulerMonitor(Monitor):
    key = "scheduler-tick"
    service = SERVICE_KEY
    title = "Scheduler tick firing"
    order = 10
    detail_url_name = "scheduler_dashboard"

    def _grace(self) -> int:
        # Overdue beyond this ⇒ the tick isn't firing. Default 5 min.
        return int(getattr(settings, "SMALLSTACK_SCHEDULER_OVERDUE_GRACE_SECONDS", 300))

    def _min_sample(self) -> int:
        # Minimum runs in the last hour before the failure-rate check applies.
        return int(getattr(settings, "SMALLSTACK_SCHEDULER_FAILURE_MIN_SAMPLE", 5))

    def check(self) -> CheckResult:
        from .models import ScheduledJob, ScheduledJobRun

        now = timezone.now()
        overdue = (
            ScheduledJob.objects.filter(
                enabled=True,
                next_run_at__isnull=False,
                next_run_at__lt=now - timedelta(seconds=self._grace()),
            ).count()
        )
        if overdue:
            return CheckResult.down(note=f"{overdue} job(s) overdue — tick not firing?")

        recent = ScheduledJobRun.objects.filter(created_at__gte=now - timedelta(hours=1))
        total = recent.count()
        failed = recent.filter(status=ScheduledJobRun.Status.FAILED).count()
        # Require a minimum sample before trusting the ratio, so a single failed
        # run in a quiet hour (1/1) can't trip the core monitor DOWN.
        if total >= self._min_sample() and failed / total > 0.5:
            return CheckResult.down(note=f"{failed}/{total} runs failed in the last hour")

        active = ScheduledJob.objects.filter(enabled=True).count()
        return CheckResult.up(note=f"{active} active schedule(s)")
