"""
Production settings for admin_starter project.
"""

from decouple import Csv, config

from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# Database
# SQLite is the default - stored in /app/data/ which is mounted as a volume
# This means the database persists across container rebuilds and deploys
# VPS backups automatically include your database - simple and effective
# See /help/database-sqlite/ for more on why SQLite works great in production
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": config("DATABASE_PATH", default="/app/data/db.sqlite3"),
    }
}

# PostgreSQL configuration (when you outgrow SQLite)
# Set DATABASE_URL environment variable to enable PostgreSQL
# Example: DATABASE_URL=postgres://user:pass@host:5432/dbname
# See /help/database-postgresql/ for migration guide
#
# To use PostgreSQL:
# 1. Install driver: uv add psycopg[binary]
# 2. Set DATABASE_URL in your environment or .kamal/secrets
# 3. Uncomment below and comment out SQLite config above
#
# import os
# from urllib.parse import urlparse
#
# DATABASE_URL = os.environ.get("DATABASE_URL")
# if DATABASE_URL:
#     url = urlparse(DATABASE_URL)
#     DATABASES = {
#         "default": {
#             "ENGINE": "django.db.backends.postgresql",
#             "NAME": url.path[1:],
#             "USER": url.username,
#             "PASSWORD": url.password,
#             "HOST": url.hostname,
#             "PORT": url.port or 5432,
#             "CONN_MAX_AGE": 60,
#             "CONN_HEALTH_CHECKS": True,
#         }
#     }

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# HTTPS settings
# CSRF_TRUSTED_ORIGINS is required for HTTPS behind a proxy (like kamal-proxy)
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="",
    cast=lambda v: [s.strip() for s in v.split(",") if s.strip()] if v else [],
)

# kamal-proxy handles HTTPS redirect, so SECURE_SSL_REDIRECT should be False
# to avoid breaking internal health checks (which use HTTP)
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=True, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=True, cast=bool)

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": (
                '{"time": "%(asctime)s", "level": "%(levelname)s", "module": "%(module)s", "message": "%(message)s"}'
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# Email configuration (configure via environment variables)
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
