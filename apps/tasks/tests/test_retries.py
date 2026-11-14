"""Retries with backoff (``reliability.py``, ``signals.py``, reaper hand-off).

Retries need the real engine (``ImmediateBackend`` can't defer, and the retry
receiver ignores its ``task_finished`` — since django-tasks-db 0.13 both
backends share Django's signal), so these tests switch ``TASKS`` to
``DatabaseBackend`` and drain the queue with SmallStack's ``db_worker --batch``
in-process. Backoff is 0 for the test tasks so a retry is due immediately and
the same batch run picks it up.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.db import connection
from django.tasks import TaskResultStatus, task, task_backends
from django.tasks.backends.immediate import ImmediateBackend
from django.tasks.signals import task_finished
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django_tasks_db.backend import DatabaseBackend
from django_tasks_db.management.commands.db_worker import Worker
from django_tasks_db.models import DBTaskResult

from apps.tasks import reliability, signals
from apps.tasks.exceptions import RETRY_SUPERSEDED_PATH, WORKER_LOST_PATH
from apps.tasks.models import TaskAttempt, WorkerHeartbeat
from apps.tasks.reaper import reap_lost_tasks
from apps.tasks.reliability import RetryPolicy, maybe_retry, pin_max_attempts, policy_for, retry_policy


def _worker_success_sender() -> DatabaseBackend:
    """What db_worker passes as ``sender`` on its success path: the backend *instance*."""
    backend = task_backends["default"]
    assert isinstance(backend, DatabaseBackend)
    return backend


DB_TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default", "email"],
    }
}

CALLS = {"n": 0}


# Module level, not nested: the worker re-imports tasks by dotted path.
@retry_policy(max_attempts=3, backoff=0, backoff_max=0)
@task
def flaky(fail_times: int) -> str:
    CALLS["n"] += 1
    if CALLS["n"] <= fail_times:
        raise OSError(f"transient #{CALLS['n']}")
    return "ok"


@retry_policy(max_attempts=3, retry_on=(OSError,), backoff=0, backoff_max=0)
@task
def picky() -> None:
    raise ValueError("permanent")


@task
def no_policy() -> None:
    raise OSError("no policy")


@retry_policy(max_attempts=3, retry_lost=False, backoff=0, backoff_max=0)
@task
def not_on_lost() -> None:
    raise OSError("x")


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _engine(settings):
    settings.TASKS = DB_TASKS
    settings.SMALLSTACK_TASKS_BACKOFF_SECONDS = 0
    settings.SMALLSTACK_TASKS_BACKOFF_MAX_SECONDS = 0
    CALLS["n"] = 0


def _run_worker() -> None:
    with mock.patch.object(Worker, "configure_signals"):
        call_command("db_worker", batch=True, startup_delay=False, queue_name="*", worker_id="t-worker", verbosity=0)


def _rows(task_obj) -> list[DBTaskResult]:
    return list(DBTaskResult.objects.filter(task_path=task_obj.module_path).order_by("enqueued_at"))


def _failed_row(task_obj, *, exc_path: str = "builtins.OSError", finished_ago: float = 0) -> DBTaskResult:
    now = timezone.now()
    return DBTaskResult.objects.create(
        status=TaskResultStatus.FAILED,
        args_kwargs={"args": [], "kwargs": {}},
        task_path=task_obj.module_path,
        backend_name="default",
        queue_name="default",
        run_after=now,
        started_at=now,
        finished_at=now - timedelta(seconds=finished_ago),
        exception_class_path=exc_path,
        traceback=f"Traceback...\n{exc_path.rsplit('.', 1)[-1]}: boom",
    )


class TestWorkerRetries:
    def test_fails_twice_then_succeeds_as_one_chain(self):
        first = flaky.enqueue(fail_times=2)
        _run_worker()

        rows = _rows(flaky)
        assert [r.status for r in rows] == ["FAILED", "FAILED", "SUCCESSFUL"]
        assert "transient #1" in rows[0].traceback and "transient #2" in rows[1].traceback
        attempts = list(TaskAttempt.objects.order_by("attempt"))
        assert [(a.attempt, a.cause) for a in attempts] == [(2, "failed"), (3, "failed")]
        assert {a.root_id for a in attempts} == {rows[0].id}
        assert str(rows[0].id) == str(first.id)
        assert attempts[0].parent_id == rows[0].id and attempts[1].parent_id == rows[1].id

    def test_stops_at_max_attempts(self):
        flaky.enqueue(fail_times=10)
        _run_worker()
        assert [r.status for r in _rows(flaky)] == ["FAILED"] * 3

    def test_retry_on_filters_exceptions(self):
        picky.enqueue()
        _run_worker()
        assert [r.status for r in _rows(picky)] == ["FAILED"]

    def test_no_policy_means_no_retry_by_default(self):
        no_policy.enqueue()
        _run_worker()
        assert len(_rows(no_policy)) == 1

    def test_default_max_attempts_setting_applies_to_undecorated_tasks(self, settings):
        settings.SMALLSTACK_TASKS_DEFAULT_MAX_ATTEMPTS = 2
        no_policy.enqueue()
        _run_worker()
        assert len(_rows(no_policy)) == 2

    def test_retry_keeps_queue_priority_and_args(self):
        flaky.using(priority=7).enqueue(fail_times=1)
        _run_worker()
        first, second = _rows(flaky)
        assert (second.priority, second.queue_name, second.backend_name) == (7, "default", "default")
        assert second.args_kwargs == first.args_kwargs

    def test_a_raising_retry_check_never_hurts_the_worker(self):
        """signals.py's contract: the receiver swallows everything."""
        flaky.enqueue(fail_times=0)
        flaky.enqueue(fail_times=5)
        with mock.patch.object(signals, "maybe_retry", side_effect=RuntimeError("boom")):
            _run_worker()
        statuses = sorted(r.status for r in _rows(flaky))
        assert statuses == ["FAILED", "SUCCESSFUL"]  # both ran; no retry; no crash

    def test_receiver_ignores_successful_results(self):
        result = mock.Mock(status=TaskResultStatus.SUCCESSFUL, id="x")
        with mock.patch.object(signals, "maybe_retry") as retry:
            task_finished.send(sender=_worker_success_sender(), task_result=result)
        retry.assert_not_called()

    def test_receiver_accepts_both_sender_forms_db_worker_uses(self):
        """Success path sends the backend instance, failure path the class."""
        assert signals._from_database_worker(_worker_success_sender())
        assert signals._from_database_worker(DatabaseBackend)
        result = mock.Mock(status=TaskResultStatus.FAILED, id="x")
        with mock.patch.object(signals, "maybe_retry") as retry:
            task_finished.send(sender=DatabaseBackend, task_result=result)
        retry.assert_called_once_with("x")

    def test_receiver_ignores_other_backends(self):
        """django-tasks-db 0.13 shares Django's signal with every backend.

        ImmediateBackend (the test suite's backend) sends the same
        task_finished. Through 0.12 this receiver never heard it; it must
        still not act on it, or every failed test-suite task would hit the DB.
        """
        assert not signals._from_database_worker(ImmediateBackend)
        assert not signals._from_database_worker(object)
        assert not signals._from_database_worker(None)
        result = mock.Mock(status=TaskResultStatus.FAILED, id="x")
        with (
            mock.patch.object(signals, "maybe_retry") as retry,
            mock.patch.object(signals, "record_late_completion") as late,
        ):
            task_finished.send(sender=ImmediateBackend, task_result=result)
        retry.assert_not_called()
        late.assert_not_called()

    def test_exactly_one_subscription_to_django_s_signal(self):
        """One signal, one receiver — and no legacy 0.12 package to hear.

        The pin is `>=0.13,<0.14`, so `django_tasks` cannot be installed. A
        second subscription would deliver one task twice, which enqueues a retry
        and then cancels it as superseded (see TestDoubleDelivery).
        """
        names = [getattr(ref(), "__name__", None) for _key, ref, *_ in signals.task_finished.receivers]
        assert names.count("retry_failed_task") == 1, names
        assert not hasattr(signals, "FINISHED_SIGNALS"), "the 0.12 dual-subscription path is back"
        with pytest.raises(ImportError):
            import django_tasks  # noqa: F401

    def test_failing_task_on_immediate_backend_is_not_retried(self, settings):
        """End to end on the backend the suite uses: no retry rows, no error."""
        settings.TASKS = {
            "default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend", "QUEUES": ["default", "email"]}
        }
        result = flaky.enqueue(fail_times=5)
        assert result.status == TaskResultStatus.FAILED
        assert CALLS["n"] == 1
        assert not TaskAttempt.objects.exists()


