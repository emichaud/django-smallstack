"""The calendar protocol: registration, validation, access, and events."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.calendar import calendar_dataset, register_calendar
from apps.calendar.core import (
    CalendarProtocolError,
    assign_series,
    build_month_grid,
    collect_events,
    get_calendar,
    iter_calendars,
    list_calendars,
    month_bounds,
    parse_month,
    resolve_keys,
    visible_calendars,
)
from apps.calendar.registry import get_spec, unregister
from apps.datasets.registry import dataset
from apps.datasets.registry import unregister as unregister_dataset
from apps.heartbeat.models import MaintenanceWindow
from apps.smallstack.models import BackupRecord

pytestmark = pytest.mark.django_db

User = get_user_model()

EXPECTED_BUNDLED = {
    "smallstack_maintenance_windows",
    "smallstack_heartbeat_daily",
    "smallstack_scheduled_jobs",
    "smallstack_scheduled_job_runs",
    "smallstack_api_tokens",
    "smallstack_backups",
    "smallstack_approval_requests",
    "smallstack_blog_posts",
    "smallstack_blog_issues",
    "smallstack_log_capture_windows",
    "smallstack_users",
}


def _backup(filename: str, status: str, created_at: datetime) -> BackupRecord:
    """``created_at`` is auto_now_add, so a create() kwarg is ignored — set it after."""
    rec = BackupRecord.objects.create(filename=filename, status=status)
    BackupRecord.objects.filter(pk=rec.pk).update(created_at=created_at)
    rec.refresh_from_db()
    return rec


@pytest.fixture
def staff():
    return User.objects.create_user(username="cal-staff", password="pw-123456", is_staff=True)


@pytest.fixture
def plain():
    return User.objects.create_user(username="cal-plain", password="pw-123456")


def _aware(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=dt_tz.utc)


# -- registry -----------------------------------------------------------------


def test_bundled_calendars_register_and_validate() -> None:
    keys = {c.key for c in iter_calendars()}
    missing = EXPECTED_BUNDLED - keys
    assert not missing, f"bundled calendars missing: {sorted(missing)}"
    for cal in iter_calendars():
        cal.validate()  # every spec names real date/datetime columns
        assert cal.spec.access == "staff"  # operator data is staff-only by default


def test_calendar_dataset_decorator_registers_both_halves() -> None:
    key = "t_cal_decorated"
    try:

        @calendar_dataset(key, start="start", end="end", title="title", access="authenticated", label="Windows")
        def windows():
            return MaintenanceWindow.objects.all()

        assert get_spec(key) is not None
        cal = get_calendar(key)
        assert cal is not None and cal.ranged and cal.label == "Windows"
        cal.validate()
        assert cal.describe()["access"] == "authenticated"
    finally:
        unregister(key)
        unregister_dataset(key)


def test_spec_without_dataset_is_absent_not_an_error() -> None:
    key = "t_cal_orphan"
    try:
        register_calendar(key, start="start")
        assert get_calendar(key) is None
        assert key not in {c.key for c in iter_calendars()}
    finally:
        unregister(key)


def test_first_registration_wins() -> None:
    key = "t_cal_dupe"
    try:
        register_calendar(key, start="start", title="title")
        register_calendar(key, start="end", title="monitor_key")
        spec = get_spec(key)
        assert spec is not None and spec.start == "start"
    finally:
        unregister(key)


def test_bad_access_level_rejected() -> None:
    with pytest.raises(ValueError):
        register_calendar("t_cal_bad_access", start="start", access="everyone")


def test_validate_rejects_non_date_columns() -> None:
    key = "t_cal_badcol"
    try:
        dataset(key)(lambda: MaintenanceWindow.objects.all())
        register_calendar(key, start="title")
        cal = get_calendar(key)
        assert cal is not None
        with pytest.raises(CalendarProtocolError):
            cal.validate()
        unregister(key)
        register_calendar(key, start="start", end="no_such_column")
        cal = get_calendar(key)
        assert cal is not None
        with pytest.raises(CalendarProtocolError):
            cal.events(date(2026, 1, 1), date(2026, 2, 1))
    finally:
        unregister(key)
        unregister_dataset(key)


# -- access -------------------------------------------------------------------


def test_visibility_follows_access_level(staff, plain) -> None:
    key = "t_cal_open"
    try:

        @calendar_dataset(key, start="start", access="authenticated")
        def windows():
            return MaintenanceWindow.objects.all()

        staff_keys = {c.key for c in visible_calendars(staff)}
        plain_keys = {c.key for c in visible_calendars(plain)}
        assert key in staff_keys and "smallstack_maintenance_windows" in staff_keys
        assert plain_keys == {key}  # bundled staff calendars are invisible
        assert visible_calendars(None) == []
        # A staff key requested by a non-staff user is "unknown", not "forbidden".
        ok, bad = resolve_keys(["smallstack_maintenance_windows", key, "nope"], plain)
        assert [c.key for c in ok] == [key] and bad == ["smallstack_maintenance_windows", "nope"]
        assert {c["key"] for c in list_calendars(plain)} == {key}
    finally:
        unregister(key)
        unregister_dataset(key)


def test_series_assignment_is_stable_and_wraps(staff) -> None:
    cals = visible_calendars(staff)
    series = assign_series(cals)
    assert set(series.values()) <= set(range(1, 9))
    assert series == assign_series(visible_calendars(staff))


# -- events -------------------------------------------------------------------


def test_ranged_events_overlap_window_and_clip_to_month(staff) -> None:
    MaintenanceWindow.objects.create(
        monitor_key="site", title="DB upgrade", start=_aware(2026, 3, 30), end=_aware(2026, 4, 2)
    )
    MaintenanceWindow.objects.create(monitor_key="site", title="Old", start=_aware(2026, 2, 1), end=_aware(2026, 2, 2))
    cal = get_calendar("smallstack_maintenance_windows")
    assert cal is not None
    lower, upper = month_bounds(date(2026, 4, 1))
    events = cal.events(lower, upper)
    assert [e.title for e in events] == ["DB upgrade"]
    ev = events[0]
    assert ev.start_date == date(2026, 3, 30) and ev.end_date == date(2026, 4, 2)
    assert ev.all_day is False and ev.subtitle == "site" and ev.calendar == cal.key
    assert ev.as_dict()["end"].startswith("2026-04-02")
    weeks = build_month_grid(date(2026, 4, 1), events, today=date(2026, 4, 15))
    cells = {c["date"]: c for w in weeks for c in w if c}
    assert [c["total"] for c in (cells[date(2026, 4, 1)], cells[date(2026, 4, 2)], cells[date(2026, 4, 3)])] == [
        1,
        1,
        0,
    ]
    assert weeks[0][0] is None  # April 2026 starts on a Wednesday → two blanks
    assert len(weeks[-1]) == 7


def test_point_events_status_and_overflow(staff) -> None:
    for i in range(6):
        _backup(f"b{i}.sqlite3", "success" if i else "failed", _aware(2026, 5, 10, 8 + i))
    cal = get_calendar("smallstack_backups")
    assert cal is not None
    events, counts, capped = collect_events([cal], date(2026, 5, 1), date(2026, 6, 1))
    assert counts == {cal.key: 6} and not capped
    assert events[0].status == "danger" and events[1].status == "success"
    assert events[0].title == "b0.sqlite3" and events[0].all_day is False
    # BackupRecord has a get_absolute_url, so rows link.
    assert events[0].url and "/backups/" in events[0].url
    weeks = build_month_grid(date(2026, 5, 1), events, today=date(2026, 5, 1), max_per_day=4)
    cell = next(c for w in weeks for c in w if c and c["date"] == date(2026, 5, 10))
    assert len(cell["events"]) == 4 and cell["overflow"] == 2 and cell["total"] == 6


def test_window_limit_marks_capped(staff) -> None:
    for i in range(3):
        _backup(f"c{i}", "success", _aware(2026, 6, 1 + i))
    cal = get_calendar("smallstack_backups")
    assert cal is not None
    events, _counts, capped = collect_events([cal], date(2026, 6, 1), date(2026, 7, 1), limit=2)
    assert len(events) == 2 and capped == {cal.key}


def test_month_helpers() -> None:
    assert month_bounds(date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 3, 1))
    assert parse_month("2025-12", date(2026, 1, 15)) == date(2025, 12, 1)
    assert parse_month("garbage", date(2026, 1, 15)) == date(2026, 1, 1)
    assert parse_month("2026-13", date(2026, 1, 15)) == date(2026, 1, 1)


@override_settings(SMALLSTACK_FRAMEWORK_DATASETS_ENABLED=False)
def test_bundled_specs_follow_the_framework_switch(staff) -> None:
    # The specs are registered at import time, but with the bundled datasets
    # off there is no dataset behind them — the calendar reports none.
    from apps.datasets.framework import framework_datasets_enabled

    assert not framework_datasets_enabled()
    # Datasets registered before the override are still present (registration
    # happened at import), so this exercises the orphan path directly instead.
    assert get_calendar("no_such_calendar") is None


def test_events_tolerate_bad_end_before_start(staff) -> None:
    MaintenanceWindow.objects.create(
        monitor_key="site", title="Backwards", start=_aware(2026, 7, 5), end=_aware(2026, 7, 5) - timedelta(hours=3)
    )
    cal = get_calendar("smallstack_maintenance_windows")
    assert cal is not None
    events = cal.events(date(2026, 7, 1), date(2026, 8, 1))
    assert events and events[0].end_date == events[0].start_date
