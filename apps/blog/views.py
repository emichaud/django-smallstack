"""The authoring console at ``/smallstack/blog/``.

**Login-gated, not staff-gated, and ownership-scoped** — the runbook
precedent. A blog belongs to a person, so the author of a blog must be able to
use the console without being an administrator of the whole installation.

The security model is one function. ``permissions.viewable_posts`` (and its
siblings) are applied in ``get_list_queryset``; ``get_detail_queryset``
defaults to it, so a row hidden from the list is also unreadable and
uneditable at its own URL, in the related-tab endpoint, in the field-preview
endpoint, in REST list *and* detail, and through every generated MCP tool. One
scoper, every read surface. Rows you may not see **404** rather than 403:
whether a neighbour has a blog called "launch" is not public information.

Lifecycle changes (publish, schedule, archive, queue a send) are POST actions
that call the service, never CRUD form fields — see ``forms.py`` for why.
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import format_html, strip_tags
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import StatsAccessory
from apps.smallstack.mixins import StaffRequiredMixin

from . import permissions, service
from .forms import BlogForm, IssueForm, PostForm, TagForm
from .models import Blog, Delivery, Issue, Post, Subscriber, Subscription, Tag

# ---------------------------------------------------------------------------
# Field transforms — semantic colour only, never a hex literal (6 palettes × 2
# themes have to all look right).
# ---------------------------------------------------------------------------

_POST_STATUS_COLORS = {
    Post.Status.PUBLISHED: "var(--success-fg)",
    Post.Status.SCHEDULED: "var(--warning-fg)",
    Post.Status.DRAFT: "var(--body-quiet-color)",
    Post.Status.ARCHIVED: "var(--body-quiet-color)",
}
_VISIBILITY_COLORS = {
    Blog.Visibility.PUBLIC: "var(--success-fg)",
    Blog.Visibility.MEMBERS: "var(--warning-fg)",
    Blog.Visibility.PRIVATE: "var(--body-quiet-color)",
}
_ISSUE_STATUS_COLORS = {
    "sent": "var(--success-fg)",
    "sending": "var(--warning-fg)",
    "queued": "var(--warning-fg)",
    "scheduled": "var(--warning-fg)",
    "failed": "var(--error-fg)",
    "canceled": "var(--body-quiet-color)",
    "draft": "var(--body-quiet-color)",
}
_SUB_STATUS_COLORS = {
    "confirmed": "var(--success-fg)",
    "pending": "var(--warning-fg)",
    "unsubscribed": "var(--body-quiet-color)",
}
_DELIVERY_STATUS_COLORS = {
    "sent": "var(--success-fg)",
    "pending": "var(--body-quiet-color)",
    "claimed": "var(--warning-fg)",
    "failed": "var(--error-fg)",
    "skipped": "var(--body-quiet-color)",
}


def _signed_in(request: HttpRequest) -> Any:
    """Narrow ``request.user`` to the concrete User our FKs store.

    Every path that reaches an owner/author assignment is behind
    ``LoginRequiredMixin``, so the user is authenticated — but mypy can't see
    that through a runtime-resolved mixin list, and the FK is typed
    ``User | None``, not ``AnonymousUser``.
    """
    return cast(Any, request.user)


def _badge(colors: dict, value: Any, label: str) -> Any:
    return format_html(
        '<span style="color: {}; font-weight: 600;">{}</span>',
        colors.get(value, "var(--body-quiet-color)"),
        label,
    )


def _post_status_badge(value: Any, obj: Post) -> Any:
    """Shows the *effective* state, not just the column.

    A row stored as `published` with a future `published_at` is an embargo, and
    a badge reading "Published" on something no reader can see is exactly the
    kind of lie that costs an author an afternoon.
    """
    if obj.status == Post.Status.PUBLISHED and not obj.is_live:
        return _badge(_POST_STATUS_COLORS, Post.Status.SCHEDULED, "Embargoed")
    return _badge(_POST_STATUS_COLORS, obj.status, obj.get_status_display())


def _visibility_badge(value: Any, obj: Blog) -> Any:
    return _badge(_VISIBILITY_COLORS, obj.visibility, obj.get_visibility_display().split(" —")[0])


def _issue_status_badge(value: Any, obj: Issue) -> Any:
    return _badge(_ISSUE_STATUS_COLORS, obj.status, obj.get_status_display())


def _sub_status_badge(value: Any, obj: Subscription) -> Any:
    return _badge(_SUB_STATUS_COLORS, obj.status, obj.get_status_display())


def _delivery_status_badge(value: Any, obj: Delivery) -> Any:
    return _badge(_DELIVERY_STATUS_COLORS, obj.status, obj.get_status_display())


# ---------------------------------------------------------------------------
# Shared CRUDView behaviour
# ---------------------------------------------------------------------------


def _is_write_surface(request: HttpRequest) -> bool:
    """Whether this request is on a surface that writes, or is about to.

    A method check alone is not enough. The read scope here is deliberately
    *wider* than the write scope — ``viewable_posts`` admits live posts from
    blogs you don't own so that search hits and shared links resolve — which
    means a GET of ``…/<pk>/edit/`` would otherwise render a populated edit
    form to someone whose eventual POST is refused. Offering a form that
    cannot be submitted is its own bug, so the edit and delete *routes* are
    treated as write surfaces whatever the method.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        return True
    return request.path.rstrip("/").rsplit("/", 1)[-1] in {"edit", "delete"}


