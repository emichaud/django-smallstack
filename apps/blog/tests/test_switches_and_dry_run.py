"""The four MAJORs from the integration harness's blog programme (rounds 2-3).

Each of these failed against the pre-fix code.

1. ``blog_send --dry-run`` sent the newsletter for real (N1). The flag was
   honoured only inside the ``--issue`` branch; with no ``--issue`` control fell
   through to ``process_sending_issues()`` and mailed every pending recipient,
   while the flag's own help text promises to send nothing.

2. Queueing a second issue for one post raised a raw ``IntegrityError`` out of
   ``issue.save()`` (N2). A second *draft* is legal — the partial constraint
   covers only queued/sending/sent — so the "Send newsletter" button creates
   one, and queueing it answered HTTP 500 because ``views.issue_queue`` catches
   ``BlogServiceError`` only.

3. ``SMALLSTACK_BLOG_ENABLED=False`` left the public surface serving and the
   scheduled ticks running (N4a) — a disabled blog went on publishing posts.

4. ``SMALLSTACK_BLOG_PUBLIC_ENABLED=False`` left the site-wide river
   syndicating post titles (N4b).

The switch tests drive the *gate functions and task bodies* rather than the
URLConf, because both master switches are read at import time and
``override_settings`` cannot re-mount routes in-process — the harness uses a
separate process for that. These cover the logic the routes funnel through.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.blog import service, tasks
from apps.blog.models import Blog, Delivery, Issue, Post
from apps.blog.public_views import public_surface_enabled

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def author():
    return User.objects.create_user(username="switch-author", password="x")


@pytest.fixture
def blog(author):
    b = service.create_blog(
        name="Switch Blog", slug="switch-blog", owner=author, visibility=Blog.Visibility.PUBLIC
    )
    b.newsletter_enabled = True
    b.save()
    return b


@pytest.fixture
def subscribed(blog, author):
    service.import_subscribers(
        blog, [("sw1@example.com", "A"), ("sw2@example.com", "B")], consent_note="t", confirmed=True
    )
    return blog


# ---------------------------------------------------------------------------
# N1 — blog_send --dry-run must not send
# ---------------------------------------------------------------------------
@override_settings(SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL=False)
def test_blog_send_dry_run_without_an_issue_sends_nothing(subscribed, author, mailoutbox):
    issue = service.create_issue(subscribed, subject="Dry", body_markdown="Body", actor=author)
    service.queue_issue(issue, actor=author)
    assert Delivery.objects.filter(status=Delivery.Status.PENDING).count() == 2

    out = StringIO()
    call_command("blog_send", "--dry-run", stdout=out)

    assert not mailoutbox, "--dry-run sent real mail"
    assert Delivery.objects.filter(status=Delivery.Status.PENDING).count() == 2, (
        "--dry-run drained the queue"
    )
    issue.refresh_from_db()
    assert issue.sent_count == 0
    assert "Would send" in out.getvalue()
    assert "Nothing sent" in out.getvalue()


@override_settings(SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL=False)
def test_blog_send_dry_run_does_not_reap(subscribed, author):
    """A dry run must not mutate the rows it was asked only to inspect."""
    issue = service.create_issue(subscribed, subject="Dry2", body_markdown="Body", actor=author)
    service.queue_issue(issue, actor=author)
    stuck = Delivery.objects.first()
    Delivery.objects.filter(pk=stuck.pk).update(
        status=Delivery.Status.CLAIMED, claimed_at=timezone.now() - timedelta(hours=9)
    )

    call_command("blog_send", "--dry-run", stdout=StringIO())

    stuck.refresh_from_db()
    assert stuck.status == Delivery.Status.CLAIMED, "--dry-run reaped a claimed row"


@override_settings(SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL=False)
def test_blog_send_without_dry_run_still_sends(subscribed, author, mailoutbox):
    """Guards against over-correcting: the real send must still work."""
    issue = service.create_issue(subscribed, subject="Real", body_markdown="Body", actor=author)
    service.queue_issue(issue, actor=author)

    call_command("blog_send", stdout=StringIO())

    assert len(mailoutbox) == 2
    assert Delivery.objects.filter(status=Delivery.Status.SENT).count() == 2


def test_blog_send_dry_run_with_nothing_queued_is_quiet(blog):
    out = StringIO()
    call_command("blog_send", "--dry-run", stdout=out)
    assert "Nothing queued" in out.getvalue()


# ---------------------------------------------------------------------------
# N2 — a second campaign for one post is refused readably, not with a 500
# ---------------------------------------------------------------------------
@override_settings(SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL=False)
def test_second_campaign_for_one_post_raises_a_service_error(subscribed, author):
    post = service.create_post(subscribed, title="Once", body_markdown="Body", actor=author)
    service.publish_post(post, actor=author)

    first = service.create_issue_from_post(post, actor=author)
    service.queue_issue(first, actor=author)

    second = service.create_issue_from_post(post, actor=author)
    assert second.status == Issue.Status.DRAFT, "a second draft is legal; only queueing is not"

    with pytest.raises(service.BlogServiceError) as excinfo:
        service.queue_issue(second, actor=author)

    message = str(excinfo.value)
    assert "Once" in message or "already been sent" in message
    second.refresh_from_db()
    assert second.status == Issue.Status.DRAFT


@override_settings(SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL=False)
def test_the_studio_queue_view_answers_rather_than_500ing(subscribed, author, client):
    """The whole point of N2: views.issue_queue catches BlogServiceError only."""
    post = service.create_post(subscribed, title="Twice", body_markdown="Body", actor=author)
    service.publish_post(post, actor=author)
    first = service.create_issue_from_post(post, actor=author)
    service.queue_issue(first, actor=author)
    second = service.create_issue_from_post(post, actor=author)

    client.force_login(author)
    response = client.post(f"/smallstack/blog/issues/{second.pk}/queue/")

    assert response.status_code in (302, 200), "an uncaught IntegrityError would 500 here"
    second.refresh_from_db()
    assert second.status == Issue.Status.DRAFT


# ---------------------------------------------------------------------------
# N4a / N4b — the switches
# ---------------------------------------------------------------------------
def test_public_surface_honours_both_switches():
    with override_settings(SMALLSTACK_BLOG_ENABLED=True, SMALLSTACK_BLOG_PUBLIC_ENABLED=True):
        assert public_surface_enabled() is True
    with override_settings(SMALLSTACK_BLOG_ENABLED=True, SMALLSTACK_BLOG_PUBLIC_ENABLED=False):
        assert public_surface_enabled() is False
    with override_settings(SMALLSTACK_BLOG_ENABLED=False, SMALLSTACK_BLOG_PUBLIC_ENABLED=True):
        assert public_surface_enabled() is False, (
            "the master switch did not reach the public surface — /blog/* and the "
            "anonymous JSON API kept serving with the feature switched off"
        )


@override_settings(SMALLSTACK_BLOG_ENABLED=False)
def test_publish_tick_is_inert_when_the_blog_is_disabled(blog, author):
    post = service.create_post(blog, title="Due", body_markdown="Body", actor=author)
    service.schedule_post(post, when=timezone.now() + timedelta(minutes=5), actor=author)
    Post.objects.filter(pk=post.pk).update(scheduled_for=timezone.now() - timedelta(minutes=1))
    assert service.due_post_count() == 1

    published = tasks.publish_scheduled_posts.func()

    assert published == [], "a disabled blog published a scheduled post"
    post.refresh_from_db()
    assert post.status == Post.Status.SCHEDULED


@override_settings(SMALLSTACK_BLOG_ENABLED=False, SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL=False)
def test_newsletter_tick_is_inert_when_the_blog_is_disabled(subscribed, author, mailoutbox):
    with override_settings(SMALLSTACK_BLOG_ENABLED=True):
        issue = service.create_issue(subscribed, subject="Off", body_markdown="Body", actor=author)
        service.queue_issue(issue, actor=author)

    results = tasks.newsletter_send_tick.func()

    assert results == [], "a disabled blog drained its send queue"
    assert not mailoutbox, "a disabled blog sent newsletter mail"


@override_settings(SMALLSTACK_BLOG_ENABLED=True)
def test_ticks_still_run_when_enabled(blog, author):
    """Guards against over-correcting."""
    post = service.create_post(blog, title="Due2", body_markdown="Body", actor=author)
    service.schedule_post(post, when=timezone.now() + timedelta(minutes=5), actor=author)
    Post.objects.filter(pk=post.pk).update(scheduled_for=timezone.now() - timedelta(minutes=1))

    published = tasks.publish_scheduled_posts.func()

    assert published == [post.pk]
    post.refresh_from_db()
    assert post.status == Post.Status.PUBLISHED
