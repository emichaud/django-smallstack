"""Publishing a runbook document into a blog, and keeping it in sync.

Two properties this file exists to defend:

* **The blog never touches runbook's ORM.** Reads go through
  ``runbook.service`` and ``runbook.permissions`` so locking, authorization
  and the audit trail still apply — and so an agent cannot publish a document
  its token could not read.
* **Manual sync means manual.** Runbook's ``is_public`` means *signed-in
  users*, so publishing grants a genuinely new tier; silently overwriting an
  author's edits the next time someone touches the runbook would be a
  surprising way to change what the internet sees.
"""

from __future__ import annotations

import pytest

from apps.blog import service
from apps.blog.models import Post
from apps.runbook import service as runbook_service
from apps.runbook.models import Runbook

pytestmark = pytest.mark.django_db


@pytest.fixture
def runbook(owner):
    return Runbook.objects.create(name="Ops", slug="ops", owner=owner)


@pytest.fixture
def document(runbook, owner):
    result = runbook_service.put_document(
        runbook=runbook,
        key="failover",
        body="---\ntitle: Database Failover\ndescription: What to do at 3am.\n---\n\n"
        "# Database Failover\n\nPromote the replica.",
        title="Database Failover",
        actor=owner,
    )
    from apps.runbook.models import Document

    return Document.objects.get(pk=result.id)


# ── Publishing ──────────────────────────────────────────────────────────────


def test_publishing_a_document_creates_a_post_with_provenance(blog, document, owner):
    post = service.publish_document(document, blog, actor=owner)

    assert post.blog == blog
    assert post.source_document_id == document.pk
    assert post.source_document_uid == document.uid
    assert post.source_version == document.version
    assert post.source_synced_at is not None
    assert post.status == Post.Status.PUBLISHED
    assert post.is_live


def test_frontmatter_becomes_the_title_and_excerpt_and_leaves_the_body(blog, document, owner):
    """Runbook only *strips* frontmatter; this is where its keys finally mean
    something."""
    post = service.publish_document(document, blog, actor=owner)

    assert post.title == "Database Failover"
    assert post.excerpt == "What to do at 3am."
    assert "title:" not in post.body_markdown
    assert "---" not in post.body_markdown.split("Promote")[0]
    assert "Promote the replica." in post.body_markdown


def test_the_duplicated_h1_is_not_rendered_twice(blog, document, owner):
    """Runbook documents almost always open with an H1 matching their title,
    which is exactly the duplication the renderer strips."""
    post = service.publish_document(document, blog, actor=owner)
    assert post.body_html.count("<h1") == 0, "the page supplies the <h1>"
    assert "Promote the replica." in post.body_html


def test_publishing_twice_converges_instead_of_forking(blog, document, owner):
    """A double-click or a retried task must not create a second post — the
    partial unique constraint would refuse it, and failing there is worse
    than converging."""
    first = service.publish_document(document, blog, actor=owner)
    second = service.publish_document(document, blog, actor=owner)

    assert first.pk == second.pk
    assert Post.objects.filter(blog=blog, source_document=document).count() == 1


def test_the_same_document_can_feed_two_different_blogs(blog, other_blog, document, staff):
    a = service.publish_document(document, blog, actor=staff)
    b = service.publish_document(document, other_blog, actor=staff)
    assert a.pk != b.pk


def test_publishing_as_a_draft_is_possible(blog, document, owner):
    post = service.publish_document(
        document, blog, status=Post.Status.DRAFT, actor=owner
    )
    assert post.status == Post.Status.DRAFT
    assert not post.is_live


def test_an_explicit_slug_is_honoured_and_deduplicated(blog, document, owner):
    service.create_post(blog, title="Taken", slug="failover-guide", actor=owner)
    post = service.publish_document(document, blog, slug="failover-guide", actor=owner)
    assert post.slug == "failover-guide-2"


# ── Authorization ───────────────────────────────────────────────────────────


def test_you_cannot_publish_into_a_blog_you_do_not_own(other_blog, document, owner):
    with pytest.raises(service.NotAuthorized):
        service.publish_document(document, other_blog, actor=owner)


