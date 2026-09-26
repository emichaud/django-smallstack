"""The Notification model — one row per recipient per event.

Deliberately small: a notification is a pointer ("something happened, look
here"), not a message store. `read_at IS NULL` is the unread flag; there is no
separate boolean to drift out of sync with the timestamp.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    # Who caused it (shown as "requested by X"); nullable so system events work
    # and user deletion doesn't cascade into recipients' history.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications_caused",
    )
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default="")
    # Internal path to the thing ("/smallstack/approvals/requests/4/").
    # Click-through routes via the mark-read redirect view.
    url = models.CharField(max_length=300, blank=True, default="")
    # Producer-namespaced category, e.g. "approvals.requested" — filtering and
    # future per-kind preferences hang off this string.
    kind = models.CharField(max_length=100, blank=True, default="", db_index=True)
    # The thing this row is *about*, as a producer-owned opaque string (e.g.
    # "approvals.request:42"). notify() is otherwise fire-and-forget: a producer
    # got no handle back, so nothing could ever retire its own rows when they
    # stopped being actionable — every approver's bell over-counted forever once
    # one of them decided (F-13). Blank ⇒ the row is not addressable.
    subject_key = models.CharField(max_length=200, blank=True, default="", db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at"], name="notif_recipient_unread"),
            models.Index(fields=["recipient", "created_at"], name="notif_recipient_created"),
            models.Index(fields=["subject_key", "read_at"], name="notif_subject_unread"),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_read(self) -> bool:
        return self.read_at is not None
