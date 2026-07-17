# Programmatic Surface Gap Analysis

**What could/should be exposed via CLI, API, MCP, and search to make each SmallStack app "pop."**

Date: 2026-07-16 · Scope: dashboard, activity, status (heartbeat), explorer, backups, users/tokens

---

## Context

SmallStack's promise is "one `CRUDView` → four surfaces" (HTML, REST, MCP, search).
That promise is **fully delivered for CRUD over a model**. But the platform apps
are not just models — they are *services*: uptime math, request-log analytics,
backup operations, maintenance scheduling, dashboard aggregation, user lifecycle
actions. CRUDView, by design, only knows how to list/get/create/update/delete a
row. So the moment an app's value lives in a **computed metric** or a **verb that
isn't row CRUD**, it falls off the four-surface conveyor belt and ends up
**HTML-only**.

This report maps, per app, (a) what is reachable programmatically today, and
(b) the highest-value services/metrics/actions that exist in code but are locked
inside Django views — plus concrete suggestions to expose them.

The good news: **the extension points already exist.** `docs/skills/custom-api-endpoints.md`
covers non-CRUD REST endpoints, each app can register custom MCP tools via an
`mcp_tools.py` (`apps/search/mcp_tools.py` is the working template), the dashboard
takes `DashboardWidget` subclasses, and the status board takes pluggable
`Visualization` panels. Almost nothing below needs new framework machinery — it
needs the apps to *use* the machinery for their services, not just their models.

---

## Current exposure at a glance

Legend: ✅ exposed · 🟡 partial · ❌ not exposed · (CLI is implicitly available for
every registered model, so the interesting CLI gaps are *service verbs*, not row CRUD.)

| App | Model / capability | CLI | REST | MCP | Search |
|-----|--------------------|:---:|:----:|:---:|:------:|
| **Dashboard** | Widget data (backup age, help counts, activity totals…) | ❌ | ❌ | ❌ | ❌ |
| **Dashboard** | "Run a backup now" / liveness check | 🟡¹ | ❌ | ❌ | ❌ |
| **Activity** | `RequestLog` rows | 🟡² | ❌ | ❌ | ❌ |
| **Activity** | Analytics (avg latency, 4xx/5xx, top paths, by-method, top users, signups) | ❌ | ❌ | ❌ | ❌ |
| **Status** | `MonitoredEndpoint` | ✅ | ✅ | ✅ | 🟡³ |
| **Status** | `MonitoredSurface` | ✅ | ❌ | ❌ | ❌ |
| **Status** | Uptime math (`_calc_uptime`, timelines, coverage, SLA state) | ❌ | 🟡⁴ | ❌ | ❌ |
| **Status** | Maintenance windows (open/close/list) | 🟡⁵ | ❌ | ❌ | ❌ |
| **Status** | Heartbeat/daily/epoch records | 🟡² | ❌ | ❌ | ❌ |
| **Explorer** | Model registry / introspection | ❌ | ❌ | ❌ | ❌ |
| **Backups** | `BackupRecord` rows | ❌ | ❌ | ❌ | ❌ |
| **Backups** | Create / prune / download | 🟡⁵ | ❌ | ❌ | ❌ |
| **Users** | User CRUD | ✅ | ❌ | ❌ | ✅ |
| **Users** | Send setup/reset link, unlock (axes), activity stats | ❌ | ❌ | ❌ | ❌ |
| **Tokens** | `APIToken` (list/detail) | ✅⁶ | ❌ | ❌ | ✅ |
| **Tokens** | Create / revoke | ✅⁶ | ❌ | ❌ | ❌ |

¹ dashboard button only ² explorer-only, no api/mcp/search flags ³ `search_fields`
defined but `enable_search` off ⁴ only the flat `/health/` JSON ⁵ management command
only ⁶ `create_api_token` + `sc token` verbs, but no REST/MCP.

**One-line takeaway:** only `MonitoredEndpoint` is a first-class four-surface
citizen. Everything genuinely valuable in these apps — the analytics, the uptime
math, the ops verbs — is reachable *only through a browser*.

---

## The core gap: CRUDView is CRUD; the apps are services

Three recurring shapes are trapped in HTML:

1. **Computed metrics** — numbers that aren't a column: `avg_response_time`,
   `uptime_24h`, `coverage_since_epoch`, `total backup size`. CRUDView can't emit
   these because they aren't model fields. They live in view `get_context_data()`
   and die there.
2. **Aggregations / rollups** — "top 10 paths by hits," "errors in the last 24h by
   status," "top users by request count." These are querysets shaped for a table,
   built inside `get_tab_context()` methods, never returned as data.
3. **Domain verbs** — actions that aren't row CRUD: *run a backup*, *open a
   maintenance window*, *send a password link*, *unlock an account*, *run one
   monitor check now*. Several already exist as clean Python functions or
   management commands; they just lack a REST/MCP door.

