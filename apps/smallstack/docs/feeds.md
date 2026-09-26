---
title: RSS / Atom Feeds
description: Publish any model as an RSS/Atom feed with one flag, or consume external feeds on a schedule into a model
---

# RSS / Atom Feeds

> **Building this?** Read the agent-facing skill first: [`docs/skills/rss.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/rss.md). It's prescriptive (what to do); this page is the reference (why + worked examples).

SmallStack ships a first-party **feed surface** (`apps.feeds`), symmetric like webhooks: **publish** any model as an RSS/Atom feed the way you expose a REST list, and **consume** external feeds on a schedule into a model. It's a foundation to build on, not a podcast app — media/podcast feeds are a documented extension.

The master switch is `SMALLSTACK_FEEDS_ENABLED` (default on; off ⇒ `/feed/` 404s and the collector no-ops).

## Publish — expose a model as a feed

Flip `enable_rss` on a CRUDView. The feed appears at `/feed/<slug>.rss` and `/feed/<slug>.atom`. Item fields fall back to your search declarations, so a single flag is usually enough:

```python
class ReleaseView(CRUDView):
    model = Release
    enable_rss = True
    search_display = "title"        # → <item><title>
    search_subtitle = "summary"     # → <item><description>
    # <pubDate> auto-detected from published_at / created_at / updated_at
    # <link>    from get_absolute_url() or the detail route
    # <guid>    "app.Model:pk"  (stable)
```

Tune with `rss_*` attributes (`rss_slug`, `rss_title_field`, `rss_date_field`, `rss_author_field`, `rss_ordering`, `rss_access`, `rss_limit`, `rss_feed_title`, …) when the defaults aren't right. Feed access follows `search_access` by default, so a feed is exactly as public or staff-gated as you declare.

### Curated & podcast feeds

When a feed merges sources or is computed (not a raw per-model dump), subclass `Feed` and register it — this is what the built-in **status feed** (incidents + maintenance) does. Enclosures/podcasts are produced with `rss_item_extra`.

## Consume — pull an external feed on a schedule

Register a feed source and the collector ingests it into a bundled `CollectedItem` model on a schedule (built on the [scheduler](/smallstack/help/smallstack/background-tasks/)):

```python
from apps.feeds import register_feed_source

register_feed_source(
    slug="django-news",
    url="https://django-news.com/feed",
)
```

Run `manage.py migrate` once so `CollectedItem` exists, and the collector deduplicates as it pulls.

## Related

- [Webhooks](/smallstack/help/smallstack/webhooks/) — the other half of the outbound/inbound integration story
- [Background Tasks](/smallstack/help/smallstack/background-tasks/) — the scheduler the collector runs on
- [Search](/smallstack/help/smallstack/search/) — the `search_display` / `search_subtitle` declarations feeds reuse
