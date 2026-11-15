---
name: explorer
description: "Model Explorer — the zero-code CRUD browser generated from existing ModelAdmin registrations; explorer_displays, dashboard widgets"
license: MIT
metadata:
  source: "docs/skills/explorer.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/explorer.md` by `make skills-index` — edit the source, not this file.

# Skill: Model Explorer

Explorer is SmallStack's built-in model browser. It reads existing Django `ModelAdmin` registrations and generates a full CRUD interface — list, detail, create, update, delete — without writing views, templates, URLs, or table classes.

## Overview

Explorer is driven by `ModelAdmin` classes. In `ExplorerConfig.ready()`:

1. `explorer.autodiscover()` imports each installed app's `explorer.py`, whose
   `explorer.register(Model, SomeAdmin, group="…")` calls are the recommended way in
2. `explorer.discover_admin()` adds models whose admin sets `explorer_enabled = True`
   (or every admin-registered model when `EXPLORER_DISCOVER_ALL = True`, as in development)
3. `explorer.build_crud_classes()` reads each ModelAdmin (see **Supported Django
   ModelAdmin Attributes**) and generates a `CRUDView` subclass per model
4. Their URL patterns are mounted under `/smallstack/explorer/`

The result is a staff-only data browser with an index page, group and app sidebars, per-model CRUD, readonly detection, an audit trail and, optionally, Django model permissions.

## File Locations

```
apps/explorer/
├── apps.py                # ExplorerConfig — nav registration
├── registry.py            # ExplorerSite — model registration and CRUDView generation
├── mixins.py              # ExplorerGroupMixin, ExplorerAppMixin, ExplorerModelMixin
├── urls.py                # URL patterns
├── views.py               # Index and example pages
└── templates/explorer/    # Explorer-specific templates

apps/smallstack/docs/      # In-app help at /smallstack/help/
├── explorer.md            # Overview
├── explorer-admin-api.md  # The ModelAdmin attributes Explorer reads
├── explorer-rest-api.md   # Explorer's REST endpoints
└── explorer-composability.md  # Embedding Explorer in your own pages
```

## Enabling Models

Register the model in an `explorer.py` in your app (imported automatically):

```python
# apps/myapp/explorer.py
from apps.explorer.registry import explorer

from .admin import WidgetAdmin
from .models import Widget

explorer.register(Widget, WidgetAdmin, group="Tools")
```

Or, the older way, set `explorer_enabled = True` on the `ModelAdmin` registered with
`admin.site`. A model registered both ways appears once, from `explorer.py`.

Explorer takes its columns from `list_display`, methods and callables included
(see below). With the default `list_display` it auto-detects fields from the model.

