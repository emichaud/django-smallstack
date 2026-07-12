"""Tests for retention: policy resolution, pruning, TTL expiry, sweep, hook."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.runbook import retention, service, signals
from apps.runbook.models import Document, DocumentVersion, Runbook
from apps.runbook.retention import RetentionPolicy
from apps.runbook.tasks import prune_versions_task


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def rb(db):
    return Runbook.objects.create(name="Ops", slug="ops")


def _add_versions(key: str, count: int) -> Document:
    for i in range(2, count + 1):
        service.put_document("ops", key, body=f"v{i}", on_exists="new_version")
    return Document.objects.get(key=key)


@pytest.mark.django_db
class TestPolicyResolution:
    def test_human_defaults_unlimited(self, rb):
        r = service.put_document("ops", "h", body="x", title="H", is_generated=False)
        doc = Document.objects.get(pk=r.id)
        assert retention.effective_policy(doc) == RetentionPolicy(None, None, None, "archive")

    def test_generated_default_max_versions(self, rb):
        r = service.put_document("ops", "g", body="x", title="G", is_generated=True)
        assert retention.effective_policy(Document.objects.get(pk=r.id)).max_versions == 100

    def test_doc_override_wins(self, rb):
        r = service.put_document("ops", "g", body="x", title="G", is_generated=True)
        doc = Document.objects.get(pk=r.id)
        doc.max_versions = 5
        doc.save()
        assert retention.effective_policy(Document.objects.get(pk=doc.pk)).max_versions == 5

    def test_runbook_default_is_middle_tier(self, rb):
        rb.default_max_versions = 10
        rb.default_ttl_days = 7
        rb.save()
        r = service.put_document("ops", "g", body="x", title="G", is_generated=True)
        policy = retention.effective_policy(Document.objects.get(pk=r.id))
        assert policy.max_versions == 10  # runbook overrides the global 100
        assert policy.ttl_days == 7        # runbook applies where global is None


@pytest.mark.django_db
class TestPruneVersions:
    def test_keeps_newest_and_head(self, rb):
        service.put_document("ops", "d", body="v1", title="D", is_generated=True)
        doc = Document.objects.get(key="d")
        doc.max_versions = 3
        doc.save()
        _add_versions("d", 7)  # v1..v7

        pruned = retention.prune_versions(Document.objects.get(key="d"))
        doc = Document.objects.get(key="d")
        assert pruned == 4
        assert sorted(doc.versions.values_list("version", flat=True)) == [5, 6, 7]
        assert doc.current_version.version == 7  # head always preserved

    def test_unlimited_prunes_nothing(self, rb):
        service.put_document("ops", "d", body="x", title="D", is_generated=False)  # unlimited
        _add_versions("d", 4)
        assert retention.prune_versions(Document.objects.get(key="d")) == 0

    def test_age_based_pruning(self, rb):
        service.put_document("ops", "d", body="v1", title="D", is_generated=False)
        _add_versions("d", 4)
        doc = Document.objects.get(key="d")
        doc.max_version_age_days = 1
        doc.save()
        # backdate the two oldest versions past the window
        for version in doc.versions.order_by("version")[:2]:
            DocumentVersion.objects.filter(pk=version.pk).update(created_at=timezone.now() - timedelta(days=5))
        assert retention.prune_versions(Document.objects.get(key="d")) == 2

    def test_prune_task(self, rb):
        service.put_document("ops", "d", body="v1", title="D", is_generated=True)
        Document.objects.filter(key="d").update(max_versions=2)
        _add_versions("d", 5)
        # ImmediateBackend runs the task synchronously on enqueue.
        prune_versions_task.enqueue(Document.objects.get(key="d").pk)
        assert Document.objects.get(key="d").versions.count() == 2


@pytest.mark.django_db
class TestExpiry:
    def _idle_doc(self, key, *, ttl_days, days_idle, on_expire="archive") -> Document:
        service.put_document("ops", key, body="x", title=key)
        Document.objects.filter(key=key).update(ttl_days=ttl_days, on_expire=on_expire)
        Document.objects.filter(key=key).update(updated_at=timezone.now() - timedelta(days=days_idle))
        return Document.objects.get(key=key)

    def test_is_expired(self, rb):
        assert retention.is_expired(self._idle_doc("e", ttl_days=1, days_idle=3))
        assert not retention.is_expired(self._idle_doc("f", ttl_days=30, days_idle=1))

    def test_no_ttl_never_expires(self, rb):
        service.put_document("ops", "d", body="x", title="D", is_generated=False)
        Document.objects.filter(key="d").update(updated_at=timezone.now() - timedelta(days=999))
        assert not retention.is_expired(Document.objects.get(key="d"))

    def test_expire_archives_and_signals(self, rb, django_capture_on_commit_callbacks):
        doc = self._idle_doc("e", ttl_days=1, days_idle=3, on_expire="archive")
        got = []

        def rx(**kw):
            got.append(kw["document"].key)

        signals.document_expired.connect(rx, weak=False)
        try:
            with django_capture_on_commit_callbacks(execute=True):
                assert retention.expire_document(doc) == "archive"
        finally:
            signals.document_expired.disconnect(rx)

        assert Document.objects.get(key="e").is_archived
        assert got == ["e"]

    def test_expire_deletes(self, rb):
        doc = self._idle_doc("e", ttl_days=1, days_idle=3, on_expire="delete")
        assert retention.expire_document(doc) == "delete"
        assert not Document.objects.filter(key="e").exists()


@pytest.mark.django_db
class TestSweep:
    def test_sweep_prunes_and_expires(self, rb):
        # over-cap doc
        service.put_document("ops", "big", body="v1", title="Big", is_generated=True)
        Document.objects.filter(key="big").update(max_versions=2)
        _add_versions("big", 5)
        # idle doc with TTL
        service.put_document("ops", "old", body="x", title="Old")
        Document.objects.filter(key="old").update(ttl_days=1)
        Document.objects.filter(key="old").update(updated_at=timezone.now() - timedelta(days=3))

        result = retention.run_sweep()
        assert result["pruned_versions"] == 3
        assert result["expired_documents"] == 1
        assert Document.objects.get(key="big").versions.count() == 2
        assert Document.objects.get(key="old").is_archived


@pytest.mark.django_db
class TestPruneOnWriteHook:
    def test_new_version_write_triggers_prune(self, rb, django_capture_on_commit_callbacks):
        # ImmediateBackend runs the enqueued prune synchronously; the hook fires
        # off document_written, so it needs the on_commit callbacks to execute.
        service.put_document("ops", "d", body="v1", title="D", is_generated=True)
        Document.objects.filter(key="d").update(max_versions=3)
        with django_capture_on_commit_callbacks(execute=True):
            for i in range(2, 8):
                service.put_document("ops", "d", body=f"v{i}", on_exists="new_version")

        doc = Document.objects.get(key="d")
        assert doc.versions.count() == 3
        assert doc.current_version.version == 7
