# Admin Page Styling Reference

This is the definitive reference for building admin pages in SmallStack. Every admin page **must** use the CSS classes defined in `components.css` — never inline styles for standard elements.

## Quick Start

Copy the starter template from `templates/smallstack/starter.html` and modify it for your page. It includes the correct layout structure, CSS classes, and block usage.

## Template Structure

Every admin page extends `smallstack/base.html` and uses these blocks:

```django
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Page Title{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Section" "app:list" %}
{% breadcrumb "Current Page" %}
{% render_breadcrumbs %}
{% endblock %}

{% block page_header %}
<!-- Full-bleed colored header — outside .content-wrapper -->
{% endblock %}

{% block content %}
<!-- Main content — inside .content-wrapper (max-width constrained) -->
{% endblock %}

{% block extra_css %}{% endblock %}
{% block extra_js %}{% endblock %}
```

**Rules:**
- `{% block page_header %}` is for the full-width colored header bar. It sits outside `.content-wrapper` so the background extends edge to edge.
- `{% block content %}` is for the main page body inside `.content-wrapper`.
- Never put page headers inside `{% block content %}`.

## Page Header

The page header is a full-bleed colored bar with title, subtitle, breadcrumb trail, and optional action buttons or action cards.

### Header with Buttons

```django
{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
    <div class="page-header-content">
        <h1>Page Title</h1>
        <p class="page-subtitle">Brief description</p>
    </div>
    <div class="page-header-actions">
        <a href="{% url 'app:create' %}" class="btn-primary">+ Add Item</a>
        <a href="{% url 'help:section_index' 'myapp' %}" class="btn-secondary">Docs</a>
    </div>
</div>
{% endblock %}
```

### Header with Action Cards

For dashboard-style pages where the header contains icon+label action cards (like Backups: Scheduled, Backup Now, Download):

```django
{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
    <div class="page-header-content">
        <h1>Dashboard</h1>
        <p class="page-subtitle">System overview</p>
    </div>
    <div class="action-cards">
        <!-- Status indicator (non-clickable) -->
        <div class="action-card action-card-success action-card-static">
            <div class="action-card-body">
                <svg class="action-card-icon" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                </svg>
                <div>
                    <div class="action-card-title">Scheduled</div>
                    <div class="action-card-subtitle">Cron enabled</div>
                </div>
            </div>
        </div>

        <!-- Clickable action -->
        <div class="action-card" onclick="doAction()">
            <div class="action-card-body">
                <svg class="action-card-icon" viewBox="0 0 24 24">
                    <path d="M5 4v2h14V4H5zm0 10h4v6h6v-6h4l-7-7-7 7z"/>
                </svg>
                <div>
                    <div class="action-card-title">Backup Now</div>
                    <div class="action-card-subtitle">Save to storage</div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

| Class | Purpose |
|-------|---------|
| `.action-cards` | Flex container for action card row |
| `.action-card` | Clickable card with primary-colored border, hover effect |
| `.action-card-success` | Green border/text variant |
| `.action-card-danger` | Red border/text variant |
| `.action-card-static` | Non-clickable (removes pointer cursor) |
| `.action-card-body` | Inner flex layout (icon + text) |
| `.action-card-icon` | SVG icon sizing (28x28, colored by variant) |
| `.action-card-title` | Bold label (0.95rem, colored by variant) |
| `.action-card-subtitle` | Muted description (0.75rem) |

**CSS classes for page header:**
| Class | Purpose |
|-------|---------|
| `.page-header-bleed` | Full-width background color (defined in theme.css) |
| `.page-header-with-actions` | Flex layout: content left, actions right |
| `.page-header-content` | Left side: title + subtitle |
| `.page-subtitle` | Muted description text below h1 |
| `.page-header-actions` | Right side: flex row of buttons |

**Do not** add inline styles to the page header div. The classes handle background, padding, and layout.

## Buttons

### Standard Buttons

Five button classes are defined in `components.css`. Use them on `<a>`, `<button>`, or `<input>` elements.

| Class | Use For | Look |
|-------|---------|------|
| `.btn-primary` | Primary actions: Create, Save, Submit, + Add | Solid primary color background |
| `.btn-secondary` | Navigation links: Public Status, SLA, Docs | Light primary-tinted background |
| `.btn-outline` | Low-emphasis actions: Export, Filter | Transparent with border |
| `.btn-danger` | Destructive actions: Delete, Remove | Red background |
| `.btn-sm` | Size modifier — combine with any button class | Smaller padding and font |

```django
<!-- Page header primary action -->
<a href="{% url 'app:create' %}" class="btn-primary">+ Add Item</a>

