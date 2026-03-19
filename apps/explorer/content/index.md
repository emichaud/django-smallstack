---
title: Explorer Overview
description: A staff-facing data browser with display palette, REST API, and composable registration
---

# Explorer

Explorer is SmallStack's built-in model browser. It reads `ModelAdmin` classes — whether registered with Django admin or not — and generates a full CRUD interface with swappable display modes, optional REST API, and CSV/JSON export.

**Direct link:** [Open Explorer](/smallstack/explorer/)

## How It Works

Explorer supports three registration paths, checked in this order:

1. **`explorer.py` files** — explicit registration via `explorer.register()` (recommended)
2. **`autodiscover()`** — auto-imports `explorer.py` from every installed app
3. **`discover_admin()`** — legacy: scans `admin.site._registry` for `explorer_enabled = True`

On startup, Explorer builds a `CRUDView` subclass for each registered model and injects URL patterns at `/smallstack/explorer/`.

The result:

- **Index page** — grid of all registered models grouped by custom groups
- **Per-model CRUD** — list with sorting, detail view, create/edit forms, and delete confirmation
- **Display palette** — swap between table, cards, or custom displays at runtime
- **REST API** — opt-in JSON endpoints for each model
- **Readonly detection** — models with restricted permissions get list + detail only

### Accessing Explorer

Explorer is in the **Admin** section of the sidebar and restricted to staff users:

- **Sidebar:** Admin → Explorer
- **Direct URL:** `/smallstack/explorer/`

## Registration

### Recommended: `explorer.py` Files

Create an `explorer.py` in any app to register models with Explorer. This is the cleanest approach — your admin.py stays focused on Django admin, and Explorer config lives separately.

**Scenario A — Shared config (simplest).** Reuse your existing ModelAdmin:

```python
# apps/heartbeat/explorer.py
from apps.explorer.registry import explorer
from .admin import HeartbeatAdmin
from .models import Heartbeat

explorer.register(Heartbeat, HeartbeatAdmin, group="Monitoring")
```

One ModelAdmin. Django admin, Explorer, and CRUDView all read from it.

**Scenario B — Different layouts.** Use a separate ModelAdmin for Explorer:

```python
# apps/profile/explorer.py
from django.contrib import admin
from apps.explorer.registry import explorer
from apps.smallstack.displays import (
    CardDisplay, DetailCardDisplay, DetailTableDisplay,
    Table2Display, TableDisplay,
)
from .models import UserProfile

class UserProfileExplorerAdmin(admin.ModelAdmin):
    """Streamlined layout for Explorer — different from full admin config."""
    list_display = ("user", "display_name", "bio", "location", "created_at")
    list_per_page = 12

    # Display palette: three list displays
    explorer_displays = [
        Table2Display,
        TableDisplay,
        CardDisplay(title_field="user", subtitle_field="created_at"),
    ]

    # Detail displays: table and photo card
    explorer_detail_displays = [
        DetailTableDisplay,
        DetailCardDisplay(image_field="profile_photo"),
    ]

    explorer_field_transforms = {"bio": "preview"}

explorer.register(UserProfile, UserProfileExplorerAdmin, group="Users")
```

**Scenario C — Explorer only.** No Django admin registration needed:

```python
# apps/myapp/explorer.py
from django.contrib import admin
from apps.explorer.registry import explorer
from .models import Widget

class WidgetExplorerAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_active"]

explorer.register(Widget, WidgetExplorerAdmin, group="Tools")
```

The model never appears in Django admin. Explorer manages it independently.

### Legacy: `explorer_enabled` on Admin

For quick prototyping, add `explorer_enabled = True` to any `ModelAdmin` registered with Django admin:

```python
@admin.register(Widget)
class WidgetAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_active"]
    explorer_enabled = True
```

## Display Palette

When a model has multiple displays configured, Explorer shows a palette of icon buttons. Click one to swap the display — the data stays the same, only the rendering changes.

### Built-in Displays

| Display | Name | Description |
|---------|------|-------------|
| `Table2Display` | `table2` | django-tables2 sortable table (default) |
| `TableDisplay` | `table` | Basic HTML table with field transforms |
| `CardDisplay` | `cards` | 3-column card grid with title/subtitle |
| `DetailTableDisplay` | `table` | Vertical key/value table (detail view) |
| `DetailCardDisplay` | `card` | 2-column: photo on left, fields on right (detail view) |

### Custom Displays

Subclass `ListDisplay` or `DetailDisplay` to create custom visualizations — charts, calendars, maps, or any layout:

```python
from apps.smallstack.displays import ListDisplay

class WeeklySummaryDisplay(ListDisplay):
    name = "weekly"
    icon = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">...</svg>'
    template_name = "heartbeat/displays/weekly_summary.html"

    def get_context(self, queryset, crud_config, request):
        # Build a 7-day calendar grid from HeartbeatDaily records
        return {"days": days, "monday": monday, ...}
```

Register it:

```python
class MyAdmin(admin.ModelAdmin):
    explorer_displays = [Table2Display, WeeklySummaryDisplay()]
```

Custom displays work in both Explorer and standalone CRUDView — the protocol is the same.

### How Display Switching Works

1. User clicks a palette icon
2. HTMX sends `GET ?display=weekly` with `HX-Request` header
3. CRUDView returns just the display template (no page chrome)
4. The display area swaps in place
5. URL updates with `?display=weekly` for bookmarking
6. localStorage remembers the choice for next visit

## REST API

Explorer models can opt into a JSON REST API:

```python
class HeartbeatAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "status", "response_time_ms")
    explorer_enable_api = True
    explorer_export_formats = ["csv", "json"]
```

See [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) for the full guide.

## Composability

Explorer's views, mixins, and context helpers can be embedded into any page:

```python
from apps.explorer.mixins import ExplorerModelMixin

class HeartbeatPageView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeat.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"
```

```html
{% load crud_tags %}
<div class="card">{% crud_table %}</div>
```

See [Composability Guide](/smallstack/help/explorer/composability/) for the full details.

## Explorer vs CRUDView

| | Explorer | CRUDView |
|---|----------|----------|
| **Setup** | `explorer.register()` + ModelAdmin | View class + URL wiring |
| **Customization** | Admin attributes + display classes | Full view/form/template control |
| **Displays** | Same display protocol | Same display protocol |
| **REST API** | `explorer_enable_api = True` | `enable_api = True` |
| **Best for** | Data browsing, internal tools | Production management pages |

Start with Explorer for rapid prototyping. Graduate to CRUDView when you need custom layouts.

## Related Documentation

- [Enabling Models for Explorer](/smallstack/help/explorer/admin-api/) — ModelAdmin API reference
- [Composability Guide](/smallstack/help/explorer/composability/) — Embed Explorer into your own pages
- [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) — Auto-generated JSON API
- [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/) — Manual CRUD with CRUDView
