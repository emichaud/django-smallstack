---
title: Settings & Configuration
description: Understanding the split settings architecture and environment variables
---

# Settings & Configuration

{{ project_name }} uses a **split settings architecture** with environment-based configuration. This approach follows security best practices by keeping sensitive values out of your codebase.

## Overview

```
config/
├── settings/
│   ├── __init__.py      # Empty, makes it a package
│   ├── base.py          # Shared Django infrastructure settings
│   ├── smallstack.py    # SmallStack-specific settings (BRAND_*, SMALLSTACK_*, etc.)
│   ├── development.py   # Local development overrides
│   └── production.py    # Production-specific settings
├── urls.py
└── wsgi.py
```

## The Settings Files

### base.py - Django Infrastructure

Contains core Django settings used in **all environments**:

- `INSTALLED_APPS` - Your Django apps
- `MIDDLEWARE` - Request/response processing
- `TEMPLATES` - Template configuration
- `AUTH_USER_MODEL` - Custom user model
- `LOGIN_URL`, `LOGIN_REDIRECT_URL` - Authentication URLs
- `STATIC_URL`, `MEDIA_URL` - Static/media file URLs

`base.py` imports everything from `smallstack.py` via `from config.settings.smallstack import *`, so all SmallStack settings are available transitively.

**When to add settings here:**
- Settings that don't change between environments
- App registrations
- Middleware ordering
- Template configuration
- URL settings

### smallstack.py - SmallStack-Specific Settings

Contains all SmallStack feature settings:

- `BRAND_*` - Branding (name, logos, favicon, social image)
- `SMALLSTACK_*` - Feature flags (docs, login, signup, sidebar, topbar nav, color palette)
- `SITE_*` - Site metadata (name, domain)
- `BACKUP_*` - Backup configuration (directory, retention, cron, downloads)
- `HEARTBEAT_*` - Uptime monitoring (retention, interval)
- `ACTIVITY_*` - Activity tracking (max rows, excluded paths)
- `AXES_*` - Login rate limiting
- `DEFAULT_FROM_EMAIL` - Default email sender
- `EMAIL_BACKEND` - Email backend
- `TIME_ZONE` - Server timezone for display
- `USE_HTTPS` - HTTPS enforcement

**When to add settings here:**
- SmallStack feature configuration
- Branding and site identity
- Feature flags and toggles

### development.py - Local Development

Imports everything from `base.py` and adds development-specific settings:

```python
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Use SQLite for simplicity
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Print emails to console
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

**When to add settings here:**
- Debug-only features
- Local database configuration
- Development email backend
- Relaxed security settings for testing
- Development-only third-party tool configs

### production.py - Production Deployment

Imports from `base.py` and adds security-hardened settings:

```python
from .base import *
from decouple import config

DEBUG = False
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=lambda v: [s.strip() for s in v.split(",")])
SECRET_KEY = config("SECRET_KEY")

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
```

**When to add settings here:**
- Security hardening
- Production database configuration
- Real email backend (SMTP)
- HTTPS/SSL settings
- Caching configuration
- Production logging

---

## Environment Variables with python-decouple

{{ project_name }} uses [python-decouple](https://github.com/HBNetwork/python-decouple) to read configuration from environment variables and `.env` files.

### Why Use Environment Variables?

1. **Security** - Secrets never enter version control
2. **Flexibility** - Change configuration without code changes
3. **12-Factor App** - Follows modern deployment best practices
4. **Environment parity** - Same code runs in dev and production

### How It Works

```python
from decouple import config

# Read with a default value
DEBUG = config("DEBUG", default=False, cast=bool)

# Read an integer
DATABASE_PORT = config("DATABASE_PORT", default=5432, cast=int)

# Read a comma-separated list
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=lambda v: [s.strip() for s in v.split(",")])
```

### The .env File

Create a `.env` file in your project root for local development:

```bash
# .env - DO NOT COMMIT THIS FILE

# Security (SECRET_KEY is auto-generated if not set)
DEBUG=True

# Database (production)
DATABASE_URL=postgres://user:pass@localhost:5432/dbname

