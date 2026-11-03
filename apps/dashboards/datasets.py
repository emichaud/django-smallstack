"""The dataset behind hand-entered metrics.

A manual metric is an ordinary metric over this dataset, filtered to its own
entries, so cards, reports, goals, trends and the rows modal need nothing special.
Not a bundled ``framework_dataset``: the setting that hides those mustn't take
people's own numbers with it. Readable by anyone signed in because the rows are
scoped here: you see the entries of the metrics you can see.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest

from apps.datasets.registry import dataset

from .models import MANUAL_DATASET, Metric, MetricEntry


def visible_entries(user: Any) -> QuerySet[MetricEntry]:
    if user is None or not getattr(user, "is_authenticated", False):
        return MetricEntry.objects.none()
    return MetricEntry.objects.filter(metric__in=Metric.objects.visible_to(user))


@dataset(
    MANUAL_DATASET,
    label="Values entered by hand",
    description="The values people type into hand-entered metrics: the date, the value, a note and who entered it.",
    columns=["date", "value", "note", "entered_by", "metric"],
    filterable=["metric", "date", "entered_by"],
    access="auth",
    link=False,
)
def metric_entries(request: HttpRequest | None = None) -> QuerySet[MetricEntry]:
    return visible_entries(getattr(request, "user", None)).select_related("entered_by", "metric")
