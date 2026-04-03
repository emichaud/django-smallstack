"""
Base Django settings for smallstack project.
"""

import secrets
from pathlib import Path

from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

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
    "django_tables2",
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
    "axes.backends.AxesStandaloneBackend",
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
TIME_ZONE = config("TIME_ZONE", default="America/New_York")
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

# Site configuration
SITE_NAME = config("SITE_NAME", default="SmallStack")
SITE_DOMAIN = config("SITE_DOMAIN", default="localhost:8000")
USE_HTTPS = config("USE_HTTPS", default=False, cast=bool)

# SmallStack Help Documentation
# Set to False to hide SmallStack reference docs from /help/
SMALLSTACK_DOCS_ENABLED = config("SMALLSTACK_DOCS_ENABLED", default=True, cast=bool)

# SmallStack Color Palette
# System-wide default palette. Users can override in their profile.
# Options: django, high-contrast, dark-blue, orange, purple
SMALLSTACK_COLOR_PALETTE = config("SMALLSTACK_COLOR_PALETTE", default="django")

# Auth Feature Flags
# Set to False to hide Login/Sign Up buttons from the topbar
SMALLSTACK_LOGIN_ENABLED = config("SMALLSTACK_LOGIN_ENABLED", default=True, cast=bool)
# Set to False to hide Sign Up and 404 the signup URL
SMALLSTACK_SIGNUP_ENABLED = config("SMALLSTACK_SIGNUP_ENABLED", default=True, cast=bool)

# Sidebar Configuration
# Set to False to completely remove the sidebar and hamburger toggle
SMALLSTACK_SIDEBAR_ENABLED = config("SMALLSTACK_SIDEBAR_ENABLED", default=True, cast=bool)
# Set to False to start with sidebar closed by default (users can still toggle open)
SMALLSTACK_SIDEBAR_OPEN = config("SMALLSTACK_SIDEBAR_OPEN", default=True, cast=bool)
# Default sidebar state: "open", "closed", or "disabled"
# When set, this takes precedence over SMALLSTACK_SIDEBAR_OPEN.
# Can be overridden per-page via template block or view context.
SMALLSTACK_SIDEBAR_DEFAULT = config("SMALLSTACK_SIDEBAR_DEFAULT", default="open")

# Topbar Navigation
# Always show the unified topbar nav (from registry), even when sidebar is open.
# When False (default), topbar nav only appears when sidebar is closed/disabled.
SMALLSTACK_TOPBAR_NAV_ALWAYS = config("SMALLSTACK_TOPBAR_NAV_ALWAYS", default=True, cast=bool)

# Legacy topbar nav (DEPRECATED — use the nav registry instead)
# These settings are kept for backward compatibility and will be removed.
SMALLSTACK_TOPBAR_NAV_ENABLED = config("SMALLSTACK_TOPBAR_NAV_ENABLED", default=False, cast=bool)
SMALLSTACK_TOPBAR_NAV_ITEMS = []

# Branding Configuration
# These paths are relative to STATIC_URL. Override to customize branding.
BRAND_NAME = config("BRAND_NAME", default="SmallStack")
BRAND_LOGO = config("BRAND_LOGO", default="smallstack/brand/django-smallstack-logo.svg")
BRAND_LOGO_DARK = config("BRAND_LOGO_DARK", default="smallstack/brand/django-smallstack-logo-dark.svg")
BRAND_LOGO_TEXT = config("BRAND_LOGO_TEXT", default="smallstack/brand/django-smallstack-text.svg")
BRAND_ICON = config("BRAND_ICON", default="smallstack/brand/django-smallstack-icon.svg")
BRAND_FAVICON = config("BRAND_FAVICON", default="smallstack/brand/django-smallstack-icon.ico")
BRAND_SOCIAL_IMAGE = config("BRAND_SOCIAL_IMAGE", default="smallstack/brand/django-smallstack-social.png")
BRAND_TAGLINE = config("BRAND_TAGLINE", default="A minimal Django starter stack")

# Legal / Consent
BRAND_PRIVACY_URL = config("BRAND_PRIVACY_URL", default="/privacy/")
BRAND_TERMS_URL = config("BRAND_TERMS_URL", default="/terms/")
BRAND_COOKIE_BANNER = config("BRAND_COOKIE_BANNER", default=True, cast=bool)
BRAND_SIGNUP_TERMS_NOTICE = config("BRAND_SIGNUP_TERMS_NOTICE", default=True, cast=bool)

# Email settings
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@example.com")
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# Activity Tracking
ACTIVITY_MAX_ROWS = config("ACTIVITY_MAX_ROWS", default=10000, cast=int)
ACTIVITY_EXCLUDE_PATHS = [
    "/static/",
    "/media/",
    "/favicon.ico",
    "/health/",
    "/status/",
    "/smallstack/status/",
    "/admin/jsi18n/",
    "/__debug__/",
]

# SQLite Backup
BACKUP_DIR = config("BACKUP_DIR", default=str(BASE_DIR / "backups"))
BACKUP_RETENTION = config("BACKUP_RETENTION", default=10, cast=int)
BACKUP_CRON_ENABLED = config("BACKUP_CRON_ENABLED", default=True, cast=bool)
BACKUP_DOWNLOAD_ENABLED = config("BACKUP_DOWNLOAD_ENABLED", default=True, cast=bool)

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

# Heartbeat / Uptime Monitoring
HEARTBEAT_RETENTION_DAYS = config("HEARTBEAT_RETENTION_DAYS", default=7, cast=int)
HEARTBEAT_EXPECTED_INTERVAL = config("HEARTBEAT_EXPECTED_INTERVAL", default=60, cast=int)

# Login Rate Limiting (django-axes)
AXES_FAILURE_LIMIT = config("AXES_FAILURE_LIMIT", default=5, cast=int)
AXES_COOLOFF_TIME = 0.25  # 15 minutes lockout
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]  # Lock per username+IP combination
AXES_RESET_ON_SUCCESS = True  # Reset failure count after successful login

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
