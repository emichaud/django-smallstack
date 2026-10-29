---
name: activity-tracking
description: "HTTP request logging middleware and configuration"
license: MIT
metadata:
  source: "docs/skills/activity-tracking.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/activity-tracking.md` by `make skills-index` — edit the source, not this file.

# Skill: Activity Tracking

This skill describes the built-in HTTP request logging system in SmallStack.

## Overview

The `apps.activity` app provides lightweight, automatic request logging via middleware. Every HTTP request (except excluded paths) is recorded with timing, user, status code, and IP address. Old rows are probabilistically pruned to keep the table bounded.

## File Locations

```
apps/activity/
├── middleware.py    # ActivityMiddleware - records requests (+ the matched route)
├── models.py       # RequestLog model
├── services.py     # Windows, summaries, histogram, roll-ups, probe classifier
├── views.py        # Dashboard, Requests, Users (+ detail), Resources (+ detail)
├── admin.py        # Read-only admin with filters and date hierarchy
├── apps.py         # App config
└── migrations/
```

## How It Works

`ActivityMiddleware` is registered in `MIDDLEWARE` in `config/settings/base.py`. For each request:

1. Check if the path is excluded (static, media, health check, etc.)
2. If not excluded, time the request and record it after the response
3. Store the `request.id` (set by `RequestIDMiddleware`) for correlation
4. Probabilistically prune old rows (1-in-N chance per request, controlled by `ACTIVITY_PRUNE_INTERVAL`)

### Request ID Correlation

Every `RequestLog` entry includes a `request_id` field populated by the `RequestIDMiddleware` (first in the middleware stack). This allows correlating a specific user-reported issue to the exact log entry. The same ID is returned to the client in the `X-Request-ID` response header.

## RequestLog Model

| Field | Type | Description |
|-------|------|-------------|
| `path` | CharField(2048) | Request path |
| `method` | CharField(10) | HTTP method (GET, POST, etc.) |
| `status_code` | PositiveSmallIntegerField | Response status code |
| `user` | ForeignKey(User, null) | Authenticated user or null |
| `request_id` | CharField(255) | Unique request ID (from `X-Request-ID` header) |
| `route` | CharField(255) | The matched URL pattern (`/smallstack/approvals/requests/<int:pk>/`), stamped from `request.resolver_match`; empty when nothing matched. The activity pages group by it (the **resource**). |
| `timestamp` | DateTimeField(auto_now_add) | When the request occurred |
| `response_time_ms` | PositiveIntegerField | Response time in milliseconds |
| `ip_address` | GenericIPAddressField(null) | Client IP (supports X-Forwarded-For) |
| `user_agent` | TextField | Browser user agent string |

Indexes on: `timestamp`, `path`, `status_code`, `route`.

`RequestLog.resource` is the grouping key the pages use: the route, else the raw path.

## Configuration

All settings are in `config/settings/smallstack.py` and can be overridden via environment variables:

```python
# Maximum rows to keep in the RequestLog table
ACTIVITY_MAX_ROWS = config("ACTIVITY_MAX_ROWS", default=10000, cast=int)

# Prune check frequency (1-in-N requests triggers a prune check)
ACTIVITY_PRUNE_INTERVAL = config("ACTIVITY_PRUNE_INTERVAL", default=100, cast=int)

# Default window for the activity pages
ACTIVITY_DEFAULT_WINDOW = config("ACTIVITY_DEFAULT_WINDOW", default="7d")

# Paths to exclude from logging (prefix match)
ACTIVITY_EXCLUDE_PATHS = [
    "/static/", "/media/", "/favicon.ico",
    "/health/", "/admin/jsi18n/", "/__debug__/",
]
```

## The activity pages (`/smallstack/activity/`)

Staff-only, all scoped to a **time window** (`?window=1h|24h|7d|30d|all`,
default `ACTIVITY_DEFAULT_WINDOW`) chosen in every page header. Tabs load over
htmx and push their URL, so a tab + window + filter combination is shareable.

