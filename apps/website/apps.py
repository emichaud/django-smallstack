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
            label="About",
            url_name="website:about",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>',  # noqa: E501
            auth_required=True,
            order=40,
        )
