"""
Base Django settings for smallstack project.
"""

from pathlib import Path

from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-this-in-production")

# Application definition
INSTALLED_APPS = [
    # Custom apps - must be before django.contrib.admin for template overrides
    "apps.accounts",
    "apps.smallstack",
    "apps.profile",
    "apps.help",
    "apps.tasks",
    "apps.activity",
    "apps.website",  # Project-specific pages (customize freely)
    # Django built-in apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "django_extensions",
    "django_tasks_db",
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.activity.middleware.ActivityMiddleware",
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
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
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

# Email settings
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@example.com")
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)

# Activity Tracking
ACTIVITY_MAX_ROWS = config("ACTIVITY_MAX_ROWS", default=10000, cast=int)
ACTIVITY_PRUNE_INTERVAL = config("ACTIVITY_PRUNE_INTERVAL", default=100, cast=int)
ACTIVITY_EXCLUDE_PATHS = ["/static/", "/media/", "/favicon.ico", "/health/", "/admin/jsi18n/", "/__debug__/"]

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
