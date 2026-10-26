"""Bundled dataset for profiles: theme/palette/timezone preferences per user."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import UserProfile


@framework_dataset(
    "smallstack_user_profiles",
    label="User profiles",
    description=(
        "One row per user profile: theme, palette and timezone preferences plus when the profile was "
        "created and last changed."
    ),
    columns=[
        "user",
        "display_name",
        "theme_preference",
        "color_palette",
        "timezone",
        "location",
        "created_at",
        "updated_at",
    ],
    filterable=["user", "theme_preference", "color_palette", "timezone", "created_at", "updated_at"],
)
def user_profiles() -> QuerySet[UserProfile]:
    return UserProfile.objects.select_related("user")
