# Skill: SQLite vs PostgreSQL — the differences that bite

SmallStack runs identically on SQLite and Postgres for *most* code. This skill
catalogues the places where they genuinely diverge — so you don't ship a change
that's green on SQLite and broken on Postgres (the default dev loop is SQLite,
so this is the common failure direction). Read it before touching **search,
data migrations, raw SQL, or order-sensitive queries**.

## Backend dispatch (how the DB choice propagates)

`apps/search/backends/__init__.py:get_backend()` picks the search backend from
`DATABASES['default']['ENGINE']`, cached for the process:

| ENGINE contains | Backend | Engine |
|---|---|---|
| `sqlite` | `SQLiteFTSBackend` | FTS5 virtual table, BM25 ranking |
| `postgresql` / `postgis` | `PostgresFTSBackend` | `tsvector` column + GIN, `ts_rank` |
| anything else | `FallbackBackend` | `__icontains` OR — slow, no ranking/operators |

`search_doctor` prints the active backend. `FallbackBackend` on Postgres means
psycopg isn't installed or `ENGINE` is wrong.

## Full-text search

### Self-provisioning (no migration, by design)

Both FTS backends **own their index structure** and create it at runtime in
`ensure_index()`, hooked to the `post_migrate` signal
(`apps/search/registry.py:ensure_all_indexes`). Neither requires a migration or
a field on the model:

- **SQLite** (`sqlite_fts.py`): `CREATE VIRTUAL TABLE IF NOT EXISTS
  <app>_<model>_search_idx USING fts5(...)` — a separate FTS5 table.
- **Postgres** (`postgres_fts.py`): `ALTER TABLE <table> ADD COLUMN IF NOT
  EXISTS search_vector tsvector` + `CREATE INDEX IF NOT EXISTS ... USING GIN
  (search_vector)` — a column on the model's own table.

Both write/read with **raw SQL** (field values resolved in Python, so `__`
paths work) and re-hydrate results via the ORM.

> **Why no `SearchVectorField` on the model + migration?** It would emit a
> `tsvector` column type that SQLite (the default) can't build, *and* make
> `makemigrations` perpetually want to create the runtime-managed column. Owning
> the index in the backend keeps the **same models working on both databases**
> with zero per-model migration work — for bundled (`User`, `APIToken`) and
> downstream models alike. This is the canonical "find option C" shape: the
> generic mechanism, not a per-model patch.

**Practical consequence:** after switching a project to Postgres, run
`migrate` (provisions columns) then `rebuild_search_index --all` (backfills
existing rows). New rows index automatically via post_save signals.

### Tokenization differs — hyphens are the sharp edge

| Aspect | SQLite FTS5 | Postgres `english` |
|---|---|---|
| Hyphens | splits on `-` (separator) | stores the **compound** lexeme *plus* parts |
| Stemming | porter | english/porter |
| Prefix | `term*` | `term:*` (via `to_tsquery`) |
| Ranking | BM25 (negated; higher=better) | `ts_rank` (higher=better) |

The hyphen case is the one that actually breaks tests. For `alice-needle-zz`:

```
SQLite:    tokens → alice, needle, zz
Postgres:  to_tsvector('english','alice-needle-zz')
           → 'alic' 'alice-needle-zz' 'needl' 'zz'   (compound + parts)
```

So:
- A **single-word** query (`needle`, or the email part of `jean-paul`) matches
  on both — the part-lexemes are present on Postgres too.
- A **hyphenated query fragment** (`needle-zz`) matches on SQLite (splits) but
  **NOT** on Postgres: `plainto_tsquery('english','needle-zz')` →
  `'needle-zz' & 'needl' & 'zz'`, and the compound `needle-zz` isn't in the
  document (whose compound is the full `alice-needle-zz`).

**Rule:** search whole words. If a test needs a shared token across rows, use a
space (`"needle zz"`) not a hyphen — it matches via parts on both backends. See
the comment in `apps/search/tests/test_security.py`
(`test_visibility_filter_scopes_rows_per_user`).

Absolute rank *values* also differ (BM25 vs ts_rank) — never assert on a
specific score, only on ordering/membership.

## Data migrations & `CharField` length

