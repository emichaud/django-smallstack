"""SmallStack feeds — RSS/Atom as a publishing surface, plus a collector.

Publish: subclass :class:`Feed` over your own scoped queryset and
``register_feed(MyFeed())`` (served at ``/feed/<slug>.rss`` and ``.atom``); a
feed per runtime object renders through :func:`apps.feeds.render.render_feed`
from your own view. The blog and the status page are the worked examples.
Consume: ``register_feed_source(name, url, …)`` + the collector (a ``@scheduled``
job and ``manage.py collect_feeds``) upserts items into a model.

See docs/skills/rss.md.
"""

from .base import Feed, FeedItem
from .registry import register_feed
from .sources import register_feed_source

__all__ = ["Feed", "FeedItem", "register_feed", "register_feed_source"]
