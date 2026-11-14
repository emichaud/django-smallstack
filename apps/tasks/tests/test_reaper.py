"""Worker heartbeat + lost-task reaper (``heartbeat.py``, ``reaper.py``, ``db_worker``).

The suite's ``TASKS`` backend is ``ImmediateBackend``, which never leaves a
row ``RUNNING`` — so the reaper tests build ``DBTaskResult`` rows directly, and
the worker tests switch ``TASKS`` to the real ``DatabaseBackend`` and run
SmallStack's ``db_worker`` in ``--batch`` mode in-process.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone
from django_tasks_db.management.commands.db_worker import Worker
from django_tasks_db.models import DBTaskResult

from apps.tasks import heartbeat, reaper
from apps.tasks.exceptions import WORKER_LOST_PATH, WorkerLost
from apps.tasks.models import WorkerHeartbeat
from apps.tasks.reaper import reap_lost_tasks

TASK_PATH = "apps.tasks.tasks.process_data_task"
DB_TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default", "email"],
    }
}


def _running(worker_id: str = "w1", *, started_ago: float = 5, status: str = "RUNNING") -> DBTaskResult:
    now = timezone.now()
    return DBTaskResult.objects.create(
        status=status,
        args_kwargs={"args": [], "kwargs": {"data": {"x": 1}}},
        task_path=TASK_PATH,
        backend_name="default",
        queue_name="default",
        run_after=now,
        started_at=now - timedelta(seconds=started_ago),
        worker_ids=[worker_id] if worker_id else [],
    )


def _heartbeat(worker_id: str = "w1", *, seen_ago: float = 1, stopped: bool = False) -> WorkerHeartbeat:
    now = timezone.now()
    return WorkerHeartbeat.objects.create(
        worker_id=worker_id,
        label=worker_id.split(heartbeat.INCARNATION_SEP)[0],
        hostname="host-a",
        pid=4242,
        last_seen_at=now - timedelta(seconds=seen_ago),
        stopped_at=now if stopped else None,
    )


@pytest.mark.django_db
class TestReaper:
    def test_task_of_stopped_worker_is_failed_as_worker_lost(self):
        _heartbeat(stopped=True)
        row = _running()

        result = reap_lost_tasks()

        row.refresh_from_db()
        assert [t.result_id for t in result.reaped] == [str(row.id)]
        assert row.status == "FAILED"
        assert row.finished_at is not None
        assert row.exception_class_path == WORKER_LOST_PATH
        assert "exited at" in row.traceback and "host-a" in row.traceback

    def test_task_of_stale_worker_is_reaped(self):
        _heartbeat(seen_ago=reaper.lost_after_seconds() + 30)
        row = _running()

        reap_lost_tasks()

        row.refresh_from_db()
        assert row.status == "FAILED"
        assert "stopped heartbeating" in row.traceback

    def test_long_task_on_live_worker_is_left_alone(self):
        _heartbeat(seen_ago=1)
        row = _running(started_ago=10 * 86_400)

        result = reap_lost_tasks()

        row.refresh_from_db()
        assert row.status == "RUNNING"
        assert result.running == 1 and result.reaped == []

    def test_no_heartbeat_uses_the_conservative_orphan_threshold(self):
        recent = _running("legacy-a", started_ago=60)
        old = _running("legacy-b", started_ago=reaper.orphan_seconds() + 60)

        reap_lost_tasks()

        recent.refresh_from_db()
        old.refresh_from_db()
        assert recent.status == "RUNNING"
        assert old.status == "FAILED"
        assert "no heartbeat record" in old.traceback

    def test_row_without_worker_ids_falls_back_to_orphan_rule(self):
        row = _running("", started_ago=reaper.orphan_seconds() + 60)
        reap_lost_tasks()
        row.refresh_from_db()
        assert row.status == "FAILED"
        assert "worker unknown" in row.traceback

    def test_finished_and_ready_rows_are_never_touched(self):
        _heartbeat(stopped=True)
        done = _running(status="SUCCESSFUL")
        ready = _running(status="READY")

        result = reap_lost_tasks()

        assert result.running == 0
        assert DBTaskResult.objects.get(id=done.id).status == "SUCCESSFUL"
        assert DBTaskResult.objects.get(id=ready.id).status == "READY"

    def test_dry_run_reports_without_changing(self):
        _heartbeat(stopped=True)
        row = _running()

        result = reap_lost_tasks(dry_run=True)

        row.refresh_from_db()
        assert len(result.reaped) == 1
        assert row.status == "RUNNING"

    def test_a_concurrent_finish_wins_the_race(self):
        """Found lost, but the worker finished it before the UPDATE: not overwritten."""
        _heartbeat(stopped=True)
        row = _running()
        running, lost = reaper.find_lost_tasks()
        DBTaskResult.objects.filter(id=row.id).update(status="SUCCESSFUL")

        with mock.patch.object(reaper, "find_lost_tasks", return_value=(running, lost)):
            result = reap_lost_tasks()

        row.refresh_from_db()
        assert row.status == "SUCCESSFUL"
        assert row.exception_class_path == ""
        assert result.raced == 1 and result.reaped == []

    def test_reaped_row_is_a_valid_failed_task_result(self, settings):
        """The engine can rebuild the result, and WorkerLost is importable."""
        settings.TASKS = DB_TASKS  # rebuilding validates the task against the backend
        _heartbeat(stopped=True)
        row = _running()
        reap_lost_tasks()
        row.refresh_from_db()

        task_result = row.task_result
        assert task_result.status.name == "FAILED"
        assert task_result.errors[0].exception_class is WorkerLost

    def test_scheduler_summary_shows_the_reason(self):
        from apps.scheduler.services import _summarize_error

        _heartbeat(stopped=True)
        row = _running()
        reap_lost_tasks()
        row.refresh_from_db()
        assert _summarize_error(row.traceback).startswith("WorkerLost: worker w1")

    def test_old_heartbeats_are_pruned(self):
        old = _heartbeat("gone", seen_ago=8 * 86_400)
        live = _heartbeat("live")

        result = reap_lost_tasks()

        assert result.heartbeats_pruned == 1
        assert not WorkerHeartbeat.objects.filter(pk=old.pk).exists()
        assert WorkerHeartbeat.objects.filter(pk=live.pk).exists()

    def test_reap_tasks_command(self, capsys):
        _heartbeat(stopped=True)
        row = _running()

        call_command("reap_tasks", "--dry-run")
        assert f"would reap {row.id}" in capsys.readouterr().out
        assert DBTaskResult.objects.get(id=row.id).status == "RUNNING"

        call_command("reap_tasks")
        assert f"reaped {row.id}" in capsys.readouterr().out
        assert DBTaskResult.objects.get(id=row.id).status == "FAILED"


@pytest.mark.django_db
class TestHeartbeat:
    def test_register_is_idempotent_for_one_incarnation(self):
        heartbeat.register_worker("w9", "w9", "default,email")
        hb = WorkerHeartbeat.objects.get(worker_id="w9")
        assert hb.queues == "default,email" and hb.pid and hb.stopped_at is None

        heartbeat.mark_stopped("w9")
        assert WorkerHeartbeat.objects.get(worker_id="w9").stopped_at is not None

        heartbeat.register_worker("w9", "w9", "*")
        hb = WorkerHeartbeat.objects.get(worker_id="w9")
        assert hb.stopped_at is None and hb.queues == "*"

    def test_beat_and_reap_errors_never_escape(self):
        thread = heartbeat.HeartbeatThread("w1", interval=0.01)
        with mock.patch.object(heartbeat, "beat", side_effect=RuntimeError("db gone")):
            thread._beat()
        with mock.patch.object(heartbeat, "reap_lost_tasks", side_effect=RuntimeError("db gone")):
            thread._reap()

    def test_mark_stopped_swallows_errors(self):
        with mock.patch.object(WorkerHeartbeat.objects, "filter", side_effect=RuntimeError("db gone")):
            heartbeat.mark_stopped("w1")


@pytest.mark.django_db
class TestWorkerIncarnation:
    """A heartbeat row identifies a *process*, not the operator's --worker-id.

    ``--worker-id`` is a stable label — SmallStack's own cli-reference advertises
    ``--worker-id mail-1`` — so it names a pool member, not an incarnation. While
    the row was keyed on it, the task → claimant join was ambiguous by
    construction, in both directions.
    """

    def test_a_restart_under_the_same_label_still_reaps_the_lost_task(self):
        """W1: a live worker reusing a label must not shadow its dead predecessor.

        While the row was label-keyed, the successor's registration reset
        ``last_seen_at`` and cleared ``stopped_at``, so the task the *predecessor*
        abandoned looked like it belonged to a live worker. It stayed hidden for
        as long as that label had a live worker — unbounded for a long-lived
        production worker, and permanent if the successor was also killed.
        """
        dead = heartbeat.new_incarnation("mail-1")
        heartbeat.register_worker(dead, "mail-1", "*")
        WorkerHeartbeat.objects.filter(worker_id=dead).update(
            last_seen_at=timezone.now() - timedelta(seconds=reaper.lost_after_seconds() + 60), pid=67197
        )
        stuck = _running(dead, started_ago=700)

        # The supervisor restarts the worker under the *same* --worker-id.
        successor = heartbeat.new_incarnation("mail-1")
        heartbeat.register_worker(successor, "mail-1", "*")
        WorkerHeartbeat.objects.filter(worker_id=successor).update(pid=67257)

        reap_lost_tasks()

        stuck.refresh_from_db()
        assert stuck.status == "FAILED", "a live worker reusing the label hid its predecessor's task"
        assert stuck.exception_class_path == WORKER_LOST_PATH
        # Attribution: the reason must name the incarnation that actually claimed
        # the task, not whichever process currently holds the label. An operator
        # debugging from this line would otherwise inspect the wrong process.
        assert "pid 67197" in stuck.traceback, f"misattributed to the successor: {stuck.traceback}"
        assert "pid 67257" not in stuck.traceback
        assert "worker mail-1" in stuck.traceback, "the reason should name the operator's label"

    def test_one_workers_clean_exit_does_not_reap_anothers_live_task(self):
        """W2: two processes sharing a label must not share a liveness row."""
        a, b = heartbeat.new_incarnation("pool"), heartbeat.new_incarnation("pool")
        heartbeat.register_worker(a, "pool", "*")
        heartbeat.register_worker(b, "pool", "*")
        a_task, b_task = _running(a), _running(b)

        heartbeat.mark_stopped(a)  # host A finished its task and exited cleanly
        reap_lost_tasks()

        a_task.refresh_from_db()
        b_task.refresh_from_db()
        assert a_task.status == "FAILED"  # A really did abandon this one
        assert b_task.status == "RUNNING", "B's live task was reaped by A's exit"

    def test_both_incarnations_get_their_own_row(self):
        first = heartbeat.new_incarnation("mail-1")
        second = heartbeat.new_incarnation("mail-1")
        assert first != second
        heartbeat.register_worker(first, "mail-1", "*")
        heartbeat.register_worker(second, "mail-1", "*")
        rows = WorkerHeartbeat.objects.filter(label="mail-1")
        assert rows.count() == 2, "a label must not be unique; an incarnation must be"

    def test_a_claim_with_no_incarnation_row_falls_through_to_orphan(self):
        """Constraint: never use stopped_at/LOST_AFTER without an exact match.

        Covers a plain upstream worker, a pre-upgrade claim, and an incarnation
        whose row was pruned — all of which must be neither instantly reapable
        nor permanently unreapable.
        """
        # A stopped row for the *label*; the task names an incarnation of it.
        heartbeat.register_worker("mail-1", "mail-1", "*")
        heartbeat.mark_stopped("mail-1")
        recent = _running("mail-1#gone", started_ago=60)
        old = _running("mail-1#gone", started_ago=reaper.orphan_seconds() + 60)

        reap_lost_tasks()

        recent.refresh_from_db()
        old.refresh_from_db()
        assert recent.status == "RUNNING", "reaped on a partial match"
        assert old.status == "FAILED" and "no heartbeat record" in old.traceback


@pytest.mark.django_db
class TestReaperSelfExclusion:
    """A worker cannot be dead while it is running the reaper pass.

    Every worker is also a reaper. When a worker's heartbeat writes start failing
    — a starved container, a saturated database, SQLite write contention — its
    own row goes stale, and without this invariant its *own* next reaper pass
    reads that row, decides the task it is executing right now is lost, fails it
    as WorkerLost and enqueues a second attempt beside the running one.
    """

    def test_a_worker_does_not_reap_the_task_it_is_running(self):
        me = heartbeat.new_incarnation("w-hog")
        heartbeat.register_worker(me, "w-hog", "*")
        # Its beats have been failing: the row is well past the threshold.
        WorkerHeartbeat.objects.filter(worker_id=me).update(
            last_seen_at=timezone.now() - timedelta(seconds=reaper.lost_after_seconds() + 60)
        )
        mine = _running(me, started_ago=25)

        heartbeat.safe_reap(me)  # this process's own pass

        mine.refresh_from_db()
        assert mine.status == "RUNNING", "the reaper failed the task its own process was executing"

    def test_self_exclusion_does_not_protect_other_stale_workers(self):
        """R5's inverse: excluding myself must not blind me to real deaths."""
        me = heartbeat.new_incarnation("w-live")
        heartbeat.register_worker(me, "w-live", "*")
        dead = _heartbeat("w-dead", seen_ago=reaper.lost_after_seconds() + 60)
        mine, theirs = _running(me), _running(dead.worker_id)

        heartbeat.safe_reap(me)

        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert mine.status == "RUNNING"
        assert theirs.status == "FAILED"

    def test_exclusion_is_by_incarnation_not_label(self):
        """Two live processes sharing a label must still reap each other's deaths."""
        mine = heartbeat.new_incarnation("pool")
        dead_sibling = heartbeat.new_incarnation("pool")
        heartbeat.register_worker(mine, "pool", "*")
        heartbeat.register_worker(dead_sibling, "pool", "*")
        WorkerHeartbeat.objects.filter(worker_id=dead_sibling).update(
            last_seen_at=timezone.now() - timedelta(seconds=reaper.lost_after_seconds() + 60)
        )
        abandoned = _running(dead_sibling)

        heartbeat.safe_reap(mine)

        abandoned.refresh_from_db()
        assert abandoned.status == "FAILED", "excluding the label would hide a dead sibling"

    def test_safe_reap_leaves_a_callers_transaction_alone(self):
        """A connection inside atomic() belongs to the caller: never closed.

        close_old_connections() would close it (autocommit differs inside a
        transaction). On Postgres that killed these tests' own transaction
        ("the connection is closed"); SQLite in-memory ignores close(), which
        is why this asserts on the call rather than on the connection's health.
        """
        from django.db import connections, transaction

        conn = connections["default"]  # the wrapper itself, not the proxy
        with transaction.atomic():
            assert conn.in_atomic_block
            with mock.patch.object(type(conn), "close_if_unusable_or_obsolete", autospec=True) as close_check:
                heartbeat.safe_reap("anyone")
            assert not any(call.args[0] is conn for call in close_check.call_args_list)

    def test_refresh_still_checks_connections_outside_a_transaction(self):
        """The guard narrows the refresh; it must not disable it."""
        from django.db import connections

        conn = connections["default"]
        conn.ensure_connection()
        with (
            mock.patch.object(conn, "in_atomic_block", False),
            mock.patch.object(type(conn), "close_if_unusable_or_obsolete", autospec=True) as close_check,
        ):
            heartbeat.refresh_owned_connections()
        assert any(call.args[0] is conn for call in close_check.call_args_list)

    def test_an_external_reaper_pass_excludes_nothing(self):
        """manage.py reap_tasks is not a worker; it has no incarnation to exclude."""
        dead = _heartbeat("gone", stopped=True)
        row = _running(dead.worker_id)
        reap_lost_tasks()
        row.refresh_from_db()
        assert row.status == "FAILED"


