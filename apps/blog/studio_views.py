"""The writing studio at ``/my/blogs/`` — a person's own blogs.

Distinct from the console at ``/smallstack/blog/``, which is the system
manager: every blog, every field, the operator's view. This is the author's
view, and it is scoped to what they own from the first query onward.

Same service, same permission scopers, same lifecycle endpoints — the studio
adds a writing surface, not a second set of rules. Lifecycle buttons post to
the existing console actions (``blog_post_publish`` and friends) with a
``next`` back here, so there is exactly one implementation of "publish".
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import permissions, service
from .models import Blog, Post
from .studio_forms import StudioBlogForm, StudioNewsletterForm, StudioPostForm


def _my_blogs(request: HttpRequest) -> Any:
    return permissions.editable_blogs(request.user).order_by("name")


def _my_blog_or_404(request: HttpRequest, slug: str) -> Blog:
    """A blog the user may author in. 404 otherwise — ownership is not a
    thing to confirm or deny to a stranger."""
    return get_object_or_404(_my_blogs(request), slug=slug)


def _my_post_or_404(request: HttpRequest, blog: Blog, pk: int) -> Post:
    post = get_object_or_404(Post.objects.select_related("blog"), pk=pk, blog=blog)
    if not permissions.can_edit_post(request.user, post):
        raise Http404("No such post.")
    return post


def _status_counts(qs: Any) -> dict[str, int]:
    now = timezone.now()
    return qs.aggregate(
        drafts=Count("pk", filter=Q(status=Post.Status.DRAFT)),
        scheduled=Count("pk", filter=Q(status=Post.Status.SCHEDULED)),
        live=Count("pk", filter=Q(status=Post.Status.PUBLISHED, published_at__lte=now)),
        embargoed=Count("pk", filter=Q(status=Post.Status.PUBLISHED, published_at__gt=now)),
        archived=Count("pk", filter=Q(status=Post.Status.ARCHIVED)),
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Your blogs, with the posts that need you first.

    A list, not a card grid: a writer scans titles. Drafts and scheduled posts
    lead because they are the ones with something left to do.
    """
    blogs = list(_my_blogs(request))
    posts = (
        Post.objects.filter(blog__in=blogs)
        .select_related("blog")
        .order_by("-updated_at", "-id")
    )
    in_progress = [p for p in posts if p.status in (Post.Status.DRAFT, Post.Status.SCHEDULED)][:12]
    recent = [p for p in posts if p.status == Post.Status.PUBLISHED][:8]
    return render(
        request,
        "blog/studio/dashboard.html",
        {
            "blogs": blogs,
            "in_progress": in_progress,
            "recent": recent,
            "counts": _status_counts(posts) if blogs else {},
        },
    )


# ---------------------------------------------------------------------------
# Blogs
# ---------------------------------------------------------------------------


@login_required
def blog_new(request: HttpRequest) -> HttpResponse:
    form = StudioBlogForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        blog = service.create_blog(
            name=data["name"],
            slug=data.get("slug") or "",
            visibility=data["visibility"],
            tagline=data.get("tagline") or "",
            description=data.get("description") or "",
            actor=request.user,
        )
        messages.success(request, f"{blog.name} is ready. Write your first post.")
        return redirect("myblogs:post_new", blog_slug=blog.slug)
    return render(request, "blog/studio/blog_form.html", {"form": form, "blog": None})


@login_required
def blog_detail(request: HttpRequest, blog_slug: str) -> HttpResponse:
    blog = _my_blog_or_404(request, blog_slug)
    status = (request.GET.get("status") or "").strip()
    posts = Post.objects.filter(blog=blog).order_by("-updated_at", "-id")
    if status in Post.Status.values:
        posts = posts.filter(status=status)
    return render(
        request,
        "blog/studio/blog_detail.html",
        {
            "blog": blog,
            "posts": posts,
            "status": status,
            "counts": _status_counts(Post.objects.filter(blog=blog)),
            "public_url": blog.get_absolute_url() if blog.is_anonymously_readable else "",
        },
    )


@login_required
def blog_settings(request: HttpRequest, blog_slug: str) -> HttpResponse:
    """Basics and newsletter as two forms on one page, each saving on its own,
    so the common edit — a rename — never touches the newsletter block."""
    blog = _my_blog_or_404(request, blog_slug)
    # Captured BEFORE the form binds: ModelForm.is_valid() copies cleaned data
    # onto the instance, so comparing against `blog.visibility` afterwards is
    # comparing the new value with itself — and the change silently never
    # reaches the service.
    previous_visibility = blog.visibility
    which = request.POST.get("which", "")
    basics = StudioBlogForm(request.POST if which == "basics" else None, instance=blog)
    newsletter = StudioNewsletterForm(
        request.POST if which == "newsletter" else None, instance=blog
    )

    if request.method == "POST":
        if which == "basics" and basics.is_valid():
            data = basics.cleaned_data
            wanted = (data.get("slug") or "").strip() or data["name"]
            blog.name = data["name"]
            blog.tagline = data.get("tagline") or ""
            blog.description = data.get("description") or ""
            blog.slug = service.unique_blog_slug(wanted, exclude_pk=blog.pk)
            blog.save(update_fields=["name", "tagline", "description", "slug", "updated_at"])
            if data["visibility"] != previous_visibility:
                service.set_visibility(blog, visibility=data["visibility"], actor=request.user)
            messages.success(request, "Saved.")
            return redirect("myblogs:blog_settings", blog_slug=blog.slug)
        if which == "newsletter" and newsletter.is_valid():
            newsletter.save()
            messages.success(request, "Newsletter settings saved.")
            return redirect("myblogs:blog_settings", blog_slug=blog.slug)

    return render(
        request,
        "blog/studio/blog_settings.html",
        {"blog": blog, "basics": basics, "newsletter": newsletter},
    )