<!-- Page header secondary links -->
<a href="{% url 'app:status' %}" class="btn-secondary">Public Status</a>
<a href="{% url 'app:sla' %}" class="btn-secondary">SLA</a>

<!-- Low-emphasis action -->
<a href="{% url 'help:index' %}" class="btn-outline">Documentation</a>

<!-- Delete trigger (opens modal) -->
<button type="button" class="btn-danger"
    data-delete-url="{% url 'app:delete' pk=obj.pk %}"
    onclick="crudDeleteModal(this, '{{ obj }}')">Delete</button>

<!-- Small button in a table cell -->
<a href="edit/" class="btn-primary btn-sm">Edit</a>
```

### Visited-Link Specificity Rule

Button classes are used on `<a>` elements throughout the framework (e.g. `<a href="..." class="btn-primary">`). The global `a:visited` rule in `theme.css` has specificity `(0,1,1)` and sets `color: var(--link-color)`. A plain class selector like `.btn-primary` is only `(0,1,0)` — so the visited-link color wins, making button text invisible when `--link-color` matches the button background (e.g. purple palette light mode).

**Rule:** Any button class that sets `color` must also include `a.<class>:link` and `a.<class>:visited` selectors:

```css
/* WRONG — text disappears on visited links */
.btn-primary {
    color: var(--button-fg);
}

/* RIGHT — always beats a:visited */
.btn-primary,
a.btn-primary:link,
a.btn-primary:visited {
    color: var(--button-fg);
}
```

This is already done for `.btn-primary`, `.btn-secondary`, `.btn-outline`, and `.btn-danger` in `components.css`, and for `.button-primary` and `.topbar .auth-link` in `theme.css`. Follow the same pattern when adding new button or link classes that set an explicit `color`.

### Form Buttons

Inside `.crud-form`, use these for submit/cancel:

| Class | Use For |
|-------|---------|
| `.btn-save` | Form submit (Save, Create, Update) |
| `.btn-cancel` | Cancel / go back link |

```django
<div class="crud-actions">
    <button type="submit" class="btn-save">Save</button>
    <a href="{{ cancel_url }}" class="btn-cancel">Cancel</a>
</div>
```

### Card Header Link Buttons

For "View All" style links in card headers, use `.btn-outline btn-sm`:

```django
<div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
    <h2>Recent Requests</h2>
    <a href="{% url 'app:list' %}" class="btn-outline btn-sm">View All</a>
</div>
```

### Filter Toggles

Small pill-style buttons for inline data filtering (like "All | Errors" in a card header):

```django
<div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
    <div style="display: flex; align-items: center; gap: 16px;">
        <h2>Latest Requests</h2>
        <div class="filter-toggles">
            <button type="button" class="filter-toggle active" data-tab="all"
                onclick="showTab('all')">All</button>
            <button type="button" class="filter-toggle" data-tab="errors"
                onclick="showTab('errors')">Errors</button>
        </div>
    </div>
    <a href="{% url 'app:list' %}" class="btn-outline btn-sm">View All</a>
</div>
```

| Class | Purpose |
|-------|---------|
| `.filter-toggles` | Flex container with 4px gap |
| `.filter-toggle` | Small pill button (0.75rem, bordered) |
| `.filter-toggle.active` | Primary-tinted background, colored text |

Toggle the `.active` class in JS:

```javascript
function showTab(tab) {
    document.querySelectorAll('.filter-toggle').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    // Show/hide content...
}
```

**Never use inline styles for buttons.** If you need a size variant, use `.btn-sm`. If you need a new variant, add it to `components.css`.

## Cards

Cards are the primary content container.

```django
<div class="card">
    <div class="card-header">
        <h2>Section Title</h2>
    </div>
    <div class="card-body">
        <!-- Content here -->
    </div>
