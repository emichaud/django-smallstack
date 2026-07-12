# CLI Reference

Every command-line tool SmallStack provides — `manage.py` commands, Make targets, and system tools — in one place. Use this as a lookup; for narrative how-to-debug-X-with-this-tool, follow the cross-links to the dedicated skill docs.

> **Vibe-coding tip**: If you're working with Claude or another AI agent, point it at `docs/skills/cli-tools.md`. That file is a decision tree from "I need to do X" to "run command Y" — purpose-built for the agent to pick the right tool without scanning every command.

## At a glance

| Category | Tool | One-line purpose |
|---|---|---|
| Setup | `make setup` | Install deps + migrate + create dev superuser |
| Dev | `make run` | Start dev server on port 8005 |
| Test | `make test` | Run pytest with coverage |
| Lint | `make lint` / `make lint-fix` | Ruff check / autofix |
| Diagnose | `make mcp-doctor` / `manage.py api_doctor` | In-process health checks |
| Smoke | `make mcp-test` / `make api-test` | HTTP smoke tests against a running server |
| Auth | `manage.py create_api_token` | Mint a token for a user |
| DB | `make backup` | SQLite backup with retention |
| Search | `manage.py rebuild_search_index` / `search_doctor` | Rebuild FTS index / diagnose search |
| Visual | `manage.py screenshot_auth` + `shot-scraper` | Authenticated browser screenshots |
| CLI | `manage.py sc` (`sc` shim) | Framework CLI: CRUD over any CRUDView (`ls/get/describe/new/set/rm`) + ops verbs (`doctor/backup/token/status/index/commands`) — see [`docs/skills/sc-cli.md`](../../../docs/skills/sc-cli.md) |
| Deploy | `make deploy` / `make logs` | Kamal deploy + tail logs |

---

## `manage.py` commands

All commands run as `uv run python manage.py <name>`. The `uv run` prefix activates the project's `.venv` automatically — there's nothing to install or activate.

### Diagnostics

#### `api_doctor`

Diagnose the REST API surface end-to-end. Same checks as the [`/smallstack/api/` Health page](api-doctor.md).

```bash
uv run python manage.py api_doctor                           # full report + self-test
uv run python manage.py api_doctor --no-self-test            # skip the HTTP self-test
uv run python manage.py api_doctor --json                    # machine-readable
uv run python manage.py api_doctor --check-only              # exit 1 on any FAIL
uv run python manage.py api_doctor --explain                 # dump every registered endpoint
uv run python manage.py api_doctor --explain /api/orders/    # filter to one path
```

| Flag | What it does |
|---|---|
| `--no-self-test` | Skip the in-process token-mint + HTTP roundtrip |
| `--json` | Emit JSON to stdout; composes with `--explain` |
| `--check-only` | Exit non-zero if any check FAILs (for CI) |
| `--explain [PATH]` | Dump endpoint registry — model, URL name, filter/search/ordering fields. Optional path filter |

Use when: setting up SmallStack as an API server, debugging "Swagger is empty," investigating a customer 401 report, or running pre-deploy sanity in CI. See [`api-doctor.md`](api-doctor.md) for the decision tree.

#### `mcp_doctor`

Diagnose the MCP server end-to-end. Same checks as the [`/smallstack/mcp/` Health page](mcp-admin.md).

```bash
uv run python manage.py mcp_doctor                           # full report + self-test
uv run python manage.py mcp_doctor --no-self-test
uv run python manage.py mcp_doctor --json
uv run python manage.py mcp_doctor --check-only
uv run python manage.py mcp_doctor --explain                 # dump every MCP tool's inputSchema
uv run python manage.py mcp_doctor --explain create_ticket   # one tool only
```

| Flag | What it does |
|---|---|
| `--no-self-test` | Skip the test-client JSON-RPC smoke |
| `--json` | Machine-readable output |
| `--check-only` | Exit non-zero on FAIL |
| `--explain [TOOL]` | Dump tool descriptions + inputSchemas — what Claude sees |

Use when: Claude Desktop fails to attach, `tools/list` is unexpectedly empty, you're chasing "Claude doesn't know it can filter by status." See [`mcp-debugging.md`](mcp-debugging.md).

#### `api_smoke`

End-to-end smoke test against a **running** HTTP server (proxy + middleware + WSGI). Where `api_doctor` runs in-process via the test client, this hits the real network. Equivalent to `make api-test`.

```bash
uv run python manage.py api_smoke                            # http://localhost:8005
uv run python manage.py api_smoke --base-url https://prod.example.com
uv run python manage.py api_smoke --user alice               # mint token under specific user
uv run python manage.py api_smoke --endpoint /api/widgets/   # specific endpoint
uv run python manage.py api_smoke --endpoint __skip__        # skip sample call (registry empty)
uv run python manage.py api_smoke --json                     # CI-friendly
uv run python manage.py api_smoke --quiet                    # output only on failure
```

