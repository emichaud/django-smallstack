"""Blog models — Blog, Post, Tag, and the newsletter side (Subscriber,
Subscription, Issue, Delivery).

Seven models, one migration. The newsletter half is unused until the send
pipeline lands, but it ships in ``0001`` so the app label and the schema are
settled once rather than churned across releases.

Two conventions worth knowing before you read on:

* **All writes go through** ``apps.blog.service`` (runbook's discipline). The
  models carry constraints and derived-value helpers, not business rules.
* **Visibility is a three-way ladder**, not a boolean — see :class:`Blog`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.html import strip_tags

from apps.search.access import SearchAccess

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Slug hygiene
# ---------------------------------------------------------------------------

# Path segments the public URLconf claims for itself. A Blog slugged "api" or a
# Post slugged "feed.rss" would be shadowed by a sibling route and silently
# unreachable; the post namespace is a catch-all under the blog slug, so this
# is the only thing standing between a well-meaning title and a 404 nobody can
# explain. Checked by `validate_unreserved_slug`, enforced in the service.
RESERVED_BLOG_SLUGS: frozenset[str] = frozenset({
    "admin", "api", "feed", "feeds", "media", "search", "sitemap", "sitemap.xml",
    "static", "subscribe", "unsubscribe", "confirm", "newsletter", "tag", "tags",
    # "p" is the post-shortlink prefix (/blog/p/<uuid>/). It was the one fixed
    # segment in public_urls.py missing from this set. Route order saves it
    # today — path("p/<uuid:uid>/") is registered before <slug:blog_slug>/ — but
    # this set is the stated defence, and "a false negative costs an
    # unreachable page" is a poor thing to leave resting on declaration order.
    "p",
    # NB the other fixed segment, "feed.json", needs no entry: SlugField rejects
    # dots, so it can never be a blog slug. The dotted names already here
    # ("sitemap.xml") are belt-and-braces for the same reason.
})
RESERVED_POST_SLUGS: frozenset[str] = frozenset({
    "archive", "feed", "feed.atom", "feed.json", "feed.rss", "feeds",
    "newsletter", "search", "subscribe", "tag", "tags",
})


def validate_unreserved_slug(value: str) -> None:
    """Reject slugs that would collide with a public route.

    Deliberately checks the union of both reserved sets, so one validator can
    sit on every slug field — a false positive costs an author one word, a
    false negative costs an unreachable page.
    """
    if value.lower() in RESERVED_BLOG_SLUGS | RESERVED_POST_SLUGS:
        raise ValidationError(
            f"'{value}' is reserved by the blog's own URLs. Pick another slug.",
            code="reserved_slug",
        )


# ---------------------------------------------------------------------------
# Cover images
# ---------------------------------------------------------------------------

# Extensions served inline as images. Anything else is stored under a `.bin`
# name so it can never be rendered or sniffed as markup.
COVER_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
MAX_COVER_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB, matching UserProfile photos


def validate_cover_image_size(image: Any) -> None:
    """Cap cover uploads at 5MB (same limit as profile photos)."""
    if image.size > MAX_COVER_IMAGE_BYTES:
        raise ValidationError(
            f"Image file too large. Maximum size is {MAX_COVER_IMAGE_BYTES // (1024 * 1024)}MB."
        )


def cover_upload_to(instance: "Post", filename: str) -> str:
    """Server-generated storage name; the uploader's filename is discarded.

    Same hardening as ``runbook.models.document_image_upload_to``, which exists
    because keeping the client's name once let ``logo.html`` be stored as such
    and served with a type guessed from it (audit C7). Blog covers live under
    the *public* ``blog/`` media prefix, so that matters more here, not less:
    unlike runbook files there is no access-checked view in front of them.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in COVER_IMAGE_EXTENSIONS:
        ext = ".bin"
    return f"blog/covers/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


# ---------------------------------------------------------------------------
# Blog — the channel
# ---------------------------------------------------------------------------