class TestUnrecognisedSender:
    """V4: the filter must not fail closed into silence.

    The sender shapes we match are an upstream inconsistency (instance on
    success, class on failure). If that is ever normalised, or changed again,
    every retry silently becomes a no-op that the repair sweep covers 30s later
    — correct-looking and nearly invisible, which is how the 0.12 signal change
    got as far as it did.
    """

    @pytest.fixture(autouse=True)
    def _rearm(self):
        signals._reset_sender_warning()
        yield
        signals._reset_sender_warning()

    def test_an_unrecognised_sender_warns_once_per_process(self, caplog):
        with caplog.at_level("WARNING", logger="apps.tasks.signals"):
            assert signals._from_database_worker("not-a-backend") is False
            assert signals._from_database_worker(object()) is False
            assert signals._from_database_worker(None) is False
        warned = [r.getMessage() for r in caplog.records if "is not a task backend" in r.getMessage()]
        assert len(warned) == 1, f"want exactly one warning per process, got {len(warned)}"
        assert "fall back to the repair sweep" in warned[0]

    def test_another_backend_is_ignored_without_warning(self, caplog):
        """ImmediateBackend sends its class for every task in this suite."""
        with caplog.at_level("WARNING", logger="apps.tasks.signals"):
            assert signals._from_database_worker(ImmediateBackend) is False
            assert signals._from_database_worker(ImmediateBackend(alias="default", params={})) is False
        assert [r.getMessage() for r in caplog.records] == []

    def test_a_recognised_sender_never_warns(self, caplog):
        with caplog.at_level("WARNING", logger="apps.tasks.signals"):
            assert signals._from_database_worker(DatabaseBackend) is True
            assert signals._from_database_worker(DatabaseBackend(alias="default", params={})) is True
        assert [r.getMessage() for r in caplog.records] == []


