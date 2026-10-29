"""Bundled datasets for the framework core: API tokens and backups.

Read-only reporting views; see ``apps/datasets/framework.py`` for the
conventions (namespaced keys, explicit column allow-lists, exposure settings).
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.calendar import register_calendar
from apps.datasets.framework import framework_dataset

from .models import APIToken, BackupRecord


@framework_dataset(
    "smallstack_api_tokens",
    label="API tokens",
    description=(
        "Every API token: owner, type, access level, activity and lifecycle dates. The key hash is never included."
    ),
    columns=[
        "name",
        "prefix",
        "token_type",
        "access_level",
        "user",
        "is_active",
        "request_count",
        "created_at",
        "last_used_at",
        "expires_at",
        "revoked_at",
    ],
    filterable=["token_type", "access_level", "user", "is_active", "created_at", "last_used_at", "expires_at"],
)
def api_tokens() -> QuerySet[APIToken]:
    return APIToken.objects.select_related("user")


@framework_dataset(
    "smallstack_backups",
    label="Backups",
    description="Database backup runs: file, size, duration, outcome and what triggered them.",
    columns=["created_at", "filename", "file_size", "duration_ms", "status", "triggered_by", "pruned_at"],
    filterable=["status", "triggered_by", "created_at", "pruned_at"],
)
def backups() -> QuerySet[BackupRecord]:
    return BackupRecord.objects.all()


# ---------------------------------------------------------------------------
# Calendar protocol
# ---------------------------------------------------------------------------


def _token_expiry_status(token: APIToken) -> str | None:
    """Expired → danger, expiring within two weeks → warning, else plain.
    A revoked token's expiry is moot."""
    from datetime import timedelta

    from django.utils import timezone

    if token.revoked_at or not token.expires_at:
        return None
    now = timezone.now()
    if token.expires_at <= now:
        return "danger"
    if token.expires_at <= now + timedelta(days=14):
        return "warning"
    return None


register_calendar(
    "smallstack_api_tokens",
    start="expires_at",
    title="name",
    subtitle=lambda t: getattr(t.user, "username", ""),
    status=_token_expiry_status,
    label="API token expiry",
    description="When each API token expires — amber inside two weeks, red once past.",
)

register_calendar(
    "smallstack_backups",
    start="created_at",
    title=lambda b: b.filename or "Backup failed",
    subtitle="triggered_by",
    status=lambda b: {"success": "success", "failed": "danger"}.get(b.status),
    label="Backups",
    description="Database backup runs on the day they were taken, tinted by outcome.",
)
