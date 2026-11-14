"""Token Manager — user-facing UI for APIToken self-service.

The APIToken model lives in apps.smallstack. This app adds the views,
URLs, templates, sidebar entry, and dashboard widget. Self-service
permissions:

- Any authenticated user can list / view / revoke their OWN tokens
  and mint a new readonly token for themselves.
- Staff can see all tokens, mint any access level, mint for any user.

The MCP consent page deep-links here so OAuth-minted tokens have a
visible management surface for the granting user.
"""

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class TokenmgrConfig(AppConfig):
    name = "apps.tokenmgr"
    label = "tokenmgr"
    verbose_name = "API Tokens"

    def ready(self):
        # Sidebar entry — login-required, NOT staff-only, since regular
        # users manage their own tokens here.
        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="admin",
                label="API Tokens",
                url_name="tokenmgr:tokens-list",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M12.65 10A6 6 0 0 0 7 6a6 6 0 0 0 0 12 6 6 0 0 0 5.65-4H17v4h4v-4h2v-4H12.65zM7 14a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"/>'  # noqa: E501
                    "</svg>"
                ),
                auth_required=True,
                order=45,  # after MCP (35), Backups (40)
            )
        except Exception:
            logger.exception("Failed to register tokenmgr sidebar entry")

        # Dashboard widget on /smallstack/ — at-a-glance token count.
        try:
            from apps.smallstack import dashboard

            from .dashboard_widgets import TokensDashboardWidget

            dashboard.register(TokensDashboardWidget())
        except Exception:
            logger.exception("Failed to register tokenmgr dashboard widget")
