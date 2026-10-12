"""Blog posts in the framework search registry.

Two halves, and the **positive** half matters as much as the negative one. A
`search_visibility` callable that raises makes the registry drop every hit from
that view — it fails safe, so a broken scoper looks exactly like "no results"
with no error logged anywhere the developer will see. That is precisely what a
reversed argument order did here: `apps.search` calls
`search_visibility(queryset, user)` while the blog scopers take
`(user, queryset)`, so search returned nothing at all and no test noticed
because every assertion was of the form "the draft is absent".

So: assert that the right things ARE found, not only that the wrong things
are not.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.blog import permissions
from apps.blog.models import Blog, Post
from apps.search.backends import get_backend
from apps.search.registry import all_views, search_all

pytestmark = pytest.mark.django_db

POST_LABEL = "smallstack_blog.Post"


def _reindex() -> None:
    """Rebuild only the Post index.

    Rebuilding every registered view would also touch the help-docs index,
    whose table is not provisioned in every test's database — an unrelated
    OperationalError that says nothing about the blog.
    """
    backend = get_backend()
    for view in all_views():
        if view.model_label == POST_LABEL:
            backend.rebuild(view)


def _post_hits(query: str, user) -> list[int]:
    return [h.object_id for h in search_all(query, user=user, limit_per_model=50) if h.model_label == POST_LABEL]


# ── The positive case ───────────────────────────────────────────────────────


def test_anonymous_finds_a_published_post_in_a_public_blog(post):
    """The test that would have caught the reversed-arguments bug."""
    _reindex()
    assert post.pk in _post_hits("Hello", AnonymousUser())


def test_the_owner_finds_her_own_draft(draft, owner):
    _reindex()
    assert draft.pk in _post_hits("Unfinished", owner)


def test_search_matches_the_body_not_only_the_title(blog, owner):
    from apps.blog import service

    p = service.create_post(blog, title="Opaque Title", body_markdown="A paragraph about zebras.", actor=owner)
    service.publish_post(p, actor=owner)
    _reindex()
    assert p.pk in _post_hits("zebras", AnonymousUser())


# ── The negative cases ──────────────────────────────────────────────────────


def test_anonymous_never_finds_a_draft(draft):
    _reindex()
    assert _post_hits("Unfinished", AnonymousUser()) == []


def test_a_signed_in_stranger_never_finds_someone_elses_draft(draft, other_user):
    _reindex()
    assert draft.pk not in _post_hits("Unfinished", other_user)


def test_anonymous_never_finds_a_post_in_a_private_blog(private_blog, owner):
    from apps.blog import service

    p = service.create_post(private_blog, title="Hidden Gem", body_markdown="x", actor=owner)
    service.publish_post(p, actor=owner)
    _reindex()
    assert _post_hits("Hidden Gem", AnonymousUser()) == []
    assert p.pk in _post_hits("Hidden Gem", owner), "the owner should still find it"


def test_anonymous_never_finds_a_post_in_a_members_blog(members_blog, owner, other_user):
    from apps.blog import service

    p = service.create_post(members_blog, title="Team Only", body_markdown="x", actor=owner)
    service.publish_post(p, actor=owner)
    _reindex()
    assert _post_hits("Team Only", AnonymousUser()) == []
    assert p.pk in _post_hits("Team Only", other_user), "a colleague should find it"


def test_an_embargoed_post_is_not_findable(future_published_post):
    """status=published with a future timestamp must not surface."""
    _reindex()
    assert _post_hits("Embargoed", AnonymousUser()) == []


# ── The adapters themselves ─────────────────────────────────────────────────


def test_search_visibility_adapters_take_queryset_first(blog, post, owner):
    """Pins the calling convention the registry actually uses.

    If someone swaps these back to the `(user, queryset)` scopers, this fails
    immediately and loudly instead of search quietly returning nothing.
    """
    qs = Post.objects.all()
    assert list(permissions.search_visible_posts(qs, owner))
    assert list(permissions.search_visible_blogs(Blog.objects.all(), owner))


def test_the_registered_views_use_the_adapters():
    """Guards the wiring, not just the helper."""
    from apps.blog.views import BlogCRUDView, PostCRUDView

    assert PostCRUDView.search_visibility is permissions.search_visible_posts
    assert BlogCRUDView.search_visibility is permissions.search_visible_blogs


def test_post_search_is_anonymous_tier_and_blog_search_is_not():
    """Published posts are public content; the list of every publication on the
    installation is not — so the two sit at different access tiers."""
    from apps.blog.views import BlogCRUDView, PostCRUDView

    assert PostCRUDView.search_access == "anonymous"
    assert BlogCRUDView.search_access == "authenticated"


# ── The public per-blog search page ─────────────────────────────────────────


def test_the_public_search_page_finds_published_posts(client, post):
    _reindex()
    body = client.get(f"/blog/{post.blog.slug}/search/?q=Hello").content.decode()
    assert post.title in body


def test_the_public_search_page_hides_drafts(client, blog, draft):
    _reindex()
    body = client.get(f"/blog/{blog.slug}/search/?q=Unfinished").content.decode()
    # Assert on the permalink, not the title: the title IS the query here, so
    # it legitimately appears in the echoed search box. Only a result card
    # links to the post.
    assert f"/{draft.slug}/" not in body
    assert "Nothing matched" in body


# ── SearchBuilder: the article-card result shape ────────────────────────────
#
# PostCRUDView implements the SearchBuilder protocol so a hit carries more
# than a title and a subtitle. These pin the contract the public search page
# and the MCP tool rely on: the extra keys, the `card` discriminator, the
# compact variant, and the variant→tool registration.


def _tagged_post(post, *names):
    from apps.blog import service

    service.set_post_tags(post, list(names))
    post.refresh_from_db()
    return post


def test_post_crudview_is_a_search_builder():
    view = next(v for v in all_views() if v.model_label == POST_LABEL)
    assert view.has_search_builder is True


def test_transform_hit_default_variant_shapes_an_article_card(post):
    from apps.blog.views import PostCRUDView

    post = _tagged_post(post, "Horology", "Essay")
    hit = PostCRUDView().transform_hit(post)
    assert hit["display"] == post.title
    assert hit["subtitle"] == post.excerpt
    assert hit["card"] == "article"
    assert hit["blog"] == post.blog.name
    assert hit["blog_url"] == post.blog.get_absolute_url()
    assert hit["published_at"] == post.published_at.isoformat()
    assert hit["reading_minutes"] >= 1
    assert hit["tags"] == ["Essay", "Horology"]  # sorted by name
    assert hit["cover_url"] == ""  # no cover on the fixture; never raises


def test_transform_hit_compact_variant_is_title_and_permalink_only(post):
    from apps.blog.views import PostCRUDView

    hit = PostCRUDView().transform_hit(post, "compact")
    assert hit == {"display": post.title, "url": post.get_absolute_url()}


def test_reading_time_is_derived_from_the_rendered_body(blog, owner):
    from apps.blog import service
    from apps.blog.views import WORDS_PER_MINUTE, search_hit_for_post

    long_post = service.create_post(
        blog, title="Long read", body_markdown=("lorem " * (WORDS_PER_MINUTE * 5)), author=owner
    )
    service.publish_post(long_post)
    long_post.refresh_from_db()
    assert search_hit_for_post(long_post)["reading_minutes"] == 5


def test_search_hits_carry_the_article_card_extra(post):
    """The backend routes transform_hit's extra keys into SearchHit.extra —
    which is what the public search page branches on."""
    _reindex()
    hits = [h for h in search_all("Hello", user=AnonymousUser(), limit_per_model=50) if h.model_label == POST_LABEL]
    assert hits, "the published post must be found before its shape can be checked"
    extra = hits[0].extra
    assert extra["card"] == "article"
    assert extra["blog"] == post.blog.name
    assert "reading_minutes" in extra
    # display/subtitle were lifted out of the dict, not duplicated into extra.
    assert "display" not in extra and "subtitle" not in extra
    assert hits[0].display == post.title


def test_compact_variant_registers_its_own_mcp_tool():
    from apps.mcp.server import TOOL_REGISTRY

    assert "search_blog_posts" in TOOL_REGISTRY
    assert "search_blog_posts_compact" in TOOL_REGISTRY
