"""Models for the SmallStack core app."""

from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse


class BackupRecord(models.Model):
    """Tracks database backup history — successes, failures, and pruned files."""

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failed", "Failed"),
        ("pruned", "Pruned"),
    ]

    TRIGGER_CHOICES = [
        ("manual", "Manual"),
        ("download", "Download"),
        ("cron", "Cron"),
        ("command", "Command"),
        ("system", "System"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    error_message = models.TextField(blank=True)
    triggered_by = models.CharField(max_length=10, choices=TRIGGER_CHOICES, default="manual")
    pruned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename or 'failed'} ({self.status})"

    def get_absolute_url(self):
        return reverse("smallstack:backup_detail", kwargs={"pk": self.pk})

    @property
    def is_pruned(self):
        return self.pruned_at is not None

    @property
    def file_exists(self):
        """Check if the backup file still exists on disk."""
        if self.pruned_at:
            return False
        if not self.filename:
            return False
        backup_dir = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
        return (backup_dir / self.filename).exists()