class _ScopedFormMixin:
    """Inject ``request.user`` into the form so it can scope its own choices.

    ``CRUDView`` builds its form with no request context, which leaves a
    generated ``ModelChoiceField`` listing every row in the table. For the
    ``blog`` field that is a cross-tenant write, so the user has to reach the
    form somehow; ``_make_view`` is the documented seam for exactly this.
    """

    @classmethod
    def _make_view(cls, base_class: Any) -> Any:
        view = super()._make_view(base_class)  # type: ignore[misc]
        if hasattr(view, "get_form_kwargs"):
            inherited = view.get_form_kwargs

            def get_form_kwargs(self: Any) -> dict:
                kwargs = inherited(self)
                kwargs["user"] = getattr(self.request, "user", None)
                return kwargs

            view.get_form_kwargs = get_form_kwargs
        return view


class _OwnedCRUDView(_ScopedFormMixin, CRUDView):
    """Ownership scoping for every blog console view.

    Subclasses implement :meth:`scope`. ``get_detail_queryset`` inherits from
    ``get_list_queryset``, so one definition covers all five HTML surfaces plus
    REST plus MCP.
    """

    mixins = [LoginRequiredMixin]
    paginate_by = 25
    # No bulk actions anywhere in this app. BulkAction.UPDATE goes through
    # queryset.update(), which fires no post_save: cached HTML would go stale,
    # the search index would drift, and no webhook would fire. Lifecycle
    # changes belong to the service.
    bulk_actions: list = []

    @staticmethod
    def scope(qs: Any, user: Any) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        return cls.scope(qs, getattr(request, "user", None))

    @classmethod
    def _make_view(cls, base_class: Any) -> Any:
        """Publish ``can_edit_object`` to the template.

        The framework's ``crud_actions`` is the class's action list, not a
        per-object verdict, so a detail template cannot tell whether *this*
        viewer may write to *this* row. The read scope here is wider than the
        write scope, so without this a reader would be shown Publish and Edit
        buttons that 404 on click. Computing it from ``can_update`` keeps the
        rule in permissions.py instead of duplicating it in a template, where
        the two would drift.
        """
        view = super()._make_view(base_class)  # type: ignore[misc]
        inherited = view.get_context_data

        def get_context_data(self: Any, **kwargs: Any) -> dict:
            context = inherited(self, **kwargs)
            obj = context.get("object")
            editable = False
            if obj is not None:
                try:
                    editable = bool(cls.can_update(obj, self.request))
                except Exception:  # noqa: BLE001
                    editable = False
            context["can_edit_object"] = editable
            return context

        view.get_context_data = get_context_data
        return view


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------


