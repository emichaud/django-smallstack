"""End-to-end ownership + visibility enforcement across web + service + REST."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.runbook import service
from apps.runbook.models import Runbook

from ._factory import make_document, make_runbook

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def owner(db):
    return User.objects.create_user("owner", password="p")


@pytest.fixture
def other(db):
    return User.objects.create_user("other", password="p")


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff", password="p", is_staff=True)


def _client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def private_rb(owner):
    rb = make_runbook(name="Priv", slug="priv", owner=owner, is_public=False)
    make_document(title="Secret", slug="secret", runbook=rb, key="secret")
    return rb


@pytest.mark.django_db
class TestWebVisibility:
    def test_owner_sees_and_edits_own_private_runbook(self, owner, private_rb):
        c = _client(owner)
        assert c.get(private_rb.get_absolute_url()).status_code == 200
        doc = private_rb.documents.first()
        assert c.get(reverse("runbook:document_detail", kwargs={"pk": doc.pk})).status_code == 200

    def test_other_cannot_see_private_runbook(self, other, private_rb):
        c = _client(other)
        assert c.get(private_rb.get_absolute_url()).status_code == 403
        doc = private_rb.documents.first()
        assert c.get(reverse("runbook:document_detail", kwargs={"pk": doc.pk})).status_code == 403

    def test_private_runbook_absent_from_others_dashboard_and_search(self, other, private_rb):
        c = _client(other)
        doc = private_rb.documents.first()
        doc_url = reverse("runbook:document_detail", kwargs={"pk": doc.pk})
        # Neither the runbook nor its doc link appears on another user's dashboard/search.
        assert private_rb.get_absolute_url() not in c.get(reverse("runbook:dashboard")).content.decode()
        search_html = c.get(reverse("runbook:search"), {"q": "Secret"}).content.decode()
        assert doc_url not in search_html and "0 results" in search_html

    def test_staff_sees_private_runbook(self, staff, private_rb):
        assert _client(staff).get(private_rb.get_absolute_url()).status_code == 200

    def test_public_runbook_readable_but_not_editable_by_other(self, owner, other):
        rb = make_runbook(name="Pub", slug="pub", owner=owner, is_public=True)
        c = _client(other)
        assert c.get(rb.get_absolute_url()).status_code == 200                 # readable
        assert c.get(reverse("runbook:runbook_update", kwargs={"slug": "pub"})).status_code == 403  # not editable

    def test_non_owner_cannot_edit_content(self, other, private_rb):
        doc = private_rb.documents.first()
        c = _client(other)
        assert c.get(reverse("runbook:document_edit_content", kwargs={"pk": doc.pk})).status_code == 403


@pytest.mark.django_db
class TestOwnershipOnCreate:
    def test_created_runbook_is_owned_and_private(self, owner):
        c = _client(owner)
        resp = c.post(reverse("runbook:runbook_create"), {"name": "Mine", "icon": "📘"})
        assert resp.status_code == 302
        rb = Runbook.objects.get(name="Mine")
        assert rb.owner_id == owner.id and rb.is_public is False


@pytest.mark.django_db
class TestPublishToggle:
    def test_owner_publishes_then_privates(self, owner, private_rb):
        c = _client(owner)
        url = reverse("runbook:runbook_publish", kwargs={"slug": "priv"})
        c.post(url)
        private_rb.refresh_from_db()
        assert private_rb.is_public is True
        c.post(url)
        private_rb.refresh_from_db()
        assert private_rb.is_public is False

    def test_other_cannot_publish(self, other, private_rb):
        resp = _client(other).post(reverse("runbook:runbook_publish", kwargs={"slug": "priv"}))
        assert resp.status_code == 403


@pytest.mark.django_db
class TestServiceAuthz:
    def test_non_viewer_write_hides_existence_as_not_found(self, other, private_rb):
        # A caller who can't even *view* a private doc must not be able to tell
        # it exists via the write path — same not-found the read path gives
        # (existence-leak guard, finding L1). Not a 403 (which would confirm it).
        with pytest.raises(service.DocumentNotFound):
            service.put_document("priv", "secret", body="hacked", actor=other)

    def test_viewable_non_owner_write_raises_not_authorized(self, owner, other):
        # A public doc IS viewable by a non-owner, so a write denial is a real
        # 403 (NotAuthorized) — existence isn't a secret, only edit rights are.
        rb = make_runbook(name="Pub", slug="pubw", owner=owner, is_public=True)
        make_document(title="Open", slug="open", runbook=rb, key="open")
        with pytest.raises(service.NotAuthorized):
            service.put_document("pubw", "open", body="hacked", actor=other)

    def test_owner_write_succeeds(self, owner, private_rb):
        result = service.put_document("priv", "secret", body="update", on_exists="overwrite", actor=owner)
        assert result.version >= 1

    def test_staff_write_succeeds(self, staff, private_rb):
        assert service.put_document("priv", "secret", body="x", on_exists="overwrite", actor=staff)

    def test_internal_caller_no_actor_bypasses(self, private_rb):
        # actor=None is a trusted/internal caller (seed/import) — not blocked.
        assert service.put_document("priv", "secret", body="seeded", on_exists="overwrite", actor=None)

    def test_get_document_hidden_from_non_viewer_is_404(self, other, private_rb):
        with pytest.raises(service.DocumentNotFound):
            service.get_document("priv", "secret", viewer=other)
        # ...but visible to the owner
        assert service.get_document("priv", "secret", viewer=None)

    def test_list_documents_scoped_by_viewer(self, owner, other, private_rb):
        assert any(d.key == "secret" for d in service.list_documents(viewer=owner))
        assert not any(d.key == "secret" for d in service.list_documents(viewer=other))
