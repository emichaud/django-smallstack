"""
Development settings for smallstack project.
"""

from decouple import config

from .base import *  # noqa: F401, F403

DEBUG = True

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

# Debug toolbar
INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405

INTERNAL_IPS = [
    "127.0.0.1",
    "localhost",
]

# Debug toolbar settings
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
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
