"""Feed provider primitives — the shape everything published as RSS/Atom takes.

One way to publish a feed: subclass :class:`Feed`, implement :meth:`Feed.items`
over a queryset *you* scope, and ``register_feed(MyFeed())`` — or, for a feed per
runtime object, build it in your own view and call
:func:`apps.feeds.render.render_feed`. The status page (incidents plus
maintenance) and the blog (site-wide river plus per-blog feeds) are the shipped
examples. Every feed renders through :mod:`apps.feeds.render` and is gated by
the same access levels as search (:class:`apps.search.access.SearchAccess`).

The one-flag ``enable_rss`` model feed was removed in 0.25.1 — it published
``model.objects.all()`` with no visibility hook. See UPGRADING.md.

Extension seam: :attr:`FeedItem.extra_kwargs` is passed straight to Django's
``feedgenerator.add_item`` — so a downstream app adds ``<enclosure>`` (podcasts),
``categories``, or an author simply by populating it; podcast/media support is a
downstream add-on, not core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from django.http import HttpRequest

from apps.search.access import SearchAccess


@dataclass
class FeedItem:
    """One ``<item>``/``<entry>``. ``link`` may be a path (resolved to an
    absolute URL against the request) or already absolute. ``unique_id`` is the
    stable GUID — keep it stable across renders so readers dedupe correctly."""

    title: str
    link: str
    unique_id: str
    description: str = ""
    pubdate: datetime | None = None
    updateddate: datetime | None = None
    author_name: str = ""
    categories: tuple[str, ...] = ()
    # Passed verbatim to feedgenerator.add_item — the enclosure/podcast seam.
    extra_kwargs: dict[str, Any] = field(default_factory=dict)


class Feed:
    """Base provider. Subclass and implement :meth:`items` for a curated feed."""

    slug: str = ""
    title: str = ""
    description: str = ""
    link: str = "/"  # channel link (path or absolute)
    access: str = SearchAccess.STAFF
    language: str = "en"
    # Max items rendered — a guard so a feed never dumps an unbounded table.
    limit: int = 50

    def items(self, request: HttpRequest) -> Iterable[FeedItem]:  # pragma: no cover - abstract
        raise NotImplementedError

    def channel_description(self) -> str:
        return self.description or self.title
