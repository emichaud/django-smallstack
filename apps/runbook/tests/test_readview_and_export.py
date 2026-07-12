"""Tests for the full runbook read view and image-bundling ZIP export."""

import io
import zipfile

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.runbook.models import DocumentImage, Runbook, Section

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
def runbook(db):
    return Runbook.objects.create(name="Ops", slug="ops")


@pytest.fixture
def section(runbook):
    return Section.objects.create(name="General", slug="general", runbook=runbook)


@pytest.mark.django_db
class TestReadView:
    def test_renders_all_docs_with_anchors(self, staff_client, runbook, section, staff_user):
        make_document(title="Alpha", body=b"# Alpha\n\nAlpha body.", section=section, created_by=staff_user)
        make_document(title="Beta", body=b"# Beta\n\nBeta body.", section=section, created_by=staff_user)
        resp = staff_client.get(reverse("runbook:runbook_read", kwargs={"slug": runbook.slug}))
        assert resp.status_code == 200
        html = resp.content.decode()
        # both documents rendered inline
        assert "Alpha body." in html
        assert "Beta body." in html
        # per-document and per-section anchors for deep-linking
        assert 'id="section-general"' in html
        assert 'id="doc-' in html

    def test_only_current_versions(self, staff_client, runbook, section, staff_user):
        doc = make_document(title="Doc", body=b"# Doc\n\nv1 body.", section=section, created_by=staff_user)
        doc.create_new_version(file=SimpleUploadedFile("d2.md", b"# Doc\n\nv2 body."), created_by=staff_user)
        resp = staff_client.get(reverse("runbook:runbook_read", kwargs={"slug": runbook.slug}))
        html = resp.content.decode()
        assert "v2 body." in html
        assert "v1 body." not in html


@pytest.mark.django_db
class TestZipExportImages:
    def test_linked_image_bundled_and_rewritten(self, staff_client, runbook, section, staff_user):
        doc = make_document(title="Guide", slug="guide", body=b"# Guide", section=section, created_by=staff_user)
        img = DocumentImage.objects.create(
            document=doc, image=ContentFile(b"\x89PNG-bytes", "diagram.png"),
        )
        serve_url = reverse("runbook:serve_image", kwargs={"pk": img.pk})
        # reference the image in the head version's markdown
        content = f"# Guide\n\n![d]({serve_url})\n"
        version = doc.current_version
        version.file.open("wb")
        version.file.write(content.encode())
        version.file.close()

        resp = staff_client.get(reverse("runbook:download_zip") + f"?runbook={runbook.slug}")
        assert resp.status_code == 200
        data = b"".join(resp.streaming_content)
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()

        # image bundled beside the markdown, under the section folder
        img_path = f"general/images/{img.pk}.png"
        assert img_path in names, names
        # markdown rewritten to the relative path (no absolute serve URL left).
        md = zf.read("general/guide.md").decode()
        assert serve_url not in md
        assert f"images/{img.pk}.png" in md

    def test_unreferenced_image_not_bundled(self, staff_client, runbook, section, staff_user):
        doc = make_document(title="Plain", body=b"# Plain\n\nNo images here.", section=section, created_by=staff_user)
        # image in the pool but NOT referenced in the markdown
        DocumentImage.objects.create(document=doc, image=ContentFile(b"x", "unused.png"))

        resp = staff_client.get(reverse("runbook:download_zip") + f"?runbook={runbook.slug}")
        data = b"".join(resp.streaming_content)
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        assert not any("/images/" in n for n in names)
