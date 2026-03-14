from django.apps import AppConfig


class WebsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.website"
    verbose_name = "Website"

    def ready(self):
        from apps.smallstack.navigation import nav

        nav.register(
            section="main",
            label="Home",
            url_name="website:home",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>',  # noqa: E501
            order=0,
        )
        nav.register(
            section="main",
            label="Getting Started",
            url_name="website:getting_started",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M13 9H9v2h4V9zm-2 4H9v2h2v-2zm4-4h-2v2h2V9zM9 3v2h6V3H9zm10 4V5l-2-2H7L5 5v2H3v14h18V7h-2zm0 12H5V7h2v2h10V7h2v12z"/></svg>',  # noqa: E501
            order=10,
        )
