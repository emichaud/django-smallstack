# Skill: Activity Tracking

This skill describes the built-in HTTP request logging system in SmallStack.

## Overview

The `apps.activity` app provides lightweight, automatic request logging via middleware. Every HTTP request (except excluded paths) is recorded with timing, user, status code, and IP address. Old rows are probabilistically pruned to keep the table bounded.

## File Locations

```
apps/activity/
├── middleware.py    # ActivityMiddleware - records requests, auto-prunes
├── models.py       # RequestLog model
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
| `timestamp` | DateTimeField(auto_now_add) | When the request occurred |
| `response_time_ms` | PositiveIntegerField | Response time in milliseconds |
| `ip_address` | GenericIPAddressField(null) | Client IP (supports X-Forwarded-For) |
| `user_agent` | TextField | Browser user agent string |

Indexes on: `timestamp`, `path`, `status_code`.

## Configuration

All settings are in `config/settings/base.py` and can be overridden via environment variables:

```python
# Maximum rows to keep in the RequestLog table
ACTIVITY_MAX_ROWS = config("ACTIVITY_MAX_ROWS", default=10000, cast=int)

# Prune check frequency (1-in-N requests triggers a prune check)
ACTIVITY_PRUNE_INTERVAL = config("ACTIVITY_PRUNE_INTERVAL", default=100, cast=int)

# Paths to exclude from logging (prefix match)
ACTIVITY_EXCLUDE_PATHS = [
    "/static/", "/media/", "/favicon.ico",
    "/health/", "/admin/jsi18n/", "/__debug__/",
]
```

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
