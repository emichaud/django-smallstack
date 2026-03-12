"""Profile app configuration."""

from django.apps import AppConfig


class ProfileConfig(AppConfig):
    """Configuration for the profile app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.profile"
    verbose_name = "User Profiles"

    def ready(self):
        # Import signals to register them
        from apps.smallstack.navigation import nav

        from . import signals  # noqa: F401

        nav.register(
            section="main",
            label="Profile",
            url_name="profile",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>',  # noqa: E501
            auth_required=True,
            order=10,
        )
