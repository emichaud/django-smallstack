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

        nav.register(
            section="admin",
            label="Group Page Example",
            url_name="explorer-example-group",
            url_kwargs={"group": "Monitoring"},
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20"'
                ' fill="currentColor"><path d="M4 6H2v14c0 1.1.9 2 2'
                " 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2"
                " 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H8V4h12v12z"
                '"/></svg>'
            ),
            staff_required=True,
            order=21,
        )

        nav.register(
            section="admin",
            label="App Page Example",
            url_name="explorer-example-app",
            url_kwargs={"app_label": "heartbeat"},
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20"'
                ' fill="currentColor"><path d="M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6'
                " 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6"
                ' 0v4h4V4h-4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z"/></svg>'
            ),
            staff_required=True,
            order=23,
        )

        nav.register(
            section="admin",
            label="Model Page Example",
            url_name="explorer-example-model",
            url_kwargs={"app_label": "heartbeat", "model_name": "heartbeat"},
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20"'
                ' fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2'
                " 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2"
                "-2zm0 16H5V5h14v14zM7 10h2v7H7zm4-3h2v10h-2zm4 6h2v4h"
                '-2z"/></svg>'
            ),
            staff_required=True,
            order=24,
        )

        nav.register(
            section="admin",
            label="Heartbeat Compose",
            url_name="explorer-example-heartbeat",
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20"'
                ' fill="currentColor"><path d="M3.5 18.49l6-6.01 4'
                " 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z"
                '"/></svg>'
            ),
            staff_required=True,
            order=25,
        )