def test_you_cannot_publish_a_document_you_cannot_read(blog, document, other_user, owner):
    """The decisive one: runbook's `is_public` is False by default, so a
    stranger must not be able to launder a private document onto the internet
    through their own blog."""
    from apps.blog.models import Blog

    theirs = Blog.objects.create(
        name="Theirs", slug="theirs", owner=other_user, visibility=Blog.Visibility.PUBLIC
    )
    with pytest.raises(service.BlogServiceError):
        service.publish_document(document, theirs, actor=other_user)


def test_publishable_documents_is_scoped_to_the_viewer(document, owner, other_user, staff):
    assert document in service.publishable_documents(owner)
    assert document not in service.publishable_documents(other_user)
    assert document in service.publishable_documents(staff)


def test_a_public_runbook_is_publishable_by_a_signed_in_user(
    runbook, document, other_user, blog
):
    """Runbook "public" means signed-in, so a colleague can read it — and may
    therefore publish it into a blog they own."""
    runbook.is_public = True
    runbook.save(update_fields=["is_public"])
    assert document in service.publishable_documents(other_user)


# ── Resync ──────────────────────────────────────────────────────────────────


def test_resync_pulls_the_latest_version(blog, runbook, document, owner):
    post = service.publish_document(document, blog, actor=owner)
    runbook_service.put_document(
        runbook=runbook, key="failover", body="# Database Failover\n\nPromote, then page Ops.",
        actor=owner,
    )
    service.resync_post(post, actor=owner)
    post.refresh_from_db()

    assert "page Ops" in post.body_markdown
    assert "page Ops" in post.body_html


def test_resync_is_a_no_op_when_the_document_has_not_moved(blog, document, owner):
    """Otherwise an auto-sync receiver firing on an unrelated write churns
    updated_at — and with it every feed's lastBuildDate — for nothing."""
    post = service.publish_document(document, blog, actor=owner)
    before = post.updated_at

    service.resync_post(post, actor=owner)
    post.refresh_from_db()
    assert post.updated_at == before


def test_force_resyncs_even_at_the_same_version(blog, document, owner):
    post = service.publish_document(document, blog, actor=owner)
    Post.objects.filter(pk=post.pk).update(body_markdown="locally mangled")
    post.refresh_from_db()

    service.resync_post(post, actor=owner, force=True)
    post.refresh_from_db()
    assert "Promote the replica." in post.body_markdown


def test_resync_refuses_a_post_with_no_source_document(draft, owner):
    with pytest.raises(service.InvalidState):
        service.resync_post(draft, actor=owner)


# ── The document_written receiver ───────────────────────────────────────────


def test_an_auto_sync_post_follows_the_runbook(
    blog, runbook, document, owner, django_capture_on_commit_callbacks
):
    """`document_written` is emitted on transaction.on_commit, which does not
    fire inside a test's transaction — hence the capture fixture (the same one
    runbook's own signal tests use)."""
    post = service.publish_document(document, blog, sync="auto", actor=owner)

    with django_capture_on_commit_callbacks(execute=True):
        runbook_service.put_document(
            runbook=runbook, key="failover",
            body="# Database Failover\n\nNow with a rollback step.", actor=owner,
        )
    post.refresh_from_db()
    assert "rollback step" in post.body_markdown


def test_a_manual_sync_post_does_not(
    blog, runbook, document, owner, django_capture_on_commit_callbacks
):
    """Manual means manual — an author's edits are not silently replaced."""
    post = service.publish_document(document, blog, sync="manual", actor=owner)
    original = post.body_markdown

    with django_capture_on_commit_callbacks(execute=True):
        runbook_service.put_document(
            runbook=runbook, key="failover", body="# Database Failover\n\nChanged upstream.",
            actor=owner,
        )
    post.refresh_from_db()
    assert post.body_markdown == original


def test_resync_for_document_updates_only_auto_posts(blog, other_blog, runbook, document, staff):
    auto = service.publish_document(document, blog, sync="auto", actor=staff)
    manual = service.publish_document(document, other_blog, sync="manual", actor=staff)

    runbook_service.put_document(
        runbook=runbook, key="failover", body="# Database Failover\n\nRevised.", actor=staff
    )

    updated = service.resync_for_document(document, actor=None)
    assert auto.pk in updated
    assert manual.pk not in updated