## Custom Explorer Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `explorer_enabled` | `bool` | `False` | Opt this model into Explorer. Required. |
| `explorer_fields` | `list[str]` | `None` | Override which fields Explorer shows and edits. Falls back to `list_display`'s model fields, then auto-detection. |
| `explorer_list_fields` | `list[str]` | `None` | The list table's columns only (forms keep `explorer_fields`). Replaces the columns `list_display` would give. |
| `explorer_readonly` | `bool` | `None` | Force readonly mode (list + detail only). When `None`, auto-detects from `has_add_permission` and `has_change_permission`. |
| `explorer_group` | `str` | `app_label.title()` | Custom group name for the Explorer index page. |
| `explorer_paginate_by` | `int` | `None` | Rows per page in the list. Unset: the ModelAdmin's `list_per_page` if it sets one, else 10. |
| `explorer_preview_fields` | `list[str]` | `[]` | Fields that get truncated with click-to-preview. Merged into `field_transforms`. |
| `explorer_field_transforms` | `dict` | `{}` | Custom field rendering: `{field: "transform_name"}`. Overrides preview mappings. |
| `explorer_displays` | `list` | `[TableDisplay]` | Display protocol classes for list view. Add `CardDisplay`, `AvatarCardDisplay`, or `CalendarDisplay` for alternate views. See `card-displays.md` and `calendar-displays.md`. |
| `explorer_detail_displays` | `list` | `[]` | Display protocol classes for detail view. |
| `explorer_form_displays` / `explorer_create_displays` / `explorer_edit_displays` | `list` | `[]` | Form display classes (both forms / create only / edit only). |
| `explorer_form_class` | `ModelForm` | `None` | The form for create and edit. A child site's `set_form()` wins over it. |
| `explorer_column_widths` | `dict` | `None` | `{field: "140px"}` for the list table. |
| `explorer_list_accessories` | `list` | `[]` | Panels above the list toolbar (`ListAccessory` instances). |
| `explorer_bulk_actions` | `list[str]` | `["delete"]` | Bulk actions on the list: `"delete"`, `"update"`; `[]` for none. |
| `explorer_export_formats` | `list` | `[]` | Export formats, e.g. `["csv", "json"]`. |
| `explorer_api_extra_fields` | `list[str]` | `[]` | Read-only fields appended to API responses |
| `explorer_api_expand_fields` | `list[str]` | `[]` | FK fields always expanded in API responses |
| `explorer_api_aggregate_fields` | `list[str]` | `[]` | Fields supporting `?sum=`, `?avg=`, `?min=`, `?max=` |
| `explorer_enable_api` | `bool` | `False` | Enable REST API endpoints for this model. |
| `explorer_enable_mcp` | `bool` | `False` | Generate MCP tools (`list_<plural>`, `get_<singular>`, …, named from the verbose names), staff-only. |
| `explorer_enable_search` | `bool` | `False` | Add the model to the ranked search index (omnibar, `/smallstack/search/`, the `search_all` tool) over its `search_fields`. |
| `explorer_enable_webhooks` | `bool` | `False` | Send outbound webhook events when rows change. |
| `explorer_related_tabs` | `list\|None\|False` | `None` | Related object tabs on detail page. `None`=auto-discover, list=explicit accessor names, `False`=disabled |
| `explorer_related_tabs_exclude` | `list` | `[]` | Accessor names to exclude from auto-discovery |
| `explorer_related_tabs_paginate_by` | `int` | `10` | Rows per tab in related object tabs |
| `explorer_dashboard_widgets` | `list` | `[]` | Dashboard widgets published by this model. See `dashboard-widgets.md`. |
| `explorer_model_permissions` | `bool\|None` | `None` | Check Django model permissions for this model (see **Permissions** below). `None` follows `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS`. |
| `explorer_enable_history` | `bool` | `True` | The **History** button on the detail page: the row's `LogEntry` audit trail at `<pk>/history/`. |

The three `explorer_enable_*` switches act only when Explorer's view is the one
serving the model. A model your app already exposes through its own `CRUDView`
keeps that view's MCP tools, search entry and webhooks: Explorer logs a warning
and registers nothing more. They apply on the main Explorer, not on child sites.

## Supported Django ModelAdmin Attributes

