"""Registry of published feeds, keyed by slug.

Feeds are registered eagerly via :func:`register_feed` by the app that owns
them — the status feed in ``apps.heartbeat``, the site-wide blog river in
``apps.blog``. A feed per *runtime* object (one per blog, per podcast show) is
not registered here at all: build the :class:`~apps.feeds.base.Feed` in your
own view and hand it to :func:`apps.feeds.render.render_feed`, as
``apps/blog/feeds.py`` does.

The one-flag ``enable_rss`` model feed that used to resolve lazily from
``CRUDView._registry`` was removed in 0.25.1: it published
``model.objects.all()`` with no tenancy or visibility hook. See UPGRADING.md.
"""

from __future__ import annotations

import logging

from .base import Feed

logger = logging.getLogger("smallstack.feeds")

_feeds: dict[str, Feed] = {}


def register_feed(feed: Feed) -> Feed | None:
    """Register a feed provider. First registration of a slug wins."""
    slug = getattr(feed, "slug", "")
    if not slug:
        logger.warning("Feed registration skipped — %r has no slug", feed)
        return None
    if slug in _feeds and _feeds[slug] is not feed:
        logger.warning("Feed slug %r already registered — ignoring %r", slug, feed)
        return _feeds[slug]
    _feeds[slug] = feed
    return feed


def get_feed(slug: str) -> Feed | None:
    """The registered feed for ``slug``, or ``None``."""
    return _feeds.get(slug)


def all_feeds() -> list[Feed]:
    """Every registered feed, in registration order."""
    return list(_feeds.values())


def unregister(slug: str) -> None:
    """Test helper."""
    _feeds.pop(slug, None)
