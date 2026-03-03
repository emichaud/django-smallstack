"""
Development settings for admin_starter project.
"""

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
#         "NAME": "admin_starter",
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
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
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
    },
}

# Email backend for development (prints to console)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Background Tasks - uses DatabaseBackend from base settings by default
# The worker auto-reloads in DEBUG mode: python manage.py db_worker
# Uncomment below to run tasks immediately without a worker (for simple testing):
# TASKS = {
#     "default": {
#         "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
#     }
# }
