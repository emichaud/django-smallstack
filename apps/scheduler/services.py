"""The one core routine: decide what's due, claim it, enqueue it, record it.

All three triggers (cron POST, ``run_due_tasks`` command, ``scheduler_beat``
loop) call :func:`run_due_jobs`. Because they can overlap in time, the routine
never assumes it is the only tick running: each due job is **claimed with an
atomic conditional UPDATE** before it is enqueued, so two concurrent ticks can
never double-fire the same schedule. This is the correctness core of the whole
app — see the concurrency note in scheduler-spec §9 addendum.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F
from django.tasks import Task
from django.utils import timezone

from . import schedules
from .models import ScheduledJob, ScheduledJobRun

logger = logging.getLogger("smallstack.scheduler")

# Engine statuses that mean "this run hasn't finished". Anything else (or a
# missing result) counts as finished for overlap purposes.
_UNFINISHED = {"READY", "RUNNING"}


def _stale_run_seconds() -> int:
    """A previous run older than this is treated as abandoned (never wedge)."""
    return int(getattr(settings, "SMALLSTACK_SCHEDULER_STALE_RUN_SECONDS", 86_400))


@dataclass
class TickResult:
    enqueued: int = 0
    skipped: int = 0
    retired: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"enqueued={self.enqueued} skipped={self.skipped} "
            f"retired={self.retired} errors={self.errors}"
        )


def run_due_jobs(*, now: datetime | None = None) -> TickResult:
    """Enqueue every schedule whose ``next_run_at`` is due. Idempotent per tick."""
    now = now or timezone.now()
    result = TickResult()

    due = ScheduledJob.objects.filter(
        enabled=True, next_run_at__isnull=False, next_run_at__lte=now
    )
    for job in due:
        try:
            _process_job(job, now=now, result=result)
        except Exception:  # noqa: BLE001 — one bad job must not sink the tick
            logger.exception("scheduler: job %s (%s) failed to process", job.pk, job.name)
            result.errors += 1
    return result


def _process_job(job: ScheduledJob, *, now: datetime, result: TickResult) -> None:
    observed = job.next_run_at  # the value we must still see to win the claim

    # Compute the cursor's next position (None => 'once' job retires).
    try:
        new_next = job.compute_next_run(after=now)
    except schedules.ScheduleConfigError:
        logger.warning("scheduler: %s has invalid cadence; disabling", job.name)
        ScheduledJob.objects.filter(pk=job.pk).update(enabled=False, last_status="invalid")
        result.errors += 1
        return

    # --- atomic claim: only the tick that flips next_run_at may act on it ----
    claimed = ScheduledJob.objects.filter(pk=job.pk, next_run_at=observed).update(
        next_run_at=new_next
    )
    if not claimed:
        return  # a concurrent tick already advanced this job

    if new_next is None:
        result.retired += 1

    # --- overlap guard ------------------------------------------------------
    if not job.allow_overlap and _previous_run_active(job, now=now):
        _record(job, ScheduledJobRun.Status.SKIPPED, observed, message="previous run still active")
        result.skipped += 1
        return

    # --- catch-up policy ----------------------------------------------------
    if job.catch_up == ScheduledJob.CatchUp.SKIP:
        missed = schedules.missed_periods(job, scheduled_for=observed, now=now)
        if missed >= 1:
            _record(job, ScheduledJobRun.Status.SKIPPED, observed, message=f"missed {missed} run(s)")
            result.skipped += 1
            return

    # --- fire ---------------------------------------------------------------
    enqueue_and_record(job, scheduled_for=observed, now=now)
    result.enqueued += 1


def enqueue_and_record(job: ScheduledJob, *, scheduled_for: datetime, now: datetime | None = None) -> str:
    """Enqueue the job's task, record a QUEUED run, and bump bookkeeping.

    Shared by the tick and the UI's Run-now so both stay consistent — notably
    the ``F()`` increment, which keeps a concurrent tick + Run-now from losing a
    ``total_runs`` count. Returns the enqueued DBTaskResult id.
    """
    now = now or timezone.now()
    task_result_id = _enqueue(job)
    _record(job, ScheduledJobRun.Status.QUEUED, scheduled_for, task_result_id=task_result_id)
    ScheduledJob.objects.filter(pk=job.pk).update(
        last_enqueued_at=now,
        last_status=ScheduledJobRun.Status.QUEUED,
        total_runs=F("total_runs") + 1,
    )
    return task_result_id


def _enqueue(job: ScheduledJob) -> str:
    """Resolve the job's task and enqueue it; return the DBTaskResult id."""
    task_obj = _resolve_task(job.task_path)
    kwargs = job.kwargs or {}
    task_result = task_obj.using(queue_name=job.queue_name).enqueue(**kwargs)
    return str(getattr(task_result, "id", "") or "")


