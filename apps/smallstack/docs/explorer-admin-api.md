---
title: Explorer ModelAdmin API
description: Full reference for ModelAdmin attributes that Explorer reads and supports
---

# Explorer ModelAdmin API Reference

Explorer reads `ModelAdmin` classes for field layout, display configuration, permissions, and API settings. This page is the complete reference.

## Registration

Explorer supports three registration methods:

### 1. Explicit Registration (Recommended)

Create an `explorer.py` in your app:

```python
# apps/myapp/explorer.py
from apps.explorer.registry import explorer
from .admin import WidgetAdmin
from .models import Widget

explorer.register(Widget, WidgetAdmin, group="Tools")
```

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | Model class | required | The Django model |
| `admin_class` | ModelAdmin subclass | `ModelAdmin` | Config source for fields, displays, etc. |
| `group` | `str` | app label (title-cased) | Display group in Explorer index and URL slug |

### 2. Autodiscovery

Explorer automatically imports `explorer.py` from every installed app on startup. No manual wiring needed — just create the file.

### 3. Legacy: `explorer_enabled` on Admin

```python
@admin.register(Widget)
class WidgetAdmin(admin.ModelAdmin):
    list_display = ["name", "category"]
    explorer_enabled = True  # Discovered from admin.site._registry
```

Models already registered via `explorer.py` take precedence — they won't be duplicated if also marked with `explorer_enabled`.

## Explorer-Specific Attributes