class BlogCRUDView(_OwnedCRUDView):
    model = Blog
    form_class = BlogForm
    # `owner` is absent: it is stamped from the request on create, because a
    # form field would let one user assign a blog to somebody else.
    fields = [
        "name", "slug", "tagline", "description", "visibility",
        "newsletter_enabled", "newsletter_from_name", "newsletter_reply_to",
        "newsletter_footer_markdown", "double_opt_in", "email_template", "mailer_alias",
    ]
    list_fields = ["name", "slug", "visibility", "owner", "newsletter_enabled", "updated_at"]
    list_columns = ["name", "slug", "visibility", "newsletter_enabled", "updated_at"]
    detail_fields = [
        "name", "slug", "tagline", "description", "visibility", "owner",
        "newsletter_enabled", "newsletter_from_name", "newsletter_reply_to",
        "double_opt_in", "mailer_alias", "created_at", "updated_at",
    ]
    link_field = "name"
    url_base = "blog/blogs"
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    filter_fields = ["visibility", "newsletter_enabled"]
    search_fields = ["name", "slug", "description", "tagline"]
    ordering_fields = ["name", "slug", "visibility", "updated_at"]
    field_transforms = {
        "visibility": _visibility_badge,
        "description": "preview",
        "updated_at": "localtime",
        "created_at": "localtime",
    }
    related_tabs = ["posts", "tags", "issues", "subscriptions"]

    enable_search = True
    search_display = "name"
    search_subtitle = "tagline"
    # A blog's *name* is not public content the way a post is — the public
    # index at /blog/ is the discovery surface for anonymous visitors. Keeping
    # this at AUTHENTICATED means the global omnibar doesn't become a directory
    # of every publication on the installation.
    search_access = "authenticated"
    search_visibility = staticmethod(permissions.search_visible_blogs)

    enable_api = True
    api_extra_fields = ["owner", "created_at", "updated_at"]
    api_expand_fields = ["owner"]

    enable_mcp = True
    mcp_singular = "blog"
    mcp_plural = "blogs"
    mcp_description = (
        "a blog channel: owner, slug, visibility (private/members/public) and newsletter "
        "settings. Posts belong to a blog; the public URL is /blog/<slug>/."
    )

    enable_webhooks = True
    webhook_events = ["created", "updated"]

    # NOT enable_rss. apps/feeds/model_feed.py:139 queries
    # `model.objects.all()` and never calls get_list_queryset, so the flag
    # would publish private blogs to an anonymous feed. See apps/blog/feeds.py.
    enable_rss = False

    @staticmethod
    def scope(qs: Any, user: Any) -> Any:
        return permissions.viewable_blogs(user, qs).select_related("owner")

    @classmethod
    def can_update(cls, obj: Blog, request: HttpRequest) -> bool:
        return permissions.can_edit(request.user, obj)

    @classmethod
    def can_delete(cls, obj: Blog, request: HttpRequest) -> bool:
        return permissions.can_edit(request.user, obj)

    @classmethod
    def check_object_permission(cls, obj: Blog, request: HttpRequest) -> None:
        if not _is_write_surface(request):
            return
        if not permissions.can_edit(request.user, obj):
            raise Http404("No such blog.")

    @classmethod
    def on_form_valid(
        cls, request: HttpRequest, form: Any, obj: Blog, is_create: bool = False
    ) -> None:
        updates: list[str] = []
        if is_create and obj.owner_id is None:
            obj.owner = _signed_in(request)
            updates.append("owner")
        wanted = (form.cleaned_data.get("slug") or "").strip() or obj.name
        resolved = service.unique_blog_slug(wanted, exclude_pk=obj.pk)
        if resolved != obj.slug:
            obj.slug = resolved
            updates.append("slug")
        if updates:
            obj.save(update_fields=updates)


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------


WORDS_PER_MINUTE = 220


def search_hit_for_post(post: Post, variant: str = "default") -> dict[str, Any]:
    """The SearchBuilder payload for one post (see ``PostCRUDView.transform_hit``).

    Kept as a plain function so it is testable without instantiating the
    CRUDView, and so a downstream project that swaps the card template can
    reuse the data without re-deriving reading time or tag lists.
    """
    url = post.public_url
    if variant == "compact":
        return {"display": post.title, "url": url}
    words = len(strip_tags(post.body_html or post.body_markdown).split())
    cover_url = ""
    if post.cover_image:
        try:
            cover_url = post.cover_image.url
        except ValueError:  # no file attached to the field
            cover_url = ""
    return {
        "display": post.title,
        "subtitle": post.excerpt,
        "card": "article",
        "blog": post.blog.name,
        "blog_url": post.blog.get_absolute_url(),
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "reading_minutes": max(1, round(words / WORDS_PER_MINUTE)),
        "tags": list(post.tags.order_by("name").values_list("name", flat=True)),
        "cover_url": cover_url,
        "cover_alt": post.cover_alt,
        "is_featured": post.is_featured,
    }


