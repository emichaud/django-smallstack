# RSS / Atom feeds — publish curated feeds, collect external ones

Feeds are a **publishing** surface in SmallStack, not an integration one. Use a
feed when other people's tools need to subscribe on their own terms — readers,
podcast apps, Slack/Discord RSS apps, Zapier/n8n triggers, RSS-to-email — and
nothing on your side should have to be configured per subscriber. For
integrations you own, reach for webhooks (push), the REST API (pull) or MCP
(agents) instead; see [`webhooks.md`](webhooks.md).

`apps.feeds` has two halves:

- **Publish** — subclass `Feed`, build items from *your own scoped queryset*,
  `register_feed()` it. The blog and the status page are the worked examples.
- **Collect** — `register_feed_source()` pulls an external RSS/Atom source into
  a model on a schedule, for the systems that only speak RSS.

> **`enable_rss = True` is gone (v0.25.1).** The one-flag model feed published
> `model.objects.all()` with no tenancy or visibility hook, so one flag could
> syndicate drafts and other tenants' rows anonymously. Setting `enable_rss`,
> any `rss_*` attribute or `rss_item_extra` on a CRUDView now raises
> `ImproperlyConfigured` at import. The migration is below; `UPGRADING.md`
> has the same recipe.

Read this before adding a feed, a feed collector, or anything that emits or
ingests RSS/Atom.

## Setup

`apps.feeds` is in `INSTALLED_APPS` already. The master switch is
`SMALLSTACK_FEEDS_ENABLED` (default on; off ⇒ `/feed/` 404s and the collector
no-ops). The consume side stores into a bundled `CollectedItem` model — run
`manage.py migrate` once.

---

## Publish — a curated feed

Subclass `Feed`, implement `items()` over a queryset **you** scope, register it
from `ready()`. The queryset is the whole point: a feed is anonymous and
cacheable, so it must only ever contain rows that are public by your own rules.

```python
# apps/changelog/feeds.py
from apps.feeds import Feed, FeedItem, register_feed
from apps.search.access import SearchAccess

class ChangelogFeed(Feed):
    slug = "changelog"                    # → /feed/changelog.rss and .atom
    title = "Changelog"
    description = "Every shipped release."
    access = SearchAccess.ANONYMOUS       # public; default is STAFF
    link = "/changelog/"

    def items(self, request):
        qs = Release.objects.filter(published=True).order_by("-published_at", "-id")[:50]
        for release in qs:
            yield FeedItem(
                title=release.title,
                link=release.get_absolute_url(),
                unique_id=f"changelog:{release.uid}",   # stable forever — never a hash of content
                description=release.body_html,
                pubdate=release.published_at,
                author_name=release.author_name,
            )

# apps/changelog/apps.py
def ready(self):
    from apps.feeds import register_feed
    from .feeds import ChangelogFeed
    register_feed(ChangelogFeed())
```

Rules that keep this safe and readable:

- **Scope the queryset with the same helper your views use.** The blog calls
  `permissions.public_posts()`; it never filters on `status` by hand.
- **Order explicitly with a unique tiebreaker** (`-published_at`, `-id`).
  Postgres returns equal keys in arbitrary order, and a feed that reshuffles
  looks like new items to every reader.
- **`unique_id` must survive a slug change and a database restore.** Use a
  UUID or `"app.Model:pk"`, not the URL.
- **Register at `ready()` only for fixed slugs.** A feed per runtime object
  (per blog, per podcast show) is built per request instead — see below.

### Feeds for runtime objects (per blog, per show)

The registry is a static slug → feed map filled at startup. When the thing you
are syndicating is created at runtime, construct the `Feed` in your own view and
hand it to the framework renderer, which is already request-relative and emits
absolute URLs:

