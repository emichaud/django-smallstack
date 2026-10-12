"""Ownership + visibility authorization — the single source of truth.

A blog has an ``owner`` (NULL = a staff-managed house blog) and a three-way
``visibility``. Posts, tags, issues and deliveries inherit from their blog.

- **view**  = staff, OR you own it, OR visibility admits you
              (``public`` ⇒ anyone; ``members`` ⇒ any signed-in user)
- **edit**  = staff, OR you own it  (owner-NULL ⇒ staff-only)
- **read a post** = you may view its blog AND (the post is live OR you may edit)

Pure functions, no request objects, so the service layer, the console
CRUDViews, REST, MCP, search visibility and the public views all share them.
``viewable_posts`` in particular is the *one* scoper behind six surfaces — get
it right here and every one of them is correct.

Rows a viewer may not see are absent from their querysets and 404 on direct
access. Never leak existence: whether a neighbour has a blog called "launch"
is not public information.
"""

from __future__ import annotations

from typing import Any, Optional

from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import Blog, Delivery, Issue, Post, Subscription, Tag


def _uid(user: Any) -> Optional[int]:
    """The user's pk, or None for AnonymousUser / None."""
    return getattr(user, "id", None)


def is_staff(user: Any) -> bool:
    return bool(getattr(user, "is_staff", False))


# -- Object-level checks ------------------------------------------------------


def can_view(user: Any, blog: Optional[Blog]) -> bool:
    """May ``user`` read this blog's shell (index, archive, tag pages)?"""
    if blog is None:
        return is_staff(user)
    if is_staff(user):
        return True
    if blog.visibility == Blog.Visibility.PUBLIC:
        return True
    if _uid(user) is None:  # anonymous gets nothing beyond public
        return False
    if blog.visibility == Blog.Visibility.MEMBERS:
        return True
    return blog.owner_id is not None and blog.owner_id == _uid(user)


def can_edit(user: Any, blog: Optional[Blog]) -> bool:
    """May ``user`` author in / configure this blog?"""
    if blog is None:
        return is_staff(user)
    if is_staff(user):
        return True
    return blog.owner_id is not None and blog.owner_id == _uid(user)


def can_view_post(user: Any, post: Optional[Post]) -> bool:
    """May ``user`` read this post?

    An unpublished post is visible only to someone who could edit it — that is
    the draft-preview affordance every blog engine has, and the reason it is
    expressed here rather than in a view.
    """
    if post is None:
        return False
    if not can_view(user, post.blog):
        return False
    if post.is_live:
        return True
    return can_edit(user, post.blog)


def can_edit_post(user: Any, post: Optional[Post]) -> bool:
    return post is not None and can_edit(user, post.blog)


# -- Queryset scopers ---------------------------------------------------------


def viewable_blogs(user: Any, qs: Optional[QuerySet[Blog]] = None) -> QuerySet[Blog]:
    """Restrict a Blog queryset to what ``user`` may view."""
    qs = Blog.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    if _uid(user) is None:
        return qs.filter(visibility=Blog.Visibility.PUBLIC)
    return qs.filter(
        Q(visibility__in=[Blog.Visibility.PUBLIC, Blog.Visibility.MEMBERS])
        | Q(owner_id=user.id)
    )


def editable_blogs(user: Any, qs: Optional[QuerySet[Blog]] = None) -> QuerySet[Blog]:
    """Restrict a Blog queryset to what ``user`` may author in.

    Narrower than :func:`viewable_blogs` on purpose — it is what scopes the
    ``blog`` choice on the post form, which ``get_list_queryset`` cannot reach.
    """
    qs = Blog.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    if _uid(user) is None:
        return qs.none()
    return qs.filter(owner_id=user.id)


def live_post_filter(prefix: str = "") -> Q:
    """``Q`` matching a post that is published and past its publication time.

    Exposed so annotations and ``filter=`` clauses can reuse the *same*
    definition of "live" the querysets use, instead of re-typing
    ``status="published"`` and silently forgetting the timestamp half — which
    is how an embargoed post ends up counted on a public index.

    ``prefix`` lets it cross a relation, e.g. ``live_post_filter("posts__")``.
    """
    return Q(
        **{
            f"{prefix}status": Post.Status.PUBLISHED,
            f"{prefix}published_at__lte": timezone.now(),
        }
    )