# ---------------------------------------------------------------------------
# Posts — the editor
# ---------------------------------------------------------------------------


_ACTIONS = {"save", "publish", "unpublish", "schedule", "archive"}


def _transition(request: HttpRequest, post: Post, action: str) -> str:
    """Apply a lifecycle action after a successful save. Returns the toast."""
    if action == "publish":
        service.publish_post(post, actor=request.user)
        return "Published."
    if action == "unpublish":
        service.unpublish_post(post, actor=request.user)
        return "Back to draft."
    if action == "archive":
        service.archive_post(post, actor=request.user)
        return "Archived."
    if action == "schedule":
        from django.utils.dateparse import parse_datetime

        raw = (request.POST.get("scheduled_for") or "").strip()
        when = parse_datetime(raw) if raw else None
        if when is None:
            raise service.InvalidState("Pick a date and time to schedule for.")
        if timezone.is_naive(when):
            when = timezone.make_aware(when, timezone.get_current_timezone())
        service.schedule_post(post, when=when, actor=request.user)
        return f"Scheduled for {timezone.localtime(when):%-d %b, %H:%M}."
    return "Saved."


def _editor(request: HttpRequest, blog: Blog, post: Post | None) -> HttpResponse:
    """Create or edit, then optionally transition — one form, one request.

    Publish / Schedule / Archive buttons set ``action``; the editor is saved
    *first*, so nothing typed is lost on the way to publishing, and the
    transition itself is still the service's single implementation.
    """
    form = StudioPostForm(
        request.POST or None, request.FILES or None, instance=post or Post(blog=blog)
    )
    action = request.POST.get("action", "save")
    if action not in _ACTIONS:
        action = "save"

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        tags = data.pop("tag_names", [])
        cover = data.get("cover_image")
        try:
            if post is None:
                post = service.create_post(
                    blog,
                    title=data["title"],
                    body_markdown=data.get("body_markdown") or "",
                    slug=data.get("slug") or "",
                    excerpt=data.get("excerpt") or "",
                    cover_alt=data.get("cover_alt") or "",
                    canonical_url=data.get("canonical_url") or "",
                    tags=tags,
                    actor=request.user,
                )
                extras: dict[str, Any] = {
                    "allow_newsletter": data.get("allow_newsletter", True),
                    "is_featured": data.get("is_featured", False),
                }
                if cover:
                    extras["cover_image"] = cover
                service.update_post(post, actor=request.user, **extras)
            else:
                fields: dict[str, Any] = {
                    k: data[k]
                    for k in (
                        "title", "slug", "body_markdown", "excerpt", "cover_alt",
                        "canonical_url", "allow_newsletter", "is_featured",
                    )
                }
                # ClearableFileInput: False means "clear", None means "unchanged".
                if cover is False:
                    fields["cover_image"] = None
                elif cover:
                    fields["cover_image"] = cover
                service.update_post(post, actor=request.user, tags=tags, **fields)
            toast = _transition(request, post, action) if action != "save" else (
                "Draft saved." if request.POST.get("was_new") else "Saved."
            )
        except service.BlogServiceError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, toast)
            return redirect("myblogs:post_edit", blog_slug=blog.slug, pk=post.pk)

    return render(
        request,
        "blog/studio/post_form.html",
        {
            "blog": blog,
            "post": post,
            "form": form,
            "word_count": len((post.body_markdown if post else "").split()),
        },
    )


@login_required
def post_new(request: HttpRequest, blog_slug: str) -> HttpResponse:
    return _editor(request, _my_blog_or_404(request, blog_slug), None)


@login_required
def post_edit(request: HttpRequest, blog_slug: str, pk: int) -> HttpResponse:
    blog = _my_blog_or_404(request, blog_slug)
    return _editor(request, blog, _my_post_or_404(request, blog, pk))


@login_required
@require_POST
def post_delete(request: HttpRequest, blog_slug: str, pk: int) -> HttpResponse:
    blog = _my_blog_or_404(request, blog_slug)
    post = _my_post_or_404(request, blog, pk)
    title = post.title
    post.delete()  # a real delete fires post_delete: search + webhooks follow
    messages.success(request, f"Deleted “{title}”.")
    return redirect("myblogs:blog_detail", blog_slug=blog.slug)
