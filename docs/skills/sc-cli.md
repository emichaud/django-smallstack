# The `sc` CLI — the framework front door for humans and agents

`manage.py sc` (or the `sc` console shim) is SmallStack's **framework CLI**: a fifth thin skin over
the same operations as the web/REST/MCP surfaces. Two verb families:

- **Resource verbs** — generic CRUD over **any** registered `CRUDView` (`sc ls/get/describe/new/set/rm`).
  Because Explorer synthesizes a CRUDView for every admin-registered model, `sc` reaches far more than
  the handful of hand-written views — run `sc ls` to see the full set.
- **Operational verbs** — a curated front over the framework's own management commands
  (`sc doctor/backup/token/status/index`) plus `sc commands` to discover the rest.

Writes go through the model's `form_class` and record `log_write(..., "CLI")`, so validation and the
audit trail are **identical** to a REST `PUT` or an MCP tool call. Every read verb takes `--json`;
failures exit non-zero (pipelines fail loudly).

> **`sc` vs `rb`**: `sc` covers CRUDView **models** + framework ops. `rb` (runbook) is a *service*, not
> a CRUDView, so its documents live under `rb` — see [`runbook-cli.md`](runbook-cli.md).

## Addressing a model

Models are addressed by a case-insensitive **token**: the model name (`user`), the `app.model` form
(`accounts.user`), the verbose name, an MCP noun (`mcp_plural`/`mcp_singular`), or the `url_base`. `sc ls`
prints the canonical token for each. A miss raises a "did you mean …" error.

## Verbs

| Verb | Does | Key flags |
|---|---|---|
| `sc ls` | List every registered model → token, flags (`a`=api `m`=mcp `s`=search), name. | `--counts` (row count/model), `--json` |
| `sc ls <model>` | List rows. Columns = the view's list fields. | `-q/--query`, `--filter k=v` (repeatable), `--order`, `--limit`, `--user`, `--json` |
| `sc get <model> <pk>` | One object's detail fields as key/value. | `--user`, `--json` |
| `sc describe <model>` | Introspection: fields+types, search/filter fields, actions, api/mcp/search flags, staff-only, url_base. | `--json` |
| `sc search <query>` | Cross-model keyword search (via `apps.search`). | `--limit`, `--user`, `--json` |
| `sc new <model> --f=v …` | Create through `form_class` validation + audit. Large fields via `--stdin-field` (stdin or `-f FILE`). | `--stdin-field`, `-f/--file`, `--user`, `--json` |
| `sc set <model> <pk> --f=v` | PATCH-merge update through the form; respects `can_update`. | `--stdin-field`, `-f/--file`, `--user`, `--json` |
| `sc rm <model> <pk> --force` | Delete; respects `can_delete`; `--force` required (no undo). | `--force`, `--user`, `--json` |
| `sc doctor [api\|mcp\|search\|webhook\|all]` | Health-check the surfaces (`all` aggregates them). | passthrough (`--json`, `--check-only`) |
| `sc backup` | SQLite backup (`backup_db`). | passthrough |
| `sc token create\|list\|revoke` | API-token ops (`create` fronts `create_api_token`; `list`/`revoke` are queries). | `list`: `--user`, `--all`, `--json` |
| `sc status [check\|maintenance …]` | Run monitors (`heartbeat`) or manage maintenance windows. | passthrough |
| `sc index [rebuild\|sync]` | Rebuild the search index / sync the help index. | passthrough |
| `sc webhook status\|list\|test\|replay\|deliveries\|tick\|pair` | Webhook **ops** (fronts `manage.py webhook`). `replay --status dead` bulk-replays every dead delivery; `pair` links two SmallStacks (S2S). Endpoint/receiver CRUD uses the generic verbs (`sc ls/new/set/rm webhook`). | `--status`, `--endpoint`, `--since`, `--limit`, `--target`, `--events`, `--slug`, `--send-secret`, `--recv-secret`, `--one-way`, `--verify`, `--json` |
| `sc commands` | Discover every framework management command, grouped by app. | `--json` |

