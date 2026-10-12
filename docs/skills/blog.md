# Blogs + Newsletters (`apps/blog/`)

**Read this before touching posts, subscribers or the send pipeline.** The app
label is `smallstack_blog`, so its CRUD template overrides live under
`templates/smallstack_blog/`, not `templates/blog/`.

A **Blog** is a channel: an owner, a slug, and a visibility level. **Posts** are
markdown. A blog can also be a **newsletter**. A runbook **Document** can be
published into a blog and optionally kept in sync.

```
/my/blogs/               the author's studio login-gated, owner-scoped (namespace `myblogs`)
/smallstack/blog/        system blog manager login-gated, ownership-scoped CRUDViews
/blog/                   public reading      anonymous (gated by a setting)
/blog/<blog>/<post>/     permalink
/blog/<blog>/feed.rss    per-blog feed       .atom and .json too
/feed/blog.rss           site-wide river
/smallstack/api/blog/*   REST (authenticated, owner-scoped) — the WRITE API
/blog/api/blogs/*        JSON (anonymous, published only) — the READ API
```

## Two authoring surfaces, one set of rules

| | `/my/blogs/` — the studio | `/smallstack/blog/` — the system manager |
|---|---|---|
| For | a person writing in their own blogs | an operator managing every blog |
| Built from | hand-rolled views + `studio_forms.py` | CRUDViews (REST + MCP come from here) |
| Scope | `permissions.editable_blogs(user)` from the first query | `viewable_*` scopers, staff see all |
| Lifecycle | buttons set `action`; the editor is **saved first**, then `service.publish_post` etc. run in the same request | POST actions with `next=` |
| Entry points | nav "My blogs" beside Runbook, the user dropdown, the profile's Blogs card | admin section of the sidebar |

Both call the same service; neither has its own idea of "publish". Add a
field to the editor in `studio_forms.StudioPostForm`, and a lifecycle verb in
`studio_views._transition`.

## The two rules

**1. Every write goes through `apps/blog/service.py`.** A post's rendered HTML,
its excerpt, its slug uniqueness and its publication timestamps are derived
state. Anything that writes a `Post` without maintaining them leaves a row that
renders wrong, searches wrong or syndicates wrong. The console's
`on_form_valid`, the REST layer, the MCP tools, the scheduled ticks and the
management commands are all thin callers.

**2. Every read goes through `apps/blog/permissions.py`.** `viewable_posts` is
the single scoper behind the console list, console detail, REST list *and*
detail, every generated MCP tool, `search_visibility` and the public views. A
`qs.all()` there is a six-surface leak at once.

## Visibility — a three-way ladder, not a boolean

| `Blog.visibility` | Who reads it | `SearchAccess` |
|---|---|---|
| `private` (default) | owner + staff | `STAFF` |
| `members` | any signed-in user | `AUTHENTICATED` |
| `public` | anyone | `ANONYMOUS` |

Not `is_public: bool`, for two reasons. `Runbook.is_public` already means
*signed-in users* — a neighbouring field meaning *anonymous* is a bug waiting
to be written. And an internal team blog readable by every colleague and
invisible to the internet is a real case a boolean cannot express.

A **post** has its own lifecycle on top (`draft` / `scheduled` / `published` /
`archived`) and **both gates apply**. A published post in a private blog is
private; a draft in a public blog is a draft. `permissions.public_posts()` is
the one definition of "on the internet" — published, `published_at <= now`, in
a public blog. Use it; don't re-type the filter.

> `status == "published"` is **not** the same as live. A row with a future
> `published_at` is an embargo. Use `post.is_live` or
> `permissions.live_post_filter()`.

## Service API

```python
from apps.blog import service

# posts
service.create_post(blog, title=…, body_markdown=…, tags=["ops"], actor=user)
service.update_post(post, actor=user, **fields)   # refuses status/timestamps
service.publish_post(post, actor=user)            # idempotent
service.unpublish_post(post, actor=user)
service.schedule_post(post, when=aware_dt, actor=user)
service.archive_post(post, actor=user)
service.publish_due_posts()                       # the 5-minute tick
service.rerender_posts(stale_only=True)           # after a renderer change

# runbook bridge
service.publishable_documents(user)
service.publish_document(doc, blog, status="draft", sync="manual", actor=user)
service.resync_post(post, actor=user, force=True)

# newsletter
service.subscribe(blog, email, source="web")      # sends the confirmation
service.confirm_subscription(raw_token)
service.unsubscribe(raw_token)
service.import_subscribers(blog, rows, consent_note="…", confirmed=True, actor=user)
service.create_issue_from_post(post, actor=user)
service.queue_issue(issue, actor=user)            # freezes body + audience
service.send_issue_batch(issue)                   # one batch
service.process_sending_issues()                  # the 1-minute tick
service.reap_stale_claims()
service.retry_failed(issue, actor=user)
```

