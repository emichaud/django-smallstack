"""Feeds — site-wide and per-blog, RSS / Atom / JSON Feed.

The blog is the reference publisher for ``apps.feeds``. (The framework's
one-flag ``enable_rss`` model feed was removed in 0.25.1 precisely because it
could not do what a blog needs: it published ``model.objects.all()`` with no
visibility hook, so it would have syndicated every draft from every blog.)

Both feeds here are built from ``permissions`` scopers and rendered
through the framework's own renderer (``apps.feeds.render.render_feed``), so
there is one XML code path and one definition of "visible".

Two kinds, because they have different lifetimes:

* **Site-wide** (``/feed/blog.rss``) — one fixed slug, so it registers into
  ``apps.feeds`` at startup like any other curated feed.
* **Per-blog** (``/blog/<slug>/feed.rss``) — blogs are created at runtime and
  the registry is a static slug→feed map populated in ``ready()``, so these are
  constructed per request and handed to the same renderer.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.feedgenerator import Enclosure

from apps.feeds.base import Feed, FeedItem
from apps.search.access import SearchAccess

from . import permissions
from .models import Blog, Post


def _feed_limit() -> int:
    return int(getattr(settings, "SMALLSTACK_BLOG_FEED_LIMIT", 25))


def _author_name(post: Post) -> str:
    if not post.author_id or post.author is None:
        return ""
    return post.author.get_full_name() or post.author.get_username()


def _enclosure_kwargs(post: Post) -> dict[str, Any]:
    """Attach the cover image as an ``<enclosure>`` when there is one.

    This is ``apps.feeds``' documented extension seam. Plural ``enclosures=``
    is the Django 6 spelling.
    """
    if not post.cover_image:
        return {}
    try:
        return {
            "enclosures": [
                Enclosure(
                    url=post.cover_image.url,
                    length=str(getattr(post.cover_image, "size", 0) or 0),
                    mime_type="image/*",
                )
            ]
        }
    except Exception:  # noqa: BLE001 — a missing file must not break the feed
        return {}


def _item_for(post: Post) -> FeedItem:
    return FeedItem(
        title=post.title,
        link=post.get_absolute_url(),
        # Derived from `uid`, not `pk`: a GUID has to stay stable across a
        # database restore or a copy between environments, or every reader
        # re-shows every post as new.
        unique_id=f"smallstack_blog.Post:{post.uid}",
        description=post.excerpt or "",
        pubdate=post.published_at,
        updateddate=post.updated_at,
        author_name=_author_name(post),
        categories=tuple(t.name for t in post.tags.all()),
        extra_kwargs=_enclosure_kwargs(post),
    )


def _published(qs: Any, limit: int) -> list[Post]:
    return list(
        qs.select_related("blog", "author")
        .prefetch_related("tags")
        .order_by("-published_at", "-id")[:limit]
    )


# ---------------------------------------------------------------------------
# Site-wide feed — registered into apps.feeds at startup
# ---------------------------------------------------------------------------


class LatestPostsFeed(Feed):
    """``/feed/blog.rss`` — the newest posts across every public blog."""

    slug = "blog"
    access = SearchAccess.ANONYMOUS
    link = "/blog/"

    def __init__(self) -> None:
        brand = getattr(settings, "BRAND_NAME", "SmallStack")
        self.title = f"{brand} — Blog"
        self.description = "Latest posts across all public blogs."
        self.limit = _feed_limit()

    def items(self, request: HttpRequest) -> Iterable[FeedItem]:
        # public_posts() is the single definition of "on the internet", shared
        # with the views, the per-blog feeds and the sitemap.
        return [_item_for(p) for p in _published(permissions.public_posts(), self.limit)]


class BlogFeed(Feed):
    """One blog's feed. Constructed per request — see the module docstring."""

    def __init__(self, blog: Blog, *, user: Any = None) -> None:
        self.blog = blog
        self.user = user
        self.slug = f"blog-{blog.slug}"
        self.title = blog.name
        self.description = blog.tagline or blog.description or blog.name
        self.link = blog.get_absolute_url()
        self.access = blog.required_access
        self.limit = _feed_limit()

    def items(self, request: HttpRequest) -> Iterable[FeedItem]:
        qs = permissions.viewable_posts(
            getattr(request, "user", None), Post.objects.filter(blog=self.blog)
        ).filter(status=Post.Status.PUBLISHED, published_at__lte=timezone.now())
        return [_item_for(p) for p in _published(qs, self.limit)]


