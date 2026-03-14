---
title: Activity Tracking
description: Lightweight, privacy-respecting analytics built into your site — no external services, no data leaks
---

# Activity Tracking

**Is anyone using my site?** That is the first question every developer asks after deploying a project. Most Django starters leave you guessing. Full-blown analytics platforms like Google Analytics, Plausible, or Umami are powerful, but they are overkill when you just want to answer a few basic questions:

- Is anyone visiting my site?
- What pages are popular?
- Where is traffic coming from?
- Are there errors I should know about?

{{ project_name }} ships with a **lightweight, privacy-respecting activity tracker** that answers all of these out of the box. Every request is logged to your own database — no data ever leaves your server, no third-party scripts are injected into your pages, and no cookie banners are required. It is self-hosted analytics for people who care about simplicity and privacy.

> **Perfect for:** hobby projects, personal sites, club and organization pages, departmental tools, internal apps, and any site where you want basic visibility without the overhead of a full analytics stack.

## What It Tracks

Each HTTP request is captured with the following data:

| Field | What it records |
|-------|-----------------|
| **Path** | The URL path requested (e.g., `/about/`, `/blog/my-post/`) |
| **Method** | HTTP method — GET, POST, PUT, DELETE, etc. |
| **Status code** | Response status (200, 301, 404, 500, etc.) |
| **User** | The authenticated user, if logged in (null for anonymous visitors) |
| **Timestamp** | When the request was made |
| **Response time** | How long the server took to respond, in milliseconds |
| **IP address** | Client IP (supports `X-Forwarded-For` for reverse proxies) |
| **User agent** | Browser or client identification string |

All of this stays in your database. Nothing is sent to external services.

## The Dashboard

The activity dashboard is available to **staff users only** at `/activity/`. It provides three views: an overview dashboard, a requests detail page, and a user activity page.

### Overview (`/activity/`)

The main dashboard gives you a high-level snapshot of your site's health and usage. At the top, six stat cards display key metrics at a glance:

| Stat | What it shows |
|------|---------------|
| **Requests** | Total tracked requests in the database |
| **Avg Response** | Average server response time in milliseconds |
| **4xx Errors** | Count of client errors (404s, 403s, etc.) |
| **5xx Errors** | Count of server errors (500s) |
| **Users** | Total registered user accounts |
| **New (30d)** | User signups in the last 30 days |

Each stat card is **clickable** — tapping one opens a modal with the detailed records behind that number (recent requests, error logs, or user lists).

Below the stats, the page splits into two side-by-side summary cards:

- **Request Activity** — shows the top 8 most-visited paths with hit counts, plus a colored status code breakdown bar (2xx/3xx/4xx/5xx). A "View All" button navigates to the full requests detail page.
- **Users** — shows the most popular theme preference (with a dark/light split bar), and the top 5 most active users ranked by request count. A "View All" button navigates to the user activity page.

At the bottom, a **Latest Requests** card shows the 5 most recent requests with toggleable "All" and "Errors" tabs. Each row displays the timestamp, path, status code (color-coded for errors), user, and response time.

### Requests Detail (`/activity/requests/`)

The requests page provides a deep dive into traffic patterns. The header shows the total request count alongside a status code group breakdown (2xx, 3xx, 4xx, 5xx counts displayed as individual badges).

Four htmx-powered tabs let you slice the data without page reloads:

| Tab | What it shows |
|-----|---------------|
| **Recent** | A sortable, paginated table of all requests — timestamp, method, path, status, user, response time, and IP address. Columns are sortable by clicking headers. |
| **Top Paths** | Ranked list of paths by hit count, with average response time for each. Useful for finding your most popular pages. |
| **Errors** | Status code breakdown for the last 24 hours, with clickable status code filters. Shows a paginated list of error responses (3xx+). |
| **By Method** | Breakdown of HTTP methods (GET, POST, etc.) over the last 24 hours, with clickable method filters and a paginated request list. |

All tables support **pagination** and **sorting** via django-tables2.

### User Activity (`/activity/users/`)

The user activity page focuses on who is using your site. The header shows total user count and 30-day signup count.

A **Theme Usage** card shows a horizontal stacked bar chart for each color palette, split by dark/light mode preference — giving you a quick visual of how users have customized their experience.

Four tabs provide different user views:

| Tab | What it shows |
|-----|---------------|
| **Top Users** | Users ranked by request count, with average response time and last-seen timestamp |
| **Activity** | Paginated feed of all authenticated user requests, most recent first |
| **Signups** | Users who registered in the last 30 days, sorted by join date |
| **Inactive** | Users with zero tracked requests — accounts that registered but never used the site |

## How It Works

### Middleware

The `ActivityMiddleware` sits at the end of the middleware stack (after `AuthenticationMiddleware` so it has access to `request.user`). For each request it:

1. Checks if the path starts with an excluded prefix — if so, skips it entirely
2. Times the request using `time.monotonic()`
3. After the response, inserts one row into the `RequestLog` table
4. Wraps everything in `try/except` — database errors never break actual requests

The middleware path is fast: one INSERT per request, no reads, no aggregation.

### Excluded Paths

These paths are excluded by default to reduce noise and avoid logging static asset requests:

| Path | Reason |
|------|--------|
| `/static/` | Static file serving |
| `/media/` | Media file serving |
| `/favicon.ico` | Browser favicon requests |
| `/health/` | Health check endpoint |
| `/admin/jsi18n/` | Django admin JavaScript i18n |
| `/__debug__/` | Django Debug Toolbar |

### Automatic Pruning

The request log table does not grow forever. A **scheduled cron job** runs the `prune_activity` management command every 15 minutes, trimming the table to a configurable maximum row count (default: 10,000).

