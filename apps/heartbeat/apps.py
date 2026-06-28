"""Heartbeat app configuration."""

from django.apps import AppConfig


class HeartbeatConfig(AppConfig):
    """Configuration for the heartbeat/uptime monitoring app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.heartbeat"
    verbose_name = "Heartbeat Monitoring"

    def ready(self) -> None:
        from django.conf import settings

        from apps.smallstack.navigation import nav

        nav.register(
            section="admin",
            label="Status",
            url_name="heartbeat:status_overview",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M3.5 18.49l6-6.01 4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z"/></svg>',  # noqa: E501
            staff_required=True,
            order=20,
            # Highlight "Status" for every page under /smallstack/status/ (overview,
            # per-monitor detail, dashboard, sla), not just the overview URL itself.
            active_prefix="/smallstack/status/",
        )

        # TEMPORARY dev hub indexing every status page. Shown under DEBUG (or when
        # SMALLSTACK_STATUS_DEV_LINKS is forced on); auto-hidden in production.
        if settings.DEBUG or getattr(settings, "SMALLSTACK_STATUS_DEV_LINKS", False):
            nav.register(
                section="admin",
                label="Status Links (dev)",
                url_name="heartbeat:dev_links",
                icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M3 5h18v2H3V5zm0 6h18v2H3v-2zm0 6h18v2H3v-2z"/></svg>',  # noqa: E501
                staff_required=True,
                order=21,
            )

        # Register the built-in "site" service + database-connectivity monitor
        # with the pluggable status framework. Best-effort, like dashboard/nav.
        try:
            from apps.smallstack import monitors, visualizations

            from .monitors import (
                CustomService,
                InternalService,
                SiteMonitor,
                SiteService,
                endpoint_monitor_source,
                surface_monitor_source,
            )
            from .visualizations import TimelineVisualization, UptimeStatsVisualization

            monitors.register_service(SiteService())
            monitors.register_service(InternalService())  # Site Monitors tier
            monitors.register_service(CustomService())  # External Monitors tier
            monitors.register_monitor(SiteMonitor())
            # User-created endpoints become live monitors (DB-backed source).
            monitors.register_monitor_source(endpoint_monitor_source)
            # User-picked exposed surfaces (API resources / MCP tools) too.
            monitors.register_monitor_source(surface_monitor_source)
            visualizations.register(UptimeStatsVisualization())
            visualizations.register(TimelineVisualization())
        except Exception:  # noqa: BLE001 — never block app startup on registration
            import logging

            logging.getLogger(__name__).exception("Failed to register heartbeat monitors")
