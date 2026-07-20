"""Unit tests for the pure next-run math — no DB required."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.scheduler import schedules
from apps.scheduler.schedules import ScheduleConfigError

UTC = ZoneInfo("UTC")


def _job(**kw):
    """A duck-typed stand-in for a ScheduledJob (schedules.py is DB-free)."""
    kw.setdefault("timezone", "")
    return SimpleNamespace(**kw)


# --- parse_interval ---------------------------------------------------------


@pytest.mark.parametrize(
    "spec,seconds",
    [("30s", 30), ("5m", 300), ("2h", 7200), ("1d", 86400), ("1w", 604800), ("90d", 90 * 86400)],
)
def test_parse_interval_fixed(spec, seconds):
    assert schedules.parse_interval(spec) == timedelta(seconds=seconds)


def test_parse_interval_calendar_units():
    from dateutil.relativedelta import relativedelta

    assert schedules.parse_interval("1mo") == relativedelta(months=1)
    assert schedules.parse_interval("2y") == relativedelta(years=2)


@pytest.mark.parametrize("bad", ["", "5", "m", "0d", "-1h", "abc", "5x"])
def test_parse_interval_rejects_garbage(bad):
    with pytest.raises(ScheduleConfigError):
        schedules.parse_interval(bad)


# --- once -------------------------------------------------------------------


def test_once_future_returns_run_at():
    run_at = datetime(2030, 1, 1, tzinfo=UTC)
    job = _job(schedule_type="once", run_at=run_at)
    assert schedules.next_run(job, after=datetime(2026, 1, 1, tzinfo=UTC)) == run_at


def test_once_past_returns_none():
    job = _job(schedule_type="once", run_at=datetime(2020, 1, 1, tzinfo=UTC))
    assert schedules.next_run(job, after=datetime(2026, 1, 1, tzinfo=UTC)) is None


# --- interval ---------------------------------------------------------------


def test_interval_unanchored_is_after_plus_delta():
    job = _job(schedule_type="interval", interval_spec="15m", anchor_at=None)
    after = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    assert schedules.next_run(job, after=after) == after + timedelta(minutes=15)


def test_interval_anchored_locks_to_cadence():
    # Anchor 10:00, every 15m; at 10:07 the next slot is 10:15 (phase-locked),
    # NOT 10:22 (which an unanchored after+delta would give).
    anchor = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    job = _job(schedule_type="interval", interval_spec="15m", anchor_at=anchor)
    after = datetime(2026, 7, 19, 10, 7, tzinfo=UTC)
    assert schedules.next_run(job, after=after) == datetime(2026, 7, 19, 10, 15, tzinfo=UTC)


def test_interval_anchored_exact_boundary_advances():
    anchor = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    job = _job(schedule_type="interval", interval_spec="15m", anchor_at=anchor)
    # strictly-after semantics: at exactly 10:15 the next run is 10:30
    assert schedules.next_run(job, after=datetime(2026, 7, 19, 10, 15, tzinfo=UTC)) == datetime(
        2026, 7, 19, 10, 30, tzinfo=UTC
    )


def test_interval_calendar_anchored_yearly():
    # "every 1y from Dec 25" → next Dec 25 after `after`.
    anchor = datetime(2020, 12, 25, 6, 0, tzinfo=UTC)
    job = _job(schedule_type="interval", interval_spec="1y", anchor_at=anchor)
    after = datetime(2026, 7, 19, tzinfo=UTC)
    assert schedules.next_run(job, after=after) == datetime(2026, 12, 25, 6, 0, tzinfo=UTC)


# --- cron -------------------------------------------------------------------


def test_cron_daily_next():
    job = _job(schedule_type="cron", cron_expression="0 6 * * *", timezone="UTC")
    after = datetime(2026, 7, 19, 7, 0, tzinfo=UTC)
    assert schedules.next_run(job, after=after) == datetime(2026, 7, 20, 6, 0, tzinfo=UTC)


def test_cron_respects_job_timezone_across_dst():
    # 2am daily in New York. On spring-forward night (2026-03-08) local 2am does
    # not exist, so the fire correctly rolls to 3am — proving the cron is
    # evaluated in the job's own zone with real DST semantics, not naive UTC.
    job = _job(schedule_type="cron", cron_expression="0 2 * * *", timezone="America/New_York")
    ny = ZoneInfo("America/New_York")
    after = datetime(2026, 3, 7, 12, 0, tzinfo=ny)
    result = schedules.next_run(job, after=after)
    assert (result.year, result.month, result.day) == (2026, 3, 8)
    assert result.hour == 3  # 2am skipped by spring-forward → 3am
    assert result.tzinfo is not None
    # And a normal (non-DST) day fires exactly at 2am local.
    normal = schedules.next_run(job, after=datetime(2026, 3, 9, 12, 0, tzinfo=ny))
    assert normal.hour == 2


def test_cron_bad_expression_raises():
    job = _job(schedule_type="cron", cron_expression="not a cron", timezone="UTC")
    with pytest.raises(ScheduleConfigError):
        schedules.next_run(job, after=datetime(2026, 1, 1, tzinfo=UTC))


def test_canonical_timezone_normalizes_case():
    # Dev/prod parity: lowercase resolves the same on macOS and Linux.
    assert schedules.canonical_timezone("america/new_york") == "America/New_York"
    assert schedules.canonical_timezone("UTC") == "UTC"
    assert schedules.canonical_timezone("Mars/Phobos") is None
    assert schedules.canonical_timezone("") is None


def test_schedule_tz_resolves_lowercase():
    job = _job(schedule_type="cron", cron_expression="0 6 * * *", timezone="america/new_york")
    assert schedules.schedule_tz(job) == ZoneInfo("America/New_York")


def test_schedule_tz_rejects_unknown():
    job = _job(schedule_type="cron", cron_expression="0 6 * * *", timezone="Mars/Phobos")
    with pytest.raises(ScheduleConfigError):
        schedules.schedule_tz(job)


@pytest.mark.parametrize("expr", ["0 0 30 2 *", "0 0 31 4 *"])  # Feb 30, Apr 31 — never match
def test_impossible_but_valid_cron_raises_config_error(expr):
    # AI-2: a syntactically valid cron that can never match a real date must
    # raise ScheduleConfigError (→ a clean 400), not an uncaught CroniterBadDateError
    # (→ 500) from get_next().
    job = _job(schedule_type="cron", cron_expression=expr, timezone="UTC")
    with pytest.raises(ScheduleConfigError):
        schedules.next_run(job, after=datetime(2026, 1, 1, tzinfo=UTC))


# --- missed_periods ---------------------------------------------------------


def test_missed_periods_on_time_is_zero():
    job = _job(schedule_type="interval", interval_spec="1h", anchor_at=None)
    t = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    assert schedules.missed_periods(job, scheduled_for=t, now=t + timedelta(minutes=5)) == 0


def test_missed_periods_counts_full_intervals():
    job = _job(schedule_type="interval", interval_spec="1h", anchor_at=None)
    t = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    # 3h10m later → 3 whole hours missed
    assert schedules.missed_periods(job, scheduled_for=t, now=t + timedelta(hours=3, minutes=10)) == 3


def test_missed_periods_cron():
    job = _job(schedule_type="cron", cron_expression="0 * * * *", timezone="UTC")
    t = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    assert schedules.missed_periods(job, scheduled_for=t, now=datetime(2026, 7, 19, 12, 30, tzinfo=UTC)) == 2
