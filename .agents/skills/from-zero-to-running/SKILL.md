---
name: from-zero-to-running
description: "New project? Start here — clone → local setup → first app → production, each phase with its verification command"
license: MIT
metadata:
  source: "docs/skills/from-zero-to-running.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/from-zero-to-running.md` by `make skills-index` — edit the source, not this file.

# Skill: From Zero to Running

Complete setup guide for creating a new SmallStack project from clone through production deployment. Follow each section in order — every step includes verification commands.

## Phase 1: Clone and Local Setup

### 1.1 Clone the Repository

```bash
git clone https://github.com/emichaud/django-smallstack.git myapp
cd myapp
rm -rf .git    # Detach from upstream (or keep for pull-based updates)
git init
```

### 1.2 Create Environment File

```bash
cp .env.example .env
```

Edit `.env` with project-specific values. Every setting below must be reviewed:

#### Required Settings

| Variable | Default | Action |
|----------|---------|--------|
| `DJANGO_SETTINGS_MODULE` | `config.settings.development` | Keep for local dev. Change to `config.settings.production` in Docker/.kamal/secrets. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Add your domain in production. |

#### Development Superuser

| Variable | Default | Action |
|----------|---------|--------|
| `DEV_SUPERUSER_USERNAME` | `admin` | Change if desired. Used by `make superuser`. |
| `DEV_SUPERUSER_PASSWORD` | `admin` | Change if desired. Local dev only — never used in production. |

#### Docker Superuser (Production)

Uncomment and set these for automatic admin creation on first Docker startup:

```bash
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=<strong-password>
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

#### Timezone

```bash
TIME_ZONE=America/New_York    # IANA timezone name
TZ=America/New_York           # For Docker: keeps cron in sync with Django
```

See: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

#### Scheduled Tasks

These run automatically in Docker via supercronic — every minute (heartbeat), every 15 minutes (activity pruning), daily at 2 AM (database backup):

```bash
BACKUP_CRON_ENABLED=true              # Disable with false if not needed
# HEARTBEAT_RETENTION_DAYS=7          # Days of raw heartbeat data to keep
# ACTIVITY_MAX_ROWS=10000             # Max activity log rows before pruning
```

#### Auth Feature Flags

```bash
# SMALLSTACK_LOGIN_ENABLED=True       # False hides Login/Sign Up from topbar
# SMALLSTACK_SIGNUP_ENABLED=True      # False hides Sign Up and 404s the URL
```

#### HTTPS (Production Only)

Leave `false` for local dev. Set `true` when behind HTTPS proxy (Kamal with SSL):

```bash
SECURE_SSL_REDIRECT=false
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
```

#### Email (Required for Password Reset and Backup Alerts)

```bash
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-email-password
EMAIL_USE_TLS=true
```

Without email configured, password reset and backup failure notifications won't work. In local dev, email prints to console by default.

### 1.3 Run Setup

```bash
make setup    # installs deps, runs migrations, creates dev superuser
```

**Verify:**
```bash
make run      # starts on http://localhost:8005
```

Log in with `admin` / `admin` (or whatever you set in `.env`). Visit:

| URL | What to Check |
|-----|---------------|
| `http://localhost:8005/` | Home page loads |
| `http://localhost:8005/smallstack/` | Dashboard loads (staff only) |
| `http://localhost:8005/smallstack/explorer/` | Explorer shows registered models |
| `http://localhost:8005/status/` | Public status page |
| `http://localhost:8005/health/` | Returns `{"status": "ok"}` |

---

This skill is long; the full text is in [references/from-zero-to-running.md](references/from-zero-to-running.md) — read it before acting.
