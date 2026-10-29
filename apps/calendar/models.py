"""A saved calendar view: a named selection of calendar datasets, per user."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.urls import reverse


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
