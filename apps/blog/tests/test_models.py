"""Blog model constraints, derived values and upload hardening.

Every constraint asserted here is load-bearing — each one is the last line of
defence for a specific failure mode named in its test. The ``IntegrityError``
assertions are each wrapped in their own ``transaction.atomic()``: without the
savepoint the enclosing Postgres transaction is poisoned and the *next*
statement fails with "current transaction is aborted", while SQLite shrugs it
off — which is exactly how this class of bug stays invisible in development.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.blog.models import (
    RENDERER_VERSION,
    Blog,
    Delivery,
    Issue,
    Post,
    Subscriber,
    Subscription,
    Tag,
    cover_upload_to,
    derive_excerpt,
    normalize_email,
    validate_cover_image_size,
    validate_unreserved_slug,
)
from apps.search.access import SearchAccess

pytestmark = pytest.mark.django_db


# ── Blog ────────────────────────────────────────────────────────────────────


def test_blog_slug_is_globally_unique(blog, other_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        Blog.objects.create(name="Clash", slug=blog.slug, owner=other_user)


def test_visibility_defaults_to_private(owner):
    """Publishing is always an explicit act — never a default."""
    assert Blog.objects.create(name="New", slug="new", owner=owner).visibility == (
        Blog.Visibility.PRIVATE
    )


@pytest.mark.parametrize(
    ("visibility", "expected"),
    [
        (Blog.Visibility.PUBLIC, SearchAccess.ANONYMOUS),
        (Blog.Visibility.MEMBERS, SearchAccess.AUTHENTICATED),
        (Blog.Visibility.PRIVATE, SearchAccess.STAFF),
    ],
)
def test_required_access_maps_onto_search_access(owner, visibility, expected):
    """The 1:1 mapping is why search, feeds and the sitemap can all derive
    their gate from this single field."""
    b = Blog(name="x", slug="x", owner=owner, visibility=visibility)
    assert b.required_access == expected
    assert b.is_anonymously_readable is (visibility == Blog.Visibility.PUBLIC)


# ── Slug hygiene ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["feed", "api", "tag", "archive", "subscribe", "sitemap.xml"])
def test_reserved_slugs_are_rejected(bad):
    """A post slugged `feed.rss` or a blog slugged `api` would be shadowed by a
    sibling route and silently unreachable."""
    with pytest.raises(ValidationError):
        validate_unreserved_slug(bad)


def test_reserved_check_is_case_insensitive():
    with pytest.raises(ValidationError):
        validate_unreserved_slug("FEED")


def test_ordinary_slugs_pass():
    for ok in ["hello-world", "feeds-i-like", "tagging-things", "api-design"]:
        validate_unreserved_slug(ok)  # must not raise


# ── Post ────────────────────────────────────────────────────────────────────


def test_post_slug_unique_per_blog_but_reusable_across_blogs(blog, other_blog, owner):
    Post.objects.create(blog=blog, title="A", slug="shared", author=owner)
    # Same slug in a different blog is fine — that's the point of scoping.
    Post.objects.create(blog=other_blog, title="A", slug="shared", author=owner)

    with pytest.raises(IntegrityError), transaction.atomic():
        Post.objects.create(blog=blog, title="Dup", slug="shared", author=owner)


def test_post_uid_is_unique_and_autoassigned(post):
    assert isinstance(post.uid, uuid.UUID)
    with pytest.raises(IntegrityError), transaction.atomic():
        Post.objects.create(blog=post.blog, title="X", slug="x", uid=post.uid)


def test_is_live_requires_published_status_and_a_past_timestamp(
    post, draft, scheduled_post, future_published_post
):
    assert post.is_live
    assert not draft.is_live
    assert not scheduled_post.is_live
    # The subtle one: status says published, the clock says not yet.
    assert not future_published_post.is_live


def test_html_staleness_tracks_the_renderer_version(post):
    assert post.html_renderer_version == RENDERER_VERSION
    assert not post.html_is_stale
    post.html_renderer_version = RENDERER_VERSION - 1
    assert post.html_is_stale


def test_ordering_has_a_unique_tiebreaker():
    """Without `-id`, two posts published in the same instant paginate
    non-deterministically on Postgres — duplicating and dropping rows."""
    assert Post._meta.ordering[-1] == "-id"


def test_one_post_per_source_document_per_blog(blog, owner):
    """Stops the runbook bridge forking one document into two posts on a
    double-click or a retried task."""
    from apps.runbook.models import Document

    doc = Document.objects.create(title="Doc", slug="doc", key="doc")
    Post.objects.create(blog=blog, title="P1", slug="p1", author=owner, source_document=doc)

    with pytest.raises(IntegrityError), transaction.atomic():
        Post.objects.create(blog=blog, title="P2", slug="p2", author=owner, source_document=doc)


def test_the_source_document_constraint_is_partial(blog, owner):
    """Many posts may have NO source document — the constraint must not
    collapse every hand-written post into one row."""
    Post.objects.create(blog=blog, title="A", slug="a", author=owner, source_document=None)
    Post.objects.create(blog=blog, title="B", slug="b", author=owner, source_document=None)
    assert Post.objects.filter(source_document__isnull=True).count() == 2


def test_cover_requires_alt_text(blog, owner):
    """Only a validator catches this; a cover with no alt text is an
    accessibility defect that otherwise ships silently."""
    p = Post(blog=blog, title="T", slug="t", author=owner, cover_image="blog/covers/x.png")
    with pytest.raises(ValidationError) as exc:
        p.full_clean(exclude=["cover_image"])
    assert "cover_alt" in exc.value.message_dict

    p.cover_alt = "A photo of a notebook"
    p.full_clean(exclude=["cover_image"])  # must not raise


# ── Cover upload hardening ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    # Distinctive stems: a one-letter stem would appear in a 32-char hex
    # string by chance and make the "name is discarded" assertion vacuous.
    ["photo.png", "PHOTO.JPG", "holiday-snap.jpeg", "zzzqqq.gif", "wxyzwxyz.webp"],
)
def test_cover_upload_discards_the_client_filename(name):
    """The uploader's name is never kept. Keeping it once let `logo.html` be
    stored as such and served with a type guessed from it (runbook audit C7) —
    and blog covers sit under the *public* media prefix with no access-checked
    view in front of them, so it matters more here, not less."""
    path = cover_upload_to(None, name)
    stem = path.rsplit("/", 1)[-1]
    assert path.startswith("blog/covers/")
    assert name.split(".")[0].lower() not in stem.lower()
    # 32 hex chars + the extension
    assert len(stem.split(".")[0]) == 32
    assert stem.endswith("." + name.rsplit(".", 1)[-1].lower())


@pytest.mark.parametrize("name", ["logo.html", "x.svg", "payload.php", "noextension"])
def test_cover_upload_forces_bin_for_unlisted_extensions(name):
    """Anything not an inline-renderable image is stored as `.bin` so it can
    never be rendered or content-sniffed as markup."""
    assert cover_upload_to(None, name).endswith(".bin")


def test_cover_upload_paths_do_not_collide():
    names = {cover_upload_to(None, "a.png") for _ in range(50)}
    assert len(names) == 50


def test_cover_size_limit():
    class _Img:
        size = 6 * 1024 * 1024

    with pytest.raises(ValidationError):
        validate_cover_image_size(_Img())

    _Img.size = 1024
    validate_cover_image_size(_Img())  # must not raise


# ── Tag ─────────────────────────────────────────────────────────────────────


def test_tag_slug_unique_per_blog_but_reusable_across_blogs(blog, other_blog):
    Tag.objects.create(blog=blog, name="Ops", slug="ops")
    Tag.objects.create(blog=other_blog, name="Ops", slug="ops")  # different tenant, fine

    with pytest.raises(IntegrityError), transaction.atomic():
        Tag.objects.create(blog=blog, name="Ops again", slug="ops")


# ── Subscriber / Subscription ───────────────────────────────────────────────


def test_subscriber_email_is_unique(subscriber):
    with pytest.raises(IntegrityError), transaction.atomic():
        Subscriber.objects.create(email=subscriber.email)


def test_normalize_email_collapses_case_and_whitespace():
    """`unique=True` is case-sensitive on Postgres and collation-dependent on
    SQLite, so normalising on write is the portable guarantee."""
    assert normalize_email("  A@B.com ") == "a@b.com"
    assert normalize_email("") == ""
    assert normalize_email(None) == ""  # type: ignore[arg-type]


def test_normalized_addresses_collide(db):
    Subscriber.objects.create(email=normalize_email("A@B.com"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Subscriber.objects.create(email=normalize_email("a@b.com"))


def test_one_subscription_per_subscriber_blog_pair(confirmed_sub):
    with pytest.raises(IntegrityError), transaction.atomic():
        Subscription.objects.create(
            subscriber=confirmed_sub.subscriber, blog=confirmed_sub.blog
        )


def test_subscription_defaults_to_pending(blog, subscriber):
    s = Subscription.objects.create(subscriber=subscriber, blog=blog)
    assert s.status == Subscription.Status.PENDING
    assert s.token_version == 1
    assert s.confirmed_at is None


# ── Issue / Delivery ────────────────────────────────────────────────────────


@pytest.mark.parametrize("live_status", ["queued", "sending", "sent"])
def test_only_one_live_issue_per_post(blog, post, live_status):
    """The outermost idempotency layer: "publish → send an issue" can never
    open a second campaign for the same post."""
    Issue.objects.create(blog=blog, post=post, subject="First", status=live_status)
    with pytest.raises(IntegrityError), transaction.atomic():
        Issue.objects.create(blog=blog, post=post, subject="Second", status=live_status)


def test_a_dead_issue_does_not_block_a_new_one(blog, post):
    """draft/canceled/failed are outside the constraint, so a cancelled send
    can be retried as a fresh issue."""
    Issue.objects.create(blog=blog, post=post, subject="Cancelled", status="canceled")
    Issue.objects.create(blog=blog, post=post, subject="Failed", status="failed")
    Issue.objects.create(blog=blog, post=post, subject="Retry", status="queued")
    assert Issue.objects.filter(post=post).count() == 3


def test_issues_without_a_post_are_unconstrained(blog):
    """A standalone issue (not derived from a post) has post=NULL; the partial
    unique index must not treat them all as the same row."""
    Issue.objects.create(blog=blog, subject="Standalone A", status="sent")
    Issue.objects.create(blog=blog, subject="Standalone B", status="sent")
    assert Issue.objects.filter(post__isnull=True).count() == 2


def test_issue_is_editable_only_before_it_is_queued(blog):
    assert Issue(blog=blog, status="draft").is_editable
    assert Issue(blog=blog, status="scheduled").is_editable
    for locked in ("queued", "sending", "sent", "failed", "canceled"):
        assert not Issue(blog=blog, status=locked).is_editable


def test_delivery_is_unique_per_issue_and_subscriber(issue, subscriber):
    """THE no-double-send guarantee, and what makes queue_issue re-runnable."""
    Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)
    with pytest.raises(IntegrityError), transaction.atomic():
        Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)


def test_delivery_bulk_create_is_idempotent(issue, subscriber):
    """`ignore_conflicts=True` relies on the constraint above — this is how
    re-queueing an issue adds no duplicate recipients."""
    rows = [Delivery(issue=issue, subscriber=subscriber, email=subscriber.email)]
    Delivery.objects.bulk_create(rows, ignore_conflicts=True)
    Delivery.objects.bulk_create(
        [Delivery(issue=issue, subscriber=subscriber, email=subscriber.email)],
        ignore_conflicts=True,
    )
    assert Delivery.objects.filter(issue=issue).count() == 1


def test_delivery_keeps_the_address_when_the_subscriber_goes_away(issue, subscriber):
    """The log must survive as an audit record after the identity is removed."""
    Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)
    subscriber.delete()
    d = Delivery.objects.get(issue=issue)
    assert d.subscriber_id is None
    assert d.email == "reader@example.test"


# ── Derived values ──────────────────────────────────────────────────────────


def test_derive_excerpt_skips_headings_fences_and_images():
    body = (
        "# A Title\n\n"
        "![cover](/x.png)\n\n"
        "```\ncode = 1\n```\n\n"
        "The actual first sentence.\nStill the same paragraph.\n\n"
        "A second paragraph that should be ignored.\n"
    )
    out = derive_excerpt(body)
    assert out == "The actual first sentence. Still the same paragraph."


def test_derive_excerpt_truncates_with_an_ellipsis():
    out = derive_excerpt("x" * 500, limit=50)
    assert len(out) == 50
    assert out.endswith("…")


def test_derive_excerpt_handles_empty_input():
    assert derive_excerpt("") == ""
    assert derive_excerpt("# Only a heading") == ""


def test_str_methods_are_human_readable(blog, post, subscriber, confirmed_sub, issue):
    assert str(blog) == "Field Notes"
    assert str(post) == "Hello World"
    assert str(subscriber) == "reader@example.test"
    assert "Field Notes" in str(confirmed_sub)
    assert str(issue) == "Issue 1"
    d = Delivery(issue=issue, email="x@y.test", status="sent")
    assert str(d) == "x@y.test (sent)"


def test_timestamps_are_timezone_aware(post):
    """All 'already sent?' and 'is it live?' logic compares aware datetimes."""
    assert timezone.is_aware(post.created_at)
    assert timezone.is_aware(post.published_at)