class TestFailedAttemptLogSeverity:
    """Finding B: an absorbed failure must not log like a real one.

    Django's `log_task_finished` logs every FAILED result at ERROR with a
    traceback. For an attempt being retried that is a page for a non-event, and
    documentation cannot reach an alerting pipeline.
    """

    def _result(self, row):
        return mock.Mock(
            status=TaskResultStatus.FAILED, id=row.id, task=mock.Mock(module_path=row.task_path)
        )

    def test_django_s_blanket_error_logger_is_no_longer_connected(self):
        from django.tasks.signals import log_task_finished

        names = [getattr(ref(), "__name__", None) for _key, ref, *_ in signals.task_finished.receivers]
        assert log_task_finished.__name__ not in names, "both loggers connected => every task logged twice"
        assert "log_task_outcome" in names

    def test_an_attempt_being_retried_logs_warning_not_error(self, caplog):
        row = _failed_row(flaky)
        retry_id = maybe_retry(row.id)
        assert retry_id is not None

        with caplog.at_level("INFO", logger="django.tasks"):
            signals.log_task_outcome(sender=DatabaseBackend, task_result=self._result(row))

        rec = next(r for r in caplog.records if "Task id=" in r.getMessage())
        assert rec.levelname == "WARNING", f"an absorbed failure logged at {rec.levelname}"
        assert f"retrying_as={retry_id}" in rec.getMessage()
        assert rec.exc_info is None, "no traceback for a failure being absorbed"

    def test_a_final_failure_still_logs_error_with_the_traceback(self, caplog):
        row = _failed_row(no_policy)  # no policy => no retry => final
        assert maybe_retry(row.id) is None

        with caplog.at_level("INFO", logger="django.tasks"):
            try:
                raise OSError("boom")  # a live exception, as upstream's except block has
            except OSError:
                signals.log_task_outcome(sender=DatabaseBackend, task_result=self._result(row))

        rec = next(r for r in caplog.records if "Task id=" in r.getMessage())
        assert rec.levelname == "ERROR"
        assert rec.exc_info is not None and rec.exc_info[0] is OSError
        assert "retrying_as" not in rec.getMessage()

    def test_the_softening_can_be_turned_off(self, caplog, settings):
        settings.SMALLSTACK_TASKS_SOFTEN_RETRYABLE_LOGS = False
        row = _failed_row(flaky)
        assert maybe_retry(row.id) is not None

        with caplog.at_level("INFO", logger="django.tasks"):
            signals.log_task_outcome(sender=DatabaseBackend, task_result=self._result(row))

        rec = next(r for r in caplog.records if "Task id=" in r.getMessage())
        assert rec.levelname == "ERROR", "the opt-out must restore Django's stock severity"

    @staticmethod
    def _one_record(fn, sender, task_result, caplog, *, raising=None):
        """The single django.tasks record `fn` emits for this task."""
        caplog.clear()
        with caplog.at_level("INFO", logger="django.tasks"):
            if raising is None:
                fn(sender=sender, task_result=task_result)
            else:
                try:
                    raise raising
                except type(raising):
                    fn(sender=sender, task_result=task_result)
        recs = [r for r in caplog.records if r.name == "django.tasks"]
        assert len(recs) == 1, recs
        r = recs[0]
        return (r.levelno, r.getMessage(), r.args, r.exc_info[0] if r.exc_info else None)

    @pytest.mark.parametrize(
        ("label", "sender_factory"),
        [
            ("DatabaseBackend, finally failed", lambda: DatabaseBackend),
            ("ImmediateBackend (global blast radius)", lambda: ImmediateBackend),
        ],
    )
    def test_our_record_is_equivalent_to_django_s_when_no_retry_is_pending(
        self, caplog, label, sender_factory
    ):
        """Condition 1: only the retry-pending case may differ.

        Taking over Django's receiver is a **global** mutation — it changes the
        record for every backend, not just DatabaseBackend. So for a task with no
        retry pending, ours must be indistinguishable from Django's in level,
        message, args and exception type. Anything else leaks project-wide.
        """
        from django.tasks.signals import log_task_finished

        row = _failed_row(no_policy)  # no policy => no retry => final failure
        assert maybe_retry(row.id) is None
        result = self._result(row)
        sender = sender_factory()
        boom = OSError("boom")

        theirs = self._one_record(log_task_finished, sender, result, caplog, raising=boom)
        ours = self._one_record(signals.log_task_outcome, sender, result, caplog, raising=boom)

        assert ours == theirs, f"{label}: diverged from Django's record\n  ours={ours}\n  theirs={theirs}"
        assert ours[0] == logging.ERROR

    def test_our_record_is_equivalent_to_django_s_on_success(self, caplog):
        from django.tasks.signals import log_task_finished

        row = _failed_row(flaky)
        DBTaskResult.objects.filter(id=row.id).update(status="SUCCESSFUL")
        result = mock.Mock(
            status=TaskResultStatus.SUCCESSFUL, id=row.id, task=mock.Mock(module_path=row.task_path)
        )
        theirs = self._one_record(log_task_finished, DatabaseBackend, result, caplog)
        ours = self._one_record(signals.log_task_outcome, DatabaseBackend, result, caplog)
        assert ours == theirs
        assert ours[0] == logging.INFO

    def test_a_successful_task_still_logs_info(self, caplog):
        row = _failed_row(flaky)
        DBTaskResult.objects.filter(id=row.id).update(status="SUCCESSFUL")
        result = mock.Mock(
            status=TaskResultStatus.SUCCESSFUL, id=row.id, task=mock.Mock(module_path=row.task_path)
        )
        with caplog.at_level("INFO", logger="django.tasks"):
            signals.log_task_outcome(sender=DatabaseBackend, task_result=result)
        rec = next(r for r in caplog.records if "Task id=" in r.getMessage())
        assert rec.levelname == "INFO"


