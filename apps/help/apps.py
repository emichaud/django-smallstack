"""Help app configuration."""

from django.apps import AppConfig


class HelpConfig(AppConfig):
    """Configuration for the help app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.help"
    verbose_name = "Help & Documentation"

    def ready(self):
        from django.conf import settings

        from apps.smallstack.navigation import nav

        nav.register(
            section="main",
            label="Components",
            url_name="help:section_index",
            url_kwargs={"section": "components"},
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z"/></svg>',  # noqa: E501
            auth_required=True,
            order=30,
        )
        nav.register(
            section="resources",
            label="Help & Docs",
            url_name="help:index",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z"/></svg>',  # noqa: E501
            order=50,
        )
        if getattr(settings, "SMALLSTACK_DOCS_ENABLED", True):
            nav.register(
                section="resources",
                label="SmallStack",
                url_name="help:section_index",
                url_kwargs={"section": "smallstack"},
                icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-1 9H9V9h10v2zm-4 4H9v-2h6v2zm4-8H9V5h10v2z"/></svg>',  # noqa: E501
                order=55,
            )
