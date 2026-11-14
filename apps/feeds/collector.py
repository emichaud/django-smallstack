"""Fetch → parse → upsert. The consume half of the RSS surface.

``collect_all()`` runs from both the ``@scheduled`` job and ``manage.py
collect_feeds`` (same core). Idempotent: items are deduped on the source's
``dedupe`` field, so re-polling never creates duplicates.
"""

from __future__ import annotations

import logging
import random
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

from django.conf import settings
from django.db.models import Model

from .parser import ParsedItem, parse_feed
from .sources import FeedSource, all_sources, get_source

logger = logging.getLogger(__name__)

_USER_AGENT = "SmallStack-FeedCollector/1.0 (+https://github.com/emichaud/django-smallstack)"
_TIMEOUT = 20


def _fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    all_headers = {"User-Agent": _USER_AGENT}
    if headers:
        all_headers.update(headers)
    req = urllib.request.Request(url, headers=all_headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (trusted, registered URLs)
        return resp.read()


def _default_map(item: ParsedItem, source: FeedSource) -> dict:
    """ParsedItem → CollectedItem kwargs (the zero-config landing shape)."""
    return {
        "source": source.name,
        "guid": item.guid,
        "title": item.title[:500],
        "link": item.link[:1000],
        "summary": item.summary,
        "author": item.author[:255],
        "published": item.published,
        "raw": {**item.raw, "enclosures": item.enclosures} if item.enclosures else item.raw,
    }


def _target_model(source: FeedSource) -> type[Model]:
    if source.model is not None:
        return source.model
    from .models import CollectedItem

    return CollectedItem


def _model_has_field(model: type[Model], name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return False


def _download(source: FeedSource) -> list[ParsedItem]:
    """Fetch and parse one source. Network and CPU only, no ORM, so it is safe
    on a worker thread; ``collect_all`` runs several at once."""
    return parse_feed(_fetch(source.url, source.request_headers()))


def _failure(name: str, source: FeedSource, exc: BaseException) -> dict:
    """The result row for a fetch or parse that raised."""
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403):
        # A gated feed answers 401 (or 403) — point the operator at the fix
        # rather than surfacing the raw urllib message.
        logger.warning("Feed %s (%s) requires auth (HTTP %s)", name, source.url, exc.code)
        return {
            "name": name,
            "error": f"auth required (HTTP {exc.code}) — set token=/headers= on the source",
            "fetched": 0,
            "created": 0,
            "skipped": 0,
        }
    logger.error("Feed fetch/parse failed for %s (%s)", name, source.url, exc_info=exc)
    return {"name": name, "error": str(exc), "fetched": 0, "created": 0, "skipped": 0}


def _ingest(source: FeedSource, items: list[ParsedItem]) -> dict:
    """Upsert parsed items into the source's model. Calling thread only."""
    name = source.name
    model = _target_model(source)
    created = skipped = 0
    for item in items:
        kwargs = source.map(item) if source.map else _default_map(item, source)
        dedupe_val = kwargs.get(source.dedupe)
        if dedupe_val in (None, ""):
            skipped += 1
            continue
        lookup = {source.dedupe: dedupe_val}
        # Scope dedupe by source when the target model records it (so two
        # sources can carry the same guid without colliding).
        if "source" in kwargs and _model_has_field(model, "source"):
            lookup["source"] = kwargs["source"]
        defaults = {k: v for k, v in kwargs.items() if k not in lookup}
        try:
            _, was_created = model._default_manager.get_or_create(defaults=defaults, **lookup)
            created += 1 if was_created else 0
            skipped += 0 if was_created else 1
        except Exception:
            logger.exception("Upsert failed for %s item %r", name, dedupe_val)
            skipped += 1

    return {"name": name, "fetched": len(items), "created": created, "skipped": skipped, "error": None}


def collect_source(name: str) -> dict:
    """Poll one source. Returns ``{name, fetched, created, skipped, error}``."""
    source = get_source(name)
    if source is None:
        return {"name": name, "error": "unknown source", "fetched": 0, "created": 0, "skipped": 0}
    if not source.enabled:
        return {"name": name, "error": "disabled", "fetched": 0, "created": 0, "skipped": 0}
    try:
        items = _download(source)
    except Exception as exc:
        return _failure(name, source, exc)
    return _ingest(source, items)


# A whole run gives up on a fetch still going after this long (DNS can hang
# past urllib's own timeout), so one stuck source can't hold the task worker.
_RUN_DEADLINE = 3 * _TIMEOUT


def _pool_size() -> int:
    return max(1, int(getattr(settings, "SMALLSTACK_FEEDS_MAX_CONCURRENT_FETCHES", 6)))


def collect_all() -> list[dict]:
    """Poll every enabled source. One source's failure never aborts the rest.

    Sources are fetched in parallel on a small thread pool, so a run with N slow
    feeds costs about one timeout rather than N. Every database write stays on
    the calling thread. Results come back in registry order.

    No-ops (returns ``[]``) when the ``SMALLSTACK_FEEDS_ENABLED`` master switch
    is off, so a disabled feeds surface never reaches out over the network.
    """
    if not getattr(settings, "SMALLSTACK_FEEDS_ENABLED", True):
        return []
    enabled = [source for source in all_sources() if source.enabled]
    if len(enabled) <= 1 or _pool_size() <= 1:
        return [collect_source(source.name) for source in enabled]

    pool = ThreadPoolExecutor(max_workers=min(_pool_size(), len(enabled)), thread_name_prefix="feed-fetch")
    try:
        # A different order each run, so a deadline that cuts the queue short
        # doesn't starve the same sources every time.
        order = random.sample(enabled, len(enabled))
        futures = {source.name: pool.submit(_download, source) for source in order}
        wait(futures.values(), timeout=_RUN_DEADLINE)
        results = []
        for source in enabled:
            future = futures[source.name]
            if not future.done():
                # cancel() succeeds only for a fetch that never started (queued
                # behind slow ones): say so, rather than "still running".
                started = not future.cancel()
                logger.warning(
                    "Feed %s (%s) %s after %ss; skipped",
                    source.name,
                    source.url,
                    "still fetching" if started else "not reached",
                    _RUN_DEADLINE,
                )
                results.append(
                    {
                        "name": source.name,
                        "error": (
                            f"fetch still running after the {_RUN_DEADLINE}s run deadline"
                            if started
                            else f"not fetched: the {_RUN_DEADLINE}s run deadline came first"
                        ),
                        "fetched": 0,
                        "created": 0,
                        "skipped": 0,
                    }
                )
            elif (exc := future.exception()) is not None:
                results.append(_failure(source.name, source, exc))
            else:
                results.append(_ingest(source, future.result()))
        return results
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
