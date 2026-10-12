"""The anonymous reading surface at ``/blog/``.

Hand-rolled CBVs rather than a ``public = True`` CRUDView, for three
independent reasons found in the code:

1. ``CRUDView.get_urls()`` emits only ``{url_base}/`` and ``{url_base}/<pk>/``
   — single-segment and pk-only — so it cannot serve
   ``/blog/<blog-slug>/<post-slug>/``.
2. Its templates extend ``smallstack/base.html``, the operator console shell.
3. ``public = True`` does **not** make the generated REST endpoints anonymous
   (``apps/smallstack/api.py`` authenticates every one of them), so it would
   not deliver the machine-readable half either.

So this module follows the ``/status/`` pattern instead: a settings master
switch, a gate mixin that raises **404** (a disabled feature should look
absent, not forbidden), standalone templates, per-row opt-in through
``Blog.visibility`` + ``Post.status``, and a machine-readable sibling behind
the same gate.

Every queryset here goes through :mod:`apps.blog.permissions`. The highest
severity bug this surface can have is a draft or a private blog leaking, and
the defence is that there is exactly one definition of "on the internet"
(``permissions.public_posts``) rather than a filter re-typed per view.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import View

from . import permissions
from .models import Blog, Post, Tag

# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def public_surface_enabled() -> bool:
    """Whether anonymous blog reading is served at all.

    **Both** switches, not just the public one. ``SMALLSTACK_BLOG_ENABLED`` is
    documented as the master switch — *"Off ⇒ no nav, no console routes, no
    public routes, no feeds, no scheduled ticks"* — but it was only ever honoured
    in ``apps.py:ready()``. ``config/urls.py`` mounts ``public_urls``
    unconditionally and gates per-view through here, so with the master switch
    off the console and the nav disappeared while ``/blog/<blog>/<post>/`` and
    the anonymous JSON API kept serving posts. An operator taking the feature
    offline was told it was gone and it was not.

    One function is the right place for it: the view mixin, the JSON API's
    ``_require_public_surface``, the per-blog feed view and ``/blog/feed.json``
    all funnel through here, so they all now honour both flags.
    """
    if not getattr(settings, "SMALLSTACK_BLOG_ENABLED", True):
        return False
    return bool(getattr(settings, "SMALLSTACK_BLOG_PUBLIC_ENABLED", True))


class PublicBlogGateMixin:
    """404 every public blog view when the surface is switched off.

    Gated at the view rather than the URLConf so that every route pointing
    here is covered and `{% url %}` references elsewhere keep resolving — they
    just render a 404 instead of raising ``NoReverseMatch`` mid-template.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not public_surface_enabled():
            raise Http404("The public blog is disabled.")
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class _MembersOnly(Exception):
    """This visitor must sign in before we will say anything about this slug.

    Deliberately not a 404. A members blog exists so a team can share its URL
    internally; answering "no such page" to a colleague who simply is not
    signed in yet makes that workflow baffling. Its *contents* stay hidden
    either way.

    ``blog`` is ``None`` when the slug does not exist at all — see
    :func:`_visible_blog` for why that case ends up here too.
    """

    def __init__(self, blog: Blog | None = None) -> None:
        self.blog = blog


def _visible_blog(request: HttpRequest, slug: str) -> Blog:
    """Fetch a blog this visitor may read, or raise.

    404 for private blogs (existence is not public information),
    ``_MembersOnly`` for the signed-in tier.

    **To an anonymous visitor, a slug that does not exist answers exactly like
    a members blog.** Otherwise the login redirect is an existence oracle: a
    members blog answered 302 while an unused slug answered 404, so anyone
    could enumerate internal blog names without an account. Keeping the
    redirect (rather than 404ing members blogs) preserves the workflow this
    tier exists for; making the *absent* case answer identically is what closes
    the leak.

    A signed-in visitor still gets an honest 404 for a slug that is not there —
    the ambiguity is confined to the only audience it protects against.
    """
    blog = Blog.objects.select_related("owner").filter(slug=slug).first()
    if blog is None:
        if not request.user.is_authenticated:
            raise _MembersOnly(None)
        raise Http404("No such blog.")
    if permissions.can_view(request.user, blog):
        return blog
    if blog.visibility == Blog.Visibility.MEMBERS and not request.user.is_authenticated:
        raise _MembersOnly(blog)
    raise Http404("No such blog.")


