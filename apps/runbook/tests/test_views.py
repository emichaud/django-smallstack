"""Tests for Runbook views (dashboard, detail, search, edit, versions, stats).

Host-compatible: URLs via ``reverse()`` and auth via ``force_login``.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.runbook import signals
from apps.runbook.models import Runbook, Section

from ._factory import make_document

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(username="rb_staff", password="pass", is_staff=True)


@pytest.fixture
def staff_client(staff_user):
    client = Client()
    client.force_login(staff_user)
    return client


@pytest.fixture
def document(db, staff_user):
    rb = Runbook.objects.create(name="Test Runbook", slug="test-runbook")
    sec = Section.objects.create(name="General", runbook=rb)
    return make_document(title="Test Doc", body=b"# Test\n\nHello world.", section=sec, created_by=staff_user)


@pytest.mark.django_db
class TestDashboard:
    def test_dashboard_loads(self, staff_client):
        assert staff_client.get(reverse("runbook:dashboard")).status_code == 200

    def test_requires_staff(self, client):
        assert client.get(reverse("runbook:dashboard")).status_code == 302  # → login

    def test_cards_view_renders_runbook_cards(self, staff_client, document):
        html = staff_client.get(reverse("runbook:dashboard")).content.decode()
        assert "rb-card" in html          # card grid
        assert "All Documents" in html    # header link to the documents list
        assert "Recent Documents" not in html  # table dropped

    def test_list_view_renders_dense_list(self, staff_client, document):
        resp = staff_client.get(reverse("runbook:dashboard"), {"view": "list"})
        assert resp.status_code == 200
        assert "rb-list-item" in resp.content.decode()


@pytest.mark.django_db
class TestDocumentDetail:
    def test_renders_markdown(self, staff_client, document):
        resp = staff_client.get(reverse("runbook:document_detail", kwargs={"pk": document.pk}))
        assert resp.status_code == 200
        assert "Hello world" in resp.content.decode()


@pytest.mark.django_db
class TestSearch:
    def test_search_by_title(self, staff_client, document):
        resp = staff_client.get(reverse("runbook:search"), {"q": "Test Doc"})
        assert resp.status_code == 200
        assert "Test Doc" in resp.content.decode()

    def test_search_by_content(self, staff_client, document):
        resp = staff_client.get(reverse("runbook:search"), {"q": "Hello world"})
        assert resp.status_code == 200
        assert "Test Doc" in resp.content.decode()

    def test_search_empty_query(self, staff_client):
        assert staff_client.get(reverse("runbook:search"), {"q": ""}).status_code == 200


@pytest.mark.django_db
class TestEditContent:
    def _url(self, document):
        return reverse("runbook:document_edit_content", kwargs={"pk": document.pk})

    def test_get_loads_editor(self, staff_client, document):
        resp = staff_client.get(self._url(document))
        assert resp.status_code == 200
        assert "# Test" in resp.content.decode()

    def test_post_saves_content(self, staff_client, document):
        resp = staff_client.post(self._url(document), {"content": "# Updated\n\nNew body."})
        assert resp.status_code == 302
        document.refresh_from_db()
        assert "New body" in document.content_text

    def test_post_updates_head_file(self, staff_client, document):
        staff_client.post(self._url(document), {"content": "# Changed"})
        document.refresh_from_db()
        assert "Changed" in document.current_version.file.read().decode()


@pytest.mark.django_db
class TestNewVersion:
    def test_upload_new_version(self, staff_client, document):
        resp = staff_client.post(
            reverse("runbook:document_new_version", kwargs={"pk": document.pk}),
            {"file": SimpleUploadedFile("v2.md", b"# Version 2"), "description": "Updated"},
        )
        assert resp.status_code == 302
        document.refresh_from_db()
        assert document.version == 2
        assert document.versions.count() == 2


@pytest.mark.django_db
class TestStatDetail:
    def _url(self, stat_type):
        return reverse("runbook:stat_detail", kwargs={"stat_type": stat_type})

    def test_runbooks_stat(self, staff_client, document):
        resp = staff_client.get(self._url("runbooks"))
        assert resp.status_code == 200
        assert "Test Runbook" in resp.content.decode()

    def test_images_stat(self, staff_client, document):
        assert staff_client.get(self._url("images")).status_code == 200

    def test_unknown_stat_returns_empty(self, staff_client):
        assert staff_client.get(self._url("nonexistent")).status_code == 200


@pytest.mark.django_db
class TestWebWritesEmitEvents:
    """The browser UI shares the service write path, so web edits fire events too."""

    def test_new_version_via_web_fires_document_written(
        self, staff_client, document, django_capture_on_commit_callbacks
    ):
        received = []

        def rx(**kw):
            received.append(kw["change_type"])

        signals.document_written.connect(rx, weak=False)
        try:
            with django_capture_on_commit_callbacks(execute=True):
                staff_client.post(
                    reverse("runbook:document_new_version", kwargs={"pk": document.pk}),
                    {"file": SimpleUploadedFile("v2.md", b"# V2"), "description": "note"},
                )
        finally:
            signals.document_written.disconnect(rx)

        assert "new_version" in received
