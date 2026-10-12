"""The console's security envelope.

Three properties, asserted on every surface the CRUDView generates:

* **anonymous → login redirect**
* **owner → 200**
* **non-owner → 404, not 403** (existence is not public information)

The 404-not-403 distinction is the one most easily lost in a refactor, so it is
asserted explicitly rather than via a generic "not 200".

The surfaces are enumerated deliberately. ``get_detail_queryset`` defaults to
``get_list_queryset``, which is what makes detail / edit / delete /
field-preview / related-tab all safe from one definition — but only a test that
hits each of them proves the default is still in place.
"""

from __future__ import annotations

import pytest

from apps.blog.models import Blog, Issue, Post, Subscription

pytestmark = pytest.mark.django_db

CONSOLE = "/smallstack/blog"


# ── Anonymous ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        f"{CONSOLE}/posts/",
        f"{CONSOLE}/posts/new/",
        f"{CONSOLE}/blogs/",
        f"{CONSOLE}/tags/",
        f"{CONSOLE}/issues/",
        f"{CONSOLE}/subscriptions/",
        f"{CONSOLE}/deliveries/",
        f"{CONSOLE}/subscribers/",
    ],
)
def test_anonymous_is_redirected_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.url


def test_anonymous_cannot_post_an_action(client, draft):
    response = client.post(f"{CONSOLE}/posts/{draft.pk}/publish/")
    assert response.status_code == 302
    assert "/login" in response.url
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT, "anonymous POST must not publish"


# ── Owner sees their own ────────────────────────────────────────────────────


def test_owner_sees_their_own_posts_including_drafts(client, owner, post, draft):
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/").content.decode()
    assert post.title in body
    assert draft.title in body


@pytest.mark.parametrize("suffix", ["", "edit/"])
def test_owner_can_open_their_own_post(client, owner, draft, suffix):
    client.force_login(owner)
    assert client.get(f"{CONSOLE}/posts/{draft.pk}/{suffix}").status_code == 200


def test_owner_can_open_their_own_blog_and_tag(client, owner, blog):
    from apps.blog.models import Tag

    tag = Tag.objects.create(blog=blog, name="Ops", slug="ops")
    client.force_login(owner)
    assert client.get(f"{CONSOLE}/blogs/{blog.pk}/").status_code == 200
    assert client.get(f"{CONSOLE}/tags/{tag.pk}/").status_code == 200


# ── Non-owner is 404 on every single-object surface ─────────────────────────


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "edit/",
        "delete/",
        "field-preview/body_markdown/",
        "related/issues/",
    ],
)
def test_non_owner_gets_404_on_every_post_surface(client, other_user, draft, suffix):
    """`get_detail_queryset` inherits from `get_list_queryset`, so one scoper
    covers all of these — but only a test per surface proves it still does."""
    client.force_login(other_user)
    response = client.get(f"{CONSOLE}/posts/{draft.pk}/{suffix}")
    assert response.status_code == 404, f"{suffix or 'detail'} leaked (got {response.status_code})"


def test_non_owner_does_not_see_the_draft_in_the_list(client, other_user, draft):
    client.force_login(other_user)
    body = client.get(f"{CONSOLE}/posts/").content.decode()
    assert draft.title not in body


def test_non_owner_gets_404_on_someone_elses_private_blog(client, other_user, private_blog):
    client.force_login(other_user)
    assert client.get(f"{CONSOLE}/blogs/{private_blog.pk}/").status_code == 404


def test_non_owner_cannot_edit_a_public_blog_they_can_read(client, other_user, blog):
    """Read scope is deliberately wider than write scope: a live post in a
    public blog is visible here, but every write surface must still refuse."""
    client.force_login(other_user)
    assert client.get(f"{CONSOLE}/blogs/{blog.pk}/").status_code == 200
    assert client.get(f"{CONSOLE}/blogs/{blog.pk}/edit/").status_code == 404
    assert client.post(f"{CONSOLE}/blogs/{blog.pk}/edit/", {"name": "Hijacked"}).status_code == 404
    blog.refresh_from_db()
    assert blog.name == "Field Notes"