class Blog(models.Model):
    """A publication: an owner, a slug, and a visibility level.

    This is the "channel" posts are published into. Each blog is independently
    addressable at ``/blog/<slug>/`` with its own feeds, tags, archive and
    newsletter list.
    """

    class Visibility(models.TextChoices):
        """Who may read this blog.

        A three-way ladder rather than ``is_public: bool``, for two reasons.
        First, ``Runbook.is_public`` already means *signed-in users* — a
        ``Blog.is_public`` meaning *anonymous*, one import away, is a bug
        waiting to be written. Second, an internal team blog readable by every
        colleague and invisible to the internet is a real and common case that
        a boolean cannot express, and the workaround is always a bespoke mixin.

        The levels map 1:1 onto ``SearchAccess``, so search, feeds and the
        sitemap all derive their gate from this one field.
        """

        PRIVATE = "private", "Private — owner and staff only"
        MEMBERS = "members", "Members — any signed-in user"
        PUBLIC = "public", "Public — anyone on the internet"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blogs",
        help_text="NULL = a staff-managed house blog.",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=80,
        unique=True,
        validators=[validate_unreserved_slug],
        help_text="First segment of the public URL: /blog/<slug>/.",
    )
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        db_index=True,
        help_text="Private by default — publishing is always an explicit act.",
    )

    # -- Newsletter settings (inert until the blog opts in) ------------------
    newsletter_enabled = models.BooleanField(default=False)
    newsletter_from_name = models.CharField(max_length=100, blank=True)
    newsletter_reply_to = models.EmailField(blank=True)
    newsletter_footer_markdown = models.TextField(
        blank=True,
        help_text="Appended to every issue. CAN-SPAM wants a postal address and a "
        "line explaining why the reader is receiving this.",
    )
    double_opt_in = models.BooleanField(
        default=True,
        help_text="Require an emailed confirmation before a subscriber receives anything.",
    )
    email_template = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional per-blog email template override; blank uses the generic wrapper.",
    )
    mailer_alias = models.CharField(
        max_length=40,
        blank=True,
        help_text="MAILERS alias used for bulk sends. Routing a blast through a "
        "second alias keeps it off the transactional mail's IP/domain reputation.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["owner", "name"], name="blog_blog_owner_idx")]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("blog:blog_detail", kwargs={"blog_slug": self.slug})

    @property
    def required_access(self) -> str:
        """This blog's visibility as a :class:`SearchAccess` level.

        The 1:1 mapping is why search, feeds and the sitemap can all derive
        their gate from this single field instead of each inventing one.
        """
        if self.visibility == self.Visibility.PUBLIC:
            return SearchAccess.ANONYMOUS
        if self.visibility == self.Visibility.MEMBERS:
            return SearchAccess.AUTHENTICATED
        return SearchAccess.STAFF

    @property
    def is_anonymously_readable(self) -> bool:
        return self.visibility == self.Visibility.PUBLIC


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------


class Tag(models.Model):
    """A per-blog tag.

    Scoped to a blog rather than global because the tag page is itself
    per-blog (``/blog/<blog>/tag/<tag>/``), so a shared table would need a
    ``posts__blog`` filter on every read and one omission cross-lists tenants.
    A global namespace is also first-writer-wins on display name and casing,
    and the vocabulary itself leaks what other tenants write about.

    Rolling these *up* into a global topic later is additive (a nullable FK
    plus a backfill); splitting a shared table *down* into tenants is not.
    """

    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=60, validators=[validate_unreserved_slug])
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["blog", "slug"], name="blog_tag_slug_per_blog"),
        ]
        indexes = [models.Index(fields=["blog", "name"], name="blog_tag_blog_name_idx")]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse(
            "blog:tag", kwargs={"blog_slug": self.blog.slug, "tag_slug": self.slug}
        )


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------

# Bumped whenever the shared markdown renderer's output changes, so
# `service.rerender_posts(stale_only=True)` can find the rows that need
# re-rendering instead of re-parsing every post in the table.
RENDERER_VERSION = 1


