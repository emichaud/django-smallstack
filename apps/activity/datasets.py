"""Bundled dataset for activity: the request log."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import RequestLog


@framework_dataset(
    "smallstack_requests",
    label="Requests",
    description=(
        "One row per logged HTTP request: path, matched route, method, status, latency, who made it and from where."
    ),
    columns=[
        "timestamp",
        "method",
        "path",
        "route",
        "status_code",
        "response_time_ms",
        "user",
        "api_token",
        "ip_address",
        "request_id",
    ],
    filterable=["timestamp", "method", "path", "route", "status_code", "user", "api_token", "ip_address", "request_id"],
)
def requests() -> QuerySet[RequestLog]:
    return RequestLog.objects.select_related("user", "api_token")
