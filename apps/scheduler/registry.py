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
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ScheduledJob

logger = logging.getLogger("smallstack.scheduler")

# Cadence fields refreshed from code on every sync (task wiring included).
_CADENCE_FIELDS = ("schedule_type", "interval_spec", "cron_expression", "run_at", "timezone")


def _resolve_anchor(anchor: str, tz: tzinfo) -> datetime | None:
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
    from .schedules import schedule_tz

    synced = 0
    for spec in _SCHEDULE_REGISTRY:
        cadence = {field: getattr(spec, field) for field in _CADENCE_FIELDS}
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

        # job.timezone is populated in both branches (defaults on create), so a
        # single schedule_tz(job) resolves the anchor's zone — no spec shim needed.
        anchor_at = _resolve_anchor(spec.anchor, schedule_tz(job))

        if created:
            if anchor_at is not None:
                job.anchor_at = anchor_at
            _reseed_next_run(job, spec.name)
            job.save(update_fields=["anchor_at", "next_run_at"])
        else:
            # Task wiring always follows code. Cadence follows code too — UNLESS
            # an operator overrode the schedule in the UI, in which case we honor
            # their value (enabled, overlap/catch-up are always user-owned).
            updates = {"task_path": spec.task_path, "kwargs": spec.kwargs}
            if not job.schedule_overridden:
                updates.update(cadence)
            changed = []
            for attr, value in updates.items():
                if getattr(job, attr) != value:
                    setattr(job, attr, value)
                    changed.append(attr)
            if not job.schedule_overridden and anchor_at is not None and job.anchor_at != anchor_at:
                job.anchor_at = anchor_at
                changed.append("anchor_at")
            if job.schedule_overridden:
                logger.info("scheduler: %s keeps its UI schedule override (code cadence not applied)", spec.name)
            # If the cadence changed (or a code job lost its next_run), recompute
            # next_run_at so the new cadence takes effect on the *next* tick —
            # not one stale fire later at the old time.
            cadence_changed = any(f in changed for f in (*_CADENCE_FIELDS, "anchor_at"))
            if job.enabled and (cadence_changed or job.next_run_at is None):
                _reseed_next_run(job, spec.name)
                changed.append("next_run_at")
            if changed:
                job.save(update_fields=list(set(changed)))
        synced += 1
    return synced


def _reseed_next_run(job: ScheduledJob, name: str) -> None:
    """Recompute job.next_run_at in place; log and leave it unscheduled if invalid."""
    from .schedules import ScheduleConfigError

    try:
        job.next_run_at = job.compute_next_run(after=_now())
    except ScheduleConfigError:
        job.next_run_at = None
        logger.warning("scheduler: %s has an invalid cadence; left unscheduled", name)


def _now() -> datetime:
    from django.utils import timezone as djtz

    return djtz.now()
