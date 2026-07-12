"""Tests for app-documentation bundles (export/import round-trip) + lock enforcement."""

import io
import json
import zipfile

import pytest
from django.contrib.auth import get_user_model
from PIL import Image

from apps.runbook import bundle, service
from apps.runbook.models import Document, Runbook, Section

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def _build_src():
    src = Runbook.objects.create(name="Src", slug="src")
    Section.objects.create(name="Guides", slug="guides", runbook=src)
    service.put_document("src", "intro", body="# Intro\n\nHello.", title="Intro", section="guides")
    return src


@pytest.mark.django_db
class TestBundleRoundTrip:
    def test_export_structure(self, db):
        _build_src()
        zf = zipfile.ZipFile(io.BytesIO(bundle.export_bundle(Runbook.objects.get(slug="src"))))
        assert "manifest.json" in zf.namelist()
        assert "guides/intro.md" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["runbook"]["slug"] == "src"
        assert manifest["documents"][0]["key"] == "intro"
        assert "Hello." in zf.read("guides/intro.md").decode()

    def test_import_creates_locked_managed(self, db):
        _build_src()
        data = bundle.export_bundle(Runbook.objects.get(slug="src"))
        result = bundle.import_bundle(data, slug_override="dst", source="app:x")
        assert result.created == 1
        doc = Document.objects.get(runbook__slug="dst", key="intro")
        assert doc.locked and doc.is_generated and doc.source == "app:x"
        assert "Hello." in service.read_head(doc)

    def test_import_unlocked(self, db):
        _build_src()
        data = bundle.export_bundle(Runbook.objects.get(slug="src"))
        bundle.import_bundle(data, slug_override="dst", locked=False)
        assert not Document.objects.get(runbook__slug="dst", key="intro").locked

    def test_reimport_unchanged_is_idempotent(self, db):
        # Re-importing a byte-identical bundle must be a no-op — no version churn.
        _build_src()
        data = bundle.export_bundle(Runbook.objects.get(slug="src"))
        bundle.import_bundle(data, slug_override="dst")
        doc = Document.objects.get(runbook__slug="dst", key="intro")
        assert doc.versions.count() == 1
        result = bundle.import_bundle(data, slug_override="dst")
        assert result.created == 0 and result.updated == 0
        doc.refresh_from_db()
        assert doc.versions.count() == 1

    def test_reimport_changed_content_bumps_version(self, db):
        _build_src()
        bundle.import_bundle(bundle.export_bundle(Runbook.objects.get(slug="src")), slug_override="dst")
        service.put_document("src", "intro", body="# Intro\n\nUpdated.", on_exists="overwrite")
        result = bundle.import_bundle(bundle.export_bundle(Runbook.objects.get(slug="src")), slug_override="dst")
        assert result.updated == 1
        doc = Document.objects.get(runbook__slug="dst", key="intro")
        assert doc.versions.count() == 2
        assert "Updated." in service.read_head(doc)

    def test_reimport_with_image_reuses_rows(self, db):
        # An unchanged re-import of a doc with an image must not recreate the image
        # rows or bump the version (the deeper idempotence guarantee).
        _build_src()
        doc = Document.objects.get(runbook__slug="src", key="intro")
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, "PNG")
        ref = service.attach_image(document=doc, data=buf.getvalue(), alt="fig")
        service.put_document("src", "intro", body="# Intro\n\n" + ref.markdown, on_exists="overwrite")
        data = bundle.export_bundle(Runbook.objects.get(slug="src"))
        bundle.import_bundle(data, slug_override="dst")
        d2 = Document.objects.get(runbook__slug="dst", key="intro")
        pks_before = set(d2.images.values_list("pk", flat=True))
        versions_before = d2.versions.count()
        result = bundle.import_bundle(data, slug_override="dst")
        assert result.updated == 0
        d2.refresh_from_db()
        assert d2.versions.count() == versions_before
        assert set(d2.images.values_list("pk", flat=True)) == pks_before

    def test_image_round_trip(self, db):
        _build_src()
        doc = Document.objects.get(runbook__slug="src", key="intro")
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, "PNG")
        ref = service.attach_image(document=doc, data=buf.getvalue(), alt="fig")
        service.put_document("src", "intro", body="# Intro\n\n" + ref.markdown, on_exists="overwrite")

        zf = zipfile.ZipFile(io.BytesIO(bundle.export_bundle(Runbook.objects.get(slug="src"))))
        assert any(n.startswith("guides/images/") for n in zf.namelist())

        bundle.import_bundle(bundle.export_bundle(Runbook.objects.get(slug="src")), slug_override="dst")
        imported = Document.objects.get(runbook__slug="dst", key="intro")
        assert imported.images.count() == 1
        body = service.read_head(imported)
        assert "/runbook/images/" in body       # rewritten to a serve URL
        assert "guides/images/" not in body      # no relative ref left

    def test_prune_archives_removed(self, db):
        src = _build_src()
        service.put_document("src", "extra", body="x", title="Extra", section="guides")
        bundle.import_bundle(bundle.export_bundle(src), slug_override="dst", source="app")

        Document.objects.filter(runbook=src, key="extra").delete()  # dropped from source
        result = bundle.import_bundle(bundle.export_bundle(src), slug_override="dst", source="app", prune=True)
        assert result.archived == 1
        assert Document.objects.get(runbook__slug="dst", key="extra").is_archived


