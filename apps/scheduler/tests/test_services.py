"""run_due_jobs: firing, the atomic claim, overlap, stale-run, catch-up, retire.

These use the DatabaseBackend (not the test default ImmediateBackend) so that
enqueue persists a DBTaskResult that stays unfinished (no worker runs) — which
is exactly what the overlap/stale guards read.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.tasks import task
from django.utils import timezone

from apps.scheduler import services
from apps.scheduler.models import ScheduledJob, ScheduledJobRun

pytestmark = pytest.mark.django_db


@task
def sample_task(**kwargs):  # enqueued by the tests; never actually run (no worker)
    return kwargs


TASK_PATH = "apps.scheduler.tests.test_services.sample_task"


@pytest.fixture
def db_backend(settings):
    """Persist enqueues so overlap/stale guards have a DBTaskResult to read."""
    settings.TASKS = {
        "default": {
            "BACKEND": "django_tasks_db.DatabaseBackend",
            "QUEUES": ["default", "email"],
        }
    }


def _make(**kw):
    kw.setdefault("name", "job")
    kw.setdefault("task_path", TASK_PATH)
    kw.setdefault("schedule_type", "interval")
    kw.setdefault("interval_spec", "1h")
    kw.setdefault("enabled", True)
    return ScheduledJob.objects.create(**kw)


def _make_due(**kw):
    """A job whose next_run_at is already in the past."""
    job = _make(**kw)
    past = timezone.now() - timedelta(minutes=1)
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=past)
    job.refresh_from_db()
    return job


# --- firing -----------------------------------------------------------------


def test_due_job_enqueues_once_and_advances(db_backend):
    job = _make_due(name="fire")
    result = services.run_due_jobs()

    assert result.enqueued == 1
    job.refresh_from_db()
    assert job.total_runs == 1
    assert job.next_run_at > timezone.now()  # cursor advanced into the future
    run = job.runs.get()
    assert run.status == ScheduledJobRun.Status.QUEUED
    assert run.task_result_id  # linked to the engine result


def test_not_due_job_is_left_alone(db_backend):
    job = _make(name="future")  # save() seeds next_run_at in the future
    result = services.run_due_jobs()
    assert result.enqueued == 0
    assert job.runs.count() == 0


def test_disabled_job_never_fires(db_backend):
    job = _make(name="off", enabled=False)
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(hours=1))
    result = services.run_due_jobs()
    assert result.enqueued == 0


# --- the atomic claim (concurrency) -----------------------------------------


def test_claim_prevents_double_fire(db_backend):
    """A tick that lost the race (next_run_at already advanced) must not fire."""
    job = _make_due(name="race")
    observed = job.next_run_at

    # Simulate a concurrent tick that already claimed + advanced this job.
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() + timedelta(hours=1))

    # `job` still holds the stale observed next_run_at, like a racing tick would.
    assert job.next_run_at == observed
    result = services.TickResult()
    services._process_job(job, now=timezone.now(), result=result)

    assert result.enqueued == 0
    assert job.runs.count() == 0  # nothing enqueued or recorded


def test_two_sequential_ticks_fire_once(db_backend):
    _make_due(name="seq")
    first = services.run_due_jobs()
    second = services.run_due_jobs()  # cursor now in the future → not due
    assert first.enqueued == 1
    assert second.enqueued == 0


# --- overlap guard ----------------------------------------------------------


def test_overlap_skips_while_previous_run_active(db_backend):
    job = _make_due(name="overlap", allow_overlap=False)
    services.run_due_jobs()  # first fire → DBTaskResult stays READY (no worker)

    # Force due again immediately.
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
    result = services.run_due_jobs()

    assert result.skipped == 1
    assert result.enqueued == 0
    skipped = job.runs.filter(status=ScheduledJobRun.Status.SKIPPED).get()
    assert "previous run" in skipped.message


def test_overlap_allowed_fires_again(db_backend):
    job = _make_due(name="overlap-ok", allow_overlap=True)
    services.run_due_jobs()
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
    result = services.run_due_jobs()
    assert result.enqueued == 1


def test_stale_previous_run_does_not_wedge(db_backend, settings):
    settings.SMALLSTACK_SCHEDULER_STALE_RUN_SECONDS = 10
    job = _make_due(name="stale", allow_overlap=False)
    services.run_due_jobs()

    # Age the previous run past the stale threshold → guard treats it as gone.
    old = timezone.now() - timedelta(seconds=30)
    ScheduledJobRun.objects.filter(job=job).update(created_at=old)
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))

    result = services.run_due_jobs()
    assert result.enqueued == 1  # not wedged


# --- catch-up policy --------------------------------------------------------


def test_catchup_skip_skips_missed_window(db_backend):
    job = _make(name="skip", interval_spec="1h", catch_up=ScheduledJob.CatchUp.SKIP)
    # Due 3h ago → multiple missed periods.
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(hours=3))
    result = services.run_due_jobs()
    assert result.skipped == 1
    assert result.enqueued == 0


def test_catchup_run_once_fires_once(db_backend):
    job = _make(name="runonce", interval_spec="1h", catch_up=ScheduledJob.CatchUp.RUN_ONCE)
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(hours=3))
    result = services.run_due_jobs()
    assert result.enqueued == 1  # one catch-up run, not three


# --- once retire ------------------------------------------------------------


def test_reconcile_emails_on_failure(db_backend, settings, monkeypatch):
    settings.SMALLSTACK_SCHEDULER_FAILURE_EMAILS = ["ops@example.com"]
    calls = []

    class _FakeTask:
        def enqueue(self, **kw):
            calls.append(kw)

    monkeypatch.setattr("apps.tasks.tasks.send_email_task", _FakeTask())

    job = _make_due(name="failmail")
    services.run_due_jobs()  # enqueues → DBTaskResult READY
    run = job.runs.get()

    from django_tasks_db.models import DBTaskResult

    DBTaskResult.objects.filter(id=run.task_result_id).update(status="FAILED")
    services.reconcile_run_outcomes()

    run.refresh_from_db()
    assert run.status == ScheduledJobRun.Status.FAILED
    assert calls and calls[0]["recipient"] == ["ops@example.com"]
    assert "failmail" in calls[0]["subject"]


def test_reconcile_no_email_when_unconfigured(db_backend, monkeypatch):
    calls = []

    class _FakeTask:
        def enqueue(self, **kw):
            calls.append(kw)

    monkeypatch.setattr("apps.tasks.tasks.send_email_task", _FakeTask())

    job = _make_due(name="silentfail")
    services.run_due_jobs()
    run = job.runs.get()
    from django_tasks_db.models import DBTaskResult

    DBTaskResult.objects.filter(id=run.task_result_id).update(status="FAILED")
    services.reconcile_run_outcomes()
    assert calls == []  # no recipients configured → no email


def test_once_job_fires_then_retires(db_backend):
    # Created with a future run_at (so save seeds next_run_at); then time
    # "passes" and both move into the past, making it due.
    job = _make(
        name="once",
        schedule_type="once",
        interval_spec="",
        run_at=timezone.now() + timedelta(minutes=5),
        enabled=True,
    )
    assert job.next_run_at is not None
    ScheduledJob.objects.filter(pk=job.pk).update(
        run_at=timezone.now() - timedelta(minutes=5),
        next_run_at=timezone.now() - timedelta(minutes=5),
    )
    result = services.run_due_jobs()
    assert result.enqueued == 1
    assert result.retired == 1

    job.refresh_from_db()
    assert job.next_run_at is None  # will not fire again
    assert services.run_due_jobs().enqueued == 0
