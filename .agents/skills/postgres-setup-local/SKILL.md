---
name: postgres-setup-local
description: "Switch a project to Postgres locally — Docker server, psycopg extra, DATABASES config, FTS auto-provision on migrate"
license: MIT
metadata:
  source: "docs/skills/postgres/setup-local.md"
  section: "Database & PostgreSQL"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/postgres/setup-local.md` by `make skills-index` — edit the source, not this file.

# Skill: Set Up PostgreSQL Locally

Switch a SmallStack project from the default SQLite to PostgreSQL for local
development. SmallStack runs on both; nothing in the framework assumes SQLite
**except** that SQLite is the zero-config default. Read
[sqlite-vs-postgres.md](sqlite-vs-postgres.md) before you rely on search or
write data migrations — there are real behavioral differences.

> **TL;DR**
> ```bash
> docker run -d --name ss-pg -e POSTGRES_PASSWORD=postgres \
>   -e POSTGRES_USER=postgres -e POSTGRES_DB=smallstack \
>   -p 5432:5432 postgres:16
> uv sync --extra postgres           # installs psycopg
> # point DATABASES at Postgres (below), then:
> make setup                         # migrate + dev superuser; FTS auto-provisions
> uv run python manage.py search_doctor   # expect backend = postgresql-fts
> ```

## 1. Start a Postgres server

Any Postgres ≥ 12 works; the project is verified on **postgres:16**.

```bash
docker run -d --name ss-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=smallstack \
  -p 5432:5432 \
  postgres:16

# wait until it answers
until docker exec ss-pg pg_isready -U postgres; do sleep 1; done
```

Use a different host port (e.g. `-p 5433:5432`) if 5432 is taken — then set
`PORT` to match in the settings below. (`brew install postgresql@16` /
`apt install postgresql` work too; Docker is just the fastest clean slate.)

## 2. Install the driver

psycopg is an **optional extra**, not a base dependency (SQLite needs nothing):

```bash
uv sync --extra postgres        # or: uv add 'psycopg[binary]'
```

`pyproject.toml` declares it under `[project.optional-dependencies]`:

```toml
postgres = ["psycopg[binary]>=3.1"]
```

> ⚠️ `make setup` / `make test` run `uv sync --extra dev` (or `--all-extras`).
> Plain `--extra dev` will **uninstall** psycopg. Use `uv sync --all-extras`
> (or `--extra postgres`) whenever you run on Postgres locally.

## 3. Point `DATABASES` at Postgres

There's a ready-to-uncomment recipe in `config/settings/development.py`:

```python
# config/settings/development.py — uncomment, comment out the SQLite block above
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "smallstack",
        "USER": "postgres",
        "PASSWORD": "postgres",
        "HOST": "localhost",
        "PORT": "5432",     # match the host port you published
    }
}
```

**Don't want to edit a tracked file?** Create an untracked override and select
it with `DJANGO_SETTINGS_MODULE`:

```python
# config/settings/_pglocal.py   (gitignore or just never commit it)
from .development import *  # noqa: F401,F403
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql", "NAME": "smallstack",
    "USER": "postgres", "PASSWORD": "postgres", "HOST": "localhost", "PORT": "5432",
}}
```
```bash
export DJANGO_SETTINGS_MODULE=config.settings._pglocal
```

## 4. Migrate + run

```bash
make setup        # uv sync + migrate + create_dev_superuser (admin/admin)
make run          # dev server on :8005
```

`make setup` is idempotent. On Postgres, `migrate` does one extra thing for
free: at `post_migrate`, every search-enabled model gets a `search_vector`
column + GIN index **provisioned automatically** (see step 5). No migration to
write.

## 5. Full-text search "just works" — but backfill existing rows

SmallStack's search backend self-provisions on Postgres. After the first
migrate the columns exist; new saves index automatically via signals. Existing
rows (created before the column existed, or loaded via fixtures) need a
one-time backfill:

```bash
uv run python manage.py rebuild_search_index --all
uv run python manage.py search_doctor          # backend should read postgresql-fts
```

If `search_doctor` shows `FallbackBackend`, psycopg isn't installed (step 2) or
`ENGINE` isn't `...postgresql` (step 3). See
[sqlite-vs-postgres.md](sqlite-vs-postgres.md) for why there's no migration and
how the `ensure_index` provisioning works.

## 6. Verify

```bash
uv run python manage.py shell -c "
from django.contrib.auth import get_user_model
from apps.search.registry import search_all
u = get_user_model().objects.get(username='admin')
print(len(search_all('admin', user=u)), 'hits')"   # > 0
```

Zero `FieldDoesNotExist`/`FieldError` in stderr means the column is present and
indexed correctly.

## Teardown

```bash
docker stop ss-pg && docker rm ss-pg      # data is in the container; gone on rm
```

## Related

- [production.md](production.md) — Postgres for production (Kamal, managed, pooling)
- [testing.md](testing.md) — run the test suite on Postgres
- [sqlite-vs-postgres.md](sqlite-vs-postgres.md) — the behavioral differences that bite
- [../database.md](../database.md) — database overview + backups + SQLite tuning
