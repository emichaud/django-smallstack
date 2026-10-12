# RSS / Atom feeds — publish and consume

SmallStack ships a first-party **feed surface** (`apps.feeds`), symmetric like
webhooks: **publish** any model as an RSS/Atom feed the way you expose a REST
list, and **consume** external feeds on a schedule into a model. It's a
*foundation to build on*, not a podcast app — media/podcast feeds are a
documented extension (see "Enclosures & podcasts").

Read this before adding a feed, a feed collector, or anything that emits/ingests
RSS/Atom.

## Setup

`apps.feeds` is in `INSTALLED_APPS` already. The master switch is
`SMALLSTACK_FEEDS_ENABLED` (default on; off ⇒ `/feed/` 404s and the collector
no-ops). The consume side stores into a bundled `CollectedItem` model — run
`manage.py migrate` once.

---

## Publish — "expose a model as a feed"

> ### ⚠ `enable_rss` publishes the WHOLE table
>
> `ModelFeed.items()` is `model.objects.all().order_by(...)[:limit]`. It does
> **not** call `get_list_queryset`, `get_detail_queryset` or
> `search_visibility`, and there is no `rss_queryset` hook — so the flag
> publishes every row, including drafts, unpublished records and other
> tenants' data, at whatever `rss_access` allows.
>
> That is fine for what it was built for: a changelog, a status feed, a
> genuinely public list. It is **not** safe on a model with a publication
> state or per-user scoping. `CRUDView._registry` is first-wins per model, so
> you also cannot register a second, published-only CRUDView to work around
> it.
>
> For anything scoped, write a curated `Feed` subclass instead and build its
> queryset from your own permission helpers. `apps/blog/feeds.py` is the
> worked example: a site-wide feed registered at `ready()`, plus per-blog
> feeds constructed per request (blogs are created at runtime, and the
> registry is a static slug map), both rendered through
> `apps.feeds.render.render_feed` so there is still one XML code path.
>
> If you serve a feed from your own view rather than `/feed/<slug>`, check
> `SMALLSTACK_FEEDS_ENABLED` yourself — it is enforced inside
> `apps/feeds/views.py`, not in the renderer.

### The one-liner (model-backed)

Flip `enable_rss` on a CRUDView. The feed appears at `/feed/<slug>.rss` and
`/feed/<slug>.atom`. Item fields fall back to your search declarations, so a
single flag is usually enough:

```python
class ReleaseView(CRUDView):
    model = Release
    enable_rss = True
    search_display = "title"        # → <item><title>
    search_subtitle = "summary"     # → <item><description>
    # <pubDate> auto-detected from published_at / created_at / updated_at
    # <link>    from get_absolute_url() or the {url_base}-detail route
    # <guid>    "app.Model:pk"  (stable)
```

Tune with the `rss_*` attributes when the defaults aren't right:

| Attribute | Default | Purpose |
|---|---|---|
| `rss_slug` | `url_base` (slashes→dashes) | Feed URL slug |
| `rss_title_field` | `search_display`, else `str(obj)` | `<title>` |
| `rss_description_field` | `search_subtitle` | `<description>` |
| `rss_date_field` | first detected timestamp | `<pubDate>` |
| `rss_author_field` | — | `<author>` (e.g. `"owner__username"`) |
| `rss_ordering` | `["-<date_field>"]` | Feed order (reverse-chron) |
| `rss_access` | `search_access` | Who can read (see Access) |
| `rss_limit` | `50` | Max items |
| `rss_feed_title` / `rss_feed_description` | model plural | Channel metadata |

### Curated feeds (custom provider)

When a feed merges sources or is computed (not a raw per-model dump), subclass
`Feed` and register it. This is what the **status feed** does (incidents +
maintenance):

