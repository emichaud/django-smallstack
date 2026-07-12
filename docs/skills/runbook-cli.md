# Runbook CLI — browse and edit runbook pages from the shell

`manage.py runbook` is a **unix-style CLI** over the runbook document service. It's the
fourth thin skin over `smallstack_runbook.service` (alongside the web UI, REST, and MCP),
built so agents and humans can list, read, create, update, and organize runbook pages from
a terminal — and, crucially, **pipe stdin straight into a page**.

```bash
uv run python manage.py runbook ls                                   # list runbooks
echo "# Report" | uv run python manage.py runbook write ops/report   # body from stdin
uv run python manage.py api_doctor --json | uv run python manage.py runbook write ops/api-health --title "API Health"
```

The `smallstack-runbook` package installs an **`rb` console script** into the project
venv, so you can drop the `uv run python manage.py` boilerplate:

```bash
uv run rb ls          # or just `rb ls` inside an activated venv
```

`rb` finds the project's `manage.py` by walking up from the current directory, so it
works anywhere in the tree. If `rb` isn't found, run `uv sync` to register the entry
point. This doc uses `rb` for brevity; `uv run python manage.py runbook` is identical.
The canonical reference ships with the package at `smallstack-runbook/docs/cli.md`.

## The mental model (unix ⇄ runbook)

| Unix | Runbook | Addressed by |
|---|---|---|
| directory | Runbook | slug (`ops`) |
| sub-directory | Section | slug within a runbook (`ops/backups` in `ls`/`toc`) |
| file | Document ("page") | `runbook/key` — or `--uid` for the canonical, move-proof address |
| file contents | the current version's markdown | — |
| file history | the DocumentVersion chain | — |

Pages are **flat within sections** — there's no nested-page tree. A page's outline comes
from its markdown headings, not the database.

**Path parsing differs by verb** (exactly like unix `ls` vs `cat`): for **listing** verbs
(`ls`, `toc`) the path is `runbook` or `runbook/section`; for **page** verbs (`cat`, `write`,
`cp`, `rm`, `restore`, `mv`, `revert`, `log`, `stat`) it's `runbook/key`. An **earlier
version** is addressed by appending `@<n>`: `cat ops/backup@3`. Every verb takes `--json`;
failures exit non-zero.

## Verbs

| Verb | Does | Key flags |
|---|---|---|
| `ls [runbook[/section]]` | No arg → runbooks + page counts. With a runbook → its pages. | `--all` (incl. archived), `--source`, `--doc-type`, `-q/--query`, `--json` |
| `toc <runbook>` | Table of contents: sections → pages (sectionless grouped last). | `--all`, `--json` |
| `find <query>` | **Ranked** full-text search across all runbooks (BM25 via the shared search engine; substring fallback if `apps.search` is absent). | `--limit`, `--json` |
| `cat <runbook>/<key>[@N]` | Print the page's **raw markdown** to stdout (pipe-clean). `@N` / `--version N` reads an earlier version. | `--uid`, `--version`, `--json` (metadata + body) |
| `write <runbook>/<key>` | Create **or** update a page. Body from **stdin** (default) or `-f FILE`. | `--title`, `--section`, `--mode`, `--expected-version`, `--source`, `--doc-type`, `--locked/--unlocked`, `--user`, `--bypass-lock`, `--json` |
| `cp <src> <dest>` | Duplicate a page (`dest` = `runbook/key`); the copy gets its **own** images. Auto-creates the dest runbook. | `-f/--force` (overwrite), `--section`, `--title`, `--uid`, `--user`, `--json` |
| `rm <runbook>/<key>` | Archive (recoverable) by default. | `--force` (hard-delete), `--uid`, `--user`, `--bypass-lock`, `--json` |
| `restore <runbook>/<key>` | Un-archive a soft-deleted page (reverse of `rm`). | `--uid`, `--user`, `--bypass-lock`, `--json` |
| `mv <src> [dest]` | Re-place a page. `dest` = `runbook[/section]`; `-` or omitted **detaches** it. | `--section`, `--uid`, `--user`, `--bypass-lock`, `--json` |
| `revert <runbook>/<key> --to N` | Roll back to version `N` by snapshotting it as a **new** head (history preserved). | `--to` (required), `--uid`, `--user`, `--bypass-lock`, `--json` |
| `log <runbook>/<key>` | Version history, newest first. | `--uid`, `--json` |
| `stat <runbook>/<key>` | Page metadata (uid, version, source, locked, …) **without** the body. | `--uid`, `--json` |
| `mkdir <runbook>[/section]` | Create an empty runbook (and optionally a section). Idempotent. | `--name`, `--description`, `--json` |
| `sections <runbook>` | List sections; `--create SLUG` adds one. | `--create`, `--name`, `--order`, `--json` |
| `publish <runbook>` / `unpublish <runbook>` | Toggle a runbook's public flag (public = any signed-in user may read; editing stays owner/staff). | `--json` |