@pytest.mark.django_db
def test_commands_round_trip(tmp_path, db, settings):
    from django.core.management import call_command

    _build_src()
    out = tmp_path / "b.zip"
    call_command("export_runbook", "src", "--out", str(out))
    assert out.exists()
    call_command("import_runbook", str(out), "--slug", "dst")
    doc = Document.objects.get(runbook__slug="dst", key="intro")
    assert doc.locked  # imported managed/locked by default


@pytest.mark.django_db
class TestLockEnforcement:
    def test_locked_blocks_staff_write(self, db):
        staff = User.objects.create_user("s", password="p", is_staff=True)
        Runbook.objects.create(name="L", slug="l")
        service.put_document("l", "d", body="v1", title="D", locked=True)
        with pytest.raises(service.DocumentLocked):
            service.put_document("l", "d", body="v2", on_exists="new_version", actor=staff)

    def test_superuser_and_bypass_allowed(self, db):
        su = User.objects.create_superuser("su", email="su@x.co", password="p")
        Runbook.objects.create(name="L", slug="l")
        service.put_document("l", "d", body="v1", title="D", locked=True)
        service.put_document("l", "d", body="v2", on_exists="new_version", actor=su)
        assert service.get_document("l", "d").version == 2
        service.put_document("l", "d", body="v3", on_exists="new_version", bypass_lock=True)
        assert service.get_document("l", "d").version == 3

    def test_api_write_to_locked_is_403(self, db):
        from django.test import Client
        from django.urls import reverse

        staff = User.objects.create_user("st", password="p", is_staff=True)  # staff, not super
        Runbook.objects.create(name="L", slug="l")
        service.put_document("l", "d", body="v1", title="D", locked=True)
        client = Client()
        client.force_login(staff)
        resp = client.put(
            reverse("runbook:api_document", kwargs={"runbook": "l", "key": "d"}),
            data=json.dumps({"body": "x"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_content_write_preserves_lock(self, db):
        # B1 regression: a content-only write (no locked field) must NOT clear the
        # lock — the bug where locked defaulted to False and clobbered True.
        su = User.objects.create_superuser("su2", email="su2@x.co", password="p")
        Runbook.objects.create(name="L", slug="l")
        service.put_document("l", "d", body="v1", title="D", locked=True)
        service.put_document("l", "d", body="v2", on_exists="new_version", actor=su)  # no locked kwarg
        assert service.get_document("l", "d").locked is True

    def test_explicit_locked_false_still_unlocks(self, db):
        su = User.objects.create_superuser("su3", email="su3@x.co", password="p")
        Runbook.objects.create(name="L", slug="l")
        service.put_document("l", "d", body="v1", title="D", locked=True)
        service.put_document("l", "d", body="v2", on_exists="new_version", locked=False, actor=su)
        assert service.get_document("l", "d").locked is False

    def test_api_superuser_write_keeps_lock(self, db):
        # The end-to-end path the reviewer reproduced: superuser PUT via REST.
        from django.test import Client
        from django.urls import reverse

        su = User.objects.create_superuser("su4", email="su4@x.co", password="p")
        Runbook.objects.create(name="L", slug="l")
        service.put_document("l", "d", body="v1", title="D", locked=True)
        client = Client()
        client.force_login(su)
        resp = client.put(
            reverse("runbook:api_document", kwargs={"runbook": "l", "key": "d"}),
            data=json.dumps({"body": "edited"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert service.get_document("l", "d").locked is True
