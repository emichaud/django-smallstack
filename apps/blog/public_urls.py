"""Public blog URLs, mounted at ``/blog/`` in config/urls.py.

Namespaced (``app_name = "blog"``) so these names cannot collide with the
console's bare CRUDView route names.

**Order matters.** ``/<blog>/<post>/`` is a catch-all under the blog slug, so
every sibling route has to be declared before it — and ``Post.slug`` rejects
the reserved words (`feed`, `tag`, `archive`, `search`, `subscribe`, …) so an
author cannot create a post that shadows one.
"""

from __future__ import annotations

from django.urls import path, register_converter

from . import feeds
from . import public_views as views
from . import subscribe_views as subs


class FeedFormatConverter:
    """Matches the ``rss`` / ``atom`` / ``json`` suffix, mirroring apps/feeds."""

    regex = "rss|atom|json"

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: str) -> str:
        return value


register_converter(FeedFormatConverter, "blogfeedfmt")

app_name = "blog"

urlpatterns = [
    # Site-wide
    path("", views.BlogIndexView.as_view(), name="index"),
    path("p/<uuid:uid>/", views.post_shortlink, name="post_shortlink"),
    # Public JSON read API (anonymous; the console REST is the write surface)
    path("api/blogs/", views.api_blogs, name="api_blogs"),
    path("api/blogs/<slug:blog_slug>/posts/", views.api_posts, name="api_posts"),
    path(
        "api/blogs/<slug:blog_slug>/posts/<slug:post_slug>/",
        views.api_post,
        name="api_post",
    ),
    path("api/blogs/<slug:blog_slug>/tags/", views.api_tags, name="api_tags"),
    path("feed.json", feeds.site_feed_json, name="site_feed_json"),
    # Subscriber lifecycle. Confirm and unsubscribe are site-wide (the token
    # carries the blog) so a link stays valid even if a blog is renamed.
    path("subscribe/confirm/<str:token>/", subs.confirm, name="confirm"),
    path("unsubscribe/<str:token>/", subs.unsubscribe, name="unsubscribe"),
    # Per-blog pages — all before the post catch-all.
    path("<slug:blog_slug>/", views.BlogDetailView.as_view(), name="blog_detail"),
    path("<slug:blog_slug>/feed.<blogfeedfmt:fmt>", feeds.blog_feed_view, name="feed"),
    path("<slug:blog_slug>/archive/", views.ArchiveView.as_view(), name="archive"),
    path("<slug:blog_slug>/search/", views.BlogSearchView.as_view(), name="search"),
    path("<slug:blog_slug>/tag/<slug:tag_slug>/", views.TagView.as_view(), name="tag"),
    path("<slug:blog_slug>/subscribe/", subs.subscribe, name="subscribe"),
    path("<slug:blog_slug>/newsletter/", subs.newsletter_archive, name="newsletter"),
    path(
        "<slug:blog_slug>/newsletter/<uuid:issue_uid>/",
        subs.newsletter_issue,
        name="newsletter_issue",
    ),
    # The catch-all permalink. Keep last.
    path(
        "<slug:blog_slug>/<slug:post_slug>/",
        views.PostDetailView.as_view(),
        name="post_detail",
    ),
]
