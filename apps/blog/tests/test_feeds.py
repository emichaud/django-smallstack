"""Feeds — site-wide and per-blog, in all three formats.

The framework's `enable_rss = True` path is deliberately NOT used: its
`ModelFeed.items()` is `model.objects.all()` with no visibility hook, so the
flag would publish every draft from every blog anonymously. These tests pin
both halves of that decision — that the flag stays off, and that the curated
replacements actually scope correctly.
"""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from apps.blog import service
from apps.blog.models import Blog
from apps.search.access import SearchAccess

pytestmark = pytest.mark.django_db


# ── The decision itself ─────────────────────────────────────────────────────


def test_no_blog_crudview_enables_the_unscoped_model_feed():
    """`ModelFeed.items()` ignores get_list_queryset / search_visibility, so
    turning this on would syndicate drafts and private blogs. If someone flips
    it, this fails and points at apps/blog/feeds.py for the reason."""
    from apps.blog import views

    for name in (
        "BlogCRUDView", "PostCRUDView", "TagCRUDView", "IssueCRUDView",
        "SubscriptionCRUDView", "SubscriberCRUDView", "DeliveryCRUDView",
    ):
        view = getattr(views, name)
        assert getattr(view, "enable_rss", False) is False, f"{name} enabled enable_rss"


def test_the_site_feed_is_registered_and_anonymous():
    from apps.feeds.registry import get_feed

    feed = get_feed("blog")
    assert feed is not None, "LatestPostsFeed should be registered in ready()"
    assert feed.access == SearchAccess.ANONYMOUS


# ── Site-wide feed ──────────────────────────────────────────────────────────


def test_the_site_feed_carries_published_public_posts(client, post):
    body = client.get("/feed/blog.rss").content.decode()
    assert post.title in body


def test_the_site_feed_excludes_drafts_and_non_public_blogs(
    client, post, draft, members_blog, private_blog, owner
):
    for b in (members_blog, private_blog):
        p = service.create_post(b, title=f"Hidden in {b.slug}", body_markdown="x", actor=owner)
        service.publish_post(p, actor=owner)

    body = client.get("/feed/blog.rss").content.decode()
    assert post.title in body
    assert draft.title not in body
    assert "Hidden in" not in body


# ── Per-blog feeds ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["rss", "atom", "json"])
def test_the_per_blog_feed_renders_in_every_format(client, blog, post, fmt):
    response = client.get(f"/blog/{blog.slug}/feed.{fmt}")
    assert response.status_code == 200
    assert post.title in response.content.decode()


def test_the_per_blog_feed_contains_only_that_blogs_posts(client, blog, other_blog, other_user):
    theirs = service.create_post(
        other_blog, title="Not Mine", body_markdown="x", actor=other_user
    )
    service.publish_post(theirs, actor=other_user)

    body = client.get(f"/blog/{blog.slug}/feed.rss").content.decode()
    assert "Not Mine" not in body


def test_a_private_blogs_feed_404s_anonymously(client, private_blog, owner):
    p = service.create_post(private_blog, title="Secret", body_markdown="x", actor=owner)
    service.publish_post(p, actor=owner)
    assert client.get(f"/blog/{private_blog.slug}/feed.rss").status_code == 404


def test_a_members_blogs_feed_401s_with_a_challenge(client, members_blog):
    """A feed reader cannot follow a login redirect, so the framework's own
    gated feeds answer 401 + WWW-Authenticate. This matches them."""
    response = client.get(f"/blog/{members_blog.slug}/feed.rss")
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_a_signed_in_member_gets_the_members_feed(client, members_blog, owner, other_user):
    p = service.create_post(members_blog, title="Team News", body_markdown="x", actor=owner)
    service.publish_post(p, actor=owner)

    client.force_login(other_user)
    response = client.get(f"/blog/{members_blog.slug}/feed.rss")
    assert response.status_code == 200
    assert "Team News" in response.content.decode()


# ── Item shape ──────────────────────────────────────────────────────────────