class TestMaybeRetry:
    def test_schedules_the_retry_after_the_backoff(self):
        row = _failed_row(flaky)
        now = timezone.now()
        with mock.patch.object(RetryPolicy, "delay", return_value=120.0):
            new_id = maybe_retry(row.id, now=now)
        new = DBTaskResult.objects.get(id=new_id)
        assert new.status == "READY"
        assert abs((new.run_after - now).total_seconds() - 120) < 1

    def test_only_one_retry_per_attempt(self):
        row = _failed_row(flaky)
        assert maybe_retry(row.id) is not None
        assert maybe_retry(row.id) is None
        assert TaskAttempt.objects.filter(parent_id=row.id).count() == 1
        assert len(_rows(flaky)) == 2

    def test_ignores_non_failed_and_missing_rows(self):
        row = _failed_row(flaky)
        DBTaskResult.objects.filter(id=row.id).update(status="SUCCESSFUL")
        assert maybe_retry(row.id) is None
        assert maybe_retry("00000000-0000-0000-0000-000000000000") is None

    def test_force_stop_is_classified_interrupted(self):
        row = _failed_row(flaky, exc_path="builtins.SystemExit")
        new_id = maybe_retry(row.id)
        assert TaskAttempt.objects.get(result_id=new_id).cause == "interrupted"

    def test_retry_lost_false_skips_lost_and_interrupted(self):
        assert maybe_retry(_failed_row(not_on_lost, exc_path="builtins.SystemExit").id) is None
        assert maybe_retry(_failed_row(not_on_lost, exc_path="apps.tasks.exceptions.WorkerLost").id) is None
        assert maybe_retry(_failed_row(not_on_lost).id) is not None

    def test_unimportable_exception_matches_only_catch_all(self):
        assert maybe_retry(_failed_row(flaky, exc_path="gone.module.Err").id) is not None
        assert maybe_retry(_failed_row(picky, exc_path="gone.module.Err").id) is None

    def test_a_pinned_budget_alone_never_reruns_a_worker_death(self):
        """An operator's max_retries must not be more aggressive than @retry_policy.

        Pinning a budget onto a task that declares no policy says "retry the
        failure", not "re-run this if the machine dies" — the latter is an
        at-least-once decision about a body nobody marked repeatable.
        """
        lost = _failed_row(no_policy, exc_path="apps.tasks.exceptions.WorkerLost")
        pin_max_attempts(lost.id, 3)
        assert maybe_retry(lost.id, TaskAttempt.Cause.LOST) is None

        killed = _failed_row(no_policy, exc_path="builtins.SystemExit")
        pin_max_attempts(killed.id, 3)
        assert maybe_retry(killed.id) is None

        # What the operator *did* ask for still works: the task raised.
        raised = _failed_row(no_policy)
        pin_max_attempts(raised.id, 3)
        assert maybe_retry(raised.id) is not None

    def test_an_explicit_policy_may_still_opt_into_retrying_a_worker_death(self):
        """flaky declares @retry_policy, so retry_lost=True is its own choice."""
        lost = _failed_row(flaky, exc_path="apps.tasks.exceptions.WorkerLost")
        pin_max_attempts(lost.id, 3)
        assert maybe_retry(lost.id, TaskAttempt.Cause.LOST) is not None

    def test_pinned_budget_overrides_the_policy_and_follows_the_chain(self):
        row = _failed_row(no_policy)
        pin_max_attempts(row.id, 3)
        second = maybe_retry(row.id)
        assert TaskAttempt.objects.get(result_id=second).max_attempts == 3
        DBTaskResult.objects.filter(id=second).update(status="FAILED", exception_class_path="builtins.OSError")
        third = maybe_retry(second)
        assert TaskAttempt.objects.get(result_id=third).attempt == 3
        DBTaskResult.objects.filter(id=third).update(status="FAILED", exception_class_path="builtins.OSError")
        assert maybe_retry(third) is None


class TestReaperAndRepair:
    def test_reaped_task_is_retried_as_lost(self):
        now = timezone.now()
        WorkerHeartbeat.objects.create(worker_id="dead", last_seen_at=now, stopped_at=now)
        row = DBTaskResult.objects.create(
            status="RUNNING",
            args_kwargs={"args": [], "kwargs": {"fail_times": 0}},
            task_path=flaky.module_path,
            backend_name="default",
            queue_name="default",
            run_after=now,
            started_at=now,
            worker_ids=["dead"],
        )

        result = reap_lost_tasks()

        assert result.retried == 1
        child = TaskAttempt.objects.get(parent_id=row.id)
        assert child.cause == "lost" and child.attempt == 2
        _run_worker()
        assert DBTaskResult.objects.get(id=child.result_id).status == "SUCCESSFUL"

    def test_repair_sweep_retries_a_missed_failure(self):
        missed = _failed_row(flaky, finished_ago=300)
        fresh = _failed_row(flaky, finished_ago=1)  # inside the grace window
        ancient = _failed_row(flaky, finished_ago=2 * 3600)  # outside the window
        unretryable = _failed_row(no_policy, finished_ago=300)

        assert reliability.repair_missed_retries() == 1

        assert TaskAttempt.objects.filter(parent_id=missed.id).exists()
        for row in (fresh, ancient, unretryable):
            assert not TaskAttempt.objects.filter(parent_id=row.id).exists()
        assert reliability.repair_missed_retries() == 0  # idempotent

    def test_repair_sweep_includes_pinned_chains(self):
        row = _failed_row(no_policy, finished_ago=300)
        pin_max_attempts(row.id, 2)
        assert reliability.repair_missed_retries() == 1