def _resolve_task(dotted: str) -> Task:
    from importlib import import_module

    module_path, attr = dotted.rsplit(".", 1)
    return getattr(import_module(module_path), attr)


def _previous_run_active(job: ScheduledJob, *, now: datetime) -> bool:
    """True if the job's last enqueued run is still unfinished and not stale.

    A run whose engine result is missing, terminal, or older than the stale
    threshold counts as *not* active — so a dead worker can never wedge a
    schedule permanently.
    """
    last = (
        job.runs.filter(status=ScheduledJobRun.Status.QUEUED)
        .exclude(task_result_id="")
        .order_by("-created_at")
        .first()
    )
    if last is None:
        return False
    if last.created_at < now - timedelta(seconds=_stale_run_seconds()):
        return False
    status = _engine_status(last.task_result_id)
    return status in _UNFINISHED


def _engine_status(task_result_id: str) -> str | None:
    """Read the django.tasks backend status for a result id (best-effort)."""
    if not task_result_id:
        return None
    try:
        from django_tasks_db.models import DBTaskResult

        row = DBTaskResult.objects.filter(id=task_result_id).values_list("status", flat=True).first()
        return row
    except Exception:  # noqa: BLE001 — backend shape may vary; treat as unknown
        return None


def _record(
    job: ScheduledJob,
    status: str,
    scheduled_for: datetime,
    *,
    task_result_id: str = "",
    message: str = "",
) -> ScheduledJobRun:
    return ScheduledJobRun.objects.create(
        job=job,
        status=status,
        scheduled_for=scheduled_for,
        task_result_id=task_result_id,
        message=message,
    )


def reconcile_run_outcomes(*, limit: int = 200) -> int:
    """Promote recent QUEUED runs to SUCCESS/FAILED from the engine's result.

    Cheap summarization so the dashboard/timeline can read terminal status off
    the run without joining DBTaskResult per row. Returns rows updated.
    """
    updated = 0
    queued = (
        ScheduledJobRun.objects.filter(status=ScheduledJobRun.Status.QUEUED)
        .exclude(task_result_id="")
        .select_related("job")  # _notify_failure reads run.job.name
        .order_by("-created_at")[:limit]
    )
    terminal = {"SUCCESSFUL": ScheduledJobRun.Status.SUCCESS, "FAILED": ScheduledJobRun.Status.FAILED}
    for run in queued:
        status = _engine_status(run.task_result_id)
        new = terminal.get(status or "")
        if not new:
            continue
        run.status = new
        run.save(update_fields=["status"])
        # Only reflect onto the job's last_status if this is its most recent run,
        # so a straggling older run can't overwrite a newer run's state.
        is_latest = not ScheduledJobRun.objects.filter(
            job_id=run.job_id, created_at__gt=run.created_at
        ).exists()
        if is_latest:
            ScheduledJob.objects.filter(pk=run.job_id).update(last_status=new)
        if new == ScheduledJobRun.Status.FAILED:
            _notify_failure(run)
        updated += 1
    return updated


def _notify_failure(run: ScheduledJobRun) -> None:
    """Email configured recipients when a scheduled run fails.

    Opt-in via ``SMALLSTACK_SCHEDULER_FAILURE_EMAILS`` (list of addresses).
    Reuses the existing ``send_email_task`` so delivery is itself backgrounded.
    Best-effort — a notification failure must not disturb reconciliation.
    """
    recipients = getattr(settings, "SMALLSTACK_SCHEDULER_FAILURE_EMAILS", None)
    if not recipients:
        return
    try:
        from apps.tasks.tasks import send_email_task

        job_name = run.job.name
        send_email_task.enqueue(
            recipient=list(recipients),
            subject=f"[scheduler] job failed: {job_name}",
            message=(
                f"Scheduled job “{job_name}” failed.\n\n"
                f"Scheduled for: {run.scheduled_for:%Y-%m-%d %H:%M %Z}\n"
                f"Task result id: {run.task_result_id}\n"
            ),
        )
    except Exception:  # noqa: BLE001
        logger.warning("scheduler: failure notification could not be enqueued", exc_info=True)
