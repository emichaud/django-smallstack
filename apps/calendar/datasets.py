"""Bundled datasets for the calendar app: saved views, and the Events calendar
(a dataset for reporting AND a provider-backed calendar under the same key)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Iterator

from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from apps.datasets.framework import framework_dataset

from .core import CalendarEvent
from .models import Event, SavedCalendarView
from .registry import register_calendar


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


EVENTS_KEY = "smallstack_events"


def visible_events(user: Any, qs: QuerySet[Event] | None = None) -> QuerySet[Event]:
    """Entries ``user`` may see: everyone's *members* entries plus their own
    *private* ones; staff see all; anonymous sees none."""
    qs = Event.objects.all() if qs is None else qs
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()
    if getattr(user, "is_staff", False):
        return qs
    return qs.filter(Q(visibility=Event.Visibility.MEMBERS) | Q(created_by=user))


@framework_dataset(
    EVENTS_KEY,
    label="Events",
    description="Hand-entered calendar entries: title, dates and times, category, visibility, who added them.",
    columns=[
        "title",
        "category",
        "start_date",
        "end_date",
        "all_day",
        "start_time",
        "end_time",
        "location",
        "cancelled",
        "visibility",
        "created_by",
        "created_at",
    ],
    filterable=["category", "start_date", "end_date", "all_day", "cancelled", "visibility", "created_by"],
)
def events(request: HttpRequest | None = None) -> QuerySet[Event]:
    return visible_events(getattr(request, "user", None)).select_related("created_by")


def _at(day: date, clock: time | None) -> date | datetime:
    if clock is None:
        return day
    return timezone.make_aware(datetime.combine(day, clock), timezone.get_current_timezone())


def events_provider(lower: date, upper: date, request: HttpRequest | None) -> Iterator[CalendarEvent]:
    """The Events calendar: stored rows as events, timed when they carry a
    time. A provider rather than the column protocol because a date column
    plus optional time columns is two shapes in one table."""
    qs = visible_events(getattr(request, "user", None)).filter(start_date__lt=upper)
    qs = qs.filter(Q(end_date__isnull=True, start_date__gte=lower) | Q(end_date__gte=lower))
    for row in qs.select_related("created_by").order_by("start_date", "start_time", "title"):
        timed = not row.all_day and row.start_time is not None
        start = _at(row.start_date, row.start_time if timed else None)
        end_day = row.end_date or row.start_date
        end = _at(end_day, row.end_time if timed and row.end_time else None) if (row.end_date or timed) else None
        subtitle = " · ".join(p for p in (row.category, row.location) if p)
        yield CalendarEvent.make(
            EVENTS_KEY,
            row.pk,
            row.title,
            start,
            end,
            subtitle=subtitle,
            url=row.get_absolute_url(),
            cancelled=row.cancelled,
        )


register_calendar(
    EVENTS_KEY,
    provider=events_provider,
    label="Events",
    description="Entries people add by hand — closures, releases, conferences. Everyone signed in can add one.",
    access="authenticated",
    spans=True,
)

