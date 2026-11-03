"""
Development settings for smallstack project.
"""

import secrets

from decouple import config

from .base import *  # noqa: F401, F403

DEBUG = True

# Persist the dev SECRET_KEY so every local process (runserver, screenshot_auth,
# manage.py shell) shares one key. base.py otherwise generates a *fresh* random
# key per process — so a session minted by e.g. `screenshot_auth` is rejected by
# the running server, and authenticated screenshots silently land on the login
# page. Mirrors the production entrypoint, which persists a key to the data
# volume. Only applies when SECRET_KEY isn't explicitly set (.env / environment).
if not config("SECRET_KEY", default=""):
    _dev_secret_key_file = BASE_DIR / ".secret_key"  # noqa: F405  (BASE_DIR from base import *)
    if _dev_secret_key_file.exists():
        SECRET_KEY = _dev_secret_key_file.read_text().strip()
    else:
        SECRET_KEY = secrets.token_urlsafe(50)
        _dev_secret_key_file.write_text(SECRET_KEY)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# Database
# SQLite is the default - simple, zero-config, perfect for development
# See /smallstack/help/smallstack/database-sqlite/ for why SQLite works great in production too
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        "OPTIONS": SQLITE_OPTIONS,  # noqa: F405
    }
}

# PostgreSQL for local development (optional)
# 1. Start PostgreSQL: docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16-alpine
# 2. Install driver: uv add psycopg[binary]
# 3. Uncomment below and comment out SQLite config above
# See /smallstack/help/smallstack/database-postgresql/ for full setup guide
#
# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": "smallstack",
#         "USER": "postgres",
#         "PASSWORD": "postgres",
#         "HOST": "localhost",
#         "PORT": "5432",
#     }
# }

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        # Puts request_id/trace_id on every record. Attached to handlers, not
        # loggers, so it also sees records propagated up from child loggers.
        "request_context": {
            "()": "apps.smallstack.logging.RequestContextFilter",
        },
    },
    "formatters": {
        # Same layout as before, plus a trailing `request_id=...` on lines
        # emitted while handling a request — match it against the
        # X-Request-ID in your browser's network tab.
        "verbose": {
            "()": "apps.smallstack.logging.TextFormatter",
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_context"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        # Uncomment to log all SQL queries (very verbose):
        # "django.db.backends": {
        #     "handlers": ["console"],
        #     "level": "DEBUG",
        #     "propagate": False,
        # },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # django-axes logs an INFO "AXES: BEGIN version …" banner on every
        # startup — including every manage.py / rb command, which is noise
        # (and pollutes piped CLI output). Keep WARNING+ (lockouts) visible.
        "axes": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        # MCP gets its own namespace so production tuning can be precise
        # without touching the wider apps.* tree. Do NOT register a
        # top-level "mcp" logger — it conflicts with the mcp package's
        # internal logger.
        "smallstack.mcp": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Database log capture, same as production — on in dev so the behaviour you
# debug locally is the behaviour you get deployed, and so the log viewer has
# something to show. Baseline is WARNING, so routine dev INFO chatter is NOT
# written to db.sqlite3; `manage.py log_capture start --level DEBUG` turns it
# up when you want to exercise it.
if TELEMETRY_LOG_CAPTURE_ENABLED:  # noqa: F405
    LOGGING["handlers"]["db"] = {
        "()": "apps.telemetry.handlers.DatabaseLogHandler",
        "level": TELEMETRY_LOG_LEVEL,  # noqa: F405
        "queue_size": TELEMETRY_LOG_QUEUE_SIZE,  # noqa: F405
        "filters": ["request_context"],
    }
    # Every logger, because they all set propagate=False — a handler on root
    # alone would only ever see records nothing else claimed.
    LOGGING["root"]["handlers"].append("db")
    for logger_config in LOGGING["loggers"].values():
        logger_config["handlers"].append("db")

# Auto-allow localhost CORS in development when no explicit origins are set
if not CORS_ALLOWED_ORIGINS:  # noqa: F405
    CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://localhost:\d+$", r"^http://127\.0\.0\.1:\d+$"]

# Explorer — show all admin-registered models without requiring explorer_enabled
EXPLORER_DISCOVER_ALL = True

# Email: dev prints to console. MAILERS is inherited from base (config/settings/
# smallstack.py, console default). To test real delivery locally, set
# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend (+ EMAIL_HOST etc.)
# in your .env — build_mailers() reads them into MAILERS automatically.

# Django 6.1's `manage.py check --deploy` raises mail.E001 for a dev-only email
# backend. Dev intentionally uses the console backend and is NOT a deploy target,
# so that deploy-readiness check doesn't apply here — silence just it, keeping
# `check --deploy` clean on a fresh clone. Production (SMTP) is unaffected and
# still validated. (The security.W0xx dev warnings remain; they don't fail.)
SILENCED_SYSTEM_CHECKS = ["mail.E001"]

# Background Tasks - uses DatabaseBackend from base settings by default
# The worker auto-reloads in DEBUG mode: python manage.py db_worker
# Uncomment below to run tasks immediately without a worker (for simple testing):
# TASKS = {
#     "default": {
#         "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
#     }
# }
