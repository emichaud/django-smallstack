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

> *"SQLite is likely used more than all other database engines combined. SQLite is in every iPhone and every Android phone, every Mac and every Windows 10 machine, every Firefox, Chrome, and Safari browser."*
> — [sqlite.org](https://www.sqlite.org/mostdeployed.html)

The SQLite developers acknowledge it's likely the most widely deployed database engine in existence, largely due to its ubiquity as an embedded database in mobile devices, set-top boxes, automotive systems, and consumer electronics.

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

In `config/settings/development.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": SQLITE_OPTIONS,  # WAL, IMMEDIATE, performance PRAGMAs
    }
}
```

In `config/settings/production.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": config("DATABASE_PATH", default="/app/data/db.sqlite3"),
        "OPTIONS": SQLITE_OPTIONS,
    }
}
```

`SQLITE_OPTIONS` is defined in `base.py` and includes WAL mode, IMMEDIATE transactions, and performance PRAGMAs. See the [Best Practices](#enable-wal-mode) section below for details.

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

Because SQLite is just a file, backups are remarkably simple. {{ project_name }} includes a **built-in backup system** with scheduled backups, a staff dashboard, and one-click downloads — no configuration required beyond enabling the cron schedule.

```bash
# Create a backup from the command line
make backup

# Or download your database from the staff dashboard at /backups/
```

The backup tool uses Python's `sqlite3.Connection.backup()` API to create safe, non-blocking copies while your application continues serving requests. Combined with VPS-level snapshots and periodic downloads to your local machine, you get solid multi-layer data protection.

**[Read the full Database Backups guide](/help/smallstack/database-backups/)** for setup instructions, scheduling, and backup strategy recommendations.

For manual or ad-hoc backups outside the built-in tool:

1. **VPS snapshots** — Most providers offer automated snapshots. Enable them and your database is automatically backed up.

2. **File copy** — With WAL mode enabled, the database uses three files: `db.sqlite3`, `db.sqlite3-wal`, and `db.sqlite3-shm`. A plain `cp` of the main file alone may produce a corrupt backup. Use `sqlite3 .backup` or `make backup` instead:
   ```bash
   # UNSAFE with WAL mode:
   # cp /root/app_data/db/db.sqlite3 /root/backups/db-$(date +%Y%m%d).sqlite3

   # SAFE — use the built-in backup command instead:
   make backup
   ```

3. **SQLite backup command** — For live backups without stopping the app:
   ```bash
   sqlite3 /root/app_data/db/db.sqlite3 ".backup '/root/backups/db-backup.sqlite3'"
   ```

## SQLite Best Practices

### Production-Grade SQLite Tuning

{{ project_name }} applies a set of PRAGMAs automatically via `SQLITE_OPTIONS` in `base.py`:

```python
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
```

| Setting | What it does |
|---------|-------------|
| `journal_mode=WAL` | Allows concurrent reads while a write is in progress |
| `synchronous=NORMAL` | Safe with WAL; reduces fsync overhead |
| `transaction_mode=IMMEDIATE` | Acquires write lock upfront, preventing "database is locked" errors from lock upgrades |
| `timeout=5` | Waits up to 5 seconds for the write lock instead of failing immediately |
| `temp_store=MEMORY` | Keeps temporary tables in memory |
| `mmap_size=128MB` | Memory-maps the database file for faster reads |
| `journal_size_limit` | Prevents the WAL file from growing unbounded |
| `cache_size=2000` | 2000 pages (~8 MB) of page cache |

### Understand the Limitations

SQLite allows **one writer at a time**, but with WAL mode enabled, reads are never blocked by writes. Combined with IMMEDIATE transactions, concurrent writers queue properly instead of failing with lock errors. This is fine for:

- ✅ Read-heavy workloads (admin dashboards, content sites)
- ✅ Low-to-moderate write volume (internal tools, small teams)
- ✅ Single-server deployments
- ✅ Background workers and cron jobs alongside web requests

Consider PostgreSQL if you need:
- ❌ Sustained high concurrent write volume beyond single-writer capacity
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

1. **Sustained write contention** — Lock errors persist even with WAL + IMMEDIATE tuning (indicates write volume exceeds single-writer capacity)
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