Exit codes: `2` = could not connect, `3` = HTTP error, `4` = response shape unexpected.

#### `mcp_smoke`

End-to-end smoke test for MCP against a running server. Mints a token, runs `tools/list`, calls a sample tool, revokes. Equivalent to `make mcp-test`.

```bash
uv run python manage.py mcp_smoke
uv run python manage.py mcp_smoke --url https://prod.example.com/mcp
uv run python manage.py mcp_smoke --user alice
uv run python manage.py mcp_smoke --tool create_ticket
uv run python manage.py mcp_smoke --json
uv run python manage.py mcp_smoke --quiet
```

### Auth & users

#### `create_api_token`

Mint a token for a user from the CLI. The canonical scripted path — CI, deploy hooks, automation. For interactive use, [the `/smallstack/tokens/` UI](api-tokens.md) is cleaner.

```bash
uv run python manage.py create_api_token alice
uv run python manage.py create_api_token alice --name "CI deploy key"
uv run python manage.py create_api_token alice --access-level readonly
uv run python manage.py create_api_token alice --access-level staff
uv run python manage.py create_api_token bot --access-level auth   # mint+manage tokens
```

| Argument | What it does |
|---|---|
| `username` (positional) | The user the token belongs to |
| `--name NAME` | Human-readable label (default: `"CLI Token"`) |
| `--access-level` | `readonly` (default) / `staff` / `auth` — see [`api-tokens.md`](api-tokens.md) |

Prints the raw key once to stdout — the only chance to capture it. Pipe to a secret manager.

#### `create_dev_superuser`

Create a development superuser from `DEV_SUPERUSER_USERNAME` / `_PASSWORD` / `_EMAIL` env vars (defaults: `admin` / `admin` / `admin@example.com`). **Development only** — refuses to run if `DEBUG=False`.

```bash
uv run python manage.py create_dev_superuser
DEV_SUPERUSER_USERNAME=me DEV_SUPERUSER_PASSWORD=secret uv run python manage.py create_dev_superuser
```

Idempotent: skips if a user with that username already exists.

#### `ensure_superuser`

Production-safe sibling. Reads `DJANGO_SUPERUSER_USERNAME` / `_PASSWORD` / `_EMAIL` and creates the superuser if it doesn't exist. Used by `docker-entrypoint.sh` for first-boot provisioning.

```bash
DJANGO_SUPERUSER_USERNAME=ops DJANGO_SUPERUSER_PASSWORD=$SECRET \
  DJANGO_SUPERUSER_EMAIL=ops@example.com \
  uv run python manage.py ensure_superuser
```

### Data

#### `backup_db`

Atomic SQLite backup with retention pruning. Uses the SQLite `.backup` API — safe to run against a live database (no locks, no missed writes).

```bash
uv run python manage.py backup_db                          # → backups/db-YYYYMMDDTHHMMSS.sqlite3
uv run python manage.py backup_db --keep 30                # prune all but the 30 most recent
uv run python manage.py backup_db --output /tmp/snap.db    # explicit destination
```

| Flag | What it does |
|---|---|
| `--keep N` | Keep only the N most recent backups; delete older ones |
| `--output PATH` | Override destination file path (default: `BACKUP_DIR` setting) |

The web admin at [`/smallstack/backups/`](database-backups.md) wraps this command — same logic, click instead of type.

#### `prune_activity`

Trim the `RequestLog` table to `ACTIVITY_MAX_ROWS` (default: 100k). Run on a schedule to keep the log bounded. The Activity dashboard surfaces a banner when pruning is overdue.

```bash
uv run python manage.py prune_activity
```

No flags — the cap is a setting (`ACTIVITY_MAX_ROWS`). For cron / deploy hooks.

> *Coming soon:* schedule this with the recurring `@scheduled` primitive; until then, wire it to system cron.

### Monitoring

#### `heartbeat`

Run a single heartbeat check (DB connectivity + write/read) and record the result. Powers the `/status/` page and the SLA tracking. Schedule it externally (cron / systemd / Kamal) — a built-in recurring `@scheduled` primitive is **coming soon**.

```bash
uv run python manage.py heartbeat
uv run python manage.py heartbeat --reset-epoch
uv run python manage.py heartbeat --reset-epoch --reset-note "Restored from backup 2026-06-17"
```

| Flag | What it does |
|---|---|
| `--reset-epoch` | Reset the monitoring epoch to now (restarts uptime calculation). Use after a planned restore or migration. |
| `--reset-note NOTE` | Annotate the epoch reset with a reason. Surfaces on the status page. |