Pruning is intentionally separated from the request path. The middleware only inserts — it never deletes. This keeps the hot path fast (just an INSERT) and avoids race conditions during concurrent requests. The table may temporarily exceed the max between prune runs, but the overshoot is small and cleaned up on the next cycle.

```bash
# Run pruning manually
python manage.py prune_activity
```

## Configuration

All settings live in `config/settings/base.py` and can be overridden via environment variables or per-environment settings files.

### Row Limit

Control how many request log rows to keep:

```python
# config/settings/base.py
ACTIVITY_MAX_ROWS = 10000  # env: ACTIVITY_MAX_ROWS
```

```bash
# Override via .env
ACTIVITY_MAX_ROWS=50000
```

For most small sites, 10,000 rows covers several days to weeks of traffic. If you want more history, increase this — each row is small and SQLite handles 50k-100k rows without issue.

### Excluding Paths

Add your own paths to the exclusion list to keep them out of the dashboard:

```python
# config/settings/base.py
ACTIVITY_EXCLUDE_PATHS = [
    "/static/", "/media/", "/favicon.ico",
    "/health/", "/admin/jsi18n/", "/__debug__/",
    "/api/webhooks/",  # Your custom exclusion
]
```

Any request whose path starts with one of these prefixes is silently skipped — no logging overhead, no dashboard noise.

## Access Control

All activity views require:

- **Authentication** — unauthenticated users are redirected to the login page
- **Staff status** — non-staff users receive a 403 Forbidden response

The Activity link in the sidebar is only visible to staff users.

## Admin Integration

`RequestLog` is also registered in Django admin as a **read-only** model at `/admin/activity/requestlog/`:

- List view with timestamp, method, path, status code, user, response time, and IP
- Filters by method and status code
- Search by path, IP address, and username
- Date hierarchy on timestamp
- No add/change permissions — delete only for superusers

## htmx Integration

The activity app demonstrates several htmx patterns that serve as reference examples for your own views.

### Tab Switching Without Page Reloads

Both the Requests and Users detail pages use htmx-powered tab bars. Clicking a tab fetches just the tab content as an HTML fragment and swaps it into the page:

```html
<button class="tab-btn"
        hx-get="{% url 'activity:requests' %}?tab=top_paths"
        hx-target="#tab-content"
        hx-swap="innerHTML"
        onclick="setActiveTab(this)">Top Paths</button>
```

### Dual-Response Views

The detail views return different templates depending on whether the request came from htmx or a full page navigation:

```python
def get(self, request, *args, **kwargs):
    tab = self.get_tab()
    context = self.get_context_data(**kwargs)
    context.update(self.get_tab_context(tab))

    if request.htmx:
        return TemplateResponse(request, self.TAB_PARTIALS[tab], context)

    context.update(self.get_status_context())
    return TemplateResponse(request, self.template_name, context)
```

Normal navigation renders the full page with header, stats, and tab bar. htmx requests return only the tab content fragment.

### Clickable Stat Cards

The dashboard overview uses htmx to load detail data into a modal when stat cards are clicked:

```html
<div class="card stat-card-clickable"
     hx-get="{% url 'activity:stat_detail' 'requests' %}"
     hx-target="#stat-modal-body"
     onclick="openStatModal('Recent Requests')">
```

## Performance Notes

- **One INSERT per request** — negligible overhead on the hot path
- **No reads in middleware** — all aggregation happens in the dashboard views, not during request processing
- **Excluded static paths** — no logging for assets, debug toolbar, or health checks
- **Indexed fields** — dashboard queries use database indexes on `timestamp`, `path`, and `status_code`
- **Scheduled pruning** — the table stays bounded without impacting request latency
- **SQLite friendly** — works perfectly with SQLite's WAL mode for concurrent reads and writes

## Limitations and When to Upgrade

The activity tracker is intentionally simple. It answers the basics but it is **not a replacement for real analytics**. Things it does not do:

- **No JavaScript tracking** — it only sees server-side requests, not client-side events like clicks, scroll depth, or time on page
- **No visitor sessions** — each request is independent; there is no concept of a "visit" or "session"
- **No geographic data** — IP addresses are logged but not geolocated
- **No referrer tracking** — HTTP referrer headers are not currently captured
- **No dashboards over time** — there are no historical trend graphs or time-series charts
- **No bot filtering** — crawlers and bots are logged alongside real users
- **No real-time streaming** — the dashboard refreshes on page load (or via htmx polling), not via WebSockets

### When to add a real analytics package

If your site starts getting serious traffic — hundreds of daily visitors, or a post goes viral — congratulations! That is a great problem to have. At that point, consider adding a proper self-hosted analytics tool:

| Tool | Why it is great |
|------|-----------------|
| **[Umami](https://umami.is)** | Privacy-focused, lightweight, beautiful dashboards. Easy to self-host. |
| **[Plausible](https://plausible.io)** | Cookie-free, GDPR-compliant, simple UI. Available as SaaS or self-hosted. |
| **[Matomo](https://matomo.org)** | Full-featured Google Analytics alternative. Self-hosted with extensive plugin ecosystem. |

All three respect user privacy, can be self-hosted alongside your {{ project_name }} app, and provide the session tracking, geographic data, referrer analysis, and historical trend charts that the built-in tracker intentionally skips.

> If your site takes off or goes viral, let the SmallStack team know so we can promote you! But seriously — if traffic grows significantly, adding one of the tools above will give you the visibility you need to understand and grow your audience.

The built-in activity tracker will continue to work alongside any external analytics tool. They complement each other: the built-in tracker gives you server-side request data and error monitoring, while external tools provide client-side visitor analytics.
