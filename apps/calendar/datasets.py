"""Bundled dataset for the calendar app: the saved views users have made."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import SavedCalendarView


@framework_dataset(
    "smallstack_calendar_views",
    label="Calendar views",
    description=(
        "Every saved calendar view: owner, name, which calendars it shows and whether it is that user's default."
    ),
    columns=["owner", "name", "datasets", "is_default", "created_at", "updated_at"],
    filterable=["owner", "is_default", "created_at", "updated_at"],
)
def calendar_views() -> QuerySet[SavedCalendarView]:
    return SavedCalendarView.objects.select_related("owner")