class PostCRUDView(_OwnedCRUDView):
    model = Post
    form_class = PostForm
    fields = [
        "blog", "title", "slug", "body_markdown", "excerpt",
        "cover_image", "cover_alt", "canonical_url", "is_featured", "allow_newsletter",
    ]
    list_fields = [
        "title", "blog", "status", "author", "published_at", "is_featured", "updated_at",
    ]
    list_columns = ["title", "blog", "status", "published_at", "updated_at"]
    detail_fields = [
        "title", "blog", "slug", "status", "author", "excerpt", "body_markdown",
        "cover_image", "cover_alt", "canonical_url", "is_featured", "allow_newsletter",
        "published_at", "scheduled_for", "source_document", "source_version",
        "source_synced_at", "source_sync", "uid", "created_at", "updated_at",
    ]
    link_field = "title"
    url_base = "blog/posts"
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    filter_fields = ["blog", "status", "is_featured"]
    ordering_fields = ["title", "status", "published_at", "updated_at"]
    search_fields = ["title", "excerpt", "body_markdown"]
    export_formats = ["csv", "json"]
    column_widths = {"title": "34%", "status": "11%"}
    field_transforms = {
        "status": _post_status_badge,
        "body_markdown": "preview",
        "excerpt": "preview",
        "published_at": "localtime",
        "updated_at": "localtime",
        "created_at": "localtime",
        "source_synced_at": "localtime",
    }
    related_tabs = ["issues"]

    enable_search = True
    # Without this the search tool is named from the model's verbose name —
    # `search_posts`, a common noun in a namespace shared with every other
    # app and every downstream project. Same reasoning as the
    # `smallstack_blog` app label.
    mcp_tool_noun_plural = "blog_posts"
    search_display = "title"
    search_subtitle = "excerpt"
    search_weight = {"title": 4, "excerpt": 2, "body_markdown": 1}
    # Published posts in public blogs ARE public content — that is the point of
    # a blog. `search_visibility` is what makes this safe: it is the same
    # scoper the console and the public views use, so anonymous callers reach
    # exactly the public subset and nothing else.
    search_access = "anonymous"
    search_visibility = staticmethod(permissions.search_visible_posts)

    # ── SearchBuilder: a uniquely formatted search result ──────────────────
    # The framework's default hit is `display` + `subtitle` + `snippet`. A
    # published article deserves more than two lines: the blog it belongs
    # to, when it ran, how long it takes to read, its tags and its cover.
    # `transform_hit` returns those as extra keys; everything that is not
    # `display`/`subtitle` lands in `SearchHit.extra`, so the public search
    # page can render an article card for `extra.card == "article"` while
    # every other model keeps the standard row. The same dict reaches REST
    # (`/api/search/`), the omnibar and the MCP tool, so an agent sees the
    # reading time too. `get_search_variants` adds a `compact` shape, which
    # the MCP factory exposes as its own tool (`search_blog_posts_compact`)
    # for callers that only want a title and a permalink.
    def get_search_variants(self) -> dict[str, str]:
        return {
            "default": "Article card: blog, published date, reading time, tags, cover image",
            "compact": "Title and permalink only — the cheapest shape for agents",
        }

    def transform_hit(self, obj: Post, variant: str = "default") -> dict[str, Any]:
        return search_hit_for_post(obj, variant)

    enable_api = True
    api_extra_fields = [
        "uid", "status", "published_at", "scheduled_for", "author",
        "source_document", "source_version", "source_synced_at",
        "created_at", "updated_at",
    ]
    api_expand_fields = ["blog", "author"]

    enable_mcp = True
    mcp_singular = "blog_post"
    mcp_plural = "blog_posts"
    mcp_description = (
        "a blog post. status: draft/scheduled/published/archived. body_markdown is the "
        "source of truth; body_html is rendered from it. Create a draft here, then call "
        "blog_publish_post to publish — a CRUD update cannot change status."
    )

    enable_webhooks = True
    webhook_events = ["created", "updated", "deleted"]

    enable_rss = False  # see BlogCRUDView.enable_rss

    list_accessories = [
        StatsAccessory(
            stats=[
                {
                    "label": "Published",
                    "value": lambda qs: qs.filter(
                        status=Post.Status.PUBLISHED, published_at__lte=timezone.now()
                    ).count(),
                    "color": "var(--success-fg)",
                },
                {
                    "label": "Scheduled",
                    "value": lambda qs: qs.filter(status=Post.Status.SCHEDULED).count(),
                    "color": "var(--warning-fg)",
                },
                {
                    "label": "Drafts",
                    "value": lambda qs: qs.filter(status=Post.Status.DRAFT).count(),
                    "color": "var(--body-quiet-color)",
                },
            ]
        )
    ]

    @staticmethod
    def scope(qs: Any, user: Any) -> Any:
        return permissions.viewable_posts(user, qs).select_related("blog", "author")

    @classmethod
    def apply_filter(cls, qs: Any, field_name: str, value: Any, request: HttpRequest) -> Any:
        if field_name == "tag":
            return qs.filter(tags__slug=value)
        return NotImplemented

    @classmethod
    def can_update(cls, obj: Post, request: HttpRequest) -> bool:
        return permissions.can_edit_post(request.user, obj)

    @classmethod
    def can_delete(cls, obj: Post, request: HttpRequest) -> bool:
        return permissions.can_edit_post(request.user, obj)

    @classmethod
    def check_object_permission(cls, obj: Post, request: HttpRequest) -> None:
        """A reader may *view* a live post here but must never write to it.

        `viewable_posts` admits live posts from blogs the user doesn't own (so
        search hits and shared links resolve), which means the read scope is
        deliberately wider than the write scope. 404, not 403 — consistent with
        the rest of the console.
        """
        if not _is_write_surface(request):
            return
        if not permissions.can_edit_post(request.user, obj):
            raise Http404("No such post.")

    @classmethod
    def on_form_valid(
        cls, request: HttpRequest, form: Any, obj: Post, is_create: bool = False
    ) -> None:
        if is_create and obj.author_id is None:
            obj.author = _signed_in(request)
        wanted = (form.cleaned_data.get("slug") or "").strip() or obj.title
        obj.slug = service.unique_slug(obj.blog, wanted, exclude_pk=obj.pk)
        # Render through the service so the console, REST, MCP and the CLI all
        # produce byte-identical HTML from the same markdown.
        service.render_body(obj)
        obj.save()
        if "tag_names" in getattr(form, "cleaned_data", {}):
            service.set_post_tags(obj, form.cleaned_data["tag_names"], actor=None)


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------


