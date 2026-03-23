# Skill: Building Pages That Fit the SmallStack Theme

This skill teaches how to build new pages that look correct in light mode, dark mode, and all five color palettes — without writing any dark mode overrides. It applies only to pages that extend `smallstack/base.html` (not third-party themes).

## The Core Idea

SmallStack uses `color-mix()` to derive every background, tint, and hover state from two CSS variables: `--primary` and `--body-bg`. When the user switches themes or palettes, those variables change, and every derived color changes with them.

**If you follow the patterns below, your page will look right in all 10 combinations (5 palettes x 2 modes) without a single `[data-theme="dark"]` override.**

## Quick Reference: The color-mix Scale

These are the standard tint levels used across SmallStack. Memorize these — they're the entire system:

```
 4%  — Subtle background (table odd rows, zebra stripe light)
 6%  — Widget/card surface
 8%  — Icon containers, tab active states
10%  — Hover tints, tag backgrounds
12%  — Table even rows, slightly more visible
15%  — Page headers, table headers, modal headers
20%  — Strong hover, button backgrounds, input focus rings
30%  — Emphasis hover (preview badges)
```

The formula is always the same:

```css
color-mix(in srgb, var(--primary) NN%, var(--body-bg))
```

Where `NN` is the percentage from the scale above. Never use `var(--card-bg)` or `var(--card-header-bg)` as the mix base for tables or page sections — those are for cards specifically. Use `var(--body-bg)`.

## Template Skeleton

Every SmallStack page starts from this skeleton. For a full copy-paste starter with all sections, use `templates/smallstack/starter.html`.

```html
{% extends "smallstack/base.html" %}
{% load static theme_tags %}

{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}  {# only if you have tables #}
<style>
    /* Page-specific styles go here */
</style>
{% endblock %}

{% block title %}Page Title{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Page Title" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<!-- Page content -->
{% endblock %}
```

## Pattern 1: Page Header

