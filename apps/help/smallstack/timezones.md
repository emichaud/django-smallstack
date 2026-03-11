---
title: Working with Timezones
description: How SmallStack stores, displays, and converts dates and times
---

# Working with Timezones

SmallStack uses a three-layer timezone architecture that keeps things predictable: UTC in the database, a server timezone for default display, and optional per-user overrides.

## The Three Layers

| Layer | Where | Purpose |
|-------|-------|---------|
| **Storage** | Database | All datetimes stored as UTC (`USE_TZ=True`) |
| **Server display** | `TIME_ZONE` setting | Default timezone for all date rendering |
| **User display** | Profile timezone | Per-user override with hover tooltip showing server time and UTC |

```
DB (UTC) → Middleware activates TZ → Django |date filter renders in active TZ
```

### 1. Storage — Always UTC

Django's `USE_TZ = True` (set in `base.py`) means every datetime stored in the database is in UTC. This is the industry standard — it avoids ambiguity around daylight saving transitions and makes timezone conversion straightforward.

You never need to think about this layer. Django handles it automatically.

### 2. Server Timezone — The Default Display

The `TIME_ZONE` setting in `base.py` controls the default timezone for all date rendering:

```python
# config/settings/base.py
TIME_ZONE = config("TIME_ZONE", default="America/New_York")
```

This affects:

- All dates shown to anonymous users
- All dates shown to logged-in users who haven't set a timezone
- The "Server" time shown in timezone tooltips

**To change the default**, set `TIME_ZONE` in your `.env`:

```bash
# .env
TIME_ZONE=America/Chicago      # Central Time
TIME_ZONE=Europe/London         # GMT/BST
TIME_ZONE=UTC                   # UTC (no conversion)
```

Use any valid [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

### 3. User Timezone — Per-User Override

Logged-in users can set their timezone on the **Profile Edit** page. When set, all dates across the site render in their chosen timezone instead of the server default.

When a user's timezone differs from the server timezone, dates appear with a **dotted underline**. Hovering shows a tooltip with:

- **Server time** — what the date looks like in the server's timezone
- **UTC time** — the raw stored time

This makes it easy to cross-reference times with teammates in different timezones or with server logs.

## How It Works

### TimezoneMiddleware

The `TimezoneMiddleware` in `apps/smallstack/middleware.py` runs on every request:

1. Checks if the user is authenticated and has a timezone preference
2. Calls `django.utils.timezone.activate(tz)` — this tells Django's `|date` template filter which timezone to use
3. Caches the resolved timezone info on the request object for fast access by template tags

```python
# What the middleware caches on every request:
request._tz_user    # ZoneInfo — the timezone used for display
request._tz_server  # ZoneInfo — the server TIME_ZONE
request._tz_differs # bool — True when user TZ ≠ server TZ
```

This means template tags never hit the database for timezone lookups — it's resolved once per request.

### The `{% localtime_tooltip %}` Template Tag

Use this tag anywhere you display a datetime:

```html
{% load theme_tags %}

{# Default format: "Mar 09, 2026 2:30 PM EDT" #}
{% localtime_tooltip record.created_at %}

{# Custom format with seconds #}
{% localtime_tooltip record.created_at "M d, Y g:i:s A T" %}
```

**Behavior:**

- If user TZ matches server TZ → plain text, no decoration
- If user TZ differs → `<span class="tz-tip">` with hover tooltip

The tooltip is pure CSS (no JavaScript), using the `.tz-tip` class in `theme.css`.

### The `|user_localtime` Filter

For cases where you need the converted datetime as a value (not rendered HTML), use the filter:

```html
{% load theme_tags %}

{{ record.created_at|user_localtime:request|date:"M d, Y g:i A T" }}
```

This returns the datetime object converted to the user's timezone. Chain it with `|date:` to format. Note: `{% localtime_tooltip %}` is preferred because it handles the tooltip automatically.

## Date Format Reference

SmallStack uses Django's `date` format codes. Common patterns used across the project:

| Format String | Example Output | Used In |
|--------------|----------------|---------|
| `"M d, Y g:i A T"` | Mar 09, 2026 2:30 PM EDT | Backup history, user dates |
| `"M d g:i:s A T"` | Mar 09 2:30:15 PM EDT | Activity request logs |
| `"M d, Y g:i:s A T"` | Mar 09, 2026 2:30:15 PM EDT | Backup detail page |
| `"M d, Y"` | Mar 09, 2026 | Date-only fields |

Key format codes: `g` = 12-hour no leading zero, `A` = AM/PM, `T` = timezone abbreviation (EDT, UTC, etc.).

## Scheduled Backups and Cron

The backup cron schedule (`scripts/smallstack-cron`) is **pinned to UTC** and is completely independent of Django's `TIME_ZONE` setting:

```cron
0 2 * * * cd /app && [ "${BACKUP_CRON_ENABLED}" = "true" ] && python3 manage.py backup_db --keep 14
```

Scheduled tasks run via [supercronic](https://github.com/aptible/supercronic), which inherits the container's environment directly. The `TZ` env var controls what timezone cron expressions use — default is UTC.

This means backups run at **2:00 AM** in whatever timezone `TZ` is set to (UTC by default), regardless of Django's `TIME_ZONE` setting or any user's timezone preference.

## Configuration Reference

### Settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `TIME_ZONE` | `America/New_York` | Server default timezone for display |
| `USE_TZ` | `True` | Store datetimes as UTC (don't change this) |
| `USE_I18N` | `True` | Enable internationalization |

### Profile Model

The timezone field on `UserProfile` stores an IANA timezone string (e.g., `America/Los_Angeles`). Key methods:

```python
# Get the user's ZoneInfo object (falls back to TIME_ZONE)
tz = request.user.profile.get_timezone()

# Convert a UTC datetime to the user's local time
local_dt = request.user.profile.to_local_time(some_utc_datetime)
```

### Template Tags

```html
{% load theme_tags %}

{# Recommended: auto-tooltip when TZ differs #}
{% localtime_tooltip record.created_at "M d, Y g:i A T" %}

{# Manual: get converted datetime, format yourself #}
{{ record.created_at|user_localtime:request|date:"M d, Y g:i A T" }}
```

## Adding Timezone-Aware Dates to New Pages

When you create a new page that displays datetimes:

1. Load theme tags: `{% load theme_tags %}`
2. Use `{% localtime_tooltip your_datetime %}` instead of `{{ your_datetime|date:"..." }}`
3. The middleware and CSS handle everything else — no extra code needed

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block content %}
<table>
    {% for item in items %}
    <tr>
        <td>{% localtime_tooltip item.created_at "M d, Y g:i A T" %}</td>
        <td>{{ item.name }}</td>
    </tr>
    {% endfor %}
</table>
{% endblock %}
```

## Troubleshooting

### All dates show UTC

Your `TIME_ZONE` setting is probably still `UTC`. Set it to your actual timezone in `.env`:

```bash
TIME_ZONE=America/New_York
```

### Timezone tooltip not appearing

The tooltip only appears when the user's timezone differs from the server timezone. If you're testing, set your profile timezone to something different from `TIME_ZONE`.

### Cron running at unexpected times

Check that `scripts/smallstack-cron` has `CRON_TZ=UTC` at the top. Without it, cron uses the container's system timezone, which may differ from what you expect.

### Dates wrong after daylight saving change

This is handled automatically. IANA timezone names (like `America/New_York`) know about DST transitions. The `T` format code will show `EDT` vs `EST` as appropriate.
