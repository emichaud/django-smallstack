from django.apps import AppConfig


class WebsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.website"
    verbose_name = "Website"

    def ready(self) -> None:
        # This project's dashboard card types (see dashboard_cards.py). Delete
        # the line to ship SmallStack's stat and roll-up cards only.
        from . import dashboard_cards

        dashboard_cards.register()
