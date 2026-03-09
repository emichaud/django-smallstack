# Skill: Timezone System

This skill describes how SmallStack stores, displays, and converts dates and times across timezones, including the middleware, template tags, and per-user overrides.

## Overview

SmallStack uses a three-layer timezone architecture: UTC in the database, a server timezone for default display, and optional per-user overrides via the profile. A custom middleware resolves the active timezone once per request and caches it for template tags to use without additional database queries.

## File Locations

```
config/settings/
├── base.py                    # TIME_ZONE setting (default: America/New_York)

apps/smallstack/
├── middleware.py               # TimezoneMiddleware — activates TZ per request
├── templatetags/
│   └── theme_tags.py           # localtime_tooltip tag, user_localtime filter

apps/profile/
├── models.py                  # UserProfile.timezone field, get_timezone(), to_local_time()

static/smallstack/css/
└── theme.css                  # .tz-tip tooltip styles

scripts/
└── smallstack-cron            # CRON_TZ=UTC pinned backup schedule

templates/ (usage examples)
├── activity/partials/          # All activity tables use {% localtime_tooltip %}
└── smallstack/partials/        # All backup tables use {% localtime_tooltip %}
```

## The Three Layers

| Layer | Where | Purpose |
|-------|-------|---------|
| Storage | Database | All datetimes stored as UTC (`USE_TZ=True`) |
| Server display | `TIME_ZONE` setting | Default timezone for all date rendering |
| User display | `UserProfile.timezone` | Per-user override with hover tooltip |

The flow on every request:

```
DB (UTC) → TimezoneMiddleware activates TZ → Django |date filter renders in active TZ
```

## TimezoneMiddleware

Located in `apps/smallstack/middleware.py`. Runs after `AuthenticationMiddleware` in the middleware stack.

```python
class TimezoneMiddleware:
    def __call__(self, request):
        server_tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        user_tz = server_tz

        if hasattr(request, "user") and request.user.is_authenticated:
            try:
                user_tz = request.user.profile.get_timezone()
            except Exception:
                pass

        # Cache on request for template tags (no DB queries in tags)
        request._tz_user = user_tz
        request._tz_server = server_tz
        request._tz_differs = str(user_tz) != str(server_tz)

        timezone.activate(user_tz)

        response = self.get_response(request)
        return response
```

### What the middleware caches

| Attribute | Type | Description |
|-----------|------|-------------|
| `request._tz_user` | `ZoneInfo` | Timezone used for display (user preference or server fallback) |
| `request._tz_server` | `ZoneInfo` | Server `TIME_ZONE` as ZoneInfo |
| `request._tz_differs` | `bool` | `True` when user TZ ≠ server TZ |

Template tags read these cached values instead of querying the database per datetime.

## Template Tags

All timezone template tags are in `apps/smallstack/templatetags/theme_tags.py`. Load with `{% load theme_tags %}`.

### `{% localtime_tooltip %}` — Recommended

Renders a datetime with an automatic hover tooltip when the user's timezone differs from the server's.

```html
{% load theme_tags %}

{# Default format #}
{% localtime_tooltip record.created_at %}

{# Custom format with seconds #}
{% localtime_tooltip record.created_at "M d, Y g:i:s A T" %}
```

**Behavior:**
- User TZ matches server TZ → plain text output, no decoration
- User TZ differs → `<span class="tz-tip" data-tz-server="..." data-tz-utc="...">` with CSS hover tooltip

**Implementation:**

```python
@register.simple_tag(takes_context=True)
def localtime_tooltip(context, dt, fmt="M d, Y g:i A T"):
    if dt is None:
        return ""

    request = context.get("request")

    # Read cached TZ info from middleware (no DB queries)
    server_tz = getattr(request, "_tz_server", None) or zoneinfo.ZoneInfo(settings.TIME_ZONE)
    user_tz = getattr(request, "_tz_user", None) or server_tz
    tz_differs = getattr(request, "_tz_differs", False)

    user_dt = dt.astimezone(user_tz)
    user_str = dateformat.format(user_dt, fmt)

    if not tz_differs:
        return user_str

    # Build tooltip with server time + UTC
    server_str = dateformat.format(dt.astimezone(server_tz), tip_fmt)
    utc_str = dateformat.format(dt.astimezone(utc_tz), tip_fmt)

    return format_html(
        '<span class="tz-tip" data-tz-server="{}" data-tz-utc="{}">{}</span>',
        f"Server: {server_str}",
        f"UTC: {utc_str}",
        user_str,
    )
```

### `|user_localtime` Filter

Converts a datetime to the user's timezone. Returns a datetime object — chain with `|date:` to format.

```html
{% load theme_tags %}
{{ record.created_at|user_localtime:request|date:"M d, Y g:i A T" }}
```

Use `{% localtime_tooltip %}` instead when possible — it handles the tooltip automatically.

## CSS Tooltip (`.tz-tip`)

The timezone tooltip is pure CSS, defined in `static/smallstack/css/theme.css`:

```css
.tz-tip {
    position: relative;
    border-bottom: 1px dotted var(--body-quiet-color);
    cursor: help;
}
.tz-tip::after {
    content: attr(data-tz-server) "\A" attr(data-tz-utc);
    white-space: pre;
    position: absolute;
    bottom: calc(100% + 6px);
    left: 0;
    background: var(--card-bg);
    color: var(--body-quiet-color);
    border: 1px solid var(--hairline-color);
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 0.75rem;
    line-height: 1.6;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.tz-tip:hover::after {
    opacity: 1;
}
```

The tooltip stacks two lines vertically:
```
Server: Mar 09, 2026 2:30 PM EST
UTC: Mar 09, 2026 7:30 PM UTC
```

