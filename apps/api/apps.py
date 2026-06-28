"""AppConfig for the API admin module.

A thin observation layer over the REST surface that lives in
``apps.smallstack.api``. This app owns ``/smallstack/api/`` (Health +
Activity admin pages), the ``api_doctor`` management command, and the
dashboard widget — but the API runtime itself stays in ``apps.smallstack``.
"""

import logging

from django.apps import AppConfig

logger = logging.getLogger("smallstack.api_admin")


class APIAdminConfig(AppConfig):
    name = "apps.api"
    label = "api_admin_app"
    verbose_name = "API Admin"

    def ready(self):
        from django.conf import settings

        # Honor the site-wide API switch: with the API off, don't surface the
        # "API Health" nav, dashboard widget, or status monitor (there's no API
        # to observe). The /smallstack/api/ admin pages stay registered.
        if not getattr(settings, "SMALLSTACK_API_ENABLED", True):
            return

        # Sidebar entry + dashboard widget. Both are best-effort — if the
        # widget/nav registries aren't available (smallstack not yet loaded
        # in some test bootstrap), don't crash app startup.
        try:
            from apps.smallstack import dashboard
            from apps.smallstack.navigation import nav

            from .dashboard_widgets import APIDashboardWidget

            dashboard.register(APIDashboardWidget())
            nav.register(
                section="admin",
                label="API Health",
                url_name="api_admin:health",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/>'
                    "</svg>"
                ),
                staff_required=True,
                order=37,
            )
        except Exception:
            logger.exception("Failed to register API admin widget/nav")

        # Status monitor (pluggable status framework). Best-effort.
        try:
            from apps.smallstack import monitors

            from .monitors import ApiMonitor, ApiService

            monitors.register_service(ApiService())
            monitors.register_monitor(ApiMonitor())
        except Exception:
            logger.exception("Failed to register API status monitor")
