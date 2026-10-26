"""AppConfig for the datasets module.

Thin registration layer (like apps.search / apps.mcp). Datasets self-register
when their app's ``datasets.py`` is autodiscovered by SmallStackConfig.ready()
(which runs first, in framework core). Here we register the opt-in MCP tools;
the REST surface is wired in urls.py.
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger("smallstack.datasets")


class DatasetsConfig(AppConfig):
    name = "apps.datasets"
    # Namespaced label (like apps.runbook's "smallstack_runbook") so a downstream
    # app labelled "datasets" — a common BI noun — can't collide in INSTALLED_APPS.
    # Safe to set now: this app has no models/migrations, so there's no downstream
    # migration-history rename. Do NOT revert to plain "datasets".
    label = "smallstack_datasets"
    verbose_name = "Datasets"

    def ready(self) -> None:
        from django.conf import settings

        if not getattr(settings, "SMALLSTACK_DATASETS_ENABLED", True):
            return

        from apps.smallstack.navigation import nav

        nav.register(
            section="admin",
            label="Datasets",
            url_name="datasets:browse-index",
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">'
                '<path d="M3 4h18v4H3zm0 6h18v4H3zm0 6h18v4H3z"/></svg>'
            ),
            staff_required=True,
            active_prefix="/smallstack/datasets/browse/",
        )

        # Register MCP tools for every opted-in dataset. No-op if apps.mcp isn't
        # installed, and skipped entirely when MCP is off site-wide.
        if getattr(settings, "SMALLSTACK_MCP_ENABLED", True):
            try:
                from .mcp_tools import register_dataset_tools

                register_dataset_tools()
            except Exception:
                logger.exception("Failed to register dataset MCP tools")
