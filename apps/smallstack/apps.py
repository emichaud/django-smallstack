"""SmallStack core app configuration."""

from django.apps import AppConfig


class SmallStackConfig(AppConfig):
    """Configuration for the SmallStack core app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.smallstack"
    verbose_name = "SmallStack"
    help_content_dir = "docs"
    help_section_slug = "smallstack"
    help_section_title = "SmallStack Reference"

    def ready(self):
        from apps.smallstack import dashboard
        from apps.smallstack.dashboard_widgets import (
            BackupsDashboardWidget,
            HelpDashboardWidget,
        )
        from apps.smallstack.navigation import nav

        dashboard.register(BackupsDashboardWidget())
        dashboard.register(HelpDashboardWidget())

        nav.register(
            section="admin",
            label="Dashboard",
            url_name="smallstack_dashboard",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/></svg>',  # noqa: E501
            staff_required=True,
            order=0,
        )
        nav.register(
            section="admin",
            label="Backups",
            url_name="smallstack:backups",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>',  # noqa: E501
            staff_required=True,
            order=30,
        )
