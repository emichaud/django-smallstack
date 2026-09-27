"""
Test settings for smallstack project.

Inherits from development but disables debug toolbar to avoid URL namespace issues.
"""

import os
import warnings

from .base import *  # noqa: F401, F403

# Suppress WhiteNoise "No directory at" warning when staticfiles/ doesn't exist
warnings.filterwarnings(
    "ignore",
    message="No directory at.*staticfiles",
    module="whitenoise.base",
)

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

# Database. Defaults to in-memory SQLite for fast tests. Set TEST_DB=postgres
# to exercise the Postgres path (FTS, varchar enforcement, transaction
# poisoning, etc.) — e.g. `TEST_DB=postgres make test`. Requires a running
# Postgres and the `postgres` extra (`uv sync --extra postgres`). Nothing runs
# it automatically — this repo ships no CI (deliberate); downstreams that add
# CI should run at MINIMUM a from-scratch `migrate` against an empty Postgres
# (~1 min) — it catches the whole hidden-by-SQLite failure class the full
# 25-min Postgres suite exists for.
if os.environ.get("TEST_DB") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("TEST_DB_NAME", "smallstack_test"),
            "USER": os.environ.get("TEST_DB_USER", "postgres"),
            "PASSWORD": os.environ.get("TEST_DB_PASSWORD", "postgres"),
            "HOST": os.environ.get("TEST_DB_HOST", "localhost"),
            "PORT": os.environ.get("TEST_DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

# Password hashers - use fast hasher for tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Email backend for testing — locmem captures sends in mail.outbox. Django 6.1
# forbids EMAIL_BACKEND alongside MAILERS (base sets MAILERS), so override the
# default mailer here rather than the deprecated setting.
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend", "OPTIONS": {}}}

# Disable logging during tests
LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {},
    "loggers": {},
}

# Use simple static files storage for tests (no manifest required)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Disable axes rate limiting during tests (avoids false lockouts)
AXES_ENABLED = False

# Background Tasks - execute immediately during tests (no worker needed).
# QUEUES must match production config so tasks with queue_name="email" don't
# raise InvalidTask during tests.
TASKS = {
    "default": {
        "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
        "QUEUES": ["default", "email"],
    }
}
