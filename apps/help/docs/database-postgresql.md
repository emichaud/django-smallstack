---
title: PostgreSQL Database
description: Scaling beyond SQLite with PostgreSQL
---

# PostgreSQL Database

When your application outgrows SQLite, **PostgreSQL** is the natural next step. It's the most popular database choice for Django applications in production, offering advanced features, better concurrency, and horizontal scaling options.

> **See also:** [SQLite Database](/help/database-sqlite/) for why SQLite is a great starting point.

## When to Choose PostgreSQL

### Signs You've Outgrown SQLite

| Symptom | What's Happening |
|---------|------------------|
| "database is locked" errors | Too many concurrent writes |
| Slow complex queries | Need better query optimization |
| Team scaling issues | Multiple developers need write access |
| Feature limitations | Need full-text search, JSONB, arrays |

### PostgreSQL Strengths

- **Concurrent writes** — Multiple connections can write simultaneously
- **Advanced data types** — JSONB, arrays, ranges, full-text search
- **Horizontal scaling** — Read replicas, connection pooling
- **Ecosystem** — PostGIS for geospatial, pg_vector for AI embeddings
- **Mature tooling** — Excellent backup, monitoring, and management tools

## Local Development Setup

### Option 1: Docker Compose (Recommended)

Add PostgreSQL to your local development environment:

```yaml
# docker-compose.yml
services:
  web:
    build: .
    ports:
      - "8010:8010"
    environment:
      - DATABASE_URL=postgres://postgres:postgres@db:5432/smallstack
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: smallstack
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### Option 2: Standalone Docker Container

Run PostgreSQL without modifying docker-compose:

```bash
# Start PostgreSQL container
docker run --name postgres-dev \
  -e POSTGRES_DB=smallstack \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  -d postgres:16-alpine

# Verify it's running
docker ps | grep postgres

# Connect with psql
docker exec -it postgres-dev psql -U postgres -d smallstack
```

### Option 3: Native Installation

**macOS (Homebrew):**
```bash
brew install postgresql@16
brew services start postgresql@16
createdb smallstack
```

**Ubuntu/Debian:**
```bash
sudo apt install postgresql postgresql-contrib
sudo -u postgres createdb smallstack
```

## Django Configuration

### Install the Driver

Add `psycopg` to your dependencies:

```bash
uv add psycopg[binary]
```

Or add to `pyproject.toml`:
```toml
dependencies = [
    "psycopg[binary]>=3.1",
    # ... other dependencies
]
```

### Update Settings

**Option A: Environment Variable (Recommended)**

In `config/settings/base.py`:

```python
import os
from urllib.parse import urlparse

# Database configuration
# SQLite is the default; set DATABASE_URL for PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Parse DATABASE_URL for PostgreSQL
    url = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": url.path[1:],  # Remove leading slash
            "USER": url.username,
            "PASSWORD": url.password,
            "HOST": url.hostname,
            "PORT": url.port or 5432,
        }
    }
else:
    # Default to SQLite
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "data" / "db.sqlite3",
        }
    }
```

**Option B: Direct Configuration**

In `config/settings/production.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "smallstack"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}
```

### Environment Variables

Add to your `.env` file:

```bash
# For DATABASE_URL approach
DATABASE_URL=postgres://postgres:your-password@localhost:5432/smallstack

# Or individual variables
POSTGRES_DB=smallstack
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-secure-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

## Migrating from SQLite

### Step 1: Export Data from SQLite

```bash
# Create a JSON dump of all data
uv run python manage.py dumpdata --natural-foreign --natural-primary -o data_dump.json
```

### Step 2: Set Up PostgreSQL

Start your PostgreSQL instance and update your environment variables.

### Step 3: Run Migrations

```bash
# Apply migrations to the new database
uv run python manage.py migrate
```

### Step 4: Import Data

```bash
# Load the data into PostgreSQL
uv run python manage.py loaddata data_dump.json
```

### Step 5: Verify

```bash
# Check the data
uv run python manage.py shell
>>> from django.contrib.auth import get_user_model
>>> get_user_model().objects.count()
```

## Production Deployment

### With Kamal

Add PostgreSQL as an accessory in `deploy.yml`:

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

Update your secrets in `.kamal/secrets`:

```bash
POSTGRES_PASSWORD=your-secure-production-password
DATABASE_URL=postgres://postgres:your-secure-production-password@localhost:5432/smallstack
```

### Managed PostgreSQL Services

For production, consider managed services:

| Provider | Service | Starting Price |
|----------|---------|----------------|
| Digital Ocean | Managed Databases | $15/month |
| AWS | RDS PostgreSQL | ~$15/month |
| Supabase | PostgreSQL | Free tier available |
| Neon | Serverless Postgres | Free tier available |
| Railway | PostgreSQL | Usage-based |

**Advantages of managed services:**
- Automated backups
- Point-in-time recovery
- Automatic updates
- Monitoring included

## PostgreSQL Best Practices

### Connection Pooling

For production, use connection pooling to manage database connections efficiently:

```python
# In production settings
DATABASES = {
    "default": {
        # ... connection details
        "CONN_MAX_AGE": 60,  # Keep connections open for 60 seconds
        "CONN_HEALTH_CHECKS": True,  # Django 4.1+
    }
}
```

For high-traffic applications, consider **PgBouncer**:

```yaml
# docker-compose.yml addition
pgbouncer:
  image: edoburu/pgbouncer
  environment:
    DATABASE_URL: postgres://postgres:password@db:5432/smallstack
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 100
  ports:
    - "6432:5432"
```

### Backups

**Managed services** handle this automatically. For self-hosted:

```bash
# Backup
pg_dump -h localhost -U postgres smallstack > backup.sql

# Restore
psql -h localhost -U postgres smallstack < backup.sql
```

### Monitoring

Check database size and performance:

```sql
-- Database size
SELECT pg_size_pretty(pg_database_size('smallstack'));

-- Table sizes
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- Active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = 'smallstack';
```

## Quick Reference

| Task | Command |
|------|---------|
| Connect to database | `psql -h localhost -U postgres -d smallstack` |
| List tables | `\dt` (in psql) |
| Describe table | `\d table_name` (in psql) |
| Backup | `pg_dump -U postgres smallstack > backup.sql` |
| Restore | `psql -U postgres smallstack < backup.sql` |
| Django shell | `uv run python manage.py dbshell` |

### Docker Commands

```bash
# Start PostgreSQL
docker-compose up -d db

# Access psql
docker-compose exec db psql -U postgres -d smallstack

# View logs
docker-compose logs db
```

### Kamal Commands

```bash
# Access PostgreSQL container
kamal accessory exec db "psql -U postgres -d smallstack"

# View database logs
kamal accessory logs db
```

## Further Reading

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Django Database Documentation](https://docs.djangoproject.com/en/stable/ref/databases/)
- [psycopg3 Documentation](https://www.psycopg.org/psycopg3/docs/)
