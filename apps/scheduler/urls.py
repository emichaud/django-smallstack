"""Scheduler URLs.

Mounted at the smallstack root (like usermanager) with a ``scheduler/`` path
prefix. No ``app_name`` — bare URL names keep CRUDView's internal reverses
working (see building-crud-pages.md "URL namespaces" footgun).
"""

from django.urls import path

from .views import (
    ScheduledJobCRUDView,
    SchedulerDashboardView,
    run_now,
    scheduler_stat_detail,
    scheduler_tick,
)

urlpatterns = [
    path("scheduler/", SchedulerDashboardView.as_view(), name="scheduler_dashboard"),
    path("scheduler/stats/<str:stat_type>/", scheduler_stat_detail, name="scheduler_stat_detail"),
    path("scheduler/jobs/<int:pk>/run-now/", run_now, name="scheduler_run_now"),
    # Localhost-only tick (cron POSTs here; runs inside gunicorn).
    path("scheduler/tick/", scheduler_tick, name="scheduler_tick"),
    *ScheduledJobCRUDView.get_urls(),
]
