# Contributing to SmallStack

Thanks for taking the time to contribute. This document captures the tacit conventions that have emerged across the project — naming, app boundaries, error-message shape, deprecation hygiene — plus the architectural decisions that aren't obvious from skimming the code. Read this once before your first PR; it'll save you re-deriving choices the project has already made.

If you only have time for one section: read [Find option C](#find-option-c--the-fix-shape-pattern). It's the single most repeatable habit that distinguishes good contributions to this project from merely correct ones.

---

## Find option C — the fix-shape pattern

When you're fixing a documented finding (an audit item, a bug report, an in-comment TODO), the requester usually proposes one or two ways to fix it. **Treat their suggestion as a starting point, not the destination.** Almost always there is a third option that's strictly better — more information for the caller, fewer false dichotomies, less surface to remember.

The pattern is small enough to teach with examples:

### Example 1 — the v0.11.9 MCP search-tier fix

Round-2 audit §3.3 reported: a non-staff user could call `search_users` via MCP and pull every user's email. The audit suggested two ways to fix it:

> Either return `{"results": []}` (silent denial) or return a JSON-RPC error (loud denial).

Both are correct. Neither is what shipped. v0.11.9 returned:

```json
{
  "results": [],
  "denied": true,
  "reason": "Access to accounts.User requires search_access >= staff; this token's user does not satisfy that tier."
}
```

This shape:
- Distinguishes "you can't see this" from "nothing matched" (the audit's silent-denial option had a false-equivalence with empty-results).
- Keeps the cross-model `search_all` handler unbroken (a JSON-RPC error would have aborted the whole call across other allowed views — the audit's loud-denial option would have been worse than the bug it fixed).
- Surfaces the specific access level the caller would need — so the developer fixing their integration knows what kind of token to mint without re-reading docs.

That's option C. The audit didn't ask for it; the code is better for it.

### Example 2 — the v0.11.9 token-error fix

Round-2 audit §4.6 reported: expired tokens get a generic `Invalid token` 401, which conflates "wrong key" with "right key, but expired" and makes debugging harder. The audit suggested:

> Distinguish expired tokens from other invalid ones.

That would have been two messages: "Invalid token" and "Token expired." v0.11.9 shipped four:

- `Invalid token` (unknown key — unchanged)
- `Token revoked` (right key, `is_active=False` or `revoked_at` set)
- `Token expired at <iso8601>` (right key, past `expires_at` — *includes the timestamp* so the developer sees the deadline)
- `Token inactive` (right key, otherwise rejected by `is_valid()`)

Plus matching reason strings on the MCP side (`token_revoked` / `token_expired` / `token_inactive`) so JSON-RPC errors distinguish too. That's option C. The asked-for fix was a 2-way; the shipped fix is a 4-way with a timestamp.

### When you're about to ship the asked-for option

Pause and ask: *what would option C look like?*

- Can the response carry **more information** without making the call site harder? (Reason strings, timestamps, the specific failed precondition.)
- Are we conflating two distinct failure modes that should be distinguishable? (The token-error fix: "wrong key" vs "right key, no longer valid.")
- Will the asked-for fix **break other code paths** as collateral? (The MCP search fix: a JSON-RPC error would have torched cross-model search; a structured deny didn't.)
- Is there a way the **caller could fix the failure themselves** if we told them more? (Surface the access tier so they know which token to mint.)

If yes to any of those, option C is probably the right shape.

### When option C is wrong

Don't over-engineer. Option C beats the asked-for option only when the extra information **costs the caller almost nothing** and **saves them something** — re-reading docs, opening a debugger, filing a ticket. If you're returning rich error objects to a CLI that's going to grep for one line, the asked-for option is right.

The instinct to look for option C is what matters. Pause, think, then choose.

---

## Code conventions

These are observed across the codebase. Following them keeps your PR easy to review.

### Naming

- **One concept = one name.** No `token` ↔ `key` drift; no `read_only` vs `readonly`; no `access_level` here and `permission_level` there. Pick the name the rest of the project uses and use it everywhere.
- **`access_level`** for API tokens (`readonly` / `staff` / `auth`). Not `permission_level`, not `role`.
- **`url_base`** for the URL prefix a CRUDView mounts under. Not `base_url`, not `prefix`.
- **`namespace`** for URL namespacing on CRUDViews (when paired with `app_name` in `urls.py`). Not `app_label`, not `space`.
- **`mcp_singular` / `mcp_plural`** for noun overrides on MCP tool names. Match the convention; don't invent `mcp_name` or `tool_name`.
- **`search_fields` / `search_display` / `search_subtitle` / `search_access` / `search_visibility`** — all `search_*` prefixed. New search hooks should follow.

### Private internals start with `_`

Module-level helpers that aren't part of the public surface start with an underscore:

```python
# apps/smallstack/api.py
def _build_filter_fields_spec(model, filter_fields):
    """Convert a flat filter_fields list to a dict with smart lookups."""
    ...

def build_api_urls(crud_config):
    """Public — emits the URL patterns for a CRUDView's REST endpoints."""
    ...
```

This is how readers tell what's import-stable from what's free-to-rename. Don't elevate a private helper to public just because you reused it once; either rename it (drop the underscore + document the contract) or import the underscored name explicitly.

### No `__init__.py` re-exports

Resist the urge to add convenience imports:

```python
# apps/smallstack/__init__.py — DON'T do this
from .crud import CRUDView, Action
```

The explicit import (`from apps.smallstack.crud import CRUDView, Action`) is more verbose but documents the *public surface* of each module accurately. Barrel re-exports hide where things actually live, make refactoring harder, and create import cycles when modules grow. They're also infectious — once one module does it, the others get pressure to follow.

The one exception: a brand-new package (no existing modules importing the leaf names directly) can choose either style. Established packages should not gain barrel exports.

### Function size + module size

- **Functions**: prefer < 50 lines. Past that, look for a sub-step that can be extracted with a clear name.
- **Modules**: at ~1,000 lines, start watching the trend. Around ~2,500 lines, plan a split. The biggest current files (`crud.py` 1702L, `api.py` 1776L) are well-organised internally with `# -----` section delimiters; if they grow past 2,500 they should split along the lines documented in their own module docstrings (URL gen vs auth vs serialization for `api.py`).

### Type hints on public surfaces

Type-hint the public API surface (the underscore-free names) and any handler that an external caller will look at. Internal `_helper(arg)` functions can be untyped if the signature is obvious from the body. Use `from __future__ import annotations` at file top so forward references work without quoting.

### Comments

Default: write no comments. Only add one when the *why* is non-obvious — a constraint that wouldn't be guessable from the code, a workaround for a known bug, an invariant a future reader would miss.

Do not narrate the *what* — the code already does that. Specifically:

- Don't write `# Increment the counter` over `count += 1`.
- Don't write `# Used by X` — the call site is a grep away and the note will rot.
- Don't write `# Added for issue #123` — that's PR metadata; it belongs in the commit.

Comments answering "why is this load-bearing weird?" are valuable. Comments restating the code are noise.

### Test shape

- Test layout — **one pattern per app, don't mix**:
  - A single test file → `apps/<name>/tests.py`.
  - Multiple test files → a package: `apps/<name>/tests/__init__.py` + `tests/test_*.py` (as `api`, `mcp`, `search`, `tokenmgr`, `accounts`, `heartbeat` do).
  - Never keep both a flat `tests.py` and a stray `apps/<name>/test_*.py` — promote to a package instead. Inside a package, import app modules **absolutely** (`from apps.<name>.models import X`), not relatively.
- DB-touching tests: `pytestmark = pytest.mark.django_db` at the module top.
- Fixtures live in `conftest.py` at the right scope. The narrower the better.
- One test asserts one thing. If you find yourself writing `# also verifies X` in a docstring, split the test.

---

## App boundaries

The codebase is organised into apps under `apps/`. Where each app lives reflects a deliberate decision; respect it.

### `apps/website/` — "edit freely"

This is the *only* app downstream projects are expected to modify wholesale. Custom homepage, project-specific landing pages, the public site nav — all go here. Upstream merges will never overwrite anything in `apps/website/`. If a downstream project's needs grow past one app, add a sibling (`apps/billing/`, `apps/projects/`) — don't expand `apps/website/` into a kitchen sink.

### `apps/smallstack/` — framework core

The CRUDView library, theming primitives, dashboard system, API factory, table column types. *Don't edit this in downstream forks* — upstream merges will conflict. If you need to change behaviour here, propose it upstream first or override via subclassing in your own app.

### `apps.api` vs `apps.smallstack.api` — observer vs runtime

This split is intentional and easy to confuse:

- `apps/smallstack/api.py` is the **runtime**: URL generation, request handling, the actual REST surface that responds to GETs and POSTs.
- `apps/api/` is the **observer**: `/smallstack/api/` admin pages that introspect what the runtime is doing, health checks, threat-panel UI, the `api_doctor` management command.

The same split exists for MCP (`apps/mcp/server.py` runtime vs `apps/mcp/admin/` observer). When in doubt: if it serves requests, it's runtime; if it introspects, it's observer.

### Why the split matters

A `apps/api/` "kitchen sink" that combined the runtime and the observer would put the API admin pages behind the same auth gate as the API itself (or vice versa), and would couple the two evolution paths together. The split lets the runtime stay small and the observer evolve independently.

### Where management commands live

A `manage.py` command lives in **the app that owns the subsystem it operates on**, not in a central `commands` app:

- `apps/smallstack/` — cross-cutting ops: `backup_db`, `create_api_token`, `create_dev_superuser`, `screenshot_auth`.
- `apps/heartbeat/` — `heartbeat`, `maintenance` (monitoring / status).
- `apps/search/` — `rebuild_search_index`, `search_doctor`, `sync_help_index`.
- `apps/activity/` — `prune_activity`.

Rule of thumb: if the command reads/writes an app's models or diagnoses its feature, it ships in that app. The full catalogue with flags is [`apps/smallstack/docs/cli-reference.md`](apps/smallstack/docs/cli-reference.md).

### App-label naming

App labels match the `apps/<name>/` directory (`accounts`, `heartbeat`, …). One label — `tokenmgr` — reads a bit cryptic versus its user-facing name ("token manager"), but it is **kept deliberately**: the label is baked into migrations, the `tokenmgr:` URL namespace, and downstream references, so renaming it for cosmetics would be a breaking change with no functional gain.

---

## Deprecation hygiene

When retiring an API, follow this pattern (visible in `apps/smallstack/tables.py` and `apps/smallstack/crud.py`):

1. Keep the old API working but **emit `warnings.warn()`** at instantiation/call time. Name the replacement in the message:

   ```python
   warnings.warn(
       "OldColumn is deprecated; use NewColumn instead. "
       "See apps/smallstack/docs/tables.md.",
       DeprecationWarning,
       stacklevel=2,
   )
   ```

2. Add a docstring `.. deprecated::` note pointing at the replacement and the removal version:

   ```python
   class OldColumn:
       """A column type that doesn't sort correctly.

       .. deprecated:: 0.10.0
          Use :class:`NewColumn` instead. Will be removed in 1.0.
       """
   ```

3. The release notes for the deprecating version call out the rename + the removal version.

4. The removal lands in a major (or pre-1.0, a minor) bump, never in a patch.

Don't break the old API in the same release that introduces the warning. Even pre-1.0, that's the kind of churn that erodes trust in the project.

---

## Architecture notes

These decisions aren't obvious from skimming and are worth a paragraph each.

### CRUDView ↔ one model ↔ multiple surfaces

The headline pattern: a single `CRUDView` declaration produces an HTML admin page, a REST endpoint, an MCP tool set, and a search index row. Each surface is opt-in via a boolean flag (`enable_api`, `enable_mcp`, `enable_search`). The factory pattern means *one* class is the source of truth for the model's behaviour across surfaces — tenancy filtering in `get_list_queryset` covers all of them; auth mixins set the access level for all of them; `search_visibility` scopes rows in all of them.

This pattern is the project's competitive differentiator. Don't add surfaces that bypass it. If a surface needs a different access model, the right answer is usually a *second* CRUDView on the same model, not a special case carved out of the first.

### Search registry as the source of truth for "who can find what"

The search system (see `docs/skills/search.md`) uses a per-view `search_access` tier (STAFF / AUTHENTICATED / ANONYMOUS) plus an optional `search_visibility` row-scoping callback. **The registry is the canonical place these decisions live.** The web search page, the MCP search tools, and (when downstream projects build it) any custom search surface should all route through `apps.search.registry.search_all()` or its helpers — not roll their own.

The v0.11.9 MCP search-tier fix is the cautionary tale: the search MCP handlers were calling `backend.query()` directly without consulting the registry's access gate, which leaked STAFF-tier data to readonly tokens. The fix routed them through `_user_can_see()` so the registry stays the single source of truth.

### The two-doc-tree split (`docs/skills/` vs `apps/smallstack/docs/`)

These are not duplicates. They have different jobs:

- **`docs/skills/`** is for AI agents working in the codebase. Optimised for "read this before doing X" prescriptive guidance. Short, opinionated, action-oriented.
- **`apps/smallstack/docs/`** is for human users browsing `/smallstack/help/`. Optimised for reference, examples, and the conversational explanation that helps a developer understand *why* a pattern exists.

When you contribute a docs change, decide which audience it's for. If your change really does affect both, write it in `docs/skills/` first (where the canonical text lives) and add a one-line pointer from the parallel `apps/smallstack/docs/<topic>.md` saying "Building this? Read the skills version first." Don't duplicate.

### The `_registry` first-wins rule

`CRUDView._registry` is class-level state populated via `__init_subclass__`. **First wins**: a CRUDView defined later in the import order doesn't overwrite an earlier one for the same model. This matters because `apps.explorer` synthesises `Explorer<Model>CRUDView` classes at AppConfig.ready() time for every admin-registered model — without the first-wins rule, Explorer's clones would silently displace the user's CRUDView in the registry, breaking `mcp_doctor`, related-tabs URL resolution, and anywhere else the registry is walked.

If you're contributing code that touches the registry, **don't reach for `_registry[cls.model] = cls`** to override. Use `setdefault`, or — if you genuinely need to overwrite — `pop` the prior entry first and add a comment explaining why.

---

## Pull request flow

1. **Branch from `main`** for a single coherent change.
2. **Write tests.** A PR without tests is a PR for code that doesn't exist yet.
3. **Run `make lint` and `make test`** before pushing. Both are part of the contract — CI will fail if they don't pass locally.
4. **Commit message style**: one-line subject (<= 70 chars) describing the change; blank line; body explaining *why* + tradeoffs. Reference the audit / issue / motivation. The full diff in the body of the commit message is overkill; the git log is for finding things, not re-reading them.
5. **One PR per concern.** "Fix audit findings 1, 4, 9 + small refactor" is harder to review than four PRs each named for what they do.

For audit-cycle PRs specifically: include a verification matrix at the top (each finding → fixed / partial / didn't reproduce / deferred) so the response author and the next-round auditor can triage at a glance. The `audit-response-*.md` files under `sandbox/apps/mcp_demo/` are the template.

---

## Where to ask

- **Project-shape questions** (architecture, naming, where does X go?): open a discussion on GitHub, or read [`docs/skills/`](docs/skills/) for the closest prescriptive guide.
- **Implementation questions** (how do I make CRUDView do Y?): the [skill files](docs/skills/) are the canonical reference; if you can't find an answer there, the gap itself is worth flagging.
- **Bug reports**: GitHub issues. Include the failing command, the actual + expected output, and the version (`pip show django-smallstack`).

If you contributed something good and didn't see your name in the release notes, please tell me. That's a process bug, not a slight.