@pytest.mark.django_db
class TestHeartbeatBackoff:
    """A worker that cannot write its own beat must stop judging others."""

    def test_missed_beats_are_counted_and_logged_loudly(self, caplog):
        thread = heartbeat.HeartbeatThread("w1", interval=0.01)
        with mock.patch.object(heartbeat, "beat", side_effect=RuntimeError("database is locked")):
            with caplog.at_level("WARNING", logger="apps.tasks.heartbeat"):
                thread._beat()
                thread._beat()
        assert thread.missed_beats == 2
        # Not DEBUG: this is how both the live-task-kill and the false-death begin.
        assert any("heartbeat for w1 skipped" in r.getMessage() for r in caplog.records)

    def test_a_worker_with_missed_beats_declines_to_reap(self, caplog):
        thread = heartbeat.HeartbeatThread("w1", interval=0.01)
        thread.missed_beats = heartbeat.MAX_MISSED_BEATS_BEFORE_YIELDING
        with mock.patch.object(heartbeat, "safe_reap") as reap:
            with caplog.at_level("WARNING", logger="apps.tasks.heartbeat"):
                thread._reap()
        reap.assert_not_called()
        assert any("skipping its reaper pass" in r.getMessage() for r in caplog.records)

    def test_a_successful_beat_clears_the_counter(self):
        thread = heartbeat.HeartbeatThread("w1", interval=0.01)
        thread.missed_beats = 5
        with mock.patch.object(heartbeat, "beat"):
            thread._beat()
        assert thread.missed_beats == 0
        with mock.patch.object(heartbeat, "safe_reap") as reap:
            thread._reap()
        reap.assert_called_once()