def test_non_owner_cannot_edit_a_live_post_they_can_read(client, other_user, post):
    client.force_login(other_user)
    assert client.get(f"{CONSOLE}/posts/{post.pk}/").status_code == 200
    assert client.get(f"{CONSOLE}/posts/{post.pk}/edit/").status_code == 404


# ── Non-owner cannot POST an action ─────────────────────────────────────────


@pytest.mark.parametrize("action", ["publish", "unpublish", "archive", "schedule"])
def test_non_owner_cannot_post_a_lifecycle_action(client, other_user, draft, action):
    client.force_login(other_user)
    response = client.post(f"{CONSOLE}/posts/{draft.pk}/{action}/")
    assert response.status_code == 404
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT


def test_lifecycle_actions_reject_get(client, owner, draft):
    """Mutating via GET would be triggerable by a link prefetch."""
    client.force_login(owner)
    assert client.get(f"{CONSOLE}/posts/{draft.pk}/publish/").status_code == 405
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT


def test_owner_can_publish_and_unpublish(client, owner, draft):
    client.force_login(owner)
    assert client.post(f"{CONSOLE}/posts/{draft.pk}/publish/").status_code == 302
    draft.refresh_from_db()
    assert draft.status == Post.Status.PUBLISHED
    assert draft.is_live

    client.post(f"{CONSOLE}/posts/{draft.pk}/unpublish/")
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT
    assert draft.published_at is None


def test_schedule_action_accepts_a_local_datetime(client, owner, draft):
    from django.utils import timezone

    when = timezone.localtime(timezone.now() + timezone.timedelta(days=2))
    client.force_login(owner)
    client.post(
        f"{CONSOLE}/posts/{draft.pk}/schedule/",
        {"scheduled_for": when.strftime("%Y-%m-%dT%H:%M")},
    )
    draft.refresh_from_db()
    assert draft.status == Post.Status.SCHEDULED
    assert draft.scheduled_for is not None


def test_schedule_action_reports_a_past_time_instead_of_publishing(client, owner, draft):
    from django.utils import timezone

    past = timezone.localtime(timezone.now() - timezone.timedelta(days=1))
    client.force_login(owner)
    client.post(
        f"{CONSOLE}/posts/{draft.pk}/schedule/",
        {"scheduled_for": past.strftime("%Y-%m-%dT%H:%M")},
        follow=True,
    )
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT, "a past schedule must not publish immediately"


def test_action_redirect_cannot_be_hijacked(client, owner, draft):
    """`next=` is an open-redirect vector if it isn't host-checked."""
    client.force_login(owner)
    response = client.post(
        f"{CONSOLE}/posts/{draft.pk}/publish/", {"next": "https://evil.test/steal"}
    )
    assert "evil.test" not in response.url


# ── The form-choice gap `get_list_queryset` cannot close ────────────────────


def test_blog_select_offers_only_blogs_you_may_write_to(client, owner, blog, other_blog):
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/new/").content.decode()
    assert f'value="{blog.pk}"' in body
    assert f'value="{other_blog.pk}"' not in body, "another owner's blog was offered"


def test_posting_to_a_blog_you_do_not_own_is_rejected(client, owner, other_blog):
    """The decisive test: narrowing a ModelChoiceField queryset IS the
    validation, so a forged pk fails rather than creating a cross-tenant row."""
    client.force_login(owner)
    response = client.post(
        f"{CONSOLE}/posts/new/",
        {"blog": other_blog.pk, "title": "Intrusion", "body_markdown": "x", "slug": ""},
    )
    assert response.status_code == 200, "should re-render the form with an error, not redirect"
    assert not Post.objects.filter(title="Intrusion").exists()


def test_issue_post_select_is_scoped_too(client, owner, post, other_blog, other_user):
    other_post = Post.objects.create(
        blog=other_blog, title="Theirs", slug="theirs", author=other_user
    )
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/issues/new/").content.decode()
    assert f'value="{post.pk}"' in body
    assert f'value="{other_post.pk}"' not in body