</div>
```

**Card with header actions:**
```django
<div class="card">
    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
        <h2>Items</h2>
        <a href="{% url 'app:create' %}" class="btn-primary">+ Add</a>
    </div>
    <div class="card-body">
        <!-- table or content -->
    </div>
</div>
```

**Card with filter toggles + link button in header:**
```django
<div class="card">
    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; align-items: center; gap: 16px;">
            <h2>Latest Requests</h2>
            <div class="filter-toggles">
                <button type="button" class="filter-toggle active" data-tab="all">All</button>
                <button type="button" class="filter-toggle" data-tab="errors">Errors</button>
            </div>
        </div>
        <a href="{% url 'app:requests' %}" class="btn-outline btn-sm">View All</a>
    </div>
    <div class="card-body">
        <!-- table content -->
    </div>
</div>
```

Note: The flex layout on `.card-header` is the one place inline styles are acceptable — it's a layout concern specific to that header, not a styling concern.

## Tables

Use `class="crud-table"` on any `<table>`. The CSS handles:
- Header styling (uppercase, muted color, primary-tinted background)
- Alternating row backgrounds
- Hover highlighting
- Cell padding (10px 16px)
- Link coloring

```django
<table class="crud-table">
    <thead>
        <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Created</th>
        </tr>
    </thead>
    <tbody>
        {% for obj in object_list %}
        <tr>
            <td><a href="{{ obj.get_absolute_url }}">{{ obj.name }}</a></td>
            <td><span class="badge badge-success">Active</span></td>
            <td>{{ obj.created_at }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

For lighter tables inside dashboard cards (no alternating rows), use `class="table-plain"`.

**Do not add** inline padding, background colors, or text alignment to `<th>` or `<td>`. The table classes handle all of this. If you need right-aligned numbers:

```django
<td style="text-align: right;">{{ obj.amount }}</td>
```

## Stat Cards

### Simple Stat Row

For metric/KPI displays at the top of dashboard pages:

```django
<div class="stat-cards">
    <div class="stat-card">
        <div class="stat-card-value">{{ total_count }}</div>
        <div class="stat-card-label">Total Items</div>
    </div>
    <div class="stat-card">
        <div class="stat-card-value">{{ active_count }}</div>
        <div class="stat-card-label">Active</div>
    </div>
    <div class="stat-card">
        <div class="stat-card-value">{{ error_count }}</div>
        <div class="stat-card-label">Errors</div>
    </div>
</div>
```

| Class | Purpose |
|-------|---------|
| `.stat-cards` | Flex container with gap and wrapping |
| `.stat-card` | Individual card with border and background |
| `.stat-card-value` | Large number (1.5rem, bold, primary color) |
| `.stat-card-label` | Muted uppercase label below the number |

### Clickable Stat Cards with Modal

For stat cards that open a detail table on click (like Activity dashboard). Clicking a card fires an HTMX GET, loads a table into the modal, and opens it:

```django
<div class="stat-cards">
    <div class="stat-card stat-card-clickable"
         hx-get="{% url 'app:stat_detail' 'requests' %}"
         hx-target="#stat-modal-body"
         onclick="openStatModal('Recent Requests')">
        <div class="stat-card-value">{{ total_requests }}</div>
        <div class="stat-card-label">Requests</div>
    </div>
</div>

<!-- Include the stat modal once at page bottom -->
{% include "smallstack/includes/stat_modal.html" %}
```

| Class | Purpose |
|-------|---------|
| `.stat-card-clickable` | Adds hover effect and pointer cursor (defined in theme.css) |

**How it works:**

1. `hx-get` fetches an HTML fragment and injects it into `#stat-modal-body`
2. `onclick="openStatModal('Title')"` sets the modal title and adds the `.open` class
3. Escape key or clicking the backdrop closes the modal

**The HTMX endpoint should return a plain HTML table** — no `<html>`, no layout, just the table:

```python
# views.py
def stat_detail(request, stat_type):
    if stat_type == "requests":
        qs = RequestLog.objects.order_by("-timestamp")[:50]
    return render(request, "app/partials/stat_table.html", {"items": qs})
```

```django
{# partials/stat_table.html — just the table, no base template #}
<table>
    <thead><tr><th>Timestamp</th><th>Path</th><th>Status</th></tr></thead>
    <tbody>
    {% for item in items %}
    <tr><td>{{ item.timestamp }}</td><td>{{ item.path }}</td><td>{{ item.status_code }}</td></tr>
    {% endfor %}
    </tbody>
</table>
```

The modal panel automatically styles tables inside it — sticky header, alternating row colors, hover highlights — all derived from `--primary` via `color-mix()`. No extra classes needed on the `<table>`.

**Stat modal CSS classes** (in `theme.css`):

| Class | Purpose |
|-------|---------|
| `.stat-modal` | Fixed full-screen overlay backdrop (`display: none` by default) |
| `.stat-modal.open` | Shows the modal (`display: flex`) |
| `.stat-modal-panel` | The card container — sized `min(80%, 90vw)` x `min(520px, 80vh)` |
| `.stat-modal-panel table` | Full-width table with sticky header and themed row colors |

**JavaScript API:**

| Function | Description |
|----------|-------------|
| `openStatModal('Title')` | Sets the title and shows the modal |
| `closeStatModal()` | Hides the modal and clears state |

## Badges

For status indicators, tags, and labels:

```django
<span class="badge badge-success">Active</span>
<span class="badge badge-warning">Pending</span>
<span class="badge badge-error">Failed</span>
<span class="badge badge-info">Draft</span>
```

| Class | Color |
|-------|-------|
| `.badge-success` | Green |
| `.badge-warning` | Amber |
| `.badge-error` | Red |
| `.badge-info` | Primary/blue |

## Forms

All forms use the `.crud-form` class. This handles input styling, labels, error states, and layout.

```django
<form method="POST" class="crud-form">
    {% csrf_token %}
    {% for field in form %}
    <div class="crud-field{% if field.errors %} has-error{% endif %}">
        <label class="crud-label">
            {{ field.label }}
            {% if field.field.required %}<span class="required">*</span>{% endif %}
        </label>
        {% if field.field.widget.input_type == "checkbox" %}
        <div class="crud-checkbox">
            {{ field }}
            <label for="{{ field.id_for_label }}">{{ field.label }}</label>
        </div>
        {% else %}
        {{ field }}
        {% endif %}
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

**Side-by-side fields:**
```django
<div class="crud-row">
    <div class="crud-field">
        <label class="crud-label">First Name</label>
        {{ form.first_name }}
    </div>
    <div class="crud-field">
        <label class="crud-label">Last Name</label>
        {{ form.last_name }}
    </div>
</div>
```

### Control Sizing

All text inputs, selects, and search fields use `min-height: var(--control-height)` (default `36px`). This ensures dropdowns and inputs are tall enough to display text without clipping, and that adjacent controls (e.g. a search box next to filter dropdowns) align at the same height.

The `--control-height` variable is defined in `theme.css` and referenced in `components.css`. To make all controls taller or shorter across the app, override the single variable:

```css
:root {
    --control-height: 40px;  /* taller controls */
}
```

This applies to:
- `.content-wrapper` bare inputs and selects (admin-style pages)
- `.crud-form` inputs and selects (CRUD create/edit forms)
- `.form-group select` (profile and auth forms)
- Toolbar search and filter controls

### File Inputs

File inputs (`<input type="file">`) are styled automatically in both `.crud-form` and bare `.content-wrapper` contexts. They get a dashed border, themed background, and a styled "Choose File" button that uses the primary color.

No extra classes are needed — Django's `ClearableFileInput` widget renders a plain `<input type="file">` and the CSS handles it:

```django
{# Inside a crud-form — automatically styled #}
<div class="crud-field">
    <label class="crud-label">File *</label>
    {{ form.file }}
</div>
```

The `::file-selector-button` pseudo-element styles the browser's native button:
- Primary-colored background with white text
- Hover state uses `--primary-hover`
- Dashed border on the input area turns solid primary on hover

For forms with file uploads, remember to add `enctype="multipart/form-data"` to the `<form>` tag.

## Tabs

For pages with multiple content sections (full-width tab bar with underline indicator):

```django
<div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab(event, 'overview')">
        Overview <span class="tab-count">{{ overview_count }}</span>
    </button>
    <button class="tab-btn" onclick="switchTab(event, 'details')">
        Details <span class="tab-count">{{ detail_count }}</span>
    </button>
</div>

<div id="tab-overview" class="tab-panel active">
    <!-- Overview content -->
</div>
<div id="tab-details" class="tab-panel">
    <!-- Details content -->
</div>

{% block extra_js %}
<script>
function switchTab(e, tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    e.currentTarget.classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');
}
</script>
{% endblock %}
```

**Tabs vs Filter Toggles:** Use `.tab-bar` / `.tab-btn` for full-width section switching (like Backups: History | Config). Use `.filter-toggles` / `.filter-toggle` for small inline data filters within a card header (like "All | Errors").

| Class | Purpose |
|-------|---------|
| `.tab-bar` | Flex container with bottom border |
| `.tab-btn` | Individual tab with underline on active |
| `.tab-btn.active` | Primary color + bottom border |
| `.tab-count` | Pill-shaped count badge next to tab label |
| `.tab-panel` | Content panel (hidden by default) |
| `.tab-panel.active` | Visible content panel |

### View Switcher (larger tabs)

For top-level section switching (e.g. Timelines / Heartbeat Log / JSON), use `.view-bar` / `.view-btn` — a larger, bolder variant of tabs:

```django
<div class="view-bar">
    <button class="view-btn active" onclick="switchView(event, 'overview')">Overview</button>
    <button class="view-btn" onclick="switchView(event, 'details')">Details</button>
</div>
<div id="view-overview" class="view-panel active">...</div>
<div id="view-details" class="view-panel">...</div>
```

| Class | Purpose |
|-------|---------|
| `.view-bar` | Flex container with bottom border (like `.tab-bar` but no margin) |
| `.view-btn` | Larger tab button (0.95rem, 600 weight, 3px underline) |
| `.view-btn.active` | Primary color + bottom border |
| `.view-panel` | Content panel (hidden by default) |
| `.view-panel.active` | Visible content panel |

### Tab Hover Styling

Tab buttons use a subtle background tint on hover rather than a color-only change. This is critical for light-theme readability — a color-only hover (e.g. `color: var(--body-fg)`) can make text disappear against light backgrounds.

The correct hover pattern for tabs:

```css
.tab-btn {
    transition: color 0.15s, border-color 0.15s, background-color 0.15s;
    border-radius: var(--radius-sm) var(--radius-sm) 0 0;
}

.tab-btn:hover {
    color: var(--body-fg);
    background-color: color-mix(in srgb, var(--body-fg) 5%, transparent);
}
```

**Anti-pattern:** Never use only `color` for tab hover — it's unreadable in light themes. Always include `background-color` with a `color-mix()` tint. The same applies to view switcher buttons (`.view-btn`) or any tab-like navigation.

## Delete Modal

The delete modal is a confirmation dialog included automatically on CRUDView list and detail pages via `{% include "smallstack/crud/includes/delete_modal.html" %}`.

### Triggering the Modal

**From a standalone button** (detail pages, card actions):

```django
<button type="button" class="btn-danger"
    data-delete-url="{% url 'app:delete' pk=obj.pk %}"
    onclick="crudDeleteModal(this, '{{ obj }}')">
    Delete
</button>
```

**From a table row** (list pages — the modal auto-detects the `<tr>` and removes it on success):

```django
<td>
    <a href="{% url 'app:edit' pk=obj.pk %}" class="btn-primary btn-sm">Edit</a>
    <button type="button" class="btn-danger btn-sm"
        data-delete-url="{% url 'app:delete' pk=obj.pk %}"
        onclick="crudDeleteModal(this, '{{ obj }}')">Delete</button>
</td>
```

### How It Works

1. `crudDeleteModal(element, name)` — reads `data-delete-url` from the trigger element, shows the modal with the object name
2. User confirms → AJAX POST to the delete URL with CSRF token
3. **From a list page**: the table row fades out and is removed from the DOM (no page reload)
4. **From a detail page**: redirects to the list URL (found via `data-list-url` on a parent element)
5. **On ProtectedError**: title changes to "Cannot Delete", error message shown, Delete button hidden, Cancel becomes "Close"
6. **On network error**: inline error message, buttons remain functional for retry

For detail pages, add `data-list-url` so the modal knows where to redirect after deletion:

```django
<div class="card" data-list-url="{{ list_view_url }}">
```

### CSS Classes

The modal styles are defined inline in the template (`delete_modal.html`) and in `components.css`:

| Class | Purpose |
|-------|---------|
| `.crud-modal-overlay` | Fixed full-screen backdrop with blur |
| `.crud-modal` | Centered card container (max-width 420px) |
| `.crud-modal-header` | Title bar with close button |
| `.crud-modal-body` | Content area (confirmation text + error messages) |
| `.crud-modal-footer` | Action buttons (Delete + Cancel), right-aligned |
| `.crud-modal-btn-delete` | Red delete button (`--delete-button-bg`) |
| `.crud-modal-btn-cancel` | Outlined cancel/close button |
| `.crud-modal-close` | The &times; close button in the header |

### JavaScript API

| Function | Description |
|----------|-------------|
| `crudDeleteModal(el, name)` | Opens the modal. `el` is the trigger element (reads `data-delete-url`), `name` is displayed in the confirmation text |
| `crudDeleteModalClose()` | Closes the modal and resets state |
| `crudDeleteConfirm()` | Sends the DELETE POST — called by the modal's Delete button |

Escape key and backdrop click also close the modal.

## Search

```django
<input type="text" class="search-input" placeholder="Search items..."
    onkeyup="filterTable(this.value)">
```

The `.search-input` class includes a magnifying glass icon, focus ring, and proper sizing.

## Page Type Recipes

### Dashboard Page
```
page_header: title + subtitle + action cards or buttons
content: stat-cards row (optionally clickable with stat_modal),
         two-column grid of cards with tables,
         recent activity card with filter toggles
```

### List Page
```
page_header: title + subtitle + "Add" button (.btn-primary)
content: single card with crud-table inside
```

### Detail Page
```
page_header: object name + subtitle + Edit (.btn-primary) / Delete (.btn-danger) buttons
content: card (with data-list-url) containing detail fields (use crud_detail tag or custom layout)
include: delete_modal.html at bottom of content block
```

### Form Page (Create/Edit)
```
page_header: "Create X" or "Edit X" + subtitle
content: card with crud-form inside, btn-save + btn-cancel at bottom
```

### Settings/Config Page
```
page_header: title + subtitle
content: card with crud-form, possibly with tab-bar for sections
```

## Complete Button Reference

| Class | Context | Example |
|-------|---------|---------|
| `.btn-primary` | Page header, card header | `+ Add Item`, `Edit` |
| `.btn-secondary` | Page header nav links | `Public Status`, `SLA`, `Docs` |
| `.btn-outline` | Low-emphasis, card headers | `View All`, `Export` |
| `.btn-danger` | Delete triggers | `Delete` (with modal onclick) |
| `.btn-sm` | Size modifier (combine with above) | `Edit` in table cell, `View All` in card header |
| `.btn-save` | Form submit inside `.crud-form` | `Save`, `Create`, `Update` |
| `.btn-cancel` | Form cancel inside `.crud-form` | `Cancel` |
| `.filter-toggle` | Inline data filters in card headers | `All`, `Errors`, `Active` |
| `.tab-btn` | Full-width section tabs | `Overview`, `History`, `Config` |

## CSS Variable Reference

These are the theme variables available in any template. Use `var(--name)` in custom CSS:

| Variable | Purpose |
|----------|---------|
| `--primary` | Brand/accent color |
| `--primary-hover` | Darker primary for hover states |
| `--body-bg` | Page background |
| `--body-fg` | Main text color |
| `--body-quiet-color` | Muted/secondary text |
| `--card-bg` | Card background |
| `--button-fg` | Text color on primary buttons |
| `--delete-button-bg` | Red for danger actions |
| `--success-fg` | Green for success states |
| `--warning-fg` | Amber for warning states |
| `--error-fg` | Red for error states |
| `--radius-sm` | Small border radius (4-6px) |
| `--radius-md` | Medium border radius (8px) |

## Anti-Patterns — Do NOT Do These

```django
<!-- BAD: inline button styles -->
<a href="..." style="background: var(--primary); color: var(--button-fg);
    padding: 0.5rem 1rem; border: none; border-radius: var(--radius-sm, 4px);
    text-decoration: none; font-size: 0.85rem;">Button</a>

<!-- GOOD: use the class -->
<a href="..." class="btn-primary">Button</a>
```

```django
<!-- BAD: inline secondary button -->
<a href="..." class="btn" style="background: color-mix(in srgb, var(--primary) 20%, var(--body-bg));
    color: var(--primary); padding: 0.5rem 1rem;">Docs</a>

<!-- GOOD: use btn-secondary -->
<a href="..." class="btn-secondary">Docs</a>
```

```django
<!-- BAD: inline filter pills -->
<button class="button button-small" style="font-size: 0.75rem; padding: 4px 10px;">All</button>

<!-- GOOD: use filter-toggle -->
<div class="filter-toggles">
    <button class="filter-toggle active">All</button>
    <button class="filter-toggle">Errors</button>
</div>
```

```django
<!-- BAD: inline action card with onmouseover/onmouseout -->
<div class="card" style="border: 2px solid color-mix(...);" onmouseover="..." onmouseout="...">
    <div class="card-body" style="display: flex; align-items: center; gap: 10px; padding: 12px 16px;">
        <svg viewBox="0 0 24 24" width="28" height="28" fill="var(--primary)">...</svg>
        <div>
            <div style="font-weight: 700; font-size: 0.95rem; color: var(--primary);">Action</div>
            <div style="color: var(--body-quiet-color); font-size: 0.75rem;">Subtitle</div>
        </div>
    </div>
</div>

<!-- GOOD: use action-card classes -->
<div class="action-card" onclick="doAction()">
    <div class="action-card-body">
        <svg class="action-card-icon" viewBox="0 0 24 24">...</svg>
        <div>
            <div class="action-card-title">Action</div>
            <div class="action-card-subtitle">Subtitle</div>
        </div>
    </div>
</div>
```

```django
<!-- BAD: inline stat card -->
<div class="card">
    <div class="card-body" style="text-align: center; padding: 14px 8px;">
        <div style="font-size: 1.75rem; font-weight: 700; color: var(--primary);">42</div>
        <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Count</div>
    </div>
</div>

<!-- GOOD: use stat-card classes -->
<div class="stat-card">
    <div class="stat-card-value">42</div>
    <div class="stat-card-label">Count</div>
</div>
```

```django
<!-- BAD: page header with inline background -->
<div style="background: color-mix(in srgb, var(--primary) 15%, var(--body-bg));
    margin: -24px; padding: 24px;">

<!-- GOOD: use the class in the correct block -->
{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
```

## File Reference

| File | Contains |
|------|----------|
| `static/smallstack/css/theme.css` | CSS variables, base layout, `.page-header-bleed`, `.stat-card-clickable`, `.stat-modal` |
| `static/smallstack/css/components.css` | All component classes (buttons, tables, forms, cards, badges, tabs, action cards, filter toggles, stat cards, search, modals) |
| `templates/smallstack/base.html` | Base template with all blocks |
| `templates/smallstack/starter.html` | Copy-paste starter template |
| `templates/smallstack/includes/stat_modal.html` | Reusable stat card drill-down modal |
| `templates/smallstack/crud/includes/delete_modal.html` | Reusable delete confirmation modal |
