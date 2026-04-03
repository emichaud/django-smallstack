---
title: Debug Toolbar
description: Enable Django Debug Toolbar for SQL profiling, template inspection, and request debugging
---

# Debug Toolbar

[Django Debug Toolbar](https://django-debug-toolbar.readthedocs.io/) is a powerful in-browser debugging panel that shows you exactly what's happening inside every request. It's installed in {{ project_name }} but **off by default** — it stays out of the way for screenshots, normal development, and demos, and comes to life with a single environment variable when you need it.

## Quick Start

```bash
# Add to your .env file (or export in your shell)
DEBUG_TOOLBAR=true
```

Restart the dev server (`make run`). A collapsible toolbar panel appears on the right side of every HTML page.

To turn it off again, set `DEBUG_TOOLBAR=false` (or remove the line) and restart.

> **Both conditions must be true:** `DEBUG=True` (always true in development) **and** `DEBUG_TOOLBAR=true` in your environment. In production, `DEBUG=False` means the toolbar never activates regardless of the env var.

## What the Toolbar Shows

The toolbar appears as a vertical strip on the right edge of your browser. Click any panel to expand it. Each panel gives you different debugging information:

| Panel | What it shows | When to use it |
|-------|--------------|----------------|
| **SQL** | Every database query, with time and EXPLAIN | Finding slow queries, N+1 problems, duplicate queries |
| **Time** | Total request time breakdown (CPU, DB, template) | Identifying bottlenecks |
| **Templates** | Which templates were rendered, in what order, and their context variables | Debugging template inheritance, checking context data |
| **Cache** | Cache hits, misses, and calls | Optimizing cache usage |
| **Headers** | Request and response HTTP headers | Checking CORS, CSP, auth headers |
| **Request** | View function, URL route, GET/POST data, cookies | Understanding which view handled the request |
| **Settings** | All active Django settings | Verifying configuration |
| **Signals** | Django signals fired during the request | Debugging signal handlers |
| **Static Files** | Static files used by the page | Finding missing or duplicate assets |
| **Profiling** | Python call stack profiling | Deep performance analysis |

## Common Debugging Scenarios

### Finding Slow Queries

The **SQL panel** is the most-used panel. It shows every query Django executed for the current request:

1. Enable the toolbar and load a page
2. Click the **SQL** panel — it shows query count and total time
3. Look for:
   - **Duplicate queries** — the same query repeated many times (N+1 problem)
   - **Slow queries** — anything over 10ms is worth investigating
   - **Missing indexes** — click a query to see its EXPLAIN plan

**Example:** If a list page shows 50 queries when it should show 3, you probably need `select_related()` or `prefetch_related()` on your queryset.

### Checking Template Context

The **Templates panel** shows exactly which templates were rendered and what variables were available in each one:

1. Click the **Templates** panel
2. See the template inheritance chain (e.g., `base.html` → `website/base.html` → `home.html`)
3. Click any template to see its full context — every variable available to that template

This is invaluable when a template variable isn't showing up and you need to figure out why.

### Debugging Request/Response

The **Headers** and **Request** panels together show the full picture:

- What URL route matched
- Which view function handled it
- All request headers (including `Authorization`, `X-Request-ID`)
- All response headers (including CSP, cache headers)
- GET parameters, POST data, cookies

### Profiling a Slow Page

For deeper performance analysis, enable the **Profiling** panel:

1. Click the checkbox next to "Profiling" in the toolbar
2. Reload the page
3. The panel shows a full Python call stack with time spent in each function

This helps identify bottlenecks in your own code, third-party packages, or Django internals.

## Configuration

The toolbar configuration lives in `config/settings/development.py`:

```python
# Enabled via environment variable (default: off)
if config("DEBUG_TOOLBAR", default=False, cast=bool):
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

# Only show for these IPs
INTERNAL_IPS = ["127.0.0.1", "localhost"]

# Toolbar display rules
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG
    and "debug_toolbar" in INSTALLED_APPS
    and not request.path.startswith(("/api/docs/", "/api/redoc/")),
}
```

### Why Certain Pages Are Excluded

The toolbar injects HTML and JavaScript into responses. This breaks standalone pages that aren't standard Django templates:

- `/api/docs/` (Swagger UI) — the toolbar's injected HTML corrupts the Swagger UI JavaScript
- `/api/redoc/` (ReDoc) — same issue

These are excluded via the `SHOW_TOOLBAR_CALLBACK`. If you add other standalone HTML pages, add their paths to the exclusion list.

### Adding More Exclusions

```python
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG
    and "debug_toolbar" in INSTALLED_APPS
    and not request.path.startswith((
        "/api/docs/", "/api/redoc/",
        "/my-custom-page/",  # Add your exclusions here
    )),
}
```

## Toolbar and API Endpoints

The toolbar only affects **HTML responses** — it does not inject into JSON API responses. Your API endpoints work normally regardless of whether the toolbar is enabled.

However, when the toolbar is active, it adds its own SQL queries and middleware overhead to every request. If you're profiling API response times, be aware that toolbar overhead can add 5-20ms. For accurate API benchmarks, disable the toolbar.

## Toolbar and Docker

When running in Docker, `127.0.0.1` may not match the container's internal IP. If the toolbar doesn't appear:

```python
# config/settings/development.py
import socket

hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
INTERNAL_IPS += [ip[: ip.rfind(".")] + ".1" for ip in ips]
```

This adds the Docker host gateway IP to `INTERNAL_IPS`. Only needed in development containers.

## Error Preview Pages

{{ project_name }} includes error preview URLs that work in development regardless of the toolbar:

| URL | Shows |
|-----|-------|
| `/_error/400/` | Bad Request page |
| `/_error/403/` | Permission Denied page |
| `/_error/404/` | Page Not Found page |
| `/_error/500/` | Server Error page |

These are useful for testing your custom error templates (if you've overridden `400.html`, `403.html`, `404.html`, or `500.html`).

## Troubleshooting

**Toolbar not appearing:**
- Check `DEBUG_TOOLBAR=true` is set (not just `true` — use `=true`)
- Restart the dev server after changing `.env`
- Make sure you're accessing from `127.0.0.1` or `localhost` (matches `INTERNAL_IPS`)
- Check the page is returning HTML (toolbar doesn't inject into JSON responses)

**Toolbar slowing down the site:**
- The SQL panel records every query — pages with many queries will be slower
- Disable with `DEBUG_TOOLBAR=false` when not actively debugging
- This is why it's off by default

**Toolbar breaking a page:**
- Add the path to the exclusion list in `SHOW_TOOLBAR_CALLBACK`
- This usually happens with pages that load standalone JavaScript apps