The fix pattern is the same in every case: **wrap the existing service function in
a thin read (custom API endpoint / read-only MCP tool) or a thin action (POST
endpoint / write MCP tool), reusing the function that the HTML view already calls.**
No logic is duplicated; a boundary is added.

---

## Per-app findings & suggestions

### 1. Dashboard (`apps/smallstack/` central `/smallstack/`)

**Today:** `DashboardWidget` subclasses (`BackupsDashboardWidget`,
`HelpDashboardWidget`, `ActivityDashboardWidget`, `UsersDashboardWidget`,
`StatusDashboardWidget`) each compute a headline number and render HTML. None of
that state is fetchable as data.

**Make it pop:**
- **`GET /api/dashboard/` + MCP `get_dashboard()`** — return every registered
  widget's `{title, value, subtitle, detail_url}` as JSON. The widgets already
  compute this for rendering; expose the same dict. Instantly lets Claude answer
  "give me the state of the system" in one call, and lets a status TV/CI poll it.
  There is already `/api/dashboard/widgets/` — audit whether it returns *values*
  or just *metadata*, and promote it if it's only metadata.
- This is the single highest-leverage change: the dashboard is *designed* to be
  the at-a-glance summary; making that summary machine-readable turns it into the
  system's health API.

### 2. Activity (`apps/activity/` — `RequestLog`)

**Today:** the richest analytics layer in the codebase, **100% HTML.**
`ActivityDashboardView.get_context_data()` computes ~25 metrics; `RequestListView`
and `UserActivityView` build `recent / top_paths / errors / by_method` and
`top_users / signups / inactive` tab data. `RequestLog` isn't even explorer-
searchable. Only a `prune_activity` management command exists.

**Make it pop:**
- **Expose `RequestLog` as a read-only four-surface resource** — `enable_api`,
  `enable_mcp` (LIST/DETAIL only), `enable_search` with
  `search_fields = ["path", "user__username", "request_id", "ip_address"]`. This
  alone makes "find the request with id X" and "show me this user's recent calls"
  work from Claude and scripts.
- **`GET /api/activity/stats/` + MCP `get_activity_stats(window_hours)`** — return
  `avg_response_time`, `status_groups`, `count_4xx/5xx`, `top_paths`,
  `top_users`, `recent_signup_count`. Refactor the metric block out of
  `get_context_data()` into a `services.py` function the view and the endpoint both
  call. High value: this is exactly the "how is traffic looking?" question Claude
  gets asked.
- **MCP `list_recent_errors(hours, status)`** — wrap the existing errors tab. A
  natural debugging tool ("what 5xxs happened in the last hour?").

### 3. Status / Heartbeat (`apps/heartbeat/`)

**Today:** the deepest service layer — 300+ lines of uptime math in `status.py`,
150+ in `services.py`, plus `maintenance.py`. Only `MonitoredEndpoint` is on all
four surfaces. The one machine-readable slice is the flat `/health/` JSON.
Everything else (per-window uptime, timelines, coverage, SLA state, the
maintenance calendar, "run a check now") is HTML/command only.

**Make it pop:**
- **MCP `get_monitor_uptime(monitor_key, hours)`** → `{uptime, coverage, sla_state}`
  wrapping `_calc_uptime` / `_uptime_over_window` / `_sla_state`. The flagship
  "what's our 7-day uptime?" tool.
- **`GET /api/status/uptime/` and `/api/status/timeline/`** — expose
  `_build_daily_timeline` / `build_stacked_timelines` as JSON so an external
  status page or Grafana can render SmallStack's own uptime data.
- **MCP `is_in_maintenance(monitor_key)` + `list_upcoming_maintenance(days)`** —
  wrap `_is_in_any_window` / `_upcoming_maintenance`. Lets an agent gate a deploy
  ("are we already in a window?").
- **Maintenance windows as an API action** — `open_window_for` / `close_windows`
  already exist as clean functions behind the `maintenance` command. Add
  `POST /api/status/maintenance/` + MCP `open_maintenance_window(minutes, title)`
  so a deploy hook can open→deploy→close without shelling into the box. This is
  the biggest ops win in the app.
- **MCP `run_monitor_check(monitor_key)`** — wrap `run_monitor_check()` for an
  on-demand probe.
- **Turn on `enable_search` for `MonitoredSurface`** — its `search_fields` are
  already declared; it's one flag from being searchable.

### 4. Explorer (`apps/explorer/`)

**Today:** pure introspection UI. It *knows* every registered model, its groups,
fields, and live row counts — but none of that registry is queryable. `sc ls`
overlaps heavily (it's the CLI's model catalog).

