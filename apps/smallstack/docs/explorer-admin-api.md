---
title: Explorer ModelAdmin API
description: Full reference for ModelAdmin attributes that Explorer reads, supports, and plans to support
---

# Explorer ModelAdmin API Reference

Explorer piggybacks on Django's admin registry. Instead of building a parallel registration system, Explorer reads your existing `ModelAdmin` classes and reuses what it can.

## How Discovery Works

1. When the app starts, `ExplorerRegistry.discover()` walks `admin.site._registry`
2. For each registered model, it checks for `explorer_enabled = True` on the `ModelAdmin`
3. Models without that flag are ignored entirely — Explorer is opt-in
4. For opted-in models, Explorer reads supported `ModelAdmin` attributes (like `list_display`) to configure the generated CRUD views
5. If a `ModelAdmin` attribute is missing or contains unsupported entries (like callables in `list_display`), Explorer falls back to auto-detection from the model's fields

## Custom Explorer Attributes

These attributes are specific to Explorer and are set directly on your `ModelAdmin` subclass.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `explorer_enabled` | `bool` | `False` | Opt this model into Explorer. Required. |
| `explorer_fields` | `list[str]` | `None` | Override which fields Explorer shows. Falls back to `list_display` (real fields only), then auto-detection. |
| `explorer_readonly` | `bool` | `None` | Force readonly mode (list + detail only). When `None`, Explorer auto-detects by checking `has_add_permission` and `has_change_permission`. |
| `explorer_accessories` | — | — | Reserved for future use (charts, maps, visualizations). |

## Supported Django ModelAdmin Attributes

These attributes are read by Explorer today and affect the generated views.

| Attribute | Django Admin Behavior | Explorer Behavior | Notes |
|-----------|-----------------------|-------------------|-------|
| `list_display` | Columns shown in the changelist | Fields shown in Explorer list and forms | Only real model fields are used. Callables, `__str__`, and non-field entries are silently skipped. Falls back to auto-detected fields if none remain. |
| `has_add_permission()` | Controls whether the "Add" button appears | Auto-detects readonly mode | If overridden to return `False`, Explorer removes create/update/delete actions. |
| `has_change_permission()` | Controls whether editing is allowed | Auto-detects readonly mode | If overridden to return `False`, Explorer removes create/update/delete actions. |

## Planned Attributes

These are low-hanging fruit that Explorer could read from your existing `ModelAdmin` with relatively small implementation effort.

| Attribute | Django Admin Behavior | Explorer Potential | Notes |
|-----------|-----------------------|-------------------|-------|
| `ordering` | Default sort order | Default sort for Explorer list | Straightforward to pass through to the queryset. |
| `search_fields` | Enables a search box | Search box in Explorer | Requires adding a search input to the list template. |
| `list_per_page` | Rows per page (default 100) | Pagination size | Explorer currently hardcodes `paginate_by = 25`. |
| `list_filter` | Sidebar filters | Filter controls in Explorer | Requires building filter UI components. |
| `date_hierarchy` | Date-based drilldown | Date navigation in Explorer | Requires building date nav UI. |
| `list_display_links` | Which columns link to detail | Configurable link columns | Currently Explorer links the first column. |
| `list_editable` | Inline editing in changelist | Inline editing in Explorer | Requires form handling in the list view. |

## Not Supported

These attributes are unlikely to be supported because they are tightly coupled to Django admin internals, require significant new UI, or don't map to Explorer's design.

| Attribute | Why Not Supported |
|-----------|-------------------|
| `list_display` (callables) | Would require invoking arbitrary methods and handling their output formatting. |
| `fieldsets` | Explorer uses a flat field list. Different UX model. |
| `inlines` | Major feature requiring nested form handling and related-object UI. |
| `actions` | Explorer's CRUD actions are per-object. Bulk actions are a different concept. |
| `autocomplete_fields` | Tied to Django admin's widget and URL system. |
| `raw_id_fields` | Admin-specific widget pattern. |
| `form` | Explorer generates its own forms from the field list. |
| `formfield_overrides` | Coupled to Django admin's form generation pipeline. |
| `filter_horizontal` / `filter_vertical` | Admin-specific widgets. |
| `prepopulated_fields` | Admin-specific JavaScript behavior. |
| `readonly_fields` | Explorer treats the whole model as readonly or not. Per-field control not yet supported. |
