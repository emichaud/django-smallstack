# Skill: Model Explorer

Explorer is SmallStack's built-in model browser. It reads existing Django `ModelAdmin` registrations and generates a full CRUD interface — list, detail, create, update, delete — without writing views, templates, URLs, or table classes.

## Overview

Explorer runs on an **admin-first** discovery system:

1. On app startup, `ExplorerSite.discover()` walks `admin.site._registry`
2. Any `ModelAdmin` with `explorer_enabled = True` is picked up
3. Explorer reads `list_display`, permissions, and other supported admin attributes
4. It dynamically generates a `CRUDView` subclass for each registered model
5. URL patterns are built and injected at `/smallstack/explorer/`

The result is a staff-only data browser with an index page, sidebar filtering, per-model CRUD, and readonly detection.

## File Locations

```
apps/explorer/
├── apps.py                # ExplorerConfig — nav registration
├── registry.py            # ExplorerSite — model registration and CRUDView generation
├── mixins.py              # ExplorerGroupMixin, ExplorerAppMixin, ExplorerModelMixin
├── urls.py                # URL patterns
├── content/               # Help documentation (app-contributed)
│   ├── _config.yaml
│   ├── index.md
│   ├── admin-api.md
│   └── composability.md
└── templates/explorer/    # Explorer-specific templates

apps/smallstack/docs/
├── explorer.md            # In-app reference (overview)
├── explorer-admin-api.md  # In-app reference (admin API)
└── explorer-composability.md  # In-app reference (composability)
```

## Enabling Models

Add `explorer_enabled = True` to any `ModelAdmin`:

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

## Custom Explorer Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `explorer_enabled` | `bool` | `False` | Opt this model into Explorer. Required. |
| `explorer_fields` | `list[str]` | `None` | Override which fields Explorer shows. Falls back to `list_display` then auto-detection. |
| `explorer_readonly` | `bool` | `None` | Force readonly mode (list + detail only). When `None`, auto-detects from `has_add_permission` and `has_change_permission`. |
| `explorer_group` | `str` | `app_label.title()` | Custom group name for the Explorer index page. |
| `explorer_paginate_by` | `int` | `10` | Rows per page in the Explorer list view. |
| `explorer_preview_fields` | `list[str]` | `[]` | Fields that get truncated with click-to-preview. Merged into `field_transforms`. |
| `explorer_field_transforms` | `dict` | `{}` | Custom field rendering: `{field: "transform_name"}`. Overrides preview mappings. |
| `explorer_displays` | `list` | `[Table2Display]` | Display protocol classes for list view. |
| `explorer_detail_displays` | `list` | `[]` | Display protocol classes for detail view. |
| `explorer_export_formats` | `list` | `[]` | Export formats, e.g. `["csv", "json"]`. |
| `explorer_api_extra_fields` | `list[str]` | `[]` | Read-only fields appended to API responses |
| `explorer_api_expand_fields` | `list[str]` | `[]` | FK fields always expanded in API responses |
| `explorer_api_aggregate_fields` | `list[str]` | `[]` | Fields supporting `?sum=`, `?avg=`, `?min=`, `?max=` |
| `explorer_enable_api` | `bool` | `False` | Enable REST API endpoints for this model. |
| `explorer_dashboard_widgets` | `list` | `[]` | Dashboard widgets published by this model. See `dashboard-widgets.md`. |

## Supported Django ModelAdmin Attributes

| Attribute | Explorer Behavior |
|-----------|-------------------|
| `list_display` | Fields shown in Explorer list and forms (real fields only) |
| `has_add_permission()` | Auto-detects readonly mode |
| `has_change_permission()` | Auto-detects readonly mode |

## Auto-Detected Features

Explorer auto-detects these from the model's fields — no configuration needed:

| Feature | How It's Detected | What It Enables |
|---------|-------------------|-----------------|
| **Search** | CharField and TextField in resolved fields → `search_fields` | `?q=` text search across the list view |
| **Filters** | Fields with choices, ForeignKey, or BooleanField → `filter_fields` | Sidebar filter controls via django-filter |
| **Export** | Set via `explorer_export_formats` | CSV and JSON download buttons when configured |

## Field Auto-Detection

When `explorer_fields` is not set and `list_display` has no real model fields, Explorer falls back:

1. Iterates `model._meta.get_fields()`
2. Skips reverse relations, M2M, AutoField/BigAutoField, `password`, non-editable fields
3. Returns the remaining field names