# ---------------------------------------------------------------------------
# JSON Feed 1.1 — cheap, and several modern readers prefer it
# ---------------------------------------------------------------------------


def render_json_feed(feed: Feed, request: HttpRequest) -> HttpResponse:
    """Serialize a :class:`Feed` as JSON Feed 1.1.

    Reuses the same ``items()`` the XML path uses, so the three formats cannot
    drift apart.
    """
    payload = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": feed.title,
        "home_page_url": request.build_absolute_uri(feed.link),
        "feed_url": request.build_absolute_uri(request.path),
        "description": feed.channel_description(),
        "language": getattr(feed, "language", "en"),
        "items": [
            {
                "id": item.unique_id,
                "url": request.build_absolute_uri(item.link),
                "title": item.title,
                "summary": item.description,
                "date_published": item.pubdate.isoformat() if item.pubdate else None,
                "date_modified": item.updateddate.isoformat() if item.updateddate else None,
                "authors": ([{"name": item.author_name}] if item.author_name else []),
                "tags": list(item.categories),
            }
            for item in feed.items(request)
        ],
    }
    response = HttpResponse(
        json.dumps(payload, indent=2), content_type="application/feed+json; charset=utf-8"
    )
    response["Cache-Control"] = "public, max-age=300"
    return response


# ---------------------------------------------------------------------------
# The per-blog feed view
# ---------------------------------------------------------------------------


def blog_feed_view(request: HttpRequest, blog_slug: str, fmt: str = "rss") -> HttpResponse:
    """``/blog/<slug>/feed.(rss|atom|json)``.

    Note the explicit ``SMALLSTACK_FEEDS_ENABLED`` check: that switch is
    enforced inside ``apps.feeds.views.feed_view``, not inside the renderer, so
    a feed served from anywhere else has to honour it itself or the master
    switch silently misses half the feeds in the project.
    """
    from apps.feeds.render import render_feed

    from .public_views import _MembersOnly, _visible_blog, public_surface_enabled

    if not public_surface_enabled():
        raise Http404("The public blog is disabled.")
    if not getattr(settings, "SMALLSTACK_FEEDS_ENABLED", True):
        raise Http404("Feeds are disabled.")

    try:
        blog = _visible_blog(request, blog_slug)
    except _MembersOnly:
        # A feed reader cannot follow a login redirect, so answer the way the
        # framework's own gated feeds do: 401 with a WWW-Authenticate challenge
        # (apps/feeds/views.py), which lets a reader retry with a token.
        response = HttpResponse("Authentication required", status=401)
        response["WWW-Authenticate"] = 'Bearer realm="blog"'
        return response

    feed = BlogFeed(blog, user=getattr(request, "user", None))
    if fmt == "json":
        return render_json_feed(feed, request)

    xml, content_type = render_feed(feed, request, "atom" if fmt == "atom" else "rss")
    response = HttpResponse(xml, content_type=content_type)
    response["Cache-Control"] = "public, max-age=300"
    return response


def site_feed_json(request: HttpRequest) -> HttpResponse:
    """``/blog/feed.json`` — the site-wide river as JSON Feed."""
    from .public_views import public_surface_enabled

    if not public_surface_enabled():
        raise Http404("The public blog is disabled.")
    if not getattr(settings, "SMALLSTACK_FEEDS_ENABLED", True):
        raise Http404("Feeds are disabled.")
    return render_json_feed(LatestPostsFeed(), request)