```python
from apps.feeds import Feed, FeedItem, register_feed
from apps.search.access import SearchAccess

class ChangelogFeed(Feed):
    slug = "changelog"
    title = "Changelog"
    access = SearchAccess.ANONYMOUS      # public
    link = "/changelog/"

    def items(self, request):
        for entry in Entry.objects.order_by("-published")[:50]:
            yield FeedItem(
                title=entry.title,
                link=entry.get_absolute_url(),
                unique_id=f"changelog:{entry.pk}",   # keep stable
                description=entry.body_html,
                pubdate=entry.published,
            )

# in your AppConfig.ready():
register_feed(ChangelogFeed())
```

`apps/heartbeat/feeds.py` is the worked reference — read it.

### Access

Feeds gate exactly like search (`SearchAccess`):

- `ANONYMOUS` — public (status pages, changelogs).
- `AUTHENTICATED` — any signed-in user, **or** a valid API token.
- `STAFF` (default) — staff users, or a token whose user is staff.

Readers can't send a session cookie, so token-gated feeds accept the token in
the `Authorization: Bearer` header **or** a `?token=` query param (embed it in
the subscribe URL). A gated feed returns **401** (not 403) so readers know to
retry with credentials.

### Enclosures & podcasts (the extension seam)

`FeedItem.extra_kwargs` is passed straight to Django's `feedgenerator.add_item`,
and overriding `rss_item_extra(self, obj)` on a CRUDView populates it per item.
That's where media/podcast support lives — **without** touching core:

```python
from django.utils.feedgenerator import Enclosure

class EpisodeView(CRUDView):
    enable_rss = True
    def rss_item_extra(self, obj):
        return {"enclosures": [Enclosure(obj.audio_url, str(obj.bytes), "audio/mpeg")]}
```

Use the **plural** `enclosures=[...]` — Django 6 dropped the old singular
`enclosure=` kwarg. SmallStack still accepts a singular `{"enclosure": …}` for
back-compat (it's folded into the list before rendering), but new code should
use the list form.

Full podcast feeds also need the iTunes namespace (`itunes:image`,
`itunes:duration`, …); subclass `Rss201rev2Feed` in a custom renderer for that.
FTS-style substring search on feeds is out of scope — feeds are chronological.

---

## Consume — "collect a feed into a model on a schedule"

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
including one **this app itself publishes** (the SmallStack→SmallStack symmetric
case) — give the source a token so the collector sends
`Authorization: Bearer <token>`:

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
nothing. (A reader-style `?token=…` in the source **URL** also works because the
publish view accepts it, but it stores a long-lived credential in the URL — prefer
`token=`/`headers=`.)

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

## Verifying

```bash
# Publish: list feeds, fetch one
manage.py shell -c "from apps.feeds.registry import all_feeds; print([f.slug for f in all_feeds()])"
curl -s http://localhost:8005/feed/status.rss | head

# Consume: register a source, collect, inspect
manage.py collect_feeds
manage.py shell -c "from apps.feeds.models import CollectedItem; print(CollectedItem.objects.count())"
```

## Anti-patterns

1. **Unstable `unique_id`** — the GUID must be stable across renders, or every
   poll looks new to readers. Use `"app.Model:pk"`, not a hash of the content.
2. **Publishing a raw high-volume table** — feeds are for human-readable,
   reverse-chronological events. Curate (like the status feed collapses
   per-minute beats into incidents) rather than dumping every row.
3. **Forgetting access** — a feed defaults to `STAFF`. Set
   `rss_access`/`access = ANONYMOUS` deliberately to make it public.
4. **Reinventing HTTP fetching / date parsing on the consume side** — use the
   collector + parser; they handle dedupe, RFC-822/3339 dates, and failures.

## Related

- [`webhooks.md`](webhooks.md) — the other integration surface (push, not pull)
- [`search.md`](search.md) — where `search_display`/`search_subtitle`/`search_access` come from
- [`scheduler.md`](scheduler.md) — the `@scheduled` primitive the collector uses
- [`status-monitors.md`](status-monitors.md) — the heartbeat app the status feed publishes from
