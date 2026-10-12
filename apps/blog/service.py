"""The blog service layer — **every write goes through here.**

Runbook's discipline, for the same reasons: a post's stored HTML, its excerpt,
its slug uniqueness and its publication timestamps are all derived state, and
anything that writes a Post without maintaining them leaves a row that renders
wrong, searches wrong, or syndicates wrong. The CRUDView ``on_form_valid``
hook, the REST layer, the MCP tools, the scheduled ticks and the management
commands are all thin callers of the functions below.

``actor=None`` means a trusted internal caller (a task, a CLI command, a
migration-time backfill) and skips authorization. Any other value is checked
against :mod:`apps.blog.permissions`.

This module covers posts, tags and scheduling. The runbook bridge and the
newsletter live alongside it and arrive in later phases.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, Sequence

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.smallstack.transforms import render_markdown

from . import permissions
from .models import (
    RENDERER_VERSION,
    Blog,
    Post,
    Tag,
    derive_excerpt,
    reserved_slugs_for,
)

logger = logging.getLogger("smallstack.blog")

Actor = Optional[Any]

# django.core.mail.DEFAULT_MAILER_ALIAS, spelled out: django-stubs does not
# yet export the symbol, and a bare `type: ignore` would hide a real typo.
DEFAULT_MAILER_ALIAS = "default"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BlogServiceError(Exception):
    """Base class for every error this layer raises deliberately."""


class BlogNotFound(BlogServiceError):
    pass


class PostNotFound(BlogServiceError):
    pass


class NotAuthorized(BlogServiceError):
    pass


class InvalidState(BlogServiceError):
    """The operation makes no sense for the object's current state."""


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def _require_blog_edit(actor: Actor, blog: Optional[Blog]) -> None:
    if actor is None:  # trusted internal caller
        return
    if not permissions.can_edit(actor, blog):
        raise NotAuthorized("You may not author in this blog.")


def _require_post_edit(actor: Actor, post: Post) -> None:
    if actor is None:
        return
    if not permissions.can_edit_post(actor, post):
        raise NotAuthorized("You may not edit this post.")


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------


def unique_slug(
    blog: Blog,
    base: str,
    *,
    kind: str = "post",
    exclude_pk: Optional[int] = None,
) -> str:
    """A slug that is URL-safe, unreserved, and unused within ``blog``.

    Disambiguates with a numeric suffix rather than raising, so an author who
    titles a post "Feed" gets ``feed-2`` instead of a validation error about a
    routing detail they have no reason to know about.

    The uniqueness check races: two concurrent creates can both see a slug as
    free. The ``(blog, slug)`` constraint is the real guarantee, and
    :func:`create_post` retries on the resulting ``IntegrityError`` — this
    function only keeps the common path tidy.
    """
    reserved = reserved_slugs_for(kind)
    candidate = slugify(base)[:180] or "post"

    qs = Post.objects if kind == "post" else Tag.objects
    taken = qs.filter(blog=blog)
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)

    suffix = 1
    stem = candidate
    while candidate.lower() in reserved or taken.filter(slug=candidate).exists():
        suffix += 1
        candidate = f"{stem}-{suffix}"
    return candidate


def unique_blog_slug(base: str, *, exclude_pk: Optional[int] = None) -> str:
    """A globally-unique, unreserved slug for a Blog."""
    reserved = reserved_slugs_for("blog")
    candidate = slugify(base)[:70] or "blog"
    taken = Blog.objects.all()
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)

    suffix = 1
    stem = candidate
    while candidate.lower() in reserved or taken.filter(slug=candidate).exists():
        suffix += 1
        candidate = f"{stem}-{suffix}"
    return candidate


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _strip_duplicate_title(markdown_text: str, title: str) -> str:
    """Drop a leading ``# Title`` that merely repeats the post's own title.

    Every page that shows a post already renders ``post.title`` as the page's
    ``<h1>``, and markdown documents — especially ones published over from
    runbook, where an H1 is the norm — almost always open with the same
    heading. Left alone that renders the title twice and puts two ``<h1>``
    elements in one document, which is both visibly wrong and an
    accessibility defect.

    Only an *exact* match is removed. An author whose first heading says
    something different meant it, and it stays.
    """
    stripped = (markdown_text or "").lstrip()
    if not stripped.startswith("# "):
        return markdown_text
    first, _, rest = stripped.partition("\n")
    if first[2:].strip().casefold() != (title or "").strip().casefold():
        return markdown_text
    return rest.lstrip("\n")


def render_body(post: Post) -> None:
    """Populate ``body_html``, ``body_toc``, ``html_renderer_version`` and —
    when blank — ``excerpt``, in place. Does **not** save.

    Rendering is cached rather than done per request because a long post would
    otherwise be re-parsed on every anonymous hit and on every feed build. The
    renderer is the hardened shared one, so raw HTML in a body becomes escaped
    text and ``javascript:`` URLs are blanked.
    """
    source = _strip_duplicate_title(post.body_markdown or "", post.title)
    rendered = render_markdown(source)
    post.body_html = rendered["html"]
    post.body_toc = rendered["toc"]
    post.html_renderer_version = RENDERER_VERSION
    if not (post.excerpt or "").strip():
        post.excerpt = derive_excerpt(post.body_markdown or "")


def render_markdown_preview(markdown_text: str) -> dict:
    """Render a body for the editor's preview pane.

    Deliberately the same call :func:`render_body` makes, so the preview is
    byte-identical to what will be stored and served. A preview with its own
    renderer is a preview that eventually lies.
    """
    return dict(render_markdown(markdown_text or ""))


