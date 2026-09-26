"""Models for the SmallStack core app."""

import hashlib
import secrets
from pathlib import Path
from typing import Any

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

    def __str__(self) -> str:
        return f"{self.filename or 'failed'} ({self.status})"

    def get_absolute_url(self) -> str:
        return reverse("smallstack:backup_detail", kwargs={"pk": self.pk})

    @property
    def is_pruned(self) -> bool:
        return self.pruned_at is not None

    @property
    def file_exists(self) -> bool:
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

    TOKEN_TYPE_CHOICES = [
        ("login", "Login"),
        ("manual", "Manual"),
        # OAuth/PKCE-issued tokens (typically MCP clients via dynamic
        # client registration + authorize/exchange). Tagged distinctly
        # so audit trails can tell client-issued tokens apart from human-
        # minted ones — round-2 audit §4.7.
        ("oauth", "OAuth"),
    ]
    ACCESS_LEVEL_CHOICES = [
        ("auth", "Auth"),
        ("staff", "Staff"),
        ("readonly", "Readonly"),
    ]

    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=8, db_index=True)
    hashed_key = models.CharField(max_length=64)
    description = models.TextField(blank=True, default="")
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPE_CHOICES, default="manual")
    access_level = models.CharField(max_length=10, choices=ACCESS_LEVEL_CHOICES, default="staff", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    request_count = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…) — {self.user}"

    def revoke(self) -> None:
        """Soft-delete: deactivate and record revocation time."""
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=["is_active", "revoked_at"])

    def is_valid(self) -> bool:
        """Check if token is active and not expired."""
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True

    # Machine-readable reasons a token cannot authenticate. Callers map these
    # onto their own error envelopes; the strings are the contract.
    REJECT_REVOKED = "revoked"
    REJECT_EXPIRED = "expired"
    REJECT_USER_INACTIVE = "user_inactive"

    def rejection_reason(self) -> str | None:
        """Why this token cannot authenticate right now; ``None`` when usable.

        ``is_valid()`` only covers the *token*. Deactivating the account
        (``is_active=False``) is the standard offboarding action and must revoke
        every credential the account holds — otherwise an already-minted bearer
        token keeps full authority (including approval authority) after the
        human has been offboarded. Interactive login already refuses an inactive
        user (``ModelBackend.user_can_authenticate``); the token path must
        agree, so this is the single place that decides.
        """
        if self.revoked_at is not None or not self.is_active:
            return self.REJECT_REVOKED
        if self.expires_at and timezone.now() > self.expires_at:
            return self.REJECT_EXPIRED
        if not getattr(self.user, "is_active", False):
            return self.REJECT_USER_INACTIVE
        return None

    @classmethod
    def _generate_raw_key(cls) -> tuple[str, str, str]:
        """Generate a raw API key and return (raw_key, prefix, hashed_key).

        The prefix never starts with ``-``. ``token_urlsafe`` uses the base64url
        alphabet, which includes ``-``, so roughly 1.4% of tokens got a prefix
        that argparse reads as an option flag — making ``sc token revoke
        -AbC1234`` (and every other prefix-taking command) fail with a usage
        error for those tokens, and making the CLI's own test suite flaky at the
        same rate. Re-rolling is free and costs no entropy: the key is still 40
        random bytes.
        """
        while True:
            raw_key = secrets.token_urlsafe(cls.TOKEN_LENGTH)
            prefix = raw_key[: cls.PREFIX_LENGTH]
            if not prefix.startswith("-"):
                break
        hashed = hashlib.sha256(raw_key.encode()).hexdigest()
        return raw_key, prefix, hashed

    @classmethod
    def create_token(
        cls,
        user,
        name="API Token",
        description="",
        expires_at=None,
        token_type="manual",
        access_level="staff",
    ) -> "tuple[APIToken, str]":
        """Create a new token. Returns (token_instance, raw_key)."""
        raw_key, prefix, hashed = cls._generate_raw_key()
        token = cls.objects.create(
            user=user,
            name=name,
            prefix=prefix,
            hashed_key=hashed,
            description=description,
            expires_at=expires_at,
            token_type=token_type,
            access_level=access_level,
        )
        return token, raw_key

    @classmethod
    def authenticate(cls, raw_key: str) -> "tuple[Any, APIToken | None]":
        """Validate a raw key. Returns one of:

        * ``(user, token)`` — success
        * ``(None, found_token)`` — found, but expired, revoked, or belonging
          to a deactivated account. Callers can distinguish "credential was
          real but is no longer valid" from "credential is wrong" and surface a
          helpful error message instead of a generic "Invalid token."
          Ask ``found_token.rejection_reason()`` for which.
        * ``(None, None)`` — not found / wrong prefix / wrong hash.
        """
        if not raw_key or len(raw_key) < cls.PREFIX_LENGTH:
            return None, None
        prefix = raw_key[: cls.PREFIX_LENGTH]
        hashed = hashlib.sha256(raw_key.encode()).hexdigest()
        try:
            # No is_active=True filter — we want to distinguish "wrong key"
            # from "right key but revoked/expired" so the caller can produce
            # an actionable error message.
            token = cls.objects.select_related("user").get(prefix=prefix, hashed_key=hashed)
        except cls.DoesNotExist:
            return None, None
        if token.rejection_reason() is not None:
            # Found the token, but it's revoked/expired, or the account it
            # belongs to has been deactivated. Return without a user so the
            # caller can introspect the reason — and so NO surface (REST, MCP,
            # feeds, OAuth) can act as a deactivated account.
            return None, token
        token.last_used_at = timezone.now()
        token.request_count = models.F("request_count") + 1
        token.save(update_fields=["last_used_at", "request_count"])
        return token.user, token
