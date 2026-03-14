# Skill: Settings & Configuration

This skill describes SmallStack's split settings structure, key configuration options, and environment variable usage.

## Overview

SmallStack uses a split settings pattern with separate files for base, development, and production. Settings are loaded from environment variables via `python-decouple`, with sensible defaults for development.

## File Locations

```
config/settings/
├── base.py           # Shared settings (all environments)
├── development.py    # DEBUG=True, debug toolbar
├── production.py     # Security headers, production database
└── test.py           # Pytest-specific settings
```

## Settings Selection

The active settings module is controlled by `DJANGO_SETTINGS_MODULE`:

| Context | Value |
|---------|-------|
| Development (default) | `config.settings.development` |
| Production / Docker | `config.settings.production` |
| Tests | `config.settings.test` |

Set via environment variable or in `manage.py` / `wsgi.py`.

## Key Settings in base.py

### Installed Apps

```python
INSTALLED_APPS = [
    # Custom apps (before django.contrib.admin for template overrides)
    "apps.accounts",
    "apps.smallstack",
    "apps.profile",
    "apps.help",
    "apps.tasks",
    "apps.activity",
    "apps.website",        # Project-specific pages
    # Django built-in
    "django.contrib.admin",
    # ...
    # Third-party
    "django_extensions",
    "django_tasks_db",
]
```

### Branding

All branding is configurable via environment variables:

```python
BRAND_NAME = config("BRAND_NAME", default="SmallStack")
BRAND_LOGO = config("BRAND_LOGO", default="smallstack/brand/django-smallstack-logo.svg")
BRAND_LOGO_DARK = config("BRAND_LOGO_DARK", default="smallstack/brand/django-smallstack-logo-dark.svg")
BRAND_LOGO_TEXT = config("BRAND_LOGO_TEXT", default="smallstack/brand/django-smallstack-text.svg")
BRAND_ICON = config("BRAND_ICON", default="smallstack/brand/django-smallstack-icon.svg")
BRAND_FAVICON = config("BRAND_FAVICON", default="smallstack/brand/django-smallstack-icon.ico")
BRAND_SOCIAL_IMAGE = config("BRAND_SOCIAL_IMAGE", default="smallstack/brand/django-smallstack-social.png")
BRAND_TAGLINE = config("BRAND_TAGLINE", default="A minimal Django starter stack")
```

Brand paths are relative to `STATIC_URL`. Override with your own assets in `static/brand/`.

### Site Configuration

```python
SITE_NAME = config("SITE_NAME", default="SmallStack")
SITE_DOMAIN = config("SITE_DOMAIN", default="localhost:8000")
USE_HTTPS = config("USE_HTTPS", default=False, cast=bool)
```

### SmallStack Feature Flags

```python
# Color palette system default (users can override in profile)
SMALLSTACK_COLOR_PALETTE = config("SMALLSTACK_COLOR_PALETTE", default="django")
# Options: django, high-contrast, dark-blue, orange, purple

# Show/hide bundled SmallStack reference docs in /help/
SMALLSTACK_DOCS_ENABLED = config("SMALLSTACK_DOCS_ENABLED", default=True, cast=bool)

# Show/hide Login/Sign Up in topbar
SMALLSTACK_LOGIN_ENABLED = config("SMALLSTACK_LOGIN_ENABLED", default=True, cast=bool)

# Show/hide Sign Up (also 404s the signup URL)
SMALLSTACK_SIGNUP_ENABLED = config("SMALLSTACK_SIGNUP_ENABLED", default=True, cast=bool)

# Completely remove the sidebar and hamburger toggle
SMALLSTACK_SIDEBAR_ENABLED = config("SMALLSTACK_SIDEBAR_ENABLED", default=True, cast=bool)

# Start with sidebar closed by default (users can still toggle open)
SMALLSTACK_SIDEBAR_OPEN = config("SMALLSTACK_SIDEBAR_OPEN", default=True, cast=bool)  # deprecated

# Default sidebar state: "open", "closed", or "disabled"
# Supersedes SMALLSTACK_SIDEBAR_OPEN. Can be overridden per-page.
SMALLSTACK_SIDEBAR_DEFAULT = config("SMALLSTACK_SIDEBAR_DEFAULT", default="open")

# Show the unified topbar nav even when the sidebar is open
SMALLSTACK_TOPBAR_NAV_ALWAYS = config("SMALLSTACK_TOPBAR_NAV_ALWAYS", default=False, cast=bool)
```

### Activity Tracking

```python
ACTIVITY_MAX_ROWS = config("ACTIVITY_MAX_ROWS", default=10000, cast=int)
ACTIVITY_PRUNE_INTERVAL = config("ACTIVITY_PRUNE_INTERVAL", default=100, cast=int)
ACTIVITY_EXCLUDE_PATHS = ["/static/", "/media/", "/favicon.ico", "/health/", "/admin/jsi18n/", "/__debug__/"]
```

### Background Tasks

```python
TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default", "email"],
    }
}
```

### Email

```python
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@example.com")
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
```

For production SMTP, set `EMAIL_BACKEND=django.core.mail.backends.smtp.SmtpBackend` and configure `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`.

### Static Files

WhiteNoise serves static files in production with compression and caching:

```python
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

## Environment Variables

SmallStack uses `python-decouple` to read from `.env` files or environment variables. The pattern:

```python
from decouple import config
SECRET_KEY = config("SECRET_KEY", default=secrets.token_urlsafe(50))  # auto-generated
USE_HTTPS = config("USE_HTTPS", default=False, cast=bool)
ACTIVITY_MAX_ROWS = config("ACTIVITY_MAX_ROWS", default=10000, cast=int)
```

### Adding New Settings

1. Add to `config/settings/base.py` using the `config()` pattern
2. Document the default value
3. Add to `.env.example` if one exists

## Development vs Production

### development.py additions
- `DEBUG = True`
- Django Debug Toolbar enabled
- Console email backend

### production.py additions
- `DEBUG = False`
- Security headers: HSTS, secure cookies, content type sniffing protection
- `ALLOWED_HOSTS` from environment variable
- Database path from `DATABASE_PATH` env var
- JSON logging format

## Best Practices

1. **Use `config()` for all secrets** — Never hardcode secrets in settings files
2. **Keep base.py generic** — Environment-specific overrides go in development.py/production.py
3. **Custom apps before Django** — Ensures template overrides work correctly
4. **Use feature flags** — `SMALLSTACK_*` settings let you toggle features without code changes