class Post(models.Model):
    """A blog post. ``body_markdown`` is the source of truth; ``body_html`` is
    a cache of the hardened render."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    # Stable across database restores and environment copies, unlike pk —
    # feed GUIDs and newsletter Message-IDs must never be reused or shift.
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts",
    )

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, validators=[validate_unreserved_slug])

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    # Two fields, not one. Collapsing them makes "did this actually go live?"
    # unanswerable when the publisher tick runs late: `scheduled_for` is intent,
    # `published_at` is fact, and the idempotency guard needs both.
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)

    body_markdown = models.TextField(blank=True)
    body_html = models.TextField(blank=True, editable=False)
    body_toc = models.TextField(blank=True, editable=False)
    html_renderer_version = models.PositiveSmallIntegerField(
        default=RENDERER_VERSION, editable=False
    )

    excerpt = models.TextField(
        blank=True,
        help_text="Used by lists, feeds, search results, the newsletter preview and "
        "the OpenGraph description. Auto-derived from the body when blank.",
    )
    cover_image = models.ImageField(
        upload_to=cover_upload_to,
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["png", "jpg", "jpeg", "gif", "webp"]),
            validate_cover_image_size,
        ],
    )
    cover_alt = models.CharField(max_length=255, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="posts")
    canonical_url = models.URLField(
        blank=True, help_text="Set when this post was first published elsewhere."
    )
    is_featured = models.BooleanField(default=False)
    allow_newsletter = models.BooleanField(
        default=True, help_text="May this post be sent as a newsletter issue?"
    )

    # -- Runbook provenance --------------------------------------------------
    source_document = models.ForeignKey(
        "smallstack_runbook.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts",
    )
    # The FK gives integrity, select_related and a related tab; this UUID copy
    # costs one column and keeps the provenance readable after the document is
    # hard-deleted (runbook supports that), because Document.uid is documented
    # as the container-independent canonical address.
    source_document_uid = models.UUIDField(null=True, blank=True, db_index=True)
    source_version = models.IntegerField(
        null=True, blank=True, help_text="Document.version at the last sync."
    )
    source_synced_at = models.DateTimeField(null=True, blank=True)
    source_sync = models.CharField(
        max_length=8,
        choices=[("manual", "Manual"), ("auto", "Auto on change")],
        default="manual",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # `-id` is not decoration: Postgres returns an arbitrary order for equal
        # sort keys where SQLite usually *looks* sorted, so without a unique
        # tiebreaker pagination silently duplicates and drops posts published in
        # the same minute — in production only.
        ordering = ["-published_at", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["blog", "slug"], name="blog_post_slug_per_blog"),
            # Stops the runbook bridge forking one document into two posts in a
            # blog on a double-click or a retried task.
            models.UniqueConstraint(
                fields=["blog", "source_document"],
                condition=models.Q(source_document__isnull=False),
                name="blog_post_one_per_source_doc",
            ),
        ]
        indexes = [
            models.Index(fields=["blog", "status", "-published_at"], name="blog_post_blogfeed_idx"),
            models.Index(fields=["status", "-published_at"], name="blog_post_sitefeed_idx"),
            models.Index(fields=["status", "scheduled_for"], name="blog_post_due_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        """The **public** permalink.

        Feeds, the sitemap, newsletter bodies and OpenGraph tags all need the
        reader-facing URL, so that is what this returns — even for a draft,
        whose permalink correctly 404s for everyone but its owner. The
        authoring page is :attr:`console_url`.

        Note the search layer links hits via the CRUDView's ``-detail`` route,
        not this method, so an author's own draft hit lands on the console.
        """
        return reverse(
            "blog:post_detail", kwargs={"blog_slug": self.blog.slug, "post_slug": self.slug}
        )

    @property
    def console_url(self) -> str:
        """The authoring page, or ``""`` if the console isn't mounted."""
        try:
            return reverse("blog/posts-detail", kwargs={"pk": self.pk})
        except NoReverseMatch:
            return ""

    @property
    def public_url(self) -> str:
        """:meth:`get_absolute_url`, or ``""`` when the public surface is off.

        Templates and console chrome use this; feeds, the sitemap and the
        newsletter use ``get_absolute_url`` and *should* fail loudly if the
        reading surface they are advertising does not exist.
        """
        try:
            return self.get_absolute_url()
        except NoReverseMatch:
            return ""

    @property
    def safe_canonical_url(self) -> str:
        """``canonical_url`` if it is safe to put in an ``href``, else ``""``.

        ``canonical_url`` is a ``URLField``, so every *user-facing* surface
        already refuses a dangerous scheme — ``URLValidator`` allows only
        http/https/ftp/ftps, and the REST, MCP and studio form paths all run it.
        But the service layer does not call ``full_clean()``, so a trusted
        internal caller (a shell session, a data import, a migration) can store
        anything, and the template rendered it straight into an ``<a href>`` and
        a ``<link rel=canonical>``.

        That is not a reachable XSS today; it is the belt to that braces. A
        stored ``javascript:`` would otherwise be one click from executing in
        the page's origin, and the thing standing between them would be a
        validator the writer bypassed.
        """
        url = (self.canonical_url or "").strip()
        if not url:
            return ""
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        # Relative URLs ("/elsewhere/") carry no scheme and are safe.
        return url if scheme in ("", "http", "https") else ""

    @property
    def is_live(self) -> bool:
        """Published *and* past its publication moment."""
        return (
            self.status == self.Status.PUBLISHED
            and self.published_at is not None
            and self.published_at <= timezone.now()
        )

    @property
    def html_is_stale(self) -> bool:
        return self.html_renderer_version != RENDERER_VERSION

    def clean(self) -> None:
        super().clean()
        # Only a validator catches this, and a cover with no alt text is an
        # accessibility defect that ships silently.
        if self.cover_image and not self.cover_alt.strip():
            raise ValidationError(
                {"cover_alt": "Describe the cover image for screen readers."}
            )