class _BlogScopedView(PublicBlogGateMixin, View):
    """Base for the per-blog pages: resolves the blog and handles the
    members-tier login redirect in one place."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            return super().dispatch(request, *args, **kwargs)
        except _MembersOnly:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())

    def get_blog(self, request: HttpRequest, blog_slug: str) -> Blog:
        return _visible_blog(request, blog_slug)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _page_size() -> int:
    return int(getattr(settings, "SMALLSTACK_BLOG_PAGE_SIZE", 10))


def _readable_posts(request: HttpRequest, blog: Blog) -> QuerySet[Post]:
    """Posts of ``blog`` this visitor may read.

    ``viewable_posts`` is the same scoper the console, REST, MCP and search
    use, so an owner previewing her own draft and an anonymous reader seeing
    nothing are the same code path.
    """
    return (
        permissions.viewable_posts(request.user, Post.objects.filter(blog=blog))
        .select_related("blog", "author")
        .prefetch_related("tags")
    )


def _paginate(request: HttpRequest, qs: QuerySet, per_page: int | None = None) -> Any:
    paginator = Paginator(qs, per_page or _page_size())
    return paginator.get_page(request.GET.get("page"))


def _base_context(request: HttpRequest, **extra: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        # Shared partials branch on this, exactly as the status page does.
        "is_public_view": True,
        "color_palette": getattr(
            getattr(request.user, "profile", None), "color_palette", ""
        )
        or getattr(settings, "SMALLSTACK_COLOR_PALETTE", ""),
    }
    ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# HTML views
# ---------------------------------------------------------------------------


class BlogIndexView(PublicBlogGateMixin, View):
    """`/blog/` — every blog the visitor may read, plus a cross-blog river."""

    def get(self, request: HttpRequest) -> HttpResponse:
        blogs = (
            permissions.viewable_blogs(request.user)
            .annotate(
                post_count=Count(
                    "posts",
                    filter=permissions.live_post_filter("posts__"),
                    distinct=True,
                )
            )
            .select_related("owner")
            .order_by("name")
        )
        recent = (
            permissions.viewable_posts(request.user)
            .filter(status=Post.Status.PUBLISHED, published_at__lte=timezone.now())
            .select_related("blog", "author")
            .prefetch_related("tags")
            .order_by("-published_at", "-id")[: _page_size()]
        )
        return render(
            request,
            "blog/public/index.html",
            _base_context(request, blogs=blogs, recent_posts=recent),
        )


class BlogDetailView(_BlogScopedView):
    """`/blog/<blog>/` — one publication's reverse-chronological index."""

    def get(self, request: HttpRequest, blog_slug: str) -> HttpResponse:
        blog = self.get_blog(request, blog_slug)
        posts = _readable_posts(request, blog)
        tags = (
            Tag.objects.filter(blog=blog, posts__in=permissions.public_posts())
            .annotate(post_count=Count("posts", distinct=True))
            .order_by("name")
            .distinct()
        )
        return render(
            request,
            "blog/public/blog_detail.html",
            _base_context(
                request, blog=blog, page_obj=_paginate(request, posts), tags=tags
            ),
        )


class PostDetailView(_BlogScopedView):
    """`/blog/<blog>/<post>/` — the permalink.

    Registered **last** in the URLConf: it is a catch-all under the blog slug,
    which is also why ``Post.slug`` rejects the reserved words.
    """

    def get(self, request: HttpRequest, blog_slug: str, post_slug: str) -> HttpResponse:
        blog = self.get_blog(request, blog_slug)
        post = get_object_or_404(_readable_posts(request, blog), slug=post_slug)
        return render(
            request,
            "blog/public/post_detail.html",
            _base_context(
                request,
                blog=blog,
                post=post,
                # Owners and staff reach their own unpublished work here; the
                # banner makes it unmistakable that a reader sees nothing.
                is_draft_preview=not post.is_live,
                # The rail Runbook and Help both show. Only when there is enough
                # structure to navigate — a two-heading post gets no rail.
                show_toc=post.body_toc.count("<li>") >= 3,
            ),
        )


class TagView(_BlogScopedView):
    def get(self, request: HttpRequest, blog_slug: str, tag_slug: str) -> HttpResponse:
        blog = self.get_blog(request, blog_slug)
        tag = get_object_or_404(Tag, blog=blog, slug=tag_slug)
        posts = _readable_posts(request, blog).filter(tags=tag)
        return render(
            request,
            "blog/public/tag.html",
            _base_context(
                request, blog=blog, tag=tag, page_obj=_paginate(request, posts)
            ),
        )