## What Explorer Generates

For each opted-in model, Explorer dynamically creates a `CRUDView` subclass with:

- `model`, `fields`, `list_fields` — from `explorer_fields` / `list_display` / auto-detection
- `url_base` — `explorer/{app_label}/{model_name}`
- `paginate_by` — from `explorer_paginate_by` (default 10)
- `table_class` — auto-generated django-tables2 Table with DetailLinkColumn and ActionsColumn
- `mixins` — includes `StaffRequiredMixin`
- `actions` — LIST + DETAIL for readonly; full CRUD for editable models
- `search_fields` — auto-detected CharField/TextField
- `filter_fields` — auto-detected choice/FK/boolean fields
- `export_formats` — from `explorer_export_formats` (default `[]`)
- `field_transforms` — merged from `explorer_preview_fields` + `explorer_field_transforms`
- `breadcrumb_parent` — `("Explorer", "explorer-index")`

## Explorer vs CRUDView

| | Explorer | CRUDView |
|---|----------|----------|
| **Setup** | One attribute on ModelAdmin | View class + table class + URL wiring |
| **Search** | Auto-detected from CharField/TextField | Set `search_fields` manually |
| **Filtering** | Auto-detected from choice/FK/boolean fields | Set `filter_fields` manually |
| **Export** | Set `explorer_export_formats` on ModelAdmin | Set `export_formats` manually |
| **API** | Set `explorer_enable_api = True` on ModelAdmin | Set `enable_api = True` |
| **Customization** | Admin API attributes | Full control over views, forms, templates |
| **Layout** | Auto-generated from registry | You design the page |
| **Best for** | Quick data browsing, staff tools | Production-facing management pages |

Start with Explorer for rapid prototyping and internal tools. Graduate to CRUDView when you need custom layouts, API endpoints, or user-facing workflows.

## Composability

Explorer provides four levels of abstraction for embedding CRUD into custom pages:

| Level | What | When to use |
|-------|------|-------------|
| **View mixins** | `ExplorerGroupMixin`, `ExplorerAppMixin`, `ExplorerModelMixin` | Most cases — two-line views |
| **Context helpers** | `get_group_context()`, `get_app_context()`, `get_model_context()` | Custom data or transformations |
| **Dataclasses** | `GroupContext`, `AppContext`, `ModelContext`, `ModelCardInfo` | Typed access to raw data |
| **Template tags** | `{% crud_table %}` | Render CRUD list table from context |

### View Mixin Example

```python
from django.views.generic import TemplateView
from apps.explorer.mixins import ExplorerModelMixin

class HeartbeatView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeats.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["chart_days"] = build_7day_chart()
        return context
```

```html
{% load crud_tags %}
<div class="card">{% crud_table %}</div>
```

### Groups vs Apps

| | Groups | Apps |
|---|--------|------|
| **Source** | `explorer_group` attribute on ModelAdmin | Django's `app_label` |
| **Flexibility** | Custom labels — group however you want | Fixed to Django's app structure |
| **Mixin** | `ExplorerGroupMixin` | `ExplorerAppMixin` |

## Dashboard Widgets

Admin classes can publish cards to the main dashboard (`/smallstack/`) and to per-group/per-app Explorer index pages by setting `explorer_dashboard_widgets`:

```python
class OrderAdmin(admin.ModelAdmin):
    explorer_enabled = True
    explorer_dashboard_widgets = [OrdersWidget()]
```

The widget inherits its group from the Explorer registration. The Explorer group/app index pages show a **Models | Widgets** toggle when scoped widgets exist. See `dashboard-widgets.md` for the full widget protocol, `DashboardWidget` class reference, and REST API (`/api/dashboard/widgets/`).

## Access Control

- Explorer is staff-only (`staff_required=True` in nav registration)
- Registered in the **Admin** section of the sidebar nav
- Accessible via sidebar, topbar apps menu, or direct URL `/smallstack/explorer/`

## Best Practices

1. **Start with Explorer** for internal tools and prototyping
2. **Use `explorer_fields`** to show a simpler field set than Django admin
3. **Use `explorer_readonly`** for audit logs and system tables
4. **Graduate to CRUDView** when you need custom templates, search, stat cards, or non-staff access
5. **Use composability mixins** to embed Explorer tables in custom dashboards
