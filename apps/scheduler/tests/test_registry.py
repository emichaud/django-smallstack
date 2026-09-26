"""@scheduled autodiscovery/sync: creation, idempotency, cadence refresh."""

from __future__ import annotations

import pytest

from apps.scheduler import decorators, registry
from apps.scheduler.decorators import ScheduleSpec
from apps.scheduler.models import ScheduledJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def clean_registry():
    """Isolate _SCHEDULE_REGISTRY **and** the code rows already in the database.

    The registry alone is not enough: the test database is built by ``migrate``,
    which syncs the tree's real ``@scheduled`` specs, so a test that registers two
    synthetic specs was really asserting against five code rows. That made the
    relative safety valve (F-30) fire — correctly: "three of five code specs
    vanished in one sync" is exactly the partial-autodiscovery signature it
    exists to catch. Rolled back with the test transaction.
    """
    saved = list(decorators._SCHEDULE_REGISTRY)
    decorators._SCHEDULE_REGISTRY.clear()
    ScheduledJob.objects.filter(source=ScheduledJob.Source.CODE).delete()
    yield decorators._SCHEDULE_REGISTRY
    decorators._SCHEDULE_REGISTRY.clear()
    decorators._SCHEDULE_REGISTRY.extend(saved)


def _spec(**kw):
    kw.setdefault("task_path", "apps.tasks.tasks.process_data_task")
    kw.setdefault("name", "Nightly")
    kw.setdefault("schedule_type", "cron")
    kw.setdefault("cron_expression", "0 6 * * *")
    return ScheduleSpec(**kw)


def test_sync_creates_code_job(clean_registry):
    clean_registry.append(_spec())
    assert registry.sync_code_jobs() == 1

    job = ScheduledJob.objects.get(name="Nightly")
    assert job.source == ScheduledJob.Source.CODE
    assert job.cron_expression == "0 6 * * *"
    assert job.next_run_at is not None


def test_sync_is_idempotent(clean_registry):
    clean_registry.append(_spec())
    registry.sync_code_jobs()
    registry.sync_code_jobs()
    registry.sync_code_jobs()
    assert ScheduledJob.objects.filter(name="Nightly").count() == 1


def test_sync_refreshes_cadence_but_preserves_enabled(clean_registry):
    clean_registry.append(_spec(cron_expression="0 6 * * *"))
    registry.sync_code_jobs()

    # User disables the job via the UI.
    ScheduledJob.objects.filter(name="Nightly").update(enabled=False)

    # Code changes the cadence and redeploys.
    clean_registry.clear()
    clean_registry.append(_spec(cron_expression="30 7 * * *"))
    registry.sync_code_jobs()

    job = ScheduledJob.objects.get(name="Nightly")
    assert job.cron_expression == "30 7 * * *"  # cadence refreshed from code
    assert job.enabled is False  # user's pause survived the deploy


def test_sync_recomputes_next_run_on_cadence_change(clean_registry):
    clean_registry.append(_spec(cron_expression="0 6 * * *"))
    registry.sync_code_jobs()
    before = ScheduledJob.objects.get(name="Nightly").next_run_at

    # Redeploy with a different cron.
    clean_registry.clear()
    clean_registry.append(_spec(cron_expression="0 2 * * *"))
    registry.sync_code_jobs()

    job = ScheduledJob.objects.get(name="Nightly")
    # next_run_at must move to the new cadence — not stay at the old 06:00 slot
    # until one stale fire (the bug this guards).
    assert job.next_run_at != before


def test_sync_resolves_interval_anchor(clean_registry):
    clean_registry.append(
        _spec(name="Annual", schedule_type="interval", interval_spec="1y", anchor="12-25", cron_expression="")
    )
    registry.sync_code_jobs()
    job = ScheduledJob.objects.get(name="Annual")
    assert job.anchor_at is not None
    assert (job.anchor_at.month, job.anchor_at.day) == (12, 25)


# --- F-23: reconcile means both directions ----------------------------------


def test_sync_disables_a_code_job_whose_spec_disappeared(clean_registry):
    """A flag that only works on a fresh database is not a flag.

    ``SMALLSTACK_APPROVALS_SWEEP_ENABLED=False`` (and any other registration
    guard) stops the @scheduled *declaration*, but the existing ScheduledJob row
    kept firing because the sync only ever created rows. An operator who set the
    flag to stop a job saw nothing change.
    """
    clean_registry.append(_spec(name="Goes away"))
    clean_registry.append(_spec(name="Stays"))
    registry.sync_code_jobs()
    assert ScheduledJob.objects.filter(enabled=True).count() == 2

    clean_registry[:] = [_spec(name="Stays")]
    registry.sync_code_jobs()

    gone = ScheduledJob.objects.get(name="Goes away")
    assert gone.enabled is False
    assert gone.next_run_at is None
    assert ScheduledJob.objects.get(name="Stays").enabled is True


