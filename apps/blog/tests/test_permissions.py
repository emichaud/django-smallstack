"""The authorization matrix.

``apps.blog.permissions`` is the single source of truth for who may see and
edit what, and ``viewable_posts`` in particular is the one scoper behind the
console list, console detail, REST, every generated MCP tool, search
visibility and the public views. A mistake here is a six-surface data leak, so
the matrix is enumerated exhaustively rather than sampled.

Convention under test: a row you may not see is **absent from your queryset**
(and 404s on direct access) — never 403. Whether a neighbour has a blog called
"launch" is not public information.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.blog import permissions as perms
from apps.blog.models import Post

pytestmark = pytest.mark.django_db


@pytest.fixture
def anon():
    return AnonymousUser()


# ── can_view: the three-tier ladder ─────────────────────────────────────────


def test_public_blog_is_visible_to_everyone(blog, anon, owner, other_user, staff):
    for actor in (anon, owner, other_user, staff):
        assert perms.can_view(actor, blog), f"public blog hidden from {actor!r}"


def test_members_blog_admits_any_signed_in_user_but_not_anonymous(
    members_blog, anon, owner, other_user, staff
):
    """The tier that exists for the workgroup case: readable by every
    colleague, invisible to the internet."""
    assert not perms.can_view(anon, members_blog)
    for actor in (owner, other_user, staff):
        assert perms.can_view(actor, members_blog)


def test_private_blog_admits_only_its_owner_and_staff(
    private_blog, anon, owner, other_user, staff
):
    assert perms.can_view(owner, private_blog)
    assert perms.can_view(staff, private_blog)
    assert not perms.can_view(anon, private_blog)
    assert not perms.can_view(other_user, private_blog)


def test_none_blog_is_staff_only(anon, owner, staff):
    assert perms.can_view(staff, None)
    assert not perms.can_view(owner, None)
    assert not perms.can_view(anon, None)


# ── can_edit ────────────────────────────────────────────────────────────────


def test_only_the_owner_and_staff_may_edit(blog, anon, owner, other_user, staff):
    assert perms.can_edit(owner, blog)
    assert perms.can_edit(staff, blog)
    assert not perms.can_edit(other_user, blog)
    assert not perms.can_edit(anon, blog)


def test_a_public_blog_is_not_editable_by_readers(blog, other_user):
    """Visibility and editability are independent axes — the whole internet
    can read a public blog and still none of them may write to it."""
    assert perms.can_view(other_user, blog)
    assert not perms.can_edit(other_user, blog)


def test_house_blog_with_no_owner_is_staff_only_to_edit(house_blog, owner, staff, anon):
    assert perms.can_edit(staff, house_blog)
    assert not perms.can_edit(owner, house_blog)
    assert not perms.can_edit(anon, house_blog)
    # …but still publicly readable.
    assert perms.can_view(anon, house_blog)


# ── can_view_post: the draft-preview rule ───────────────────────────────────


def test_live_post_follows_its_blogs_visibility(post, anon, other_user, staff):
    for actor in (anon, other_user, staff):
        assert perms.can_view_post(actor, post)


def test_draft_is_visible_only_to_those_who_could_edit_it(
    draft, anon, owner, other_user, staff
):
    """Draft preview is the affordance; a leak here is the highest-severity
    failure this app has."""
    assert perms.can_view_post(owner, draft)
    assert perms.can_view_post(staff, draft)
    assert not perms.can_view_post(other_user, draft)
    assert not perms.can_view_post(anon, draft)


def test_scheduled_and_embargoed_posts_are_not_readable_by_outsiders(
    scheduled_post, future_published_post, anon, other_user, owner
):
    for p in (scheduled_post, future_published_post):
        assert not perms.can_view_post(anon, p)
        assert not perms.can_view_post(other_user, p)
        assert perms.can_view_post(owner, p)


def test_live_post_in_a_private_blog_is_still_hidden(private_blog, owner, other_user, anon):
    """Post status alone never grants access — the blog gate applies first."""
    from django.utils import timezone

    p = Post.objects.create(
        blog=private_blog, title="Live but private", slug="lbp", author=owner,
        status=Post.Status.PUBLISHED, published_at=timezone.now() - timezone.timedelta(hours=1),
    )
    assert perms.can_view_post(owner, p)
    assert not perms.can_view_post(other_user, p)
    assert not perms.can_view_post(anon, p)


def test_can_view_post_handles_none():
    assert not perms.can_view_post(AnonymousUser(), None)


# ── viewable_blogs ──────────────────────────────────────────────────────────


def test_viewable_blogs_for_anonymous_is_public_only(
    blog, members_blog, private_blog, other_blog, anon
):
    slugs = set(perms.viewable_blogs(anon).values_list("slug", flat=True))
    assert slugs == {"field-notes", "someone-else"}


def test_viewable_blogs_for_a_signed_in_stranger(
    blog, members_blog, private_blog, other_blog, other_user
):
    """Sees public + members everywhere, but never someone else's private."""
    slugs = set(perms.viewable_blogs(other_user).values_list("slug", flat=True))
    assert slugs == {"field-notes", "team-internal", "someone-else"}
    assert "scratch" not in slugs


