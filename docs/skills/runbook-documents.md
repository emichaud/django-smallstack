# Runbook & dynamic documents — driving docs from web, service, MCP, REST, CLI, and bundles

**Read this** before you touch runbook documents any way other than clicking around the UI — before you write to them from code, expose them to an agent, script a sync, or ship an app's help docs. The runbook app is **dynamic-documents plumbing**: versioned markdown documents with images, retention, events, and CRUD over every transport. The single rule that keeps you out of trouble: **every write goes through `smallstack_runbook.service` — never poke the models directly.** That's what keeps versioning, provenance, locking, and events identical no matter who's writing.

> **Prerequisites**: for shipped behavior + defaults read [`../../DYNAMIC-DOCUMENTS-FEATURES.md`](../../DYNAMIC-DOCUMENTS-FEATURES.md) (the source of truth). The original design rationale in [`../../packages/smallstack-runbook/docs/dynamic-documents.md`](../../packages/smallstack-runbook/docs/dynamic-documents.md) is **historical / pre-implementation** — useful for the "why," but out of date on names (`external_id`→`uid`) and missing locking. For UI work on document pages read [`modern-dark-theme.md`](modern-dark-theme.md); for the management-command habit read [`cli-tools.md`](cli-tools.md).

## The mental model

| Term | What it is |
|---|---|
| **Runbook** | A named container / namespace for related documents (slug-addressed). |
| **Section** | An ordered grouping inside a runbook. Optional — docs can be sectionless. |
| **Document** | Logical identity: a stable **uid**, an optional `(runbook, key)` alias, a `current_version` pointer, and denormalized head fields (`title`, `content_text`, `version`). |
| **DocumentVersion** | An immutable content snapshot. History only ever grows. |
| **DocumentImage** | An image attached to the *logical* Document, so it survives across versions. |

**Identity**: `uid` (a UUID) is the canonical, container-independent address. `(runbook, key)` is a convenient human alias with a partial-unique constraint. A document can be **detached** (runbook/key cleared) and still be addressed by uid — identity outlives the container.

## Pick your surface

| You want to… | Use |
|---|---|
| Let a human read/write docs in the browser | The web UI at `/smallstack/runbook/` |
| Write/read docs **from Python** (signals, tasks, seeds) | `smallstack_runbook.service` |
| Let **Claude / an MCP client** read & write docs | The `runbook_*` MCP tools |
| Browse/edit docs **from a shell** (pipe stdin into a page) | The `manage.py runbook` CLI ([`runbook-cli.md`](runbook-cli.md)) |
| Integrate over **HTTP** (scripts, other services) | The REST endpoints under `api/documents/…` |
| **Ship an app's help docs** with the app | `export_runbook` / `import_runbook` bundles |
| Populate sample or first-run content | `seed_runbook` / `seed_runbook_docs` |

Everything below the UI is a **thin skin over the service** — same semantics everywhere.

---

## The service layer (the one write path)

`from smallstack_runbook import service`

**Keyed ops** (idempotent, addressed by `(runbook, key)` — this is what MCP/REST/CLI use):

```python
service.put_document("ops", "backup-report", body=md, title="Backup Report",
                     on_exists="overwrite", source="cron")          # create-or-update
service.get_document("ops", "backup-report", with_body=True)        # -> DocumentResult
service.get_document(uid="…")                                       # address by uid
service.list_documents(runbook="ops", query="backup")               # -> [DocumentSummary]
service.append_to_document("ops", "backup-report", body="\n- 03:00 ok")
service.move_document(runbook="ops", key="backup-report", to_runbook="archive")
service.move_document(uid="…", to_runbook=None)                     # detach → standalone
service.archive_document(runbook="ops", key="backup-report")        # soft-delete (recoverable)
service.delete_document(runbook="ops", key="backup-report", force=True)  # hard-delete
```

**`on_exists`** chooses write semantics when the doc already exists:

| Value | Effect |
|---|---|
| `new_version` (default) | Snapshot a new version; history grows. |
| `overwrite` | Replace the head content in place; no new version. |
| `append` | Concatenate to the head content in place. |
| `fail` | Raise `DocumentAlreadyExists`. |

**`expected_version=N`** is an optimistic lock — the write raises `VersionConflict` if the head moved.

**Instance ops** (`write_version`, `attach_image`, `archive_document`, …) work on any `Document`, including sectionless/keyless ones — the browser UI uses these.