def test_sync_never_touches_operator_created_jobs(clean_registry):
    ScheduledJob.objects.create(
        name="Hand made",
        task_path="apps.tasks.tasks.process_data_task",
        schedule_type="cron",
        cron_expression="0 6 * * *",
        source=ScheduledJob.Source.UI,
    )
    clean_registry.append(_spec(name="Stays"))
    registry.sync_code_jobs()
    assert ScheduledJob.objects.get(name="Hand made").enabled is True


def test_empty_registry_is_treated_as_not_yet_discovered(clean_registry):
    """Safety valve: an empty registry almost always means autodiscovery hasn't
    run, not that every code job was deleted — retiring everything on that
    evidence would be worse than doing nothing."""
    clean_registry.append(_spec(name="Stays"))
    registry.sync_code_jobs()
    clean_registry.clear()
    registry.sync_code_jobs()
    assert ScheduledJob.objects.get(name="Stays").enabled is True


# --- F-30: retirement must be reversible ------------------------------------
#
# F-23's fix retired a code job whose spec disappeared, and had no reverse:
# `SMALLSTACK_APPROVALS_SWEEP_ENABLED=False` then `=True` left the sweep dead
# forever, because get_or_create found the existing row and `enabled` is
# operator-owned. A toggle that cannot be toggled back is worse than the bug it
# replaced — an operator who flips a flag to test something, or promotes a
# staging database, silently loses the job with no log line and no UI hint.


def test_a_returning_spec_re_enables_the_job_it_retired(clean_registry, caplog):
    """The exact two-migrate repro, as a test."""
    import logging

    clean_registry[:] = [_spec(name="Sweep"), _spec(name="Other")]
    registry.sync_code_jobs()
    assert ScheduledJob.objects.get(name="Sweep").enabled is True

    # Flag off — the registration disappears.
    clean_registry[:] = [_spec(name="Other")]
    registry.sync_code_jobs()
    retired = ScheduledJob.objects.get(name="Sweep")
    assert retired.enabled is False
    assert retired.auto_retired is True, "retirement left no marker, so it cannot be undone"
    assert retired.next_run_at is None

    # Flag back on — the documented remedy must actually work.
    clean_registry[:] = [_spec(name="Sweep"), _spec(name="Other")]
    with caplog.at_level(logging.INFO, logger="smallstack.scheduler"):
        registry.sync_code_jobs()
    restored = ScheduledJob.objects.get(name="Sweep")
    assert restored.enabled is True, "the flag is still one-way"
    assert restored.auto_retired is False
    assert restored.next_run_at is not None, "re-enabled but never rescheduled"
    assert any("re-enabled" in r.getMessage() for r in caplog.records)


def test_an_operator_disabled_job_is_not_re_enabled_by_a_sync(clean_registry, caplog):
    """The property that makes the reverse safe: `enabled` stays operator-owned.

    Negative control for the test above — without this, re-enabling on sync would
    override a deliberate pause on every deploy.
    """
    import logging

    clean_registry[:] = [_spec(name="Paused")]
    registry.sync_code_jobs()
    job = ScheduledJob.objects.get(name="Paused")
    job.enabled = False
    job.save(update_fields=["enabled"])
    assert job.auto_retired is False  # nobody marked it

    with caplog.at_level(logging.INFO, logger="smallstack.scheduler"):
        registry.sync_code_jobs()
    assert ScheduledJob.objects.get(name="Paused").enabled is False
    # …but say so, so "my job isn't running" is a one-line diagnosis.
    assert any("disabled by an operator" in r.getMessage() for r in caplog.records)


def test_a_partial_autodiscovery_failure_retires_nothing(clean_registry, caplog):
    """Relative safety valve.

    The absolute valve only catches a TOTAL import failure. One app's tasks.py
    raising on import, or `migrate` against a shared database with a different
    settings module, retires exactly that app's jobs — silently, and (before the
    reverse above) permanently.
    """
    import logging

    clean_registry[:] = [_spec(name=f"Job {i}") for i in range(5)]
    registry.sync_code_jobs()
    assert ScheduledJob.objects.filter(enabled=True).count() == 5

    # Autodiscovery half-failed: only one spec made it into the registry.
    clean_registry[:] = [_spec(name="Job 0")]
    with caplog.at_level(logging.WARNING, logger="smallstack.scheduler"):
        registry.sync_code_jobs()

    assert ScheduledJob.objects.filter(enabled=True).count() == 5, "retired on bad evidence"
    assert any("refusing to retire" in r.getMessage() for r in caplog.records)


def test_a_genuine_single_removal_is_still_retired(clean_registry):
    """Negative control for the valve — it must not block ordinary removals."""
    clean_registry[:] = [_spec(name=f"Job {i}") for i in range(5)]
    registry.sync_code_jobs()
    clean_registry[:] = [_spec(name=f"Job {i}") for i in range(4)]
    registry.sync_code_jobs()
    assert ScheduledJob.objects.get(name="Job 4").enabled is False
    assert ScheduledJob.objects.filter(enabled=True).count() == 4
