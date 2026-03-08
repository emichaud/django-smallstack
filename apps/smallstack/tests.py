"""Tests for the SmallStack backup system."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import BackupRecord

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a regular test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def staff_user(db):
    """Create a staff test user."""
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def success_record(db):
    """Create a successful backup record."""
    return BackupRecord.objects.create(
        filename="db-20260308-120000.sqlite3",
        file_size=100000,
        duration_ms=15,
        status="success",
        triggered_by="manual",
    )


@pytest.fixture
def failed_record(db):
    """Create a failed backup record."""
    return BackupRecord.objects.create(
        filename="",
        file_size=0,
        duration_ms=5,
        status="failed",
        error_message="disk full",
        triggered_by="command",
    )


@pytest.fixture
def pruned_record(db):
    """Create a pruned backup record (success record with pruned_at set)."""
    return BackupRecord.objects.create(
        filename="db-20260301-080000.sqlite3",
        file_size=95000,
        duration_ms=12,
        status="success",
        triggered_by="cron",
        pruned_at=timezone.now(),
    )


# ── Model Tests ──────────────────────────────────────────────


class TestBackupRecordModel:
    """Tests for the BackupRecord model."""

    def test_str_success(self, success_record):
        assert str(success_record) == "db-20260308-120000.sqlite3 (success)"

    def test_str_failed(self, failed_record):
        assert str(failed_record) == "failed (failed)"

    def test_ordering(self, success_record, failed_record):
        """Most recent records should come first."""
        records = list(BackupRecord.objects.all())
        assert records[0] == failed_record  # created second = more recent
        assert records[1] == success_record

    def test_get_absolute_url(self, success_record):
        url = success_record.get_absolute_url()
        assert url == f"/backups/{success_record.pk}/"

    def test_is_pruned_false(self, success_record):
        assert success_record.is_pruned is False

    def test_is_pruned_true(self, pruned_record):
        assert pruned_record.is_pruned is True

    def test_file_exists_no_filename(self, failed_record):
        assert failed_record.file_exists is False

    def test_file_exists_pruned_short_circuits(self, pruned_record):
        """Pruned records should return False without checking disk."""
        assert pruned_record.file_exists is False

    def test_file_exists_missing_file(self, success_record):
        """File doesn't exist on disk, so file_exists should be False."""
        assert success_record.file_exists is False


# ── Prune Logic Tests ────────────────────────────────────────


class TestPruneBackups:
    """Tests for the _prune_backups helper."""

    @override_settings(BACKUP_RETENTION=None)
    def test_prune_returns_empty_when_no_retention(self, db):
        from .views import _prune_backups

        result = _prune_backups(keep=None)
        assert result == []

    @override_settings(BACKUP_RETENTION=2)
    def test_prune_marks_records_with_pruned_at(self, db, tmp_path):
        """Pruning should set pruned_at on the original success record."""
        from .views import _prune_backups

        # Create 3 backup files
        for i in range(3):
            fname = f"db-20260301-00000{i}.sqlite3"
            (tmp_path / fname).write_bytes(b"x" * 100)
            BackupRecord.objects.create(
                filename=fname,
                file_size=100,
                duration_ms=5,
                status="success",
                triggered_by="manual",
            )

        with override_settings(BACKUP_DIR=str(tmp_path), BACKUP_RETENTION=2):
            pruned = _prune_backups()

        assert len(pruned) == 1
        # The pruned file's record should have pruned_at set
        pruned_rec = BackupRecord.objects.get(filename=pruned[0])
        assert pruned_rec.pruned_at is not None
        assert pruned_rec.status == "success"

    @override_settings(BACKUP_RETENTION=5)
    def test_prune_no_files_to_remove(self, db, tmp_path):
        """If fewer files than retention, nothing should be pruned."""
        from .views import _prune_backups

        (tmp_path / "db-20260301-000000.sqlite3").write_bytes(b"x" * 100)

        with override_settings(BACKUP_DIR=str(tmp_path), BACKUP_RETENTION=5):
            pruned = _prune_backups()

        assert pruned == []


# ── View Permission Tests ────────────────────────────────────


class TestBackupViewPermissions:
    """Tests for backup view access control."""

    def test_backup_page_requires_login(self, client, db):
        response = client.get(reverse("smallstack:backups"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_backup_page_requires_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("smallstack:backups"))
        assert response.status_code == 403

    def test_backup_page_accessible_by_staff(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backups"))
        assert response.status_code == 200

    def test_backup_detail_requires_login(self, client, success_record):
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        assert response.status_code == 302

    def test_backup_detail_requires_staff(self, client, user, success_record):
        client.force_login(user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        assert response.status_code == 403

    def test_backup_detail_accessible_by_staff(self, client, staff_user, success_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        assert response.status_code == 200

    def test_backup_detail_404_for_missing_record(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": 99999}))
        assert response.status_code == 404

    def test_stat_detail_requires_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "success"}))
        assert response.status_code == 403

    def test_stat_detail_invalid_stat_404(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "bogus"}))
        assert response.status_code == 404

    def test_file_download_missing_file_404(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_file_download", kwargs={"filename": "nonexistent.sqlite3"}))
        assert response.status_code == 404


# ── View Context Tests ───────────────────────────────────────


class TestBackupPageContext:
    """Tests for BackupPageView context data."""

    def test_context_has_stats(self, client, staff_user, success_record, failed_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backups"))
        ctx = response.context

        assert ctx["success_count"] == 1  # only non-pruned success
        assert ctx["failed_count"] == 1
        assert ctx["pruned_count"] == 1
        assert ctx["total_backups"] == 3

    def test_context_total_size_excludes_pruned(self, client, staff_user, success_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backups"))
        ctx = response.context

        # Only the non-pruned success record's size
        assert ctx["total_backup_size"] == success_record.file_size


class TestBackupDetailContext:
    """Tests for BackupDetailView context data."""

    def test_success_record_has_created_event(self, client, staff_user, success_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        events = response.context["events"]

        assert len(events) >= 1
        assert events[0]["label"] == "Backup created"
        assert events[0]["status"] == "success"

    def test_failed_record_has_error_event(self, client, staff_user, failed_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": failed_record.pk}))
        events = response.context["events"]

        assert len(events) == 2
        assert events[1]["label"] == "Backup failed"
        assert events[1]["detail"] == "disk full"

    def test_pruned_record_has_pruned_event(self, client, staff_user, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": pruned_record.pk}))
        events = response.context["events"]

        assert any(e["label"] == "File pruned" for e in events)

    def test_missing_file_has_warning_event(self, client, staff_user, success_record):
        """A success record whose file is gone should show a warning."""
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        events = response.context["events"]

        assert any(e["label"] == "File missing" for e in events)


class TestBackupStatDetailView:
    """Tests for stat detail filtering."""

    def test_success_filter_excludes_pruned(self, client, staff_user, success_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "success"}))
        records = response.context["records"]

        filenames = [r.filename for r in records]
        assert success_record.filename in filenames
        assert pruned_record.filename not in filenames

    def test_pruned_filter_includes_pruned(self, client, staff_user, success_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "pruned"}))
        records = response.context["records"]

        filenames = [r.filename for r in records]
        assert pruned_record.filename in filenames
        assert success_record.filename not in filenames

    def test_failed_filter(self, client, staff_user, failed_record, success_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "failed"}))
        records = response.context["records"]

        assert len(records) == 1
        assert records[0].status == "failed"
