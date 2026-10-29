---
name: postgres-production
description: "Postgres in production — driver in the image, DATABASE_URL, CONN_MAX_AGE/PgBouncer, Kamal accessory, managed services, deploy-time search backfill, pg_dump backups (NOT make backup)"
license: MIT
metadata:
  source: "docs/skills/postgres/production.md"
  section: "Database & PostgreSQL"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/postgres/production.md` by `make skills-index` — edit the source, not this file.

# Skill: PostgreSQL in Production

Run a SmallStack deployment on PostgreSQL. This covers the production-only
concerns that local setup ([setup-local.md](setup-local.md)) skips: getting the
driver into the image, connection reuse/pooling, the deploy-time steps that
search needs, and how backups differ from the bundled SQLite system.

## Decide: do you even need Postgres?

SmallStack's SQLite config (WAL + `transaction_mode=IMMEDIATE`, see
[../database.md](../database.md)) handles real production traffic for
single-server, read-heavy, or small-team apps. Switch to Postgres when you hit:

- persistent `database is locked` under concurrent writes,
- a need for read replicas / horizontal scale / a managed DB tier,
- multiple app servers (SQLite is one-file-one-host).

If none of those apply, staying on SQLite is a valid production choice, not a
shortcut.

## 1. Get psycopg into the production image

The `postgres` extra must be installed at build time — production won't have it
otherwise (it's not a base dependency):

```dockerfile
# Dockerfile — install with the postgres extra
RUN uv sync --frozen --extra postgres
```

For Kamal/Docker Compose builds that run `uv sync --all-extras`, it's already
included.

## 2. Configure `DATABASES`

**`DATABASE_URL` (recommended)** — one env var, clean switching. `base.py`
parses it and falls back to SQLite when unset:

```python
# config/settings/base.py
import os
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    url = urlparse(DATABASE_URL)
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": url.path[1:], "USER": url.username, "PASSWORD": url.password,
        "HOST": url.hostname, "PORT": url.port or 5432,
        "CONN_MAX_AGE": 60,            # reuse connections for 60s (see §4)
        "CONN_HEALTH_CHECKS": True,    # Django 4.1+: validate reused conns
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": config("DATABASE_PATH", default="/app/data/db.sqlite3"),
        "OPTIONS": SQLITE_OPTIONS,
    }}
```

```bash
# .kamal/secrets or the host env
DATABASE_URL=postgres://postgres:STRONG_PASSWORD@db:5432/smallstack
```

## 3. Deploy-time steps (don't skip the search backfill)

Every deploy must run migrations; the **first** switch to Postgres also needs a
one-time search backfill, because the `search_vector` columns are created at
`migrate` but existing rows aren't indexed until you rebuild:

```bash
uv run python manage.py migrate                      # provisions FTS columns + GIN indexes
uv run python manage.py rebuild_search_index --all   # one-time after switch / data import
uv run python manage.py search_doctor                # confirm postgresql-fts
```

After that, signals keep the index current on every save — no recurring step.
(There is no migration to write for search; the backend self-provisions. See
[sqlite-vs-postgres.md](sqlite-vs-postgres.md).)

**Keep `rebuild_search_index --all` OFF the hot deploy path.** It's a one-off
(first switch / bulk import), not a per-deploy step — running it every deploy
thrashes the DB and gets killed by the next redeploy. What *does* belong on
every deploy is the cheap stats refresh, which the container entrypoint already
runs for you:

```bash
uv run python manage.py analyze_search_index   # fast; keeps FTS on the GIN index
```

Skipping it after a large backfill is the classic "search was instant in dev,
crawls in prod" bug: with stale stats the planner seq-scans `search_vector @@ q`
until autovacuum catches up. If search is ever slow or empty in prod and you
can't reach `psql`, run **`manage.py search_diagnose "<query>"`** (or the
staff page `/smallstack/search/diagnostics/`) — it reports per-table health, app
timing, and a live `EXPLAIN` verdict (Seq Scan vs GIN). Remember that **bulk
writes bypass the index** — call `apps.search.reindex_instances(...)` after any
`bulk_create` / `bulk_update` / `.update()` (see [search.md](../search.md)).

## 4. Connection management

Each Django request opens a DB connection. On Postgres that's more expensive
than SQLite's in-process file handle.

- **`CONN_MAX_AGE`** (set in §2) reuses a connection across requests instead of
  reconnecting each time. 60s is a safe default.
- **PgBouncer** for high concurrency or many app workers — pool in
  `transaction` mode and point `DATABASE_URL` at the bouncer:

```yaml
# docker-compose.yml / deploy.yml accessory
pgbouncer:
  image: edoburu/pgbouncer
  environment:
    DATABASE_URL: postgres://postgres:PASSWORD@db:5432/smallstack
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 100
  ports: ["6432:5432"]
```

> With PgBouncer in `transaction` mode, avoid `CONN_MAX_AGE` > 0 on the Django
> side (let the bouncer own pooling) and avoid session-scoped server state.

## 5. Kamal accessory

```yaml
# deploy.yml
accessories:
  db:
    image: postgres:16-alpine
    host: <your-host-ip>
    env:
      secret: [POSTGRES_PASSWORD]
      clear:
        POSTGRES_DB: smallstack
        POSTGRES_USER: postgres
    directories:
      - data:/var/lib/postgresql/data    # persist across redeploys
    ports: ["5432:5432"]
```

```bash
kamal accessory boot db
kamal accessory exec db "psql -U postgres -d smallstack"
```

## 6. Managed services

For production, a managed Postgres removes backup/patching/HA toil:

| Provider | Service | Notes |
|---|---|---|
| Neon | Serverless Postgres | free tier, autoscaling, branching |
| Supabase | Postgres | free tier, includes auth/storage you can ignore |
| DigitalOcean | Managed Databases | from ~$15/mo, automated backups |
| AWS | RDS Postgres | mature, VPC integration |
| Railway | Postgres | usage-based |

Set `DATABASE_URL` to the provider's connection string and you're done.

## 7. Backups — NOT `make backup`

> ⚠️ **The bundled backup system (`make backup`, `backup_db`, `/backups/`) is
> SQLite-only.** It snapshots the `.sqlite3` file. On Postgres it does not back
> up your data.

On Postgres use `pg_dump` (or your managed provider's backups):

```bash
pg_dump -h <host> -U postgres smallstack > backup.sql       # backup
psql -h <host> -U postgres smallstack < backup.sql          # restore
# Kamal:
kamal accessory exec db "pg_dump -U postgres smallstack" > backup.sql
```

Managed services handle this automatically (point-in-time recovery, scheduled
snapshots) — prefer them over rolling your own.

## Checklist

- [ ] `uv sync --extra postgres` in the image build
- [ ] `DATABASE_URL` set; `CONN_MAX_AGE`/`CONN_HEALTH_CHECKS` configured
- [ ] deploy runs `migrate`; first switch also runs `rebuild_search_index --all`
- [ ] `search_doctor` shows `postgresql-fts`
- [ ] backups via `pg_dump`/managed service (NOT `make backup`)
- [ ] persistent volume for self-hosted `db` accessory

## Related

- [setup-local.md](setup-local.md) — get it running locally first
- [testing.md](testing.md) — verify on Postgres before you deploy
- [sqlite-vs-postgres.md](sqlite-vs-postgres.md) — behavioral differences
- [../kamal-deployment.md](../kamal-deployment.md) · [../docker-deployment.md](../docker-deployment.md)
