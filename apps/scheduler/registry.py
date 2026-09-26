"""Autodiscovery + idempotent sync of ``@scheduled`` specs into the DB.

``sync_code_jobs()`` is called from ``SchedulerConfig.ready()`` after
autodiscovery. It is safe to run on every boot: it *creates* a code-managed
``ScheduledJob`` if absent and *refreshes its cadence fields* if present, and it
**never deletes** — retirement is a disable, so the run history stays readable.

It does write ``enabled``, in both directions, but only for rows *it* owns the
state of — the ``auto_retired`` flag is what tells the two apart:

* **Spec disappeared** (decorator removed, app dropped from ``INSTALLED_APPS``):
  the orphan is disabled with ``auto_retired=True`` and ``next_run_at=None``.
* **Spec came back**: a row carrying ``auto_retired=True`` is re-enabled
  automatically. Without that, the flag would be a one-way switch and the
  documented remedy — re-declare the spec — would do nothing.
* **An operator disabled it by hand**: no ``auto_retired`` marker, so it stays
  off. Deliberate operator intent is never overwritten.

Two safety valves guard the retirement path, because "no spec declares this" is
also what a *broken import* looks like: an empty registry retires nothing
(total autodiscovery failure), and a large single-sync shrink retires nothing
(partial failure — one app's ``tasks.py`` raising, a different settings module).
Both log rather than act. See ``UPGRADING.md`` for what an upgrader observes.
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

    **Reconcile means both directions.** A ``source=CODE`` row whose spec is no
    longer registered — the feature was removed, or a flag like
    ``SMALLSTACK_APPROVALS_SWEEP_ENABLED`` turned its registration off — is
    disabled here. Previously only ``get_or_create`` ran, so the flag worked on a
    fresh database and did nothing on an existing install: the operator set it,
    saw no change, and the job kept firing. (F-23.) Rows the operator created in
    the UI (``source=UI``) are never touched.
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
            # The spec is back. If WE retired it (auto_retired), un-retire it —
            # otherwise the flag that stopped the job is a one-way switch and the
            # documented remedy (set it back) does nothing. A row an operator
            # disabled by hand carries no marker and stays off. (F-30.)
            if job.auto_retired:
                job.enabled = True
                job.auto_retired = False
                changed.extend(["enabled", "auto_retired"])
                logger.info(
                    "scheduler: re-enabled %r — its @scheduled spec is declared again",
                    spec.name,
                )
            elif not job.enabled:
                logger.info(
                    "scheduler: %r is declared in code but disabled by an operator "
                    "— leaving it off",
                    spec.name,
                )

            cadence_changed = any(f in changed for f in (*_CADENCE_FIELDS, "anchor_at"))
            if job.enabled and (cadence_changed or job.next_run_at is None):
                _reseed_next_run(job, spec.name)
                changed.append("next_run_at")
            if changed:
                job.save(update_fields=list(set(changed)))
        synced += 1

    # Retire code-declared rows whose spec disappeared. Disabled, not deleted:
    # the run history stays readable. The `auto_retired` marker set below is what
    # lets the branch above re-enable the row automatically if the spec returns —
    # an operator-disabled row carries no marker and is left alone.
    live_names = {spec.name for spec in _SCHEDULE_REGISTRY}
    if not live_names:
        # Safety valve: an empty registry almost always means autodiscovery
        # hasn't run (or failed), not that every code job was removed. Retiring
        # everything on that evidence would be worse than doing nothing.
        return synced
    orphans = list(
        ScheduledJob.objects.filter(source=ScheduledJob.Source.CODE, enabled=True).exclude(
            name__in=live_names
        )
    )
    if orphans and not _retirement_is_plausible(orphans, live_names):
        # Relative safety valve. The absolute one (empty registry) only catches a
        # TOTAL autodiscovery failure. A PARTIAL one — one app's tasks.py raising
        # on import, an app temporarily out of INSTALLED_APPS, `migrate` run
        # against a shared database with a different settings module — retires
        # exactly that app's jobs, silently. Treat a large single-sync shrink as
        # evidence about the registry, not about the jobs. (F-30.)
        logger.warning(
            "scheduler: refusing to retire %d code job(s) — only %d spec(s) are "
            "registered, which looks like a partial autodiscovery failure rather "
            "than a removal. Retired nothing. Orphans: %s",
            len(orphans),
            len(live_names),
            ", ".join(sorted(job.name for job in orphans)),
        )
        return synced
    for job in orphans:
        job.enabled = False
        job.auto_retired = True
        job.next_run_at = None
        job.save(update_fields=["enabled", "auto_retired", "next_run_at"])
        logger.info(
            "scheduler: disabled %r — no @scheduled spec declares it any more "
            "(will re-enable automatically if the spec returns)",
            job.name,
        )

    return synced


def _retirement_is_plausible(orphans: list, live_names: set[str]) -> bool:
    """False when this sync would retire more than half of the known code jobs.

    ``known`` is the registry plus the orphans, i.e. the set of code jobs this
    install has ever seen. Retiring one of five is a removal; retiring four of
    five is almost always a broken import.
    """
    known = len(live_names) + len(orphans)
    return len(orphans) * 2 <= known


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