def test_viewable_blogs_includes_your_own_private_blog(
    blog, members_blog, private_blog, other_blog, owner
):
    slugs = set(perms.viewable_blogs(owner).values_list("slug", flat=True))
    assert "scratch" in slugs


def test_viewable_blogs_for_staff_is_everything(
    blog, members_blog, private_blog, other_blog, staff
):
    assert perms.viewable_blogs(staff).count() == 4


# ── editable_blogs — the form-choice scoper ─────────────────────────────────


def test_editable_blogs_is_narrower_than_viewable(
    blog, members_blog, other_blog, owner, other_user, anon
):
    """This is what scopes the `blog` <select> on the post form — the one gap
    `get_list_queryset` cannot close, and a cross-tenant *write* if missed."""
    assert set(perms.editable_blogs(owner).values_list("slug", flat=True)) == {
        "field-notes", "team-internal",
    }
    # other_user can VIEW field-notes but must not be offered it to write into.
    assert perms.can_view(other_user, blog)
    assert "field-notes" not in set(
        perms.editable_blogs(other_user).values_list("slug", flat=True)
    )
    assert perms.editable_blogs(anon).count() == 0


def test_editable_blogs_excludes_ownerless_house_blogs(house_blog, owner, staff):
    assert house_blog not in perms.editable_blogs(owner)
    assert house_blog in perms.editable_blogs(staff)


# ── public_posts — the one definition of "on the internet" ──────────────────


def test_public_posts_admits_only_live_posts_in_public_blogs(
    post, draft, scheduled_post, future_published_post, private_blog, owner
):
    from django.utils import timezone

    Post.objects.create(
        blog=private_blog, title="Hidden", slug="hidden", author=owner,
        status=Post.Status.PUBLISHED, published_at=timezone.now() - timezone.timedelta(hours=1),
    )
    titles = set(perms.public_posts().values_list("title", flat=True))
    assert titles == {"Hello World"}


def test_public_posts_excludes_members_blogs(members_blog, owner):
    from django.utils import timezone

    Post.objects.create(
        blog=members_blog, title="Internal", slug="internal", author=owner,
        status=Post.Status.PUBLISHED, published_at=timezone.now() - timezone.timedelta(hours=1),
    )
    assert not perms.public_posts().filter(title="Internal").exists()


# ── viewable_posts — the six-surface scoper ─────────────────────────────────


def test_viewable_posts_for_anonymous_matches_public_posts(
    post, draft, scheduled_post, future_published_post, members_blog, private_blog, owner, anon
):
    anon_titles = set(perms.viewable_posts(anon).values_list("title", flat=True))
    assert anon_titles == {"Hello World"}
    assert anon_titles == set(perms.public_posts().values_list("title", flat=True))


def test_viewable_posts_never_leaks_another_owners_draft(
    draft, other_blog, other_user, owner
):
    other_draft = Post.objects.create(
        blog=other_blog, title="Their Secret", slug="their-secret",
        author=other_user, status=Post.Status.DRAFT,
    )
    mine = set(perms.viewable_posts(owner).values_list("title", flat=True))
    assert "Unfinished" in mine, "owner should see their own draft"
    assert other_draft.title not in mine


def test_viewable_posts_includes_every_status_in_your_own_blogs(
    post, draft, scheduled_post, future_published_post, owner
):
    titles = set(perms.viewable_posts(owner).values_list("title", flat=True))
    assert titles == {"Hello World", "Unfinished", "Later", "Embargoed"}


def test_viewable_posts_lets_a_member_read_live_posts_in_a_members_blog(
    members_blog, owner, other_user
):
    from django.utils import timezone

    Post.objects.create(
        blog=members_blog, title="Team Update", slug="team-update", author=owner,
        status=Post.Status.PUBLISHED, published_at=timezone.now() - timezone.timedelta(hours=1),
    )
    titles = set(perms.viewable_posts(other_user).values_list("title", flat=True))
    assert "Team Update" in titles


