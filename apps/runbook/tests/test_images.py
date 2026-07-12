"""Tests for document image upload, secured serving, and version fidelity.

These run against a host SmallStack project (URLs mounted under a prefix, axes
enabled), so they use ``reverse()`` for URLs and ``force_login`` to bypass the
brute-force backend.
"""

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from apps.runbook.models import DocumentImage, Runbook, Section

from ._factory import make_document

User = get_user_model()


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _png_upload(name: str = "dot.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _png_bytes(), content_type="image/png")


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Keep uploaded test files out of the project's real media directory."""
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


def _upload_url(pk):
    return reverse("runbook:document_image_upload", kwargs={"pk": pk})


def _serve_url(pk):
    return reverse("runbook:serve_image", kwargs={"pk": pk})


@pytest.mark.django_db
class TestImageUpload:
    def test_upload_returns_markdown_and_attaches_to_root(self, staff_client, document):
        resp = staff_client.post(_upload_url(document.pk), {"image": _png_upload(), "alt": "diagram"})
        assert resp.status_code == 200
        data = resp.json()
        img = DocumentImage.objects.get()
        # attached to the logical document
        assert img.document_id == document.pk
        assert data["url"] == _serve_url(img.pk)
        assert data["markdown"] == f"![diagram]({data['url']})"

    def test_rejects_non_image(self, staff_client, document):
        resp = staff_client.post(
            _upload_url(document.pk),
            {"image": SimpleUploadedFile("x.txt", b"not an image", content_type="text/plain")},
        )
        assert resp.status_code == 400
        assert DocumentImage.objects.count() == 0

    def test_pasted_blob_filename_accepted(self, staff_client, document):
        # JS gives pasted blobs a default name; ensure that path works.
        resp = staff_client.post(_upload_url(document.pk), {"image": _png_upload("pasted-image.png")})
        assert resp.status_code == 200


@pytest.mark.django_db
class TestImageServe:
    def test_staff_can_fetch_bytes(self, staff_client, document):
        staff_client.post(_upload_url(document.pk), {"image": _png_upload()})
        img = DocumentImage.objects.get()
        resp = staff_client.get(_serve_url(img.pk))
        assert resp.status_code == 200
        body = b"".join(resp.streaming_content)
        assert body[:8] == b"\x89PNG\r\n\x1a\n"

    def test_anonymous_denied_not_public(self, document, staff_user):
        staff = Client()
        staff.force_login(staff_user)
        staff.post(_upload_url(document.pk), {"image": _png_upload()})
        img = DocumentImage.objects.get()

        resp = Client().get(_serve_url(img.pk))
        assert resp.status_code != 200  # never public, unlike /media
        assert resp.status_code in (302, 403)


@pytest.mark.django_db
class TestVersionFidelity:
    def test_images_shared_across_versions(self, staff_client, document, staff_user):
        # attach an image to v1
        staff_client.post(_upload_url(document.pk), {"image": _png_upload()})
        img = DocumentImage.objects.get()

        # create v2 of the document (create_new_version advances the same logical doc)
        document.create_new_version(file=SimpleUploadedFile("v2.md", b"# v2"), created_by=staff_user)
        assert document.version == 2
        assert img.document_id == document.pk

        # uploading again lands on the same logical document's shared pool
        staff_client.post(_upload_url(document.pk), {"image": _png_upload("second.png")})
        assert DocumentImage.objects.filter(document=document).count() == 2
