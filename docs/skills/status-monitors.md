# Status Monitors — pluggable uptime/health monitoring

The status system tracks the uptime and health of *services* (the site, the REST
API, MCP, search, …) and any *user-created endpoint*. It's a pluggable registry,
like the dashboard-widget system: an app contributes a **Service** and one or more
**Monitors** from `AppConfig.ready()`, and they show up on the overview with a
status dot, uptime, and a per-monitor timeline page — **no changes to the overview,
the runner, or the views**.

The surfaces it powers:

| Surface | URL | Who |
|---|---|---|
| **Staff overview** — 3-tier board, banners, drill-downs | `/smallstack/status/overview/` | staff |
| **Public status page** — branded, 90-day timelines + maintenance calendar | `/status/` | anyone |
| **Per-monitor detail / timeline** | `/smallstack/status/monitor/<key>/` | public-aware |
| **Per-monitor SLA + maintenance** | `/smallstack/status/sla/?monitor=<key>` | staff |
| **Site Timeline** (the site monitor's 1d/7d/90d bars) | `/smallstack/status/dashboard/` | staff |
| **Scheduled maintenance** (list + 6-month calendar) | `/status/maintenance/` | anyone |

Read this before adding monitoring for a subsystem, exposing a health check, adding
a status visualization, or working on any status page.

## The three concepts

| Concept | What it is | Lives in |
|---|---|---|
| **Service** | A monitored subsystem (the tag monitors attach to): `site`, `api`, `mcp`, `search`, `custom`. Owns an icon + title. | `apps.smallstack.monitors.Service` |
| **Monitor** | A single *cheap* liveness check tagged to one service. Produces a per-minute heartbeat timeseries. | `apps.smallstack.monitors.Monitor` |
| **Visualization** | A pluggable panel (timeline bars, uptime stats, …) that renders any monitor's timeseries. | `apps.smallstack.visualizations.Visualization` |

The registries live in `apps/smallstack/monitors.py` and
`apps/smallstack/visualizations.py` — pure, import-light modules that mirror
`dashboard.py` / `navigation.py`.

## The three tiers (Service.category)

The overview groups services into three tiers via `Service.category`:

| Tier (label) | `category` | What lives here |
|---|---|---|
| **Site** | `core` (default) | The platform's own surfaces — `site`, `api`, `mcp`, `search` (and, later, `scheduler`). Any service an app registers via `ready()` is `core` by default. |
| **Site Monitors** | `internal` | Monitors for surfaces *this project exposes* — `enable_api` REST resources + MCP tools — picked from the live registry (`MonitoredSurface` rows). Checked cheaply **in-process**; optionally **deep-checked** by an app-published override. Home service: `internal`. See "Site Monitors" below. |
| **External Monitors** | `external` | Generic HTTP probes of arbitrary URLs (`MonitoredEndpoint` rows). Home service: `custom` (slug kept for back-compat; labelled "External Monitors"). |

`category` defaults to `"core"`, so existing/third-party services need no change.
The category labels/order live next to the registry as `CATEGORY_LABELS` /
`CATEGORY_ORDER` / `CATEGORY_HINTS`. The overview rolls each tier up to one
worst-state badge; empty tiers show a hint (staff) and are dropped on the public
board.

> Forthcoming (own pass): a **scheduler** core monitor (background-task health).

### The Site card & `Monitor.inventory()`

The **Site** tier renders as ONE collapsed card on the overview: a hero (the site
monitor's uptime % + **SLA**/**Timeline** links) over each core service —
**Database, Search, REST API, MCP** — as an **on/off row you can expand**.

The on/off state and the "what's behind it" drill-down come from each monitor's
optional **`inventory()`** hook (live, in-process): the API monitor lists its
`_api_registry` endpoints, MCP its `TOOL_REGISTRY` tools, Search its indexed models,
Site its DB connection. Implement `inventory()` on a core monitor to add a
drill-down; the default returns `{"ok": True, "summary": "", "items": []}` (no
drill-down). Keep it **cheap** — it runs on page render, not in the per-minute loop.

```python
def inventory(self) -> dict:
    return {"ok": bool(TOOL_REGISTRY), "summary": f"{len(TOOL_REGISTRY)} tools",
            "items": [{"label": n, "meta": t.description} for n, t in TOOL_REGISTRY.items()]}
```

## Add a monitor for a subsystem (the common case)

Create `apps/<yourapp>/monitors.py`:

```python
from apps.smallstack.monitors import CheckResult, Monitor, Service


class WidgetsService(Service):
    key = "widgets"                 # slug, unique
    title = "Widgets"
    description = "The widgets pipeline."
    icon = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="…"/></svg>'
    order = 60
    public = False                  # internal subsystem → staff-only on the public page


class WidgetsMonitor(Monitor):
    key = "widgets"                 # Heartbeat.monitor_key — its own timeseries
    service = "widgets"             # the Service.key this is tagged to
    title = "Queue reachable"
    public = False
    detail_url_name = "heartbeat:monitor_detail"          # its composed timeline page
    detail_url_kwargs = {"monitor_key": "widgets"}

    def check(self) -> CheckResult:
        # CHEAP liveness only — runs every minute. No HTTP, no heavy queries.
        from .queue import is_reachable

        if not is_reachable():
            return CheckResult.down("Queue unreachable")
        return CheckResult.up(note="ok")
```

Register both in `apps/<yourapp>/apps.py:ready()`, best-effort (like every other
registry):

```python
def ready(self):
    try:
        from apps.smallstack import monitors

        from .monitors import WidgetsMonitor, WidgetsService

        monitors.register_service(WidgetsService())
        monitors.register_monitor(WidgetsMonitor())
    except Exception:
        logging.getLogger(__name__).exception("Failed to register widgets monitor")
```

That's it. The monitor now appears on `/smallstack/status/` under "Widgets", the
runner records a beat for it every minute, and it gets a composed detail page at
`/smallstack/status/monitor/widgets/`. Live examples: `apps/api/monitors.py`,
`apps/mcp/monitors.py`, `apps/search/monitors.py`, `apps/heartbeat/monitors.py`.

### `CheckResult`

```python
CheckResult.up(response_time_ms=12, note="4 tools")   # healthy
CheckResult.down("schema URL not wired", response_time_ms=5)   # unhealthy
```

A monitor whose `check()` *raises* is recorded as a failure automatically (the
exception becomes the note) — the runner isolates it so one broken probe can't
crash the per-minute run or block the others.

## The cheap-check rule (the #1 thing to get right)

`check()` runs **every minute for every monitor**. Keep it sub-millisecond:
a registry count, a `reverse()`, an in-process flag. **Never** run the expensive
`*_doctor` reports (build OpenAPI spec, HTTP self-test, FTS probes) in `check()`.

```python
# ❌ DON'T — runs the full doctor every minute, on every monitor
def check(self):
    from apps.api.admin_views import _build_api_report
    report = _build_api_report()            # builds + validates OpenAPI, mints a token…
    return CheckResult.up() if all(r["status"] != "FAIL" for r in report) else CheckResult.down("…")

# ✓ DO — cheap liveness; the doctor stays on the Health page (link via Service.detail_url_name)
def check(self):
    from django.urls import NoReverseMatch, reverse
    try:
        reverse("api-schema")
    except NoReverseMatch:
        return CheckResult.down("API schema URL not wired")
    return CheckResult.up()
```

Point `Service.detail_url_name` at the existing deep page (e.g.
`"api_admin:health"`) so the heavy diagnostics stay one click away, on demand.

## The public status page (and `public` scoping)

`/status/` (anonymous) is a **standalone, branded** page — *not* the admin shell
(`StatusPageView` → `heartbeat/public_status.html`). For the brand (`BRAND_NAME`)
and every `public=True` monitor it shows:

- an **overall health pill** ("All systems operational" / "N down" / "N degraded" /
  "N under maintenance");
- a **rolling 6-month maintenance calendar** (day squares; maintenance days striped;
  today ringed; hover for the window), navigable via `?cal=YYYY-MM`;
- **stacked 1-day / 7-day / 90-day uptime bar timelines** for the site monitor
  (Claude-status style — hourly bars for 1d/7d, daily for 90d), plus a 90-day bar row
  per other public monitor;
- a **Scheduled maintenance** link → next-90-days list (`/status/maintenance/`, a
  vertical timeline) + a 6-month calendar (`/status/maintenance/calendar/`).

**Maintenance masks the live status.** While a `MaintenanceWindow` is active for a
monitor, `_get_status_data` returns `"maintenance"` (accent-coloured "Under
maintenance") instead of `down`/`degraded` — a service that's intentionally down
during its window isn't an incident. It's a single chokepoint, so the per-monitor
rows, the overview, and `/status/json/` all agree. The overall roll-up precedence is
**down > degraded > maintenance > operational** — a *real* outage on a monitor that
*isn't* in a window still wins (it never gets masked).

`public` is **per monitor** and *enforced* — not just a label. The built-in `site`
monitor is `public=True`; api/mcp/search default `public=False`; default new
internal monitors to `public=False`.

- **Staff overview** (`/smallstack/status/overview/`) shows *every* monitor;
  `public=False` ones are labelled "**· private**" (i.e. hidden from the public board).
- **Public board** (`/status/`) shows only `public=True` monitors; internal ones are
  hidden, an internal monitor's detail page returns **404** to anon (not disclosed),
  and a public monitor's detail renders only `public_safe` visualizations.

The stacked timelines are a reusable partial — **`heartbeat/_site_timelines.html`**
(expects `site_timelines` in context, built by `status.build_stacked_timelines(key)`)
— shared by the public page, the staff **Site Timeline** dashboard
(`/smallstack/status/dashboard/`), **and every per-monitor detail page** (the
`TimelineVisualization` renders it scoped to that monitor), so all three show the
same Last 24h / 7d / 90d format.

The compact **last-hour sparkline** on the overview (one bar per minute) is a
self-contained control in the same spirit: include the styles once
(`{% include "heartbeat/_hour_spark_css.html" %}`) and render per use
(`{% include "heartbeat/_hour_spark.html" with slots=<minute_timeline> only %}`,
`wide=1` for the line-filling hero variant). `slots` come from
`status._build_minute_timeline(60, key)`. Placement (which column/line it sits in)
stays in the host page; the control owns its size + palette-correct colors.

**`/status/json/` shape:** top-level fields (`status`, `uptime_*`, `sla_*`,
`monitoring_since`) describe the `site` monitor (back-compat); the `monitors[]`
array is the public board (one self-contained entry per public monitor, incl. its
`category`) — prefer it for multi-monitor consumers. **Orphaned monitors are
excluded** from both the board and `monitors[]` even if `public=True` — a monitor
whose surface was deregistered isn't a live signal worth publishing.

**Turning the public surface off:** `SMALLSTACK_PUBLIC_STATUS_ENABLED=False` (in
`.env`, then restart) makes `/status/`, `/status/json/`, and the public
scheduled-maintenance pages return **404**, and hides the "Public page"/"JSON" links
on the staff overview. The staff status tooling under `/smallstack/status/`
(overview, dashboard, SLA, per-monitor) is unaffected. The gate is at the view
level, so it covers every route pointing at those views. See
[settings → Surface toggles](settings.md).

## User-created (external) monitors — no code

Staff add HTTP monitors from **+ Add monitor** on the overview
(`/smallstack/status/endpoints/new/`). The form
(`heartbeat/crud/monitoredendpoint_form.html`) has two modes:

- **SmallStack site** (the shortcut): paste a site's base URL → it monitors
  `<url>/health/` as `GET` expecting 200, auto-generates the slug from the name, and
  a **Verify** button probes `/health/` to confirm it's a live SmallStack site
  (non-blocking — the `verify_smallstack` view).
- **Custom device**: the full field set (URL, method, expected status, timeout) with
  **segmented** Method and **toggle** Enabled / Public controls.

There's **no tier picker** — every user-created endpoint defaults to the `custom` /
**External Monitors** tier (the model default). Internal surfaces use the separate
Site Monitors picker below. Each enabled `MonitoredEndpoint` row becomes a live monitor
via a `register_monitor_source()` hook; its `monitor_key` is `ep_<slug>`
(collision-proof). On the endpoints list, a row's **name links to its timeline**
(`/smallstack/status/monitor/ep_<slug>/`, via the `CRUDView.row_link_url` hook); the
**pencil** edits it.

`MonitoredEndpointCRUDView` has `enable_api = True` + `enable_mcp = True`, so the
same monitors are manageable over **REST** (`/smallstack/api/status/endpoints/`)
and **MCP** (`list_status_endpoints`, `create/update/delete_monitored_endpoint`)
— the CRUDView magic applied to the monitoring system itself ("add a monitor for
https://… by asking Claude"). Writes auto-gate to staff (the API/MCP factory
honours the `StaffRequiredMixin`); `MonitoredEndpoint.clean()` is the SSRF /
service-validation backstop for programmatic callers, same as the form.

> ⚠️ Endpoint checks make a real **synchronous** HTTP request inside the
> per-minute run, and internal URLs are allowed (it's staff-gated). For many
> external endpoints or untrusted users, move the checks off the ping (db_worker)
> and add an SSRF allowlist in `check_http_endpoint` (`apps/heartbeat/monitors.py`).

## Site Monitors — watch an *exposed surface* (no code)

The **Site Monitors** tier watches surfaces the project itself exposes — every
`enable_api=True` REST resource (`_api_registry`) and every MCP tool
(`TOOL_REGISTRY`). Staff add one from **+ Add** on the Site Monitors card
(`/smallstack/status/site-monitors/new/`): the form's **Surface** dropdown is
populated *live* from what's exposed **right now** (grouped into API-endpoint / MCP-tool
optgroups), so you can only pick something that actually exists. Each enabled
`MonitoredSurface` row becomes a live monitor (`monitor_key = sm_<slug>`) via
`surface_monitor_source`.

A surface is identified by a **`(kind, target)`** pair — `("mcp", <tool_name>)` or
`("api", <registry_name>)` — defined in `apps/heartbeat/surfaces.py`
(`get_exposed_surfaces`, `exposed_keys`, `is_surface_exposed`). Three check modes:

- **Presence probe** (default) — confirms the surface is still exposed. A cheap,
  in-process liveness floor; an exposed surface with no deep check is "up" by virtue
  of still being wired.
- **Deep check** (opt-in) — an app publishes an override for a specific surface via
  `monitors.register_surface_check(kind, target, fn)` from `ready()`; the picked
  monitor runs `fn()` (which can actually exercise the tool/endpoint) instead of the
  presence probe. This is what catches *"the MCP server is up but `search_widgets`
  is broken"* false positives. `fn` must be cheap and return a `CheckResult`.

  ```python
  # apps/widgets/apps.py: ready()
  from apps.smallstack import monitors
  from apps.smallstack.monitors import CheckResult

  def _check_search():
      from .search import run_widget_search
      hits = run_widget_search("ping")               # exercise the real tool path
      return CheckResult.up(note=f"{len(hits)} hits") if hits else CheckResult.down("no results")

  monitors.register_surface_check("mcp", "search_widgets", _check_search)
  ```

- **Orphaned** — the picked surface is **no longer exposed** (model deleted, or
  `enable_api`/MCP turned off). This is a config change, *not* an outage: the runner
  **skips** the monitor (no fail beats, no SLA dent — `run_all_monitors` honours
  `monitor.orphaned`), and the overview renders it **muted** with a "Remove" button.
  Distinguishing *deregistered* (neutral, clean up) from *present-but-failing* (real
  DOWN) is the core of the lifecycle handling.

The picked surface's `name` defaults to the surface label; rows link to the monitor
timeline (`row_link_url`). `MonitoredSurface` is a config table — no `enable_api` /
`enable_mcp` (unlike `MonitoredEndpoint`).

### The "+ Add" modal pattern (reusable)

The overview's **+ Add** buttons (Site Monitors *and* External Monitors) open the
create form **in a modal** and stay on the page — no full navigation. The mechanism
reuses the standalone CRUDView create pages as the single source of truth, so there's
no duplicate form to maintain:

- both form templates pick their base via
  `{% extends request.META.HTTP_X_REQUESTED_WITH|yesno:"smallstack/_form_modal_base.html,smallstack/base.html" %}`
  — a normal visit renders the full page; an `X-Requested-With: XMLHttpRequest`
  fetch renders a **bare fragment** (just the form card, breadcrumb header suppressed);
- the overview (`status_overview.html`) fetches that fragment into a modal,
  **re-executing injected `<script>` tags** (so the endpoint form's mode-toggle /
  Verify JS runs), and the form carries `action="{{ request.path }}"` so it posts to
  the create URL, not the overview;
- submit is AJAX: a **302 redirect = success** → `location.reload()`; a **200** =
  validation errors → the returned fragment is re-injected into the modal.

The `<a href>` is the no-JS fallback (it still navigates to the full create page).
To give another CRUDView form the same treatment: add the `yesno` extends + an
`action="{{ request.path }}"` to its template, and trigger it with a
`data-add-monitor`-style hook.

## Add a visualization (new chart, zero monitor changes)

Visualizations render a monitor's timeseries; they're registered independently,
so a new panel appears on **every** monitor's detail page without touching any
monitor. Add a `Visualization` subclass + a partial, then register it:

```python
from apps.smallstack.visualizations import Visualization

class SparklineVisualization(Visualization):
    key = "sparkline"
    title = "30-day sparkline"
    order = 30
    template = "heartbeat/visualizations/sparkline.html"
    public_safe = True              # may appear on the public page

    def get_context(self, monitor_key: str) -> dict:
        from apps.heartbeat.status import _build_24h_timeline   # status helpers are keyed by monitor_key
        return {"points": _build_24h_timeline(monitor_key)}
```

```python
# in ready()
from apps.smallstack import visualizations
visualizations.register(SparklineVisualization())
```

All status math lives in `apps/heartbeat/status.py`, every function keyed by
`monitor_key` — `_get_status_data`, `_calc_uptime`; the timelines
(`_build_minute_timeline`, `_build_24h_timeline`, `_build_hourly_timeline` for the
1d/7d bars, `_build_daily_timeline` for the 90-day bars); and the public calendar +
maintenance helpers (`_build_calendar_months`, `_maintenance_by_date`,
`_upcoming_maintenance`, sharing `_daily_uptime_map`). Call those; never query
`Heartbeat` directly in a visualization.

## How beats get recorded

`apps.heartbeat.services.run_all_monitors()` iterates the registry and records
one `Heartbeat(monitor_key=…)` per monitor per minute. It's invoked by the cron
ping (`POST /heartbeat/ping/`, localhost-only) and `manage.py heartbeat`. In dev,
run `uv run python manage.py heartbeat` (or hit the ping) to record a round.

## Uptime, coverage, and "warming up"

- **24h** uptime is exact (raw beats). **Overall / 7d** blend pruned
  `HeartbeatDaily` summaries (older span) with raw beats (recent span) — see
  `_uptime_over_window` in `apps/heartbeat/status.py`.
- **Coverage caveat:** overall uptime is only as complete as daily-summary
  coverage. An in-epoch span with *neither* raw beats *nor* a summary counts as
  "no data" (not downtime), so overall can over-report if summaries are missing
  (pruning never ran, a partial restore). The SLA page shows the coverage % inline
  on the Overall stat-card label (`_coverage_since_epoch`) and raises a **"Low data
  coverage — the headline % may over-report"** warning when it's `< 90%`.
- **Warming up:** a monitor younger than `HEARTBEAT_WARMUP_MINUTES` (default 60)
  shows a neutral "warming up" pill on the overview/board instead of a 24h % that
  doesn't yet represent a full window.

## Per-monitor SLA

Every monitor has its own SLA targets and maintenance windows — `HeartbeatEpoch`
is keyed by `monitor_key` (unique per monitor) with its own `service_target` /
`service_minimum` (defaults 99.9 / 99.5). The SLA page is parameterized by
`?monitor=<key>` (default `site`): each monitor's detail page links to **SLA** →
`/smallstack/status/sla/?monitor=<key>`, where you set that monitor's
goal/commitment, reset its epoch, and schedule maintenance windows scoped to it.
Omitting the param is the original site-only page. Reset writes only that monitor's
epoch (`HeartbeatEpoch.reset(monitor_key=…)`), leaving the others untouched.

**These values are independent per monitor — there is no inheritance.** A
`MonitoredEndpoint`'s SLA targets and `MaintenanceWindow`s belong to *its*
`monitor_key` (`ep_<slug>`) and have no relationship to the `site` monitor's: the
site's 99.9% target and its maintenance windows don't apply to an endpoint, and an
endpoint's don't roll up into the site. Each monitor is scored, classified
(`_build_daily_timeline` uses the per-monitor target), and excused-during-maintenance
purely against its own `HeartbeatEpoch` + `MaintenanceWindow` rows. If you want a
monitor to share the site's commitment, set the same numbers on its epoch.

The SLA page (`heartbeat/sla.html`) is a **tabbed card** (SLA targets / How it works,
Save bar at the card bottom) beside a half-page **Maintenance Windows** panel (compact
table, icon Edit/Delete actions); the daily-summary table shows the last 7 days.

## Maintenance windows from the CLI

A `MaintenanceWindow` marks planned downtime: while one is active the status page
reads **"Under maintenance"** (not "Down") and the SLA calculation excludes the
span (`MaintenanceWindow.is_in_maintenance()` / `get_excluded_ranges()`). Besides
the staff form on the SLA page, there's a management command — use it for scripts,
AI/automation, and deploys:

```bash
# Open a 15-minute window starting now (typical for a deploy)
uv run python manage.py maintenance open --minutes 15 --title "Deploy v1.2.3"

# Explicit bounds (naive times are read in the project timezone, like the form)
uv run python manage.py maintenance open --start "2026-07-01 02:00" --end "2026-07-01 03:00" --title "DB migration"

# Scope to a non-site monitor, or record without excluding from SLA
uv run python manage.py maintenance open --minutes 30 --monitor ep_docs-site
uv run python manage.py maintenance open --minutes 30 --no-sla-exclude   # informational only

uv run python manage.py maintenance close          # end active windows now (keeps the row)
uv run python manage.py maintenance close --delete-future   # also drop not-yet-started windows
uv run python manage.py maintenance list [--active] [--json]
```

The shared helpers live in `apps/heartbeat/maintenance.py`
(`open_window` / `open_window_for` / `close_windows` / `list_windows`) — call
those directly from other Python rather than re-implementing the model writes.

### SLA-excluding a deploy (Kamal)

Opt in by setting `MAINTENANCE_ON_DEPLOY=true` (and optionally
`MAINTENANCE_WINDOW_MINUTES`) in `.kamal/secrets`. Then `.kamal/hooks/pre-deploy`
opens a **bounded** window before the container swap and `.kamal/hooks/post-deploy`
closes it once the new container is healthy — both via `kamal app exec`, so no
separate token is needed (it rides the SSH channel Kamal already uses). The window
is bounded by `--minutes`, so an aborted deploy that never reaches post-deploy
self-heals when the window expires. Left unset, the hooks no-op.

## Trust signals (overview + board)

- **Overall-health banner** — every visible monitor rolls up to one banner at the
  top of the staff overview and the public board: green "All systems operational",
  amber "N degraded", or red "N down". The most-scannable signal on the page.
- **Stale-heartbeat banner** (staff only) — if the freshest beat across *all*
  monitors is older than `5 ×` the expected interval, a warning banner says the
  per-minute runner probably isn't running (the #1 "the feature is broken" cause
  when it's really a missing cron ping). Computed from `_last_beat_age_seconds()`.

## Registry API quick reference

```python
from apps.smallstack import monitors
monitors.register_service(service)        # idempotent on service.key
monitors.register_monitor(monitor)        # idempotent on monitor.key
monitors.register_monitor_source(fn)      # fn() -> Iterable[Monitor], called fresh each lookup (DB-backed)
monitors.register_surface_check(kind, target, fn)  # fn() -> CheckResult — deep check for a picked Site Monitor surface
monitors.get_services()                   # ordered
monitors.get_monitors(service=None)       # all, or filtered by service tag
monitors.get_monitor(key)
```

## Anti-patterns

❌ **Running a `*_doctor` / HTTP call / heavy query in `check()`** — it runs every
minute for every monitor. Keep it cheap; link the doctor via `Service.detail_url_name`.

❌ **Querying `Heartbeat.objects` without a `monitor_key` filter** in a status view
or visualization — it blends every monitor's data together. Always go through the
`status.py` helpers (they're keyed) or filter by `monitor_key`.

❌ **Tagging a monitor to an unregistered `service`** — it runs every minute but
never appears on the overview (which groups by registered services). Register the
`Service`, or tag to an existing one (`site`/`api`/`mcp`/`search`/`custom`).

❌ **A second status page / modal for a monitor** — every monitor already gets a
composed detail page at `/smallstack/status/monitor/<key>/` built from the
visualization registry. Add a `Visualization`, don't fork the page.

❌ **Hard-coded colors in a visualization partial** — use palette state variables
(`var(--success-fg)`, `var(--error-fg)`, …) like `visualizations/timeline.html`.
See `modern-dark-theme.md`.

## Related skills

- `dashboard-widgets.md` — the at-a-glance widgets on the central `/smallstack/`
  dashboard (a different surface; a monitor's status can feed one)
- `dashboard-cards.md` — the `{% stat_card %}` tiles the uptime visualization uses
- `modern-dark-theme.md` — palette-correct colors for visualization partials
- `cli-tools.md` — `manage.py heartbeat` and the status CLI surface