class TagCRUDView(_OwnedCRUDView):
    model = Tag
    form_class = TagForm
    fields = ["blog", "name", "slug", "description"]
    list_fields = ["name", "blog", "slug", "description"]
    list_columns = ["name", "blog", "slug"]
    detail_fields = ["name", "blog", "slug", "description", "created_at"]
    link_field = "name"
    url_base = "blog/tags"
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    filter_fields = ["blog"]
    search_fields = ["name", "slug"]
    field_transforms = {"description": "preview", "created_at": "localtime"}

    enable_api = True
    api_expand_fields = ["blog"]
    # Tag CRUD is noise in a tool list and in the global omnibar; set_post_tags
    # does the work an agent actually wants.
    enable_mcp = False
    enable_search = False
    enable_webhooks = False
    enable_rss = False

    @staticmethod
    def scope(qs: Any, user: Any) -> Any:
        return permissions.viewable_tags(user, qs).select_related("blog")

    @classmethod
    def can_update(cls, obj: Tag, request: HttpRequest) -> bool:
        return permissions.can_edit(request.user, obj.blog)

    can_delete = can_update

    @classmethod
    def check_object_permission(cls, obj: Tag, request: HttpRequest) -> None:
        if not _is_write_surface(request):
            return
        if not permissions.can_edit(request.user, obj.blog):
            raise Http404("No such tag.")

    @classmethod
    def on_form_valid(
        cls, request: HttpRequest, form: Any, obj: Tag, is_create: bool = False
    ) -> None:
        wanted = (form.cleaned_data.get("slug") or "").strip() or obj.name
        resolved = service.unique_slug(obj.blog, wanted, kind="tag", exclude_pk=obj.pk)
        if resolved != obj.slug:
            obj.slug = resolved
            obj.save(update_fields=["slug"])


# ---------------------------------------------------------------------------
# Newsletter — Subscription (the owner's audience) and Subscriber (staff)
# ---------------------------------------------------------------------------


class SubscriptionCRUDView(_OwnedCRUDView):
    """A blog owner's audience list.

    Read-only: subscribing is a double-opt-in flow, not a form an owner fills
    in on someone's behalf. Scoped by *editable* blogs, not viewable ones — a
    members-visibility blog is readable by every colleague and its subscriber
    list is not.
    """

    model = Subscription
    fields: list = []
    list_fields = ["subscriber", "blog", "status", "source", "confirmed_at", "created_at"]
    detail_fields = [
        "subscriber", "blog", "status", "source", "consent_note",
        "confirmed_at", "unsubscribed_at", "created_at",
    ]
    link_field = "subscriber"
    url_base = "blog/subscriptions"
    actions = [Action.LIST, Action.DETAIL]
    filter_fields = ["blog", "status", "source"]
    search_fields = ["subscriber__email", "subscriber__name"]
    export_formats = ["csv"]
    field_transforms = {
        "status": _sub_status_badge,
        "confirmed_at": "localtime",
        "created_at": "localtime",
    }

    enable_api = True
    api_expand_fields = ["subscriber", "blog"]
    # Deliberately NOT exposed to MCP, and not searchable. An MCP tool that
    # pages subscriber email addresses into an LLM client is a data
    # exfiltration surface, not a feature; likewise addresses in the omnibar.
    enable_mcp = False
    enable_search = False
    enable_rss = False
    # The CRM-sync seam. Endpoints are staff-configured, so this is opt-in by
    # the operator rather than ambient.
    enable_webhooks = True
    webhook_events = ["created", "updated"]

    @staticmethod
    def scope(qs: Any, user: Any) -> Any:
        return permissions.owned_subscriptions(user, qs).select_related("subscriber", "blog")