def rerender_posts(
    *,
    blog: Optional[Blog] = None,
    stale_only: bool = True,
    limit: Optional[int] = None,
) -> int:
    """Re-render stored HTML. Returns the number of posts updated.

    ``stale_only`` restricts the work to rows rendered by an older
    ``RENDERER_VERSION`` — the reason that column exists. Saves one row at a
    time, deliberately: ``bulk_update`` would fire no ``post_save``, so the
    search index and any webhook subscribers would silently drift out of step
    with the content.
    """
    qs = Post.objects.all()
    if blog is not None:
        qs = qs.filter(blog=blog)
    if stale_only:
        qs = qs.exclude(html_renderer_version=RENDERER_VERSION)
    if limit is not None:
        qs = qs[:limit]

    count = 0
    for post in qs.iterator():
        render_body(post)
        post.save(update_fields=["body_html", "body_toc", "html_renderer_version", "excerpt"])
        count += 1
    return count


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def set_post_tags(post: Post, names: Sequence[str], *, actor: Actor = None) -> list[Tag]:
    """Replace a post's tags, creating any that don't exist in its blog.

    Takes human names, not pks, because that is what every caller actually has
    — a form's comma-separated field, a runbook document's frontmatter, an MCP
    tool argument. Tags are per-blog, so this can never attach another
    publication's tag.
    """
    _require_post_edit(actor, post)

    tags: list[Tag] = []
    seen: set[str] = set()
    for raw in names:
        name = (raw or "").strip()
        if not name:
            continue
        slug = slugify(name)[:60]
        if not slug or slug in seen:
            continue
        seen.add(slug)
        # get_or_create can race; the (blog, slug) constraint settles it and we
        # just re-read. The nested atomic keeps a failed INSERT from poisoning
        # the surrounding Postgres transaction.
        try:
            with transaction.atomic():
                tag, _ = Tag.objects.get_or_create(
                    blog=post.blog, slug=slug, defaults={"name": name}
                )
        except IntegrityError:
            tag = Tag.objects.get(blog=post.blog, slug=slug)
        tags.append(tag)

    post.tags.set(tags)
    return tags


# ---------------------------------------------------------------------------
# Posts — create / update
# ---------------------------------------------------------------------------


@transaction.atomic
def create_post(
    blog: Blog,
    *,
    title: str,
    body_markdown: str = "",
    slug: str = "",
    excerpt: str = "",
    tags: Sequence[str] = (),
    cover_alt: str = "",
    canonical_url: str = "",
    author: Actor = None,
    actor: Actor = None,
) -> Post:
    """Create a draft. Publishing is always a separate, explicit act."""
    _require_blog_edit(actor, blog)
    if not (title or "").strip():
        raise InvalidState("A post needs a title.")

    post = Post(
        blog=blog,
        title=title.strip(),
        body_markdown=body_markdown,
        excerpt=excerpt,
        cover_alt=cover_alt,
        canonical_url=canonical_url,
        author=author if author is not None else (actor if actor is not None else None),
        status=Post.Status.DRAFT,
    )
    post.slug = unique_slug(blog, slug or title)
    render_body(post)

    try:
        with transaction.atomic():
            post.save()
    except IntegrityError:
        # Lost a slug race. Recompute and retry once — the second candidate is
        # derived after the winner is visible, so it cannot collide the same way.
        post.slug = unique_slug(blog, slug or title)
        post.save()

    if tags:
        set_post_tags(post, tags, actor=None)
    return post


def update_post(post: Post, *, actor: Actor = None, **fields: Any) -> Post:
    """Update editable fields and re-derive everything that depends on them.

    Status, timestamps and the runbook provenance columns are **not** settable
    here — they belong to :func:`publish_post`, :func:`schedule_post` and the
    runbook bridge. Letting a generic update move them is how a post ends up
    published with no rendered HTML.
    """
    _require_post_edit(actor, post)

    protected = {
        "status", "published_at", "scheduled_for", "body_html", "body_toc",
        "html_renderer_version", "uid", "blog", "source_document",
        "source_document_uid", "source_version", "source_synced_at",
    }
    rejected = protected.intersection(fields)
    if rejected:
        raise InvalidState(
            f"{sorted(rejected)} cannot be set through update_post — use the "
            "publish/schedule/runbook-sync operations instead."
        )

    tags = fields.pop("tags", None)
    changed: list[str] = []
    for name, value in fields.items():
        setattr(post, name, value)
        changed.append(name)

    if "title" in changed and not (post.title or "").strip():
        raise InvalidState("A post needs a title.")

    if "slug" in changed:
        post.slug = unique_slug(post.blog, post.slug or post.title, exclude_pk=post.pk)

    if "body_markdown" in changed or "excerpt" in changed:
        render_body(post)
        changed += ["body_html", "body_toc", "html_renderer_version", "excerpt"]

    post.save(update_fields=sorted(set(changed)) or None)
    if tags is not None:
        set_post_tags(post, tags, actor=None)
    return post


# ---------------------------------------------------------------------------
# Posts — lifecycle
# ---------------------------------------------------------------------------


@transaction.atomic
def publish_post(
    post: Post,
    *,
    at: Optional[datetime] = None,
    actor: Actor = None,
) -> Post:
    """Publish now (or stamp ``at``), rendering the body on the way out.

    Idempotent: re-publishing an already-live post leaves its original
    ``published_at`` alone, so a double-click or a retried task cannot quietly
    move a post's date and reorder every feed.
    """
    _require_post_edit(actor, post)

    now = timezone.now()
    if post.status == Post.Status.PUBLISHED and post.published_at is not None:
        return post

    post.status = Post.Status.PUBLISHED
    post.published_at = at or post.published_at or now
    post.scheduled_for = None
    render_body(post)
    post.save()
    return post


@transaction.atomic
def unpublish_post(post: Post, *, actor: Actor = None) -> Post:
    """Return a post to draft.

    ``published_at`` is cleared: leaving it set would make a draft look live to
    ``is_live`` and to any filter that checks the timestamp rather than the
    status.
    """
    _require_post_edit(actor, post)
    post.status = Post.Status.DRAFT
    post.published_at = None
    post.scheduled_for = None
    post.save(update_fields=["status", "published_at", "scheduled_for", "updated_at"])
    return post


