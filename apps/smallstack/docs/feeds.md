---
title: RSS / Atom Feeds
description: Publish a blog, podcast or changelog as a curated RSS/Atom feed, or collect external feeds into a model on a schedule
---

# RSS / Atom Feeds

> **Building this?** Read the agent-facing skill first: [`docs/skills/rss.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/rss.md). It's prescriptive (what to do); this page is the reference (why + worked examples).

Feeds are SmallStack's **publishing** surface for the open web. A feed is how readers, podcast apps, Slack and Discord, Zapier and n8n, and RSS-to-email tools subscribe to what you publish, with nothing to configure per subscriber. For integrations between systems you control, use [webhooks](/smallstack/help/smallstack/webhooks/), the REST API or MCP instead.

`apps.feeds` has two halves. **Publish** a curated `Feed` built over a queryset you scope yourself; the blog and the status page are the shipped examples. **Collect** an external RSS/Atom source into a model on a schedule, for the systems that only speak RSS.

The master switch is `SMALLSTACK_FEEDS_ENABLED` (default on; off ⇒ `/feed/` 404s and the collector no-ops).

> **`enable_rss = True` was removed in v0.25.1.** The one-flag model feed published `model.objects.all()` with no tenancy or visibility hook, so a single flag could syndicate drafts and other tenants' rows anonymously. Setting it now raises `ImproperlyConfigured`; the migration is in `UPGRADING.md` and at the end of the skill file.

## Publish — a curated feed

Subclass `Feed`, build `items()` from a queryset **you** scope, and register it from `ready()`:

```python
from apps.feeds import Feed, FeedItem, register_feed
from apps.search.access import SearchAccess

class ChangelogFeed(Feed):
    slug = "changelog"                 # → /feed/changelog.rss and .atom
    title = "Changelog"
    access = SearchAccess.ANONYMOUS    # public; the default is STAFF
    link = "/changelog/"

    def items(self, request):
        for release in Release.objects.filter(published=True).order_by("-published_at", "-id")[:50]:
            yield FeedItem(
                title=release.title,
                link=release.get_absolute_url(),
                unique_id=f"changelog:{release.uid}",   # stable forever
                description=release.body_html,
                pubdate=release.published_at,
            )

# AppConfig.ready():
register_feed(ChangelogFeed())
```

Access follows the same three tiers as search. A gated feed answers `401` and accepts an API token in the `Authorization` header or a `?token=` query parameter, because readers cannot send a session cookie.

### Feeds for things created at runtime

The registry is a static slug map. When the thing you syndicate is created at runtime — one feed per blog, per podcast show — build the `Feed` in your own view and hand it to `apps.feeds.render.render_feed`, which is request-relative and emits absolute URLs. That is how `/blog/<slug>/feed.rss` works; the site-wide `/feed/blog.rss` is registered normally. Check `SMALLSTACK_FEEDS_ENABLED` yourself in such a view: the framework enforces it in its own view, not in the renderer.

### Enclosures and podcasts

`FeedItem.extra_kwargs` is passed straight to Django's `feedgenerator.add_item`, so `enclosures=[Enclosure(url, length, mime)]` and `categories=[…]` attach media and tags without touching core. The blog attaches each post's cover image this way. Full podcast directories also want the iTunes namespace; add it by subclassing `Rss201rev2Feed` in your own view.

## Collect — pull an external feed on a schedule

Register a feed source and the collector ingests it into the bundled `CollectedItem` model, or a model of yours, on a schedule (built on the [scheduler](/smallstack/help/smallstack/scheduler/)):

```python
from apps.feeds import register_feed_source

register_feed_source("django-news", "https://django-news.com/feed")
```

Run `manage.py migrate` once so `CollectedItem` exists. Collection is idempotent, authenticated sources take `token=` or `headers=`, and `manage.py collect_feeds` runs it by hand.

## Related

- [Blog & Newsletter](/smallstack/help/blog/) — the reference publisher: per-blog and site-wide feeds, JSON Feed, enclosures
- [Webhooks](/smallstack/help/smallstack/webhooks/) — the integration surface, push rather than pull
- [Scheduler](/smallstack/help/smallstack/scheduler/) — what the collector runs on
- [Search](/smallstack/help/smallstack/search/) — where the access tiers come from