The standard page header is a full-bleed colored bar. **Use the CSS classes** — never inline the background/padding. The `.page-header-bleed` class handles the 15% primary tint. See [admin-page-styling.md](admin-page-styling.md#page-header) for all header variants.

```html
{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
    <div class="page-header-content">
        <h1>Page Title</h1>
        <p class="page-subtitle">A brief description of this page.</p>
    </div>
    <div class="page-header-actions">
        <a href="#" class="btn-primary">+ Add Item</a>
        <a href="#" class="btn-secondary">Docs</a>
    </div>
</div>
{% endblock %}
```

## Pattern 2: Tables

**Always use `crud-table`.** Do not write custom table CSS.

```html
{% include "smallstack/crud/_table_styles.html" %}

<div class="table-container">
    <table class="crud-table">
        <thead>
            <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Count</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td><a href="{{ item.url }}">{{ item.name }}</a></td>
                <td>{{ item.status }}</td>
                <td>{{ item.count }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
```

What `crud-table` does for you:

| Element | Tint | Result |
|---------|------|--------|
| Header row | 15% | Distinct tinted background |
| Odd rows | 4% | Nearly transparent, subtle stripe |
| Even rows | 12% | Visible alternation |
| Hover | 20% | Clear highlight |
| Text | `--body-quiet-color` | Uppercase, small, muted headers |
| Links | `--primary` | Themed link color |
| Borders | None | Clean, borderless look |

**If you need a table inside a modal or a denser layout**, don't invent new CSS. Copy the exact `color-mix` percentages from the scale:

```css
.my-modal-table thead tr { background-color: color-mix(in srgb, var(--primary) 15%, var(--body-bg)) !important; }
.my-modal-table tbody tr:nth-child(odd) { background-color: color-mix(in srgb, var(--primary) 4%, var(--body-bg)) !important; }
.my-modal-table tbody tr:nth-child(even) { background-color: color-mix(in srgb, var(--primary) 12%, var(--body-bg)) !important; }
.my-modal-table tbody tr:hover { background-color: color-mix(in srgb, var(--primary) 20%, var(--body-bg)) !important; }
```

## Pattern 3: Cards

Use the built-in `card`, `card-header`, `card-body` classes. Don't add inline background colors.

```html
<div class="card">
    <div class="card-header"><h2>Section Title</h2></div>
    <div class="card-body">
        <p>Content goes here.</p>
    </div>
</div>
```

Cards use `var(--card-bg)`, `var(--card-border)`, and `var(--card-header-bg)` which are purpose-built for card surfaces. These are different from the `color-mix` tints — cards have solid backgrounds, not tinted ones.

**Cards in a grid:**

```html
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px;">
    <div class="card">
        <div class="card-header"><h3>Card 1</h3></div>
        <div class="card-body">Content</div>
    </div>
    <div class="card">
        <div class="card-header"><h3>Card 2</h3></div>
        <div class="card-body">Content</div>
    </div>
</div>
```

## Pattern 4: Stat / Widget Cards

**Use the built-in `.stat-card` classes** from `components.css`. For clickable stat cards that open a modal, add `.stat-card-clickable`:

```html
<div class="stat-cards">
    <div class="stat-card">
        <div class="stat-card-value">42</div>
        <div class="stat-card-label">Metric Label</div>
    </div>
    <div class="stat-card stat-card-clickable"
         hx-get="{% url 'app:stat_detail' 'metric' %}"
         hx-target="#stat-modal-body"
         onclick="openStatModal('Metric Details')">
        <div class="stat-card-value">{{ count }}</div>
        <div class="stat-card-label">Clickable Metric</div>
    </div>
</div>
{% include "smallstack/includes/stat_modal.html" %}
```

For **action cards** with icons (like Backups: Backup Now, Download), use `.action-card`:

```html
<div class="action-cards">
    <div class="action-card" onclick="doAction()">
        <div class="action-card-body">
            <svg class="action-card-icon" viewBox="0 0 24 24"><path d="..."/></svg>
            <div>
                <div class="action-card-title">Run Action</div>
                <div class="action-card-subtitle">Description</div>
            </div>
        </div>
    </div>
</div>
```

See [admin-page-styling.md](admin-page-styling.md#stat-cards) for all stat card and action card variants.

If you need a custom widget card that doesn't fit these classes, use the `color-mix` tint pattern:

```css
.widget-card {
    display: block;
    text-decoration: none;
    color: var(--body-fg);
    background: color-mix(in srgb, var(--primary) 6%, var(--body-bg));
    border: 1px solid transparent;
    border-radius: var(--radius-md, 8px);
    padding: 20px;
    transition: border-color 0.15s, background 0.15s;
}
.widget-card:hover {
    border-color: var(--primary);
    background: color-mix(in srgb, var(--primary) 12%, var(--body-bg));
}
```

## Pattern 5: Status Badges

**Use the built-in badge classes** from `components.css`:

```html
<span class="badge badge-success">Active</span>
<span class="badge badge-warning">Pending</span>
<span class="badge badge-error">Failed</span>
<span class="badge badge-info">Draft</span>
```

These use 15% `color-mix` tinting with status color variables — they adapt to all themes automatically. Don't redefine badge CSS.

For a primary-colored tag/label (not a status badge), use the same tint pattern:

```css
.tag {
    font-size: 0.7rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    padding: 2px 8px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
    color: var(--primary);
}
```

## Pattern 6: Detail / Key-Value Tables

For showing object details (label → value pairs), use the same tint pattern as data tables:

```css
.detail-table {
    width: 100%;
    border-collapse: collapse;
}
.detail-table td {
    padding: 10px 16px;
    border: none;
    font-size: 0.85rem;
}
.detail-table tr:nth-child(odd) {
    background-color: color-mix(in srgb, var(--primary) 4%, var(--body-bg));
}
.detail-table tr:nth-child(even) {
    background-color: color-mix(in srgb, var(--primary) 12%, var(--body-bg));
}
.detail-table .label-cell {
    font-weight: 600;
    color: var(--body-quiet-color);
    width: 140px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
```

```html
<table class="detail-table">
    <tr>
        <td class="label-cell">Name</td>
        <td>{{ object.name }}</td>
    </tr>
    <tr>
        <td class="label-cell">Status</td>
        <td><span class="badge badge-success">Active</span></td>
    </tr>
    <tr>
        <td class="label-cell">Created</td>
        <td>{% localtime_tooltip object.created_at %}</td>
    </tr>
</table>
```

## Pattern 7: Buttons and Actions

**Use the button classes** from `components.css`. Never inline button styles.

```html
<!-- Primary action -->
<a href="#" class="btn-primary">+ Add Item</a>

<!-- Secondary / navigation link -->
<a href="#" class="btn-secondary">Public Status</a>

<!-- Low-emphasis -->
<a href="#" class="btn-outline">View All</a>

<!-- Danger / delete -->
<button type="button" class="btn-danger" onclick="crudDeleteModal(this, '{{ obj }}')">Delete</button>

<!-- Small variant -->
<a href="#" class="btn-primary btn-sm">Edit</a>

<!-- Form submit / cancel -->
<div class="crud-actions">
    <button type="submit" class="btn-save">Save</button>
    <a href="..." class="btn-cancel">Cancel</a>
</div>
```

See [admin-page-styling.md](admin-page-styling.md#buttons) for the complete button reference including filter toggles and tab buttons.

## Pattern 8: Messages / Alerts

Use the built-in message classes:

```html
{% include "smallstack/includes/messages.html" %}
```

For manual alerts:

```html
<div class="message success">Operation completed successfully.</div>
<div class="message error">Something went wrong.</div>
<div class="message warning">Check your configuration.</div>
<div class="message info">Tip: you can customize this.</div>
```

Messages use `color-mix(in srgb, var(--success-fg) 10%, var(--card-bg))` etc. — automatically themed.

## Pattern 9: Icon Containers

Icons inside tinted circles (used in dashboards, nav grids):

```css
.icon-box {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 38px;
    border-radius: var(--radius-sm);
    background-color: color-mix(in srgb, var(--primary) 8%, var(--card-bg));
    border: 1px solid color-mix(in srgb, var(--primary) 14%, var(--card-bg));
    color: var(--primary);
}
```

## Pattern 10: Modals / Panels

For overlay modals, follow the field-preview pattern:

```css
.modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 1000;
    align-items: center;
    justify-content: center;
}
.modal-overlay.open {
    display: flex;
}
.modal-panel {
    width: min(680px, 90vw);
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--radius-md, 8px);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    overflow: hidden;
}
.modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    border-bottom: 1px solid color-mix(in srgb, var(--body-fg) 10%, var(--body-bg));
    background: color-mix(in srgb, var(--primary) 8%, var(--body-bg));
}
.modal-body {
    padding: 16px 20px;
    overflow-y: auto;
    flex: 1;
    min-height: 0;
}
```

## Pattern 11: Empty States

When a table or list has no data:

```html
<div style="
    text-align: center;
    padding: 3rem 1rem;
    color: var(--body-quiet-color);
">
    <p style="font-size: 1.1rem; margin-bottom: 0.5rem;">No items yet.</p>
    <a href="#" style="color: var(--primary); text-decoration: none;">Create your first item</a>
</div>
```

## The Variable Cheat Sheet

Use these variables and nothing else. Never hardcode hex colors.

**Backgrounds:**

| Variable | Use for |
|----------|---------|
| `var(--body-bg)` | Page background, color-mix base |
| `var(--card-bg)` | Card surfaces, modal panels, dropdown menus |
| `var(--card-header-bg)` | Card headers only |
| `var(--content-bg)` | Main content area |

**Text:**

| Variable | Use for |
|----------|---------|
| `var(--body-fg)` | Primary text |
| `var(--body-quiet-color)` | Secondary text, labels, captions |
| `var(--text-muted)` | Even quieter text |
| `var(--primary)` | Branded text, metric values, active states |

**Borders:**

| Variable | Use for |
|----------|---------|
| `var(--card-border)` | Card borders, dividers |
| `var(--hairline-color)` | Very subtle separators |

**Interactive:**

| Variable | Use for |
|----------|---------|
| `var(--primary)` | Button backgrounds, link text, active borders |
| `var(--primary-hover)` | Hover state for primary elements |
| `var(--button-fg)` | Text on primary-colored buttons |
| `var(--link-color)` | Standalone links |

**Status:**

| Variable | Use for |
|----------|---------|
| `var(--success-fg)` | Success text and badge text |
| `var(--error-fg)` | Error text and badge text |
| `var(--warning-fg)` | Warning text and badge text |
| `var(--info-fg)` | Info text and badge text |

**Layout:**

| Variable | Use for |
|----------|---------|
| `var(--radius-sm)` | Buttons, badges, inputs (4px) |
| `var(--radius-md)` | Cards, modals (8px) |
| `var(--radius-lg)` | Hero sections (12px) |
| `var(--shadow-sm)` | Cards |
| `var(--shadow-md)` | Elevated elements |
| `var(--transition-fast)` | Hover/active transitions (0.15s) |

## Rules

1. **Never hardcode colors.** Not even `#333` or `rgba(0,0,0,0.1)`. Use variables.
2. **Never write `[data-theme="dark"]` overrides.** If you need them, you picked the wrong variable. The `color-mix()` pattern and CSS variables handle dark mode automatically.
3. **Never use `var(--card-header-bg)` for table headers.** Use `color-mix(in srgb, var(--primary) 15%, var(--body-bg))`.
4. **Always include `_table_styles.html` if your page has a table.** Use the `crud-table` class.
5. **Use `{% localtime_tooltip %}` for datetimes.** It inherits theme variables and shows timezone tooltips automatically.
6. **Put styles in `{% block extra_css %}`.** Don't create new CSS files for one-off page styles.
7. **Stick to the scale.** 4%, 6%, 8%, 10%, 12%, 15%, 20%, 30%. Don't invent new percentages — consistency is the point.
8. **Test by switching palettes.** Open Profile, pick "purple", then "orange". If something looks wrong, you hardcoded a color.

## Complete Example: A Dashboard Page

```html
{% extends "smallstack/base.html" %}
{% load static theme_tags %}

{% block title %}Dashboard{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Dashboard" %}
{% render_breadcrumbs %}
{% endblock %}

{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
    <div class="page-header-content">
        <h1>Dashboard</h1>
        <p class="page-subtitle">System overview</p>
    </div>
    <div class="page-header-actions">
        <a href="#" class="btn-secondary">Settings</a>
    </div>
</div>
{% endblock %}

{% block content %}
<!-- Stat cards -->
<div class="stat-cards">
    <div class="stat-card stat-card-clickable"
         hx-get="{% url 'app:stat_detail' 'users' %}"
         hx-target="#stat-modal-body"
         onclick="openStatModal('Users')">
        <div class="stat-card-value">{{ user_count }}</div>
        <div class="stat-card-label">Users</div>
    </div>
    <div class="stat-card">
        <div class="stat-card-value">{{ task_count }}</div>
        <div class="stat-card-label">Tasks</div>
    </div>
    <div class="stat-card">
        <div class="stat-card-value">{{ error_count }}</div>
        <div class="stat-card-label">Errors</div>
    </div>
</div>

<!-- Data table with filter toggles -->
<div class="card">
    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; align-items: center; gap: 16px;">
            <h2>Recent Activity</h2>
            <div class="filter-toggles">
                <button class="filter-toggle active" data-tab="all" onclick="showFilterTab('all')">All</button>
                <button class="filter-toggle" data-tab="errors" onclick="showFilterTab('errors')">Errors</button>
            </div>
        </div>
        <a href="{% url 'app:list' %}" class="btn-outline btn-sm">View All</a>
    </div>
    <div class="card-body" style="padding: 0;">
        <table class="crud-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>User</th>
                    <th>Action</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for event in events %}
                <tr>
                    <td>{% localtime_tooltip event.timestamp %}</td>
                    <td>{{ event.user }}</td>
                    <td>{{ event.action }}</td>
                    <td>
                        {% if event.success %}
                            <span class="badge badge-success">OK</span>
                        {% else %}
                            <span class="badge badge-error">Failed</span>
                        {% endif %}
                    </td>
                </tr>
                {% empty %}
                <tr>
                    <td colspan="4" style="text-align: center; padding: 2rem; color: var(--body-quiet-color);">
                        No activity yet.
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

{% include "smallstack/includes/stat_modal.html" %}
{% endblock %}
```

This page works in light mode, dark mode, and all five palettes with zero dark mode overrides. Every element uses CSS classes from `components.css` — no inline button styles, stat card styles, or page header styles.

## Related Skills

- [admin-page-styling.md](admin-page-styling.md) — **Definitive UI reference**: all CSS classes, button types, card patterns, starter template
- [theming-system.md](theming-system.md) — Full variable reference, palette system, dark mode internals
- [templates.md](templates.md) — Template inheritance, blocks, includes
- [django-apps.md](django-apps.md) — Creating apps, CRUDView, django-tables2
- [adding-your-own-theme.md](adding-your-own-theme.md) — Using a different CSS framework (not SmallStack's theme)