@transaction.atomic
def schedule_post(post: Post, *, when: datetime, actor: Actor = None) -> Post:
    """Queue a post to go live at ``when``.

    Refuses a past timestamp rather than publishing immediately: "schedule" and
    "publish" are different intents, and silently doing the second when asked
    for the first is how an embargo gets broken.
    """
    _require_post_edit(actor, post)
    if timezone.is_naive(when):
        raise InvalidState("Schedule times must be timezone-aware.")
    if when <= timezone.now():
        raise InvalidState("That time has already passed — publish it instead.")

    post.status = Post.Status.SCHEDULED
    post.scheduled_for = when
    post.published_at = None
    render_body(post)
    post.save()
    return post


@transaction.atomic
def archive_post(post: Post, *, actor: Actor = None) -> Post:
    """Retire a post: off the lists and feeds, but its URL keeps working for
    anyone who may already have bookmarked or linked it."""
    _require_post_edit(actor, post)
    post.status = Post.Status.ARCHIVED
    post.scheduled_for = None
    post.save(update_fields=["status", "scheduled_for", "updated_at"])
    return post


def publish_due_posts(
    *,
    now_: Optional[datetime] = None,
    limit: int = 200,
) -> list[int]:
    """Publish every scheduled post whose time has come. Returns their pks.

    Iterates and saves one row at a time **on purpose**. A
    ``queryset.update(status="published")`` would be one query instead of N —
    and would fire no ``post_save``, so nothing would reindex the posts for
    search, nothing would fan out a webhook, and the rendered HTML would never
    be refreshed. That shortcut is the single most likely silent bug in this
    feature, which is why it is called out here rather than in a commit message.
    """
    now = now_ or timezone.now()
    due = Post.objects.filter(
        status=Post.Status.SCHEDULED,
        scheduled_for__isnull=False,
        scheduled_for__lte=now,
    ).order_by("scheduled_for", "pk")[:limit]

    published: list[int] = []
    for post in list(due):
        try:
            # published_at records when it ACTUALLY went live, not when it was
            # due — a tick that runs four minutes late should say so.
            publish_post(post, at=now, actor=None)
            published.append(post.pk)
        except Exception:  # noqa: BLE001
            # One bad row must not strand the rest of the queue.
            logger.exception("blog: failed to publish scheduled post %s", post.pk)
    return published


def due_post_count(*, now_: Optional[datetime] = None) -> int:
    """Scheduled posts already past their time — the status monitor's signal."""
    return Post.objects.filter(
        status=Post.Status.SCHEDULED,
        scheduled_for__isnull=False,
        scheduled_for__lte=now_ or timezone.now(),
    ).count()


# ---------------------------------------------------------------------------
# The runbook bridge
# ---------------------------------------------------------------------------
#
# Runbook holds versioned markdown that teams already maintain; a blog is a
# channel to publish into. The bridge is one-directional by design: the blog
# reads runbook through `runbook.service` (never its ORM, so locking,
# permissions and the audit trail all still apply), and nothing in runbook
# knows the blog exists. The "Publish to blog" entry point lives on the blog
# side, so no runbook template or view is touched.
#
# Note runbook's own `is_public` means *signed-in users*, not anonymous
# (apps/runbook/permissions.py). Publishing a document here therefore grants a
# genuinely new tier, which is why it is an explicit act against a specific
# blog whose visibility the author chose — never an automatic consequence of a
# runbook flag.


class DocumentNotPublishable(BlogServiceError):
    """The actor may not read the document, or it cannot be published."""


def _resolve_document(document: Any, *, viewer: Actor = None) -> Any:
    """Fetch a runbook ``Document``, honouring runbook's own permissions.

    Accepts a Document, a pk, or a uid. The lookup goes through
    ``runbook.service.get_document`` so the viewer check, the archived check
    and the audit path all apply; that returns a flat ``DocumentResult`` DTO
    rather than the model, so the model is re-read by the id it reports.
    """
    from apps.runbook import service as runbook_service
    from apps.runbook.models import Document

    if isinstance(document, Document):
        # Re-read rather than trusting the caller's instance. A Document held
        # across a runbook write is stale in exactly the two fields this
        # bridge depends on — `version`, which decides whether a resync is a
        # no-op, and `current_version`, which `read_head` follows to the file.
        # Trusting it makes resync silently do nothing.
        return Document.objects.select_related("current_version").get(pk=document.pk)
    try:
        if isinstance(document, int):
            result = runbook_service.get_document(id=document, viewer=viewer)
        else:
            result = runbook_service.get_document(uid=str(document), viewer=viewer)
    except Exception as exc:  # noqa: BLE001 — runbook raises its own taxonomy
        raise DocumentNotPublishable(f"No readable runbook document {document!r}.") from exc
    return Document.objects.select_related("current_version").get(pk=result.id)


def publishable_documents(user: Actor) -> Any:
    """Runbook documents ``user`` may read, and so may publish."""
    from apps.runbook.models import Document
    from apps.runbook.permissions import viewable_documents

    return viewable_documents(user, Document.objects.filter(is_archived=False)).select_related(
        "runbook"
    )


def _document_body(doc: Any) -> tuple[dict[str, Any], str]:
    """``(frontmatter, body)`` for a runbook document's current version."""
    from apps.runbook import service as runbook_service
    from apps.smallstack.transforms import parse_frontmatter

    return parse_frontmatter(runbook_service.read_head(doc))


def _apply_document(post: Post, doc: Any, meta: dict[str, Any], body: str) -> None:
    """Copy a document's content onto a post. Shared by publish and resync, so
    the two cannot drift."""
    post.title = str(meta.get("title") or doc.title or post.title or "Untitled")
    post.body_markdown = body
    summary = meta.get("description") or meta.get("summary") or doc.description
    if summary:
        post.excerpt = str(summary)
    post.source_document = doc
    post.source_document_uid = doc.uid
    post.source_version = doc.version
    post.source_synced_at = timezone.now()
    render_body(post)


