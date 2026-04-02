---
title: Tables
description: HTML tables with built-in column sorting and SmallStack's dark theme
---

# Tables

SmallStack ships with purpose-built table styles that look great in both light and dark mode. The styling uses CSS custom properties (`--primary`, `--body-bg`, `--body-quiet-color`, etc.) and the `color-mix()` function so that row colors, hover states, and header backgrounds adapt automatically when the user toggles themes.

If you drop a plain `<table>` into a template without the right classes, it will look out of place -- white backgrounds in dark mode, no hover states, harsh borders. This guide shows you how to get tables that match the built-in apps like User Manager, Activity Tracking, and Explorer.

## Quick Start: HTML Tables

The fastest way to get a good-looking table is to include the built-in table styles partial and use the `crud-table` class.

### Step 1: Include the table styles

Add this to your template's `extra_css` block:

```html
{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}
{% endblock %}
```

### Step 2: Use the `crud-table` class

```html
<div class="card">
    <div class="card-body">
        <table class="crud-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Created</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Widget Alpha</td>
                    <td>Active</td>
                    <td>Mar 10, 2026</td>
                </tr>
                <tr>
                    <td>Widget Beta</td>
                    <td>Draft</td>
                    <td>Mar 12, 2026</td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
```

That gives you:

- **Striped rows** -- alternating backgrounds using `color-mix(in srgb, var(--primary) 4%, var(--body-bg))` and `color-mix(in srgb, var(--primary) 12%, var(--body-bg))`
- **Hover highlight** -- rows light up to `color-mix(in srgb, var(--primary) 20%, var(--body-bg))` on hover
- **Themed header** -- uppercase, muted text, subtle primary-tinted background
- **No harsh borders** -- clean, borderless look that works in both themes
- **Primary-colored links** -- any `<a>` inside the table picks up `var(--primary)` automatically

### What NOT to do

```html
<!-- DON'T: plain table with no class -->
<table>
    <tr><td>This will look terrible in dark mode</td></tr>
</table>

<!-- DON'T: hardcoded colors -->
<table style="background: white;">
    <tr style="background: #f5f5f5;"><td>This breaks dark mode</td></tr>
</table>

<!-- DON'T: Bootstrap table classes without SmallStack integration -->
<table class="table table-dark table-striped">
    <tr><td>SmallStack doesn't use Bootstrap -- these classes do nothing</td></tr>
</table>
```

Always use `crud-table` and let the CSS variables handle the theming.

## Built-in Column Sorting

The built-in `TableDisplay` and `{% crud_table %}` tag now support column sorting via HTMX. Clicking a column header sorts ascending, clicking again sorts descending, and a third click clears the sort. Sort indicators (▲/▼) show the active sort direction.

Sorting works automatically for any column backed by a real model field. Computed or transform-only columns render as plain (non-clickable) headers.

### How it works

- The list view reads `?ordering=field` (or `?ordering=-field` for descending) from the URL
- Allowed fields are derived from `list_fields`, filtered to actual model fields
- Override with `ordering_fields` on your CRUDView to allow/restrict specific fields
- Sort state persists in the URL via `hx-push-url="true"`, so sorting works with search and filters

### Using `{% sortable_th %}` in manual tables

For tables outside CRUDView (like the Activity app), use the `{% sortable_th %}` template tag:

```html
{% load crud_tags %}
<table class="crud-table">
    <thead>
        <tr>
            {% sortable_th "name" "Name" target="#my-table-container" %}
            {% sortable_th "created_at" "Created" target="#my-table-container" %}
            <th>Non-sortable Column</th>
        </tr>
    </thead>
    ...
</table>
```

The tag reads `?ordering=` from the request, shows the correct indicator, and generates HTMX attributes for the toggle.

## Stable Column Widths

Tables use `table-layout: fixed` so column widths are determined by the header row, not cell content. This prevents columns from shifting when sort order changes and different rows become visible.

Long content is truncated with CSS `text-overflow: ellipsis`. Hovering any truncated cell shows the full value in a native tooltip.

### Custom column proportions

For tables where equal-width columns don't make sense (e.g., a wide "Path" column alongside a narrow "Method" column), use a `<colgroup>`:

```html
<table class="crud-table">
    <colgroup>
        <col style="width: 20%;">
        <col style="width: 50%;">
        <col style="width: 15%;">
        <col style="width: 15%;">
    </colgroup>
    ...
</table>
```

For CRUDView tables, set `column_widths` on the view class instead:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    list_fields = ["name", "description", "status", "created_at"]
    column_widths = {"name": "20%", "description": "50%"}
```

Fields not listed in `column_widths` share the remaining space equally.

## Matching the Built-in Theme

Every table in SmallStack's built-in apps follows the same visual pattern. Here is exactly what the `_table_styles.html` partial provides and the CSS variables it relies on.

### The `crud-table` class breakdown

| Style | CSS | What it does |
|-------|-----|--------------|
| **Full width** | `width: 100%; border-collapse: collapse;` | Table spans its container |
| **Header row** | `background-color: color-mix(in srgb, var(--primary) 15%, var(--body-bg))` | Subtle primary-tinted header |
| **Header text** | `text-transform: uppercase; font-size: 0.8rem; font-weight: 600; letter-spacing: 0.3px; color: var(--body-quiet-color)` | Muted, uppercase labels |
| **Odd rows** | `background-color: color-mix(in srgb, var(--primary) 4%, var(--body-bg))` | Very subtle stripe |
| **Even rows** | `background-color: color-mix(in srgb, var(--primary) 12%, var(--body-bg))` | Slightly more visible stripe |
| **Hover** | `background-color: color-mix(in srgb, var(--primary) 20%, var(--body-bg))` | Interactive feedback |
| **Cell padding** | `padding: 10px 16px; font-size: 0.85rem` | Comfortable density |
| **No borders** | `border: none !important` on all elements | Clean, modern look |
| **Links** | `color: var(--primary)` | Consistent link color |

### Tables inside stat modals

SmallStack's stat modal (`smallstack/includes/stat_modal.html`) has its own table styles under `.stat-modal-panel table`. These mirror the `crud-table` styles -- same striped rows, same hover, same header treatment -- so any `<table>` inside a stat modal looks consistent automatically. You don't need to add `crud-table` to tables inside the modal.

## Bulk Selection

CRUDView and Explorer tables include bulk selection checkboxes by default (when bulk actions are enabled). A "select all" checkbox in the header toggles all visible rows, and a compact action bar appears below the toolbar with the selection count and available actions (Delete, Update, Clear).

Bulk delete is enabled by default — no configuration needed. Set `bulk_actions = []` on CRUDView or `explorer_bulk_actions = []` on the ModelAdmin to disable the checkboxes.

## CRUDView Tables

If you are using SmallStack's CRUDView system, table setup is automatic. Use `TableDisplay` (the default) -- it renders the `{% crud_table %}` tag with built-in column sorting, pagination, and themed styling. No separate table class is needed.

```python
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import TableDisplay

class ItemCRUDView(CRUDView):
    model = Item
    fields = ["name", "category", "is_active"]
    list_fields = ["name", "category", "is_active", "created_at"]
    url_base = "manage/items"
    paginate_by = 10
    displays = [TableDisplay]
    # ordering_fields = ["name", "created_at"]  # optional: restrict sortable columns
```

Column headers are automatically sortable for any field backed by a real model field. The `ordering_fields` attribute lets you restrict which columns are sortable.

For the full walkthrough on setting up CRUD pages with tables, see [Building CRUD Pages](/smallstack/help/building-crud-pages/).

## Common Pitfalls

**Plain `<table>` without `crud-table`** -- The most common mistake. You get browser-default white backgrounds that blow out in dark mode. Always add `class="crud-table"` and include the `_table_styles.html` partial.

**Hardcoded background colors** -- Writing `style="background: #f5f5f5"` on rows or cells defeats the theming system. Use CSS variables: `var(--body-bg)`, `var(--card-bg)`, or `color-mix()` expressions with `var(--primary)`.

**Hardcoded text colors** -- Same problem. Use `var(--body-fg)` for regular text, `var(--body-quiet-color)` for muted text, `var(--primary)` for emphasis.

**Using Bootstrap classes** -- SmallStack does not use Bootstrap. Classes like `table-dark`, `table-striped`, or `table-hover` have no effect. Use `crud-table` instead.