# Email
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Development superuser (defaults match the README quick-start)
DEV_SUPERUSER_USERNAME=admin
DEV_SUPERUSER_PASSWORD=admin
DEV_SUPERUSER_EMAIL=admin@example.com
```

### Configuration Lookup Order

python-decouple looks for values in this order:

1. **Environment variables** - System or shell environment
2. **`.env` file** - In the project root (`BASE_DIR / ".env"`)
3. **Default value** - Specified in code with `default=`

This means:
- In production, set real environment variables (more secure)
- In development, use `.env` file (convenient)
- Defaults provide fallbacks for optional settings

**Project-scoped, not walk-up.** SmallStack overrides the default decouple
behaviour (which walks UP the filesystem looking for any `.env`) and binds
the lookup to `BASE_DIR / ".env"` only. This stops a parent-directory `.env`
(e.g. in a multi-project workspace) from silently shadowing your project's
defaults. See `config/settings/base.py` for the monkey-patch.

---

## Adding New Configuration

### Step 1: Decide Where It Belongs

| Setting Type | File | Example |
|--------------|------|---------|
| App registration | `base.py` | `INSTALLED_APPS` |
| Django infrastructure | `base.py` | `AUTH_USER_MODEL`, `MIDDLEWARE` |
| SmallStack features | `smallstack.py` | `BRAND_NAME`, `SMALLSTACK_*`, `BACKUP_*` |
| Debug features | `development.py` | `DEBUG_TOOLBAR_CONFIG` |
| Security settings | `production.py` | `SECURE_SSL_REDIRECT` |
| Secrets | `.env` + `production.py` | `SECRET_KEY`, API keys |
| Environment-specific | Both dev & prod | `DATABASES` |

### Step 2: Add the Setting

**Example: Adding a third-party API key**

1. Add to `.env`:
```bash
STRIPE_API_KEY=sk_test_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx
```

2. Add to `production.py` (or `base.py` if needed everywhere):
```python
from decouple import config

STRIPE_API_KEY = config("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = config("STRIPE_WEBHOOK_SECRET")
```

3. For development with a default:
```python
STRIPE_API_KEY = config("STRIPE_API_KEY", default="sk_test_development_key")
```

**Example: Adding a feature flag**

1. Add to `.env`:
```bash
ENABLE_NEW_FEATURE=True
```

2. Add to `base.py`:
```python
from decouple import config

ENABLE_NEW_FEATURE = config("ENABLE_NEW_FEATURE", default=False, cast=bool)
```

3. Use in your code:
```python
from django.conf import settings

if settings.ENABLE_NEW_FEATURE:
    # New feature code
```

### Built-in Feature Flags

SmallStack includes these feature flags out of the box:

| Flag | Default | Purpose |
|------|---------|---------|
| `SMALLSTACK_DOCS_ENABLED` | `True` | Show/hide SmallStack reference docs from `/help/` |
| `SMALLSTACK_LOGIN_ENABLED` | `True` | Show/hide Login and Sign Up buttons in the topbar |
| `SMALLSTACK_SIGNUP_ENABLED` | `True` | Show/hide Sign Up UI and 404 the signup URL |
| `SMALLSTACK_SIDEBAR_ENABLED` | `True` | Show/hide the sidebar and hamburger toggle |
| `SMALLSTACK_SIDEBAR_OPEN` | `True` | Whether sidebar starts open or closed |
| `SMALLSTACK_TOPBAR_NAV_ENABLED` | `False` | Show a horizontal nav menu in the topbar |
| `SMALLSTACK_COLOR_PALETTE` | `"django"` | System default color palette (`django`, `light-blue`, `dark-blue`, `orange`, `purple`) |
| `TIME_ZONE` | `America/New_York` | Server timezone for date display (any IANA timezone name) |

All of these are defined in `config/settings/smallstack.py`. `SMALLSTACK_TOPBAR_NAV_ITEMS` is a Python list (not an env var) — configure it directly in your settings file. See [Topbar Navigation](/help/smallstack/topbar-navigation/) for the item format and examples.

See [Authentication](/help/smallstack/authentication/) for details on the auth flags. See [Working with Timezones](/help/smallstack/timezones/) for the full timezone architecture.

**Example: Debug Toolbar (env-gated dev tool)**

The debug toolbar is installed but off by default — controlled by an env var:

```bash
# .env
DEBUG_TOOLBAR=true
```

```python
# development.py
if config("DEBUG_TOOLBAR", default=False, cast=bool):
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
```

See the [Debug Toolbar](/help/smallstack/debug-toolbar/) page for full usage guide.

---

## Selecting the Active Settings

### Method 1: Environment Variable (Recommended)

Set `DJANGO_SETTINGS_MODULE` before running Django:

```bash
# Development
export DJANGO_SETTINGS_MODULE=config.settings.development
uv run python manage.py runserver

# Production
export DJANGO_SETTINGS_MODULE=config.settings.production
gunicorn config.wsgi:application
```

### Method 2: In .env File

```bash
# .env
DJANGO_SETTINGS_MODULE=config.settings.development
```

### Method 3: Command Line Flag

```bash
uv run python manage.py runserver --settings=config.settings.development
```

### In Docker

The `Dockerfile` and `docker-compose.yml` set this automatically:

```yaml
# docker-compose.yml
environment:
  - DJANGO_SETTINGS_MODULE=config.settings.production
```

---

## Security Best Practices

### Never Commit Secrets

Add to `.gitignore`:

```gitignore
# Environment files
.env
.env.local
.env.production

# But DO commit the example
!.env.example
```

### Use .env.example as Documentation

Maintain a `.env.example` with dummy values:

```bash
# .env.example - Safe to commit, shows required variables

# SECRET_KEY is auto-generated — only set if you want a specific key
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

DATABASE_URL=postgres://user:password@localhost:5432/dbname

EMAIL_HOST=smtp.example.com
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-password
```

### Secret Key Management

SmallStack auto-generates `SECRET_KEY` so you never need to configure one manually:

- **Development:** A random key is generated each time Django starts (sessions reset on restart, which is fine for dev)
- **Docker/Kamal:** `docker-entrypoint.sh` generates a key on first deploy and persists it to `/app/data/.secret_key` — it survives container rebuilds and redeploys
- **Explicit override:** Set `SECRET_KEY` in your environment or `.kamal/secrets` to use a specific key

### Validate Required Settings

In `production.py`, ensure critical settings are present:

```python
from decouple import config

# These will raise an error if not set
SECRET_KEY = config("SECRET_KEY")  # No default = required
DATABASE_URL = config("DATABASE_URL")

# Explicitly fail if DEBUG is somehow True
DEBUG = config("DEBUG", default=False, cast=bool)
if DEBUG:
    raise ValueError("DEBUG must be False in production")
```

### Use Different Secrets Per Environment

| Environment | SECRET_KEY |
|-------------|------------|
| Development | Can use a simple key |
| Staging | Unique secure key |
| Production | Unique secure key (different from staging) |

---

## Common Patterns

### Database Configuration

**Development (SQLite):**
```python
# development.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
```

**Production (PostgreSQL with dj-database-url):**
```python
# production.py
import dj_database_url
from decouple import config

DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL")
    )
}
```

### Email Configuration

**Development (Console):**
```python
# development.py
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