| Attribute | Explorer Behavior |
|-----------|-------------------|
| `list_display` | The list's columns. Model fields are also the form fields (unless `explorer_fields` is set). Methods on the ModelAdmin, model methods and properties, plain callables and `"__str__"` become columns too, with Django admin's header (`@admin.display(description=…)`) and value; `boolean=True` shows ✓ / —. They aren't sortable. |
| `readonly_fields`, `exclude` | Kept off the create and edit forms; still shown on the list and detail page. |
| `fields`, `fieldsets` | The detail page's fields (flattened). |
| `ordering` | The list's default order, before a column header is clicked. |
| `list_select_related` | `True` or a list: joined in the list's query. `False` (Django's default): the foreign keys shown in the list are joined, as Django admin does. |
| `list_per_page` | Rows per page, when the ModelAdmin sets it and `explorer_paginate_by` doesn't. |
| `search_fields` | The list's search box, REST `?q=` and the MCP `list_*` tool's `q`. Django admin's prefixes work: `^name` starts with, `=email` exact (case-insensitive), `@body` a substring match (Explorer has no portable full-text lookup; `explorer_enable_search` is the ranked search). |
| `list_filter` | Field names and `(field, FilterClass)` pairs: the list's filter dropdowns and REST/MCP filter parameters. `SimpleListFilter` classes: a dropdown of their `lookups()`, filtering with their `queryset()`, on the list, REST and MCP. Other `ListFilter` classes are ignored. |
| `has_add_permission()`, `has_change_permission()` | Overridden to refuse: the model is readonly (list and detail only). |
| `has_view/add/change/delete_permission()` overrides | Asked on every surface (pages, bulk actions, REST, MCP), whatever `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` says. `has_change_permission(request, obj)` and `has_delete_permission(request, obj)` are also asked **per row** with the object, so a rule about one row (UserAdmin: only a superuser changes a superuser) holds in Explorer as in Django admin. See **Permissions**. |

Not read: `inlines`, `actions`, `date_hierarchy`, `autocomplete_fields`, `raw_id_fields`,
`list_editable`, `form`, `save_model()` and other ModelAdmin hooks, and `get_queryset()`.
Use Django admin (still at `/admin/`) or a `CRUDView` of your own for those.

## Permissions

By default any staff account may do everything in Explorer. Set
`SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = True` (env var of the same name) and
Explorer checks Django's model permissions the way Django admin does: `view`
(or `change`) to see a model's list and rows, `add` to create, `change` to edit
and `delete` to delete. Grant them with groups or per user, as for Django admin;
superusers hold all four. With it on:

- the index lists only the models a user may view, and pages, buttons, bulk
  actions and related tabs follow the user's permissions (a 403 for the rest);
- Explorer's REST endpoints check the same permission by method (GET view,
  POST add, PUT/PATCH change, DELETE delete);
- a delete that would cascade into rows of an admin-registered model the user
  may not delete is refused, as in Django admin.

`StaffRequiredMixin` still applies first: permissions narrow what a staff
account may do, they don't open Explorer to non-staff users. A ModelAdmin's
`explorer_model_permissions = True` / `False` overrides the setting for one model.
Turning it on is a behaviour change for staff accounts that hold no explicit
permissions: they lose access until they are granted some.

**A ModelAdmin's own `has_*_permission` methods apply either way.** When the
ModelAdmin declares one, Explorer asks it (fail closed: a method that raises
refuses). `has_change_permission(request, obj)` and
`has_delete_permission(request, obj)` are asked for each row too, through the
view's `can_update` / `can_delete`, so the row's edit and delete buttons, pages,
bulk actions, REST and MCP all follow it:

```python
class InvoiceAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status == "paid":
            return False          # paid invoices are read-only, in admin and Explorer
        return super().has_change_permission(request, obj)
```

`super()` is Django's model-permission check (`change_invoice`), so with an
override like this staff need that permission in Explorer even with
`SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` off. This was new in the Access release
(before it, Explorer ignored the per-object form): check a downstream
ModelAdmin's overrides when you upgrade.

## Audit trail and delete confirmation

Creates, edits and deletes made on Explorer's pages write a Django `LogEntry`,
as its REST endpoints and bulk actions already did. Each detail page has a
**History** button listing every entry for that row, from every surface, Django
admin's included. The delete confirmation (the page and the modal the list and
detail pages open) lists what the delete takes with it, from Django's own
deletion collector, and offers no Delete button when a protected row stops it.

## Search, filters and export

None of these are detected from the model: a model with no `search_fields` has no
search box, and one with no `list_filter` has no filters.