**Make it pop:**
- **MCP `list_models()` / `describe_model(token)`** — mirror `sc ls` / `sc describe`
  as tools so an agent can discover the data model before querying it ("what can I
  look at here?"). This is the natural "self-describing API" capstone and reuses
  the same registry `sc` reads.
- Lower priority than the service apps — explorer's value is discovery, and `sc`
  already delivers that on the CLI; this is about extending it to MCP.

### 5. Backups (`apps/smallstack/` — `BackupRecord` + `backup_db`)

**Today:** `_do_backup()` / `_prune_backups()` are clean functions; `backup_db` is
a management command; the UI has create/download/prune buttons. `BackupRecord`
has no CRUDView, so no list/detail anywhere but the bespoke page.

**Make it pop:**
- **Expose `BackupRecord` read-only** (`enable_api`, `enable_mcp` LIST/DETAIL) so
  "when did the last backup run and did it succeed?" is one call. Pairs perfectly
  with the dashboard-state API.
- **MCP `run_backup(keep)` (write, staff-gated) + `POST /api/backups/`** — wrap
  `_do_backup()`. "Back up the database now" is a textbook agent-ops action, and
  the function is already isolated and safe (atomic SQLite `.backup()`).
- Keep binary **download** UI-only (auth/size concerns) — expose *status and
  trigger*, not the bytes.

### 6. Users & Tokens (`apps/usermanager/`, `apps/tokenmgr/`, `apps/accounts/`)

**Today:** User CRUD is on the CLI + search (`search_users`) but **not** REST/MCP.
Tokens are CLI (`sc token …`, `create_api_token`) + search (`search_api_tokens`),
not REST/MCP. The valuable *lifecycle actions* — `send_setup_or_reset()`,
`unlock_user()` (axes), `token.revoke()`, and the per-user activity stats — are
all HTML button handlers.

**Make it pop:**
- **Decide the policy first, then expose deliberately.** User/token mutation is
  security-sensitive; there is a `/api/auth/users/…` admin surface already
  (auth-level token). The gap is that the *rich manager actions* aren't there.
- **MCP `send_user_setup_link(user)` + `unlock_user(user)`** (staff-gated, write) —
  wrap the existing functions. Common helpdesk asks ("resend Bob's invite,"
  "Bob's locked out, clear it") that are safe, reversible, and audited.
- **MCP/REST `revoke_token(prefix)`** — wrap `token.revoke()`; a clean, low-risk
  security action worth having programmatically ("kill the leaked key").
- **`get_user_activity(user)`** (read) — expose `_get_user_activity_stats` so the
  per-user engagement view is queryable; complements the Activity work above.
- Leave guardrails (last-superuser, self-deactivation) in the shared service layer
  so every surface inherits them — do **not** reimplement them per endpoint.

---

## Cross-cutting recommendations

1. **Adopt a "service function → thin surface" convention.** The repeated smell is
   metrics computed inside `get_context_data()`/`get_tab_context()`. Extract those
   into `services.py` (heartbeat already models this well) so the HTML view, a
   custom API endpoint, and an MCP tool can all call one function. This is the
   structural change that makes everything else cheap.
2. **Two new CRUDView-adjacent flags would cover most of the metric gap.** Consider
   a first-class pattern (or a documented recipe) for **read-only "stat" endpoints**
   attached to a CRUDView — e.g. a `stats` hook that, when present, auto-emits
   `GET /api/<base>/stats/` and an MCP `get_<noun>_stats` tool. Activity, status,
   backups, and the dashboard all want the identical shape. Worth a design spike:
   it would turn today's per-app custom endpoints into one declarative surface,
   staying true to the "declare once, light up everywhere" thesis.
3. **Distinguish read vs. action tools explicitly.** Reads (uptime, stats, activity)
   are safe to expose broadly at `readonly`. Actions (backup, maintenance window,
   unlock, revoke) should be `staff`-gated writes and audited via the existing
   `log_write` path — same as CRUD writes, so they show up in Activity.
4. **Everything new is auditable for free** if it routes through `log_write` /
   the shared audit helper — which also means the Activity app immediately observes
   the new API/MCP traffic. The apps reinforce each other once they're all on the
   bus.

---

## Suggested priority order

Ranked by value-to-effort (each reuses code that already exists):

1. **Dashboard state API/MCP** (`get_dashboard`) — highest leverage, near-zero risk;
   turns the existing summary into the system's health API.
2. **Activity stats API/MCP + searchable `RequestLog`** — unlocks the richest,
   most-asked-for data in the codebase.
3. **Status uptime & maintenance tools** (`get_monitor_uptime`, `is_in_maintenance`,
   `open_maintenance_window`) — deep service logic already written; huge ops payoff.
4. **Backup status + `run_backup`** — small, self-contained, classic agent-ops verb.
5. **User/token lifecycle actions** (`send_user_setup_link`, `unlock_user`,
   `revoke_token`) — high utility, do *after* nailing the read-only auth policy.
6. **Explorer `list_models`/`describe_model` MCP** — the self-describing capstone;
   nice-to-have once the data surfaces above exist.

> The throughline: SmallStack already nails "declare a model, get four surfaces."
> The next step-change is doing the same for **services and metrics** — a small,
> repeatable "stat endpoint / action tool" pattern that lets the apps expose what
> makes them valuable, not just the rows they store.
