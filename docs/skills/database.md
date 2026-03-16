# Skill: Database Configuration

SmallStack uses SQLite by default and supports PostgreSQL for production scaling. This skill covers database selection, configuration, backups, and migration between engines.

## Overview

SmallStack ships with SQLite as a deliberate choice — not a compromise. For solo developers, small teams, and internal tools, SQLite handles thousands of requests per second with zero configuration. When you need concurrent writes, advanced data types, or horizontal scaling, PostgreSQL is the upgrade path.

## File Locations

```
config/settings/
├── base.py                # Database configuration, BACKUP_* settings
├── development.py         # SQLite default
└── production.py          # PostgreSQL option

data/
└── db.sqlite3             # SQLite database file (persistent)

backups/                   # Backup files (auto-managed)

apps/smallstack/docs/
├── database-sqlite.md     # In-app SQLite reference
├── database-postgresql.md # In-app PostgreSQL guide
└── database-backups.md    # In-app backup reference
```

## SQLite (Default)

### Data Directory Pattern

The database file lives in `data/db.sqlite3`, separated from application code. This is critical for containerized deployments — the `data/` directory is mounted as a volume.

```python
# config/settings/base.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db.sqlite3",
    }
}
```

### When SQLite Works

| Use Case | Why |
|----------|-----|
| Internal tools | Single-user or small team, infrequent writes |
| Admin dashboards | Read-heavy workloads |
| Prototypes & MVPs | Ship fast, migrate later |
| Content sites | Blogs, docs, portfolios |
| Budget deployments | No database service fees |

## PostgreSQL

### When to Switch

- "database is locked" errors (too many concurrent writes)
- Need JSONB, arrays, full-text search
- Multiple developers need simultaneous write access
- Horizontal scaling (read replicas, connection pooling)

### Configuration

```python
# config/settings/base.py (DATABASE_URL approach)
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    url = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": url.path[1:],
            "USER": url.username,
            "PASSWORD": url.password,
            "HOST": url.hostname,
            "PORT": url.port or 5432,
        }
    }
```

### Install Driver

```bash
uv add psycopg[binary]
```

### Environment Variables

```bash
# .env
DATABASE_URL=postgres://postgres:password@localhost:5432/smallstack
```

## Migration: SQLite → PostgreSQL

```bash
# 1. Export from SQLite
uv run python manage.py dumpdata --natural-foreign --natural-primary -o data_dump.json

# 2. Switch DATABASE_URL to PostgreSQL

# 3. Apply migrations
uv run python manage.py migrate

# 4. Import data
uv run python manage.py loaddata data_dump.json
```

## Backups (SQLite)

SmallStack ships a complete SQLite backup system: scheduled, manual, and downloadable.

### Quick Start

```bash
make backup                           # Create a backup
python manage.py backup_db --keep 5   # With custom retention
```

### Backup Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `BACKUP_DIR` | `<project>/backups/` | Backup storage directory |
| `BACKUP_RETENTION` | `10` | Default number of backups to keep |
| `BACKUP_CRON_ENABLED` | `false` | Enable cron-based scheduled backups |
| `BACKUP_DOWNLOAD_ENABLED` | `true` | Allow downloads from web UI |

### Dashboard

Staff users access `/backups/` for:

- **Activity tab** — stat cards, backup history table with status badges
- **Files tab** — backup files on disk with sizes
- **Configuration tab** — current database and backup settings
- **Backup detail** — per-backup timeline, download, and metadata

### Scheduled Backups (Docker)

Enable with `BACKUP_CRON_ENABLED=true` in `docker-compose.yml` or `deploy.yml`. Default: daily at 2 AM UTC, retaining 14 days.

### Three-Layer Strategy

| Layer | Covers | Doesn't Cover |
|-------|--------|---------------|
| On-server backups | Bad deploys, data errors | VPS failure |
| Downloaded copies | VPS failure, provider outage | Freshness |
| VPS snapshots | Disk failure, server destruction | Provider outage |

## Production with Kamal

PostgreSQL as a Kamal accessory:

```yaml
accessories:
  db:
    image: postgres:16-alpine
    host: 107.170.48.56
    env:
      secret:
        - POSTGRES_PASSWORD
      clear:
        POSTGRES_DB: smallstack
        POSTGRES_USER: postgres
    directories:
      - data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```

## Best Practices

1. **Start with SQLite** — it handles more than you think
2. **Separate data from code** — use the `data/` directory pattern
3. **Enable backups early** — `BACKUP_CRON_ENABLED=true` in production
4. **Download copies periodically** — on-server backups don't survive VPS failure
5. **Migrate to PostgreSQL** only when you hit SQLite's limits (concurrent writes, advanced features)
6. **Use `DATABASE_URL`** for clean environment-based switching