**Returns are typed dataclasses** — `DocumentResult` / `DocumentSummary` (and `ImageRef`). They carry `uid`, `runbook`, `key`, `title`, `version`, `source`, `is_generated`, `locked`, `updated_at`. Don't reach into models to reconstruct these.

**Errors** are a small hierarchy off `DocumentServiceError`: `RunbookNotFound`, `SectionNotFound`, `DocumentNotFound`, `DocumentAlreadyExists`, `VersionConflict`, `DocumentLocked`. Catch the base to map to a transport error.

**Provenance & events**: every write records `source` (a free-text provenance label, e.g. `"newsletter-bot"`) and `via` (the transport: `web`/`api`/`mcp`/`seed`/`import`). Writes emit domain signals **on commit** — `document_written`, `document_archived`, `document_moved`, `document_image_attached`. Subscribe to these for notifiers/fan-out; don't hook `post_save` on the models.

## Search

One query backs all surfaces: case-insensitive match against **title + description + content**.

```python
service.list_documents(query="deploy")                       # everywhere
service.list_documents(runbook="ops", query="deploy")        # scoped
```

- REST: `GET api/documents/?q=deploy&runbook=ops`
- MCP: `runbook_list_documents(query="deploy")`
- UI: the Search page + the htmx search-results fragment

Because it matches `content_text` (frontmatter-stripped, resynced on every write), a term buried in a paragraph or a table cell is found — not just titles. Note this local query is a case-insensitive substring (`icontains`) — unranked.

### Ranked full-text search + the search MCP tool (the engine)

`Document` is **registered with the SmallStack search engine** (`smallstack_runbook/search.py` → `apps.search`), which gives it a much stronger, shared retrieval path than the local substring query above:

- **BM25-ranked full-text** — SQLite FTS5 / Postgres `ts_rank` (results ordered by relevance, not `updated_at`).
- **`search_runbook_documents(query, limit)` MCP tool** + inclusion in the cross-model **`search_all`** tool and the global omnibar / `/smallstack/search/`.
- **Ownership-scoped** — the same `permissions.viewable_documents` gates results everywhere (omnibar, search page, *and* MCP), so private runbooks never leak.
- **Live** — every write reindexes (via the head-sync `post_save`); backfill existing rows with `manage.py rebuild_search_index smallstack_runbook.Document`.

This is the runbook acting as a **lightweight RAG retrieval source**: a doc written via REST/MCP/CLI is instantly ranked-searchable, and a chatbot (Claude via MCP) can `search_runbook_documents` to pull grounded context. See `docs/skills/search.md` for the registration pattern. The engine now backs `GET api/documents/?q=` (BM25-ranked, `limit`-capped) and the CLI's `find` verb too, both scoped to what the caller may view (`service.search_documents`); they fall back to the substring `list_documents` path only when `apps.search` is absent. The runbook's own `/runbook/search/` HTML page still uses the local `?q=` substring scan.

**Coming next (not built yet):** passage-level *chunking* (return the relevant paragraph + a `#anchor`, not the whole doc) and an *original-source link* so an app can convert a PDF/docx → markdown, keep the original, and have search return both. Tracked in the base project's `ai_cowork/search/search-rag-roadmap.md`.

## MCP tools