See [`uptime-monitoring.md`](uptime-monitoring.md) for cron setup.

#### `maintenance`

Open, close, or list maintenance windows — planned downtime that the status page
shows as "Under maintenance" (not "Down") and the SLA calculation excludes. Use it
for deploys, scripts, and AI/automation. (The staff SLA page has an equivalent form.)

```bash
uv run python manage.py maintenance open --minutes 15 --title "Deploy v1.2.3"
uv run python manage.py maintenance open --start "2026-07-01 02:00" --end "2026-07-01 03:00" --title "DB migration"
uv run python manage.py maintenance close                 # end active windows now (keeps the row)
uv run python manage.py maintenance close --delete-future # also drop not-yet-started windows
uv run python manage.py maintenance list --active --json
```

| Flag | What it does |
|---|---|
| `open` / `close` / `list` | Subcommand (required positional). |
| `--minutes N` | open: window starting now, lasting N minutes (bounded → self-heals). |
| `--start ISO --end ISO` | open: explicit bounds (naive times read in the project timezone). |
| `--title` / `--note` | open: window title (default "Maintenance") / optional note. |
| `--monitor KEY` | Monitor the window applies to (default `site`; e.g. `ep_<slug>`). |
| `--no-sla-exclude` | open: record the window but DON'T exclude it from SLA. |
| `--delete-future` | close: also delete windows that haven't started yet. |
| `--active` | list: only windows active right now. |
| `--json` | Machine-readable output (open/close/list). |

Shared helpers: `apps/heartbeat/maintenance.py`. Wire it into deploys with
`MAINTENANCE_ON_DEPLOY=true` in `.kamal/secrets` (see
[`status-monitors.md`](../../../docs/skills/status-monitors.md)).

### Search

#### `rebuild_search_index`

Rebuild the full-text search index for one or all indexed CRUDViews. Run after a bulk import, a change to searchable fields, or whenever the index drifts from the data.

```bash
uv run python manage.py rebuild_search_index                 # rebuild every indexed model
uv run python manage.py rebuild_search_index support.Ticket  # just one model
uv run python manage.py rebuild_search_index --all           # explicit "all"
```

| Argument | What it does |
|---|---|
| `target` (positional, optional) | Model label (e.g. `support.Ticket`). Omit to rebuild all. |
| `--all` | Rebuild every indexed model. |

Rows are indexed automatically on save via signals — you mainly need this for backfills and drift. For a periodic safety-net rebuild, run it on a schedule.

> *Coming soon:* schedule this with the recurring `@scheduled` primitive; until then, wire it to system cron.

#### `search_doctor`

Diagnose the search subsystem end-to-end — backend, indexed models, `search_fields`, and MCP-tool exposure. The search-side counterpart to `api_doctor` / `mcp_doctor`.

```bash
uv run python manage.py search_doctor
uv run python manage.py search_doctor --explain
uv run python manage.py search_doctor --audit
uv run python manage.py search_doctor --check-only   # CI gate
```

| Flag | What it does |
|---|---|
| `--json` | Machine-readable output. |
| `--check-only` | Exit non-zero if any check FAILs (for CI). |
| `--explain` | Dump every indexed model + its `search_fields` + the MCP tool name. |
| `--audit` | Access audit: every indexed CRUDView grouped by `search_access` level, plus a staff/auth/anonymous audience simulation. |

See [`search.md`](../../../docs/skills/search.md).

#### `sync_help_index`

Sync the help-article search index from the filesystem markdown (the bundled `/help/` docs), so help content is findable in search. Run it after editing help articles. No-ops on a non-SQLite database or when there are zero articles.

```bash
uv run python manage.py sync_help_index
```

### Visual / dev tooling

#### `screenshot_auth`

Generate a Playwright auth-state JSON for `shot-scraper`. Logs in as the first staff user, writes the session cookie to stdout. Pipe to a file, pass to `shot-scraper --auth`.

```bash
uv run python manage.py screenshot_auth > /tmp/auth.json
uv run python manage.py screenshot_auth --domain prod.example.com > /tmp/prod-auth.json

shot-scraper http://localhost:8005/smallstack/ \
  --auth /tmp/auth.json -o /tmp/dash.png --width 1440
```

| Flag | What it does |
|---|---|
| `--domain DOMAIN` | Cookie domain (default: `localhost`) — set when capturing prod |

See [`screenshot-workflow.md`](screenshot-workflow.md) for visual-verification recipes.

---

## Make targets

Every target in the `Makefile`, grouped by purpose. Run `make help` (or just `make`) for the same list with one-liners.

### Setup

| Target | What it does |
|---|---|
| `make setup` | One-time: `uv sync`, migrate, create dev superuser, run check |
| `make help` | Display all targets (default) |

### Dev loop

