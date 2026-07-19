"""SchedulerDashboardWidget — a card on the central /smallstack/ dashboard."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.smallstack.displays import DashboardWidget


class SchedulerDashboardWidget(DashboardWidget):
    title = "Scheduler"
    icon = (
        '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
        '<path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12'
        'S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z'
        'M12.5 7H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>'
    )
    order = 45
    url_name = "scheduler_dashboard"

    def get_data(self, model_class: type | None = None) -> dict:
        from .models import ScheduledJob, ScheduledJobRun

        active = ScheduledJob.objects.filter(enabled=True).count()
        day_ago = timezone.now() - timedelta(hours=24)
        failures = ScheduledJobRun.objects.filter(
            status=ScheduledJobRun.Status.FAILED, created_at__gte=day_ago
        ).count()

        nxt = (
            ScheduledJob.objects.filter(enabled=True, next_run_at__isnull=False)
            .order_by("next_run_at")
            .values_list("next_run_at", flat=True)
            .first()
        )
        detail = f"next {nxt:%b %d %H:%M}" if nxt else "nothing scheduled"
        status = "danger" if failures else ("ok" if active else "muted")

        return {
            "headline": f"{active} active",
            "detail": f"{detail} · {failures} failed / 24h" if failures else detail,
            "status": status,
            "extra": {"active": active, "failures_24h": failures},
        }