**Writable fields ⊆ shown fields.** `new`/`set` go through the model's **form** (exactly like the web UI
and MCP), so they accept only the form's fields — a *subset* of what `ls`/`get`/`describe`/`--filter`
surface. A display-only or filter column (e.g. a computed one) will error `unknown field(s): …` on a write.
`sc describe <model>` marks writable fields (`rw`) and lists them under `writable:` — check there before a
write. Field names use **underscores** (`--expected_status`), and an unknown `--field` errors rather than
silently no-op'ing.

## Security / actor

**Without `--user`**, `sc` acts as a **local admin with full, unscoped access** (like `manage.py shell`
and `sc search`) — so `ls`, `get`, and `ls --counts` agree with each other. Pass `--user <username>` to
scope reads/writes through the view's `get_list_queryset` tenancy hook *as that user* and to set the
audit actor. Writes to a **staff-only** model (`StaffRequiredMixin`) require a **staff** `--user`,
mirroring the MCP `requires_access="staff"` gate.

Field names use **underscores** (`--expected_status`, not `--expected-status`); unknown `--field` keys on
a write error out rather than silently no-op. `sc` runs with local shell privileges (it's `manage.py`) —
treat it as a local admin tool.

## Examples

```bash
sc ls                                   # every model + flags (the table of contents)
sc ls user -q alice --order -date_joined --limit 20
sc ls monitoredendpoint --filter enabled=true --json
sc get user 3
sc describe apitoken                    # fields, search/filter, actions, flags
sc search "acme"                        # cross-model, ranked

# writes (staff-gated model → staff --user)
sc new monitoredendpoint --name "Homepage" --slug home --method GET \
   --url https://example.com --expected_status 200 --timeout_seconds 10 --user admin
echo "$LONG_BODY" | sc new note --title Report --stdin-field=body --user admin
sc set monitoredendpoint 5 --enabled=false --user admin
sc rm monitoredendpoint 5 --force --user admin

# framework ops
sc doctor all                           # api + mcp + search + webhook health
sc token list --all
sc token revoke -- -AbC1234             # '--' when a prefix starts with '-' (pre-0.20 tokens)
sc backup
sc commands                             # discover everything else

# webhooks — CRUD via generic verbs, ops via `sc webhook`
sc new webhook --name Zapier --target_url https://hooks.zapier.com/... \
   --event_filter '["support.ticket.*"]' --enabled=true --user admin
sc webhook status                       # counts by delivery status + retry backlog
sc webhook list                         # endpoints with health (last status, fail-streak)
sc webhook test Zapier                  # fire a signed test delivery
sc webhook deliveries --status dead --limit 20
sc webhook replay 42                    # re-send one dead delivery
sc webhook replay --status dead         # BULK: replay every dead delivery (dead-letter recovery)
sc webhook pair --target https://peer/webhooks/in/x/   # link two SmallStacks (emits the peer cmd)

# select the extension seams on an endpoint/receiver with the generic `sc set`:
sc set webhook 3 --transform slack --auth_scheme sas          # outbound transform + auth (endpoint)
sc set webhookreceiver 2 --verifier stripe --challenge eventgrid   # inbound verify + handshake
# is_paired is read-only (managed by `sc webhook pair`) — shown, never settable.
```

> **Gotcha — creating an endpoint via CLI/REST:** `enabled` is a form `BooleanField`,
> so a `sc new webhook` (or REST `POST`) **without `--enabled=true` creates a *disabled*
> endpoint** (an unchecked checkbox = False). Pass `--enabled=true` to arm it, or flip it
> later with `sc set webhook <pk> --enabled=true`.

## Piping + JSON

Every read verb emits `--json` (`json.dumps(indent=2, default=str)`), and `new`/`set` read a field from
stdin via `--stdin-field`, so `sc` composes with any tool:

```bash
sc ls user --json | jq '.[].email'
some_command | sc new note --title "Log" --stdin-field=body --user admin
sc get ticket 5 --json | jq '.status'
```

## When to reach for `sc` (agents)

- **Inspect/query any model from the shell** — `sc ls <model> -q …`, `sc get`, `sc describe` (faster than
  writing a shell script or a one-off query).
- **Discover the surface** — `sc ls` (models) and `sc commands` (operations) are the map.
- **Health-check** — `sc doctor all` before/after changes.
- **Scripted CRUD** — `sc new/set/rm --json` with the same validation + audit as the UI.

Prefer `sc` over ad-hoc `manage.py shell` snippets for CRUD and introspection — it's audited, validated,
and JSON-friendly.
