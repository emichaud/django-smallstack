"""ScheduledJob validation + save-time bookkeeping."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.scheduler.models import ScheduledJob

pytestmark = pytest.mark.django_db


def _base(**kw):
    kw.setdefault("name", "job")
    kw.setdefault("task_path", "apps.tasks.tasks.process_data_task")
    return ScheduledJob(**kw)


def test_clean_requires_field_for_type():
    with pytest.raises(ValidationError):
        _base(schedule_type="interval").clean()  # missing interval_spec
    with pytest.raises(ValidationError):
        _base(schedule_type="cron").clean()  # missing cron_expression
    with pytest.raises(ValidationError):
        _base(schedule_type="once").clean()  # missing run_at


def test_clean_rejects_bad_interval_and_cron():
    with pytest.raises(ValidationError):
        _base(schedule_type="interval", interval_spec="banana").clean()
    with pytest.raises(ValidationError):
        _base(schedule_type="cron", cron_expression="99 99 * * *").clean()


def test_clean_accepts_valid():
    _base(schedule_type="interval", interval_spec="5m").clean()  # no raise
    _base(schedule_type="cron", cron_expression="0 6 * * *").clean()


def test_save_seeds_next_run_at_when_enabled():
    job = _base(name="seed", schedule_type="interval", interval_spec="1h", enabled=True)
    job.save()
    assert job.next_run_at is not None
    assert job.next_run_at > timezone.now()


def test_save_does_not_seed_when_disabled():
    job = _base(name="disabled", schedule_type="interval", interval_spec="1h", enabled=False)
    job.save()
    assert job.next_run_at is None


def test_save_reseeds_next_run_on_cadence_change():
    # F-A1: a retune (via form/API/programmatic save) must recompute next_run_at,
    # not leave it pointing at the old cadence until one stale fire.
    job = _base(name="retune", schedule_type="interval", interval_spec="1h", enabled=True)
    job.save()
    before = job.next_run_at  # ~now + 1h

    job.interval_spec = "5m"
    job.save()
    assert job.next_run_at < before  # moved to the new, sooner cadence
    assert job.next_run_at <= timezone.now() + timedelta(minutes=6)


def test_save_does_not_reseed_on_non_cadence_change():
    job = _base(name="descr", schedule_type="interval", interval_spec="1h", enabled=True)
    job.save()
    before = job.next_run_at

    job.description = "just a note"
    job.save()
    assert job.next_run_at == before  # unchanged — no cadence field moved


def test_save_reseeds_under_partial_update_fields():
    # A serializer that saves only the changed cadence field still gets a reseed.
    job = _base(name="partial", schedule_type="interval", interval_spec="1h", enabled=True)
    job.save()
    before = job.next_run_at

    job.cron_expression = ""  # keep interval; just shorten it
    job.interval_spec = "10m"
    job.save(update_fields=["interval_spec"])
    job.refresh_from_db()
    assert job.next_run_at < before  # next_run_at persisted despite update_fields


def test_cadence_display():
    assert "every 5m" in _base(schedule_type="interval", interval_spec="5m").cadence_display
    assert "cron" in _base(schedule_type="cron", cron_expression="0 6 * * *").cadence_display
    once = _base(schedule_type="once", run_at=timezone.now() + timedelta(days=1))
    assert once.cadence_display.startswith("once")
