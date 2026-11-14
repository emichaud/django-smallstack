from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class FeedsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.feeds"
    verbose_name = "RSS Feeds"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_FEEDS_ENABLED", True):
            return

        # Let any app declare consumed sources in a `feed_sources.py` module
        # (pure imports — no DB). Model feeds resolve lazily at request time, so
        # nothing to register here for publishing. The @scheduled collector in
        # our own tasks.py is picked up by the scheduler's autodiscovery.
        try:
            from apps.smallstack.autodiscover import autodiscover_app_modules

            autodiscover_app_modules(("feed_sources",))
        except Exception:
            logger.warning("feeds: feed_sources autodiscovery failed", exc_info=True)
