"""Tests for the ``maintenance`` management command and its helpers."""

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.timezone import localtime, now

from apps.heartbeat.models import MaintenanceWindow

pytestmark = pytest.mark.django_db


def _run(*args):
    out = StringIO()
    call_command("maintenance", *args, stdout=out)
    return out.getvalue()


def test_open_minutes_creates_window():
    _run("open", "--minutes", "30", "--title", "Test")

    window = MaintenanceWindow.objects.get()
    assert window.title == "Test"
    assert window.exclude_from_sla is True
    delta = (window.end - window.start).total_seconds()
    assert 29 * 60 <= delta <= 31 * 60


def test_open_window_marks_now_as_in_maintenance():
    _run("open", "--minutes", "10", "--title", "Deploy")
    # The command must feed the real SLA path the status page reads.
    assert MaintenanceWindow.is_in_maintenance(now()) is True


def test_open_start_end_parses_iso():
    # Naive input is interpreted in the project timezone (like the staff form),
    # so we compare against the localtime round-trip rather than raw UTC.
    start_str = "2099-07-01 02:00"
    end_str = "2099-07-01 03:00"
    _run("open", "--start", start_str, "--end", end_str, "--title", "Scheduled")

    window = MaintenanceWindow.objects.get()
    assert window.start.tzinfo is not None
    assert window.end.tzinfo is not None
    assert localtime(window.start).strftime("%Y-%m-%d %H:%M") == start_str
    assert (window.end - window.start) == timedelta(hours=1)


def test_open_rejects_minutes_and_explicit_bounds():
    with pytest.raises(CommandError):
        _run("open", "--minutes", "10", "--start", "2026-07-01 02:00", "--end", "2026-07-01 03:00")


def test_open_rejects_end_before_start():
    start = now() + timedelta(days=1)
    end = start - timedelta(hours=1)
    with pytest.raises(CommandError):
        _run("open", "--start", start.strftime("%Y-%m-%d %H:%M"), "--end", end.strftime("%Y-%m-%d %H:%M"))


def test_no_sla_exclude_flag():
    _run("open", "--minutes", "15", "--title", "Info", "--no-sla-exclude")
    assert MaintenanceWindow.objects.get().exclude_from_sla is False


def test_close_ends_active_window():
    _run("open", "--minutes", "60", "--title", "Deploy")
    assert MaintenanceWindow.is_in_maintenance(now()) is True

    out = _run("close")
    assert "ended 1 active" in out
    assert MaintenanceWindow.is_in_maintenance(now()) is False
    # Row is kept (ended), not deleted, so the maintenance history survives.
    assert MaintenanceWindow.objects.count() == 1


def test_close_delete_future():
    start = now() + timedelta(days=1)
    end = start + timedelta(hours=1)
    _run("open", "--start", start.strftime("%Y-%m-%d %H:%M"), "--end", end.strftime("%Y-%m-%d %H:%M"))
    assert MaintenanceWindow.objects.count() == 1

    _run("close", "--delete-future")
    assert MaintenanceWindow.objects.count() == 0


def test_close_with_nothing_active():
    out = _run("close")
    assert "No active maintenance windows" in out


def test_list_json():
    _run("open", "--minutes", "20", "--title", "Listed")
    out = _run("list", "--json")
    rows = json.loads(out)
    assert len(rows) == 1
    assert rows[0]["title"] == "Listed"
    assert rows[0]["active"] is True


def test_list_active_only():
    # One active, one future.
    _run("open", "--minutes", "30", "--title", "Active")
    future = now() + timedelta(days=2)
    _run(
        "open",
        "--start",
        future.strftime("%Y-%m-%d %H:%M"),
        "--end",
        (future + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "--title",
        "Future",
    )

    rows = json.loads(_run("list", "--active", "--json"))
    assert [r["title"] for r in rows] == ["Active"]


def test_monitor_scoping():
    _run("open", "--minutes", "30", "--title", "DB", "--monitor", "database")
    assert MaintenanceWindow.is_in_maintenance(now(), "database") is True
    assert MaintenanceWindow.is_in_maintenance(now(), "site") is False