| Page | URL | What it answers |
|------|-----|-----------------|
| Dashboard | `activity:dashboard` | Headline numbers, the traffic histogram, the probing card, top resources, most active users, latest requests |
| Requests | `activity:requests` | The log. Tabs: Recent, Top paths, Errors, By method, **Probes**. Every tab has a filter bar (status, method, path contains, IP, anonymous-only) |
| Users | `activity:users` | Per-user roll-up (hits, errors, paths, latency, last seen), the signed-in stream, signups and inactive users for the window, theme preferences |
| User detail | `activity:user_detail` (`users/<pk>/`) | One user: histogram, status mix, top resources, addresses, clients, API tokens, and their requests / resources / errors |
| Resources | `activity:resources` | One row per URL pattern (plus unmatched paths): hits, users, errors, latency, last hit |
| Resource detail | `activity:resource_detail` (`resources/detail/?r=`) | One resource: histogram, who uses it, status + method mix, sample paths, requests / users / slowest |

Every request row links to its resource, its user, and its IP (the log
filtered to that address), and to the telemetry log lines for its
`request_id`. Tables are `crud-table`s with sortable, resizable columns.

All the numbers come from `apps/activity/services.py` — one window parser,
one aggregate (`status_summary`), one histogram, one user / resource roll-up
— so the pages never disagree with each other. Build on those helpers rather
than re-querying `RequestLog` in a template or view.

### Probing & noise

`services.probe_report()` classifies the window's traffic at read time (so
the rules can change without touching stored rows):

- **Signatures** on a single request: an *error* response to a path only
  scanners ask for (`.php`, `/wp-admin`, `/.env`, `/.git`, `phpmyadmin`,
  `cgi-bin`, traversal, backup dumps, app-server consoles — see
  `DEFAULT_PROBE_PATTERNS`) or a user agent only scanners send
  (`DEFAULT_SCANNER_AGENTS`; curl / python-requests are deliberately *not*
  on it).
- **Behaviour** of an anonymous IP over the window: at least half its
  requests were 404s across many distinct paths, a fifth or more were
  401/403, or django-axes recorded repeated failed logins / a lockout.
- A flagged IP contributes only its **error rows** as evidence. Its ordinary
  traffic is never swept in — a NAT or a dev box shares one address with
  legitimate use.

The Requests page shows the report as a warning band (addresses with their
reasons, most-probed paths) and a **Probes** tab with every flagged request;
flagged rows carry a `!` glyph in every table. Tune with:

```python
ACTIVITY_PROBE_PATTERNS_EXTRA = [r"/secret-admin"]   # more path regexes (case-insensitive)
ACTIVITY_SCANNER_AGENTS_EXTRA = ["evilbot"]          # more UA substrings
ACTIVITY_PROBE_IGNORE_PATHS = ["/legacy.php"]        # prefixes your site really serves
```

The panel identifies; it does not block. Pair it with django-axes (already
wired) or your proxy's rate limiting for enforcement.

## Admin Interface

The `RequestLogAdmin` provides a read-only view at `/admin/activity/requestlog/`:

- **List display:** timestamp, method, path, status_code, user, response_time_ms, ip_address
- **Filters:** method, status_code
- **Search:** path, ip_address, username
- **Date hierarchy:** timestamp
- **Permissions:** read-only; only superusers can delete

## Excluding Additional Paths

To exclude paths from logging, add to `ACTIVITY_EXCLUDE_PATHS` in settings:

```python
ACTIVITY_EXCLUDE_PATHS = [
    "/static/", "/media/", "/favicon.ico",
    "/health/", "/admin/jsi18n/", "/__debug__/",
    "/api/heartbeat/",  # Add your custom exclusions
]
```

## Pruning Behavior

Pruning is **probabilistic** to avoid performance overhead:
- On each logged request, there's a 1-in-`ACTIVITY_PRUNE_INTERVAL` chance of checking the row count
- If rows exceed `ACTIVITY_MAX_ROWS`, the oldest rows beyond the limit are deleted
- This keeps the table bounded without running a scheduled job

## Best Practices

1. **Keep ACTIVITY_MAX_ROWS reasonable** — 10,000 rows is a good default for most projects
2. **Exclude noisy paths** — Add health checks, API polling endpoints, etc. to the exclude list
3. **Use the admin** — The date hierarchy and filters make it easy to investigate issues
4. **Don't rely on it for analytics** — This is for operational visibility, not user analytics