`actor=None` means a trusted internal caller (a task, a CLI command) and skips
authorization. Any other value is checked.

## The send pipeline

**`Delivery` rows are the ledger.** `queue_issue` materialises one per
recipient up front, snapshots `body_html` and freezes `recipient_count`; from
then on sending is just draining `pending`.

Three independent layers stop a double-send:

1. `UniqueConstraint(issue, subscriber)` — `queue_issue` is re-runnable.
2. `Delivery.status` — only `pending` is claimed; `sent` is terminal.
3. `UniqueConstraint(post) where status in (queued, sending, sent)` — one live
   campaign per post, ever.

Claiming is a **compare-and-swap** (`UPDATE … WHERE status='pending'`), not
`select_for_update(skip_locked=True)`, which raises `NotSupportedError` on
SQLite. A worker killed mid-batch leaves `claimed` rows; `reap_stale_claims()`
returns them (including rows whose `claimed_at` is NULL, which would otherwise
be orphaned forever). One SMTP connection per **batch**, via
`django.core.mail.mailers` — `get_connection()` is deprecated in Django 6.1.

### Bounce policy

| Failure | Delivery | Subscriber |
|---|---|---|
| `SMTPRecipientsRefused` / `SMTPSenderRefused` 5xx | `failed` | **suppressed** |
| dropped connection, timeout, 4xx | back to `pending`, `attempts += 1` | `consecutive_failures += 1` |
| soft failure at `SEND_MAX_ATTEMPTS` | `failed` | **not** suppressed |
| success | `sent` | `consecutive_failures = 0` |

Soft failures only suppress at `SOFT_FAIL_LIMIT` consecutive misses counted
across issues. Suppressing on *any* exception means one transient SMTP hiccup
silently and permanently drops a good reader.

### Tokens

`django.core.signing` with a **distinct salt per purpose**, so a confirm token
cannot be replayed as an unsubscribe token. Four checks on read: the
subscription exists, it is the blog the token was minted for, the address still
matches, and `token_version` is current (re-subscribing bumps it, so an old
unsubscribe link cannot kill a fresh signup). Confirm links expire; **unsubscribe
links never do** — an expired opt-out link is a compliance problem.

> **`/blog/unsubscribe/<token>/` POST is `@csrf_exempt`, and must stay that
> way.** RFC 8058 one-click arrives from Gmail/Yahoo with no session and no
> CSRF token; adding protection makes the unsubscribe button in every mail
> client silently fail. The signed token is the credential.

## Feeds — why `enable_rss` is OFF

`apps/feeds/model_feed.py` builds its queryset as `model.objects.all()`. It
never calls `get_list_queryset`, `get_detail_queryset` or `search_visibility`,
and there is no `rss_queryset` hook — so `enable_rss = True` on `Post` would
publish **every draft from every blog, including private ones**, to an
anonymous feed. `CRUDView._registry` is also first-wins per model, so a second
published-only CRUDView cannot be registered to work around it.

Both feeds are therefore curated `apps.feeds.base.Feed` subclasses built from
the permission scopers, rendered through the framework's own
`apps.feeds.render.render_feed`:

* **site-wide** — a fixed slug, registered into `apps.feeds` at `ready()`;
* **per-blog** — blogs are created at runtime and the registry is a static slug
  map, so these are constructed per request.

`SMALLSTACK_FEEDS_ENABLED` is enforced inside `apps/feeds/views.py`, not the
renderer, so a feed served from anywhere else must check it itself.

## The runbook bridge

One-directional: the blog reads runbook through `runbook.service` and
`runbook.permissions`; runbook does not know the blog exists, and no runbook
template is edited. The "Publish to blog" entry point is at
`/smallstack/blog/import-runbook/`.

Frontmatter is **parsed**, not just stripped — `title` and `description` become
the post's title and excerpt. (Runbook itself only strips it.) A leading `# H1`
that exactly matches the title is dropped at render time, because the page
already supplies the `<h1>`; a different first heading is kept.

`sync="auto"` follows the `document_written` signal. `sync="manual"` does not,
so an author who adapted the text for readers does not lose it.

## Settings

| Setting | Default | Notes |
|---|---|---|
| `SMALLSTACK_BLOG_ENABLED` | `True` | Master switch: nav, console, public, feeds, ticks. |
| `SMALLSTACK_BLOG_PUBLIC_ENABLED` | `True` | The anonymous surface alone. Off ⇒ **404**, not 403. |
| `SMALLSTACK_BLOG_PAGE_SIZE` | `10` | |
| `SMALLSTACK_BLOG_FEED_LIMIT` | `25` | |
| `SMALLSTACK_BLOG_SEND_BATCH_SIZE` | `100` | |
| `SMALLSTACK_BLOG_SEND_MAX_BATCHES` | `20` | Keeps a tick inside the lost-task reaper window. |
| `SMALLSTACK_BLOG_CLAIM_TIMEOUT_MINUTES` | `15` | Must exceed one batch's duration. |
| `SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS` | `3` | Soft failures only. |
| `SMALLSTACK_BLOG_SOFT_FAIL_LIMIT` | `5` | Consecutive, across issues, reset on success. |
| `SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL` | `True` | Refuse to queue when the site URL is localhost. |
| `SMALLSTACK_BLOG_CONFIRM_MAX_AGE_DAYS` | `7` | Confirm only; unsubscribe never expires. |

