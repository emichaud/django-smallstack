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
    help_slides_dir = "docs/slides"

    def ready(self):
        # Import every app's views.py so CRUDView subclasses register into
        # CRUDView._registry (Django auto-imports models/admin, never views). The
        # framework core loads before every consumer, so doing this here — and
        # unconditionally — keeps the registry populated regardless of feature
        # toggles. (It used to ride on the MCP app's autodiscover, which coupled
        # Search to SMALLSTACK_MCP_ENABLED.)
        from apps.smallstack.autodiscover import autodiscover_app_modules

        # views.py → CRUDView subclasses; datasets.py → @dataset providers.
        # Both must be imported so their decorators/subclasses self-register.
        autodiscover_app_modules(("views", "datasets"))

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
            # /smallstack/ prefixes every admin route, so without this any page
            # lacking its own nav entry lights up Dashboard. (T3.)
            active_exact=True,
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