def test_a_runbook_write_never_breaks_because_of_the_blog(
    blog, runbook, document, owner, monkeypatch, django_capture_on_commit_callbacks
):
    """The receiver is best-effort: a blog failure must not roll back the
    runbook write that triggered it."""
    service.publish_document(document, blog, sync="auto", actor=owner)

    def _boom(*args, **kwargs):
        raise RuntimeError("blog exploded")

    monkeypatch.setattr("apps.blog.tasks.enqueue_resync", _boom)

    result = runbook_service.put_document(
        runbook=runbook, key="failover", body="# Database Failover\n\nStill saved.",
        actor=owner,
    )
    from apps.runbook.models import Document

    assert "Still saved." in runbook_service.read_head(Document.objects.get(pk=result.id))


# ── The bridge reads runbook through its service, not its ORM ──────────────


def test_the_bridge_goes_through_runbook_service(blog, document, owner, monkeypatch):
    """Guards the architectural rule: if someone swaps in a direct ORM read,
    locking, permissions and audit silently stop applying."""
    called: list[str] = []
    real = runbook_service.read_head

    def _spy(doc):
        called.append("read_head")
        return real(doc)

    monkeypatch.setattr(runbook_service, "read_head", _spy)
    service.publish_document(document, blog, actor=owner)
    assert called, "publish_document should read the body via runbook.service.read_head"


# ── The console import picker ───────────────────────────────────────────────


IMPORT_URL = "/smallstack/blog/import-runbook/"


def test_the_picker_lists_only_documents_you_can_read(
    client, blog, other_blog, document, owner, other_user
):
    """Both actors need a blog of their own, or the page shows its
    "create a blog first" state instead of the document list."""
    client.force_login(owner)
    assert document.title in client.get(IMPORT_URL).content.decode()

    client.force_login(other_user)
    assert document.title not in client.get(IMPORT_URL).content.decode()


def test_the_picker_offers_only_blogs_you_can_write_to(
    client, blog, other_blog, document, owner
):
    """Needs a readable document too: the blog <select> lives in the
    "Publish into" card, which only renders when there is something to
    publish."""
    client.force_login(owner)
    body = client.get(IMPORT_URL).content.decode()
    assert f'value="{blog.pk}"' in body
    assert f'value="{other_blog.pk}"' not in body


def test_publishing_through_the_picker_works(client, blog, document, owner):
    client.force_login(owner)
    response = client.post(
        IMPORT_URL,
        {"document": document.pk, "blog": blog.pk, "status": "draft", "sync": "manual"},
    )
    assert response.status_code == 302
    post = Post.objects.get(source_document=document)
    assert post.blog == blog
    assert post.status == Post.Status.DRAFT


def test_the_picker_refuses_a_document_you_cannot_read(client, document, other_user):
    """A forged pk must 404 rather than launder a private runbook page onto a
    blog the attacker does own."""
    from apps.blog.models import Blog

    theirs = Blog.objects.create(
        name="Theirs", slug="theirs-pick", owner=other_user,
        visibility=Blog.Visibility.PUBLIC,
    )
    client.force_login(other_user)
    response = client.post(
        IMPORT_URL, {"document": document.pk, "blog": theirs.pk, "status": "draft"}
    )
    assert response.status_code == 404
    assert not Post.objects.filter(source_document=document).exists()


def test_the_picker_refuses_a_blog_you_do_not_own(client, blog, document, other_user, runbook):
    runbook.is_public = True
    runbook.save(update_fields=["is_public"])
    client.force_login(other_user)
    client.post(IMPORT_URL, {"document": document.pk, "blog": blog.pk, "status": "draft"})
    assert not Post.objects.filter(source_document=document).exists()


def test_the_picker_requires_login(client):
    assert client.get(IMPORT_URL).status_code == 302


def test_the_resync_action_pulls_fresh_content(client, blog, runbook, document, owner):
    post = service.publish_document(document, blog, actor=owner)
    runbook_service.put_document(
        runbook=runbook, key="failover", body="# Database Failover\n\nNewer text.", actor=owner
    )
    client.force_login(owner)
    client.post(f"/smallstack/blog/posts/{post.pk}/resync/")
    post.refresh_from_db()
    assert "Newer text." in post.body_markdown


def test_the_resync_action_refuses_a_stranger(client, blog, document, owner, other_user):
    post = service.publish_document(document, blog, actor=owner)
    client.force_login(other_user)
    assert client.post(f"/smallstack/blog/posts/{post.pk}/resync/").status_code == 404
