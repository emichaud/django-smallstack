---
title: Model Explorer
description: A staff-facing data browser with display palette, REST API, and composable registration
---

# Model Explorer

Explorer is SmallStack's built-in model browser. It reads `ModelAdmin` classes — whether registered with Django admin or not — and generates a full CRUD interface with swappable display modes, optional REST API, and CSV/JSON export.

**Direct link:** [Open Explorer](/smallstack/explorer/)

![Explorer index](/static/smallstack/docs/images/explorer-index.png)

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

For quick prototyping, you can still add `explorer_enabled = True` to any `ModelAdmin` registered with Django admin. Explorer will discover it automatically:

```python
# apps/myapp/admin.py
@admin.register(Widget)
class WidgetAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_active"]
    explorer_enabled = True
```

This approach works but is less flexible — you can't have different layouts for admin vs Explorer, and the config is mixed into your admin.py.

### Groups and Multi-Registration

Models are organized into groups. The group name appears in the URL and the Explorer index.

```
/smallstack/explorer/{group_slug}/{model_name}/
```

The same model can be registered in multiple groups with different layouts:

```python
# Different views of the same data
explorer.register(Heartbeat, HeartbeatMonitoringAdmin, group="Monitoring")
explorer.register(Heartbeat, HeartbeatOpsAdmin, group="Operations")
```

If no group is specified, Explorer uses the app label (title-cased).

## Display Palette

When a model has multiple displays configured, Explorer shows a palette of icon buttons. Click one to swap the display — the data stays the same, only the rendering changes.

![Display palette with table and card views](/static/smallstack/docs/images/explorer-display-palette.png)

### Built-in List Displays

| Display | Name | Description |
|---------|------|-------------|
| `Table2Display` | `table2` | django-tables2 sortable table (default) |
| `TableDisplay` | `table` | Basic HTML table with field transforms |
| `CardDisplay` | `cards` | 3-column card grid with title/subtitle |

```python
from apps.smallstack.displays import Table2Display, TableDisplay, CardDisplay

class MyAdmin(admin.ModelAdmin):
    explorer_displays = [
        Table2Display,                    # Sortable columns
        TableDisplay,                     # Basic table (supports transforms)
        CardDisplay(title_field="name", subtitle_field="created_at"),
    ]
```

![Card display](/static/smallstack/docs/images/explorer-cards-display.png)

### Built-in Detail Displays

| Display | Name | Description |
|---------|------|-------------|
| `DetailTableDisplay` | `table` | Vertical key/value table |
| `DetailCardDisplay` | `card` | 2-column: photo on left, fields on right |

```python
from apps.smallstack.displays import DetailTableDisplay, DetailCardDisplay

class MyAdmin(admin.ModelAdmin):
    explorer_detail_displays = [
        DetailTableDisplay,
        DetailCardDisplay(image_field="profile_photo"),
    ]
```

![Detail card display](/static/smallstack/docs/images/explorer-detail-card.png)

### Creating Custom Displays

Any class that follows the display protocol works:

```python
from apps.smallstack.displays import ListDisplay

class MapDisplay(ListDisplay):
    name = "map"
    icon = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">...</svg>'
    template_name = "myapp/displays/map.html"

    def get_context(self, queryset, crud_config, request):
        return {
            "markers": [
                {"lat": obj.latitude, "lng": obj.longitude, "label": str(obj)}
                for obj in queryset
            ]
        }
```

Then use it in your explorer registration:

```python
class MyAdmin(admin.ModelAdmin):
    explorer_displays = [Table2Display, MapDisplay]
```

The palette handles the rest — HTMX swaps the display area when the user clicks an icon.

### How Display Switching Works

1. User clicks a palette icon
2. HTMX sends `GET ?display=map` with `HX-Request` header
3. CRUDView detects the HTMX request and returns just the display template (no page chrome)
4. The display area swaps in place
5. localStorage remembers the choice for next visit

## Bulk Actions

Explorer list views include bulk actions by default. When rows are selected via checkboxes, a compact action bar appears below the toolbar showing the selection count and available actions.

**Bulk delete** is enabled by default — no configuration needed. Select rows, click "Delete", and confirm in the modal. The operation processes each object individually, so protected objects (with FK constraints) return per-object errors while the rest are deleted.

To add bulk update or disable bulk actions entirely:

```python
class MyAdmin(admin.ModelAdmin):
    # Default — bulk delete enabled
    explorer_bulk_actions = ["delete"]

    # Enable both delete and update
    explorer_bulk_actions = ["delete", "update"]

    # Disable all bulk actions
    explorer_bulk_actions = []
```

When bulk update is enabled, the `can_bulk_update_fields()` hook controls which fields are updatable.

### Bulk API

Bulk operations use a single endpoint:

```
POST /smallstack/api/explorer/{group}/{model}/bulk/
```

See [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) for request/response format.

## REST API

Explorer models can opt into a JSON REST API by setting `explorer_enable_api = True` on the ModelAdmin.

```python
class HeartbeatAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "status", "response_time_ms", "note")
    search_fields = ("note", "status")
    explorer_enable_api = True
    explorer_export_formats = ["csv", "json"]
```

This generates API endpoints alongside the HTML views:

```
GET    /smallstack/api/explorer/{group}/{model}/          List + search + filter + export
POST   /smallstack/api/explorer/{group}/{model}/          Create
GET    /smallstack/api/explorer/{group}/{model}/<pk>/     Detail
PUT    /smallstack/api/explorer/{group}/{model}/<pk>/     Full update
PATCH  /smallstack/api/explorer/{group}/{model}/<pk>/     Partial update
DELETE /smallstack/api/explorer/{group}/{model}/<pk>/     Delete
```

See [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) for the full guide.

## Field Transforms

Field transforms change how values render in the basic table display (`TableDisplay`). They do **not** apply to django-tables2 displays.

```python
class MyAdmin(admin.ModelAdmin):
    explorer_field_transforms = {
        "bio": "preview",          # Truncate long text with expand toggle
        "status": ("badge", {}),   # Render as colored badge
    }
```

Built-in transforms: `preview` (truncation with HTMX expand).

## Explorer Attributes Reference

These attributes can be set on any `ModelAdmin` used with Explorer:

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `explorer_displays` | `list` | `[Table2Display]` | List view display classes |
| `explorer_detail_displays` | `list` | `[]` | Detail view display classes |
| `explorer_fields` | `list[str]` | `None` | Override displayed fields (falls back to `list_display`) |
| `explorer_readonly` | `bool` | `None` | Force readonly mode (auto-detected from permissions if `None`) |
| `explorer_field_transforms` | `dict` | `{}` | Field rendering transforms for basic table |
| `explorer_paginate_by` | `int` | `10` | Items per page |
| `explorer_enable_api` | `bool` | `False` | Generate REST API endpoints |
| `explorer_export_formats` | `list` | `[]` | Enabled export formats (e.g., `["csv", "json"]`) |
| `explorer_bulk_actions` | `list` | `["delete"]` | Bulk actions available on list view. Options: `"delete"`, `"update"`. Set to `[]` to disable. |

Standard ModelAdmin attributes that Explorer reads:

| Attribute | Explorer Usage |
|-----------|---------------|
| `list_display` | List view columns (real fields only, callables skipped) |
| `search_fields` | API search (used by `?q=` parameter) |
| `list_per_page` | Pagination size (overridden by `explorer_paginate_by`) |
| `has_add_permission()` | Auto-detects readonly mode |
| `has_change_permission()` | Auto-detects readonly mode |

## Explorer vs CRUDView

| | Explorer | CRUDView |
|---|----------|----------|
| **Setup** | `explorer.register()` + ModelAdmin | View class + URL wiring |
| **Customization** | Admin attributes + display classes | Full view/form/template control |
| **Layout** | Auto-generated | You design the page |
| **Displays** | Palette with HTMX swapping | Same display protocol |
| **REST API** | One attribute (`explorer_enable_api`) | `enable_api = True` on CRUDView |
| **Best for** | Data browsing, internal tools, rapid prototyping | Production management pages |

Start with Explorer for rapid prototyping. Graduate to CRUDView when you need custom layouts. Use Explorer's [composability mixins](/smallstack/help/smallstack/explorer-composability/) to embed auto-generated tables into your own pages.

## See Also

- [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) — Authentication, endpoints, search, export
- [Explorer Composability](/smallstack/help/smallstack/explorer-composability/) — Embed Explorer into custom pages
- [Explorer ModelAdmin API](/smallstack/help/smallstack/explorer-admin-api/) — Full attribute reference
- [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/) — When you outgrow Explorer
