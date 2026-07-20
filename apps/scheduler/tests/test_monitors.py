"""SchedulerMonitor: overdue detection + failure-rate with a sample floor (C-12)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.scheduler.models import ScheduledJob, ScheduledJobRun
from apps.scheduler.monitors import SchedulerMonitor

pytestmark = pytest.mark.django_db


def _job(**kw):
    kw.setdefault("name", "job")
    kw.setdefault("task_path", "apps.tasks.tasks.process_data_task")
    kw.setdefault("schedule_type", "interval")
    kw.setdefault("interval_spec", "1h")
    return ScheduledJob.objects.create(**kw)


def _runs(job, *, failed, total):
    now = timezone.now()
    for i in range(total):
        status = "failed" if i < failed else "success"
        ScheduledJobRun.objects.create(job=job, status=status, scheduled_for=now, created_at=now)


def test_single_failure_in_quiet_hour_stays_up():
    # 1/1 failed must NOT trip the core monitor DOWN (no minimum sample).
    job = _job(name="quiet")
    _runs(job, failed=1, total=1)
    assert SchedulerMonitor().check().ok is True


def test_high_failure_rate_with_enough_samples_trips_down():
    job = _job(name="busy")
    _runs(job, failed=3, total=5)  # 60% over the floor of 5
    result = SchedulerMonitor().check()
    assert result.ok is False
    assert "failed" in result.note


def test_healthy_runs_stay_up():
    job = _job(name="healthy")
    _runs(job, failed=0, total=8)
    assert SchedulerMonitor().check().ok is True


def test_overdue_job_trips_down():
    job = _job(name="overdue")
    # Force it well past the 5-minute grace.
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(hours=1))
    result = SchedulerMonitor().check()
    assert result.ok is False
    assert "overdue" in result.note