class SubscriberCRUDView(CRUDView):
    """**Staff only.**

    A Subscriber row aggregates across every blog an address subscribes to, so
    showing it to a blog owner would reveal which of her neighbours' lists her
    readers are also on. Owners get ``Subscription`` (scoped to their blogs);
    staff get the identity, because suppression is a site-wide ops concern.
    """

    model = Subscriber
    fields = ["name", "is_suppressed", "suppression_reason"]
    list_fields = [
        "email", "name", "is_suppressed", "bounce_count", "consecutive_failures", "created_at",
    ]
    detail_fields = [
        "email", "name", "user", "is_suppressed", "suppressed_at", "suppression_reason",
        "bounce_count", "consecutive_failures", "last_failure_at", "created_at",
    ]
    link_field = "email"
    url_base = "blog/subscribers"
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL, Action.UPDATE]
    filter_fields = ["is_suppressed"]
    search_fields = ["email", "name"]
    paginate_by = 50
    field_transforms = {"created_at": "localtime", "last_failure_at": "localtime"}
    bulk_actions: list = []

    enable_api = True
    enable_mcp = False
    enable_search = False
    enable_webhooks = False
    enable_rss = False


# ---------------------------------------------------------------------------
# Newsletter — Issue, Delivery
# ---------------------------------------------------------------------------


class IssueCRUDView(_OwnedCRUDView):
    model = Issue
    form_class = IssueForm
    fields = ["blog", "post", "subject", "preheader", "body_markdown"]
    list_fields = [
        "subject", "blog", "status", "recipient_count", "sent_count",
        "failed_count", "scheduled_for", "finished_at",
    ]
    list_columns = ["subject", "blog", "status", "recipient_count", "sent_count", "finished_at"]
    detail_fields = [
        "subject", "blog", "post", "preheader", "body_markdown", "status",
        "scheduled_for", "queued_at", "started_at", "finished_at",
        "recipient_count", "sent_count", "failed_count", "created_by", "uid", "created_at",
    ]
    link_field = "subject"
    url_base = "blog/issues"
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    filter_fields = ["blog", "status"]
    search_fields = ["subject", "body_markdown"]
    field_transforms = {
        "status": _issue_status_badge,
        "body_markdown": "preview",
        "finished_at": "localtime",
        "scheduled_for": "localtime",
        "created_at": "localtime",
    }
    related_tabs = ["deliveries"]

    enable_api = True
    api_extra_fields = [
        "uid", "status", "queued_at", "started_at", "finished_at",
        "recipient_count", "sent_count", "failed_count", "created_at",
    ]
    api_expand_fields = ["blog", "post"]

    enable_mcp = True
    mcp_singular = "newsletter_issue"
    mcp_plural = "newsletter_issues"
    mcp_description = (
        "a newsletter issue: one send of a blog's newsletter, optionally built from a post. "
        "status: draft/scheduled/queued/sending/sent/failed/canceled. Drafting is allowed "
        "here; SENDING is not exposed as a tool — a blast to thousands of real people is a "
        "deliberate human action."
    )
    # No delete, and no send tool. Queueing a blast is not a tool call.
    mcp_actions = [Action.LIST, Action.DETAIL, Action.CREATE, Action.UPDATE]

    enable_search = False
    enable_rss = False
    enable_webhooks = True
    webhook_events = ["updated"]  # status → sent is the downstream signal

    @staticmethod
    def scope(qs: Any, user: Any) -> Any:
        return permissions.owned_issues(user, qs).select_related("blog", "post")

    @classmethod
    def check_object_permission(cls, obj: Issue, request: HttpRequest) -> None:
        """A sent issue is a record of what went out — it must never be edited.

        403 with a message here, not 404: the row's existence is not a secret
        from someone who can already see it, and "you can't edit a sent issue"
        is genuinely useful to read.
        """
        if not _is_write_surface(request):
            return
        if not permissions.can_edit(request.user, obj.blog):
            raise Http404("No such issue.")
        if not obj.is_editable:
            raise PermissionDenied(
                "This issue has already been queued or sent and is now a permanent record."
            )

    @classmethod
    def on_form_valid(
        cls, request: HttpRequest, form: Any, obj: Issue, is_create: bool = False
    ) -> None:
        if is_create and obj.created_by_id is None:
            obj.created_by = _signed_in(request)
            obj.save(update_fields=["created_by"])