### `write` in depth — the create-or-update workhorse

`write` is an idempotent upsert (it wraps `service.put_document`). `--mode` controls what
happens **when the page already exists**:

| `--mode` | Effect |
|---|---|
| `new_version` (default) | Snapshot a new version; history grows. |
| `overwrite` | Replace the head content in place; version number unchanged. |
| `append` | Concatenate to the head content in place. |
| `fail` | Error if the page already exists. |

- **Body input**: stdin by default; `-f path.md` to read a file (`-f -` also = stdin).
- **`--title`** defaults to the key on create; on update it's left unchanged unless passed.
- **`--expected-version N`** is an optimistic lock — errors with a non-zero exit if the head moved.
- **Auto-creates** a missing runbook (and `--section`) `mkdir -p`-style. Pass
  `--no-create-runbook` to error instead.

### Versions & recovery

Every `write` (in `new_version` mode) snapshots history, and the CLI can read and roll it back:

```bash
rb log ops/backup                # list versions, newest first
rb cat ops/backup@3              # read version 3's markdown (does not change the head)
rb revert ops/backup --to 3      # roll back — writes v3's content as a NEW head version
```

`revert` never rewrites history; it appends a fresh version whose body equals the old one, so
the rollback is itself auditable and reversible. Deletion is recoverable the same way: `rm`
soft-**archives** (hidden from `ls`/search but intact), and `restore` un-archives it. Only
`rm --force` is irreversible.

## Piping — the whole point

Every read verb writes clean output and `write` reads stdin, so pages compose with any tool:

```bash
# Turn a diagnostic into a living doc
rb log ops/backup-report --json | jq '.[0]' | rb write ops/last-backup --title "Last backup"

# Copy a page
rb cat ops/backup-report | rb write archive/backup-report --title "Backup (archived)"

# Capture command output as a report
git log --oneline -20 | rb write ops/recent-commits --title "Recent commits" --source git
```

## JSON for programmatic use

Every read/list verb takes `--json`, emitting the service dataclasses
(`DocumentSummary` / `DocumentResult`) verbatim — the same shapes the REST API returns. Use
it whenever an agent needs to parse rather than display:

```bash
rb ls ops --json          # [ {key, title, version, source, updated_at, …}, … ]
rb stat ops/report --json # single DocumentResult (content_markdown is null)
rb toc ops --json         # {runbook, sections:[{slug, documents:[…]}], sectionless:[…]}
```

## Provenance, actors, and locking

- Every write records **`via="cli"`** plus whatever `--source` you pass (a free-text
  provenance label like `git`, `cron`, `smoke`).
- **`--user USERNAME`** acts as that user (needed to write a **locked** doc as a superuser).
  Default actor is anonymous.
- **Locked** (managed / shipped) docs reject writes unless you're a superuser (`--user`) or
  pass **`--bypass-lock`**. This mirrors REST/MCP exactly — the check lives in the service.

## Errors

Every `service` error (not-found, version conflict, locked, already-exists) surfaces as a
`CommandError` with a **non-zero exit**, so a broken step fails a pipeline loudly instead of
silently writing garbage.

## When to reach for which surface

- **CLI (`runbook`)** — shell workflows, piping command output into docs, quick agent edits.
- **`smallstack_runbook.service`** — from Python (signals, tasks, seeds).
- **REST `api/documents/…`** — HTTP from other services.
- **MCP `runbook_*` tools** — Claude / MCP clients.
- **`export_runbook` / `import_runbook`** — ship an app's docs as a bundle.

All of them are thin skins over the same service, so semantics (versioning, locking,
provenance, events) are identical. See [`runbook-documents.md`](runbook-documents.md) for the
full picture.