**Production (SMTP):**
```python
# production.py
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD")
```

### Static Files

**Development:**
```python
# development.py - Django serves static files
# No additional configuration needed
```

**Production:**
```python
# production.py - Use WhiteNoise or external storage
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Or S3
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME")
```

---

## Troubleshooting

### "SECRET_KEY not found"

In development, a random key is auto-generated — you shouldn't see this error. In Docker/production, `docker-entrypoint.sh` generates and persists a key automatically. If you still see this error, you may be running production settings outside of Docker:

```bash
# Set one explicitly
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
```

### Wrong Settings File Being Used

Check which settings module is active:

```python
# In Django shell
from django.conf import settings
print(settings.SETTINGS_MODULE)
```

### Changes Not Taking Effect

1. Restart your development server
2. Check you're editing the correct settings file
3. Verify the environment variable is exported (not just set)

```bash
# Wrong (only sets for current line)
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py runserver

# Right (exports for session)
export DJANGO_SETTINGS_MODULE=config.settings.development
python manage.py runserver
```

---

## Summary

| File | Purpose | Secrets? |
|------|---------|----------|
| `base.py` | Django infrastructure settings | No |
| `smallstack.py` | SmallStack feature settings (BRAND_*, SMALLSTACK_*, etc.) | No |
| `development.py` | Local dev overrides | No |
| `production.py` | Production settings | Read from env |
| `.env` | Local secrets | Yes (don't commit) |
| `.env.example` | Documentation | No (safe to commit) |

**Key principles:**
1. Secrets go in environment variables, never in code
2. Use `base.py` for Django infrastructure settings
3. Use `smallstack.py` for SmallStack feature settings (branding, flags, monitoring, etc.)
4. Use environment-specific files for overrides
5. Always provide `.env.example` for documentation
6. Validate required settings in production