Autodiscovered from `mcp_tools.py` when the SmallStack MCP app is installed. Read tools require a `readonly`-or-higher token; **write tools require a `staff`-tier token** (`write=True` also blocks read-only tokens). The service then enforces per-runbook **ownership** on the actor (the token's user), so a write only lands if that user owns the target runbook or is staff. The `do_*` delegates take an explicit `actor` so they're unit-testable without an MCP dispatch context.

| Tool | Does |
|---|---|
| `runbook_list_documents` | List/search (runbook, source, query, limit). |
| `runbook_get_document` | Fetch one (with body) by `(runbook, key)`, `uid`, or `id`. |
| `runbook_put_document` | Create/update; `on_exists` controls the write. |
| `runbook_append_document` | Append to head content. |
| `runbook_move_document` | Move/detach (identity by uid unchanged). |
| `runbook_delete_document` | Archive (default) or `force` hard-delete. |

For MCP design patterns see [`mcp/build-mcp-solution.md`](mcp/build-mcp-solution.md) and [`mcp/write-a-custom-tool.md`](mcp/write-a-custom-tool.md).

## REST endpoints

Under the runbook URLs. Reads need auth (and are ownership-scoped by `viewer`). Writes need an **authenticated user** and a **non-read-only** token (`_require_write` enforces both); the **service** then enforces per-runbook **ownership** — any owner or staff may write (`NotAuthorized` → 403). A write (or read) targeting a runbook/doc the caller can't even *view* returns **404**, so the API never leaks whether a private slug exists.

```
# Documents
GET    api/documents/?runbook=&source=&q=&limit=   # list / BM25-ranked search (q)
GET    api/documents/by-uid/<uid>/                 # read by canonical uid
GET    api/documents/<runbook>/<key>/              # read (with body)
PUT    api/documents/<runbook>/<key>/              # upsert (JSON body: body, title, on_exists, …)
DELETE api/documents/<runbook>/<key>/[?force=true] # archive / hard-delete
POST   api/documents/<runbook>/<key>/append/       # accumulate
POST   api/documents/<runbook>/<key>/move/         # re-place / detach
POST   api/documents/<runbook>/<key>/archive/      # soft-delete
POST   api/documents/<runbook>/<key>/unarchive/    # reverse a soft-delete
POST   api/documents/<runbook>/<key>/revert/       # roll back to a version (JSON: {"to": N})
POST   api/documents/<runbook>/<key>/copy/         # duplicate (JSON: to_runbook, to_key, …)

# Runbook containers
GET    api/runbooks/                               # list (ownership-scoped)
POST   api/runbooks/                               # create — owned by the caller (JSON: slug, name, …)
GET    api/runbooks/<slug>/                        # detail + table of contents (sections → pages)
GET    api/runbooks/<slug>/sections/               # list sections
POST   api/runbooks/<slug>/sections/               # create a section (edit rights)
POST   api/runbooks/<slug>/publish/                # make public (edit rights)
POST   api/runbooks/<slug>/unpublish/              # make private (edit rights)
```

A REST-created runbook is owned by the calling user (a private runbook they control) — unlike the CLI's `mkdir`, which makes an `owner=NULL` system runbook. `publish`/`unpublish` and section creation require **edit rights** (owner or staff); a runbook the caller can't view returns **404**.

Error mapping: `DocumentLocked`/`NotAuthorized` → **403**, `VersionConflict`/`DocumentAlreadyExists`/`RunbookAlreadyExists` → **409**, not-found → **404**, other service errors → **400**. To add a *new* endpoint, follow [`custom-api-endpoints.md`](custom-api-endpoints.md) and keep it a thin skin over the service.

## CLI

`manage.py runbook` is the shell skin — unix verbs over the same service, so you can pipe
command output straight into a page:

```bash
uv run python manage.py runbook ls                                   # list runbooks
uv run python manage.py runbook cat ops/backup-report                # print markdown
echo "# Report" | uv run python manage.py runbook write ops/report   # body from stdin
```

Verbs: `ls`, `toc`, `find` (ranked search), `cat` (`@N` reads old versions), `write`
(create-or-update), `cp`, `rm`, `restore` (un-archive), `mv`, `revert` (roll back a version),
`log`, `stat`, `mkdir`, `sections`, `publish`/`unpublish`.
Page verbs address `runbook/key` (or `--uid`); every verb takes `--json`. `write` writes
`via="cli"`, auto-creates a missing runbook/section, and honors locking (`--bypass-lock` /
`--user` for a superuser). The package installs an `rb` console script, so `rb ls` works too. Full
reference: [`runbook-cli.md`](runbook-cli.md).

## Locking (managed / read-only docs)

A **locked** document is read-only in the UI, REST, and MCP for everyone **except a superuser**. The check lives in the service (`_check_writable`), so all transports honor it identically — a write raises `DocumentLocked`. Authorized syncs (import, seed) pass `bypass_lock=True`; end users never can. Locked docs show a **🔒 Managed** badge; a superuser toggles the lock in the UI.

Locking is how *shipped* documentation stays authoritative — the content comes from a source of truth and casual edits are prevented.

## Retention

Runbooks bound history on two axes: **per-version** (`max_versions`, `max_version_age_days`) and **whole-document TTL** (`ttl_days`). Policy resolves **document → runbook → global default** (the global default differs for generated vs. human-authored). Pruning runs as a background task on write plus a periodic sweep — it never blocks a save. Generated/managed docs usually want tighter retention since they're regenerated anyway.

---

## The developer workflow: ship app docs as a bundle

This is the headline reason the system is transport-agnostic. **Author your app's help docs as a runbook** (rich editor, images, live preview), then **freeze them to a portable ZIP** that ships in your app repo and installs into any downstream project.

```bash
# 1. Author in a runbook while developing (edit freely).
# 2. Freeze to a portable, database-independent ZIP:
uv run python manage.py export_runbook my-app-docs --out docs-bundle.zip
# 3. On install / in CI, hydrate it into the target project:
uv run python manage.py import_runbook docs-bundle.zip --slug my-app-docs
```

The bundle is `manifest.json` + one markdown file per document + content-hashed images, with image URLs rewritten to **relative refs** (so it doesn't depend on any database's primary keys).

**What `import_runbook` does:**
- Upserts runbook + sections + documents **by key** — safe to re-run.
- Stamps each doc `is_generated`, sets a `source` label, and **locks** it (bundle is the source of truth; installed copy is read-only, superuser to change).
- `--unlock` imports editable copies (for authoring on a dev box).
- `--prune` archives managed docs from the same `source` that dropped out of the bundle, so deletions propagate.

**To edit shipped docs**: import with `--unlock` (or unlock as a superuser), edit in the UI, then `export_runbook` again and commit the refreshed ZIP. The lock keeps the installed copy authoritative between authoring passes.

These are **developer/admin** tools (they need shell access) — which is exactly the intended gate: app developers build install docs; end users just read them.

### Dogfood reference

Runbook ships its **own** documentation this way. `seed_runbook_docs` builds the `runbook-guide` runbook (User / Admin / Developer sections, locked+managed, `source="runbook-docs"`) — read that command as the worked example of the pattern, and browse it at `/smallstack/runbook/runbook-guide/`.

```bash
uv run python manage.py seed_runbook_docs            # managed/locked
uv run python manage.py seed_runbook_docs --unlock   # editable copies
```

## Management commands at a glance

| Command | Purpose |
|---|---|
| `seed_runbook` | Sample runbook with demo docs/versions/images. |
| `seed_runbook_docs [--unlock]` | Runbook's own docs (the bundle pattern, dogfooded). |
| `export_runbook <slug> --out <zip>` | Freeze a runbook to a portable bundle. |
| `import_runbook <zip> [--slug --source --unlock --prune]` | Hydrate a bundle into a runbook. |
| `runbook <verb> …` | Unix-style CLI (ls/cat/write/rm/mv/log/stat/toc/sections) — see [`runbook-cli.md`](runbook-cli.md). |

---

## Anti-patterns (don't do these)

1. **Writing to `Document` / `DocumentVersion` models directly.** You'll skip versioning, provenance, lock enforcement, and events. Go through `service`. (Seeds/imports use `service.*` with `bypass_lock=True`, not raw ORM writes.)
2. **Hooking `post_save` on the models** to react to changes. Subscribe to the domain signals (`document_written`, …) instead — they fire on commit with `change_type`, `actor`, `source`, `via`.
3. **Addressing docs only by `(runbook, key)`** when identity must survive a move/detach. Use `uid` for durable links.
4. **Re-seeding managed content with `on_exists="new_version"`.** That spams version history on every run. Managed seeds use `overwrite` (idempotent, stays at v1).
5. **Editing an installed bundle's docs in place and expecting it to stick.** The installed copy is locked; edit the *source* runbook and re-export, or import `--unlock` for a deliberate authoring pass.
6. **Bypassing `_require_write` / lock checks in a new transport.** Any new surface must call the service (which enforces per-runbook ownership *and* locking) and gate writes on an **authenticated, non-read-only** caller — let the service raise `NotAuthorized` for a non-owner rather than pre-gating on staff.

## When you're stuck

| Problem | Look at |
|---|---|
| A write returns 403 / `DocumentLocked` | The doc is locked (managed). Superuser to edit, or it's a shipped bundle doc — edit the source and re-import. |
| Re-running a seed keeps bumping versions | Use `on_exists="overwrite"`, not `new_version`. |
| A moved/renamed doc's links broke | Address by `uid`, not `(runbook, key)`. |
| Search misses a doc | It matches title/description/`content_text`; confirm the term is in one of those and the doc isn't archived. |
| Imported images don't render | Check the bundle's relative refs were rewritten to serve URLs on import (they are, per attached `DocumentImage`). |
