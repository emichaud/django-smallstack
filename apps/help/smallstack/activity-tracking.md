---
title: Activity Tracking
description: Lightweight request logging with staff dashboard and automatic pruning
---

# Activity Tracking

Most Django starters have zero visibility into whether anyone is actually using the site. Full analytics solutions like Umami or Plausible are overkill when you just want to answer "is anyone visiting?" {{ project_name }} includes a lightweight activity tracking system that logs HTTP requests to the database, prunes automatically, and gives staff users a live dashboard — with zero external dependencies.

## What You Get

- **Staff dashboard** at `/activity/` — request stats, user activity, theme preferences
- **Request detail page** at `/activity/requests/` — top paths, status codes, recent requests with live refresh
- **User detail page** at `/activity/users/` — top users, signups, inactive accounts
- **Automatic pruning** — table stays bounded at a configurable row cap (default 10,000)
- **htmx live-refresh** — detail page tables auto-update every 30 seconds without page reload
- **Zero config** — works out of the box after `make setup`

## How It Works

### Middleware

The `ActivityMiddleware` sits at the end of the middleware stack (after `AuthenticationMiddleware` so it has access to `request.user`). For each request:

1. Check if the path starts with an excluded prefix — if so, skip it
2. Time the request using `time.monotonic()`
3. After the response, INSERT one row into the `RequestLog` table
4. Every ~100 requests (configurable), check if the table exceeds the row cap and prune oldest rows

The middleware is wrapped in `try/except` — database errors never break actual requests.

### Excluded Paths

These paths are excluded by default (no logging overhead, no noise in the dashboard):

| Path | Reason |
|------|--------|
| `/static/` | Static file serving |
| `/media/` | Media file serving |
| `/favicon.ico` | Browser favicon requests |
| `/health/` | Health check endpoint |
| `/admin/jsi18n/` | Django admin JavaScript i18n |
| `/__debug__/` | Django Debug Toolbar |

### The RequestLog Model

Each logged request captures:

| Field | Type | Description |
|-------|------|-------------|
| `path` | CharField(2048) | Request path |
| `method` | CharField(10) | GET, POST, PUT, etc. |
| `status_code` | SmallIntegerField | HTTP response status |
| `user` | FK → User | Authenticated user (null for anonymous) |
| `timestamp` | DateTimeField | When the request was made (indexed) |
| `response_time_ms` | IntegerField | Response time in milliseconds |
| `ip_address` | GenericIPAddressField | Client IP (supports X-Forwarded-For) |
| `user_agent` | TextField | Browser/client user agent string |

Indexed on `timestamp`, `path`, and `status_code` for fast dashboard queries.

## Configuration

All settings are in `config/settings/base.py` and can be overridden via environment variables:

```python
# Maximum rows to keep in the RequestLog table
ACTIVITY_MAX_ROWS = 10000  # env: ACTIVITY_MAX_ROWS

# Check for pruning every N requests (probabilistic)
ACTIVITY_PRUNE_INTERVAL = 100  # env: ACTIVITY_PRUNE_INTERVAL

# Paths to exclude from logging
ACTIVITY_EXCLUDE_PATHS = [
    "/static/", "/media/", "/favicon.ico",
    "/health/", "/admin/jsi18n/", "/__debug__/",
]
```

### Changing the Row Cap

Set the `ACTIVITY_MAX_ROWS` environment variable:

```bash
# In .env
ACTIVITY_MAX_ROWS=50000
```

Or override directly in settings:

```python
# config/settings/production.py
ACTIVITY_MAX_ROWS = 25000
```

### How Pruning Works

Pruning is **probabilistic** to avoid running a COUNT query on every request:

1. On each logged request, a random number between 1 and `ACTIVITY_PRUNE_INTERVAL` is generated
2. If the number is 1 (1-in-100 chance by default), the middleware checks the row count
3. If count exceeds `ACTIVITY_MAX_ROWS`, it deletes the oldest rows beyond the cap
4. This means the table may temporarily exceed the cap by up to ~100 rows, which is fine

This approach means:
- **99% of requests** have zero overhead beyond the INSERT
- **1% of requests** run a quick COUNT + conditional DELETE
- The table stays bounded without a background task or cron job

### Excluding Additional Paths

To exclude your own paths (e.g., an API endpoint you don't want tracked):

```python
# config/settings/base.py
ACTIVITY_EXCLUDE_PATHS = [
    "/static/", "/media/", "/favicon.ico",
    "/health/", "/admin/jsi18n/", "/__debug__/",
    "/api/webhooks/",  # Your custom exclusion
]
```

## The Dashboard

### Overview (`/activity/`)

The main dashboard shows six stat cards at a glance:

- **Requests** — total tracked requests
- **Avg Response** — average response time in ms
- **4xx Errors** — client error count
- **5xx Errors** — server error count
- **Users** — total registered users
- **New (30d)** — signups in the last 30 days

Below the stats, two summary cards show top paths with hit counts and user stats (theme preferences, color palettes, most active users). "View All" links navigate to the detail pages.

### Requests Detail (`/activity/requests/`)

Full request log with:
- Status code breakdown (2xx/3xx/4xx/5xx)
- Top 25 paths with hit counts and average response times
- Recent 50 requests with method, path, status, user, response time, and IP
- **Live refresh** — the recent requests table auto-updates every 30 seconds via htmx
- **Manual refresh** button for immediate updates

### Users Detail (`/activity/users/`)

User activity breakdown with:
- Theme and color palette preference counts
- Top 25 users by request count with average response time and last seen
- Recent signups (last 30 days) with join date and last login
- Recent authenticated requests with live refresh
- Users with no tracked requests (inactive accounts)

## htmx Integration

The activity app demonstrates several htmx patterns that serve as reference examples:

### Dual-Response Views

The detail views return different templates based on whether the request came from htmx:

```python
def get(self, request, *args, **kwargs):
    context = self.get_context_data(**kwargs)
    if request.htmx:
        return TemplateResponse(request, self.partial_template_name, context)
    return TemplateResponse(request, self.template_name, context)
```

Normal navigation gets the full page. htmx polling gets just the table fragment.

### Polling with hx-trigger

The partial templates include self-refreshing behavior:

```html
<div id="recent-requests"
     hx-get="{% url 'activity:requests' %}"
     hx-trigger="every 30s"
     hx-swap="outerHTML">
    <!-- table content -->
</div>
```

### Manual Refresh

A button triggers an immediate refresh of the live table:

```html
<button hx-get="{% url 'activity:requests' %}"
        hx-target="#recent-requests"
        hx-swap="outerHTML">
    Refresh
</button>
```

## Access Control

All activity views require:
- **Authentication** — redirects to login if not logged in
- **Staff status** — returns 403 if `user.is_staff` is False

The sidebar shows the Activity link only inside the `{% if user.is_staff %}` block.

## Admin Integration

`RequestLog` is registered in Django admin as a read-only model:
- List view with timestamp, method, path, status code, user, response time, IP
- Filters by method and status code
- Search by path, IP, and username
- Date hierarchy on timestamp
- No add/change permissions (delete only for superusers)

Browse at `/admin/activity/requestlog/`.

## Performance Notes

- **One INSERT per request** — negligible overhead
- **Probabilistic pruning** — avoids COUNT on most requests
- **Excluded static paths** — no logging for assets
- **Indexed fields** — dashboard queries use indexes on timestamp, path, status_code
- **SQLite friendly** — works perfectly with SQLite's WAL mode for concurrent reads/writes
