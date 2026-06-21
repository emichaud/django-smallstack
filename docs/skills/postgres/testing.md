# Skill: Test on PostgreSQL

The suite runs on in-memory SQLite by default (fast — ~18s). To catch
Postgres-only regressions (varchar enforcement, FTS tokenization, query
ordering — see [sqlite-vs-postgres.md](sqlite-vs-postgres.md)) you run the same
suite against a real Postgres. This skill is how.

> **TL;DR**
> ```bash
> docker run -d --name ss-pg-test -e POSTGRES_PASSWORD=postgres \
>   -e POSTGRES_USER=postgres -p 5433:5432 postgres:16
> uv sync --all-extras                                   # psycopg must be present
> TEST_DB=postgres TEST_DB_PORT=5433 uv run pytest       # NOT `make test`
> ```

## The `TEST_DB` switch

`config/settings/test.py` selects the engine from an env var:

```python
if os.environ.get("TEST_DB") == "postgres":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME":     os.environ.get("TEST_DB_NAME", "smallstack_test"),
        "USER":     os.environ.get("TEST_DB_USER", "postgres"),
        "PASSWORD": os.environ.get("TEST_DB_PASSWORD", "postgres"),
        "HOST":     os.environ.get("TEST_DB_HOST", "localhost"),
        "PORT":     os.environ.get("TEST_DB_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
```

Unset → SQLite in-memory (the default). `TEST_DB=postgres` → Postgres, with
host/port/name/user/password each overridable. The Postgres role needs
`CREATEDB` (the default `postgres` superuser has it) — Django creates and drops
a `test_<NAME>` database around the run.

## Running it

```bash
# psycopg must be installed — `make test` uses `--extra dev` and will NOT have it
uv sync --all-extras

TEST_DB=postgres TEST_DB_PORT=5433 uv run pytest             # whole suite
TEST_DB=postgres TEST_DB_PORT=5433 uv run pytest apps/search # one app
TEST_DB=postgres TEST_DB_PORT=5433 uv run pytest -q --no-cov # faster, no coverage
```

`DJANGO_SETTINGS_MODULE=config.settings.test` is already wired via pyproject
`addopts`/ini, so you don't pass it.

> ⚠️ **`make test` can't do Postgres.** Its `uv sync --extra dev` step
> uninstalls psycopg. Run `pytest` directly with `uv sync --all-extras` (or
> `--extra postgres`) first.

## What to expect

- **Search columns auto-exist in the test DB.** `post_migrate` runs the
  backend's `ensure_index` during test-database creation, so the
  `search_vector` columns + GIN indexes are provisioned automatically — no
  fixture or manual step. (Same self-provisioning as dev/prod.)
- **Counts differ by design.** A clean run is roughly: SQLite **884 passed / 7
  skipped**, Postgres **875 passed / 16 skipped**. The extra skips are
  SQLite-only tests (e.g. `apps/search/tests/test_sqlite_backend.py`) that gate
  on the active backend. **Zero failures on either** is the bar.
- **Postgres is slower** (~110s vs ~18s) — real DB create/migrate/teardown vs
  in-memory. Use `--no-cov` and target specific apps while iterating.

## Verifying a change on both backends

When you touch search, migrations, raw SQL, or anything ordering-sensitive, run
both before committing:

```bash
uv run pytest -q --no-cov                                  # SQLite
TEST_DB=postgres TEST_DB_PORT=5433 uv run pytest -q --no-cov  # Postgres
```

If a test passes on SQLite but fails on Postgres, it's almost always one of the
documented divergences (hyphenated FTS fragments, unordered querysets, varchar
length, case sensitivity) — see [sqlite-vs-postgres.md](sqlite-vs-postgres.md).
Fix the test to be **backend-neutral** (don't weaken the assertion, and don't
special-case the backend in product code unless the behavior itself is wrong).

## CI matrix

CI runs both engines so Postgres-only regressions can't ship — shipped at
**`.github/workflows/test.yml`**. The `test` job uses a matrix over
`TEST_DB` (`""` = SQLite, `postgres`) with Postgres provided by a service
container; a separate `lint` job runs ruff. The shape:

```yaml
# .github/workflows/test.yml (excerpt — see the file for the full version)
jobs:
  test:
    strategy:
      matrix:
        include:
          - { label: sqlite,   test_db: "" }
          - { label: postgres, test_db: postgres }
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_USER: postgres, POSTGRES_PASSWORD: postgres }
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s
          --health-timeout 5s --health-retries 5
    env:
      TEST_DB: ${{ matrix.test_db }}
      TEST_DB_HOST: localhost
      TEST_DB_PORT: "5432"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with: { python-version: "3.13" }
      - run: uv sync --all-extras
      - run: uv run pytest -q --no-cov
```

## Teardown

```bash
docker stop ss-pg-test && docker rm ss-pg-test
```

## Related

- [sqlite-vs-postgres.md](sqlite-vs-postgres.md) — *why* tests diverge; the gotcha catalogue
- [setup-local.md](setup-local.md) — local Postgres for manual verification
- [../development-workflow.md](../development-workflow.md) — branching, coverage, commit style
