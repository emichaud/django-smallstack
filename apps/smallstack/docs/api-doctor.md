# API Doctor & Activity

> **Building this?** Read the agent-facing skill first: [`docs/skills/api-doctor.md`](../../../docs/skills/api-doctor.md). It's prescriptive (what to do); this page is the reference (why + worked examples).

The `/smallstack/api/` admin pages give you a one-pane sanity check for the REST surface, plus an operational view of `/api/*` traffic and the threat signals derived from it.

Two pages, both staff-gated:

- **`/smallstack/api/`** — Health diagnostics
- **`/smallstack/api/activity/`** — per-endpoint operational view + threat panel + filterable request log

The CLI equivalent is `python manage.py api_doctor`. The web UI re-binds the same `_check_*` methods to HTML, so the two stay in lockstep.

## Health page

Renders nine read-only checks as colored cards:

| Check | What's verified |
|---|---|
| `openapi-spec-validator` | The validator dependency is importable |
| `Installed apps` | `apps.smallstack` is registered; warns on missing `apps.activity` or `axes` (the threat panel relies on both) |
| `API registry` | At least one CRUDView has `enable_api = True` (warns at 0 — Swagger would be empty) |
| `URL conf` | `/api/schema/`, `/api/schema/openapi.json`, `/api/docs/`, `/api/redoc/`, `/api/auth/token/`, `/api/auth/me/` all resolve |
| `Swagger / ReDoc shells` | Both UI shells return 200 and contain their CDN script tag |
| `OpenAPI validity` | The generated spec passes OpenAPI 3.0.3 validation |
| `Endpoint consistency` | Every entry in `_api_registry` resolves to a live list URL |
| `Orphan files` | Files declaring `enable_api = True` that aren't reachable through `INSTALLED_APPS` (typically a missing `from . import views` in `AppConfig.ready()`) |
| `APIToken inventory` | Count of active vs revoked tokens |

The **Run Self-Test** button (top right) does what `make api-test` does, except in-process: mints a temp readonly `APIToken`, hits `/api/schema/` + `/api/schema/openapi.json` + the first list endpoint, then revokes the token in a `finally` block. The result swaps into the page via htmx — no token is ever left active, even if the test fails mid-stream.

## Activity page

Three regions stacked top to bottom.

### Top endpoints

Aggregates `RequestLog` rows under `/api/*` across the selected `since` window. Columns: Path · Hits · Avg ms · Errors · Error rate. The error-rate column is colored red ≥10% and orange ≥1% so anomalies pop without you having to sort.

### Threat signals

The heuristics in `apps/api/threats.py` run on every page load. Each detector is a pure function over `RequestLog` and `axes.models.AccessAttempt`, returning a list of `ThreatSignal` dataclasses; the view aggregates and orders by severity.

| Detector | Severity | Threshold |
|---|---|---|
| Active axes lockouts | HIGH | `failures_since_start >= AXES_FAILURE_LIMIT` (5) within the cooloff window |
| Auth-failure burst | HIGH | ≥ 10 × 401/403 on `/api/*` from one IP in the last hour |
| Path scanning | MEDIUM | ≥ 10 distinct paths **and** ≥ 20 × 404s from one IP in the last hour |
| Request burst | MEDIUM | ≥ 200 requests from one IP in the last minute |
| Scanner user-agent | MEDIUM | UA matches `sqlmap`, `nikto`, `nmap`, `masscan`, `zgrab`, `dirbuster`, `gobuster`, `ffuf`, `wpscan`, `acunetix`, `nessus`, `burpsuite`, `metasploit`, `openvas` (substring, case-insensitive) |
| Revoked-token use | LOW | Any `/api/*` request authenticated with an `is_active=False` APIToken in the last 24h |

**What this is**: observation. Each row links the offending IP back into the filtered request log so you can investigate. **What it isn't**: a WAF or active response. There is no "block this IP" button — that's the operator's call. Use [`axes`](https://django-axes.readthedocs.io/) for active lockouts, your server firewall for IP blocks, or the [token manager](api-tokens.md) to revoke compromised keys.

**False-positive shape** worth knowing:

- A single staff user mistyping their password 10 times in an hour will fire the auth-failure burst (HIGH). Pair it with the user/IP in the log table before reacting.
- A legitimate test script hitting many 404s during development will fire path scanning. Filter by `?since=1h` and check the request log to confirm it's an internal IP.
- A monitoring tool that crawls `/api/missing-endpoint/` repeatedly will look like reconnaissance. Add the monitor's UA to an allowlist if it becomes noisy (no current allowlist UI; edit `SCANNER_UA_PATTERNS` in `apps/api/threats.py`).

### Recent /api requests

The full request log filtered to `/api/*`. Filters: `since` window, method, status class, IP, user, scanner-UA toggle. Paginated 50 per page. The filter form only applies to this region — the top-endpoints summary and threat panel always reflect the current `since` window.

## Dashboard widget

`/smallstack/` shows an **API** card next to the **MCP** card. Cheap to render — no HTTP, no DB writes. It shows endpoint count + the highest-priority signal:

| Condition | Status | Detail |
|---|---|---|
| 1+ HIGH-severity threat in last 24h | `degraded` | `N high-severity threats` |
| Orphan files detected | `degraded` | `N unregistered files` |
| No CRUDView with `enable_api=True` | `operational` | `Awaiting enable_api` |
| Clean | `operational` | `All checks passing` |

## What we can't see

Worth being honest about so you don't misinterpret an empty threat panel as "we're safe":

- **No geoip** — we don't ship a geo database. An IP from a high-risk country isn't a signal here; it's a signal in your edge layer.
- **No TLS handshake info** — if there's a cipher-downgrade attack, this page can't tell you.
- **No request-body sampling** — payload-based attacks (SSRF, SQLi via body, command injection) aren't visible unless they produce a downstream 401/403/404 that the heuristics already catch.
- **No per-key cross-tenant analytics** — the request log shows which token authed a request, but doesn't profile usage shape across tenants.

Each of those is a scoped feature; raise an issue if you need one.

## Related

- [`api-documentation.md`](api-documentation.md) — Swagger UI + ReDoc + the OpenAPI builder
- [`api-tokens.md`](api-tokens.md) — token mint / reveal / revoke
- [`mcp-admin.md`](mcp-admin.md) — the parallel module for the MCP surface
- [`activity-tracking.md`](activity-tracking.md) — `RequestLog` itself
