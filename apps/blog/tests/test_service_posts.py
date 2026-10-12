"""The post half of the service layer.

Two properties matter most here and are asserted the hard way:

1. **Publishing is idempotent** — a double-click or a retried task must not
   move a post's date and reorder every feed.
2. **The scheduled publisher fires `post_save`** — it iterates and saves row by
   row rather than using `queryset.update()`, because the shortcut would skip
   the search reindex, the webhook fan-out and the HTML render. That is the
   likeliest silent bug in the feature, so the test watches for the signal
   rather than just the status column.
"""

from __future__ import annotations

import pytest
from django.db.models.signals import post_save
from django.utils import timezone

from apps.blog import service
from apps.blog.models import RENDERER_VERSION, Blog, Post, Tag

pytestmark = pytest.mark.django_db


# ── create_post ─────────────────────────────────────────────────────────────


def test_create_post_starts_as_a_draft_and_renders(blog, owner):
    p = service.create_post(blog, title="My Post", body_markdown="# Hi\n\nSome prose.", actor=owner)
    assert p.status == Post.Status.DRAFT
    assert p.published_at is None
    assert "<h1" in p.body_html
    assert p.body_toc
    assert p.html_renderer_version == RENDERER_VERSION
    assert p.author == owner
    assert p.slug == "my-post"


def test_create_post_derives_the_excerpt_when_blank(blog, owner):
    p = service.create_post(
        blog, title="T", body_markdown="# Heading\n\nThe first sentence.", actor=owner
    )
    assert p.excerpt == "The first sentence."


def test_create_post_keeps_an_explicit_excerpt(blog, owner):
    p = service.create_post(
        blog, title="T", body_markdown="# H\n\nBody.", excerpt="Hand written.", actor=owner
    )
    assert p.excerpt == "Hand written."


def test_create_post_deduplicates_slugs_within_a_blog(blog, owner):
    a = service.create_post(blog, title="Same Name", actor=owner)
    b = service.create_post(blog, title="Same Name", actor=owner)
    assert a.slug == "same-name"
    assert b.slug == "same-name-2"


def test_create_post_sidesteps_reserved_slugs_instead_of_failing(blog, owner):
    """An author who titles a post "Feed" should not meet a validation error
    about a routing detail they have no reason to know about."""
    p = service.create_post(blog, title="Feed", actor=owner)
    assert p.slug == "feed-2"


def test_create_post_requires_a_title(blog, owner):
    with pytest.raises(service.InvalidState):
        service.create_post(blog, title="   ", actor=owner)


def test_create_post_handles_a_title_that_slugifies_to_nothing(blog, owner):
    p = service.create_post(blog, title="日本語", actor=owner)
    assert p.slug  # never empty — an empty slug would be an unroutable URL


def test_create_post_attaches_tags_by_name(blog, owner):
    p = service.create_post(blog, title="T", tags=["Ops", "On Call"], actor=owner)
    assert set(p.tags.values_list("slug", flat=True)) == {"ops", "on-call"}


def test_create_post_refuses_a_blog_you_do_not_own(other_blog, owner):
    with pytest.raises(service.NotAuthorized):
        service.create_post(other_blog, title="Intrusion", actor=owner)


def test_actor_none_is_a_trusted_internal_caller(other_blog):
    """Tasks, CLI commands and backfills pass actor=None and skip the gate."""
    assert service.create_post(other_blog, title="From a task", actor=None).pk


# ── update_post ─────────────────────────────────────────────────────────────


def test_update_post_rerenders_when_the_body_changes(draft, owner):
    service.update_post(draft, body_markdown="## New heading", actor=owner)
    draft.refresh_from_db()
    assert "<h2" in draft.body_html


@pytest.mark.parametrize(
    "field", ["status", "published_at", "scheduled_for", "body_html", "source_document"]
)
def test_update_post_refuses_to_set_derived_or_lifecycle_fields(draft, owner, field):
    """Letting a generic update move these is how a post ends up published
    with no rendered HTML, or live with a stale body."""
    with pytest.raises(service.InvalidState):
        service.update_post(draft, actor=owner, **{field: "x"})


def test_update_post_reslugs_uniquely(blog, draft, owner):
    service.create_post(blog, title="Taken", slug="taken", actor=owner)
    service.update_post(draft, slug="taken", actor=owner)
    draft.refresh_from_db()
    assert draft.slug == "taken-2"


def test_update_post_refuses_a_stranger(draft, other_user):
    with pytest.raises(service.NotAuthorized):
        service.update_post(draft, title="Defaced", actor=other_user)


# ── publish / unpublish ─────────────────────────────────────────────────────


