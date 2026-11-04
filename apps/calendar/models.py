"""Saved calendar views, and the one calendar a person can type into."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

from .recurrence import REPEAT_CHOICES, SHORTEST_GAP, WEEKDAYS, describe, is_occurrence


class SavedCalendarView(models.Model):
    """Which calendars a user wants on the grid together, under a name.

    ``datasets`` is an ordered list of calendar dataset keys. Keys that stop
    existing (a dataset removed, the bundled set switched off) are skipped at
    render time rather than breaking the view. One view per owner may be the
    default — the one ``/smallstack/calendar/`` opens with no parameters.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="calendar_views",
    )
    name = models.CharField(max_length=120)
    datasets = models.JSONField(
        default=list,
        blank=True,
        help_text="The calendar datasets shown together in this view.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Open this view when the calendar page is visited with no view selected.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "calendar view"
        verbose_name_plural = "calendar views"
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="calendar_view_owner_name_uniq"),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        super().save(*args, **kwargs)
        if self.is_default:
            # One default per owner. Cleared after the save so a fresh row's pk
            # is known and excluded.
            SavedCalendarView.objects.filter(owner_id=self.owner_id, is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )

    @property
    def keys(self) -> list[str]:
        """The stored keys as a clean list of strings (the JSON column is
        untyped; a hand-edited value must not crash the page)."""
        raw = self.datasets if isinstance(self.datasets, list) else []
        return [str(k) for k in raw if isinstance(k, str) and k]

    def get_absolute_url(self) -> str:
        return reverse("calendar_index") + f"?view={self.pk}"


class Event(models.Model):
    """A hand-entered calendar entry — the "Events" calendar.

    Every other bundled calendar is derived from data the system already
    holds; this is the one a person types into: a closure, a conference, an
    onboarding week, a release. All-day by default because most of what an
    organisation keeps on a calendar is a day rather than a meeting; times are
    optional and additive. ``end_date`` is the last day **inclusive**.

    ``visibility`` is the blog's ladder, minus public: *members* (every
    signed-in user) is the default because an org calendar is for the org;
    *private* keeps an entry to its author and staff. A cancelled entry stays
    on the calendar struck through — a cancelled window is still information.
    """

    class Visibility(models.TextChoices):
        MEMBERS = "members", "Everyone signed in"
        PRIVATE = "private", "Only me (and staff)"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text="Optional grouping — 'Closure', 'Release', 'Patching'. Shown with the entry.",
    )
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(
        null=True, blank=True, help_text="Last day, inclusive, for a multi-day entry. Blank means one day."
    )
    all_day = models.BooleanField(default=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    repeat = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=REPEAT_CHOICES,
        help_text="Blank means it happens once. The first day and times set the pattern.",
    )
    repeat_until = models.DateField(
        null=True, blank=True, help_text="The last date it may happen. Blank means no end."
    )
    skip_dates = models.JSONField(
        default=list, blank=True, help_text="Dates this series doesn't happen, as YYYY-MM-DD."
    )
    location = models.CharField(max_length=200, blank=True, default="")
    url = models.URLField(max_length=500, blank=True, default="", help_text="A page with more about it.")
    cancelled = models.BooleanField(
        default=False, help_text="Keep it on the calendar, struck through — the fact it was planned still matters."
    )
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.MEMBERS, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="calendar_events"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_date", "start_time", "title"]
        verbose_name = "event"
        verbose_name_plural = "events"
        indexes = [models.Index(fields=["start_date", "end_date"])]

    def __str__(self) -> str:
        return f"{self.title} ({self.start_date:%Y-%m-%d})"

    def clean(self) -> None:
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date cannot be before the start date."})
        if not self.all_day and not self.start_time:
            raise ValidationError({"start_time": "A timed entry needs a start time (or tick All day)."})
        if self.start_time and self.end_time and self.end_time < self.start_time and not self.end_date:
            raise ValidationError({"end_time": "The end time cannot be before the start time."})
        if not self.repeat:
            self.repeat_until = None
            self.skip_dates = []
            return
        if self.repeat_until and self.repeat_until < self.start_date:
            raise ValidationError({"repeat_until": "The last repeat cannot be before the first day."})
        if self.end_date and (self.end_date - self.start_date).days >= SHORTEST_GAP[self.repeat]:
            raise ValidationError(
                {
                    "end_date": (
                        "On a repeating event, the last day is how long each one lasts, so each would run into "
                        "the next. Use Until to say when the series ends."
                    )
                }
            )
        if self.repeat == WEEKDAYS and self.start_date.weekday() >= 5:
            raise ValidationError({"start_date": "A weekday series has to start on a weekday."})
        # Moving or shortening a series can leave a skip on a date it no longer has.
        self.skip_dates = [d for d in self.skip_dates or [] if self._has_date(date.fromisoformat(d))]

    def _has_date(self, day: date) -> bool:
        return is_occurrence(self, day, ignore_skips=True)

    @property
    def last_day(self) -> Any:
        return self.end_date or self.start_date

    @property
    def span_days(self) -> int:
        return (self.end_date - self.start_date).days if self.end_date else 0

    @property
    def skipped(self) -> frozenset[date]:
        return frozenset(date.fromisoformat(d) for d in self.skip_dates or [])

    @property
    def skipped_dates(self) -> list[date]:
        return sorted(self.skipped)

    @property
    def repeat_summary(self) -> str:
        """The rule in words, "" for a one-off."""
        return describe(self) if self.repeat else ""

    def is_over(self, today: date) -> bool:
        """Whether its last occurrence has passed. A series with no end never is."""
        if not self.repeat:
            return bool(self.last_day < today)
        return self.repeat_until is not None and self.repeat_until < today

    def set_skipped(self, day: date, skipped: bool) -> None:
        """Take one date out of the series, or put it back."""
        dates = set(self.skipped)
        dates.add(day) if skipped else dates.discard(day)
        self.skip_dates = sorted(d.isoformat() for d in dates)
        self.save(update_fields=["skip_dates", "updated_at"])

    def get_absolute_url(self) -> str:
        return reverse("calendar/events-detail", kwargs={"pk": self.pk})