| Target | What it does |
|---|---|
| `make run` | Start dev server on port 8005 (override: `PORT=8000 make run`) |
| `make services` | Run the worker + heartbeat locally (`utils/dev_services.sh`); `ARGS="--interval 5 --smoke"` to pass flags |
| `make migrate` | Apply pending migrations |
| `make migrations` | Create new migrations after model changes |
| `make shell` | Open `shell_plus` with auto-imports |
| `make superuser` | Create the dev superuser via `create_dev_superuser` |

### Quality

| Target | What it does |
|---|---|
| `make test` | Run pytest with coverage |
| `make coverage` | Run tests + open `htmlcov/index.html` |
| `make lint` | Run ruff |
| `make lint-fix` | Run ruff with `--fix` |

### Diagnostics

| Target | What it does |
|---|---|
| `make mcp-doctor` | `manage.py mcp_doctor` — in-process MCP checks |
| `make mcp-test` | `manage.py mcp_smoke` — HTTP smoke against the running server |
| `make api-test` | `manage.py api_smoke` — HTTP smoke for `/api/*` |

### Data

| Target | What it does |
|---|---|
| `make backup` | `manage.py backup_db` |

### Static & Docker

| Target | What it does |
|---|---|
| `make collectstatic` | Gather static files (production prep) |
| `make docker-up` | Build + start Docker containers |
| `make docker-down` | Stop Docker containers |

### Deployment (Kamal)

| Target | What it does |
|---|---|
| `make deploy` | `kamal deploy` |
| `make logs` | `kamal app logs` |

### Tooling

| Target | What it does |
|---|---|
| `make screenshot-auth` | Wraps `manage.py screenshot_auth` → `/tmp/auth.json` |
| `make optimize-images` | `pngquant` over `static/` PNGs (requires `brew install pngquant`) |
| `make clean` | Remove `__pycache__/`, `.pyc`, test caches |

Full prose narrative for each target: [`make-commands.md`](make-commands.md).

---

## System tools

Tools you install once via `uv tool install`, available across all SmallStack projects.

### `shot-scraper`

Headless browser screenshots from the CLI. Used for visual verification of UI changes — see [`screenshot-workflow.md`](../docs/skills/screenshot-workflow.md).

```bash
uv tool install shot-scraper
shot-scraper install                                          # one-time Chromium download

# Basic screenshot
shot-scraper http://localhost:8005/ -o /tmp/home.png --width 1440

# Light mode
shot-scraper http://localhost:8005/ -o /tmp/home-light.png \
  --width 1440 \
  --javascript "document.documentElement.setAttribute('data-theme','light')"

# Authenticated (using screenshot_auth)
uv run python manage.py screenshot_auth > /tmp/auth.json
shot-scraper http://localhost:8005/smallstack/ \
  --auth /tmp/auth.json -o /tmp/dash.png

# Wait for animations
shot-scraper http://localhost:8005/ -o /tmp/home.png --wait 1500

# Specific element
shot-scraper http://localhost:8005/activity/ -s ".card:first-child" -o /tmp/card.png
```

### `ruff`

Already wired up via `make lint` / `make lint-fix`. Run directly when you want format + check:

```bash
uv run ruff check .                # lint
uv run ruff check --fix .          # lint + autofix imports & easy issues
uv run ruff format .               # format only
```

### `uv`

The project package manager. SmallStack assumes `uv ≥ 0.4`.

```bash
uv sync                            # install / update dependencies from uv.lock
uv run python manage.py <cmd>      # run any Python with the project's venv
uv tool install <tool>             # install a CLI tool globally (shot-scraper, etc.)
uv lock                            # regenerate the lock file after pyproject changes
```

---

## Exit codes worth knowing

| Code | Where |
|---|---|
| `0` | Success |
| `1` | Generic failure or `--check-only` saw a FAIL row |
| `2` | `api_smoke` / `mcp_smoke`: could not reach the server |
| `3` | `api_smoke`: HTTP error from the server |
| `4` | `api_smoke`: response shape was unexpected |

Useful in CI:

```bash
make lint && make test && uv run python manage.py api_doctor --check-only
```

---

## Related

- [`make-commands.md`](make-commands.md) — narrative tour of Make targets
- [`api-doctor.md`](api-doctor.md) — Health/Activity pages + decision tree
- [`mcp-admin.md`](mcp-admin.md) — MCP admin pages
- [`api-tokens.md`](api-tokens.md) — token mint/reveal/revoke
- [`uptime-monitoring.md`](uptime-monitoring.md) — heartbeat cron setup
- [`screenshot-workflow.md`](../docs/skills/screenshot-workflow.md) — visual verification recipes
- [`docs/skills/cli-tools.md`](../docs/skills/cli-tools.md) — AI-agent decision tree
