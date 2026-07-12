"""
Base Django settings for smallstack project.
"""

import secrets
from pathlib import Path

import decouple
from decouple import Config, RepositoryEmpty, RepositoryEnv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Scope python-decouple to *this project's* .env BEFORE anything else
# imports from it. The default ``from decouple import config`` walks UP
# the filesystem looking for an .env file, which silently picks up
# parent-directory .env files in nested-project workspaces (a
# sandbox/.env shadowing the project's own defaults was the round-2
# audit's environmental finding). Binding to BASE_DIR / ".env" keeps
# each project's secrets local. Environment variables still take
# precedence — that's the decouple contract.
#
# We monkey-patch ``decouple.config`` so every subsequent
# ``from decouple import config`` (in smallstack.py, development.py,
# production.py, etc.) picks up the scoped version automatically — no
# need to change four call sites.
_PROJECT_ENV = BASE_DIR / ".env"
config = Config(RepositoryEnv(str(_PROJECT_ENV)) if _PROJECT_ENV.exists() else RepositoryEmpty())
decouple.config = config

# SmallStack app-level settings (branding, feature flags, sidebar, etc.)
# Edit config/settings/smallstack.py to customize your instance.
from config.settings.smallstack import *  # noqa: E402, F401, F403

# SECURITY WARNING: keep the secret key used in production secret!
# In development, auto-generates a random key so devs never need to configure one.
# In production, docker-entrypoint.sh generates and persists a key to the data volume,
# or you can set SECRET_KEY explicitly via environment variable or .kamal/secrets.
SECRET_KEY = config("SECRET_KEY", default=secrets.token_urlsafe(50))

# Application definition
INSTALLED_APPS = [
    # Custom apps - must be before django.contrib.admin for template overrides
    "apps.accounts",
    "apps.smallstack",
    "apps.profile",
    "apps.help",
    "apps.tasks",
    "apps.activity",
    "apps.heartbeat",
    "apps.usermanager",
    "apps.website",  # Project-specific pages (customize freely)
    "apps.mcp",  # Model Context Protocol server for AI clients
    "apps.tokenmgr",  # User-facing UI for API token management
    "apps.api",  # API admin: /smallstack/api/ health + activity + threat panel
    "apps.search",  # Search: FTS5/PG-FTS + per-CRUDView opt-in + MCP search tools
    # Django built-in apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Explorer must come after django.contrib.admin (discovers admin-registered models)
    "apps.explorer",
    # Third-party apps
    "django_extensions",
    "django_tasks_db",
    "django_filters",
    "corsheaders",
    "axes",
]

# Background Tasks configuration
# Uses DatabaseBackend for persistent task storage
# Run workers with: python manage.py db_worker
TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default", "email"],
    }
}

MIDDLEWARE = [
    # First: answer /health/ before Host validation so proxy/LB health checks
    # (unpredictable container-IP Host) succeed without ALLOWED_HOSTS=*.
    "apps.smallstack.middleware.HealthCheckMiddleware",
    "apps.smallstack.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.smallstack.middleware.TimezoneMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.smallstack.middleware.HtmxLoginRedirectMiddleware",
    "apps.activity.middleware.ActivityMiddleware",
    "axes.middleware.AxesMiddleware",
    "csp.middleware.CSPMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.smallstack.context_processors.branding",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Custom user model
AUTH_USER_MODEL = "accounts.User"

# Authentication backends (axes must be first for rate limiting)
AUTHENTICATION_BACKENDS = [
    # Axes must stay first so brute-force protection wraps every attempt.
    "axes.backends.AxesStandaloneBackend",
    # Allow signing in with username OR email. Remove this line to require
    # username-only login.
    "apps.accounts.backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Authentication settings
LOGIN_URL = "/smallstack/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Internationalization
LANGUAGE_CODE = "en-us"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise configuration
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = config("MEDIA_ROOT", default=str(BASE_DIR / "media"))

# SQLite Performance Tuning
# Applied to all SQLite connections in dev and production.
# WAL mode enables concurrent reads during writes.
# IMMEDIATE transactions prevent "database is locked" errors.
# See: https://blog.pecar.me/sqlite-django-config
SQLITE_OPTIONS = {
    "transaction_mode": "IMMEDIATE",
    "timeout": 5,
    "init_command": (
        "PRAGMA journal_mode=WAL;"
        "PRAGMA synchronous=NORMAL;"
        "PRAGMA temp_store=MEMORY;"
        "PRAGMA mmap_size=134217728;"
        "PRAGMA journal_size_limit=27103364;"
        "PRAGMA cache_size=2000;"
    ),
}

# Content Security Policy (django-csp)
# Styles, fonts, and images allow "https:" so CDN frameworks (Bootstrap, Tailwind,
# Google Fonts, etc.) work out of the box. Scripts stay restricted to 'self' — that's
# where XSS risk lives. Tighten these in production if you don't use external resources,
# or loosen script-src if you need third-party analytics/widgets.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "'unsafe-inline'"],
        "style-src": ["'self'", "'unsafe-inline'", "https:"],
        "img-src": ["'self'", "data:", "https:"],
        "font-src": ["'self'", "https:", "data:"],
        "connect-src": ["'self'"],
        "frame-ancestors": ["'none'"],
        "form-action": ["'self'"],
        # Strict directives that cost nothing here (no inline-script trade-off):
        # block <base> tag hijacking and <object>/<embed> plugin injection.
        "base-uri": ["'self'"],
        "object-src": ["'none'"],
    }
}


# CORS (django-cors-headers)
# By default, no cross-origin requests are allowed. To enable a frontend on a
# different origin (e.g., React dev server), set CORS_ALLOWED_ORIGINS in .env:
#   CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="",
    cast=lambda v: [s.strip() for s in v.split(",") if s.strip()] if v else [],
)
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "origin",
    "x-requested-with",
]

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