# ── Creating through the console goes through the service ───────────────────


def test_creating_a_post_renders_html_and_derives_the_excerpt(client, owner, blog):
    client.force_login(owner)
    client.post(
        f"{CONSOLE}/posts/new/",
        {
            "blog": blog.pk,
            "title": "From the Console",
            "slug": "",
            "body_markdown": "# Head\n\nThe opening line.",
            "excerpt": "",
            "tag_names": "ops, release",
        },
    )
    created = Post.objects.get(title="From the Console")
    assert "<h1" in created.body_html, "on_form_valid must render through the service"
    assert created.excerpt == "The opening line."
    assert created.slug == "from-the-console"
    assert created.author == owner
    assert created.status == Post.Status.DRAFT
    assert set(created.tags.values_list("slug", flat=True)) == {"ops", "release"}


def test_creating_a_blog_stamps_the_owner(client, owner):
    client.force_login(owner)
    client.post(
        f"{CONSOLE}/blogs/new/",
        {"name": "Brand New", "slug": "", "visibility": Blog.Visibility.PRIVATE},
    )
    created = Blog.objects.get(name="Brand New")
    assert created.owner == owner, "owner must come from the request, never a form field"
    assert created.slug == "brand-new"
    assert created.visibility == Blog.Visibility.PRIVATE


def test_post_form_cannot_set_status_even_if_submitted(client, owner, blog):
    """`status` is not in `fields`, so a crafted POST must be ignored — not
    honoured. A form that could publish would skip the render and the webhook."""
    client.force_login(owner)
    client.post(
        f"{CONSOLE}/posts/new/",
        {
            "blog": blog.pk,
            "title": "Sneaky",
            "slug": "",
            "body_markdown": "x",
            "status": Post.Status.PUBLISHED,
            "published_at": "2020-01-01T00:00",
        },
    )
    created = Post.objects.get(title="Sneaky")
    assert created.status == Post.Status.DRAFT
    assert created.published_at is None


# ── Markdown preview ────────────────────────────────────────────────────────


def test_preview_renders_the_same_html_the_service_stores(client, owner):
    client.force_login(owner)
    response = client.post(
        f"{CONSOLE}/posts/preview/", {"body_markdown": "# Live\n\n<script>x</script>"}
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "<h1" in body
    assert "<script>" not in body, "preview must be hardened like the stored HTML"


def test_preview_requires_login(client):
    assert client.post(f"{CONSOLE}/posts/preview/", {"body_markdown": "x"}).status_code == 302


# ── Staff-only surfaces ─────────────────────────────────────────────────────


def test_subscriber_list_is_staff_only(client, owner, staff, subscriber):
    """A Subscriber row aggregates across blogs, so a blog owner must not see
    it — they get Subscription, scoped to their own blogs."""
    client.force_login(owner)
    assert client.get(f"{CONSOLE}/subscribers/").status_code == 403

    client.force_login(staff)
    assert client.get(f"{CONSOLE}/subscribers/").status_code == 200


def test_owner_sees_only_their_own_audience(client, owner, other_user, blog, other_blog, subscriber):
    Subscription.objects.create(subscriber=subscriber, blog=blog)
    Subscription.objects.create(subscriber=subscriber, blog=other_blog)

    client.force_login(owner)
    body = client.get(f"{CONSOLE}/subscriptions/").content.decode()
    assert "Field Notes" in body
    assert "Someone Else" not in body


def test_a_members_blog_reader_sees_no_audience_or_issues(
    client, other_user, members_blog, subscriber
):
    """Readable blog, private newsletter — the editable-vs-viewable split."""
    Subscription.objects.create(subscriber=subscriber, blog=members_blog)
    Issue.objects.create(blog=members_blog, subject="Internal")

    client.force_login(other_user)
    assert subscriber.email not in client.get(f"{CONSOLE}/subscriptions/").content.decode()
    assert "Internal" not in client.get(f"{CONSOLE}/issues/").content.decode()


# ── A sent issue is a permanent record ──────────────────────────────────────


def test_a_queued_issue_cannot_be_edited(client, owner, blog):
    issue = Issue.objects.create(blog=blog, subject="Going out", status=Issue.Status.QUEUED)
    client.force_login(owner)
    assert client.get(f"{CONSOLE}/issues/{issue.pk}/").status_code == 200, "still readable"
    assert client.get(f"{CONSOLE}/issues/{issue.pk}/edit/").status_code == 403
    assert client.post(f"{CONSOLE}/issues/{issue.pk}/edit/", {"subject": "Changed"}).status_code == 403
    issue.refresh_from_db()
    assert issue.subject == "Going out"


def test_a_draft_issue_can_still_be_edited(client, owner, blog):
    issue = Issue.objects.create(blog=blog, subject="Draft issue")
    client.force_login(owner)
    assert client.get(f"{CONSOLE}/issues/{issue.pk}/edit/").status_code == 200


def test_deliveries_are_read_only(client, owner, issue, subscriber):
    from apps.blog.models import Delivery

    d = Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)
    client.force_login(owner)
    assert client.get(f"{CONSOLE}/deliveries/{d.pk}/").status_code == 200
    # No edit/delete routes are generated at all for a LIST+DETAIL view.
    assert client.get(f"{CONSOLE}/deliveries/{d.pk}/edit/").status_code == 404


