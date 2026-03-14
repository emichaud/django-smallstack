---
title: Tables
description: HTML tables and django-tables2 with SmallStack's dark theme
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

## django-tables2 Setup

For dynamic data, [django-tables2](https://django-tables2.readthedocs.io/) is the way to go. SmallStack uses it throughout -- User Manager, Activity Tracking, Uptime Monitoring, and Explorer all use django-tables2 tables with the `crud-table` class.

### 1. Define a Table class

```python
# apps/myapp/tables.py
import django_tables2 as tables
from .models import Project

class ProjectTable(tables.Table):
    name = tables.Column()
    status = tables.Column()
    created_at = tables.DateTimeColumn(format="M d, Y")

    class Meta:
        model = Project
        fields = ("name", "status", "created_at")
        order_by = "-created_at"
        attrs = {"class": "crud-table"}   # <-- This is the key line
```

The `attrs = {"class": "crud-table"}` in `Meta` is what connects your table to SmallStack's styling. Without it, django-tables2 renders a plain unstyled table.

### 2. Use it in a view

```python
# apps/myapp/views.py
import django_tables2 as tables
from .models import Project
from .tables import ProjectTable

class ProjectListView(tables.SingleTableView):
    model = Project
    table_class = ProjectTable
    template_name = "myapp/project_list.html"
    paginate_by = 15
```

### 3. Render it in a template

```html
{% extends "smallstack/base.html" %}
{% load django_tables2 %}

{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}
<style>
    /* Sort indicators for clickable column headers */
    .crud-table thead th a { color: var(--body-quiet-color); text-decoration: none; }
    .crud-table thead th a:hover { color: var(--primary); }
    .crud-table thead th.asc a::after { content: " \25B2"; font-size: 0.65rem; }
    .crud-table thead th.desc a::after { content: " \25BC"; font-size: 0.65rem; }

    /* Pagination styling */
    ul.pagination {
        display: flex; justify-content: center; gap: 0.25rem;
        list-style: none !important; padding: 1rem 0 0 !important; margin: 0 !important;
    }
    ul.pagination li { list-style: none !important; }
    ul.pagination li a, ul.pagination li span {
        display: inline-block; padding: 0.3rem 0.75rem;
        border-radius: var(--radius-sm, 4px); color: var(--body-quiet-color);
        text-decoration: none; font-size: 0.85rem;
    }
    ul.pagination li a:hover {
        color: var(--primary);
        background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
    }
    ul.pagination li.active a, ul.pagination li.active span {
        background: var(--primary); color: var(--button-fg);
    }
</style>
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <h2>Projects</h2>
    </div>
    <div class="card-body">
        {% render_table table %}
    </div>
</div>
{% endblock %}
```

The `{% render_table table %}` tag handles the `<table>`, sorting links, and pagination all at once. The sort indicator and pagination styles above are needed because django-tables2 generates its own markup for those elements -- without the CSS, sort arrows won't appear and pagination will render as a raw bullet list.

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

### SmallStack's reusable column types

SmallStack provides three column classes in `apps.smallstack.tables` that handle common patterns:

```python
from apps.smallstack.tables import ActionsColumn, BooleanColumn, DetailLinkColumn
```

- **`DetailLinkColumn(url_base, link_view="detail")`** -- Wraps the cell value in a link to the detail or edit page. Set `link_view="update"` to go straight to the edit form.
- **`BooleanColumn(true_mark="...", false_mark="...")`** -- Renders `True` as a themed checkmark and `False` as a muted dash. Centers the content automatically.
- **`ActionsColumn(url_base, edit=True, delete=True)`** -- Adds edit (pencil) and delete (trash) icon buttons aligned to the right. The delete button uses `var(--delete-button-bg)` for the red color.

### Complete example matching built-in apps

Here is a table definition that looks exactly like User Manager or Activity Tracking:

```python
# apps/inventory/tables.py
import django_tables2 as tables
from apps.smallstack.tables import ActionsColumn, BooleanColumn, DetailLinkColumn
from .models import Item

class ItemTable(tables.Table):
    name = DetailLinkColumn(url_base="manage/items", link_view="update")
    category = tables.Column()
    in_stock = BooleanColumn(verbose_name="In Stock")
    quantity = tables.Column(attrs={"td": {"style": "text-align: right;"}})
    actions = ActionsColumn(url_base="manage/items")

    class Meta:
        model = Item
        fields = ("name", "category", "in_stock", "quantity")
        order_by = "name"
        attrs = {"class": "crud-table"}
```

### Custom rendering with `format_html`

The built-in apps use `render_<column>` methods to add visual polish. Here are patterns pulled from the real codebase:

```python
# Monospace text for paths or codes
def render_sku(self, value):
    return format_html(
        '<span style="font-family:monospace;font-size:0.9rem;">{}</span>',
        value,
    )

# Status badges with color coding
def render_status(self, value):
    colors = {
        "active": "var(--primary)",
        "archived": "var(--body-quiet-color)",
        "error": "var(--delete-button-bg, red)",
    }
    color = colors.get(value, "var(--body-fg)")
    return format_html('<span style="color:{};">{}</span>', color, value)

# Timestamps with timezone-aware formatting
def render_updated_at(self, value):
    if value:
        local = localtime(value)
        return format_html(
            '<span style="white-space:nowrap;font-size:0.85rem;">{}</span>',
            local.strftime("%b %d %I:%M %p %Z").lstrip("0"),
        )
    return format_html('<span style="color:var(--body-quiet-color);">{}</span>', chr(8212))
```

Always use `var(--primary)`, `var(--body-quiet-color)`, `var(--body-fg)`, and other CSS variables instead of hardcoded hex colors. That way your custom rendering adapts to both light and dark mode without any extra work.

### Tables inside stat modals

SmallStack's stat modal (`smallstack/includes/stat_modal.html`) has its own table styles under `.stat-modal-panel table`. These mirror the `crud-table` styles -- same striped rows, same hover, same header treatment -- so any `<table>` inside a stat modal looks consistent automatically. You don't need to add `crud-table` to tables inside the modal.

## CRUDView Tables

If you are using SmallStack's CRUDView system, table setup is largely automatic. You define a `table_class` on your CRUDView, and the generic list template handles including the table styles, rendering the table with `{% render_table %}`, and wiring up pagination.

```python
from apps.smallstack.crud import Action, CRUDView
from .tables import ItemTable

class ItemCRUDView(CRUDView):
    model = Item
    table_class = ItemTable
    paginate_by = 10
    # ... rest of config
```

The generic list template at `smallstack/crud/object_list.html` automatically includes `_table_styles.html` and adds sort indicator CSS when it detects a django-tables2 table.

For the full walkthrough on setting up CRUD pages with tables, see [Building CRUD Pages](/smallstack/help/building-crud-pages/).

## Common Pitfalls

**Plain `<table>` without `crud-table`** -- The most common mistake. You get browser-default white backgrounds that blow out in dark mode. Always add `class="crud-table"` and include the `_table_styles.html` partial.

**Hardcoded background colors** -- Writing `style="background: #f5f5f5"` on rows or cells defeats the theming system. Use CSS variables: `var(--body-bg)`, `var(--card-bg)`, or `color-mix()` expressions with `var(--primary)`.

**Hardcoded text colors** -- Same problem. Use `var(--body-fg)` for regular text, `var(--body-quiet-color)` for muted text, `var(--primary)` for emphasis.

**Missing sort indicator CSS** -- django-tables2 adds `.asc` and `.desc` classes to `<th>` elements but doesn't style them. Without the sort indicator CSS shown above, users have no visual feedback when they click a column to sort. Copy the four-line block from the template examples in this guide.

**Pagination rendered as bullet list** -- django-tables2 outputs pagination as a `<ul class="pagination">`. Without the pagination CSS, it renders as a bulleted list. Include the pagination styles shown in the django-tables2 template example.

**Forgetting `attrs` in the Table Meta** -- If you define a django-tables2 Table class but omit `attrs = {"class": "crud-table"}`, the table renders without any SmallStack styling. This is easy to miss because the table still *works* -- it just looks wrong.

**Using Bootstrap classes** -- SmallStack does not use Bootstrap. Classes like `table-dark`, `table-striped`, or `table-hover` have no effect. Use `crud-table` instead.
