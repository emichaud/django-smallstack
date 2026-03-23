# Skill: UI Components

Quick reference for SmallStack's themed UI components. All components work in both light and dark modes with zero overrides when using CSS variables.

> **Full reference:** See [admin-page-styling.md](admin-page-styling.md) for the definitive guide with all patterns, code examples, anti-patterns, and the copy-paste starter template.

## Overview

SmallStack provides styled components via CSS classes in `static/smallstack/css/components.css`. Components use `var(--primary)`, `var(--card-bg)`, `var(--body-quiet-color)`, etc. — they adapt automatically to all theme/palette combinations.

## File Locations

```
static/smallstack/css/
├── theme.css              # CSS variables, layout, page-header-bleed, stat-modal
├── components.css         # All component classes (buttons, tables, forms, cards, badges, tabs, action cards, filter toggles, stat cards, search)
└── palettes.css           # Color palette overrides

templates/smallstack/
├── base.html              # Base template with all blocks
├── starter.html           # Copy-paste starter template for new pages
├── crud/                  # CRUD generic templates
│   └── includes/
│       └── delete_modal.html  # Reusable delete confirmation modal
└── includes/
    ├── sidebar.html
    ├── topbar.html
    ├── search_bar.html    # Reusable HTMX search bar
    └── stat_modal.html    # Stat card drilldown modal
```

## Buttons

| Class | Use For | Look |
|-------|---------|------|
| `.btn-primary` | Primary actions: Create, Save, + Add | Solid primary color background |
| `.btn-secondary` | Navigation links: Public Status, SLA, Docs | Light primary-tinted background |
| `.btn-outline` | Low-emphasis: View All, Export | Transparent with border |
| `.btn-danger` | Destructive: Delete, Remove | Red background |
| `.btn-sm` | Size modifier (combine with above) | Smaller padding and font |
| `.btn-save` | Form submit inside `.crud-form` | Primary color, wider padding |
| `.btn-cancel` | Form cancel inside `.crud-form` | Muted text link style |

```html
<a href="{% url 'app:create' %}" class="btn-primary">+ Add Item</a>
<a href="{% url 'app:status' %}" class="btn-secondary">Status</a>
<a href="{% url 'app:list' %}" class="btn-outline btn-sm">View All</a>
<button type="button" class="btn-danger" onclick="crudDeleteModal(this, '{{ obj }}')">Delete</button>
```

## Cards

```html
<div class="card">
    <div class="card-header">
        <h2>Title</h2>
    </div>
    <div class="card-body">Content</div>
</div>
```

Card with header actions (flex layout on card-header is acceptable):

```html
<div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
    <h2>Items</h2>
    <a href="..." class="btn-primary">+ Add</a>
</div>
```

## Tables

```html
<table class="crud-table">
    <thead><tr><th>Name</th><th>Status</th></tr></thead>
    <tbody><tr><td>Widget A</td><td><span class="badge badge-success">Active</span></td></tr></tbody>
</table>
```

For lighter dashboard tables, use `class="table-plain"`.

### django-tables2

```python
class WidgetTable(tables.Table):
    name = DetailLinkColumn(url_base="manage/widgets", link_view="update")
    is_active = BooleanColumn(verbose_name="Active")
    actions = ActionsColumn(url_base="manage/widgets")

    class Meta:
        model = Widget
        fields = ("name", "is_active", "created_at")
        attrs = {"class": "crud-table"}
```

## Stat Cards

```html
<div class="stat-cards">
    <div class="stat-card">
        <div class="stat-card-value">{{ count }}</div>
        <div class="stat-card-label">Label</div>
    </div>
</div>
```

Clickable with modal drilldown:

```html
<div class="stat-card stat-card-clickable"
     hx-get="{% url 'stat-detail' 'total' %}"
     hx-target="#stat-modal-body"
     onclick="openStatModal('All Items')">
    <div class="stat-card-value">{{ count }}</div>
    <div class="stat-card-label">Label</div>
</div>
{% include "smallstack/includes/stat_modal.html" %}
```

## Action Cards

