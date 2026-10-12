"""Render a :class:`~apps.feeds.base.Feed` to RSS 2.0 or Atom.

Uses Django's stdlib ``feedgenerator`` (no ``contrib.sites`` dependency —
absolute URLs come from the request). One renderer for both the model-backed
and custom feeds, so every feed is emitted identically.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils.feedgenerator import Atom1Feed, Rss201rev2Feed

from .base import Feed


def _absolute(request: HttpRequest, url: str | None) -> str:
    if not url:
        return request.build_absolute_uri("/")
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return request.build_absolute_uri(url)


def render_feed(feed: Feed, request: HttpRequest, fmt: str = "rss") -> tuple[str, str]:
    """Return ``(xml_string, content_type)`` for ``feed`` in ``fmt`` (rss|atom)."""
    feed_cls = Atom1Feed if fmt == "atom" else Rss201rev2Feed
    generator = feed_cls(
        title=feed.title,
        link=_absolute(request, getattr(feed, "link", "/")),
        description=feed.channel_description(),
        language=getattr(feed, "language", "en"),
        feed_url=request.build_absolute_uri(request.path),
    )

    for item in feed.items(request):
        kwargs: dict[str, Any] = {
            "title": item.title,
            "link": _absolute(request, item.link),
            "unique_id": item.unique_id,
            "unique_id_is_permalink": False,
            "description": item.description,
            "pubdate": item.pubdate,
            "updateddate": item.updateddate,
            "author_name": item.author_name or None,
        }
        if item.categories:
            kwargs["categories"] = tuple(item.categories)
        # The extension seam wins on any overlapping key (e.g. enclosure,
        # categories) — merge rather than double-pass to add_item().
        kwargs.update(item.extra_kwargs)
        # Normalize the enclosure seam: Django 6 dropped the singular
        # ``enclosure=`` kwarg in favour of ``enclosures=[...]``. Accept either
        # form (and fold a singular into the list) so a ``FeedItem.extra_kwargs``
        # keeps working regardless of Django version / which key it used.
        if "enclosure" in kwargs:
            enclosure = kwargs.pop("enclosure")
            if enclosure is not None:
                enclosures = list(kwargs.get("enclosures") or [])
                enclosures.append(enclosure)
                kwargs["enclosures"] = enclosures
        generator.add_item(**kwargs)

    return generator.writeString("utf-8"), generator.content_type
