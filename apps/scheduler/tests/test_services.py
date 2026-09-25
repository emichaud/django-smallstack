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


def _set_engine_result(task_result_id, *, status, return_value=None, traceback=""):
    """Force a DBTaskResult into a terminal state for reconcile tests."""
    from django_tasks_db.models import DBTaskResult

    DBTaskResult.objects.filter(id=task_result_id).update(
        status=status, return_value=return_value, traceback=traceback
    )


# --- unresolvable task_path is disabled, not silently erroring (AI-3) --------


def test_unresolvable_task_path_disables_and_marks_invalid(db_backend):
    job = _make_due(name="ghost", task_path="apps.scheduler.tests.test_services.no_such_task")
    result = services.run_due_jobs()

    assert result.enqueued == 0
    assert result.errors == 1
    job.refresh_from_db()
    assert job.enabled is False  # can never succeed → disabled, not left ticking
    assert job.last_status == "invalid"  # visible in the health list, not blank
    run = job.runs.get()
    assert run.status == ScheduledJobRun.Status.FAILED
    assert "unresolvable" in run.message

    # And it doesn't keep erroring every tick now that it's disabled.
    ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
    assert services.run_due_jobs().errors == 0  # disabled → not even considered


# --- reconcile surfaces the return value (C-3) ------------------------------


def test_enqueue_failure_is_recorded_not_lost(db_backend):
    """An exception outside the unresolvable-path allowlist (here InvalidTask
    for an unknown queue) used to advance next_run_at with no run row and
    last_status still "success" — a silently lost fire. (Audit 2026-09-13, D2.)"""
    job = _make_due(queue_name="nope-not-configured")
    ScheduledJob.objects.filter(pk=job.pk).update(last_status="success")

    result = services.run_due_jobs()

    assert result.errors == 1
    job.refresh_from_db()
    assert job.last_status == ScheduledJobRun.Status.FAILED
    assert job.enabled, "possibly-transient failures must not disable the job"
    run = ScheduledJobRun.objects.get(job=job)
    assert run.status == ScheduledJobRun.Status.FAILED
    assert "enqueue failed" in run.message


def test_clean_rejects_unknown_queue_name(db_backend):
    from django.core.exceptions import ValidationError

    job = ScheduledJob(
        name="q", task_path=TASK_PATH, schedule_type="interval", interval_spec="1h", queue_name="bogus"
    )
    with pytest.raises(ValidationError) as exc:
        job.clean()
    assert "queue_name" in exc.value.message_dict
    job.queue_name = "email"
    job.clean()


def test_reconcile_surfaces_success_return_value(db_backend):
    job = _make_due(name="etl")
    services.run_due_jobs()
    run = job.runs.get()
    _set_engine_result(run.task_result_id, status="SUCCESSFUL", return_value={"upserted": 5})

    services.reconcile_run_outcomes()
    run.refresh_from_db()
    assert run.status == ScheduledJobRun.Status.SUCCESS
    assert "upserted" in run.message and "5" in run.message  # the count is visible


def test_reconcile_surfaces_failure_message(db_backend):
    job = _make_due(name="boom")
    services.run_due_jobs()
    run = job.runs.get()
    _set_engine_result(
        run.task_result_id, status="FAILED", traceback="Traceback...\nValueError: provider timeout"
    )

    services.reconcile_run_outcomes()
    run.refresh_from_db()
    assert run.status == ScheduledJobRun.Status.FAILED
    assert "ValueError: provider timeout" in run.message


# --- lazy code-job sync on first tick (C-1) ---------------------------------


def test_first_tick_lazily_syncs_code_jobs(db_backend, monkeypatch):
    from apps.scheduler import decorators
    from apps.scheduler.decorators import ScheduleSpec

    # sync_code_jobs() reads decorators._SCHEDULE_REGISTRY at call time.
    monkeypatch.setattr(decorators, "_SCHEDULE_REGISTRY", [
        ScheduleSpec(
            task_path=TASK_PATH, name="Lazy job", schedule_type="cron", cron_expression="0 6 * * *"
        )
    ])
    # Reset the once-per-process guard so this tick performs the sync.
    monkeypatch.setattr(services, "_code_jobs_synced", False)

    assert not ScheduledJob.objects.filter(name="Lazy job").exists()
    services.run_due_jobs()
    assert ScheduledJob.objects.filter(name="Lazy job", source=ScheduledJob.Source.CODE).exists()


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


# --- trace_id: each job's slice of a tick is correlated (trace-id finding) --


def test_process_job_binds_a_trace_id_for_its_slice_of_the_tick(db_backend, monkeypatch):
    """apps.smallstack.docs.logging-audit.md documents bind_trace_id() as the
    correlation primitive for background/scheduled work; the scheduler's own
    tick didn't use it. This pins that _process_job now binds one trace per
    job per tick — distinct from the trace apps.tasks binds later around the
    enqueued task's actual execution — and resets it afterward."""
    from apps.smallstack.logging import get_trace_id

    seen = {}
    original_body = services._process_job_body

    def spy(job, *, now, result):
        seen["trace_id"] = get_trace_id()
        return original_body(job, now=now, result=result)

    monkeypatch.setattr(services, "_process_job_body", spy)

    job = _make_due(name="traced")
    assert get_trace_id() == ""
    services.run_due_jobs()

    assert seen["trace_id"].startswith(f"trace_schedjob_{job.pk}_")
    assert get_trace_id() == "", "must be reset once the job's processing is done"


def test_two_jobs_in_the_same_tick_get_different_trace_ids(db_backend, monkeypatch):
    from apps.smallstack.logging import get_trace_id

    seen = []
    original_body = services._process_job_body

    def spy(job, *, now, result):
        seen.append(get_trace_id())
        return original_body(job, now=now, result=result)

    monkeypatch.setattr(services, "_process_job_body", spy)

    _make_due(name="job-a")
    _make_due(name="job-b")
    services.run_due_jobs()

    assert len(seen) == 2
    assert seen[0] != seen[1]


def test_trace_id_is_reset_even_when_the_job_raises(db_backend, monkeypatch):
    """run_due_jobs() catches per-job exceptions so one bad job can't sink the
    tick — the trace binding must unwind on that path too, not just the
    happy path, or the exception's trace would leak into whatever the tick
    (or the next job) logs next."""
    from apps.smallstack.logging import get_trace_id

    def boom(job, *, now, result):
        raise RuntimeError("job processing exploded")

    monkeypatch.setattr(services, "_process_job_body", boom)

    _make_due(name="explodes")
    result = services.run_due_jobs()

    assert result.errors == 1
    assert get_trace_id() == ""
