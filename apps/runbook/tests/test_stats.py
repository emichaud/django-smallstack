"""Tests for dashboard stat drill-down rows: detail links + images stat."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse

from apps.runbook.models import DocumentImage, Runbook, Section
from apps.runbook.views import _get_stat_table, _render_stat_table

from ._factory import make_document

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def staff(db):
    # Stat tables are now viewer-scoped; a staff user sees everything.
    return User.objects.create_user("statstaff", password="p", is_staff=True)


@pytest.fixture
def doc(db):
    rb = Runbook.objects.create(name="Ops", slug="ops")
    sec = Section.objects.create(name="Gen", slug="gen", runbook=rb)
    return make_document(title="Guide", slug="guide", body=b"# Guide", section=sec)


@pytest.mark.django_db
class TestStatRows:
    def test_runbook_row_links_and_columns(self, doc, staff):
        columns, rows, _ = _get_stat_table("runbooks", staff)
        assert [c[0] for c in columns] == ["Runbook", "Sections", "Documents"]
        url = reverse("runbook:runbook_detail", kwargs={"slug": "ops"})
        assert any(url in row[0] for row in rows)         # link lives in the first cell
        assert '<a href="/' in _render_stat_table(columns, rows)

    def test_document_row_links_and_has_runbook_column(self, doc, staff):
        columns, rows, _ = _get_stat_table("documents", staff)
        assert ("Runbook", "left") in columns             # runbook column added
        url = reverse("runbook:document_detail", kwargs={"pk": doc.pk})
        assert url in rows[0][0]
        assert "Ops" in rows[0][1]                          # runbook name cell

    def test_images_stat_empty_then_lists(self, doc, staff):
        columns, rows, empty = _get_stat_table("images", staff)
        assert rows == [] and empty == "No images attached yet."
        DocumentImage.objects.create(document=doc, image=ContentFile(b"x", "a.png"))
        DocumentImage.objects.create(document=doc, image=ContentFile(b"y", "b.png"))
        columns, rows, _ = _get_stat_table("images", staff)
        assert "Guide" in rows[0][0]
        assert rows[0][-1] == "2 images"
        assert "Ops" in rows[0][1]                          # runbook column present

    def test_cells_are_escaped(self, staff):
        rb = Runbook.objects.create(name="X", slug="x")
        sec = Section.objects.create(name="S", slug="s", runbook=rb)
        make_document(title="<script>x</script>", slug="evil", body=b"# e", section=sec)
        columns, rows, _ = _get_stat_table("documents", staff)
        html = _render_stat_table(columns, rows)
        assert "<script>" not in html and "&lt;script&gt;" in html

    def test_empty_message_renders(self):
        html = _render_stat_table([("Runbook", "left")], [], "No runbooks yet.")
        assert "No runbooks yet." in html


@pytest.mark.django_db
class TestStatEndpoint:
    def test_images_endpoint_renders(self, doc):
        client = Client()
        client.force_login(User.objects.create_user("s", password="p", is_staff=True))
        resp = client.get(reverse("runbook:stat_detail", kwargs={"stat_type": "images"}))
        assert resp.status_code == 200