@pytest.mark.django_db
class TestHeartbeatClock:
    """Staleness is measured on the database's clock, not on any app server's.

    ``last_seen_at`` is written by the worker host and the threshold is evaluated
    by the reaper host. While both used ``timezone.now()``, the 90s window was
    really a measure of NTP skew between them: a worker whose clock ran slow
    looked permanently dead and its *live* tasks were reaped and retried.
    """

    @staticmethod
    def _skew(seconds: float):
        """Patch this process's wall clock forward — as if its NTP had drifted."""
        return mock.patch.object(timezone, "now", return_value=timezone.now() + timedelta(seconds=seconds))

    def test_writers_ignore_a_skewed_app_clock(self):
        real = timezone.now()
        with self._skew(600):
            heartbeat.register_worker("skewed", "skewed", "*")
        hb = WorkerHeartbeat.objects.get(worker_id="skewed")
        assert abs((hb.last_seen_at - real).total_seconds()) < 60, "register_worker used the app clock"

        WorkerHeartbeat.objects.filter(worker_id="skewed").update(last_seen_at=real - timedelta(hours=1))
        with self._skew(600):
            heartbeat.beat("skewed")
        hb.refresh_from_db()
        assert abs((hb.last_seen_at - real).total_seconds()) < 60, "beat() used the app clock"

        with self._skew(600):
            heartbeat.mark_stopped("skewed")
        hb.refresh_from_db()
        assert abs((hb.stopped_at - real).total_seconds()) < 60, "mark_stopped() used the app clock"

    def test_a_reaper_whose_clock_runs_fast_leaves_a_live_workers_task_alone(self):
        """The regression: skew must not look like a missed heartbeat."""
        heartbeat.register_worker("live", "live", "*")
        row = _running("live")

        with self._skew(10 * reaper.lost_after_seconds()):
            result = reap_lost_tasks()

        row.refresh_from_db()
        assert row.status == "RUNNING", f"live worker's task reaped on clock skew alone: {result}"
        assert result.reaped == []

    def test_a_genuinely_stale_worker_is_still_reaped(self):
        """The inverse: the fix must not blind the reaper to a real dead worker."""
        heartbeat.register_worker("goner", "goner", "*")
        WorkerHeartbeat.objects.filter(worker_id="goner").update(
            last_seen_at=timezone.now() - timedelta(seconds=reaper.lost_after_seconds() + 60)
        )
        row = _running("goner")

        reap_lost_tasks()

        row.refresh_from_db()
        assert row.status == "FAILED"
        assert "stopped heartbeating" in row.traceback