@transaction.atomic
def publish_document(
    document: Any,
    blog: Blog,
    *,
    slug: str = "",
    status: str = Post.Status.PUBLISHED,
    sync: str = "manual",
    actor: Actor = None,
) -> Post:
    """Publish a runbook document into ``blog`` as a post.

    Idempotent per (blog, document): publishing the same document twice
    updates the existing post rather than forking it — the partial unique
    constraint would refuse the second row anyway, and silently failing on a
    double-click would be worse than converging.

    Frontmatter is *parsed*, not just stripped: a document's ``title`` and
    ``description`` keys become the post's title and excerpt. Runbook itself
    only strips frontmatter, so this is where those keys finally mean
    something.
    """
    _require_blog_edit(actor, blog)
    doc = _resolve_document(document, viewer=actor)

    if actor is not None:
        from apps.runbook.permissions import can_view_doc

        if not can_view_doc(actor, doc):
            raise DocumentNotPublishable("You may not read that runbook document.")

    if sync not in {"manual", "auto"}:
        raise InvalidState(f"Unknown sync mode {sync!r}.")

    meta, body = _document_body(doc)
    post = Post.objects.filter(blog=blog, source_document=doc).first()
    created = post is None
    if post is None:
        post = Post(blog=blog, author=actor if actor is not None else None)

    _apply_document(post, doc, meta, body)
    post.source_sync = sync
    if created:
        post.slug = unique_slug(blog, slug or meta.get("slug") or post.title)
    elif slug:
        post.slug = unique_slug(blog, slug, exclude_pk=post.pk)

    if status == Post.Status.PUBLISHED:
        post.status = Post.Status.PUBLISHED
        post.published_at = post.published_at or timezone.now()
    elif created:
        post.status = status

    post.save()
    return post


@transaction.atomic
def resync_post(post: Post, *, actor: Actor = None, force: bool = False) -> Post:
    """Pull the latest runbook content into an already-published post.

    Skips when the document has not moved on, so an auto-sync receiver firing
    on an unrelated write does not churn ``updated_at`` (and with it every
    feed's ``lastBuildDate``) for nothing.
    """
    _require_post_edit(actor, post)
    if not post.source_document_id:
        raise InvalidState("This post was not published from a runbook document.")

    doc = _resolve_document(post.source_document, viewer=actor)
    if not force and post.source_version == doc.version:
        return post

    meta, body = _document_body(doc)
    _apply_document(post, doc, meta, body)
    post.save()
    return post


def resync_for_document(document: Any, *, actor: Actor = None) -> list[int]:
    """Resync every ``sync="auto"`` post fed by ``document``. Returns their pks.

    Manual-sync posts are deliberately left alone: an author who published a
    runbook page once and then edited the post should not have their edits
    silently overwritten the next time someone touches the runbook.
    """
    doc = _resolve_document(document, viewer=None)
    updated: list[int] = []
    for post in Post.objects.filter(source_document=doc, source_sync="auto"):
        try:
            resync_post(post, actor=None)
            updated.append(post.pk)
        except Exception:  # noqa: BLE001
            logger.exception("blog: resync failed for post %s", post.pk)
    return updated


# ---------------------------------------------------------------------------
# Blogs
# ---------------------------------------------------------------------------


@transaction.atomic
def create_blog(
    *,
    name: str,
    owner: Actor = None,
    slug: str = "",
    visibility: str = Blog.Visibility.PRIVATE,
    tagline: str = "",
    description: str = "",
    actor: Actor = None,
) -> Blog:
    """Create a blog. Private by default — see :class:`Blog.Visibility`."""
    if not (name or "").strip():
        raise InvalidState("A blog needs a name.")
    if actor is not None and owner is None:
        owner = actor
    blog = Blog(
        name=name.strip(),
        slug=unique_blog_slug(slug or name),
        owner=owner,
        visibility=visibility,
        tagline=tagline,
        description=description,
    )
    blog.save()
    return blog


@transaction.atomic
def set_visibility(blog: Blog, *, visibility: str, actor: Actor = None) -> Blog:
    """Change a blog's visibility level — the publish toggle."""
    _require_blog_edit(actor, blog)
    if visibility not in Blog.Visibility.values:
        raise InvalidState(f"Unknown visibility {visibility!r}.")
    blog.visibility = visibility
    blog.save(update_fields=["visibility", "updated_at"])
    return blog


# ---------------------------------------------------------------------------
# Newsletter — subscribers
# ---------------------------------------------------------------------------


class SubscriptionNotFound(BlogServiceError):
    pass


class AlreadySending(BlogServiceError):
    """The issue is past the point where it can be changed or re-queued."""


class NewsletterNotReady(BlogServiceError):
    """The blog or the deployment is not in a state where sending is safe."""


def audience(blog: Blog) -> Any:
    """Subscriptions that may receive this blog's next issue.

    Confirmed, not unsubscribed, and not globally suppressed. Suppression is
    checked here rather than at send time so the recipient count an author
    sees before queueing is the number that will actually be attempted.
    """
    from .models import Subscription

    return (
        Subscription.objects.filter(blog=blog, status=Subscription.Status.CONFIRMED)
        .exclude(subscriber__is_suppressed=True)
        .select_related("subscriber", "blog")
    )