**Postgres enforces `varchar(N)`; SQLite ignores it.** Postgres validates the
length of a `SET`/`INSERT` literal against the column type **even when zero rows
match**. A `RunPython` data migration that assigns an over-length temporary
value passes on SQLite and **fails every fresh Postgres `make setup`**:

```python
# field is CharField(max_length=10)
.update(triggered_by="_scheduler2")   # 11 chars → DataError on Postgres, fine on SQLite
```

This is exactly how migration `0005` shipped broken for 12 releases (SQLite-only
dev loop). **Rule:** keep every value a migration writes within the column's
`max_length`, temp values included; run migrations against Postgres before
tagging.

## Query ordering

Postgres returns rows in **no guaranteed order** without `ORDER BY`; SQLite
often returns insertion order, which masks missing `order_by()`. A test that
asserts `qs[0]` or a sequence without ordering can pass on SQLite and flake on
Postgres (watch for `UnorderedObjectListWarning`). **Rule:** add explicit
`order_by()` anywhere order is asserted or paginated.

## Other divergences

| Area | SQLite | Postgres | Mitigation |
|---|---|---|---|
| String `=` / `LIKE` | case-insensitive for ASCII | **case-sensitive** | use `iexact`/`icontains` when you mean case-insensitive |
| `GROUP BY` / `DISTINCT ON` | lenient | strict (every selected col must be grouped) | follow standard SQL; `distinct('field')` is Postgres-only |
| Booleans / JSON / arrays | emulated | native types | prefer Django field types over raw SQL |
| Concurrent writes | single writer (WAL helps) | true MVCC | Postgres if you need it |
| `make backup` / `backup_db` | ✅ supported | ❌ **SQLite-only** (copies the `.sqlite3` file) | use `pg_dump` / managed backups |

## How to test the search divergence

```bash
# Spin up Postgres (see setup-local.md / testing.md), then:
TEST_DB=postgres TEST_DB_PORT=5433 uv run pytest apps/search -q --no-cov

# Inspect tokenization directly to debug a non-match:
docker exec ss-pg psql -U postgres -d smallstack -At -c \
  "select to_tsvector('english','alice-needle-zz'), plainto_tsquery('english','needle-zz');"

# End-to-end sanity in the shell (expect > 0 hits, no FieldError in stderr):
uv run python manage.py shell -c "
from django.contrib.auth import get_user_model
from apps.search.registry import search_all
u = get_user_model().objects.get(username='admin')
print(len(search_all('admin', user=u)))"
```

A query that returns hits on SQLite but `[]` on Postgres, with no stderr error,
is almost always the **hyphen/tokenization** case above — not a backend bug.

## The "green on SQLite, red on Postgres" checklist

Before tagging a release or merging search/migration/SQL work:

- [ ] Ran the suite with `TEST_DB=postgres` (0 failures)
- [ ] Ran a **from-scratch `migrate` against an EMPTY Postgres** (~1 min) — the
      cheapest gate for the whole transaction-poisoning class: a failed
      statement poisons the entire Postgres transaction ("current transaction
      is aborted"), so the *visible* error is often Django's next statement,
      not the culprit; SQLite carries on and hides the category. Fresh-DB runs
      also order `post_migrate` provisioning AFTER every migration, which
      incremental databases never exercise
- [ ] Any data migration's written values fit the column `max_length`
- [ ] No migration **creates or saves rows of a searchable model** — the
      search index is provisioned at `post_migrate`, and any `except
      Exception` around a DB write is a backend-dependent promise unless the
      write is wrapped in `transaction.atomic()` (a savepoint)
- [ ] Order-sensitive queries/tests have explicit `order_by()`
- [ ] FTS tests search whole words, not hyphenated fragments
- [ ] Case-sensitivity intent is explicit (`iexact`/`icontains`)
- [ ] Backups on Postgres use `pg_dump`, not `make backup`

## Related

- [setup-local.md](setup-local.md) · [production.md](production.md) · [testing.md](testing.md)
- [../search.md](../search.md) — the search opt-in guide (FTS5/PG-FTS, MCP tool)
- [../database.md](../database.md) — database overview, SQLite tuning, backups
