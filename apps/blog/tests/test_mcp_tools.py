"""The blog's MCP surface.

Two kinds of assertion here. The ordinary kind — the tools work and respect
the same scoping as every other surface. And the kind that guards a deliberate
*omission*: there is no send tool, and the subscriber models are not exposed
at all. An omission has no code to point at, so without a test it quietly
stops being true the first time someone adds a flag "for symmetry".
"""

from __future__ import annotations

import pytest

from apps.blog import mcp_tools
from apps.blog.models import Post

pytestmark = pytest.mark.django_db


# ── Registration ────────────────────────────────────────────────────────────


def _registry() -> dict:
    from apps.mcp.server import TOOL_REGISTRY

    return TOOL_REGISTRY


@pytest.mark.parametrize(
    "name",
    [
        "blog_draft_post",
        "blog_publish_post",
        "blog_unpublish_post",
        "blog_list_publishable_documents",
        "blog_publish_runbook_document",
        "blog_resync_post",
    ],
)
def test_the_custom_tools_are_registered(name):
    assert name in _registry()


@pytest.mark.parametrize(
    "name",
    [
        "list_blogs", "get_blog", "create_blog", "update_blog", "delete_blog",
        "list_blog_posts", "get_blog_post", "create_blog_post",
        "update_blog_post", "delete_blog_post",
        "list_newsletter_issues", "get_newsletter_issue",
        "create_newsletter_issue", "update_newsletter_issue",
        "search_blogs", "search_blog_posts",
    ],
)
def test_the_generated_tools_are_registered(name):
    assert name in _registry()


def test_tool_names_are_namespaced_not_common_nouns():
    """`search_posts` or `list_posts` in a namespace shared with every other
    app — and every downstream project — is the same collision the
    `smallstack_blog` app label avoids."""
    assert "search_posts" not in _registry()
    assert "list_posts" not in _registry()
    assert "search_blog_posts" in _registry()


# ── The deliberate omissions ────────────────────────────────────────────────


def test_there_is_no_tool_that_sends_a_newsletter():
    """Mailing thousands of real people is not something a tool call should be
    able to do. Issues can be drafted over MCP; sending stays a human action
    behind a confirmation in the console."""
    forbidden = [
        name
        for name in _registry()
        if any(word in name for word in ("send", "queue"))
        and ("blog" in name or "newsletter" in name or "issue" in name)
    ]
    assert forbidden == [], f"a send/queue tool appeared: {forbidden}"


def test_the_pii_models_are_not_exposed_to_mcp():
    """Asserted on the flags, which is where the decision lives.

    A `Subscriber` row aggregates across every blog an address subscribes to,
    and a `Delivery` row is a log of who was mailed what. A tool that pages
    either into an LLM client is a data-exfiltration surface, not a feature.
    """
    from apps.blog.views import DeliveryCRUDView, SubscriberCRUDView, SubscriptionCRUDView

    for view in (SubscriberCRUDView, SubscriptionCRUDView, DeliveryCRUDView):
        assert view.enable_mcp is False, f"{view.__name__} opted into MCP"
        assert view.enable_search is False, f"{view.__name__} opted into search"


def test_no_blog_tool_is_named_for_subscriber_data():
    """Scoped to this app's tools — `replay_delivery` and friends belong to
    webhooks and are a different thing entirely."""
    blog_tools = [
        name
        for name in _registry()
        if name.startswith("blog_") or "blog" in name or "newsletter" in name
    ]
    leaky = [
        name
        for name in blog_tools
        if any(word in name for word in ("subscriber", "subscription", "delivery", "deliveries"))
    ]
    assert leaky == [], f"subscriber data was exposed to MCP: {leaky}"
    assert blog_tools, "no blog tools found — the assertion would be vacuous"


# ── Delegates: drafting and publishing ──────────────────────────────────────


def test_draft_post_creates_a_draft_with_tags(blog, owner):
    result = mcp_tools.do_draft_post(
        owner,
        blog=blog.slug,
        title="From an agent",
        body_markdown="# From an agent\n\nWritten by a tool.",
        tags=["ops", "automation"],
    )
    assert result["status"] == Post.Status.DRAFT
    assert result["slug"] == "from-an-agent"
    assert set(result["tags"]) == {"ops", "automation"}

    post = Post.objects.get(uid=result["uid"])
    # The body repeats the title, as an agent's markdown usually will, so the
    # duplicate heading is dropped — the page supplies the <h1>.
    assert "<h1" not in post.body_html
    assert post.excerpt == "Written by a tool."


def test_draft_post_keeps_a_heading_that_differs_from_the_title(blog, owner):
    result = mcp_tools.do_draft_post(
        owner, blog=blog.slug, title="Outer", body_markdown="# Something else\n\nBody."
    )
    assert "<h1" in Post.objects.get(uid=result["uid"]).body_html


