"""@scheduled autodiscovery/sync: creation, idempotency, cadence refresh."""

from __future__ import annotations

import pytest

from apps.scheduler import decorators, registry
from apps.scheduler.decorators import ScheduleSpec
from apps.scheduler.models import ScheduledJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def clean_registry():
    """Isolate _SCHEDULE_REGISTRY per test."""
    saved = list(decorators._SCHEDULE_REGISTRY)
    decorators._SCHEDULE_REGISTRY.clear()
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


def test_sync_resolves_interval_anchor(clean_registry):
    clean_registry.append(
        _spec(name="Annual", schedule_type="interval", interval_spec="1y", anchor="12-25", cron_expression="")
    )
    registry.sync_code_jobs()
    job = ScheduledJob.objects.get(name="Annual")
    assert job.anchor_at is not None
    assert (job.anchor_at.month, job.anchor_at.day) == (12, 25)