def test_guids_are_stable_across_renders_and_derive_from_uid(client, blog, post):
    """A GUID must survive a database restore or an environment copy, or every
    reader re-shows every post as new. That rules out the primary key."""
    first = client.get(f"/blog/{blog.slug}/feed.rss").content.decode()
    second = client.get(f"/blog/{blog.slug}/feed.rss").content.decode()

    expected = f"smallstack_blog.Post:{post.uid}"
    assert expected in first
    assert expected in second
    # Structural, not a substring check: a pk of 1 occurs inside a UUID's hex
    # by chance, so `str(pk) not in guid` would be meaningless.
    assert expected != f"smallstack_blog.Post:{post.pk}"
    assert f"<guid isPermaLink=\"false\">{expected}</guid>" in first


def test_links_are_absolute(client, blog, post):
    body = client.get(f"/blog/{blog.slug}/feed.rss").content.decode()
    assert f"http://testserver{post.get_absolute_url()}" in body


def test_tags_become_categories(client, blog, post, owner):
    service.set_post_tags(post, ["Ops", "Postgres"], actor=owner)
    body = client.get(f"/blog/{blog.slug}/feed.rss").content.decode()
    assert "<category>Ops</category>" in body


def test_the_json_feed_is_valid_jsonfeed_1_1(client, blog, post):
    response = client.get(f"/blog/{blog.slug}/feed.json")
    assert response["Content-Type"].startswith("application/feed+json")
    data = json.loads(response.content.decode())
    assert data["version"] == "https://jsonfeed.org/version/1.1"
    assert data["items"][0]["title"] == post.title
    assert data["items"][0]["url"].startswith("http://testserver/blog/")
    assert data["items"][0]["id"] == f"smallstack_blog.Post:{post.uid}"


def test_the_three_formats_agree_on_which_posts_are_included(client, blog, post, draft):
    rss = client.get(f"/blog/{blog.slug}/feed.rss").content.decode()
    atom = client.get(f"/blog/{blog.slug}/feed.atom").content.decode()
    js = client.get(f"/blog/{blog.slug}/feed.json").content.decode()
    for body in (rss, atom, js):
        assert post.title in body
        assert draft.title not in body


def test_the_feed_is_capped(client, blog, owner, settings):
    settings.SMALLSTACK_BLOG_FEED_LIMIT = 2
    for i in range(5):
        p = service.create_post(blog, title=f"Post {i}", body_markdown="x", actor=owner)
        service.publish_post(p, actor=owner)
    data = json.loads(client.get(f"/blog/{blog.slug}/feed.json").content.decode())
    assert len(data["items"]) == 2


# ── Switches ────────────────────────────────────────────────────────────────


@override_settings(SMALLSTACK_FEEDS_ENABLED=False)
def test_the_feeds_master_switch_reaches_blog_feeds_too(client, blog):
    """SMALLSTACK_FEEDS_ENABLED is enforced inside apps.feeds' own view, so a
    feed served from anywhere else has to check it itself — otherwise the
    switch silently misses half the feeds in the project."""
    assert client.get(f"/blog/{blog.slug}/feed.rss").status_code == 404
    assert client.get(f"/blog/{blog.slug}/feed.json").status_code == 404
    assert client.get("/blog/feed.json").status_code == 404


@override_settings(SMALLSTACK_BLOG_PUBLIC_ENABLED=False)
def test_blog_feeds_follow_the_public_surface_switch(client, blog):
    assert client.get(f"/blog/{blog.slug}/feed.rss").status_code == 404


def test_the_feed_channel_describes_the_blog(client, blog, post):
    body = client.get(f"/blog/{blog.slug}/feed.rss").content.decode()
    assert f"<title>{blog.name}</title>" in body
    assert blog.tagline in body


def test_a_blog_with_no_posts_still_renders_a_valid_feed(client, owner):
    empty = Blog.objects.create(
        name="Empty", slug="empty", owner=owner, visibility=Blog.Visibility.PUBLIC
    )
    response = client.get(f"/blog/{empty.slug}/feed.rss")
    assert response.status_code == 200
    assert "<rss" in response.content.decode()