@pytest.mark.django_db(transaction=True)
class TestHeartbeatThread:
    def test_thread_beats_and_reaps_until_stopped(self):
        heartbeat.register_worker("me", "me", "*")
        WorkerHeartbeat.objects.filter(worker_id="me").update(last_seen_at=timezone.now() - timedelta(seconds=30))
        before = WorkerHeartbeat.objects.get(worker_id="me").last_seen_at
        _heartbeat("dead", stopped=True)
        lost = _running("dead")

        thread = heartbeat.HeartbeatThread("me", interval=0.02, reap_every=1)
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if WorkerHeartbeat.objects.get(worker_id="me").last_seen_at > before:
                break
            time.sleep(0.02)
        thread.stop()

        assert not thread.is_alive()
        assert WorkerHeartbeat.objects.get(worker_id="me").last_seen_at > before
        assert DBTaskResult.objects.get(id=lost.id).status == "FAILED"


@pytest.mark.django_db(transaction=True)
class TestDbWorkerCommand:
    """SmallStack's db_worker shadows upstream and wraps it with a heartbeat."""

    @pytest.fixture(autouse=True)
    def _database_backend(self, settings):
        settings.TASKS = DB_TASKS

    def _run_worker(self, worker_id: str) -> None:
        # Upstream installs SIGINT/SIGTERM handlers; keep pytest's.
        with mock.patch.object(Worker, "configure_signals"):
            call_command(
                "db_worker",
                batch=True,
                startup_delay=False,
                queue_name="*",
                worker_id=worker_id,
                verbosity=0,
            )

    def test_exclude_queues_passes_through_and_is_recorded(self):
        """django-tasks-db 0.13's --exclude-queues works through the override."""
        from apps.tasks.tasks import process_data_task, send_email_task

        data = process_data_task.enqueue(data={"k": "v"})
        mail = send_email_task.enqueue(recipient="a@example.com", subject="s", message="m")

        with mock.patch.object(Worker, "configure_signals"):
            call_command(
                "db_worker",
                batch=True,
                startup_delay=False,
                queue_name="*",
                exclude_queues="email",
                worker_id="no-mail",
                verbosity=0,
            )

        assert DBTaskResult.objects.get(id=data.id).status == "SUCCESSFUL"
        assert DBTaskResult.objects.get(id=mail.id).status == "READY"  # excluded, untouched
        hb = WorkerHeartbeat.objects.get(label="no-mail")
        assert hb.queues == "* (excluding email)"

    def test_worker_registers_runs_tasks_and_marks_stopped(self):
        from apps.tasks.tasks import process_data_task

        result = process_data_task.enqueue(data={"k": "v"})
        assert DBTaskResult.objects.get(id=result.id).status == "READY"

        self._run_worker("cmd-worker")

        assert DBTaskResult.objects.get(id=result.id).status == "SUCCESSFUL"
        hb = WorkerHeartbeat.objects.get(label="cmd-worker")
        assert hb.stopped_at is not None
        # The row is keyed on the incarnation the worker handed upstream, and that
        # is what the claim recorded — so the reaper can join them exactly.
        assert hb.worker_id.startswith("cmd-worker" + heartbeat.INCARNATION_SEP)
        assert DBTaskResult.objects.get(id=result.id).worker_ids[-1] == hb.worker_id

    def test_worker_reaps_a_dead_predecessors_task_at_startup(self):
        _heartbeat("predecessor", seen_ago=reaper.lost_after_seconds() + 60)
        lost = _running("predecessor")

        self._run_worker("successor")

        row = DBTaskResult.objects.get(id=lost.id)
        assert row.status == "FAILED"
        assert row.exception_class_path == WORKER_LOST_PATH

    def test_startup_reap_does_not_catch_a_predecessor_still_inside_the_window(self):
        """The startup pass is a head start, not a clean-queue guarantee.

        A supervisor normally restarts a crashed worker well inside
        LOST_AFTER_SECONDS, so its predecessor's heartbeat is not yet stale and
        its abandoned task cannot be judged at startup. The heartbeat thread's
        pass reaps it once the threshold elapses. The docstrings claimed the
        startup pass failed a crashed predecessor's tasks "before this worker
        claims anything", which is wrong for exactly the normal case — this pins
        the real ordering so the claim cannot drift back.
        """
        _heartbeat("recent#aaa", seen_ago=2)  # crashed 2s ago; threshold is 90s
        still_fresh = _running("recent#aaa")

        self._run_worker("successor")

        still_fresh.refresh_from_db()
        assert still_fresh.status == "RUNNING", "reaped a predecessor too fresh to judge"

        # Once the predecessor is genuinely stale, a pass does catch it.
        WorkerHeartbeat.objects.filter(worker_id="recent#aaa").update(
            last_seen_at=timezone.now() - timedelta(seconds=reaper.lost_after_seconds() + 60)
        )
        reap_lost_tasks()
        still_fresh.refresh_from_db()
        assert still_fresh.status == "FAILED"

    def test_marks_stopped_even_when_the_worker_exits_via_sys_exit(self):
        with mock.patch.object(Worker, "run", side_effect=SystemExit(1)), pytest.raises(SystemExit):
            self._run_worker("forced")
        assert WorkerHeartbeat.objects.get(label="forced").stopped_at is not None

    def test_disabled_is_a_pure_pass_through(self, settings):
        settings.SMALLSTACK_TASKS_HEARTBEAT_ENABLED = False
        self._run_worker(f"plain-{uuid.uuid4().hex[:6]}")
        assert not WorkerHeartbeat.objects.exists()
