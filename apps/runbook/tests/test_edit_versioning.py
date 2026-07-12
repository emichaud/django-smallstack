"""Tests for the 'Save as new version' toggle on in-place content editing."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.runbook.models import DocumentImage, DocumentVersion, Runbook, Section

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
    rb = Runbook.objects.create(name="RB", slug="rb")
    sec = Section.objects.create(name="S", runbook=rb)
    return make_document(title="Doc", section=sec, created_by=staff_user)


def _edit_url(pk):
    return reverse("runbook:document_edit_content", kwargs={"pk": pk})


@pytest.mark.django_db
class TestEditContentVersioning:
    def test_default_save_is_in_place(self, staff_client, document):
        resp = staff_client.post(_edit_url(document.pk), {"content": "# Doc edited in place"})
        assert resp.status_code == 302
        # head version overwritten in place — no new version
        document.refresh_from_db()
        assert document.version == 1
        assert document.versions.count() == 1
        assert "edited in place" in document.content_text

    def test_save_as_version_creates_version_when_changed(self, staff_client, document):
        resp = staff_client.post(
            _edit_url(document.pk),
            {"content": "# Doc v2 content", "save_as_version": "1"},
        )
        assert resp.status_code == 302
        document.refresh_from_db()
        # same logical document, advanced to v2
        assert document.version == 2
        assert document.versions.count() == 2
        head = document.current_version
        assert head.version == 2
        assert "v2 content" in head.content_text
        assert resp.url == document.get_absolute_url()

    def test_save_as_version_noop_when_unchanged(self, staff_client, document):
        resp = staff_client.post(
            _edit_url(document.pk),
            {"content": "# Doc", "save_as_version": "1"},
        )
        assert resp.status_code == 302
        document.refresh_from_db()
        assert document.version == 1
        assert document.versions.count() == 1  # no churn

    def test_versioned_edit_keeps_images_on_document(self, staff_client, document):
        DocumentImage.objects.create(document=document, image=SimpleUploadedFile("i.png", b"x"))
        staff_client.post(
            _edit_url(document.pk),
            {"content": "# Doc v2", "save_as_version": "1"},
        )
        document.refresh_from_db()
        assert document.version == 2
        assert DocumentVersion.objects.filter(document=document).count() == 2
        # image stays on the logical document, shared across versions
        assert document.images.count() == 1