@transaction.atomic
def subscribe(
    blog: Blog,
    email: str,
    *,
    name: str = "",
    source: str = "web",
    consent_note: str = "",
    send_email: bool = True,
    actor: Actor = None,
) -> Any:
    """Subscribe an address to a blog's newsletter.

    Idempotent and re-entrant. Re-subscribing an address that previously
    unsubscribed **bumps ``token_version``**, which invalidates every
    confirm/unsubscribe link from the earlier relationship — otherwise an old
    one-click link, still sitting in an inbox, could silently kill the new
    signup.

    Returns the Subscription whatever its state. The caller must not vary its
    response on that: telling an anonymous visitor whether an address is
    already subscribed turns the form into a membership oracle.
    """
    from .models import Subscriber, Subscription, normalize_email

    if not blog.newsletter_enabled:
        raise NewsletterNotReady(f"{blog.name} does not have a newsletter.")

    address = normalize_email(email)
    if not address or "@" not in address:
        raise InvalidState("That does not look like an email address.")

    if blog.double_opt_in is False and actor is None:
        # Skipping confirmation is an operator decision (an internal list
        # import), never something an anonymous web signup can trigger.
        raise NotAuthorized("This list requires confirmation.")

    try:
        with transaction.atomic():
            subscriber, _ = Subscriber.objects.get_or_create(
                email=address, defaults={"name": name}
            )
    except IntegrityError:
        subscriber = Subscriber.objects.get(email=address)

    if name and not subscriber.name:
        subscriber.name = name
        subscriber.save(update_fields=["name", "updated_at"])

    subscription, created = Subscription.objects.get_or_create(
        subscriber=subscriber,
        blog=blog,
        defaults={"source": source, "consent_note": consent_note},
    )

    if not created and subscription.status == Subscription.Status.CONFIRMED:
        return subscription  # already in; say nothing different to the caller

    if not created:
        subscription.token_version += 1
        subscription.unsubscribed_at = None
        subscription.source = source or subscription.source

    subscription.status = Subscription.Status.PENDING
    subscription.save()

    if send_email:
        from . import emails

        emails.send_confirmation(subscription)
    return subscription


@transaction.atomic
def confirm_subscription(raw_token: str) -> Any:
    """Complete a double opt-in. Idempotent — a second click is a no-op."""
    from . import tokens
    from .models import Subscription

    subscription = tokens.read_confirm_token(raw_token)
    if subscription.status == Subscription.Status.CONFIRMED:
        return subscription

    subscription.status = Subscription.Status.CONFIRMED
    subscription.confirmed_at = timezone.now()
    subscription.unsubscribed_at = None
    subscription.save(update_fields=["status", "confirmed_at", "unsubscribed_at"])

    from . import emails

    emails.send_welcome(subscription)
    return subscription


@transaction.atomic
def unsubscribe(raw_token: str, *, reason: str = "user") -> Any:
    """Opt a subscriber out of one blog.

    A state transition, never a delete: the row is what remembers that this
    person opted out, so a later import cannot resurrect them. Idempotent, so
    a provider that retries the one-click POST sees success rather than an
    error.
    """
    from . import tokens
    from .models import Subscription

    subscription = tokens.read_unsubscribe_token(raw_token)
    if subscription.status == Subscription.Status.UNSUBSCRIBED:
        return subscription

    subscription.status = Subscription.Status.UNSUBSCRIBED
    subscription.unsubscribed_at = timezone.now()
    subscription.save(update_fields=["status", "unsubscribed_at"])
    logger.info("blog: unsubscribed from %s (%s)", subscription.blog.slug, reason)
    return subscription


@transaction.atomic
def unsubscribe_email(blog: Blog, email: str, *, reason: str = "", actor: Actor = None) -> int:
    """Operator-side opt-out by address. Returns the number of rows changed."""
    from .models import Subscription, normalize_email

    _require_blog_edit(actor, blog)
    rows = Subscription.objects.filter(
        blog=blog, subscriber__email=normalize_email(email)
    ).exclude(status=Subscription.Status.UNSUBSCRIBED)
    count = 0
    for subscription in rows:
        subscription.status = Subscription.Status.UNSUBSCRIBED
        subscription.unsubscribed_at = timezone.now()
        subscription.save(update_fields=["status", "unsubscribed_at"])
        count += 1
    return count


def suppress_subscriber(subscriber: Any, *, reason: str) -> Any:
    """Stop sending to an address across every blog. Hard bounces only."""
    subscriber.is_suppressed = True
    subscriber.suppressed_at = timezone.now()
    subscriber.suppression_reason = reason[:200]
    subscriber.bounce_count += 1
    subscriber.save(
        update_fields=[
            "is_suppressed", "suppressed_at", "suppression_reason",
            "bounce_count", "updated_at",
        ]
    )
    return subscriber


def unsuppress_subscriber(subscriber: Any, *, actor: Actor = None) -> Any:
    """Undo a suppression — the manual escape hatch for a false positive."""
    subscriber.is_suppressed = False
    subscriber.suppressed_at = None
    subscriber.suppression_reason = ""
    subscriber.consecutive_failures = 0
    subscriber.save(
        update_fields=[
            "is_suppressed", "suppressed_at", "suppression_reason",
            "consecutive_failures", "updated_at",
        ]
    )
    return subscriber


def import_subscribers(
    blog: Blog,
    rows: Iterable[tuple[str, str]],
    *,
    consent_note: str,
    confirmed: bool = False,
    actor: Actor = None,
) -> dict[str, int]:
    """Bulk-add ``(email, name)`` pairs.

    ``consent_note`` is **required** — importing a list is the one path that
    can bypass confirmation, so the record of why these people may be mailed
    has to exist before the first send, not be reconstructed afterwards.
    """
    from .models import Subscriber, Subscription, normalize_email

    _require_blog_edit(actor, blog)
    if not (consent_note or "").strip():
        raise InvalidState("Importing a list requires a consent note.")

    stats = {"created": 0, "existing": 0, "skipped": 0}
    for raw_email, raw_name in rows:
        address = normalize_email(raw_email)
        if not address or "@" not in address:
            stats["skipped"] += 1
            continue
        try:
            with transaction.atomic():
                subscriber, _ = Subscriber.objects.get_or_create(
                    email=address, defaults={"name": (raw_name or "").strip()}
                )
                subscription, created = Subscription.objects.get_or_create(
                    subscriber=subscriber,
                    blog=blog,
                    defaults={
                        "source": "import",
                        "consent_note": consent_note[:200],
                        "status": (
                            Subscription.Status.CONFIRMED
                            if confirmed
                            else Subscription.Status.PENDING
                        ),
                        "confirmed_at": timezone.now() if confirmed else None,
                    },
                )
        except IntegrityError:
            stats["skipped"] += 1
            continue
        stats["created" if created else "existing"] += 1
    return stats


