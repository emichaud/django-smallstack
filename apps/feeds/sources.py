"""Registry of feed sources to consume.

A downstream app declares its sources in ``apps.py:ready()`` (or a
``feed_sources.py`` autodiscovered module)::

    from apps.feeds import register_feed_source

    register_feed_source("upstream-status", "https://status.vendor.com/feed.rss")

    # or map into your own model:
    register_feed_source(
        "vendor-incidents",
        "https://status.vendor.com/history.atom",
        model=Incident,
        map=lambda item: {"guid": item.guid, "headline": item.title,
                          "url": item.link, "opened_at": item.published},
        dedupe="guid",
    )

The collector polls every enabled source and upserts (deduped on ``dedupe``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class FeedSource:
    name: str
    url: str
    model: type | None = None  # None → the bundled CollectedItem
    map: Callable[[Any], dict] | None = None  # ParsedItem -> model kwargs
    dedupe: str = "guid"  # unique field (scoped per-source) to detect seen items
    enabled: bool = True
    # Auth for gated feeds. `token` is sugar for a Bearer header; `headers`
    # merges arbitrary request headers. Both are sent on every fetch. Prefer
    # sourcing the secret from settings/env over hard-coding it.
    token: str | None = None
    headers: dict[str, str] | None = None

    def request_headers(self) -> dict[str, str]:
        """Extra request headers for the fetch (Bearer token + any custom)."""
        out: dict[str, str] = {}
        if self.token:
            out["Authorization"] = f"Bearer {self.token}"
        if self.headers:
            out.update(self.headers)
        return out


_sources: dict[str, FeedSource] = {}


def register_feed_source(
    name: str,
    url: str,
    *,
    model: type | None = None,
    map: Callable[[Any], dict] | None = None,
    dedupe: str = "guid",
    enabled: bool = True,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> FeedSource:
    """Register (or replace) a feed source by ``name``.

    ``token`` sends ``Authorization: Bearer <token>`` on the fetch (for
    consuming a STAFF/AUTHENTICATED feed — e.g. one this app itself publishes).
    ``headers`` merges arbitrary request headers. Source the secret from
    settings/env rather than embedding it in ``url`` as ``?token=``.
    """
    if name in _sources:
        logger.info("Feed source %r re-registered", name)
    source = FeedSource(
        name=name,
        url=url,
        model=model,
        map=map,
        dedupe=dedupe,
        enabled=enabled,
        token=token,
        headers=headers,
    )
    _sources[name] = source
    return source


def get_source(name: str) -> FeedSource | None:
    return _sources.get(name)


def all_sources() -> list[FeedSource]:
    return list(_sources.values())


def unregister_source(name: str) -> None:
    """Test helper."""
    _sources.pop(name, None)
