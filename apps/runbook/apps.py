"""Runbook app configuration."""

from django.apps import AppConfig


class RunbookConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.runbook"
    # Keep the historical label so existing migrations (which reference
    # "smallstack_runbook.<model>") and any downstream tables still resolve.
    label = "smallstack_runbook"
    verbose_name = "Runbook"
    help_content_dir = "content"
    help_section_slug = "runbook"

    def ready(self) -> None:
        # Connect built-in domain-event consumers (e.g. retention pruning).
        from . import receivers  # noqa: F401

        # Register Document with the SmallStack search engine (FTS + MCP), if
        # present. Independent of nav so it still runs when nav is unavailable.
        from .search import register_document

        register_document()

        try:
            from apps.smallstack.navigation import nav
        except ImportError:
            return

        icon = (
            '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
            '<path d="M6 2a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6H6z'
            "m7 1.5L18.5 9H13V3.5zM8 12h8v2H8v-2zm0 4h8v2H8v-2z"
            '"/></svg>'
        )
        nav.register(
            section="main",
            label="Runbook",
            url_name="runbook:dashboard",
            icon_svg=icon,
            auth_required=True,
            order=5,
        )