# ---------------------------------------------------------------------------
# Newsletter — issues and the send pipeline
# ---------------------------------------------------------------------------
#
# The design in one line: **Delivery rows are the ledger.** `queue_issue`
# materialises one per recipient up front; from then on the send is just
# draining `pending`, and a worker that dies mid-batch costs nothing but a
# reaper pass. Three independent layers stop a double-send:
#
#   1. UniqueConstraint(issue, subscriber) — queue_issue is re-runnable.
#   2. Delivery.status — only `pending` is ever claimed; `sent` is terminal.
#   3. UniqueConstraint(post) where status in (queued, sending, sent) — one
#      live campaign per post, ever.


def _send_settings() -> dict[str, int]:
    from django.conf import settings as _s

    return {
        "batch": int(getattr(_s, "SMALLSTACK_BLOG_SEND_BATCH_SIZE", 100)),
        "max_batches": int(getattr(_s, "SMALLSTACK_BLOG_SEND_MAX_BATCHES", 20)),
        "claim_timeout": int(getattr(_s, "SMALLSTACK_BLOG_CLAIM_TIMEOUT_MINUTES", 15)),
        "max_attempts": int(getattr(_s, "SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS", 3)),
        "soft_limit": int(getattr(_s, "SMALLSTACK_BLOG_SOFT_FAIL_LIMIT", 5)),
    }


@transaction.atomic
def create_issue(
    blog: Blog,
    *,
    subject: str,
    body_markdown: str = "",
    preheader: str = "",
    post: Optional[Post] = None,
    actor: Actor = None,
) -> Any:
    from .models import Issue

    _require_blog_edit(actor, blog)
    if not (subject or "").strip():
        raise InvalidState("An issue needs a subject.")
    return Issue.objects.create(
        blog=blog,
        post=post,
        subject=subject.strip(),
        preheader=preheader,
        body_markdown=body_markdown,
        created_by=actor if actor is not None else None,
    )


def create_issue_from_post(
    post: Post, *, subject: str = "", preheader: str = "", actor: Actor = None
) -> Any:
    """Open an issue carrying a post. The body is left blank and resolved from
    the post at queue time, so edits up to the moment of sending are picked up."""
    _require_post_edit(actor, post)
    if not post.allow_newsletter:
        raise InvalidState("This post is marked as not for the newsletter.")
    return create_issue(
        post.blog,
        subject=subject or post.title,
        preheader=preheader or post.excerpt[:200],
        post=post,
        actor=actor,
    )


@transaction.atomic
def queue_issue(
    issue: Any,
    *,
    dry_run: bool = False,
    actor: Actor = None,
) -> Any:
    """Freeze the issue and materialise its recipient ledger.

    After this the content cannot change — ``body_html`` is a snapshot, so
    editing the post next month does not rewrite what subscribers received —
    and the audience cannot change either, so somebody who signs up mid-send
    does not get a half-finished issue.
    """
    from django.conf import settings as _s

    from .models import Delivery, Issue, issue_body_source

    _require_blog_edit(actor, issue.blog)

    locked = Issue.objects.select_for_update().get(pk=issue.pk)
    if locked.status not in {Issue.Status.DRAFT, Issue.Status.SCHEDULED}:
        raise AlreadySending(
            f"This issue is already {locked.get_status_display().lower()}."
        )
    if not issue.blog.newsletter_enabled:
        raise NewsletterNotReady(f"{issue.blog.name} does not have a newsletter.")

    # A blast cannot be recalled, and unsubscribe links that point at
    # localhost are unusable for every recipient. Refuse rather than warn.
    if getattr(_s, "SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL", True):
        from apps.accounts.emails import site_url_is_local

        if site_url_is_local():
            raise NewsletterNotReady(
                "The site URL still resolves to localhost, so every unsubscribe "
                "link in this send would be dead. Set SITE_DOMAIN (or SITE_URL) "
                "first, or set SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL=False to "
                "override deliberately."
            )

    body = issue_body_source(issue)
    if not body.strip():
        raise InvalidState("This issue has no body to send.")

    recipients = list(audience(issue.blog))
    if not recipients:
        raise InvalidState("This blog has no confirmed subscribers yet.")

    if dry_run:
        return {"recipients": len(recipients), "subject": issue.subject}

    rendered = render_markdown(body)
    issue.body_html = rendered["html"]
    issue.recipient_count = len(recipients)
    issue.status = Issue.Status.SENDING
    issue.queued_at = timezone.now()
    issue.started_at = timezone.now()
    issue.save()

    # ignore_conflicts relies on UniqueConstraint(issue, subscriber): queueing
    # twice adds nobody twice.
    Delivery.objects.bulk_create(
        [
            Delivery(issue=issue, subscriber=sub.subscriber, email=sub.subscriber.email)
            for sub in recipients
        ],
        ignore_conflicts=True,
    )
    return issue


@transaction.atomic
def cancel_issue(issue: Any, *, actor: Actor = None) -> Any:
    """Stop a send. Already-sent copies cannot be recalled; this only stops
    the rest."""
    from .models import Delivery, Issue

    _require_blog_edit(actor, issue.blog)
    if issue.status == Issue.Status.SENT:
        raise AlreadySending("This issue has already finished sending.")

    issue.status = Issue.Status.CANCELED
    issue.finished_at = timezone.now()
    issue.save(update_fields=["status", "finished_at", "updated_at"])
    Delivery.objects.filter(
        issue=issue, status__in=[Delivery.Status.PENDING, Delivery.Status.CLAIMED]
    ).update(status=Delivery.Status.SKIPPED)
    return issue