class TestLateCompletion:
    """A reaped attempt that completes anyway: the chain executed twice.

    The reaper is a heuristic; the worker's own result is ground truth. A worker
    paused or partitioned past LOST_AFTER_SECONDS is reaped and replaced, then
    resumes and overwrites the reaper's verdict with an unconditional UPDATE
    upstream owns. The late completion is allowed to win — but the fact that two
    executions happened must survive, durably, not just as a log line.
    """

    def _reaped_and_retried(self, *, task_obj=flaky):
        """Attempt 1 declared lost and replaced by attempt 2 — the pre-condition."""
        now = timezone.now()
        WorkerHeartbeat.objects.create(worker_id="paused#aaa", label="paused", last_seen_at=now, stopped_at=now)
        parent = DBTaskResult.objects.create(
            status="RUNNING",
            args_kwargs={"args": [], "kwargs": {"fail_times": 0}},
            task_path=task_obj.module_path,
            backend_name="default",
            queue_name="default",
            run_after=now,
            started_at=now,
            worker_ids=["paused#aaa"],
        )
        reap_lost_tasks()
        child = TaskAttempt.objects.get(parent_id=parent.id)
        assert child.cause == "lost" and child.parent_completed_at is None
        return parent, child

    def _completes_late(self, parent, *, status="SUCCESSFUL"):
        """The paused worker resumes; upstream overwrites the reaper's verdict."""
        DBTaskResult.objects.filter(id=parent.id).update(
            status=status, finished_at=timezone.now(), exception_class_path="", traceback=""
        )

    def test_a_late_success_is_recorded_durably_on_the_chain(self):
        parent, child = self._reaped_and_retried()
        self._completes_late(parent)

        late = reliability.record_late_completion(parent.id)

        assert late is not None and late.parent_id == str(parent.id)
        child.refresh_from_db()
        assert child.parent_completed_at is not None, "no durable record that the chain ran twice"
        assert child.parent_status == "SUCCESSFUL"

    def test_the_receiver_records_it_on_the_success_path(self):
        """Upstream sends task_finished for successes too — that's the seam."""
        parent, child = self._reaped_and_retried()
        self._completes_late(parent)

        task_finished.send(
            sender=_worker_success_sender(),
            task_result=mock.Mock(status=TaskResultStatus.SUCCESSFUL, id=parent.id),
        )

        child.refresh_from_db()
        assert child.parent_completed_at is not None

    def test_a_normal_failure_is_not_mistaken_for_a_late_completion(self):
        """The ordinary path: fail, then get retried. Exactly one execution."""
        row = _failed_row(flaky)
        assert reliability.record_late_completion(row.id) is None
        assert maybe_retry(row.id) is not None
        assert TaskAttempt.objects.get(parent_id=row.id).parent_completed_at is None

    def test_recording_is_idempotent_across_both_detectors(self):
        parent, child = self._reaped_and_retried()
        self._completes_late(parent)

        assert reliability.record_late_completion(parent.id) is not None
        assert reliability.record_late_completion(parent.id) is None, "counted twice"
        assert reliability.detect_late_completions() == []

    def test_the_sweep_catches_one_the_signal_never_reported(self):
        """The worker died between set_successful() and sending the signal."""
        parent, child = self._reaped_and_retried()
        self._completes_late(parent)

        found = reliability.detect_late_completions()

        assert [f.parent_id for f in found] == [str(parent.id)]
        child.refresh_from_db()
        assert child.parent_completed_at is not None

    def test_the_sweep_ignores_an_attempt_still_carrying_the_reapers_verdict(self):
        """Reaped and never came back: one execution, nothing to report."""
        self._reaped_and_retried()
        assert reliability.detect_late_completions() == []

    def test_a_reaper_pass_counts_it_separately_from_raced(self):
        parent, _ = self._reaped_and_retried()
        self._completes_late(parent)

        result = reap_lost_tasks()

        assert result.reaped_then_completed == 1
        assert result.raced == 0, "a benign lost race must not be conflated with a double execution"
        assert "reaped_then_completed=1" in str(result)

    def test_a_still_ready_retry_is_cancelled_best_effort(self):
        parent, child = self._reaped_and_retried()
        assert DBTaskResult.objects.get(id=child.result_id).status == "READY"
        self._completes_late(parent)

        late = reliability.record_late_completion(parent.id)

        assert late.retry_cancelled is True
        retry_row = DBTaskResult.objects.get(id=child.result_id)
        assert retry_row.status == "FAILED"
        assert retry_row.exception_class_path == RETRY_SUPERSEDED_PATH

    def test_a_cancelled_retry_leaves_the_chain_reporting_the_real_outcome(self):
        """The retry never ran, so it is not the outcome — and nothing ran twice.

        Reporting the cancelled retry would mark a job FAILED (RetrySuperseded)
        for a run that actually succeeded, and would send a failure email for it.
        """
        parent, child = self._reaped_and_retried()
        self._completes_late(parent, status="SUCCESSFUL")
        reliability.record_late_completion(parent.id)

        outcome = reliability.chain_outcome(parent.id)

        assert outcome.status == "SUCCESSFUL", "the cancelled retry was reported as the outcome"
        assert outcome.attempt == 1
        assert outcome.executed_more_than_once is False, "nothing ran twice: the retry was cancelled"
        assert outcome.double_execution_note() == ""

    def test_a_retry_that_already_started_is_left_alone(self):
        """Cancelling what already ran would not un-execute it."""
        parent, child = self._reaped_and_retried()
        DBTaskResult.objects.filter(id=child.result_id).update(status="RUNNING")
        self._completes_late(parent)

        late = reliability.record_late_completion(parent.id)

        assert late.retry_cancelled is False
        assert DBTaskResult.objects.get(id=child.result_id).status == "RUNNING"
        # ...and it is still recorded as a double execution.
        child.refresh_from_db()
        assert child.parent_completed_at is not None

    def test_only_a_reaped_child_counts_as_evidence_of_a_late_completion(self):
        """R5a: a `failed`-cause retry is not a supersession, and must survive.

        A child row means "something retried this attempt". Only a *reap* also
        means "we declared it dead while it might still have been running",
        which is the premise of a late completion. Without the `cause=lost`
        filter, any second report of one finished task reads its own fresh retry
        as proof of a late completion and **cancels a legitimate retry** — work
        loss, with the spurious marker merely the visible half.
        """
        parent = _failed_row(flaky)
        retry_id = maybe_retry(parent.id)  # ordinary path => cause=failed
        child = TaskAttempt.objects.get(parent_id=parent.id)
        assert child.cause == TaskAttempt.Cause.FAILED

        # The same finished attempt gets reported a second time.
        self._completes_late(parent)
        assert reliability.record_late_completion(parent.id) is None

        child.refresh_from_db()
        assert child.parent_completed_at is None, "a normal retry was recorded as a supersession"
        assert child.retry_cancelled is False
        assert DBTaskResult.objects.get(id=retry_id).status == "READY", "a legitimate retry was cancelled"

    def test_a_manual_retry_is_not_evidence_of_a_late_completion_either(self):
        """`Cause.MANUAL` is already in the model: a human retrying what looks
        stuck runs the same race the reaper does, and must not be mistaken for a
        supersession the moment the original finishes."""
        parent = _failed_row(flaky)
        retry = _failed_row(flaky)
        DBTaskResult.objects.filter(id=retry.id).update(status="READY")
        TaskAttempt.objects.create(
            result_id=retry.id,
            root_id=parent.id,
            parent_id=parent.id,
            attempt=2,
            cause=TaskAttempt.Cause.MANUAL,
        )
        self._completes_late(parent)

        assert reliability.record_late_completion(parent.id) is None
        assert reliability.detect_late_completions() == []  # the sweep already agreed
        assert DBTaskResult.objects.get(id=retry.id).status == "READY"
        assert TaskAttempt.objects.get(parent_id=parent.id).parent_completed_at is None

    def test_a_reaped_child_still_counts(self):
        """The inverse: the predicate must not have been narrowed into uselessness."""
        parent, child = self._reaped_and_retried()
        assert child.cause == TaskAttempt.Cause.LOST
        self._completes_late(parent)
        assert reliability.record_late_completion(parent.id) is not None
        child.refresh_from_db()
        assert child.parent_completed_at is not None

    def test_the_repair_sweep_never_resurrects_a_cancelled_retry(self):
        """U4: the row that records a cancellation must not be retryable input.

        `_mark_superseded` writes the cancellation as FAILED with
        `RetrySuperseded` — which subclasses Exception, so the default
        `retry_on=(Exception,)` matched it. The sweep (every reaper pass, ~1/min,
        every worker) then "repaired" the cancelled retry and re-ran the task the
        cancellation existed to stop.
        """
        parent, child = self._reaped_and_retried()
        self._completes_late(parent)
        late = reliability.record_late_completion(parent.id)
        assert late.retry_cancelled is True

        # Age the cancellation past REPAIR_GRACE so the sweep considers it.
        DBTaskResult.objects.filter(id=child.result_id).update(finished_at=timezone.now() - timedelta(minutes=5))

        assert reliability.repair_missed_retries() == 0, "the sweep resurrected a cancelled retry"
        assert not TaskAttempt.objects.filter(parent_id=child.result_id).exists()

    def test_a_bookkeeping_row_is_never_retry_input_by_any_path(self):
        """Gated in `_decide`, the funnel all three retry paths share."""
        parent, child = self._reaped_and_retried()
        self._completes_late(parent)
        reliability.record_late_completion(parent.id)

        cancelled = DBTaskResult.objects.get(id=child.result_id)
        assert cancelled.exception_class_path == RETRY_SUPERSEDED_PATH
        assert maybe_retry(cancelled.id) is None
        assert maybe_retry(cancelled.id, TaskAttempt.Cause.LOST) is None
        assert reliability._decide(cancelled, TaskAttempt.Cause.FAILED) is None

    def test_a_worker_lost_row_is_still_retry_input(self):
        """The inverse: a reaped task really executed, so it stays retryable."""
        row = _failed_row(flaky, exc_path=WORKER_LOST_PATH)
        assert maybe_retry(row.id, TaskAttempt.Cause.LOST) is not None

    def test_a_resurrected_cancelled_retry_is_reported_not_hidden(self):
        """If a resurrection happens anyway, the chain must not go quiet.

        Terminating the walk at the cancelled row is exactly how U4's duplicate
        reported `attempt=1`, `executed_more_than_once=False` and an empty note.
        """
        parent, child = self._reaped_and_retried()
        self._completes_late(parent)
        reliability.record_late_completion(parent.id)

        # Fabricate what the pre-fix sweep produced: a descendant of the
        # cancelled row, which then ran.
        ghost = _failed_row(flaky)
        DBTaskResult.objects.filter(id=ghost.id).update(status="SUCCESSFUL")
        TaskAttempt.objects.create(
            result_id=ghost.id,
            root_id=parent.id,
            parent_id=child.result_id,
            attempt=3,
            cause=TaskAttempt.Cause.FAILED,
        )

        outcome = reliability.chain_outcome(parent.id)

        assert outcome.attempt == 3, "the walk stopped at the cancelled row and hid the resurrection"
        assert outcome.resurrected_cancelled_retry is True
        assert outcome.executed_more_than_once is True
        assert outcome.double_execution_note() != "", "the chain report stayed silent"
        assert "ran again unexpectedly" in outcome.double_execution_note()

    def test_chain_outcome_surfaces_the_fork(self):
        parent, child = self._reaped_and_retried()
        DBTaskResult.objects.filter(id=child.result_id).update(status="RUNNING")
        self._completes_late(parent)
        reliability.record_late_completion(parent.id)
        DBTaskResult.objects.filter(id=child.result_id).update(
            status="SUCCESSFUL", finished_at=timezone.now(), return_value={"ok": 1}
        )

        outcome = reliability.chain_outcome(parent.id)

        assert outcome.status == "SUCCESSFUL" and outcome.attempt == 2
        assert outcome.executed_more_than_once is True
        assert outcome.superseded_attempt == 1
        assert outcome.superseded_status == "SUCCESSFUL"
        assert "ran more than once" in outcome.double_execution_note()

    def test_an_ordinary_chain_is_not_reported_as_forked(self):
        first = flaky.enqueue(fail_times=1)
        _run_worker()
        outcome = reliability.chain_outcome(first.id)
        assert outcome.status == "SUCCESSFUL" and outcome.attempt == 2
        assert outcome.executed_more_than_once is False
        assert outcome.double_execution_note() == ""


