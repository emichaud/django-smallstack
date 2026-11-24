"""Explorer registration for the custom User model."""

from datetime import timedelta

from django.utils import timezone

from apps.explorer.registry import explorer
from apps.smallstack.displays import (
    AvatarCardDisplay,
    DashboardWidget,
    TableDisplay,
)

from .admin import UserAdmin
from .models import User


class UsersDashboardWidget(DashboardWidget):
    title = "Users"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34'
        "-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 "
        "6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67"
        "-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19"
        'h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>'
    )
    order = 30
    url_name = "manage/users-list"

    def visible_to(self, user):
        """Account counts are account data: the User Manager it links to needs
        ``accounts.view_user`` too (eval 45 T5-9)."""
        return bool(getattr(user, "is_active", False) and user.has_perm("accounts.view_user"))

    def get_data(self, model_class=None):
        cls = model_class or User
        active_count = cls.objects.filter(is_active=True).count()
        thirty_days_ago = timezone.now() - timedelta(days=30)
        new_count = cls.objects.filter(date_joined__gte=thirty_days_ago).count()
        return {"headline": f"{active_count} active", "detail": f"{new_count} new (30d)"}


setattr(UserAdmin, "explorer_list_fields", ("username", "email", "is_staff", "is_active"))
setattr(
    UserAdmin,
    "explorer_column_widths",
    {
        "username": "20%",
        "email": "50%",
        "is_staff": "15%",
        "is_active": "15%",
    },
)
setattr(UserAdmin, "explorer_dashboard_widgets", [UsersDashboardWidget()])
setattr(
    UserAdmin,
    "explorer_displays",
    [
        TableDisplay,
        AvatarCardDisplay(
            title_field="username",
            subtitle_field="email",
            show_avatar=True,  # no photo on User — initials only
            pill_field=lambda u: u.date_joined.strftime("%Y") if u.date_joined else None,
            pill_label="joined",
        ),
    ],
)

explorer.register(User, UserAdmin, group="Accounts")