| Feature | Comes from | What it enables |
|---------|------------|-----------------|
| **Search** | The ModelAdmin's `search_fields` | The list's search box and `?q=` on REST and MCP |
| **Filters** | The ModelAdmin's `list_filter` | Dropdowns in the list toolbar (choices from the values present), and REST/MCP parameters |
| **Export** | `explorer_export_formats` | `?format=csv` / `json` on the REST list |

## Field Auto-Detection

When `explorer_fields` is not set and `list_display` has no real model fields, Explorer falls back:

1. Iterates `model._meta.get_fields()`
2. Skips reverse relations, M2M, AutoField/BigAutoField, `password`, non-editable fields
3. Returns the remaining field names

## What Explorer Generates

For each opted-in model, Explorer dynamically creates a `CRUDView` subclass with:

- `model`, `fields`, `list_fields` — from `explorer_fields` / `list_display` / auto-detection; `readonly_fields` and `exclude` removed from `fields`
- `list_columns`, `column_labels` — `list_display` with its methods and callables
- `queryset` — with the ModelAdmin's `ordering` and `list_select_related`
- `url_base` — `explorer/{group-slug}/{model_name}` (no `explorer/` prefix on a child site)
- `paginate_by` — `explorer_paginate_by`, else a declared `list_per_page`, else 10
- `displays` — `explorer_displays`, default `[TableDisplay]`
- `mixins` — `[StaffRequiredMixin]`
- `model_permissions` — follows `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` / `explorer_model_permissions` (off by default)
- `enable_history` — on (`explorer_enable_history = False` turns it off)
- `actions` — LIST + DETAIL for readonly; full CRUD for editable models
- search and filters — read from the ModelAdmin's `search_fields` and `list_filter` (see above)
- `export_formats` — from `explorer_export_formats` (default `[]`)
- `enable_api`, `enable_mcp`, `enable_search`, `enable_webhooks` — from the `explorer_enable_*` switches (all off by default)
- `field_transforms` — merged from `explorer_preview_fields` + `explorer_field_transforms`
- `breadcrumb_parent` — `("Explorer", "explorer-index")` (a child site's own name and index)

## Explorer vs CRUDView

| | Explorer | CRUDView |
|---|----------|----------|
| **Setup** | A ModelAdmin + one `explorer.register()` | A `CRUDView` class + URL wiring |
| **Search** | The ModelAdmin's `search_fields` | `search_fields` on the view |
| **Filtering** | The ModelAdmin's `list_filter` | `filter_fields` on the view |
| **Export** | `explorer_export_formats` | `export_formats` |
| **API / MCP / search / webhooks** | `explorer_enable_api` / `_mcp` / `_search` / `_webhooks` | `enable_api` / `enable_mcp` / `enable_search` / `enable_webhooks` |
| **Who may use it** | Staff, optionally narrowed by model permissions | Whatever `mixins`, `model_permissions` and the per-row hooks say |
| **Customization** | Admin API attributes | Full control over views, forms, templates, hooks |
| **Layout** | Auto-generated from registry | You design the page |
| **Best for** | Quick data browsing, staff tools | Production-facing management pages |

Start with Explorer for rapid prototyping and internal tools. Graduate to CRUDView when you need custom layouts, per-row rules (`get_list_queryset`, `can_update`), non-staff users, or user-facing workflows.

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

- Explorer is staff-only: every page and REST endpoint has `StaffRequiredMixin`, and the nav entry is `staff_required=True`
- Within that, `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` adds Django model permissions (see **Permissions**)
- Registered in the **Admin** section of the sidebar nav
- Accessible via sidebar, topbar apps menu, or direct URL `/smallstack/explorer/`

## Best Practices

1. **Start with Explorer** for internal tools and prototyping
2. **Use `explorer_fields`** to show a simpler field set than Django admin
3. **Use `explorer_readonly`** for audit logs and system tables
4. **Graduate to CRUDView** when you need custom templates, stat cards, per-row rules or non-staff access
5. **Use composability mixins** to embed Explorer tables in custom dashboards