class DeliveryCRUDView(_OwnedCRUDView):
    """The per-recipient send ledger. Read-only — the pipeline owns these rows."""

    model = Delivery
    fields: list = []
    list_fields = ["email", "issue", "status", "attempts", "sent_at", "last_error"]
    list_columns = ["email", "issue", "status", "attempts", "sent_at"]
    detail_fields = [
        "email", "issue", "subscriber", "status", "attempts",
        "claimed_at", "sent_at", "last_error",
    ]
    link_field = "email"
    url_base = "blog/deliveries"
    actions = [Action.LIST, Action.DETAIL]
    filter_fields = ["issue", "status"]
    search_fields = ["email"]
    paginate_by = 50
    field_transforms = {
        "status": _delivery_status_badge,
        "last_error": "preview",
        "sent_at": "localtime",
        "claimed_at": "localtime",
    }

    enable_api = True
    enable_mcp = False
    enable_search = False
    enable_rss = False
    # One row per recipient per issue: a 5,000-recipient send would emit 10,000+
    # webhook deliveries and drown any endpoint subscribed to it. Subscribe to
    # smallstack_blog.issue.updated instead.
    enable_webhooks = False

    @staticmethod
    def scope(qs: Any, user: Any) -> Any:
        return permissions.owned_deliveries(user, qs).select_related("issue", "issue__blog")


# ---------------------------------------------------------------------------
# Lifecycle actions (POST only)
# ---------------------------------------------------------------------------


def _safe_next(request: HttpRequest, fallback: str) -> str:
    """An internal redirect target, or the fallback. Never an open redirect."""
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return fallback


def _editable_post_or_404(request: HttpRequest, pk: int) -> Post:
    """Fetch a post this user may edit, 404ing otherwise.

    Goes through the *editable* scope, not the viewable one: a reader can see a
    live post in the console and must not be able to POST an action against it.
    """
    post = get_object_or_404(Post.objects.select_related("blog"), pk=pk)
    if not permissions.can_edit_post(request.user, post):
        raise Http404("No such post.")
    return post


@login_required
@require_POST
def post_publish(request: HttpRequest, pk: int) -> HttpResponse:
    post = _editable_post_or_404(request, pk)
    try:
        service.publish_post(post, actor=request.user)
    except service.BlogServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"“{post.title}” is published.")
    return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))


@login_required
@require_POST
def post_unpublish(request: HttpRequest, pk: int) -> HttpResponse:
    post = _editable_post_or_404(request, pk)
    service.unpublish_post(post, actor=request.user)
    messages.success(request, f"“{post.title}” is back to draft.")
    return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))


@login_required
@require_POST
def post_archive(request: HttpRequest, pk: int) -> HttpResponse:
    post = _editable_post_or_404(request, pk)
    service.archive_post(post, actor=request.user)
    messages.success(request, f"“{post.title}” is archived.")
    return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))


@login_required
@require_POST
def post_schedule(request: HttpRequest, pk: int) -> HttpResponse:
    post = _editable_post_or_404(request, pk)
    raw = (request.POST.get("scheduled_for") or "").strip()
    if not raw:
        messages.error(request, "Pick a date and time to schedule for.")
        return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))

    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(raw)
    if parsed is None:
        messages.error(request, "That date and time could not be understood.")
        return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))
    if timezone.is_naive(parsed):
        # The <input type="datetime-local"> has no offset; interpret it in the
        # viewer's active timezone, which the timezone middleware has set.
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

    try:
        service.schedule_post(post, when=parsed, actor=request.user)
    except service.BlogServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"“{post.title}” is scheduled.")
    return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))


def _editable_issue_or_404(request: HttpRequest, pk: int) -> Issue:
    issue = get_object_or_404(Issue.objects.select_related("blog", "post"), pk=pk)
    if not permissions.can_edit(request.user, issue.blog):
        raise Http404("No such issue.")
    return issue


@login_required
@require_POST
def issue_queue(request: HttpRequest, pk: int) -> HttpResponse:
    """Freeze the issue and start sending.

    The single most consequential button in the app — it mails real people and
    cannot be undone — so every refusal from the service is surfaced verbatim
    rather than collapsed into a generic error.
    """
    issue = _editable_issue_or_404(request, pk)
    try:
        service.queue_issue(issue, actor=request.user)
    except service.BlogServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"“{issue.subject}” is queued for {issue.recipient_count} subscriber(s). "
            "A worker on the email queue will deliver it.",
        )
    return redirect(_safe_next(request, f"/smallstack/blog/issues/{issue.pk}/"))


@login_required
@require_POST
def issue_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    issue = _editable_issue_or_404(request, pk)
    try:
        service.cancel_issue(issue, actor=request.user)
    except service.BlogServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Send cancelled. Copies already delivered can't be recalled.")
    return redirect(_safe_next(request, f"/smallstack/blog/issues/{issue.pk}/"))


