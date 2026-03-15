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

Every SmallStack page starts from this skeleton:

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

## Pattern 1: Page Header with Tinted Background

The standard page header sits above the content and uses 15% primary tint:

```html
<div style="
    background: color-mix(in srgb, var(--primary) 15%, var(--body-bg));
    margin: -24px -24px 24px -24px;
    padding: 24px;
    border-radius: 8px 8px 0 0;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
">
    <div>
        <h1 style="font-size: 1.75rem; font-weight: 600; color: var(--body-fg); margin: 0;">
            Page Title
        </h1>
        <p style="color: var(--text-muted); margin-top: 4px; font-size: 1rem;">
            A brief description of this page.
        </p>
        <nav style="margin-top: 0.5rem; font-size: 0.8rem;">
            <a href="/" style="color: var(--body-quiet-color); text-decoration: none;">Home</a>
            <span style="color: var(--body-quiet-color); margin: 0 0.3rem;">/</span>
            <span style="color: var(--body-fg);">Page Title</span>
        </nav>
    </div>
    <div>
        <a href="#" class="btn" style="
            background: var(--primary);
            color: var(--button-fg);
            padding: 0.5rem 1rem;
            border: none;
            border-radius: var(--radius-sm, 4px);
            text-decoration: none;
            font-size: 0.9rem;
        ">+ Add Item</a>
    </div>
</div>
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

Dashboard-style clickable widgets use the 6%/12% tint pattern:

```html
<a href="/some-page/" style="
    display: block;
    text-decoration: none;
    color: var(--body-fg);
    background: color-mix(in srgb, var(--primary) 6%, var(--body-bg));
    border: 1px solid transparent;
    border-radius: var(--radius-md, 8px);
    padding: 20px;
    transition: border-color 0.15s, background 0.15s;
" onmouseover="this.style.borderColor='var(--primary)';this.style.background='color-mix(in srgb, var(--primary) 12%, var(--body-bg))'"
   onmouseout="this.style.borderColor='transparent';this.style.background='color-mix(in srgb, var(--primary) 6%, var(--body-bg))'">
    <div style="font-size: 0.8rem; text-transform: uppercase; color: var(--body-quiet-color); letter-spacing: 0.5px;">
        Metric Label
    </div>
    <div style="font-size: 2rem; font-weight: 700; color: var(--primary); margin: 4px 0;">
        42
    </div>
</a>
```

For cleaner code, use a `<style>` block with a class instead of inline hover handlers:

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
.widget-value {
    font-size: 2rem;
    font-weight: 700;
    color: var(--primary);
}
.widget-label {
    font-size: 0.8rem;
    text-transform: uppercase;
    color: var(--body-quiet-color);
    letter-spacing: 0.5px;
}
```

## Pattern 5: Status Badges

Badges use the status color variables with a 15% `color-mix` background:

```css
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
}
.badge-success {
    background: color-mix(in srgb, var(--success-fg) 15%, var(--card-bg));
    color: var(--success-fg);
}
.badge-error {
    background: color-mix(in srgb, var(--error-fg) 15%, var(--card-bg));
    color: var(--error-fg);
}
.badge-warning {
    background: color-mix(in srgb, var(--warning-fg) 15%, var(--card-bg));
    color: var(--warning-fg);
}
.badge-info {
    background: color-mix(in srgb, var(--info-fg) 15%, var(--card-bg));
    color: var(--info-fg);
}
.badge-muted {
    background: color-mix(in srgb, var(--body-quiet-color) 15%, var(--card-bg));
    color: var(--body-quiet-color);
}
```

For a primary-colored tag/label:

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

SmallStack buttons use the `btn` class. Primary actions use `var(--primary)`:

```html
<!-- Primary button -->
<a href="#" class="btn" style="
    background: var(--primary);
    color: var(--button-fg);
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--radius-sm, 4px);
    text-decoration: none;
    font-size: 0.9rem;
">Save</a>

<!-- Secondary / muted button -->
<a href="#" style="
    background: color-mix(in srgb, var(--primary) 20%, var(--body-bg));
    color: var(--primary);
    border: none;
    padding: 0.5rem 1rem;
    border-radius: var(--radius-sm, 4px);
    text-decoration: none;
    font-size: 0.9rem;
">Cancel</a>
```

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

{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}
<style>
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
    .widget-value { font-size: 2rem; font-weight: 700; color: var(--primary); }
    .widget-label { font-size: 0.8rem; text-transform: uppercase; color: var(--body-quiet-color); letter-spacing: 0.5px; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
    .badge-success { background: color-mix(in srgb, var(--success-fg) 15%, var(--card-bg)); color: var(--success-fg); }
    .badge-error { background: color-mix(in srgb, var(--error-fg) 15%, var(--card-bg)); color: var(--error-fg); }
</style>
{% endblock %}

{% block title %}Dashboard{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Dashboard" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<!-- Page header -->
<div style="
    background: color-mix(in srgb, var(--primary) 15%, var(--body-bg));
    margin: -24px -24px 24px -24px;
    padding: 24px;
    border-radius: 8px 8px 0 0;
">
    <h1 style="font-size: 1.75rem; font-weight: 600; color: var(--body-fg); margin: 0;">Dashboard</h1>
    <p style="color: var(--text-muted); margin-top: 4px;">System overview</p>
</div>

<!-- Stat widgets -->
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px;">
    <a href="#" class="widget-card">
        <div class="widget-label">Users</div>
        <div class="widget-value">{{ user_count }}</div>
    </a>
    <a href="#" class="widget-card">
        <div class="widget-label">Tasks</div>
        <div class="widget-value">{{ task_count }}</div>
    </a>
    <a href="#" class="widget-card">
        <div class="widget-label">Errors</div>
        <div class="widget-value">{{ error_count }}</div>
    </a>
</div>

<!-- Data table -->
<div class="card">
    <div class="card-header"><h2>Recent Activity</h2></div>
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
{% endblock %}
```

This page works in light mode, dark mode, and all five palettes with zero dark mode overrides.

## Related Skills

- [theming-system.md](theming-system.md) — Full variable reference, palette system, dark mode internals
- [templates.md](templates.md) — Template inheritance, blocks, includes
- [django-apps.md](django-apps.md) — Creating apps, CRUDView, django-tables2
- [adding-your-own-theme.md](adding-your-own-theme.md) — Using a different CSS framework (not SmallStack's theme)
