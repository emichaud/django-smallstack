---
title: Showing posts in your own pages
order: 6
---

# Showing posts in your own pages

The built-in reader at `/blog/` is deliberately plain. Most projects want
posts somewhere else too: a "Latest from the blog" strip on the home page, a
`/news/` page in the project's own theme, a React or Astro front end, a static
site. This page is the recipe for each of those, and for publishing *into* a
blog from your own code.

Everything below rests on one rule: **never filter posts yourself**. Which
posts a visitor may see depends on the blog's visibility (private / members /
public), the post's status, *and* whether its publish time has passed — a
scheduled post is `published` with a future `published_at`. The scopers in
`apps.blog.permissions` and the public JSON API encode all three. Use them and
your page shows exactly what `/blog/` shows.

## Pick the route

| Where the page is rendered | Use |
|---|---|
| A Django view in this project (your own template, your own theme) | the Python scopers, [below](#in-a-django-template-same-project) |
| A separate front end — React, Vue, Astro, Next, a static-site generator | the anonymous JSON API, [below](#from-another-front-end-the-json-api) |
| A feed reader, a newsletter tool, another CMS | the [feeds](feeds-and-apis.md) |

## In a Django template (same project)

Query through the permission scopers, then render the stored HTML.

```python
# apps/website/views.py
from django.shortcuts import render

from apps.blog import permissions
from apps.blog.models import Post


def home_view(request):
    latest = (
        permissions.viewable_posts(request.user)       # what THIS visitor may read
        .filter(blog__slug="field-notes")             # optional: one blog
        .select_related("blog", "author")
        .prefetch_related("tags")
        .order_by("-published_at", "-id")[:3]
    )
    return render(request, "website/home.html", {"latest_posts": latest})
```

```django
{# templates/website/home.html #}
<section class="card">
  <h2>Latest from the blog</h2>
  {% for post in latest_posts %}
    <article>
      <h3><a href="{{ post.get_absolute_url }}">{{ post.title }}</a></h3>
      <p>{{ post.excerpt }}</p>
      <small>
        {{ post.published_at|date:"j M Y" }} · {{ post.blog.name }}
        {% for tag in post.tags.all %} · {{ tag.name }}{% endfor %}
      </small>
    </article>
  {% empty %}
    <p>Nothing published yet.</p>
  {% endfor %}
  <a href="{% url 'blog:blog_detail' 'field-notes' %}">All posts →</a>
</section>
```

Two scopers cover every case:

- `permissions.viewable_posts(user)` — everything `user` may read: live posts
  in blogs they can see, plus their own drafts if they are an author. Pass
  `request.user` and an anonymous visitor, a colleague on a members blog and
  the owner previewing a draft all get the right answer from one line.
- `permissions.public_posts()` — the anonymous subset only (live posts in
  public blogs). Use it for anything cached or shared between visitors, such
  as a sitemap, a home-page strip rendered into a page cache, or a feed.

Both accept an optional queryset to narrow first:
`permissions.public_posts(Post.objects.filter(is_featured=True))`.

### A full post page in your theme

If you want the article itself inside your own base template rather than the
built-in reader:

```python
from django.shortcuts import get_object_or_404, render

from apps.blog import permissions


def article_view(request, blog_slug, post_slug):
    post = get_object_or_404(
        permissions.viewable_posts(request.user).select_related("blog"),
        blog__slug=blog_slug,
        slug=post_slug,
    )
    return render(request, "website/article.html", {"post": post})
```

```django
{% extends "smallstack/base.html" %}
{% load static %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'blog/public.css' %}">{% endblock %}
{% block content %}
  <article class="blog-article">
    <h1>{{ post.title }}</h1>
    {% if post.cover_image %}<img src="{{ post.cover_image.url }}" alt="{{ post.cover_alt }}">{% endif %}
    {% if post.body_toc %}<nav aria-label="On this page">{{ post.body_toc|safe }}</nav>{% endif %}
    {{ post.body_html|safe }}
  </article>
{% endblock %}
```

The fields you will reach for:

| Field | Notes |
|---|---|
| `title`, `slug`, `excerpt` | `excerpt` is plain text, derived from the body when the author leaves it blank |
| `body_html` | Rendered and sanitised when the post was saved. `\|safe` is correct here — raw HTML in the markdown is escaped at render time, not trusted |
| `body_toc` | A `<ul>` of in-page anchors, or empty. The built-in reader shows it only when it has three or more entries |
| `body_markdown` | The source, if you want to render it differently (`apps.smallstack.transforms.render_markdown` is the hardened renderer the blog uses) |
| `cover_image`, `cover_alt` | An `ImageField`; check `if post.cover_image` before reading `.url` |
| `published_at`, `updated_at` | Aware datetimes. `published_at` is `None` on drafts |
| `tags` | Per-blog `Tag` rows with `name` and `slug` |
| `blog` | `name`, `slug`, `tagline`, `get_absolute_url()` |
| `get_absolute_url()` | The built-in reader's permalink, `/blog/<blog>/<post>/`. `public_url` is the same but `""` when the public surface is switched off |
| `is_live` | `True` when published and the publish time has passed — useful in a template, but filter with the scopers, not this |

Linking back into the built-in reader works with the `blog` URL namespace:
`{% url 'blog:post_detail' post.blog.slug post.slug %}`,
`{% url 'blog:tag' post.blog.slug tag.slug %}`, `{% url 'blog:archive' blog.slug %}`.

### Search on your own page

`apps.search.registry.search_all(query, user=request.user)` returns ranked hits
across every searchable model, already scoped per visitor; keep the ones with
`model_label == "smallstack_blog.Post"`. Each hit's `extra` carries the blog
name, publish date, reading time, tags and cover (the blog's
`transform_hit`), so you can render a rich result without a second query.

## From another front end (the JSON API)

Anonymous, no token, published content only, mounted next to the reader:

| Endpoint | Returns |
|---|---|
| `GET /blog/api/blogs/` | `{"blogs": [{slug, name, tagline, description, url, feeds: {rss, atom, json}}]}` |
| `GET /blog/api/blogs/<blog>/posts/?page=2&tag=ops` | `{"blog": {slug, name}, "count", "page", "pages", "posts": [post…]}` |
| `GET /blog/api/blogs/<blog>/posts/<post>/` | `{"post": post}` with `body_html` and `body_markdown` added |
| `GET /blog/api/blogs/<blog>/tags/` | `{"tags": [{slug, name, count}]}` |

A `post` object in a list:

```json
{
  "uid": "7b1b2c0e-…",
  "slug": "running-postgres-without-surprises",
  "title": "Running Postgres Without Surprises",
  "excerpt": "SQLite forgives a great deal. Postgres does not…",
  "url": "/blog/field-notes/running-postgres-without-surprises/",
  "canonical_url": null,
  "published_at": "2026-10-11T09:00:00+00:00",
  "updated_at": "2026-10-11T09:12:41+00:00",
  "tags": [{"slug": "ops", "name": "ops"}, {"slug": "postgres", "name": "postgres"}],
  "author": "everett",
  "cover": {"url": "/media/blog/covers/2026/10/….jpg", "alt": "A dashboard"}
}
```

`url` and `cover.url` are site-relative. Prefix them with the site origin when
the front end lives on another host. `cover` is `null` when there is no image.
Page size follows `SMALLSTACK_BLOG_PAGE_SIZE` (default 10); walk `page` until
it equals `pages`.

```js
// A React / Astro / plain-fetch client
const ORIGIN = "https://example.com";

export async function latestPosts(blog, page = 1) {
  const res = await fetch(`${ORIGIN}/blog/api/blogs/${blog}/posts/?page=${page}`);
  if (!res.ok) throw new Error(`blog api ${res.status}`);
  const data = await res.json();
  return data.posts.map((p) => ({ ...p, url: ORIGIN + p.url }));
}

export async function post(blog, slug) {
  const res = await fetch(`${ORIGIN}/blog/api/blogs/${blog}/posts/${slug}/`);
  if (res.status === 404) return null;
  const { post } = await res.json();
  return post;            // post.body_html is sanitised; render it as HTML
}
```

```python
# A static-site generator, or any Python caller
import requests

ORIGIN = "https://example.com"

def all_posts(blog: str) -> list[dict]:
    posts, page, pages = [], 1, 1
    while page <= pages:
        data = requests.get(f"{ORIGIN}/blog/api/blogs/{blog}/posts/", params={"page": page}, timeout=10).json()
        posts += data["posts"]
        page, pages = data["page"] + 1, data["pages"]
    return posts
```

What to expect from the API:

- **Visibility is enforced the same way as the reader.** A private blog is a
  `404` (its existence is not public). A members blog is a `404` to an
  anonymous caller — a JSON client cannot follow a login redirect — but a
  browser with a signed-in session gets it, so a same-origin front end for a
  team blog works without tokens.
- **Drafts and scheduled posts never appear**, for anyone, including the
  author. This API is the anonymous read surface; authors see drafts in the
  studio and the console.
- **Responses carry `Cache-Control: public, max-age=60`.** A CDN or browser may
  serve a post for up to a minute after an edit.
- **Cross-origin browsers need CORS.** Set `CORS_ALLOWED_ORIGINS` in `.env`
  (comma-separated) to the front end's origins; server-to-server callers need
  nothing.
- **Switching the public surface off** (`SMALLSTACK_BLOG_PUBLIC_ENABLED=False`)
  makes every route here a `404`, the HTML pages included. Drafting
  internally with nothing public yet is a supported state.
- **Permalinks survive renames** via `/blog/p/<uid>/`, which redirects to the
  current `url`. Store `uid` if you cache posts on your side.

Do not point a public front end at `/smallstack/api/blog/posts/`. That is the
authenticated **write** API; it answers `401` to anonymous requests and, with
a token, returns only what that token's owner may edit.

## Publishing from your own code

Three ways in, in order of preference.

**Python, inside the project** — the service layer is the only write path the
blog itself uses, so going through it gets the same slug generation, HTML
rendering, excerpt derivation, search indexing and webhook events as the
studio:

```python
from apps.blog import service
from apps.blog.models import Blog

blog = Blog.objects.get(slug="field-notes")
post = service.create_post(
    blog,
    title="Release notes, October",
    body_markdown=markdown_text,
    tags=["release"],
    author=request.user,
    actor=request.user,          # permission-checked; None means a trusted internal caller
)
service.publish_post(post, actor=request.user)                 # now
service.schedule_post(post, when=aware_datetime, actor=request.user)  # or later
```

`update_post` refuses `status` and the timestamps; publishing, scheduling,
unpublishing and archiving are explicit calls so nothing goes live by
accident. A runbook document can be published with
`service.publish_document(document, blog, sync="auto")` — see
[Publishing runbook pages](publishing-runbook-pages.md).

**REST, from outside** — mint a token under **API Tokens**, then:

```
POST /smallstack/api/blog/posts/
Authorization: Bearer <token>
{"blog": 1, "title": "…", "body_markdown": "…"}
```

This creates a draft. Publishing is not a field you can `PATCH`; a human
publishes in the studio, or an agent calls the MCP tool below.

**MCP, from an AI client** — `blog_draft_post` (markdown + tag names),
`blog_publish_post`, `blog_unpublish_post`, `blog_publish_runbook_document`.
Each sees exactly what the token's owner may see.

## Keeping your pages fresh

If your front end caches or pre-renders, subscribe a webhook endpoint under
**Webhooks** to `smallstack_blog.post.created`, `.updated` and `.deleted` and
rebuild the affected page on delivery. On `created` and `updated` the
envelope's `data` is the post as the REST API serialises it (`id`, `uid`,
`slug`, `blog`, `status`, `published_at`, …), so a static site can rebuild one
page rather than all of them; a `deleted` event carries only `id`, so key
your cache by `id` as well as `uid`. There is no event for a post merely *becoming* live at its scheduled
time without an edit, so a site that shows scheduled posts promptly should also
re-fetch on a short timer, or simply rely on the API's one-minute cache.

## Gotchas

| Symptom | Cause |
|---|---|
| A post shows on your page but not on `/blog/` | You filtered on `status="published"` yourself and included a scheduled post. Use `viewable_posts` / `public_posts` |
| Anonymous visitors see a members blog's posts on your page | The queryset was built once (module level, or cached) for a signed-in user and reused. Call `viewable_posts(request.user)` per request, or cache only `public_posts()` |
| `cover.url` is broken on the front end | It is site-relative; prefix the origin. In production, media must be served (see **Deployment**) |
| The JSON API returns `404` for a blog you can open in the browser | It is a members blog and your fetch has no session cookie. Use same-origin requests with credentials, or make the blog public |
| Every blog route is `404` | `SMALLSTACK_BLOG_PUBLIC_ENABLED` is off |
| `{% url 'blog:post_detail' … %}` raises `NoReverseMatch` | `SMALLSTACK_BLOG_ENABLED` is off, so the public URLs are not mounted. Use `post.public_url`, which returns `""` instead of raising |
