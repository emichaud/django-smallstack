"""Runbook Document ↔ SmallStack search engine integration.

Verifies Document is registered with apps.search (ranked FTS, correct hit
shape) and that ownership scoping (permissions.viewable_documents) governs who
sees what — the same rule as every other surface.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.runbook import service
from apps.runbook.models import Document
from apps.runbook.search import DocumentSearchConfig

from ._factory import make_document, make_runbook

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def _engine():
    from apps.search.backends import get_backend
    from apps.search.registry import get_view

    return get_backend(), get_view(Document)


def _scoped_ids(query, user):
    """Object ids for ``query``, after applying the view's ownership visibility."""
    be, view = _engine()
    ids = [h.object_id for h in be.query(view, query, limit=25)]
    qs = Document.objects.filter(pk__in=ids)
    return set(DocumentSearchConfig.search_visibility(qs, user).values_list("pk", flat=True))


class TestRegistration:
    def test_document_is_registered(self):
        from apps.search.registry import get_view

        view = get_view(Document)
        assert view is not None
        assert "title" in view.fields and "content_text" in view.fields
        assert view.access == "authenticated"

    def test_written_doc_is_findable_ranked_with_url_and_subtitle(self):
        rb = make_runbook(name="KB", slug="kb")
        make_document(title="Zebra deployment guide", slug="zeb", runbook=rb, body=b"# Zebra\n\nHow to deploy zebras.")
        be, view = _engine()
        hits = be.query(view, "zebra", limit=10)
        top = next((h for h in hits if "Zebra" in h.display), None)
        assert top is not None
        assert top.url and top.url.startswith("/")     # from Document.get_absolute_url
        assert top.subtitle == "KB"                     # search_subtitle_text property (runbook, no section)
        assert top.rank                                 # BM25 score present


class TestVisibility:
    def test_private_doc_hidden_from_non_owner(self):
        owner = User.objects.create_user("own", password="p")
        other = User.objects.create_user("oth", password="p")
        staff = User.objects.create_user("stf", password="p", is_staff=True)
        rb = make_runbook(name="Priv", slug="priv", owner=owner, is_public=False)
        doc = make_document(title="Secret zonkey notes", slug="sec", runbook=rb, body=b"# secret zonkey")

        assert doc.pk in _scoped_ids("zonkey", owner)        # owner sees own private doc
        assert doc.pk not in _scoped_ids("zonkey", other)    # non-owner does not
        assert doc.pk in _scoped_ids("zonkey", staff)        # staff sees everything

    def test_public_doc_visible_to_any_user(self):
        other = User.objects.create_user("pub_other", password="p")
        rb = make_runbook(name="Pub", slug="pub", is_public=True)
        doc = make_document(title="Public quokka doc", slug="pub-doc", runbook=rb, body=b"# quokka")
        assert doc.pk in _scoped_ids("quokka", other)

    def test_archived_doc_excluded(self):
        user = User.objects.create_user("arc_user", password="p")
        rb = make_runbook(name="Arc", slug="arc", is_public=True)
        doc = make_document(title="Archived numbat doc", slug="arc-doc", runbook=rb, body=b"# numbat")
        doc.is_archived = True
        doc.save(update_fields=["is_archived"])
        assert doc.pk not in _scoped_ids("numbat", user)


class TestReindexOnWrite:
    def test_new_version_reindexes_content(self):
        make_runbook(name="RX", slug="rx")
        service.put_document("rx", "d", body="# nothing special here", title="D")
        be, view = _engine()
        assert not [h for h in be.query(view, "wombat", limit=10)]      # term not present yet
        service.put_document("rx", "d", body="# now all about the wombat", on_exists="overwrite")
        assert [h for h in be.query(view, "wombat", limit=10)]          # reindexed on write
