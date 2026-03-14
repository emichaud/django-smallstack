---
title: Model Explorer
description: A staff-facing data browser that auto-generates CRUD views from your Django admin registrations
---

# Model Explorer

Explorer is SmallStack's built-in model browser. It reads your existing Django `ModelAdmin` registrations and generates a full CRUD interface — list, detail, create, update, delete — without writing views, templates, URLs, or table classes.

You opt models in with a single attribute (`explorer_enabled = True`), and Explorer does the rest. It's the fastest path from "I have a model" to "I can manage it in a browser."

**Direct link:** [Open Explorer](/smallstack/explorer/)

## How It Works

Explorer runs on an **admin-first** discovery system:

1. On app startup, Explorer's registry walks `admin.site._registry`
2. Any `ModelAdmin` with `explorer_enabled = True` is picked up
3. Explorer reads `list_display`, permissions, and other supported admin attributes
4. It dynamically generates a `CRUDView` subclass for each registered model
5. URL patterns are built and injected at `/smallstack/explorer/`

The result is a staff-only data browser at `/smallstack/explorer/` with:

- **Index page** — a grid of all registered models grouped by custom groups or Django app
- **Sidebar filtering** — switch between group view and app view
- **Per-model CRUD** — list with sorting, detail view, create/edit forms, and delete confirmation
- **Readonly detection** — models with restricted permissions automatically get list + detail only

### Accessing Explorer

Explorer is registered in the **Admin** section of the sidebar nav and is restricted to staff users:

- **Sidebar:** Admin → Explorer
- **Apps menu:** The grid icon in the topbar (staff only)
- **Direct URL:** `/smallstack/explorer/`

## Enabling Models

Add `explorer_enabled = True` to any `ModelAdmin`. That's the only required step.

```python
# apps/myapp/admin.py
from django.contrib import admin
from .models import Widget

@admin.register(Widget)
class WidgetAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_active", "created_at"]
    explorer_enabled = True
```

Explorer reads `list_display` for columns (real model fields only — callables are skipped). If no real fields remain, it auto-detects from the model's field definitions.

### Custom Explorer Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `explorer_enabled` | `bool` | `False` | Opt this model into Explorer. Required. |
| `explorer_fields` | `list[str]` | `None` | Override which fields Explorer shows. Falls back to `list_display` (real fields only), then auto-detection. |
| `explorer_readonly` | `bool` | `None` | Force readonly mode (list + detail only). When `None`, Explorer auto-detects from `has_add_permission` and `has_change_permission`. |

### Examples

**With field overrides** — show a different set of fields in Explorer than in Django admin:

```python
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "priority", "assignee", "created_at"]
    explorer_enabled = True
    explorer_fields = ["title", "status", "priority"]  # simpler view for Explorer
```

**Auto-detected readonly** — override permissions and Explorer detects it automatically:

```python
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "user", "action", "detail"]
    explorer_enabled = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

**Explicit readonly** — force readonly mode directly:

```python
@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "updated_at"]
    explorer_enabled = True
    explorer_readonly = True
```

### Field Auto-Detection

When `explorer_fields` is not set and `list_display` contains no real model fields, Explorer falls back to auto-detection:

1. Iterates over `model._meta.get_fields()`
2. Skips reverse relations and many-to-many fields
3. Skips `AutoField` and `BigAutoField` (primary keys)
4. Skips the `password` field
5. Skips non-editable fields
6. Returns the remaining field names

## Explorer vs CRUDView

| | Explorer | CRUDView |
|---|----------|----------|
| **Setup** | One attribute on ModelAdmin | View class + table class + URL wiring |
| **Customization** | Admin API attributes | Full control over views, forms, templates |
| **Layout** | Auto-generated from registry | You design the page |
| **Best for** | Quick data browsing, staff tools | Production-facing management pages |

Start with Explorer for rapid prototyping and internal tools. When you need custom layouts or user-facing workflows, graduate to [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/). Explorer's composability mixins bridge the gap — embed auto-generated tables inside custom pages without rewriting anything.
