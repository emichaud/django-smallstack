---
title: SQLite Database
description: Why SQLite is the perfect default for many Django projects
---

# SQLite Database

{{ project_name }} uses **SQLite** as its default database—and that's a deliberate choice, not a compromise. For solo developers, small teams, and internal applications, SQLite is often the *best* database option, not just the easiest one.

> **See also:** [PostgreSQL Database](/help/smallstack/database-postgresql/) for when you need to scale beyond SQLite.

## Why SQLite?

SQLite has experienced a renaissance in the web development community. What was once dismissed as "just for development" is now recognized as a **production-ready database** for many use cases.

### The Numbers

- **Handles thousands of requests per second** on modern hardware
- **Supports databases up to 281 terabytes** (far more than most apps need)
- **Used in production** by countless mobile apps, embedded systems, and yes—web applications
- **Most deployed database in the world** (every smartphone, browser, and countless applications)

### Perfect For

| Use Case | Why SQLite Works |
|----------|------------------|
| Internal tools | Single-user or small team, infrequent writes |
| Admin dashboards | Read-heavy workloads are SQLite's strength |
| Prototypes & MVPs | Ship fast, migrate later if needed |
| Personal projects | Zero configuration, zero cost |
| Content sites | Blogs, documentation, portfolios |
| Budget-conscious deployments | No database service fees |

## How {{ project_name }} Sets Up SQLite

The project separates the database file from the application code, which is critical for containerized deployments.

### The Data Directory Pattern

```
/app/
├── apps/               # Application code (disposable)
├── static/             # Static files (disposable)
├── data/               # Database lives here (PERSISTENT)
│   └── db.sqlite3
└── media/              # Uploads (PERSISTENT)
```

In `config/settings/base.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db.sqlite3",
    }
}
```

### Why This Matters for Docker

Containers are **ephemeral**—they can be destroyed and recreated at any time. By mounting the `data/` directory as a volume, your database persists across container rebuilds:

```yaml
# docker-compose.yml
volumes:
  - ./data:/app/data      # Local development

# deploy.yml (Kamal)
volumes:
  - /root/app_data/db:/app/data   # VPS deployment
```

**Key insight:** The database lives on your VPS filesystem, not inside the container. When you deploy a new version, the container is replaced but the data remains untouched.

### Backup Strategy

With SQLite on a VPS, backups are straightforward:

1. **VPS snapshots** — Most providers offer automated snapshots. Enable them and your database is automatically backed up.

2. **File copy** — SQLite is a single file. Copy it anywhere:
   ```bash
   # On the VPS
   cp /root/app_data/db/db.sqlite3 /root/backups/db-$(date +%Y%m%d).sqlite3
   ```

3. **SQLite backup command** — For live backups without stopping the app:
   ```bash
   sqlite3 /root/app_data/db/db.sqlite3 ".backup '/root/backups/db-backup.sqlite3'"
   ```

## SQLite Best Practices

### Enable WAL Mode

Write-Ahead Logging improves concurrent read performance. {{ project_name }} enables this automatically, but here's how it works:

```python
# In settings
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db.sqlite3",
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL;",
        },
    }
}
```

### Understand the Limitations

SQLite has **one write at a time**. This is fine for:
- ✅ Read-heavy workloads (admin dashboards, content sites)
- ✅ Low-to-moderate write volume (internal tools, small teams)
- ✅ Single-server deployments

Consider PostgreSQL if you need:
- ❌ High concurrent write volume
- ❌ Multiple servers writing to the same database
- ❌ Advanced features (full-text search, JSON operators, PostGIS)

## Cost Comparison

Consider hosting a small Django application:

**With Managed PostgreSQL:**

| Item | Monthly Cost |
|------|-------------|
| VPS (basic) | $5-10 |
| Managed PostgreSQL | $15+ |
| **Total** | **$20-25+** |

**With SQLite:**

| Item | Monthly Cost |
|------|-------------|
| VPS (basic) | $5-10 |
| Database | $0 (included) |
| **Total** | **$5-10** |

**Savings: $10-15/month ($120-180/year)** per application

For a solo developer running multiple small projects, SQLite can save hundreds of dollars annually.

## The Trending Shift

The "SQLite in production" movement has gained significant momentum:

- **Ruby on Rails 8** ships with SQLite as a viable production option
- **Litestream** enables real-time SQLite replication
- **Turso/LibSQL** brings SQLite to the edge
- **Major frameworks** are reconsidering SQLite as a first-class citizen

The web development community is recognizing that **not every application needs PostgreSQL**. For many projects, SQLite's simplicity, reliability, and zero-cost operation make it the pragmatic choice.

## When to Migrate

You'll know it's time to consider PostgreSQL when:

1. **Write contention** — You're seeing database lock errors under load
2. **Team growth** — Multiple developers need concurrent write access
3. **Scale requirements** — You need horizontal scaling or read replicas
4. **Feature needs** — You need full-text search, JSONB, or geospatial queries

Until then, SQLite serves admirably. And when you do need to migrate, the path is well-documented.

**[Read the PostgreSQL Migration Guide](/help/smallstack/database-postgresql/)**

## Quick Reference

| Task | Command |
|------|---------|
| Access SQLite shell | `sqlite3 data/db.sqlite3` |
| Backup database | `sqlite3 data/db.sqlite3 ".backup 'backup.sqlite3'"` |
| Check database size | `ls -lh data/db.sqlite3` |
| Vacuum (reclaim space) | `sqlite3 data/db.sqlite3 "VACUUM;"` |
| Check integrity | `sqlite3 data/db.sqlite3 "PRAGMA integrity_check;"` |

### In Docker/Kamal

```bash
# Access SQLite shell
kamal app exec "sqlite3 /app/data/db.sqlite3"

# Run Django shell
kamal app exec "python manage.py dbshell"
```
