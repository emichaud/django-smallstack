"""Tests for the transport-agnostic document service + domain signals."""

import pytest

from apps.runbook import service, signals
from apps.runbook.models import Document, Runbook, Section


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def rb(db):
    return Runbook.objects.create(name="Ops", slug="ops")


@pytest.mark.django_db
class TestPutDocument:
    def test_create_then_new_version(self, rb):
        r1 = service.put_document("ops", "digest", body="# One", title="Digest", source="bot")
        assert (r1.version, r1.key, r1.runbook, r1.source) == (1, "digest", "ops", "bot")
        r2 = service.put_document("ops", "digest", body="# Two", on_exists="new_version")
        assert r2.version == 2
        assert Document.objects.get(key="digest").versions.count() == 2

    def test_overwrite_keeps_version(self, rb):
        service.put_document("ops", "d", body="a", title="D")
        r = service.put_document("ops", "d", body="b", on_exists="overwrite")
        assert r.version == 1
        assert service.get_document("ops", "d", with_body=True).content_markdown.strip() == "b"

    def test_append_accumulates_in_place(self, rb):
        service.put_document("ops", "log", body="line1", title="Log")
        r = service.append_to_document("ops", "log", body="line2")
        assert r.version == 1
        body = service.get_document("ops", "log", with_body=True).content_markdown
        assert "line1" in body and "line2" in body

    def test_append_version_grows_body_and_bumps_version(self, rb):
        # First call creates the doc (v1); each subsequent append_version grows
        # the body AND snapshots a new version — the running-log primitive.
        r1 = service.append_version("ops", "status", body="snap1", title="Status")
        assert r1.version == 1
        r2 = service.append_version("ops", "status", body="snap2")
        assert r2.version == 2  # version bumped (unlike append)
        doc = Document.objects.get(key="status")
        assert doc.versions.count() == 2
        body = service.get_document("ops", "status", with_body=True).content_markdown
        assert "snap1" in body and "snap2" in body  # both entries retained (unlike new_version)

    def test_append_version_via_put_document_on_exists(self, rb):
        service.put_document("ops", "log2", body="a", title="Log2")
        r = service.put_document("ops", "log2", body="b", on_exists="append_version")
        assert r.version == 2
        body = service.get_document("ops", "log2", with_body=True).content_markdown
        assert "a" in body and "b" in body

    def test_fail_on_exists(self, rb):
        service.put_document("ops", "d", body="a", title="D")
        with pytest.raises(service.DocumentAlreadyExists):
            service.put_document("ops", "d", body="b", on_exists="fail")

    def test_expected_version_conflict_then_success(self, rb):
        service.put_document("ops", "d", body="a", title="D")  # v1
        with pytest.raises(service.VersionConflict):
            service.put_document("ops", "d", body="b", expected_version=5)
        r = service.put_document("ops", "d", body="b", expected_version=1)
        assert r.version == 2

    def test_unknown_runbook(self, db):
        with pytest.raises(service.RunbookNotFound):
            service.put_document("nope", "d", body="a", title="D")

    def test_title_and_section_update(self, rb):
        sec = Section.objects.create(name="Gen", slug="gen", runbook=rb)
        service.put_document("ops", "d", body="a", title="D")
        r = service.put_document("ops", "d", body="b", title="D2", section="gen", on_exists="overwrite")
        assert r.title == "D2"
        assert Document.objects.get(key="d").section == sec


@pytest.mark.django_db
class TestGetListArchive:
    def test_get_by_id_and_missing(self, rb):
        r = service.put_document("ops", "d", body="a", title="D")
        assert service.get_document(id=r.id).key == "d"
        with pytest.raises(service.DocumentNotFound):
            service.get_document("ops", "missing")

    def test_list_filters(self, rb):
        service.put_document("ops", "a", body="x", title="Apple", source="botA")
        service.put_document("ops", "b", body="y", title="Banana", source="botB")
        assert len(service.list_documents(runbook="ops")) == 2
        assert len(service.list_documents(runbook="ops", source="botA")) == 1
        assert len(service.list_documents(query="Apple")) == 1

    def test_archive_then_delete(self, rb):
        service.put_document("ops", "d", body="a", title="D")
        service.archive_document(runbook="ops", key="d")
        assert len(service.list_documents(runbook="ops")) == 0
        assert len(service.list_documents(runbook="ops", include_archived=True)) == 1
        # default delete = archive (recoverable)
        service.delete_document(runbook="ops", key="d")
        assert Document.objects.filter(key="d").exists()
        # force delete removes it
        service.delete_document(runbook="ops", key="d", force=True)
        assert not Document.objects.filter(key="d").exists()


@pytest.mark.django_db
class TestAttachImage:
    def test_attach_returns_markdown(self, rb):
        doc = Document.objects.get(pk=service.put_document("ops", "d", body="a", title="D").id)
        ref = service.attach_image(document=doc, data=b"\x89PNG", alt="fig")
        assert ref.markdown == f"![fig]({ref.url})"
        assert doc.images.count() == 1


@pytest.mark.django_db
class TestSignals:
    def test_document_written_fires_on_commit(self, rb, django_capture_on_commit_callbacks):
        received = []

        def rx(**kw):
            received.append((kw["change_type"], kw["document"].key, kw["version"].version))

        signals.document_written.connect(rx, weak=False)
        try:
            with django_capture_on_commit_callbacks(execute=True):
                service.put_document("ops", "d", body="a", title="D")
                service.put_document("ops", "d", body="b", on_exists="new_version")
        finally:
            signals.document_written.disconnect(rx)

        assert ("created", "d", 1) in received
        assert ("new_version", "d", 2) in received

    def test_archived_signal_fires(self, rb, django_capture_on_commit_callbacks):
        got = []

        def rx(**kw):
            got.append(kw["document"].key)

        signals.document_archived.connect(rx, weak=False)
        service.put_document("ops", "d", body="a", title="D")
        try:
            with django_capture_on_commit_callbacks(execute=True):
                service.archive_document(runbook="ops", key="d")
        finally:
            signals.document_archived.disconnect(rx)

        assert got == ["d"]
