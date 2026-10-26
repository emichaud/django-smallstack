"""Bundled datasets for telemetry: captured log records and capture windows."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from django.db.models import QuerySet
from django.urls import reverse

from apps.datasets.framework import framework_dataset

from .models import LogCaptureWindow, LogRecord


def _log_record_link(record: LogRecord) -> Optional[str]:
    """The logs page showing this record's request (or trace) — the detail
    route is an HTMX partial, not a page of its own."""
    if record.request_id:
        return reverse("telemetry:logs") + "?" + urlencode({"request_id": record.request_id})
    if record.trace_id:
        return reverse("telemetry:logs") + "?" + urlencode({"trace_id": record.trace_id})
    return None


def _logs_page(_window: LogCaptureWindow) -> str:
    return reverse("telemetry:logs")


@framework_dataset(
    "smallstack_log_records",
    label="Log records",
    description=(
        "Captured log lines: time, level, logger, message, source location and the request/trace ids they "
        "belong to. Exception tracebacks and extra payloads are left out."
    ),
    columns=[
        "ts",
        "level",
        "level_no",
        "logger",
        "message",
        "module",
        "func",
        "line",
        "request_id",
        "trace_id",
        "exc_type",
    ],
    filterable=["ts", "level", "logger", "module", "request_id", "trace_id", "exc_type"],
    link=_log_record_link,
)
def log_records() -> QuerySet[LogRecord]:
    return LogRecord.objects.all()


@framework_dataset(
    "smallstack_log_capture_windows",
    label="Log capture windows",
    description="Time-boxed capture windows: the level captured, who opened it, when it started and when it expires.",
    columns=["level", "started_at", "expires_at", "started_by", "note"],
    filterable=["level", "started_at", "expires_at", "started_by"],
    link=_logs_page,
)
def log_capture_windows() -> QuerySet[LogCaptureWindow]:
    return LogCaptureWindow.objects.all()