It uses `data-tz-server` and `data-tz-utc` attributes with CSS `content: attr()` and `"\A"` for the line break. No JavaScript required.

## UserProfile Timezone Methods

Located in `apps/profile/models.py`:

```python
class UserProfile(models.Model):
    timezone = models.CharField(max_length=50, blank=True, default="", choices=TIMEZONE_CHOICES)

    def get_timezone(self):
        """Return ZoneInfo object. Falls back to settings.TIME_ZONE."""
        tz_name = self.timezone or settings.TIME_ZONE
        return zoneinfo.ZoneInfo(tz_name)

    def to_local_time(self, dt):
        """Convert a UTC datetime to the user's local timezone."""
        return dt.astimezone(self.get_timezone())
```

The timezone choices are grouped by region (Americas, Europe, Asia/Pacific, etc.) in `TIMEZONE_CHOICES`.

## Profile Edit — Live TZ Preview

The profile edit page (`templates/profile/profile_edit.html`) includes a JavaScript widget below the timezone select that shows the current time in both UTC and the selected timezone, updating every second:

```javascript
function updatePreview() {
    const tz = tzSelect.value;
    if (!tz) { preview.textContent = ''; return; }
    const now = new Date();
    const utcStr = formatTime(now, 'UTC');
    const localStr = formatTime(now, tz);
    preview.innerHTML =
        '<span>UTC:</span> ' + utcStr +
        '<br><span>' + tz + ':</span> ' + localStr;
}
tzSelect.addEventListener('change', updatePreview);
updatePreview();
setInterval(updatePreview, 1000);
```

This uses the browser's `Intl.DateTimeFormat` via `toLocaleString()` for client-side timezone conversion.

## Date Format Reference

SmallStack uses Django's `date` format codes consistently:

| Format String | Example Output | Used In |
|--------------|----------------|---------|
| `"M d, Y g:i A T"` | Mar 09, 2026 2:30 PM EDT | Backup history, user dates |
| `"M d g:i:s A T"` | Mar 09 2:30:15 PM EDT | Activity request logs |
| `"M d, Y g:i:s A T"` | Mar 09, 2026 2:30:15 PM EDT | Backup detail page |
| `"M d, Y"` | Mar 09, 2026 | Date-only fields |

Key format codes:
- `g` — 12-hour hour, no leading zero
- `A` — AM/PM
- `T` — Timezone abbreviation (EDT, EST, UTC, etc.)

## Cron and Timezones

The backup cron schedule in `scripts/smallstack-cron` is pinned to UTC:

```bash
CRON_TZ=UTC
0 2 * * * . /app/.env.cron && cd /app && python manage.py backup_db --keep 14
```

`CRON_TZ=UTC` ensures backups always fire at 2:00 AM UTC regardless of:
- The Django `TIME_ZONE` setting
- The container's system timezone (`TZ` env var)

Backup filenames (`db-YYYYMMDD-HHMMSS.sqlite3`) also use UTC timestamps for consistent sorting.

## Configuration

### Settings

| Setting | Default | Location | Purpose |
|---------|---------|----------|---------|
| `TIME_ZONE` | `America/New_York` | `base.py` | Server default timezone for display |
| `USE_TZ` | `True` | `base.py` | Store datetimes as UTC (don't change) |

Override via `.env`:

```bash
TIME_ZONE=Europe/London
TIME_ZONE=America/Chicago
TIME_ZONE=UTC
```

### Middleware Order

`TimezoneMiddleware` must come after `AuthenticationMiddleware` (it needs `request.user`):

```python
MIDDLEWARE = [
    # ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.smallstack.middleware.TimezoneMiddleware",    # Must be after auth
    # ...
]
```

## Adding Timezone-Aware Dates to New Pages

When creating any page that displays datetimes:

1. Load theme tags: `{% load theme_tags %}`
2. Use `{% localtime_tooltip your_datetime "M d, Y g:i A T" %}`
3. The middleware and CSS handle everything else

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

Don't use bare `{{ item.created_at|date:"..." }}` — it won't get the tooltip or proper timezone conversion.

## Testing Timezone Code

Tests use `override_settings`, `RequestFactory`, and `timezone.activate()`:

```python
from django.test import RequestFactory, override_settings
from django.utils import timezone

@override_settings(TIME_ZONE="America/New_York")
def test_user_with_tz_overrides_server(self, user):
    user.profile.timezone = "America/Los_Angeles"
    user.profile.save()

    factory = RequestFactory()
    request = factory.get("/")
    request.user = user

    middleware = TimezoneMiddleware(lambda r: None)
    middleware(request)

    assert str(request._tz_user) == "America/Los_Angeles"
    assert request._tz_differs is True
```

For template tag tests, create a mock request with the cached `_tz_*` attributes:

```python
def _make_request(user_tz, server_tz):
    request = RequestFactory().get("/")
    request._tz_server = zoneinfo.ZoneInfo(server_tz)
    request._tz_user = zoneinfo.ZoneInfo(user_tz)
    request._tz_differs = user_tz != server_tz
    return request
```

## Best Practices

1. **Always use `{% localtime_tooltip %}`** for datetimes in templates — it handles timezone conversion and the tooltip automatically
2. **Don't use bare `|date:` filters** on UTC datetimes — they won't get the tooltip treatment
3. **Keep `USE_TZ = True`** — never disable it; UTC storage is the foundation everything else depends on
4. **Set `TIME_ZONE` to your actual server timezone** — don't leave it as UTC unless your team is distributed globally
5. **Pin cron to UTC** with `CRON_TZ=UTC` — display timezone changes should never shift when scheduled jobs run
6. **Test DST transitions** — use dates in both January (standard time) and June (daylight saving time) to catch offset bugs
7. **Cache timezone lookups** — the middleware caches `_tz_*` on the request; template tags should read from these, not query the database
