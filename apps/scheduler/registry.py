"""Autodiscovery + idempotent sync of ``@scheduled`` specs into the DB.

``sync_code_jobs()`` is called from ``SchedulerConfig.ready()`` after
autodiscovery. It is safe to run on every boot: it *creates* a code-managed
``ScheduledJob`` if absent and *refreshes its cadence fields* if present, but
never touches ``enabled`` (user-controlled) and never deletes. Removing a
``@scheduled`` decorator + redeploying leaves the row orphaned as
``source="code"`` — retired by ``prune_orphan_code_jobs`` or manual disable.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("smallstack.scheduler")


def _resolve_anchor(anchor: str, tz) -> datetime | None:
    """Resolve a decorator ``anchor`` string to an aware datetime.

    Accepts ``"MM-DD"`` (this year, midnight in the schedule TZ) or a full ISO
    date/datetime. Returns None for an empty anchor.
    """
    if not anchor:
        return None
    from django.utils import timezone as djtz

    try:
        if len(anchor) == 5 and anchor[2] == "-":  # "MM-DD"
            month, day = int(anchor[:2]), int(anchor[3:])
            ref = djtz.now().astimezone(tz)
            naive = datetime(ref.year, month, day, 0, 0)
        else:
            naive = datetime.fromisoformat(anchor)
    except (ValueError, TypeError):
        logger.warning("scheduler: bad anchor %r, ignoring", anchor)
        return None
    if djtz.is_naive(naive):
        return naive.replace(tzinfo=tz)
    return naive


def sync_code_jobs() -> int:
    """Reconcile every registered ``@scheduled`` spec into a ScheduledJob row.

    Returns the number of specs synced. Idempotent — running twice does not
    duplicate rows (``name`` is unique and used as the natural key).
    """
    from .decorators import _SCHEDULE_REGISTRY
    from .models import ScheduledJob
    from .schedules import ScheduleConfigError, schedule_tz

    synced = 0
    for spec in _SCHEDULE_REGISTRY:
        cadence = {
            "schedule_type": spec.schedule_type,
            "interval_spec": spec.interval_spec,
            "cron_expression": spec.cron_expression,
            "run_at": spec.run_at,
            "timezone": spec.timezone,
        }
        job, created = ScheduledJob.objects.get_or_create(
            name=spec.name,
            defaults={
                **cadence,
                "task_path": spec.task_path,
                "kwargs": spec.kwargs,
                "queue_name": spec.queue_name,
                "catch_up": spec.catch_up,
                "allow_overlap": spec.allow_overlap,
                "source": ScheduledJob.Source.CODE,
            },
        )

        # Resolve the anchor now that we know the job's timezone.
        anchor_at = _resolve_anchor(spec.anchor, schedule_tz(job if not created else _spec_tz(spec)))

        if created:
            if anchor_at is not None:
                job.anchor_at = anchor_at
            try:
                job.next_run_at = job.compute_next_run(after=_now())
            except ScheduleConfigError:
                logger.warning("scheduler: %s has an invalid cadence; left unscheduled", spec.name)
            job.save(update_fields=["anchor_at", "next_run_at"])
        else:
            # Refresh cadence + task wiring from code; preserve user's enabled flag,
            # overlap/catch-up (user may have tuned them), and bookkeeping.
            changed = []
            for attr, value in {**cadence, "task_path": spec.task_path, "kwargs": spec.kwargs}.items():
                if getattr(job, attr) != value:
                    setattr(job, attr, value)
                    changed.append(attr)
            if anchor_at is not None and job.anchor_at != anchor_at:
                job.anchor_at = anchor_at
                changed.append("anchor_at")
            # Ensure a code job that lost its next_run gets rescheduled.
            if job.enabled and job.next_run_at is None:
                try:
                    job.next_run_at = job.compute_next_run(after=_now())
                    changed.append("next_run_at")
                except ScheduleConfigError:
                    pass
            if changed:
                job.save(update_fields=list(set(changed)))
        synced += 1
    return synced


def _spec_tz(spec):
    """Duck-typed shim so schedule_tz() can resolve a spec's timezone pre-save."""

    class _Shim:
        timezone = spec.timezone

    return _Shim()


def _now():
    from django.utils import timezone as djtz

    return djtz.now()