def send_test(issue: Any, to: str, *, actor: Actor = None) -> int:
    """Send one preview copy to ``to``. Writes no Delivery row."""
    from . import emails
    from .models import Subscriber, Subscription, normalize_email

    _require_blog_edit(actor, issue.blog)
    body = issue.body_html or render_markdown(
        __import__("apps.blog.models", fromlist=["x"]).issue_body_source(issue)
    )["html"]
    issue.body_html = body

    # A real-looking Subscription so the footer and List-Unsubscribe headers
    # render exactly as a subscriber would receive them — an unsaved stand-in,
    # so nothing touches the audience.
    stand_in = Subscription(
        blog=issue.blog,
        subscriber=Subscriber(email=normalize_email(to), name="Test"),
        token_version=1,
    )
    stand_in.pk = 0
    return emails.send_test_copy(issue, normalize_email(to), stand_in)


def _claim(issue: Any, limit: int) -> list[int]:
    """Claim up to ``limit`` pending deliveries, atomically.

    A compare-and-swap rather than ``select_for_update(skip_locked=True)``,
    which raises ``NotSupportedError`` on SQLite. The ``WHERE status='pending'``
    inside the UPDATE *is* the lock: only rows this statement actually changed
    are ours, so two concurrent workers cannot claim the same recipient.
    """
    from .models import Delivery

    candidates = list(
        Delivery.objects.filter(issue=issue, status=Delivery.Status.PENDING)
        .order_by("pk")
        .values_list("pk", flat=True)[:limit]
    )
    if not candidates:
        return []
    now = timezone.now()
    Delivery.objects.filter(pk__in=candidates, status=Delivery.Status.PENDING).update(
        status=Delivery.Status.CLAIMED, claimed_at=now
    )
    return list(
        Delivery.objects.filter(
            pk__in=candidates, status=Delivery.Status.CLAIMED, claimed_at=now
        ).values_list("pk", flat=True)
    )


def _classify_failure(exc: BaseException) -> str:
    """``"hard"`` (suppress the address) or ``"soft"`` (retry).

    Only an explicit 5xx recipient/sender rejection is hard. Everything else —
    a dropped connection, a timeout, a 4xx greylist — is transient. The prior
    implementation suppressed on *any* exception, so one flaky moment silently
    and permanently dropped a good reader.
    """
    import smtplib

    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        code = getattr(exc, "smtp_code", None)
        if code is None and isinstance(exc, smtplib.SMTPRecipientsRefused):
            codes = [v[0] for v in (exc.recipients or {}).values()]
            code = codes[0] if codes else None
        if code is not None and 500 <= int(code) < 600:
            return "hard"
    return "soft"


def _send_one(issue: Any, delivery: Any, *, connection: Any, limits: dict[str, int]) -> str:
    """Send one message and record the outcome. Returns 'sent'|'failed'|'retry'."""
    from . import emails
    from .models import Delivery, Subscription

    subscription = (
        Subscription.objects.select_related("subscriber", "blog")
        .filter(blog=issue.blog, subscriber_id=delivery.subscriber_id)
        .first()
    )
    if subscription is None or subscription.status != Subscription.Status.CONFIRMED:
        # Unsubscribed between queueing and sending — honour it immediately.
        delivery.status = Delivery.Status.SKIPPED
        delivery.save(update_fields=["status"])
        return "skipped"

    delivery.attempts += 1
    try:
        message = emails.build_issue_message(
            issue, delivery, subscription, connection=connection
        )
        message.send()
    except Exception as exc:  # noqa: BLE001 — classified below
        kind = _classify_failure(exc)
        subscriber = subscription.subscriber
        delivery.last_error = f"{type(exc).__name__}: {exc}"[:2000]

        if kind == "hard":
            delivery.status = Delivery.Status.FAILED
            delivery.save(update_fields=["status", "attempts", "last_error"])
            suppress_subscriber(subscriber, reason=delivery.last_error[:200])
            return "failed"

        subscriber.consecutive_failures += 1
        subscriber.last_failure_at = timezone.now()
        subscriber.save(update_fields=["consecutive_failures", "last_failure_at", "updated_at"])
        if subscriber.consecutive_failures >= limits["soft_limit"]:
            suppress_subscriber(
                subscriber,
                reason=f"{subscriber.consecutive_failures} consecutive delivery failures",
            )

        if delivery.attempts >= limits["max_attempts"]:
            delivery.status = Delivery.Status.FAILED
            delivery.save(update_fields=["status", "attempts", "last_error"])
            return "failed"

        delivery.status = Delivery.Status.PENDING
        delivery.claimed_at = None
        delivery.save(update_fields=["status", "claimed_at", "attempts", "last_error"])
        return "retry"

    delivery.status = Delivery.Status.SENT
    delivery.sent_at = timezone.now()
    delivery.last_error = ""
    delivery.save(update_fields=["status", "sent_at", "attempts", "last_error"])

    subscriber = subscription.subscriber
    if subscriber.consecutive_failures:
        subscriber.consecutive_failures = 0
        subscriber.save(update_fields=["consecutive_failures", "updated_at"])
    return "sent"


