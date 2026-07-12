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
# See /help/database-sqlite/ for why SQLite works great in production too
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
# See /help/database-postgresql/ for full setup guide
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

# Debug toolbar — installed but off by default
# Enable with DEBUG_TOOLBAR=true in .env (requires DEBUG=True)
# Stays out of the way for screenshots and normal development
if config("DEBUG_TOOLBAR", default=False, cast=bool):
    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405

INTERNAL_IPS = [
    "127.0.0.1",
    "localhost",
]

DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: (
        DEBUG
        and "debug_toolbar" in INSTALLED_APPS  # noqa: F405
        and not request.path.startswith(("/api/docs/", "/api/redoc/"))
    ),
}

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
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

# Auto-allow localhost CORS in development when no explicit origins are set
if not CORS_ALLOWED_ORIGINS:  # noqa: F405
    CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://localhost:\d+$", r"^http://127\.0\.0\.1:\d+$"]

# Explorer — show all admin-registered models without requiring explorer_enabled
EXPLORER_DISCOVER_ALL = True

# Email backend for development (prints to console)
# To test real email delivery locally, set EMAIL_BACKEND in your .env file:
#   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# Background Tasks - uses DatabaseBackend from base settings by default
# The worker auto-reloads in DEBUG mode: python manage.py db_worker
# Uncomment below to run tasks immediately without a worker (for simple testing):
# TASKS = {
#     "default": {
#         "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
#     }
# }