# ---------------------------------------------------------------------------
# Newsletter — Subscriber, Subscription
# ---------------------------------------------------------------------------


class Subscriber(models.Model):
    """An email identity, deliberately decoupled from ``AUTH_USER_MODEL``.

    **Global, not per-blog**, and rows are **never deleted**. Suppression and
    bounce history are properties of an *address*, so unsubscribing is a state
    transition on :class:`Subscription`; hard-deleting the identity throws away
    the knowledge that an address bounces and lets a re-import resurrect
    someone who opted out.
    """

    # Normalised to lowercase on every write path, because unique=True is
    # case-sensitive on Postgres and collation-dependent on SQLite. Cheaper and
    # more portable than a UniqueConstraint(Lower("email")).
    email = models.EmailField(max_length=254, unique=True)
    name = models.CharField(max_length=120, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_subscribers",
        help_text="Incidental link when the subscriber also has an account.",
    )

    is_suppressed = models.BooleanField(default=False, db_index=True)
    suppressed_at = models.DateTimeField(null=True, blank=True)
    suppression_reason = models.CharField(max_length=200, blank=True)
    bounce_count = models.PositiveIntegerField(default=0)
    # Counted across issues and reset on any success, so one transient SMTP
    # hiccup can't permanently suppress a good address.
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_failure_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email


class Subscription(models.Model):
    """One subscriber's relationship with one blog's newsletter."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"

    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="subscriptions"
    )
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name="subscriptions")
    status = models.CharField(
        max_length=14, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    source = models.CharField(
        max_length=40, blank=True, help_text="web | import | api | mcp | staff"
    )
    consent_note = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where consent came from. Required when importing a list.",
    )
    # Embedded in every confirm/unsubscribe token and bumped on re-subscribe,
    # so an unsubscribe link from an old email cannot silently kill a fresh
    # signup. This is the replay defence.
    token_version = models.PositiveIntegerField(default=1)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["subscriber", "blog"], name="blog_subscription_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["blog", "status"], name="blog_sub_blog_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber} → {self.blog}"


# ---------------------------------------------------------------------------
# Newsletter — Issue, Delivery
# ---------------------------------------------------------------------------


class Issue(models.Model):
    """One newsletter send: a subject, a frozen body, and an audience."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name="issues")
    post = models.ForeignKey(
        Post, on_delete=models.SET_NULL, null=True, blank=True, related_name="issues"
    )

    subject = models.CharField(max_length=200)
    preheader = models.CharField(
        max_length=200, blank=True, help_text="Preview line shown after the subject in inboxes."
    )
    body_markdown = models.TextField(blank=True)
    # A snapshot taken when the issue is queued, never a live read of the post:
    # editing the post next month must not rewrite what subscribers were sent.
    # The issue is the record of what went out.
    body_html = models.TextField(blank=True, editable=False)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    recipient_count = models.PositiveIntegerField(
        default=0, help_text="Audience size frozen at queue time."
    )
    # Display conveniences. The Delivery rows are the source of truth — these
    # are denormalised counters and may lag mid-send.
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_issues",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # The outermost idempotency layer: "publish → send an issue" can
            # never create a second live campaign for the same post.
            models.UniqueConstraint(
                fields=["post"],
                condition=models.Q(status__in=["queued", "sending", "sent"]),
                name="blog_issue_one_live_per_post",
            ),
        ]
        indexes = [
            models.Index(fields=["blog", "status", "-created_at"], name="blog_issue_blog_idx"),
            models.Index(fields=["status", "scheduled_for"], name="blog_issue_due_idx"),
        ]

    def __str__(self) -> str:
        return self.subject

    @property
    def is_editable(self) -> bool:
        return self.status in {self.Status.DRAFT, self.Status.SCHEDULED}

    @property
    def progress_percent(self) -> int:
        """How far a send has got, 0-100. For the console's progress bar."""
        if not self.recipient_count:
            return 0
        done = self.sent_count + self.failed_count
        return min(100, round(done * 100 / self.recipient_count))


