"""Bundled datasets for the scheduler: job definitions and their run history."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import ScheduledJob, ScheduledJobRun


@framework_dataset(
    "smallstack_scheduled_jobs",
    label="Scheduled jobs",
    description=(
        "Every recurring job: what it runs, its cadence, whether it is enabled, and its last/next run "
        "bookkeeping. Task kwargs are left out."
    ),
    columns=[
        "name",
        "job_kind",
        "task_path",
        "queue_name",
        "schedule_type",
        "interval_spec",
        "cron_expression",
        "run_at",
        "timezone",
        "enabled",
        "source",
        "auto_retired",
        "next_run_at",
        "last_enqueued_at",
        "last_status",
        "total_runs",
        "created_at",
        "updated_at",
    ],
    filterable=[
        "job_kind",
        "queue_name",
        "schedule_type",
        "enabled",
        "source",
        "auto_retired",
        "last_status",
        "next_run_at",
        "last_enqueued_at",
        "created_at",
    ],
)
def scheduled_jobs() -> QuerySet[ScheduledJob]:
    return ScheduledJob.objects.all()


@framework_dataset(
    "smallstack_scheduled_job_runs",
    label="Scheduled job runs",
    description=(
        "One row per scheduled-job firing: the job, when it was due, when it was enqueued, its outcome and message."
    ),
    columns=["job", "status", "scheduled_for", "created_at", "message", "task_result_id"],
    filterable=["job", "status", "scheduled_for", "created_at"],
)
def scheduled_job_runs() -> QuerySet[ScheduledJobRun]:
    return ScheduledJobRun.objects.select_related("job")
