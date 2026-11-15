from django.apps import AppConfig


class UsermanagerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.usermanager"
    label = "usermanager"

    def ready(self):
        from apps.smallstack.navigation import nav

        nav.register(
            section="admin",
            label="Users",
            url_name="manage/users-list",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>',  # noqa: E501
            staff_required=True,
            # The list needs accounts.view_user; hide a link that would 403.
            visible=lambda request: request.user.has_perm("accounts.view_user"),
            order=40,
        )
        # The Timezones dashboard is a team tool open to every staff account
        # (names and time zones, no access state), so it has its own entry:
        # plain staff don't see Users (E-dec 3).
        nav.register(
            section="admin",
            label="Timezones",
            url_name="manage/users-timezones",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67V7z"/></svg>',  # noqa: E501
            staff_required=True,
        )