class Delivery(models.Model):
    """One issue, one recipient. **This table is the progress ledger.**

    Materialised up front by ``service.queue_issue`` so a send is resumable:
    a worker killed mid-batch leaves ``claimed`` rows, the reaper returns them
    to ``pending``, and the next tick finishes the job without re-sending
    anything already ``sent``.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CLAIMED = "claimed", "Claimed"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="deliveries")
    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.SET_NULL, null=True, blank=True, related_name="deliveries"
    )
    # Snapshot of the address actually used, so the log survives as an audit
    # record even once `subscriber` is nulled.
    email = models.EmailField(max_length=254)

    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            # THE no-double-send guarantee, and what makes queue_issue
            # re-runnable via bulk_create(ignore_conflicts=True).
            models.UniqueConstraint(
                fields=["issue", "subscriber"], name="blog_delivery_once_per_issue"
            ),
        ]
        indexes = [
            models.Index(fields=["issue", "status"], name="blog_delivery_issue_idx"),
            models.Index(fields=["status", "claimed_at"], name="blog_delivery_claim_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.email} ({self.status})"


def normalize_email(email: str) -> str:
    """Lowercase + strip. The single normalisation for subscriber addresses.

    Lives here rather than in the service so the model layer, forms and
    imports cannot disagree about what counts as the same address.
    """
    return (email or "").strip().lower()


def derive_excerpt(markdown_text: str, *, limit: int = 240) -> str:
    """First prose paragraph of a markdown body, flattened to plain text.

    Skips headings, fences, quotes, list markers and images so the excerpt
    reads as a sentence rather than "# Title".
    """
    lines: list[str] = []
    in_fence = False
    for raw in (markdown_text or "").splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not line:
            if lines:
                break
            continue
        if line.startswith(("#", ">", "|", "---", "===")) or line.startswith("!["):
            continue
        lines.append(line.lstrip("-*+ ").strip())
    # strip_tags because the excerpt is contractually *plain text*: it reaches
    # feeds, search snippets and the OpenGraph description, and a body that
    # opens with raw markup should not put angle brackets in all three.
    # Consumers must still escape — this is tidiness, not the XSS defence
    # (that is the hardened renderer, applied to body_html).
    text = strip_tags(" ".join(lines)).strip()
    return text[: limit - 1].rstrip() + "…" if len(text) > limit else text


def reserved_slugs_for(kind: str) -> frozenset[str]:
    """Reserved slugs for ``"blog"`` or ``"post"`` (used by the service)."""
    return RESERVED_BLOG_SLUGS if kind == "blog" else RESERVED_POST_SLUGS


def issue_body_source(issue: Issue) -> str:
    """The markdown an issue should render from: its own, else its post's."""
    if issue.body_markdown.strip():
        return issue.body_markdown
    return issue.post.body_markdown if issue.post_id and issue.post else ""


def subscriber_is_sendable(sub: Optional[Subscriber]) -> bool:
    """Whether an address may receive bulk mail right now."""
    return sub is not None and not sub.is_suppressed