```python
from django.conf import settings
from django.http import Http404, HttpResponse
from apps.feeds.render import render_feed

def blog_feed_view(request, blog_slug, fmt="rss"):
    if not getattr(settings, "SMALLSTACK_FEEDS_ENABLED", True):
        raise Http404("Feeds are disabled")       # enforced in feeds.views, NOT the renderer
    blog = _visible_blog(request, blog_slug)      # your own visibility rule
    xml, content_type = render_feed(BlogFeed(blog), request, "atom" if fmt == "atom" else "rss")
    return HttpResponse(xml, content_type=content_type)
```

`apps/blog/feeds.py` does exactly this for `/blog/<slug>/feed.rss|atom|json`,
plus a site-wide river registered normally. Both kinds share one item builder
so the formats cannot drift.

### Access

Feeds gate exactly like search (`SearchAccess`):

- `ANONYMOUS` — public (blogs, podcasts, changelogs, status pages).
- `AUTHENTICATED` — any signed-in user, **or** a valid API token.
- `STAFF` (default) — staff users, or a token whose user is staff.

Readers can't send a session cookie, so token-gated feeds accept the token in
the `Authorization: Bearer` header **or** a `?token=` query param (embed it in
the subscribe URL). A gated feed returns **401** (not 403) so readers know to
retry with credentials.

### Enclosures & podcasts

`FeedItem.extra_kwargs` is passed straight to Django's `feedgenerator.add_item`.
That is where media lives — cover images, audio, categories — without touching
core:

```python
from django.utils.feedgenerator import Enclosure

yield FeedItem(
    title=episode.title,
    link=episode.get_absolute_url(),
    unique_id=f"podcast:{episode.uid}",
    description=episode.show_notes_html,
    pubdate=episode.published_at,
    extra_kwargs={
        "enclosures": [Enclosure(episode.audio.url, str(episode.audio.size), "audio/mpeg")],
        "categories": [t.name for t in episode.tags.all()],
    },
)
```

Use the **plural** `enclosures=[...]` — Django 6 dropped the singular kwarg.
SmallStack still folds a singular `{"enclosure": …}` into the list for
back-compat, but new code should use the list form. The blog attaches a post's
cover image this way (`apps/blog/feeds.py:_enclosure_kwargs`).

Full podcast directories also want the iTunes namespace (`itunes:image`,
`itunes:duration`, `itunes:explicit`). Subclass `Rss201rev2Feed`, add the
namespace in `root_attributes()` and the elements in `add_item_elements()`,
and pass that generator to your own view. That is a downstream add-on, not
core; the `Feed` / `FeedItem` shape does not change.

---

## Collect — pull an external feed into a model on a schedule

This is the integration half, kept here because it shares the parser. Use it
when the content originates elsewhere and the source only offers RSS/Atom:
vendor security advisories, a partner's announcements, a podcast's episodes.

### Register a source

Declare sources in your app's `ready()` (or an autodiscovered `feed_sources.py`):

```python
from apps.feeds import register_feed_source

# Zero-config: items land in the bundled CollectedItem model.
register_feed_source("python-insider", "https://blog.python.org/feeds/posts/default")

# Or map into your own model with a custom dedupe key:
register_feed_source(
    "vendor-status",
    "https://status.vendor.com/history.atom",
    model=VendorIncident,
    map=lambda item: {"guid": item.guid, "headline": item.title,
                      "url": item.link, "opened_at": item.published},
    dedupe="guid",
)
```

`map` receives a `ParsedItem` (`title`, `link`, `guid`, `summary`, `author`,
`published`, `enclosures`, `raw`) and returns model kwargs. Dedupe is scoped per
source, so two feeds can share a guid without colliding.

### Consuming an authenticated feed

Public feeds need nothing extra. To consume a `STAFF`/`AUTHENTICATED` feed —
including one **this app itself publishes** (the SmallStack→SmallStack case) —
give the source a token so the collector sends `Authorization: Bearer <token>`:

```python
from django.conf import settings

register_feed_source(
    "internal-audit",
    "https://myapp.example.com/feed/audit.rss",
    token=settings.INTERNAL_FEED_TOKEN,        # → Authorization: Bearer …
)

# Arbitrary headers also work (e.g. a vendor's API-key header):
register_feed_source("vendor", "https://vendor.example.com/feed.rss",
                     headers={"X-API-Key": settings.VENDOR_KEY})
```