Set these on the `ModelAdmin` subclass passed to `explorer.register()`:

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `explorer_displays` | `list` | `[TableDisplay]` | Display classes for the list view. See [Display Protocol](#display-protocol). |
| `explorer_detail_displays` | `list` | `[]` | Display classes for the detail view. |
| `explorer_fields` | `list[str]` | `None` | Override which fields are shown. Falls back to `list_display` (real fields only), then auto-detection. |
| `explorer_readonly` | `bool` | `None` | Force readonly mode (list + detail only). `None` = auto-detect from permissions. |
| `explorer_field_transforms` | `dict` | `{}` | Field rendering transforms for basic table display. |
| `explorer_paginate_by` | `int` | `None` | Items per page in list view. Unset: the ModelAdmin's `list_per_page` if it sets one, else 10. |
| `explorer_enable_api` | `bool` | `False` | Generate REST API endpoints for this model. |
| `explorer_enable_mcp` | `bool` | `False` | Generate MCP tools for this model (staff-only). |
| `explorer_enable_search` | `bool` | `False` | Add it to the ranked search index over its `search_fields`. |
| `explorer_enable_webhooks` | `bool` | `False` | Send outbound webhook events when its rows change. |
| `explorer_export_formats` | `list` | `[]` | Enabled export formats, e.g. `["csv", "json"]`. |
| `explorer_bulk_actions` | `list` | `["delete"]` | Bulk actions on list view. Options: `"delete"`, `"update"`. Set to `[]` to disable. |
| `explorer_related_tabs` | `list\|None\|False` | `None` | Related object tabs on detail page. `None`=auto-discover reverse FKs with registered CRUDViews. A list of accessor names shows only those tabs in that order. `False`=disabled. |
| `explorer_related_tabs_exclude` | `list` | `[]` | Accessor names to exclude from auto-discovery. |
| `explorer_related_tabs_paginate_by` | `int` | `10` | Rows per tab in related object tabs. |
| `explorer_model_permissions` | `bool\|None` | `None` | Check Django model permissions for this model. `None` follows the `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` setting. See [Permissions](#permissions). |
| `explorer_enable_history` | `bool` | `True` | The History button on the detail page: the row's audit trail. |

## Standard ModelAdmin Attributes

These Django-standard attributes are read by Explorer:

| Attribute | Django Behavior | Explorer Behavior |
|-----------|----------------|-------------------|
| `list_display` | Changelist columns | List columns, including ModelAdmin methods, model methods and properties, callables and `__str__`, with the header from `@admin.display(description=…)` and ✓ / — for `boolean=True`. Its model fields are also the form fields. With the default `("__str__",)`, fields are auto-detected. |
| `readonly_fields`, `exclude` | Not editable / not on the form | Left off the create and edit forms; still on the list and detail page. |
| `fields` | Detail/edit field list | Detail view fields (flat list). |
| `fieldsets` | Grouped field layout | Flattened into detail fields. |
| `ordering` | Default changelist order | The list's default order. |
| `list_select_related` | Joins on the changelist query | The same joins. When `False`, the foreign keys shown in the list are joined, as in Django admin. |
| `search_fields` | Admin search box | The list's search box, REST `?q=` and MCP `q`, with Django admin's prefixes: `^` starts with, `=` exact, `@` substring (no portable full-text lookup). |
| `list_per_page` | Changelist pagination | Rows per page when the ModelAdmin sets it (`explorer_paginate_by` wins; otherwise 10). |
| `list_filter` | Sidebar filters | Toolbar dropdowns and REST/MCP filter parameters. `SimpleListFilter` classes work with their own `lookups()` and `queryset()`. |
| `has_add_permission()` | Controls "Add" button | Auto-detects readonly mode. |
| `has_change_permission()` | Controls editing | Auto-detects readonly mode. |

Explorer doesn't read `inlines`, `actions`, `date_hierarchy`, `autocomplete_fields`, `raw_id_fields`,
`list_editable`, `form` or the ModelAdmin's hooks (`get_queryset()`, `save_model()` and the like).

## Display Protocol

Display classes control how data renders in the list and detail views. Explorer ships with five built-in displays.

### List Displays

| Class | Name | Constructor | Description |
|-------|------|-------------|-------------|
| `TableDisplay` | `table` | `TableDisplay` | Sortable HTML table with field transforms and bulk-select. Default. |
| `CardDisplay` | `cards` | `CardDisplay` | Zero-config card grid — label:value rows using the model's `list_fields`. |
| `AvatarCardDisplay` | `cards` | `AvatarCardDisplay(title_field=None, subtitle_field=None, image_field=None, pill_field=None, pill_label=None, show_avatar=None)` | Card grid with avatar + title + subtitle + optional pill. |
| `CalendarDisplay` | `calendar` | `CalendarDisplay(date_field, end_field=None, title_field=None, status_field=None, variant="chip", month_param="month")` | Month-grid calendar. Events render on their date cell; `end_field` stretches ranged events across days; `status_field` tints chips green/yellow/red for `"success"`/`"warning"`/`"danger"`; `variant="block"` swaps small chips for one large colored block per day (for daily stats). |

### Detail Displays

| Class | Name | Constructor | Description |
|-------|------|-------------|-------------|
| `DetailTableDisplay` | `table` | `DetailTableDisplay` | Vertical key/value table. |
| `DetailCardDisplay` | `card` | `DetailCardDisplay(image_field=None)` | 2-column: image left, fields right. |

### Custom Displays

Subclass `ListDisplay` or `DetailDisplay`:

```python
from apps.smallstack.displays import ListDisplay

class ChartDisplay(ListDisplay):
    name = "chart"
    icon = '<svg>...</svg>'
    template_name = "myapp/displays/chart.html"

    def get_context(self, queryset, crud_config, request):
        """Return template context for rendering."""
        return {"chart_data": aggregate(queryset)}
```

Register it:

```python
class MyAdmin(admin.ModelAdmin):
    explorer_displays = [TableDisplay, ChartDisplay]
```

When multiple displays are configured, Explorer shows a palette. The user clicks an icon and HTMX swaps the display in place.

## Field Auto-Detection

When `explorer_fields` is not set and `list_display` yields no real fields, Explorer auto-detects:

1. Iterates `model._meta.get_fields()`
2. Skips reverse relations and many-to-many fields
3. Skips `AutoField` and `BigAutoField`
4. Skips the `password` field
5. Skips non-editable fields
6. Returns the remaining field names

## Field Transforms

Transforms change how field values render in the list table and the card displays.

```python
class MyAdmin(admin.ModelAdmin):
    explorer_field_transforms = {
        "bio": "preview",          # Truncate with HTMX expand
        "status": ("badge", {}),   # Colored badge (future)
    }
```

Transforms can be:
- A string name: `"preview"`
- A tuple: `("badge", {"colors": {"active": "green"}})`
- A callable: `lambda value, obj, field_name, context: formatted_value`

## Permissions

Explorer is for staff only. Within that, it does one of two things:

- **By default,** any staff account may view, create, edit and delete every model registered with Explorer.
- **With `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = True`,** Explorer checks Django's model permissions the way Django admin does. A staff account sees a model only with its `view` (or `change`) permission, and creates, edits or deletes only with `add`, `change` or `delete`. Grant them with groups. The index, buttons, bulk actions, related tabs and Explorer's REST endpoints follow the same permissions. A delete that would also remove rows of an admin-registered model the user may not delete is refused.

Turning the setting on narrows access for staff accounts that hold no permissions yet, so grant them before you switch it on. Superusers keep everything. `explorer_model_permissions` on a ModelAdmin overrides the setting for that model.

Readonly mode (below) still applies on top: a readonly model offers no create, edit or delete to anyone.

## Readonly Mode

Explorer determines readonly status in this order:

1. **Explicit:** `explorer_readonly = True` on the admin class
2. **Auto-detected:** If `has_add_permission()` or `has_change_permission()` returns `False`
3. **Default:** Full CRUD (list, create, detail, update, delete)

Readonly models get `Action.LIST` and `Action.DETAIL` only — no create, update, or delete.

## Complete Example

```python
# apps/profile/explorer.py
from django.contrib import admin
from apps.explorer.registry import explorer
from apps.smallstack.displays import (
    AvatarCardDisplay, DetailCardDisplay, DetailTableDisplay, TableDisplay,
)
from .models import UserProfile

class UserProfileExplorerAdmin(admin.ModelAdmin):
    # Standard Django attrs (read by Explorer)
    list_display = ("user", "display_name", "bio", "location", "created_at")
    search_fields = ("user__username", "display_name", "location")
    list_per_page = 12

    # Explorer-specific attrs
    explorer_displays = [
        TableDisplay,
        AvatarCardDisplay(title_field="user", subtitle_field="created_at"),
    ]
    explorer_detail_displays = [
        DetailTableDisplay,
        DetailCardDisplay(image_field="profile_photo"),
    ]
    explorer_field_transforms = {"bio": "preview"}
    explorer_enable_api = True
    explorer_export_formats = ["csv"]

explorer.register(UserProfile, UserProfileExplorerAdmin, group="Users")
```

## See Also

- [Model Explorer](/smallstack/help/smallstack/explorer/) — Overview, registration, and display palette
- [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) — API authentication, CRUD endpoints, custom endpoints, and testing
- [Explorer Composability](/smallstack/help/smallstack/explorer-composability/) — Embed Explorer into custom pages