def test_viewable_posts_hides_members_blog_drafts_from_members(members_blog, owner, other_user):
    """A colleague may read the blog; that does not make them an author."""
    Post.objects.create(
        blog=members_blog, title="Team Draft", slug="team-draft",
        author=owner, status=Post.Status.DRAFT,
    )
    titles = set(perms.viewable_posts(other_user).values_list("title", flat=True))
    assert "Team Draft" not in titles


def test_viewable_posts_for_staff_is_everything(
    post, draft, scheduled_post, future_published_post, staff
):
    assert perms.viewable_posts(staff).count() == 4


def test_viewable_posts_returns_no_duplicates(blog, post, owner):
    """The Q(...)|Q(...) in viewable_posts can fan out across the tags join —
    a duplicated row would silently double-count in feeds and pagination."""
    from apps.blog.models import Tag

    post.tags.add(
        Tag.objects.create(blog=blog, name="A", slug="a"),
        Tag.objects.create(blog=blog, name="B", slug="b"),
    )
    qs = perms.viewable_posts(owner).filter(pk=post.pk)
    assert qs.count() == 1
    assert len(list(qs)) == 1


# ── Newsletter scopers — PII belongs to the publisher ───────────────────────


def test_issues_and_subscriptions_scope_by_editable_not_viewable(
    members_blog, owner, other_user, subscriber
):
    """A members blog is readable by every colleague. Its newsletter drafts and
    its subscriber list are NOT — those are scoped by editability."""
    from apps.blog.models import Issue, Subscription

    Issue.objects.create(blog=members_blog, subject="Internal issue")
    Subscription.objects.create(subscriber=subscriber, blog=members_blog)

    assert perms.can_view(other_user, members_blog)
    assert perms.owned_issues(other_user).count() == 0
    assert perms.owned_subscriptions(other_user).count() == 0
    assert perms.owned_issues(owner).count() == 1
    assert perms.owned_subscriptions(owner).count() == 1


def test_deliveries_scope_through_their_issues_blog(issue, subscriber, owner, other_user, staff):
    from apps.blog.models import Delivery

    Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)
    assert perms.owned_deliveries(owner).count() == 1
    assert perms.owned_deliveries(other_user).count() == 0
    assert perms.owned_deliveries(staff).count() == 1


def test_tag_scopers_follow_their_blog(blog, private_blog, other_user, owner, anon):
    from apps.blog.models import Tag

    Tag.objects.create(blog=blog, name="Public", slug="public-tag")
    Tag.objects.create(blog=private_blog, name="Secret", slug="secret-tag")

    assert set(perms.viewable_tags(anon).values_list("slug", flat=True)) == {"public-tag"}
    assert set(perms.viewable_tags(owner).values_list("slug", flat=True)) == {
        "public-tag", "secret-tag",
    }
    assert set(perms.viewable_tags(other_user).values_list("slug", flat=True)) == {"public-tag"}
    assert set(perms.editable_tags(other_user).values_list("slug", flat=True)) == set()


# ── Guard: the scopers must never be a no-op ────────────────────────────────


@pytest.mark.parametrize(
    "scoper",
    [
        perms.viewable_blogs, perms.editable_blogs, perms.viewable_posts,
        perms.viewable_tags, perms.editable_tags, perms.owned_issues,
        perms.owned_subscriptions, perms.owned_deliveries,
    ],
)
def test_no_scoper_returns_everything_for_a_stranger(
    scoper, blog, private_blog, other_user, subscriber, issue
):
    """A `qs.all()` slipped into any scoper — even temporarily, for debugging —
    ships and leaks. This asserts each one actually narrows for a non-owner.

    Every model a scoper covers needs at least one row the stranger must not
    see, or the assertion passes vacuously — the `unscoped.count() > 0` guard
    below is what keeps this test honest as models are added.
    """
    from apps.blog.models import Delivery, Post, Subscription, Tag

    Tag.objects.create(blog=private_blog, name="T", slug="t-private")
    Subscription.objects.create(subscriber=subscriber, blog=private_blog)
    Post.objects.create(blog=private_blog, title="Hidden", slug="hidden-guard")
    Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)

    scoped = scoper(other_user)
    unscoped = scoped.model._default_manager.all()
    assert unscoped.count() > 0, "fixture produced no rows — the test proves nothing"
    assert scoped.count() < unscoped.count(), f"{scoper.__name__} did not narrow"
