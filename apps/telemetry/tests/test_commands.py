"""The two management commands: retention (`prune_logs`) and the capture
window control surface (`log_capture`)."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.telemetry import capture
from apps.telemetry.handlers import DatabaseLogHandler
from apps.telemetry.models import LogCaptureWindow, LogRecord

pytestmark = pytest.mark.django_db


def make_rows(count, *, age_days=0, level="WARNING"):
    ts = timezone.now() - timedelta(days=age_days)
    LogRecord.objects.bulk_create(
        [
            LogRecord(ts=ts - timedelta(seconds=i), level=level, level_no=30, logger="apps.demo", message=f"row {i}")
            for i in range(count)
        ]
    )


def run(command, *args, **options):
    out = StringIO()
    call_command(command, *args, stdout=out, **options)
    return out.getvalue()


# ---------------------------------------------------------------------------
# prune_logs
# ---------------------------------------------------------------------------


def test_prune_deletes_by_age():
    make_rows(3, age_days=30)
    make_rows(2, age_days=0)

    run("prune_logs", "--keep-days", "7", "--max-rows", "10000")

    assert LogRecord.objects.count() == 2


def test_prune_enforces_the_row_cap():
    """Age alone can't save you from an incident that logs a million lines in
    ten minutes."""
    make_rows(50, age_days=0)

    run("prune_logs", "--keep-days", "7", "--max-rows", "10")

    assert LogRecord.objects.count() == 10


def test_prune_keeps_the_newest_rows_when_capping():
    make_rows(5, age_days=0)
    newest = LogRecord.objects.order_by("-ts").first()

    run("prune_logs", "--max-rows", "2")

    assert LogRecord.objects.filter(pk=newest.pk).exists()


def test_prune_is_a_noop_when_within_limits():
    make_rows(3)
    output = run("prune_logs", "--keep-days", "7", "--max-rows", "1000")

    assert LogRecord.objects.count() == 3
    assert "deleted 0 by age" in output


@override_settings(TELEMETRY_LOG_RETENTION_DAYS=1, TELEMETRY_LOG_MAX_ROWS=5)
def test_prune_defaults_come_from_settings():
    make_rows(3, age_days=3)
    make_rows(20, age_days=0)

    run("prune_logs")

    assert LogRecord.objects.count() == 5


def test_prune_keeps_capture_windows_longer_than_logs():
    """Who turned verbosity up, and why, is an audit trail — it outlives the
    logs the window produced."""
    LogCaptureWindow.objects.create(level="DEBUG", expires_at=timezone.now() - timedelta(days=30))

    run("prune_logs", "--keep-days", "7")

    assert LogCaptureWindow.objects.count() == 1


def test_prune_eventually_drops_ancient_capture_windows():
    LogCaptureWindow.objects.create(level="DEBUG", expires_at=timezone.now() - timedelta(days=200))

    run("prune_logs", "--keep-days", "7")

    assert LogCaptureWindow.objects.count() == 0


# ---------------------------------------------------------------------------
# log_capture
# ---------------------------------------------------------------------------


def test_log_capture_start_opens_a_window():
    output = run("log_capture", "start", "--level", "DEBUG", "--minutes", "15")

    window = capture.active_window()
    assert window is not None
    assert window.level == "DEBUG"
    assert "Capturing DEBUG until" in output


def test_log_capture_start_records_the_reason():
    run("log_capture", "start", "--note", "chasing the checkout 500")
    assert capture.active_window().note == "chasing the checkout 500"


def test_log_capture_start_does_not_claim_clamping_when_there_was_none():
    """Regression: the clamp message used to fire unconditionally because it
    compared two independently-generated timezone.now() values (expires_at
    vs. auto_now_add started_at) instead of the requested duration against
    the actual cap."""
    output = run("log_capture", "start", "--level", "DEBUG", "--minutes", "5")
    assert "clamped" not in output


@override_settings(TELEMETRY_MAX_CAPTURE_MINUTES=30)
def test_log_capture_start_reports_clamping_when_it_actually_happened():
    output = run("log_capture", "start", "--minutes", "10000")
    assert "clamped" in output
    assert capture.active_window().expires_at is not None


def test_log_capture_stop_closes_the_window():
    capture.start(minutes=15)

    output = run("log_capture", "stop")

    assert capture.active_window() is None
    assert "Closed 1 capture window" in output


def test_log_capture_stop_is_safe_when_nothing_is_open():
    assert "No open capture window" in run("log_capture", "stop")


def test_log_capture_status_reports_the_baseline_when_closed():
    make_rows(4)
    output = run("log_capture", "status")

    assert "No capture window" in output
    assert "Stored records: 4" in output


def test_log_capture_status_reports_an_open_window():
    capture.start(level="INFO", minutes=20, actor="admin", note="why")
    output = run("log_capture", "status")

    assert "Capture window OPEN: INFO" in output
    assert "admin" in output


def test_log_capture_status_prints_the_handler_in_words():
    """Not a Python dict, and not a baseline level that reads as "capture is
    off" while a window is open (Test Lab LOG-4)."""
    handler = DatabaseLogHandler(level="WARNING", start_worker=False)
    try:
        capture.start(level="DEBUG", minutes=5, actor="admin", note="why")
        output = run("log_capture", "status")
    finally:
        handler.close()
    assert "{'level'" not in output
    assert "This process's handler: level WARNING (this command's own process" in output
