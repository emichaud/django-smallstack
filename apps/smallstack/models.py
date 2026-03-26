"""Models for the SmallStack core app."""

import hashlib
import secrets
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class BackupRecord(models.Model):
    """Tracks database backup history — successes, failures, and pruned files."""

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failed", "Failed"),
        ("pruned", "Pruned"),
    ]

    TRIGGER_CHOICES = [
        ("manual", "Manual"),
        ("command", "Command"),
        ("scheduler", "Scheduler"),
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


class APIToken(models.Model):
    """Bearer token for REST API authentication.

    Tokens are stored as SHA-256 hashes with an 8-character prefix for lookup.
    The raw key is shown once at creation and cannot be retrieved later.
    """

    TOKEN_LENGTH = 40
    PREFIX_LENGTH = 8

    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=8, db_index=True)
    hashed_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…) — {self.user}"

    @classmethod
    def create_token(cls, user, name="API Token"):
        """Create a new token. Returns (token_instance, raw_key)."""
        raw_key = secrets.token_urlsafe(cls.TOKEN_LENGTH)
        prefix = raw_key[: cls.PREFIX_LENGTH]
        hashed = hashlib.sha256(raw_key.encode()).hexdigest()
        token = cls.objects.create(user=user, name=name, prefix=prefix, hashed_key=hashed)
        return token, raw_key

    @classmethod
    def authenticate(cls, raw_key):
        """Validate a raw key. Returns the user or None."""
        if not raw_key or len(raw_key) < cls.PREFIX_LENGTH:
            return None
        prefix = raw_key[: cls.PREFIX_LENGTH]
        hashed = hashlib.sha256(raw_key.encode()).hexdigest()
        try:
            token = cls.objects.select_related("user").get(prefix=prefix, hashed_key=hashed, is_active=True)
        except cls.DoesNotExist:
            return None
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return token.user
