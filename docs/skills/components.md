# Skill: UI Components

Quick reference for SmallStack's themed UI components. All components work in both light and dark modes with zero overrides when using CSS variables.

## Overview

SmallStack provides styled components that use CSS variables from the theming system. Components use `var(--primary)`, `var(--card-bg)`, `var(--body-quiet-color)`, etc. — they adapt automatically to all theme/palette combinations.

## File Locations

```
static/smallstack/css/
├── theme.css              # Component styles, CSS variables
└── help/css/help.css      # Help-specific styles

templates/smallstack/
├── base.html              # Base template with all blocks
├── crud/                  # CRUD generic templates
└── includes/
    ├── sidebar.html
    ├── topbar.html
    ├── search_bar.html    # Reusable HTMX search bar
    ├── stat_modal.html    # Stat card drilldown modal
    └── _table_styles.html # Table CSS include

apps/smallstack/docs/      # Detailed component docs (in-app)
├── buttons.md
├── cards.md
├── forms.md
├── tables.md
├── grid-layout.md
├── messages.md
├── quick-links.md
├── navigation.md
└── theme-bars.md
```

## Cards

```html
<div class="card">
    <div class="card-header">Title</div>
    <div class="card-body">Content</div>
</div>
```

Multi-column layout:

```html
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem;">
    <div class="card">...</div>
    <div class="card">...</div>
</div>
```

## Buttons

| Class | Usage |
|-------|-------|
| `.button` | Base button style |
| `.button-primary` | Primary color background |
| `.button-prominent` | Slightly larger, bolder |
| `.button-secondary` | Outlined/subdued style |
| `.button-small` | Compact size |

```html
<button class="button button-primary">Save</button>
<a href="/docs/" class="button button-secondary">View Docs</a>
<button class="button button-primary button-prominent">Create New</button>
```

Links can use button classes for consistent styling.

## Forms

### Text Input

```html
<input type="text" class="vTextField" name="name" placeholder="Enter name">
```

### Two-Column Layout

```html
<div class="form-row-2col">
    <div>
        <label>First Name</label>
        <input type="text" class="vTextField" name="first_name">
    </div>
    <div>
        <label>Last Name</label>
        <input type="text" class="vTextField" name="last_name">
    </div>
</div>
```

### Form Buttons

```html
<div style="display: flex; gap: 0.5rem; margin-top: 1rem;">
    <button type="submit" class="button button-primary">Save</button>
    <a href="{% url 'list' %}" class="button button-secondary">Cancel</a>
</div>
```

## Tables

### Quick Start

```html
{% include "smallstack/crud/_table_styles.html" %}
<table class="crud-table">
    <thead><tr><th>Name</th><th>Status</th></tr></thead>
    <tbody><tr><td>Widget A</td><td>Active</td></tr></tbody>
</table>
```

### django-tables2

```python
class WidgetTable(tables.Table):
    name = DetailLinkColumn(url_base="manage/widgets", link_view="update")
    is_active = BooleanColumn(verbose_name="Active")
    actions = ActionsColumn(url_base="manage/widgets")

    class Meta:
        model = Widget
        fields = ("name", "is_active", "created_at")
        attrs = {"class": "crud-table"}   # Required
```

Column types from `apps.smallstack.tables`:
- `DetailLinkColumn` — clickable cell value
- `BooleanColumn` — checkmark / dash
- `ActionsColumn` — edit + delete icon buttons

### CSS Variables for Tables

- `--primary` — header accents, hover highlights
- `--body-bg` — table background
- `--body-quiet-color` — muted text
- `--delete-button-bg` — delete button color
- `color-mix()` for adaptive light/dark colors

## Messages

Django messages with SmallStack styling:

```python
from django.contrib import messages
messages.success(request, "Widget created successfully.")
messages.error(request, "Something went wrong.")
```

Available levels: `success`, `info`, `warning`, `error`.

## Stat Cards

### Plain (Display Only)

```html
<div class="card">
    <div class="card-body" style="text-align: center; padding: 14px 8px;">
        <div style="font-size: 1.75rem; font-weight: 700; color: var(--primary);">{{ count }}</div>
        <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Label</div>
    </div>
</div>
```

### Clickable (With Modal Drilldown)

```html
<div class="card stat-card-clickable"
     hx-get="{% url 'stat-detail' 'total' %}"
     hx-target="#stat-modal-body"
     onclick="openStatModal('All Items')">
    ...
</div>

{# Include at bottom of content block: #}
{% include "smallstack/includes/stat_modal.html" %}
```

### Title Bar Number Cards

```html
<div style="text-align: center; padding: 8px 16px;
     background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
     border-radius: var(--radius-sm, 6px);">
    <div style="font-size: 1.5rem; font-weight: 700; color: var(--primary);">{{ value }}</div>
    <div style="font-size: 0.7rem; color: var(--body-quiet-color);
         text-transform: uppercase;">Label</div>
</div>
```

## Title Bar Pattern

Used on management pages:

```html
<div style="background: color-mix(in srgb, var(--primary) 15%, var(--body-bg));
            margin: -24px -24px 24px -24px; padding: 24px;
            border-radius: 8px 8px 0 0;
            display: flex; align-items: center; justify-content: space-between;">
    <div>
        <h1>Page Title</h1>
        <nav style="margin-top: 0.5rem; font-size: 0.8rem;">
            <a href="{% url 'website:home' %}" style="color: var(--body-quiet-color);">Home</a>
            <span style="color: var(--body-quiet-color); margin: 0 0.3rem;">/</span>
            <span style="color: var(--body-fg);">Current Page</span>
        </nav>
    </div>
    <div style="display: flex; gap: 0.5rem;">
        <a href="{{ create_view_url }}" class="btn"
           style="background: var(--primary); color: var(--button-fg);
                  padding: 0.5rem 1rem; border: none; border-radius: var(--radius-sm, 4px);">
            + Add Item
        </a>
    </div>
</div>
```

## Search Bar

Reusable HTMX search bar include:

```html
{% include "smallstack/includes/search_bar.html" with placeholder="Search..." target="#search-results" %}

<div id="search-results">
    {% include "myfeature/_table.html" %}
</div>
```

## Grid Layout

```html
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem;">
    <div class="card">...</div>
    <div class="card">...</div>
    <div class="card">...</div>
</div>
```

## Quick Links

Icon-based navigation grid:

```html
<div class="quick-links">
    <a href="..." class="quick-link">
        <svg>...</svg>
        <span>Label</span>
    </a>
</div>
```

## Best Practices

1. **Always use CSS variables** — `var(--primary)`, not hardcoded colors
2. **Use `color-mix()`** for tints — `color-mix(in srgb, var(--primary) 15%, var(--body-bg))`
3. **Include `_table_styles.html`** before any `crud-table`
4. **Use `vTextField`** class on all text inputs for consistent styling
5. **Use `attrs = {"class": "crud-table"}`** on django-tables2 Meta
6. **See `building-themed-pages` skill** for the full color-mix scale and dark mode patterns
