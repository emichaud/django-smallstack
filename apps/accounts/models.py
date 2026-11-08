"""
Custom User model for authentication.
"""

from datetime import timedelta
from typing import cast

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom manager for User model."""

    def create_user(
        self, username: str, email: str | None = None, password: str | None = None, **extra_fields
    ) -> "User":
        """Create and save a regular user."""
        if not username:
            raise ValueError("The username must be set")

        email = self.normalize_email(email) if email else None
        user = cast("User", self.model(username=username, email=email, **extra_fields))
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, username: str, email: str | None = None, password: str | None = None, **extra_fields
    ) -> "User":
        """Create and save a superuser."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model that uses username as the primary identifier.
    Extends AbstractBaseUser to provide full control over authentication fields.
    """

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.username

    def get_full_name(self) -> str:
        """Return the first_name plus the last_name, with a space in between."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.username

    def get_short_name(self) -> str:
        """Return the short name for the user."""
        return self.first_name or self.username


class LoginCode(models.Model):
    """A one-time numeric code for passwordless ("email me a code") login.

    The raw code is never persisted — only a salted hash. Codes expire, are
    single-use, and are attempt-limited to resist brute force.
    """

    MAX_ATTEMPTS = 5

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="login_codes"
    )
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["user", "consumed", "expires_at"])]

    def __str__(self) -> str:
        return f"LoginCode(user={self.user_id}, consumed={self.consumed})"

    @classmethod
    def issue(cls, user, *, length: int = 6, ttl_seconds: int | None = None):
        """Create and store a fresh code for ``user``; return (instance, raw_code)."""
        from django.conf import settings

        from .emails import generate_numeric_code

        ttl = cast("int", ttl_seconds or getattr(settings, "SMALLSTACK_LOGIN_CODE_TTL", 600))
        code = generate_numeric_code(length)
        obj = cls.objects.create(
            user=user,
            code_hash=make_password(code),
            expires_at=timezone.now() + timedelta(seconds=ttl),
        )
        return obj, code

    @property
    def is_live(self) -> bool:
        return (
            not self.consumed
            and self.attempts < self.MAX_ATTEMPTS
            and self.expires_at > timezone.now()
        )

    def rekey(self, *, length: int = 6) -> str | None:
        """Give this live code a fresh secret and return it, or None if it's spent.

        The sender calls this right before mailing, so the raw code exists only
        in the process that sends it — never in a task's stored arguments. The
        row itself is created in the request (``issue``) so the resend throttle
        and hourly cap still count it the moment it's asked for.
        """
        from .emails import generate_numeric_code

        code = generate_numeric_code(length)
        updated = type(self).objects.filter(
            pk=self.pk, consumed=False, expires_at__gt=timezone.now()
        ).update(code_hash=make_password(code))
        return code if updated else None

    def check_code(self, raw: str) -> bool:
        return check_password(raw, self.code_hash)
