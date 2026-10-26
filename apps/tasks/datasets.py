"""Bundled datasets for background tasks: retry attempts and worker heartbeats."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import TaskAttempt, WorkerHeartbeat


@framework_dataset(
    "smallstack_task_attempts",
    label="Task attempts",
    description=(
        "One row per retry attempt of a background task: the retry chain, attempt number, why it was "
        "retried and how the parent attempt ended."
    ),
    columns=[
        "created_at",
        "root_id",
        "result_id",
        "parent_id",
        "attempt",
        "max_attempts",
        "cause",
        "parent_status",
        "parent_completed_at",
        "retry_cancelled",
    ],
    filterable=["created_at", "root_id", "cause", "parent_status", "retry_cancelled"],
)
def task_attempts() -> QuerySet[TaskAttempt]:
    return TaskAttempt.objects.all()


@framework_dataset(
    "smallstack_worker_heartbeats",
    label="Workers",
    description=(
        "Every task worker that has reported in: host, pid, queues served, and when it started, was last "
        "seen and stopped."
    ),
    columns=["worker_id", "label", "hostname", "pid", "queues", "started_at", "last_seen_at", "stopped_at"],
    filterable=["label", "hostname", "queues", "started_at", "last_seen_at", "stopped_at"],
)
def worker_heartbeats() -> QuerySet[WorkerHeartbeat]:
    return WorkerHeartbeat.objects.all()
