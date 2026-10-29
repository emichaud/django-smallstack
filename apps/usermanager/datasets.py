"""Bundled dataset for user management: the user directory (no credentials)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Model, QuerySet

from apps.calendar import register_calendar
from apps.datasets.framework import framework_dataset


@framework_dataset(
    "smallstack_users",
    label="Users",
    description=(
        "The user directory: identity, staff/superuser flags, activity state, join and last-login dates. "
        "No credential fields."
    ),
    columns=[
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
        "last_login",
    ],
    filterable=["username", "email", "is_staff", "is_superuser", "is_active", "date_joined", "last_login"],
)
def users() -> QuerySet[Model]:
    return get_user_model()._default_manager.all()


# ---------------------------------------------------------------------------
# Calendar protocol
# ---------------------------------------------------------------------------

register_calendar(
    "smallstack_users",
    start="date_joined",
    title="username",
    subtitle="email",
    label="User sign-ups",
    description="Each account on the day it joined.",
)