Icon + label cards for dashboard headers (like Backups: Scheduled, Backup Now, Download):

```html
<div class="action-cards">
    <div class="action-card action-card-success action-card-static">
        <div class="action-card-body">
            <svg class="action-card-icon" viewBox="0 0 24 24"><path d="..."/></svg>
            <div>
                <div class="action-card-title">Scheduled</div>
                <div class="action-card-subtitle">Cron enabled</div>
            </div>
        </div>
    </div>
    <div class="action-card" onclick="doAction()">
        <div class="action-card-body">
            <svg class="action-card-icon" viewBox="0 0 24 24"><path d="..."/></svg>
            <div>
                <div class="action-card-title">Run Now</div>
                <div class="action-card-subtitle">Execute action</div>
            </div>
        </div>
    </div>
</div>
```

Variants: `.action-card-success` (green), `.action-card-danger` (red), `.action-card-static` (non-clickable).

## Badges

```html
<span class="badge badge-success">Active</span>
<span class="badge badge-warning">Pending</span>
<span class="badge badge-error">Failed</span>
<span class="badge badge-info">Draft</span>
```

## Tabs

Full-width section switching:

```html
<div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab(event, 'overview')">
        Overview <span class="tab-count">3</span>
    </button>
    <button class="tab-btn" onclick="switchTab(event, 'config')">Config</button>
</div>
<div id="tab-overview" class="tab-panel active">...</div>
<div id="tab-config" class="tab-panel">...</div>
```

## Filter Toggles

Small inline pill buttons for data filtering in card headers:

```html
<div class="filter-toggles">
    <button class="filter-toggle active" data-tab="all">All</button>
    <button class="filter-toggle" data-tab="errors">Errors</button>
</div>
```

## Page Header

```html
{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
    <div class="page-header-content">
        <h1>Page Title</h1>
        <p class="page-subtitle">Description</p>
    </div>
    <div class="page-header-actions">
        <a href="..." class="btn-primary">+ Add</a>
        <a href="..." class="btn-secondary">Docs</a>
    </div>
</div>
{% endblock %}
```

## Forms

```html
<form method="POST" class="crud-form">
    {% csrf_token %}
    {% for field in form %}
    <div class="crud-field{% if field.errors %} has-error{% endif %}">
        <label class="crud-label">{{ field.label }}</label>
        {{ field }}
        {% if field.help_text %}<div class="crud-help">{{ field.help_text }}</div>{% endif %}
        {% if field.errors %}<div class="crud-error">{{ field.errors.0 }}</div>{% endif %}
    </div>
    {% endfor %}
    <div class="crud-actions">
        <button type="submit" class="btn-save">Save</button>
        <a href="{{ cancel_url }}" class="btn-cancel">Cancel</a>
    </div>
</form>
```

## Search Bar

```html
<input class="search-input" type="search" placeholder="Search..."
       hx-get="..." hx-target="#results" hx-trigger="input delay:500ms">
```

## Messages

```python
from django.contrib import messages
messages.success(request, "Widget created successfully.")
messages.error(request, "Something went wrong.")
```

Available levels: `success`, `info`, `warning`, `error`.

## Delete Modal

Include once on any page with delete buttons:

```html
{% include "smallstack/crud/includes/delete_modal.html" %}
```

Trigger from a button:

```html
<button type="button" class="btn-danger"
    data-delete-url="{% url 'app:delete' pk=obj.pk %}"
    onclick="crudDeleteModal(this, '{{ obj }}')">Delete</button>
```

## Best Practices

1. **Use CSS classes from components.css** — never inline styles for standard elements
2. **Use CSS variables** — `var(--primary)`, not hardcoded colors
3. **Use `color-mix()`** for tints — `color-mix(in srgb, var(--primary) 15%, var(--body-bg))`
4. **Use `.crud-table`** for all tables
5. **Use `.crud-form`** for all forms
6. **Copy `templates/smallstack/starter.html`** when creating new pages
7. **See [admin-page-styling.md](admin-page-styling.md)** for the full reference with anti-patterns
