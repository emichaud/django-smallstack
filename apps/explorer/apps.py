"""Explorer app configuration."""

from django.apps import AppConfig


class ExplorerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.explorer"
    verbose_name = "Model Explorer"
    help_content_dir = "content"
    help_section_slug = "explorer"
    help_section_title = "Explorer"

    def ready(self):
        from apps.smallstack.navigation import nav

        from .registry import explorer_registry

        explorer_registry.discover()
        explorer_registry.build()

        nav.register(
            section="admin",
            label="Explorer",
            url_name="explorer-index",
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20"'
                ' fill="currentColor"><path d="M12 2C6.48 2 2 6.48'
                " 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1"
                " 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9"
                " 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9"
                "-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1"
                ' 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97'
                '-2.1 5.39z"/></svg>'
            ),
            staff_required=True,
            order=20,
        )