def test_draft_post_refuses_a_blog_you_do_not_own(other_blog, owner):
    result = mcp_tools.do_draft_post(owner, blog=other_blog.slug, title="Intrusion")
    assert "error" in result
    assert not Post.objects.filter(title="Intrusion").exists()


def test_publish_and_unpublish_round_trip(draft, owner):
    published = mcp_tools.do_publish_post(owner, post=str(draft.uid))
    assert published["status"] == Post.Status.PUBLISHED
    assert published["published_at"]

    back = mcp_tools.do_unpublish_post(owner, post=str(draft.uid))
    assert back["status"] == Post.Status.DRAFT


def test_publishing_accepts_a_numeric_id_too(draft, owner):
    assert mcp_tools.do_publish_post(owner, post=draft.pk)["status"] == Post.Status.PUBLISHED


def test_publish_refuses_a_post_you_cannot_edit(draft, other_user):
    result = mcp_tools.do_publish_post(other_user, post=str(draft.uid))
    assert "error" in result
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT


def test_an_unknown_post_and_an_inaccessible_one_answer_identically(draft, other_user):
    """Whether a post exists is not something an agent without access should
    be able to probe for."""
    missing = mcp_tools.do_publish_post(other_user, post="00000000-0000-0000-0000-000000000000")
    forbidden = mcp_tools.do_publish_post(other_user, post=str(draft.uid))
    assert "error" in missing and "error" in forbidden


# ── Delegates: the runbook bridge ───────────────────────────────────────────


@pytest.fixture
def runbook_doc(owner):
    from apps.runbook import service as runbook_service
    from apps.runbook.models import Document, Runbook

    rb = Runbook.objects.create(name="Ops", slug="ops", owner=owner)
    result = runbook_service.put_document(
        runbook=rb, key="failover", title="Failover",
        body="---\ntitle: Failover\ndescription: At 3am.\n---\n\n# Failover\n\nPromote.",
        actor=owner,
    )
    return Document.objects.get(pk=result.id)


def test_list_publishable_documents_is_scoped(runbook_doc, owner, other_user):
    mine = mcp_tools.do_list_publishable_documents(owner)
    assert any(d["uid"] == str(runbook_doc.uid) for d in mine["results"])

    theirs = mcp_tools.do_list_publishable_documents(other_user)
    assert theirs["results"] == []


def test_list_publishable_documents_filters(runbook_doc, owner):
    assert mcp_tools.do_list_publishable_documents(owner, query="failover")["results"]
    assert mcp_tools.do_list_publishable_documents(owner, query="nothing")["results"] == []


def test_publish_runbook_document_creates_a_post(blog, runbook_doc, owner):
    result = mcp_tools.do_publish_runbook_document(
        owner, document=str(runbook_doc.uid), blog=blog.slug
    )
    assert result["title"] == "Failover"
    assert result["status"] == Post.Status.DRAFT, "draft by default — review before live"
    assert result["source_document_uid"] == str(runbook_doc.uid)


def test_publish_runbook_document_cannot_launder_a_private_document(
    runbook_doc, other_user
):
    """The decisive one: a stranger must not be able to push a runbook
    document they cannot read onto a blog they *do* own."""
    from apps.blog.models import Blog

    theirs = Blog.objects.create(
        name="Theirs", slug="theirs-mcp", owner=other_user, visibility=Blog.Visibility.PUBLIC
    )
    result = mcp_tools.do_publish_runbook_document(
        other_user, document=str(runbook_doc.uid), blog=theirs.slug
    )
    assert "error" in result
    assert not Post.objects.filter(source_document=runbook_doc).exists()


def test_resync_pulls_the_latest_version(blog, runbook_doc, owner):
    from apps.runbook import service as runbook_service

    published = mcp_tools.do_publish_runbook_document(
        owner, document=str(runbook_doc.uid), blog=blog.slug
    )
    runbook_service.put_document(
        runbook="ops", key="failover", body="# Failover\n\nNow with rollback.", actor=owner
    )
    result = mcp_tools.do_resync_post(owner, post=published["uid"])
    assert "error" not in result
    assert "rollback" in Post.objects.get(uid=published["uid"]).body_markdown


# ── Generated tools honour the scopers ──────────────────────────────────────


def test_list_blog_posts_is_scoped_by_the_same_queryset(draft, other_blog, other_user):
    """The MCP factory routes through get_list_queryset, so one scoper covers
    the console, REST and MCP alike."""
    from apps.blog.views import PostCRUDView

    theirs = Post.objects.create(
        blog=other_blog, title="Theirs", slug="theirs-mcp", author=other_user
    )
    visible = PostCRUDView.scope(Post.objects.all(), draft.author)
    assert draft in visible
    assert theirs not in visible