class ArchiveView(_BlogScopedView):
    def get(self, request: HttpRequest, blog_slug: str) -> HttpResponse:
        from django.db.models.functions import TruncMonth

        blog = self.get_blog(request, blog_slug)
        posts = _readable_posts(request, blog).filter(published_at__isnull=False)
        # TruncMonth rather than .datetimes(): the two convert differently per
        # backend, and this one gives an identical result on SQLite and
        # Postgres.
        months = (
            posts.annotate(month=TruncMonth("published_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("-month")
        )
        return render(
            request,
            "blog/public/archive.html",
            _base_context(
                request, blog=blog, months=months, page_obj=_paginate(request, posts, 100)
            ),
        )


class BlogSearchView(_BlogScopedView):
    """Keyword search over one blog, via the framework's search registry.

    Anonymous search works because ``search_all`` is not itself login-gated,
    ``PostCRUDView.search_access`` is ANONYMOUS, and the registry applies
    ``search_visibility`` to anonymous callers too — so the FTS5 / Postgres-GIN
    ranking comes for free with the tenancy scope already enforced.
    """

    def get(self, request: HttpRequest, blog_slug: str) -> HttpResponse:
        blog = self.get_blog(request, blog_slug)
        query = (request.GET.get("q") or "").strip()
        posts: list[Post] = []
        if query:
            from apps.search.registry import search_all

            hits = search_all(query, user=request.user, limit_per_model=50)
            ids = [
                h.object_id
                for h in hits
                if getattr(h, "model_label", "") == "smallstack_blog.Post"
            ]
            if ids:
                found = {p.pk: p for p in _readable_posts(request, blog).filter(pk__in=ids)}
                # Preserve the engine's relevance order.
                posts = [found[i] for i in ids if i in found]
        return render(
            request,
            "blog/public/search.html",
            _base_context(request, blog=blog, query=query, posts=posts),
        )


# ---------------------------------------------------------------------------
# Public JSON API — the anonymous *read* surface
# ---------------------------------------------------------------------------
#
# Separate from the console REST at /smallstack/api/blog/*, which authenticates
# every request (apps/smallstack/api.py) and is the *write* surface. This one
# exists so a downstream project can build its own reader UI — a React front
# end, a static-site generator, another service — against published content
# without a token. Same gate, same scoper, no other logic.


def _serialize_post(post: Post, *, full: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "uid": str(post.uid),
        "slug": post.slug,
        "title": post.title,
        "excerpt": post.excerpt,
        "url": post.public_url,
        "canonical_url": post.canonical_url or None,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "updated_at": post.updated_at.isoformat(),
        "tags": [{"slug": t.slug, "name": t.name} for t in post.tags.all()],
        "author": post.author.get_username() if post.author is not None else None,
        "cover": (
            {"url": post.cover_image.url, "alt": post.cover_alt}
            if post.cover_image
            else None
        ),
    }
    if full:
        data["body_html"] = post.body_html
        data["body_markdown"] = post.body_markdown
    return data


def _json(payload: dict[str, Any]) -> JsonResponse:
    response = JsonResponse(payload)
    # Published content is cacheable; a minute keeps a popular post cheap
    # without making an edit feel stuck.
    response["Cache-Control"] = "public, max-age=60"
    return response


def _require_public_surface() -> None:
    if not public_surface_enabled():
        raise Http404("The public blog is disabled.")


def api_blogs(request: HttpRequest) -> JsonResponse:
    _require_public_surface()
    blogs = permissions.viewable_blogs(request.user).order_by("name")
    return _json(
        {
            "blogs": [
                {
                    "slug": b.slug,
                    "name": b.name,
                    "tagline": b.tagline,
                    "description": b.description,
                    "url": b.get_absolute_url(),
                    "feeds": {
                        "rss": f"/blog/{b.slug}/feed.rss",
                        "atom": f"/blog/{b.slug}/feed.atom",
                        "json": f"/blog/{b.slug}/feed.json",
                    },
                }
                for b in blogs
            ]
        }
    )


def api_posts(request: HttpRequest, blog_slug: str) -> JsonResponse:
    _require_public_surface()
    blog = _visible_blog_for_api(request, blog_slug)
    qs = _readable_posts(request, blog)
    tag = request.GET.get("tag")
    if tag:
        qs = qs.filter(tags__slug=tag)
    page = _paginate(request, qs)
    return _json(
        {
            "blog": {"slug": blog.slug, "name": blog.name},
            "count": page.paginator.count,
            "page": page.number,
            "pages": page.paginator.num_pages,
            "posts": [_serialize_post(p) for p in page.object_list],
        }
    )


def api_post(request: HttpRequest, blog_slug: str, post_slug: str) -> JsonResponse:
    _require_public_surface()
    blog = _visible_blog_for_api(request, blog_slug)
    post = get_object_or_404(_readable_posts(request, blog), slug=post_slug)
    return _json({"post": _serialize_post(post, full=True)})


def api_tags(request: HttpRequest, blog_slug: str) -> JsonResponse:
    _require_public_surface()
    blog = _visible_blog_for_api(request, blog_slug)
    tags = (
        Tag.objects.filter(blog=blog, posts__in=permissions.public_posts())
        .annotate(post_count=Count("posts", distinct=True))
        .order_by("name")
        .distinct()
    )
    return _json(
        {
            "tags": [
                {"slug": t.slug, "name": t.name, "count": t.post_count} for t in tags
            ]
        }
    )


def _visible_blog_for_api(request: HttpRequest, slug: str) -> Blog:
    """Like :func:`_visible_blog`, but a members blog 404s rather than
    redirecting — a JSON client has nowhere to follow a login redirect to."""
    try:
        return _visible_blog(request, slug)
    except _MembersOnly as exc:
        raise Http404("No such blog.") from exc


# ---------------------------------------------------------------------------
# Convenience redirect
# ---------------------------------------------------------------------------


def post_shortlink(request: HttpRequest, uid: str) -> HttpResponse:
    """`/blog/p/<uid>/` → the post's permalink.

    A stable link that survives a retitle, which is what you want in a
    newsletter or a chat message.
    """
    _require_public_surface()
    post = get_object_or_404(
        permissions.viewable_posts(request.user).select_related("blog"), uid=uid
    )
    return redirect(post.get_absolute_url())