def public_posts(qs: Optional[QuerySet[Post]] = None) -> QuerySet[Post]:
    """Only anonymously-readable posts: live, in a public blog.

    The one definition of "on the internet", used by the public views, both
    feed kinds, the sitemap and the public JSON API — so there is exactly one
    place a draft leak could originate.
    """
    qs = Post.objects.all() if qs is None else qs
    return qs.filter(
        status=Post.Status.PUBLISHED,
        published_at__lte=timezone.now(),
        blog__visibility=Blog.Visibility.PUBLIC,
    )


def viewable_posts(user: Any, qs: Optional[QuerySet[Post]] = None) -> QuerySet[Post]:
    """Restrict a Post queryset to what ``user`` may view.

    Runs for the console list, console detail, REST list/detail, every
    generated MCP tool, ``search_visibility`` and the public views. A
    ``qs.all()`` here would be a cross-tenant data leak on all six at once.
    """
    qs = Post.objects.all() if qs is None else qs
    if is_staff(user):
        return qs

    live = Q(
        status=Post.Status.PUBLISHED,
        published_at__lte=timezone.now(),
    )
    if _uid(user) is None:
        return qs.filter(live & Q(blog__visibility=Blog.Visibility.PUBLIC))

    # Signed in: live posts in any blog they can see, plus everything —
    # drafts included — in the blogs they own.
    return qs.filter(
        (live & Q(blog__visibility__in=[Blog.Visibility.PUBLIC, Blog.Visibility.MEMBERS]))
        | Q(blog__owner_id=user.id)
    ).distinct()


# -- Search-registry adapters -------------------------------------------------
#
# apps.search calls `search_visibility(queryset, user)`; the scopers above take
# `(user, queryset)`, matching runbook's convention and reading better at every
# other call site. Passing a scoper directly raises inside the registry, which
# fails *safe* by dropping every hit from that view — so the symptom is "search
# silently returns nothing", with no error anywhere. These adapters exist so the
# argument order can never be got wrong by accident again.


def search_visible_posts(qs: QuerySet[Post], user: Any) -> QuerySet[Post]:
    """``search_visibility`` adapter for :func:`viewable_posts`."""
    return viewable_posts(user, qs)


def search_visible_blogs(qs: QuerySet[Blog], user: Any) -> QuerySet[Blog]:
    """``search_visibility`` adapter for :func:`viewable_blogs`."""
    return viewable_blogs(user, qs)


def viewable_tags(user: Any, qs: Optional[QuerySet[Tag]] = None) -> QuerySet[Tag]:
    qs = Tag.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    return qs.filter(blog__in=viewable_blogs(user))


def editable_tags(user: Any, qs: Optional[QuerySet[Tag]] = None) -> QuerySet[Tag]:
    qs = Tag.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    return qs.filter(blog__in=editable_blogs(user))


def owned_issues(user: Any, qs: Optional[QuerySet[Issue]] = None) -> QuerySet[Issue]:
    """Issues belong to whoever may author in the blog — never to a mere reader.

    Scoped by ``editable_blogs``, not ``viewable_blogs``: a members-visibility
    blog is readable by every colleague, and its newsletter drafts and audience
    are not.
    """
    qs = Issue.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    return qs.filter(blog__in=editable_blogs(user))


def owned_subscriptions(
    user: Any, qs: Optional[QuerySet[Subscription]] = None
) -> QuerySet[Subscription]:
    """A blog owner's audience. Same editable-blogs reasoning as issues —
    subscriber addresses are PII and belong to the publisher, not the reader."""
    qs = Subscription.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    return qs.filter(blog__in=editable_blogs(user))


def owned_deliveries(user: Any, qs: Optional[QuerySet[Delivery]] = None) -> QuerySet[Delivery]:
    qs = Delivery.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    return qs.filter(issue__blog__in=editable_blogs(user))