class TestShippedEmailTaskRunsTwiceVisibly:
    """The double-execution guarantee, on a task SmallStack actually ships.

    `retry_lost` defaults to True, so every task that opts into retries at all is
    in T3's scope — including all three bundled email tasks. Narrowing the
    *implicit* fallback (IMPLICIT_PINNED_POLICY) does not cover them, because
    they carry an explicit `@retry_policy`: their author asserted they are safe
    to repeat. So `send_email_task` really can send twice, and the whole promise
    is that the trail says so rather than reading as one send.

    Delivery is measured as files on disk, which is what the queue actually
    produced — not `mail.outbox`, which has previously scored a working case as
    broken here.
    """

    @pytest.fixture
    def maildir(self, settings, tmp_path):
        settings.MAILERS = {
            "default": {
                "BACKEND": "django.core.mail.backends.filebased.EmailBackend",
                "OPTIONS": {"file_path": str(tmp_path)},
            }
        }
        return tmp_path

    @staticmethod
    def _delivered(maildir) -> int:
        return len(list(maildir.glob("*.log")))

    def test_a_paused_email_worker_sends_twice_and_the_trail_says_so(self, maildir, caplog):
        from apps.tasks.tasks import send_email_task

        # 1. attempt 1 is claimed, then its worker freezes past LOST_AFTER.
        first = send_email_task.enqueue(recipient="ops@example.com", subject="invoice", message="body")
        now = timezone.now()
        WorkerHeartbeat.objects.create(
            worker_id="frozen#aaa", label="frozen", hostname="box", pid=9, last_seen_at=now, stopped_at=now
        )
        DBTaskResult.objects.filter(id=first.id).update(status="RUNNING", started_at=now, worker_ids=["frozen#aaa"])

        # 2. the reaper declares it lost and enqueues a replacement. This is the
        #    step D3 does NOT prevent for a task with an explicit @retry_policy.
        reaped = reap_lost_tasks()
        assert reaped.retried == 1, "an explicitly-retryable email task IS re-run after a worker death"
        retry = TaskAttempt.objects.get(parent_id=first.id)

        # 3. the replacement runs on a real worker: send #1.
        DBTaskResult.objects.filter(id=retry.result_id).update(run_after=timezone.now())
        _run_worker()
        assert self._delivered(maildir) == 1

        # 4. the frozen worker thaws and finishes its own send: #2. Then it does
        #    exactly what upstream's run_task does — records success and signals.
        send_email_task.call(recipient="ops@example.com", subject="invoice", message="body")
        DBTaskResult.objects.filter(id=first.id).update(
            status="SUCCESSFUL", finished_at=timezone.now(), exception_class_path="", traceback=""
        )
        with caplog.at_level("WARNING", logger="apps.tasks.reliability"):
            task_finished.send(
                sender=_worker_success_sender(),
                task_result=mock.Mock(status=TaskResultStatus.SUCCESSFUL, id=first.id),
            )

        # The invoice went out twice. Every channel must say so.
        assert self._delivered(maildir) == 2, "precondition: the recipient really got two emails"

        retry.refresh_from_db()
        assert retry.parent_completed_at is not None, "no durable record on the chain"
        assert retry.retry_cancelled is False, "the replacement had already sent; nothing was cancelled"

        warnings = [r.getMessage() for r in caplog.records]
        assert any("DOUBLE EXECUTION" in w and "send_email_task" in w for w in warnings), warnings

        outcome = reliability.chain_outcome(first.id)
        assert outcome.executed_more_than_once is True
        assert "ran more than once" in outcome.double_execution_note()

    def test_the_same_path_with_the_replacement_still_queued_sends_once(self, maildir):
        """The good case: cancelled before it ran, so one email and no false alarm."""
        from apps.tasks.tasks import send_email_task

        first = send_email_task.enqueue(recipient="ops@example.com", subject="s", message="m")
        now = timezone.now()
        WorkerHeartbeat.objects.create(worker_id="frozen#bbb", label="frozen", last_seen_at=now, stopped_at=now)
        DBTaskResult.objects.filter(id=first.id).update(status="RUNNING", started_at=now, worker_ids=["frozen#bbb"])
        reap_lost_tasks()

        # The frozen worker thaws before the replacement is picked up.
        send_email_task.call(recipient="ops@example.com", subject="s", message="m")
        DBTaskResult.objects.filter(id=first.id).update(
            status="SUCCESSFUL", finished_at=timezone.now(), exception_class_path="", traceback=""
        )
        reliability.record_late_completion(first.id)
        _run_worker()  # the cancelled replacement must not send

        assert self._delivered(maildir) == 1
        outcome = reliability.chain_outcome(first.id)
        assert outcome.status == "SUCCESSFUL"
        assert outcome.executed_more_than_once is False, "a false double-execution flag is worse than none"