## Tools

```bash
manage.py blog_rerender [--blog slug] [--all] [--dry-run]
manage.py blog_send [--issue <uid>] [--dry-run] [--reap]
manage.py blog_import_subscribers <blog> <csv> --consent-note "…" [--confirmed]
manage.py rebuild_search_index smallstack_blog.Post   # after enabling search
```

Two `@scheduled` jobs: *Blog: publish scheduled posts* (5m) and *Blog: send
queued newsletter batches* (1m, `email` queue). Both need
`manage.py db_worker`; the status monitors on `/smallstack/status/` report when
nothing is draining them, because otherwise both fail completely silently.

## MCP

Generated from the flags: `list_/get_/create_/update_/delete_blog`, the same
for `blog_post`, `list_/get_/create_/update_newsletter_issue`, plus
`search_blogs` and `search_blog_posts`. Custom tools: `blog_draft_post`,
`blog_publish_post`, `blog_unpublish_post`, `blog_list_publishable_documents`,
`blog_publish_runbook_document`, `blog_resync_post`.

**There is no send tool, and the subscriber models are not exposed to MCP at
all.** Queueing a blast to thousands of real people is not a tool call, and a
tool that pages email addresses into an LLM client is a data-exfiltration
surface. Both omissions are load-bearing; a test asserts no blog tool returns a
subscriber address.

## Don't

1. **Don't write a `Post` outside the service.** `body_html`, `excerpt`,
   `html_renderer_version` and slug uniqueness all go stale.
2. **Don't use `queryset.update()` or `bulk_update` on `Post`.** No `post_save`
   ⇒ no search reindex, no webhook, no re-render. `publish_due_posts` iterates
   for exactly this reason; `bulk_actions` is empty on every blog CRUDView.
   After a genuine bulk write, call `service.reindex(posts)`.
3. **Don't set `enable_rss = True`.** See above.
4. **Don't add CSRF protection to the unsubscribe POST.**
5. **Don't expose subscribers to MCP or search.**
6. **Don't pass a permission scoper straight to `search_visibility`.** The
   registry calls `(queryset, user)`; the scopers take `(user, queryset)`. Use
   `permissions.search_visible_posts` / `search_visible_blogs`. Getting it
   wrong **fails safe** — the registry drops every hit — so the symptom is
   "search silently returns nothing", with no error anywhere.
7. **Don't call `reverse()` at import or `ready()` time** (e.g. in a
   `ModelForm.__init__`, which startup instantiates). It builds and caches the
   root URLConf before the app registry is ready, leaving every later-registered
   app with no routes. Use `reverse_lazy` or `django.utils.functional.lazy`.
   `apps/smallstack/test_urlconf_load_timing.py` is the canary.
8. **Don't hard-code a colour** in a template or `blog.css` — six palettes × two
   themes. See `modern-dark-theme.md`.

## When you're stuck

| Problem | Look at |
|---|---|
| Search returns no posts | Argument order on `search_visibility` (don't #6), then `manage.py rebuild_search_index smallstack_blog.Post` |
| A draft is visible publicly | Something bypassed `permissions.public_posts()`; grep for `status=` filters that omit `published_at` |
| Scheduled posts never publish | No worker on the `default` queue — check `/smallstack/status/` |
| A send is stuck at N of M | No worker on the `email` queue; `manage.py blog_send --reap` then `blog_send` |
| `queue_issue` refuses | Read the message: no confirmed subscribers, an empty body, or a localhost site URL |
| Unsubscribe links 403 | CSRF protection crept back onto the POST handler (don't #4) |
| The post page shows its title twice | The body's leading H1 differs from the title, so it was kept deliberately |
| Feed shows nothing after publishing | `SMALLSTACK_FEEDS_ENABLED`, then blog visibility — a members blog's feed 401s |

## Related

- `apps/blog/content/custom-pages.md` — the help page for showing posts in a
  project's own templates or a separate front end (scopers, JSON API shapes,
  CORS, publishing from code). Point users there before hand-rolling a query.

- `docs/skills/building-a-user-facing-site.md` — the login-gated-console +
  anonymous-surface pattern this app is the worked example of
- `docs/skills/rss.md` — the feeds subsystem (and the `enable_rss` caveat)
- `docs/skills/runbook-documents.md` — the service the bridge reads through
- `docs/skills/modern-dark-theme.md` — before touching any template
- `docs/skills/scheduler.md`, `docs/skills/search.md`, `docs/skills/webhooks.md`
