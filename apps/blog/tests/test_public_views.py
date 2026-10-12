"""The anonymous reading surface.

The highest-severity defect this app can ship is a draft or a private blog
appearing on the internet — a *fail-open* bug, where a dropped filter returns
MORE rows and raises nothing. So the draft-leak checks here enumerate every
public surface rather than sampling one: permalink, blog index, site index,
JSON API, sitemap-ish listings and search all get asserted separately, because
each is a different queryset and only one of them has to be wrong.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.blog import service
from apps.blog.models import Post

pytestmark = pytest.mark.django_db


# ── Reachability ────────────────────────────────────────────────────────────


def test_public_pages_are_reachable_anonymously(client, blog, post):
    for path in (
        "/blog/",
        f"/blog/{blog.slug}/",
        f"/blog/{blog.slug}/{post.slug}/",
        f"/blog/{blog.slug}/archive/",
        f"/blog/{blog.slug}/search/",
    ):
        assert client.get(path).status_code == 200, path


def test_the_permalink_is_what_get_absolute_url_says(post):
    assert post.get_absolute_url() == "/blog/field-notes/hello-world/"


def test_blog_and_tag_permalinks(blog):
    from apps.blog.models import Tag

    tag = Tag.objects.create(blog=blog, name="Ops", slug="ops")
    assert blog.get_absolute_url() == "/blog/field-notes/"
    assert tag.get_absolute_url() == "/blog/field-notes/tag/ops/"


def test_the_shortlink_redirects_to_the_permalink(client, post):
    response = client.get(f"/blog/p/{post.uid}/")
    assert response.status_code == 302
    assert response.url == post.get_absolute_url()


# ── Draft containment — one assertion per surface ──────────────────────────


def test_a_draft_permalink_404s_for_everyone_but_its_owner(
    client, blog, draft, owner, other_user
):
    path = f"/blog/{blog.slug}/{draft.slug}/"
    assert client.get(path).status_code == 404

    client.force_login(other_user)
    assert client.get(path).status_code == 404

    client.force_login(owner)
    response = client.get(path)
    assert response.status_code == 200
    assert "Draft preview" in response.content.decode()


def test_a_draft_appears_on_no_public_listing(client, blog, draft, scheduled_post,
                                              future_published_post):
    for path in (
        "/blog/",
        f"/blog/{blog.slug}/",
        f"/blog/{blog.slug}/archive/",
        f"/blog/{blog.slug}/feed.rss",
        f"/blog/{blog.slug}/feed.json",
        "/blog/feed.json",
        "/feed/blog.rss",
        f"/blog/api/blogs/{blog.slug}/posts/",
    ):
        body = client.get(path).content.decode()
        for hidden in (draft.title, scheduled_post.title, future_published_post.title):
            assert hidden not in body, f"{hidden!r} leaked on {path}"


def test_an_embargoed_post_is_not_public_until_its_moment(client, blog, future_published_post):
    """status=published with a future timestamp. Filtering on status alone —
    the easy mistake — would publish this early."""
    assert client.get(f"/blog/{blog.slug}/{future_published_post.slug}/").status_code == 404

    Post.objects.filter(pk=future_published_post.pk).update(
        published_at=future_published_post.created_at
    )
    assert client.get(f"/blog/{blog.slug}/{future_published_post.slug}/").status_code == 200


# ── Blog visibility tiers ───────────────────────────────────────────────────


def test_a_private_blog_404s_for_strangers_and_opens_for_its_owner(
    client, private_blog, owner, other_user, staff
):
    path = f"/blog/{private_blog.slug}/"
    assert client.get(path).status_code == 404

    client.force_login(other_user)
    assert client.get(path).status_code == 404

    client.force_login(owner)
    assert client.get(path).status_code == 200

    client.force_login(staff)
    assert client.get(path).status_code == 200


def test_a_members_blog_redirects_anonymous_to_login_rather_than_404(
    client, members_blog, other_user
):
    """Not a 404: a members blog exists so a team can share its URL, and
    answering "no such page" to a colleague who merely isn't signed in yet
    makes that workflow baffling. The contents stay hidden either way."""
    response = client.get(f"/blog/{members_blog.slug}/")
    assert response.status_code == 302
    assert "/login" in response.url

    client.force_login(other_user)
    assert client.get(f"/blog/{members_blog.slug}/").status_code == 200


def test_the_index_lists_only_blogs_you_may_read(
    client, blog, members_blog, private_blog, other_blog, owner
):
    body = client.get("/blog/").content.decode()
    assert blog.name in body
    assert other_blog.name in body
    assert members_blog.name not in body
    assert private_blog.name not in body

    client.force_login(owner)
    body = client.get("/blog/").content.decode()
    assert members_blog.name in body
    assert private_blog.name in body


def test_the_index_post_count_excludes_drafts(client, blog, post, draft, scheduled_post):
    """The count annotation must use the same definition of "live" the lists
    do, or the index advertises posts a visitor cannot open."""
    body = client.get("/blog/").content.decode()
    assert "1 post" in body


# ── The master switch ───────────────────────────────────────────────────────


@override_settings(SMALLSTACK_BLOG_PUBLIC_ENABLED=False)
def test_every_public_route_404s_when_the_surface_is_disabled(client, blog, post):
    """404, not 403 — a disabled feature should look absent. And the JSON
    endpoints must honour the same switch as the HTML ones."""
    for path in (
        "/blog/",
        f"/blog/{blog.slug}/",
        f"/blog/{blog.slug}/{post.slug}/",
        f"/blog/{blog.slug}/archive/",
        f"/blog/{blog.slug}/search/",
        f"/blog/{blog.slug}/feed.rss",
        "/blog/feed.json",
        "/blog/api/blogs/",
        f"/blog/api/blogs/{blog.slug}/posts/",
        f"/blog/api/blogs/{blog.slug}/tags/",
        f"/blog/p/{post.uid}/",
    ):
        assert client.get(path).status_code == 404, f"{path} stayed reachable"


@override_settings(SMALLSTACK_BLOG_PUBLIC_ENABLED=False)
def test_the_console_still_works_when_the_public_surface_is_off(client, owner, draft):
    """"Drafting internally, nothing public yet" is a real state — disabling
    the reading surface must not disable authoring."""
    client.force_login(owner)
    assert client.get("/smallstack/blog/posts/").status_code == 200


# ── Reserved slugs cannot shadow a route ────────────────────────────────────


def test_a_post_cannot_be_slugged_to_shadow_a_sibling_route(blog, owner):
    """`/<blog>/<post>/` is a catch-all, so a post slugged `archive` or
    `feed.rss` would be unreachable. The service renames instead of failing."""
    for wanted in ("archive", "feed", "search", "tag"):
        p = service.create_post(blog, title=wanted.title(), slug=wanted, actor=owner)
        assert p.slug != wanted


def test_the_sibling_routes_still_win(client, blog, post):
    assert client.get(f"/blog/{blog.slug}/archive/").status_code == 200
    assert client.get(f"/blog/{blog.slug}/search/").status_code == 200


# ── Public JSON API ─────────────────────────────────────────────────────────


def test_api_blogs_lists_only_readable_blogs(client, blog, private_blog):
    data = client.get("/blog/api/blogs/").json()
    slugs = {b["slug"] for b in data["blogs"]}
    assert blog.slug in slugs
    assert private_blog.slug not in slugs


def test_api_posts_returns_published_only(client, blog, post, draft):
    data = client.get(f"/blog/api/blogs/{blog.slug}/posts/").json()
    titles = {p["title"] for p in data["posts"]}
    assert post.title in titles
    assert draft.title not in titles
    assert data["count"] == 1


def test_api_post_detail_includes_the_body(client, blog, post):
    data = client.get(f"/blog/api/blogs/{blog.slug}/posts/{post.slug}/").json()
    assert data["post"]["body_html"]
    assert data["post"]["body_markdown"]
    assert data["post"]["url"] == post.get_absolute_url()


def test_api_post_detail_404s_for_a_draft(client, blog, draft):
    assert client.get(f"/blog/api/blogs/{blog.slug}/posts/{draft.slug}/").status_code == 404


def test_api_is_anonymous_unlike_the_console_rest(client, blog, post):
    """The console REST at /smallstack/api/blog/* authenticates every request;
    this one is the anonymous *read* surface. Pinning both halves so nobody
    later wires a public reader UI to the 401-ing one."""
    assert client.get(f"/blog/api/blogs/{blog.slug}/posts/").status_code == 200
    assert client.get("/smallstack/api/blog/posts/").status_code == 401


def test_api_for_a_members_blog_404s_rather_than_redirecting(client, members_blog):
    """A JSON client has nowhere to follow a login redirect to."""
    assert client.get(f"/blog/api/blogs/{members_blog.slug}/posts/").status_code == 404


def test_api_responses_are_cacheable(client, blog):
    response = client.get("/blog/api/blogs/")
    assert "max-age" in response["Cache-Control"]


def test_no_subscriber_data_appears_on_any_public_surface(
    client, blog, post, confirmed_sub, subscriber
):
    for path in (
        "/blog/",
        f"/blog/{blog.slug}/",
        f"/blog/{blog.slug}/{post.slug}/",
        f"/blog/{blog.slug}/feed.rss",
        "/blog/api/blogs/",
        f"/blog/api/blogs/{blog.slug}/posts/",
    ):
        assert subscriber.email not in client.get(path).content.decode(), path


# ── Rendering ───────────────────────────────────────────────────────────────


def test_the_post_page_renders_the_hardened_html(client, blog, owner):
    hostile = service.create_post(
        blog, title="Hostile", body_markdown="<img src=x onerror=alert(1)>", actor=owner
    )
    service.publish_post(hostile, actor=owner)
    body = client.get(f"/blog/{blog.slug}/{hostile.slug}/").content.decode()
    assert "<img src=x onerror=alert(1)>" not in body


def test_the_title_is_not_rendered_twice(client, blog, owner):
    """A markdown body that opens with the post's own title would otherwise
    produce two <h1>s — visibly wrong and an accessibility defect."""
    p = service.create_post(
        blog, title="Repeated", body_markdown="# Repeated\n\nBody text.", actor=owner
    )
    service.publish_post(p, actor=owner)
    body = client.get(f"/blog/{blog.slug}/{p.slug}/").content.decode()
    assert body.count("<h1") == 1


def test_a_different_first_heading_is_preserved(client, blog, owner):
    p = service.create_post(
        blog, title="Outer", body_markdown="# Something Else\n\nBody.", actor=owner
    )
    service.publish_post(p, actor=owner)
    assert "Something Else" in p.body_html


def test_the_page_carries_feed_discovery_and_canonical_links(client, blog, post):
    body = client.get(f"/blog/{blog.slug}/{post.slug}/").content.decode()
    assert 'rel="alternate"' in body
    assert 'rel="canonical"' in body
    assert 'property="og:title"' in body


def test_the_public_pages_do_not_load_the_admin_shell(client, blog, post):
    """A standalone template, per the /status/ pattern — no sidebar, no topbar."""
    body = client.get(f"/blog/{blog.slug}/{post.slug}/").content.decode()
    assert "sidebar" not in body.lower()
    assert "skip-link" in body, "but it must still have the a11y skip link"