def test_publish_sets_status_and_timestamp_and_renders(draft, owner):
    before = timezone.now()
    p = service.publish_post(draft, actor=owner)
    assert p.status == Post.Status.PUBLISHED
    assert p.published_at is not None and p.published_at >= before
    assert p.is_live
    assert "<p>" in p.body_html


def test_publish_is_idempotent_and_does_not_move_the_date(post, owner):
    """A double-click must not re-date the post and reorder every feed."""
    original = post.published_at
    service.publish_post(post, actor=owner)
    service.publish_post(post, actor=owner)
    post.refresh_from_db()
    assert post.published_at == original


def test_publish_clears_a_pending_schedule(scheduled_post, owner):
    p = service.publish_post(scheduled_post, actor=owner)
    assert p.scheduled_for is None
    assert p.status == Post.Status.PUBLISHED


def test_unpublish_clears_the_timestamp_too(post, owner):
    """Leaving published_at set would make a draft look live to is_live and to
    any filter that checks the timestamp rather than the status."""
    p = service.unpublish_post(post, actor=owner)
    assert p.status == Post.Status.DRAFT
    assert p.published_at is None
    assert not p.is_live


def test_archive_keeps_the_post_but_takes_it_off_the_lists(post, owner):
    p = service.archive_post(post, actor=owner)
    assert p.status == Post.Status.ARCHIVED
    assert not p.is_live
    from apps.blog import permissions

    assert post not in permissions.public_posts()


def test_publish_refuses_a_stranger(draft, other_user):
    with pytest.raises(service.NotAuthorized):
        service.publish_post(draft, actor=other_user)


# ── schedule ────────────────────────────────────────────────────────────────


def test_schedule_sets_intent_without_publishing(draft, owner):
    when = timezone.now() + timezone.timedelta(days=1)
    p = service.schedule_post(draft, when=when, actor=owner)
    assert p.status == Post.Status.SCHEDULED
    assert p.scheduled_for == when
    assert p.published_at is None
    assert not p.is_live


def test_schedule_refuses_a_past_time(draft, owner):
    """"Schedule" and "publish" are different intents; silently doing the
    second when asked for the first is how an embargo gets broken."""
    with pytest.raises(service.InvalidState):
        service.schedule_post(
            draft, when=timezone.now() - timezone.timedelta(minutes=1), actor=owner
        )


def test_schedule_refuses_a_naive_datetime(draft, owner):
    import datetime as _dt

    with pytest.raises(service.InvalidState):
        service.schedule_post(draft, when=_dt.datetime(2099, 1, 1), actor=owner)


# ── publish_due_posts — the tick ────────────────────────────────────────────


def test_publish_due_posts_publishes_only_what_is_due(blog, owner):
    now = timezone.now()
    due = Post.objects.create(
        blog=blog, title="Due", slug="due", author=owner,
        status=Post.Status.SCHEDULED, scheduled_for=now - timezone.timedelta(minutes=5),
    )
    later = Post.objects.create(
        blog=blog, title="Later", slug="later-2", author=owner,
        status=Post.Status.SCHEDULED, scheduled_for=now + timezone.timedelta(days=1),
    )

    published = service.publish_due_posts()
    assert published == [due.pk]

    due.refresh_from_db()
    later.refresh_from_db()
    assert due.status == Post.Status.PUBLISHED
    assert later.status == Post.Status.SCHEDULED


def test_publish_due_posts_fires_post_save(blog, owner):
    """The `.update()` trap. A queryset update would flip the status in one
    query and fire NO post_save — so nothing would reindex the post for search,
    nothing would fan out a webhook, and body_html would never be refreshed.
    Watching for the signal is the only assertion that catches that rewrite."""
    seen: list[int] = []

    def _receiver(sender, instance, **kwargs):
        seen.append(instance.pk)

    post_save.connect(_receiver, sender=Post, dispatch_uid="blog-test-due")
    try:
        p = Post.objects.create(
            blog=blog, title="Due", slug="due-signal", author=owner,
            status=Post.Status.SCHEDULED,
            scheduled_for=timezone.now() - timezone.timedelta(minutes=1),
        )
        seen.clear()
        service.publish_due_posts()
    finally:
        post_save.disconnect(sender=Post, dispatch_uid="blog-test-due")

    assert p.pk in seen, "publish_due_posts must save per row, not queryset.update()"


def test_publish_due_posts_records_the_real_go_live_moment(blog, owner):
    """A tick running four minutes late should say so: scheduled_for is intent,
    published_at is fact."""
    intent = timezone.now() - timezone.timedelta(minutes=4)
    p = Post.objects.create(
        blog=blog, title="Late", slug="late", author=owner,
        status=Post.Status.SCHEDULED, scheduled_for=intent,
    )
    service.publish_due_posts()
    p.refresh_from_db()
    assert p.published_at > intent