# ── Staff see everything ────────────────────────────────────────────────────


def test_staff_see_every_blogs_posts(client, staff, post, draft, other_blog, other_user):
    theirs = Post.objects.create(
        blog=other_blog, title="Theirs", slug="theirs", author=other_user
    )
    client.force_login(staff)
    body = client.get(f"{CONSOLE}/posts/").content.decode()
    for title in (post.title, draft.title, theirs.title):
        assert title in body


# ── Detail page affordances ─────────────────────────────────────────────────


def test_owner_sees_publishing_controls_and_the_rendered_article(client, owner, draft):
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/{draft.pk}/").content.decode()
    assert "Publish now" in body
    assert "Rendered" in body
    assert f"/posts/{draft.pk}/publish/" in body


def test_a_reader_is_offered_no_publishing_controls(client, other_user, post):
    """The read scope is wider than the write scope, so a reader lands here —
    and must not be shown buttons whose POST is refused."""
    client.force_login(other_user)
    body = client.get(f"{CONSOLE}/posts/{post.pk}/").content.decode()
    assert "Publish now" not in body
    assert "Return to draft" not in body
    assert f"/posts/{post.pk}/publish/" not in body


def test_published_post_offers_unpublish_rather_than_publish(client, owner, post):
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/{post.pk}/").content.decode()
    assert "Return to draft" in body
    assert "Publish now" not in body


def test_an_embargoed_post_says_so(client, owner, future_published_post):
    """status=published + a future timestamp is the state most likely to be
    misread; the page must not claim the post is live."""
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/{future_published_post.pk}/").content.decode()
    assert "embargoed" in body.lower()


def test_the_list_badge_distinguishes_embargoed_from_published(
    client, owner, post, future_published_post
):
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/").content.decode()
    assert "Embargoed" in body
    assert "Published" in body


def test_the_editor_asset_and_preview_url_are_present_on_the_form(client, owner, blog):
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/new/").content.decode()
    assert "blog/blog.js" in body
    assert "blog/blog.css" in body
    assert 'data-preview-url="/smallstack/blog/posts/preview/"' in body
    assert "blog-markdown-input" in body


def test_the_rendered_article_is_the_hardened_html(client, owner, blog):
    """The detail page emits body_html with |safe, so this asserts the column
    it trusts really is sanitised end to end."""
    from apps.blog import service

    hostile = service.create_post(
        blog, title="Hostile", body_markdown="<img src=x onerror=alert(1)>", actor=owner
    )
    client.force_login(owner)
    body = client.get(f"{CONSOLE}/posts/{hostile.pk}/").content.decode()
    assert "<img src=x onerror=alert(1)>" not in body