class TestChainOutcomeCost:
    """Fork detection rides the existing walk — the "zero extra queries" claim.

    `chain_outcome` runs on every reconcile pass for every queued run, so a
    per-link query added here is multiplied by `limit=200`. The marker fields are
    selected in the `values_list` the walk already issues; this pins that, so the
    claim fails loudly if someone later reaches for the parent row instead.
    """

    def _chain_of_two(self, *, forked: bool):
        parent, child = _failed_row(flaky), _failed_row(flaky)
        DBTaskResult.objects.filter(id__in=[parent.id, child.id]).update(status="SUCCESSFUL")
        TaskAttempt.objects.create(
            result_id=child.id,
            root_id=parent.id,
            parent_id=parent.id,
            attempt=2,
            cause=TaskAttempt.Cause.LOST,
            parent_completed_at=timezone.now() if forked else None,
            parent_status="SUCCESSFUL" if forked else "",
        )
        return parent

    @pytest.mark.parametrize("forked", [False, True])
    def test_a_two_attempt_chain_costs_three_queries_forked_or_not(self, forked):
        parent = self._chain_of_two(forked=forked)
        with CaptureQueriesContext(connection) as queries:
            outcome = reliability.chain_outcome(parent.id)
        assert outcome.executed_more_than_once is forked
        # two walk steps (the link, then the miss that ends it) + the result row.
        assert len(queries) == 3, [q["sql"] for q in queries.captured_queries]