def test_publish_due_posts_is_resilient_to_one_bad_row(blog, owner, monkeypatch):
    """One failure must not strand the rest of the queue."""
    now = timezone.now()
    bad = Post.objects.create(
        blog=blog, title="Bad", slug="bad", author=owner,
        status=Post.Status.SCHEDULED, scheduled_for=now - timezone.timedelta(minutes=9),
    )
    good = Post.objects.create(
        blog=blog, title="Good", slug="good", author=owner,
        status=Post.Status.SCHEDULED, scheduled_for=now - timezone.timedelta(minutes=8),
    )

    real = service.publish_post

    def _flaky(post, **kwargs):
        if post.pk == bad.pk:
            raise RuntimeError("boom")
        return real(post, **kwargs)

    monkeypatch.setattr(service, "publish_post", _flaky)
    published = service.publish_due_posts()

    assert published == [good.pk]
    good.refresh_from_db()
    assert good.status == Post.Status.PUBLISHED


def test_due_post_count_is_the_monitor_signal(blog, owner):
    assert service.due_post_count() == 0
    Post.objects.create(
        blog=blog, title="Overdue", slug="overdue", author=owner,
        status=Post.Status.SCHEDULED,
        scheduled_for=timezone.now() - timezone.timedelta(hours=2),
    )
    assert service.due_post_count() == 1


# ── rerender ────────────────────────────────────────────────────────────────


def test_rerender_touches_only_stale_rows(post, draft):
    Post.objects.filter(pk=post.pk).update(html_renderer_version=RENDERER_VERSION - 1)
    assert service.rerender_posts(stale_only=True) == 1
    post.refresh_from_db()
    assert post.html_renderer_version == RENDERER_VERSION


def test_rerender_all_touches_everything(post, draft):
    assert service.rerender_posts(stale_only=False) == 2


def test_rerender_repairs_html_that_drifted_from_the_markdown(post):
    """The point of the version column: find and fix rows whose cached HTML no
    longer reflects the renderer."""
    Post.objects.filter(pk=post.pk).update(
        body_html="<p>stale</p>", html_renderer_version=RENDERER_VERSION - 1
    )
    service.rerender_posts(stale_only=True)
    post.refresh_from_db()
    assert "stale" not in post.body_html
    assert "<h1" in post.body_html


# ── tags ────────────────────────────────────────────────────────────────────


def test_set_post_tags_replaces_rather_than_appends(post, owner):
    service.set_post_tags(post, ["a", "b"], actor=owner)
    service.set_post_tags(post, ["b", "c"], actor=owner)
    assert set(post.tags.values_list("slug", flat=True)) == {"b", "c"}


def test_set_post_tags_reuses_existing_tags(blog, post, owner):
    existing = Tag.objects.create(blog=blog, name="Ops", slug="ops")
    service.set_post_tags(post, ["Ops"], actor=owner)
    assert list(post.tags.all()) == [existing]
    assert Tag.objects.filter(blog=blog, slug="ops").count() == 1


def test_set_post_tags_ignores_blanks_and_duplicates(post, owner):
    tags = service.set_post_tags(post, ["Ops", "ops", "  ", "", "OPS"], actor=owner)
    assert len(tags) == 1


def test_set_post_tags_cannot_borrow_another_blogs_tag(blog, other_blog, post, owner):
    """Tags are per-blog, so a same-named tag elsewhere is a different row."""
    theirs = Tag.objects.create(blog=other_blog, name="Ops", slug="ops")
    service.set_post_tags(post, ["Ops"], actor=owner)
    mine = post.tags.get()
    assert mine.pk != theirs.pk
    assert mine.blog == blog


# ── blogs ───────────────────────────────────────────────────────────────────


def test_create_blog_is_private_by_default_and_owned_by_the_actor(owner):
    b = service.create_blog(name="Field Notes", actor=owner)
    assert b.visibility == Blog.Visibility.PRIVATE
    assert b.owner == owner
    assert b.slug == "field-notes"


def test_create_blog_dedupes_and_avoids_reserved_slugs(owner, blog):
    assert service.create_blog(name="Field Notes", actor=owner).slug == "field-notes-2"
    assert service.create_blog(name="API", actor=owner).slug == "api-2"


def test_set_visibility_is_the_publish_toggle(private_blog, owner):
    b = service.set_visibility(private_blog, visibility=Blog.Visibility.PUBLIC, actor=owner)
    assert b.is_anonymously_readable


def test_set_visibility_rejects_an_unknown_level(blog, owner):
    with pytest.raises(service.InvalidState):
        service.set_visibility(blog, visibility="sort-of-public", actor=owner)


def test_set_visibility_refuses_a_stranger(blog, other_user):
    with pytest.raises(service.NotAuthorized):
        service.set_visibility(blog, visibility=Blog.Visibility.PUBLIC, actor=other_user)