@login_required
@require_POST
def issue_test(request: HttpRequest, pk: int) -> HttpResponse:
    """Send one real copy to one address — the only way to catch a rendering
    or header mistake before thousands of people see it."""
    issue = _editable_issue_or_404(request, pk)
    to = (request.POST.get("to") or getattr(request.user, "email", "") or "").strip()
    if not to:
        messages.error(request, "Give an address to send the test to.")
    else:
        sent = service.send_test(issue, to, actor=request.user)
        if sent:
            messages.success(request, f"Test copy sent to {to}.")
        else:
            messages.error(request, f"Could not send a test copy to {to}.")
    return redirect(_safe_next(request, f"/smallstack/blog/issues/{issue.pk}/"))


@login_required
@require_POST
def issue_retry(request: HttpRequest, pk: int) -> HttpResponse:
    issue = _editable_issue_or_404(request, pk)
    count = service.retry_failed(issue, actor=request.user)
    if count:
        messages.success(request, f"Re-queued {count} failed delivery(s).")
    else:
        messages.info(request, "Nothing to retry.")
    return redirect(_safe_next(request, f"/smallstack/blog/issues/{issue.pk}/"))


@login_required
@require_POST
def post_send_newsletter(request: HttpRequest, pk: int) -> HttpResponse:
    """Open a newsletter issue from a post, as a draft.

    Creating the issue and *sending* it are deliberately two actions: this one
    lands you on a page where you can preview, test-send and then queue.
    """
    post = _editable_post_or_404(request, pk)
    try:
        issue = service.create_issue_from_post(post, actor=request.user)
    except service.BlogServiceError as exc:
        messages.error(request, str(exc))
        return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))
    messages.success(request, "Draft issue created — preview it, then send.")
    return redirect(f"/smallstack/blog/issues/{issue.pk}/")


@login_required
def runbook_import(request: HttpRequest) -> HttpResponse:
    """Pick a runbook document and publish it into one of your blogs.

    The entry point lives on the blog side on purpose: runbook needs no
    knowledge of the blog, no template edit and no new dependency, so the two
    apps stay one-directionally coupled and a project that removes the blog
    loses nothing from its runbook.
    """
    blogs = permissions.editable_blogs(request.user).order_by("name")
    documents = service.publishable_documents(request.user).order_by("title")

    query = (request.GET.get("q") or "").strip()
    if query:
        documents = documents.filter(title__icontains=query)

    if request.method == "POST":
        blog_pk = (request.POST.get("blog") or "").strip()
        doc_pk = (request.POST.get("document") or "").strip()
        if not blog_pk.isdigit() or not doc_pk.isdigit():
            messages.error(request, "Pick a document and a blog.")
            return redirect("blog_runbook_import")

        blog = blogs.filter(pk=int(blog_pk)).first()
        if blog is None:
            messages.error(request, "Pick a blog you can write to.")
            return redirect("blog_runbook_import")

        # Resolved against the *scoped* queryset, so a forged pk is a 404 and
        # not a way to publish someone else's private runbook page.
        doc = documents.filter(pk=int(doc_pk)).first()
        if doc is None:
            raise Http404("No such runbook document.")

        try:
            post = service.publish_document(
                doc,
                blog,
                status=request.POST.get("status") or Post.Status.DRAFT,
                sync=request.POST.get("sync") or "manual",
                actor=request.user,
            )
        except service.BlogServiceError as exc:
            messages.error(request, str(exc))
            return redirect("blog_runbook_import")

        messages.success(request, f"Published “{post.title}” into {blog.name}.")
        return redirect(post.console_url or "/smallstack/blog/posts/")

    return render(
        request,
        "blog/import_runbook.html",
        {
            "blogs": blogs,
            "documents": documents[:200],
            "query": query,
            "already_published": set(
                Post.objects.filter(source_document__isnull=False).values_list(
                    "source_document_id", flat=True
                )
            ),
        },
    )


@login_required
@require_POST
def post_resync(request: HttpRequest, pk: int) -> HttpResponse:
    """Pull the latest runbook content into a published post."""
    post = _editable_post_or_404(request, pk)
    try:
        service.resync_post(post, actor=request.user, force=True)
    except service.BlogServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"“{post.title}” now matches its runbook page.")
    return redirect(_safe_next(request, post.console_url or "/smallstack/blog/posts/"))


@login_required
@require_POST
def post_preview(request: HttpRequest) -> HttpResponse:
    """Render markdown for the editor's live preview pane (htmx).

    Calls the *same* ``render_markdown`` the service uses, so what the author
    previews is byte-identical to what gets stored and served. A separate
    preview renderer is how a preview starts lying.
    """
    rendered = service.render_markdown_preview(request.POST.get("body_markdown", ""))
    return render(request, "blog/_markdown_preview.html", {"rendered": rendered})
