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
│   ├── base.py          # Shared settings for all environments
│   ├── development.py   # Local development overrides
│   └── production.py    # Production-specific settings
├── urls.py
└── wsgi.py
```

## The Three Settings Files

### base.py - Shared Configuration

Contains settings used in **all environments**:

- `INSTALLED_APPS` - Your Django apps
- `MIDDLEWARE` - Request/response processing
- `TEMPLATES` - Template configuration
- `AUTH_USER_MODEL` - Custom user model
- `LOGIN_URL`, `LOGIN_REDIRECT_URL` - Authentication URLs
- `STATIC_URL`, `MEDIA_URL` - Static/media file URLs

**When to add settings here:**
- Settings that don't change between environments
- App registrations
- Middleware ordering
- Template configuration
- URL settings

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

# Read a string (default type)
SECRET_KEY = config("SECRET_KEY")

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

# Security
SECRET_KEY=your-secret-key-here
DEBUG=True

# Database (production)
DATABASE_URL=postgres://user:pass@localhost:5432/dbname

# Email
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Development superuser
DEV_SUPERUSER_USERNAME=admin
DEV_SUPERUSER_PASSWORD=admin123
DEV_SUPERUSER_EMAIL=admin@example.com
```

### Configuration Lookup Order

python-decouple looks for values in this order:

1. **Environment variables** - System or shell environment
2. **`.env` file** - In the project root
3. **Default value** - Specified in code with `default=`

This means:
- In production, set real environment variables (more secure)
- In development, use `.env` file (convenient)
- Defaults provide fallbacks for optional settings

---

## Adding New Configuration

### Step 1: Decide Where It Belongs

| Setting Type | File | Example |
|--------------|------|---------|
| App registration | `base.py` | `INSTALLED_APPS` |
| Shared behavior | `base.py` | `AUTH_USER_MODEL` |
| Debug features | `development.py` | `DEBUG_TOOLBAR_CONFIG` |
| Security settings | `production.py` | `SECURE_SSL_REDIRECT` |
| Secrets | `.env` + `production.py` | `SECRET_KEY`, API keys |
| Environment-specific | Both dev & prod | `DATABASES`, `EMAIL_BACKEND` |

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

**Example: Adding debug-only settings**

Add directly to `development.py` (no env var needed):

```python
# development.py

# Django Debug Toolbar
INSTALLED_APPS += ["debug_toolbar"]
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
INTERNAL_IPS = ["127.0.0.1"]
```

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

SECRET_KEY=change-me-to-a-real-secret-key
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

DATABASE_URL=postgres://user:password@localhost:5432/dbname

EMAIL_HOST=smtp.example.com
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-password
```

### Generate Secure Secret Keys

Never use a weak or example secret key in production:

```python
# Generate a new secret key
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
```

Or use an online generator like [djecrety.ir](https://djecrety.ir/).

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

The setting isn't in your environment or `.env` file:

```bash
# Check if it's set
echo $SECRET_KEY

# Or add to .env
echo "SECRET_KEY=your-key-here" >> .env
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
| `base.py` | Shared settings | No |
| `development.py` | Local dev overrides | No |
| `production.py` | Production settings | Read from env |
| `.env` | Local secrets | Yes (don't commit) |
| `.env.example` | Documentation | No (safe to commit) |

**Key principles:**
1. Secrets go in environment variables, never in code
2. Use `base.py` for shared settings
3. Use environment-specific files for overrides
4. Always provide `.env.example` for documentation
5. Validate required settings in production