class TestPolicy:
    def test_backoff_doubles_with_jitter_and_caps(self):
        policy = RetryPolicy(backoff=10, backoff_max=100)
        for _ in range(50):
            assert 5 <= policy.delay(1) <= 10
            assert 20 <= policy.delay(3) <= 40
            assert 50 <= policy.delay(10) <= 100

    def test_backoff_is_the_upper_bound_not_the_delay(self):
        """T4: pins the numbers the docs now quote.

        `test_backoff_doubles_with_jitter_and_caps` already asserted the true
        `[bound/2, bound]` range — while five doc sites called `backoff` "the
        first retry delay". The behaviour was right and tested; only the prose
        drifted. This states the relationship in the docs' own terms so the two
        can't diverge again.
        """
        policy = RetryPolicy(backoff=5, backoff_max=600)
        delays = [policy.delay(1) for _ in range(2000)]
        assert min(delays) >= 2.5 and max(delays) <= 5.0, "the documented 2.5-5s range"
        # The setting is the ceiling, so the mean sits at 0.75x it, not at it.
        assert 3.5 < sum(delays) / len(delays) < 4.0
        assert max(policy.delay(2) for _ in range(2000)) <= 10.0
        assert max(policy.delay(3) for _ in range(2000)) <= 20.0

    def test_decorator_validation(self):
        with pytest.raises(ValueError):
            retry_policy(max_attempts=0)
        with pytest.raises(TypeError):
            retry_policy(max_attempts=2)(lambda: None)

    def test_email_tasks_opt_in(self):
        for name in ("send_email_task", "send_html_email_task", "send_welcome_email"):
            policy = policy_for(f"apps.tasks.tasks.{name}")
            assert policy.attempts() == 3 and policy.retry_on == (OSError,)
        assert policy_for("apps.tasks.tasks.process_data_task").attempts() == 1
