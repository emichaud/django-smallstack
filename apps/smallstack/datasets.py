"""Bundled datasets for the framework core: API tokens and backups.

Read-only reporting views; see ``apps/datasets/framework.py`` for the
conventions (namespaced keys, explicit column allow-lists, exposure settings).
"""

from __future__ import annotations

from django.db.models import QuerySet

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
