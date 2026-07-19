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


def test_cadence_display():
    assert "every 5m" in _base(schedule_type="interval", interval_spec="5m").cadence_display
    assert "cron" in _base(schedule_type="cron", cron_expression="0 6 * * *").cadence_display
    once = _base(schedule_type="once", run_at=timezone.now() + timedelta(days=1))
    assert once.cadence_display.startswith("once")
