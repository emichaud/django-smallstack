"""Bundled dataset for notifications: the in-app inbox across all recipients."""

from __future__ import annotations

from typing import Optional

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import Notification


def _subject_link(notification: Notification) -> Optional[str]:
    """Where the notification points — not the recipient's open/mark-read
    route, which is theirs alone and has a side effect. Same rule as that
    route: only a local path is followed, never an external URL."""
    url = notification.url or ""
    return url if url.startswith("/") and not url.startswith("//") else None


@framework_dataset(
    "smallstack_notifications",
    label="Notifications",
    description=(
        "Every in-app notification: recipient, actor, kind, subject, title, when it was created and when it was read."
    ),
    columns=["created_at", "recipient", "actor", "kind", "subject_key", "title", "read_at"],
    filterable=["created_at", "recipient", "actor", "kind", "subject_key", "read_at"],
    link=_subject_link,
)
def notifications() -> QuerySet[Notification]:
    return Notification.objects.select_related("recipient", "actor")
