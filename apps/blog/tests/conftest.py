"""Shared fixtures for the blog tests.

The fixture set is deliberately a *visibility matrix*: a blog at each of the
three levels, plus a second owner's blog, plus a post at each lifecycle stage.
Most defects in this app are "the wrong row was visible to the wrong person",
so nearly every test needs several of these at once.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.blog.models import Blog, Issue, Post, Subscriber, Subscription


def _make_post(**kwargs) -> Post:
    """Create a Post with its derived fields populated, the way the service
    would. Building rows straight through the ORM leaves ``body_html`` and
    ``excerpt`` empty, which quietly makes any test that reads them pass or
    fail for the wrong reason."""
    from apps.blog import service

    post = Post(**kwargs)
    service.render_body(post)
    post.save()
    return post


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(
        username="owner", email="owner@example.test", password="pw"
    )


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(
        username="other", email="other@example.test", password="pw"
    )


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(
        username="staffer", email="staff@example.test", password="pw", is_staff=True
    )


@pytest.fixture
def blog(owner):
    """A public blog owned by ``owner`` — the common case."""
    return Blog.objects.create(
        name="Field Notes", slug="field-notes", owner=owner, visibility=Blog.Visibility.PUBLIC
    )


@pytest.fixture
def members_blog(owner):
    return Blog.objects.create(
        name="Team Internal", slug="team-internal", owner=owner,
        visibility=Blog.Visibility.MEMBERS,
    )


@pytest.fixture
def private_blog(owner):
    return Blog.objects.create(
        name="Scratch", slug="scratch", owner=owner, visibility=Blog.Visibility.PRIVATE
    )


@pytest.fixture
def house_blog(db):
    """``owner=None`` — a staff-managed house blog."""
    return Blog.objects.create(
        name="Release Notes", slug="release-notes", owner=None,
        visibility=Blog.Visibility.PUBLIC,
    )


@pytest.fixture
def other_blog(other_user):
    return Blog.objects.create(
        name="Someone Else", slug="someone-else", owner=other_user,
        visibility=Blog.Visibility.PUBLIC,
    )


@pytest.fixture
def post(blog, owner):
    """A live post: published, with ``published_at`` in the past."""
    return _make_post(
        blog=blog, author=owner, title="Hello World", slug="hello-world",
        body_markdown="# Hello\n\nFirst post.", excerpt="First post.",
        status=Post.Status.PUBLISHED,
        published_at=timezone.now() - timezone.timedelta(hours=1),
    )


@pytest.fixture
def draft(blog, owner):
    return _make_post(
        blog=blog, author=owner, title="Unfinished", slug="unfinished",
        body_markdown="Secret notes.", status=Post.Status.DRAFT,
    )


@pytest.fixture
def scheduled_post(blog, owner):
    """Published status is NOT set — it is `scheduled` until the tick runs."""
    return _make_post(
        blog=blog, author=owner, title="Later", slug="later",
        body_markdown="Coming soon.", status=Post.Status.SCHEDULED,
        scheduled_for=timezone.now() + timezone.timedelta(days=1),
    )


@pytest.fixture
def future_published_post(blog, owner):
    """status=published but ``published_at`` is in the future — must NOT be live.

    Guards the difference between the status field and the clock: a row like
    this is how an embargo leaks if a view filters on status alone.
    """
    return _make_post(
        blog=blog, author=owner, title="Embargoed", slug="embargoed",
        body_markdown="Not yet.", status=Post.Status.PUBLISHED,
        published_at=timezone.now() + timezone.timedelta(days=1),
    )


@pytest.fixture
def subscriber(db):
    return Subscriber.objects.create(email="reader@example.test", name="Reader")


@pytest.fixture
def confirmed_sub(blog, subscriber):
    return Subscription.objects.create(
        subscriber=subscriber, blog=blog,
        status=Subscription.Status.CONFIRMED, confirmed_at=timezone.now(), source="web",
    )


@pytest.fixture
def issue(blog, post):
    return Issue.objects.create(
        blog=blog, post=post, subject="Issue 1", body_markdown="Hi there."
    )