def send_issue_batch(issue: Any, *, batch_size: Optional[int] = None) -> dict[str, int]:
    """Send one batch. Returns counts; safe to call repeatedly."""
    from django.core.mail import mailers

    from .models import Delivery

    limits = _send_settings()
    ids = _claim(issue, batch_size or limits["batch"])
    if not ids:
        finalize_issue(issue)
        return {"claimed": 0, "sent": 0, "failed": 0, "retry": 0, "skipped": 0}

    # One connection per BATCH, not per message: a fresh connection per
    # recipient means a TCP+TLS handshake and an SMTP AUTH for each one, which
    # is the difference between a 5,000-recipient send taking minutes and
    # taking hours.
    #
    # Via `mailers[...]`, not the deprecated `get_connection()` (removed in
    # Django 2028). `Blog.mailer_alias` selects a second MAILERS entry so a
    # blast can be routed away from the transactional mail's IP and domain
    # reputation; an unknown alias falls back rather than failing the send.
    alias = issue.blog.mailer_alias or DEFAULT_MAILER_ALIAS
    try:
        connection = mailers[alias]
    except Exception:  # noqa: BLE001 — a typo'd alias must not strand a send
        logger.warning(
            "blog: unknown mailer alias %r for %s; using the default",
            alias, issue.blog.slug,
        )
        connection = mailers[DEFAULT_MAILER_ALIAS]
    counts = {"claimed": len(ids), "sent": 0, "failed": 0, "retry": 0, "skipped": 0}
    try:
        connection.open()
    except Exception:  # noqa: BLE001 — backends needn't implement open()
        logger.debug("blog: connection.open() unsupported", exc_info=True)
    try:
        for delivery in Delivery.objects.filter(pk__in=ids).select_related("subscriber"):
            outcome = _send_one(issue, delivery, connection=connection, limits=limits)
            counts[outcome] = counts.get(outcome, 0) + 1
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            pass

    _refresh_counters(issue)
    finalize_issue(issue)
    return counts


def _refresh_counters(issue: Any) -> None:
    from django.db.models import Count, Q

    from .models import Delivery, Issue

    agg = Delivery.objects.filter(issue=issue).aggregate(
        sent=Count("pk", filter=Q(status=Delivery.Status.SENT)),
        failed=Count("pk", filter=Q(status=Delivery.Status.FAILED)),
    )
    Issue.objects.filter(pk=issue.pk).update(
        sent_count=agg["sent"] or 0, failed_count=agg["failed"] or 0
    )
    issue.sent_count = agg["sent"] or 0
    issue.failed_count = agg["failed"] or 0


def finalize_issue(issue: Any) -> Any:
    """Flip an issue to `sent` once nothing is left in flight."""
    from .models import Delivery, Issue

    if issue.status != Issue.Status.SENDING:
        return issue
    outstanding = Delivery.objects.filter(
        issue=issue, status__in=[Delivery.Status.PENDING, Delivery.Status.CLAIMED]
    ).exists()
    if outstanding:
        return issue

    _refresh_counters(issue)
    attempted = Delivery.objects.filter(issue=issue).exclude(
        status=Delivery.Status.SKIPPED
    ).count()
    issue.status = (
        Issue.Status.FAILED
        if attempted and issue.sent_count == 0
        else Issue.Status.SENT
    )
    issue.finished_at = timezone.now()
    issue.save(update_fields=["status", "finished_at", "sent_count", "failed_count", "updated_at"])
    return issue


def reap_stale_claims(*, older_than_minutes: Optional[int] = None) -> int:
    """Return orphaned `claimed` rows to `pending`.

    A worker killed mid-batch leaves its claims behind. Without this they are
    never retried and the issue never finalises — the send just stops, with
    no error and a progress bar stuck short of 100%.
    """
    from django.db.models import Q

    from .models import Delivery

    minutes = older_than_minutes or _send_settings()["claim_timeout"]
    cutoff = timezone.now() - timedelta(minutes=minutes)
    # `claimed_at IS NULL` is included deliberately: a claimed row with no
    # timestamp can only come from an interrupted write or a hand-edit, and
    # without this clause it is orphaned *permanently* — never retried, and
    # the issue never finalises, so the send simply stops short with no error.
    return Delivery.objects.filter(
        Q(claimed_at__lt=cutoff) | Q(claimed_at__isnull=True),
        status=Delivery.Status.CLAIMED,
    ).update(status=Delivery.Status.PENDING, claimed_at=None)


def process_sending_issues(
    *, batch_size: Optional[int] = None, max_batches: Optional[int] = None
) -> list[dict]:
    """Drain every in-flight issue. The scheduled tick's entry point."""
    from .models import Issue

    limits = _send_settings()
    budget = max_batches or limits["max_batches"]
    results: list[dict] = []

    for issue in Issue.objects.filter(status=Issue.Status.SENDING).order_by("queued_at"):
        while budget > 0:
            counts = send_issue_batch(issue, batch_size=batch_size)
            budget -= 1
            if not counts["claimed"]:
                break
            results.append({"issue": str(issue.uid), **counts})
        if budget <= 0:
            break
    return results


def retry_failed(issue: Any, *, actor: Actor = None) -> int:
    """Re-queue failed deliveries that have attempts left. Never touches
    `sent` rows, so a retry cannot double-send."""
    from .models import Delivery, Issue

    _require_blog_edit(actor, issue.blog)
    limits = _send_settings()
    count = Delivery.objects.filter(
        issue=issue,
        status=Delivery.Status.FAILED,
        attempts__lt=limits["max_attempts"],
    ).update(status=Delivery.Status.PENDING, claimed_at=None)
    if count:
        Issue.objects.filter(pk=issue.pk).update(
            status=Issue.Status.SENDING, finished_at=None
        )
        issue.refresh_from_db()
    return count


def due_issue_count(*, now_: Optional[datetime] = None) -> int:
    """Issues stuck mid-send for too long — the status monitor's signal."""
    from .models import Issue

    cutoff = (now_ or timezone.now()) - timedelta(hours=1)
    return Issue.objects.filter(
        status=Issue.Status.SENDING, started_at__lt=cutoff
    ).count()


def reindex(posts: Iterable[Post]) -> None:
    """Refresh the search index for rows written without ``post_save``.

    Only needed after a genuine bulk write (``bulk_create`` / ``bulk_update`` /
    ``QuerySet.update``), which fires no signals. The service avoids those, so
    this is here for importers and backfill commands.
    """
    try:
        from apps.search import reindex_instances

        reindex_instances(Post, list(posts))
    except Exception:  # noqa: BLE001
        logger.warning("blog: search reindex failed", exc_info=True)
