"""Consume-side tests — collector upserts + dedupes into a model."""

from __future__ import annotations

import pytest

from apps.feeds import collector
from apps.feeds.collector import collect_all, collect_source
from apps.feeds.models import CollectedItem
from apps.feeds.sources import all_sources, register_feed_source, unregister_source

pytestmark = pytest.mark.django_db

SAMPLE = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
  <item><title>A</title><link>https://e/a</link><guid>a</guid>
    <description>first</description><pubDate>Mon, 06 Sep 2021 16:20:00 +0000</pubDate></item>
  <item><title>B</title><link>https://e/b</link><guid>b</guid><description>second</description></item>
</channel></rss>"""


@pytest.fixture
def _fake_fetch(monkeypatch):
    """Serve SAMPLE bytes instead of hitting the network."""
    monkeypatch.setattr(collector, "_fetch", lambda url, headers=None: SAMPLE)


@pytest.fixture(autouse=True)
def _clean_sources():
    yield
    for s in list(all_sources()):
        unregister_source(s.name)


def test_collect_into_bundled_model(_fake_fetch):
    register_feed_source("blog", "https://e/feed.rss")
    result = collect_source("blog")
    assert result["fetched"] == 2 and result["created"] == 2 and result["error"] is None
    assert CollectedItem.objects.filter(source="blog").count() == 2
    a = CollectedItem.objects.get(source="blog", guid="a")
    assert a.title == "A" and a.summary == "first" and a.published is not None


def test_collect_is_idempotent(_fake_fetch):
    register_feed_source("blog", "https://e/feed.rss")
    collect_source("blog")
    second = collect_source("blog")
    assert second["created"] == 0 and second["skipped"] == 2
    assert CollectedItem.objects.filter(source="blog").count() == 2


def test_same_guid_across_sources_does_not_collide(_fake_fetch):
    register_feed_source("s1", "https://e/1.rss")
    register_feed_source("s2", "https://e/2.rss")
    collect_all()
    # guid "a" exists under both sources — dedupe is scoped per source.
    assert CollectedItem.objects.filter(guid="a").count() == 2


def test_custom_model_and_mapper(_fake_fetch):
    # Map into CollectedItem with a custom shape + a different dedupe field.
    register_feed_source(
        "mapped",
        "https://e/feed.rss",
        model=CollectedItem,
        map=lambda item: {"source": "mapped", "guid": item.guid, "title": item.title.lower()},
        dedupe="guid",
    )
    collect_source("mapped")
    assert CollectedItem.objects.get(source="mapped", guid="a").title == "a"


def test_unknown_source_reports_error():
    assert collect_source("nope")["error"] == "unknown source"


def test_fetch_failure_is_contained(monkeypatch):
    def boom(url, headers=None):
        raise OSError("network down")

    monkeypatch.setattr(collector, "_fetch", boom)
    register_feed_source("bad", "https://e/feed.rss")
    result = collect_source("bad")
    assert result["created"] == 0 and "network down" in result["error"]


def test_collect_all_noops_when_feeds_disabled(monkeypatch, settings):
    """Master switch off ⇒ collector does not fetch and returns []."""
    settings.SMALLSTACK_FEEDS_ENABLED = False

    def boom(url, headers=None):
        raise AssertionError("collector must not fetch when feeds are disabled")

    monkeypatch.setattr(collector, "_fetch", boom)
    register_feed_source("blog", "https://e/feed.rss")
    assert collect_all() == []
    assert CollectedItem.objects.count() == 0


# --- consume-side auth (token/headers threaded into the fetch) ---------------


def test_request_headers_builds_bearer_and_custom():
    from apps.feeds.sources import FeedSource

    s = FeedSource(name="x", url="https://e/f.rss", token="abc123", headers={"X-K": "v"})
    h = s.request_headers()
    assert h["Authorization"] == "Bearer abc123"
    assert h["X-K"] == "v"
    # No auth configured → no Authorization header.
    assert "Authorization" not in FeedSource(name="y", url="https://e/f.rss").request_headers()


def test_token_source_sends_bearer_header(monkeypatch):
    """A source with a token collects a gated feed — the Bearer header reaches _fetch."""
    seen = {}

    def fake_fetch(url, headers=None):
        seen["headers"] = headers or {}
        return SAMPLE

    monkeypatch.setattr(collector, "_fetch", fake_fetch)
    register_feed_source("gated", "https://e/staff.rss", token="tok-xyz")
    result = collect_source("gated")
    assert seen["headers"].get("Authorization") == "Bearer tok-xyz"
    assert result["fetched"] == 2 and result["error"] is None


def test_gated_feed_without_auth_reports_auth_required(monkeypatch):
    """No token on a 401 feed → clear 'auth required' error, zero items."""
    import urllib.error

    def raise_401(url, headers=None):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(collector, "_fetch", raise_401)
    register_feed_source("gated", "https://e/staff.rss")
    result = collect_source("gated")
    assert result["fetched"] == 0 and result["created"] == 0
    assert "auth required" in result["error"] and "401" in result["error"]


# ── collect_all fetches in parallel; writes stay on the calling thread ──────
def test_collect_all_fetches_sources_at_the_same_time(monkeypatch, settings):
    """A barrier proves overlap: serial fetches would break it and record errors."""
    import threading

    settings.SMALLSTACK_FEEDS_MAX_CONCURRENT_FETCHES = 6
    barrier = threading.Barrier(3, timeout=5)

    def meet(url, headers=None):
        barrier.wait()
        return SAMPLE

    monkeypatch.setattr(collector, "_fetch", meet)
    for name in ("p1", "p2", "p3"):
        register_feed_source(name, f"https://e/{name}.rss")
    results = collect_all()
    assert [r["name"] for r in results] == ["p1", "p2", "p3"]  # registry order kept
    assert all(r["error"] is None and r["created"] == 2 for r in results)


def test_pool_of_one_fetches_one_after_another(monkeypatch, settings):
    import threading

    settings.SMALLSTACK_FEEDS_MAX_CONCURRENT_FETCHES = 1
    barrier = threading.Barrier(2, timeout=0.2)

    def meet(url, headers=None):
        barrier.wait()
        return SAMPLE

    monkeypatch.setattr(collector, "_fetch", meet)
    register_feed_source("s_a", "https://e/a.rss")
    register_feed_source("s_b", "https://e/b.rss")
    assert all(r["error"] is not None for r in collect_all())  # nobody to meet


def test_pooled_writes_happen_on_the_calling_thread(monkeypatch, _fake_fetch):
    import threading

    from django.db.models.signals import post_save

    caller = threading.get_ident()
    writers: set[int] = set()

    def on_save(sender, **kwargs):
        writers.add(threading.get_ident())

    register_feed_source("w1", "https://e/1.rss")
    register_feed_source("w2", "https://e/2.rss")
    post_save.connect(on_save, sender=CollectedItem)
    try:
        collect_all()
    finally:
        post_save.disconnect(on_save, sender=CollectedItem)
    assert writers == {caller}
    assert CollectedItem.objects.count() == 4


def test_pooled_failures_stay_per_source(monkeypatch):
    import io
    import urllib.error

    def fetch(url, headers=None):
        if "gated" in url:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO())
        if "broken" in url:
            raise OSError("connection reset")
        return SAMPLE

    monkeypatch.setattr(collector, "_fetch", fetch)
    register_feed_source("ok", "https://e/ok.rss")
    register_feed_source("gated", "https://e/gated.rss")
    register_feed_source("broken", "https://e/broken.rss")
    by_name = {r["name"]: r for r in collect_all()}
    assert by_name["ok"]["created"] == 2 and by_name["ok"]["error"] is None
    assert "auth required" in by_name["gated"]["error"]
    assert by_name["broken"]["error"] == "connection reset"


def test_fetch_past_the_run_deadline_is_skipped(monkeypatch):
    import threading
    import time

    release = threading.Event()

    def fetch(url, headers=None):
        if "slow" in url:
            release.wait(10)
        return SAMPLE

    monkeypatch.setattr(collector, "_fetch", fetch)
    monkeypatch.setattr(collector, "_RUN_DEADLINE", 0.5)
    register_feed_source("slow", "https://e/slow.rss")
    register_feed_source("fast", "https://e/fast.rss")
    started = time.monotonic()
    try:
        by_name = {r["name"]: r for r in collect_all()}
    finally:
        release.set()
    assert time.monotonic() - started < 5  # abandoned, not waited on
    assert by_name["fast"]["created"] == 2
    assert "deadline" in by_name["slow"]["error"]
    assert not CollectedItem.objects.filter(source="slow").exists()


def test_a_source_never_fetched_says_so(monkeypatch, settings):
    import threading

    release = threading.Event()

    def fetch(url, headers=None):
        if "slow" in url:
            release.wait(10)
        return SAMPLE

    settings.SMALLSTACK_FEEDS_MAX_CONCURRENT_FETCHES = 2
    monkeypatch.setattr(collector, "_fetch", fetch)
    monkeypatch.setattr(collector, "_RUN_DEADLINE", 0.5)
    monkeypatch.setattr(collector.random, "sample", lambda seq, k: list(seq))  # registry order
    register_feed_source("slow1", "https://e/slow1.rss")
    register_feed_source("slow2", "https://e/slow2.rss")
    register_feed_source("tail", "https://e/tail.rss")
    try:
        by_name = {r["name"]: r for r in collect_all()}
    finally:
        release.set()
    assert "still running" in by_name["slow1"]["error"]
    assert by_name["tail"]["error"].startswith("not fetched")