Source the secret from settings/env — don't hard-code it. A gated source with no
`token`/`headers` fails cleanly: the collector reports
`auth required (HTTP 401) — set token=/headers= on the source` and collects
nothing.

### Run the collector

It runs two ways off the **same** `collect_all()` core:

```bash
manage.py collect_feeds            # all sources, run by hand (backfill/debug)
manage.py collect_feeds vendor-status
```

and on a schedule — the `@scheduled` `poll_feed_sources` job (every 15 min by
default) shows up in the scheduler UI, where ops can pause/retune the cadence
without a redeploy. Collection is idempotent: re-polling never duplicates.

The parser handles **RSS 2.0 + Atom 1.0** with zero dependencies. Need exotic
formats (RSS 1.0/RDF, Media RSS)? Swap in `feedparser` behind the same
`parse_feed`/`ParsedItem` seam.

---

## Migrating from `enable_rss` (removed in v0.25.1)

If a CRUDView set `enable_rss = True`:

1. Create a `Feed` subclass in your app's `feeds.py`, as in the example above.
   `rss_slug` → `slug`; `rss_feed_title` / `rss_feed_description` → `title` /
   `description`; `rss_access` → `access`; `rss_limit` and `rss_ordering` →
   the slice and `order_by` in `items()`; `rss_title_field` /
   `rss_description_field` / `rss_date_field` / `rss_author_field` → the
   `FeedItem` kwargs; `rss_item_extra()` → `extra_kwargs=`.
2. **Scope the queryset.** This is the step the flag never did. Use the same
   helper your list view uses, or the public subset explicitly.
3. `register_feed(YourFeed())` from `AppConfig.ready()`.
4. Delete the `enable_rss` / `rss_*` lines. They now raise
   `ImproperlyConfigured` at import so a stale copy cannot be missed.

The feed URL stays `/feed/<slug>.rss` and `.atom`; keep the same slug and
`unique_id` scheme (`"app.Model:pk"`) and existing subscribers notice nothing.

## Verifying

```bash
# Publish: list feeds, fetch one
manage.py shell -c "from apps.feeds.registry import all_feeds; print([f.slug for f in all_feeds()])"
curl -s http://localhost:8005/feed/status.rss | head
curl -s http://localhost:8005/feed/blog.rss | head

# Consume: register a source, collect, inspect
manage.py collect_feeds
manage.py shell -c "from apps.feeds.models import CollectedItem; print(CollectedItem.objects.count())"
```

## Anti-patterns

1. **Filtering the feed's queryset by hand** (`status="published"`) instead of
   with the helper your views use — scheduled posts and visibility tiers slip
   through. The blog's `public_posts()` is the model.
2. **Unstable `unique_id`** — the GUID must be stable across renders, or every
   poll looks new to readers. Use a UUID or `"app.Model:pk"`, not a hash of
   the content or the URL.
3. **Publishing a raw high-volume table** — feeds are for human-readable,
   reverse-chronological events. Curate (like the status feed collapses
   per-minute beats into incidents) rather than dumping every row.
4. **Forgetting access** — a feed defaults to `STAFF`. Set
   `access = SearchAccess.ANONYMOUS` deliberately to make it public.
5. **Using a feed where you own both ends** — if you control the consumer,
   webhooks push with a signature and retries; the API paginates and filters.
6. **Reinventing HTTP fetching / date parsing on the consume side** — use the
   collector + parser; they handle dedupe, RFC-822/3339 dates, and failures.

## Related

- [`blog.md`](blog.md) — the reference publisher: site-wide + per-blog feeds, JSON Feed, enclosures
- [`webhooks.md`](webhooks.md) — the integration surface (push, not pull)
- [`search.md`](search.md) — where `SearchAccess` comes from
- [`scheduler.md`](scheduler.md) — the `@scheduled` primitive the collector uses
- [`status-monitors.md`](status-monitors.md) — the heartbeat app the status feed publishes from
