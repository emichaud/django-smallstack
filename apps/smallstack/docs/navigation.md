# Navigation System

SmallStack uses a unified, data-driven navigation system. One registry drives both the sidebar and the topbar — adding or removing an app in `INSTALLED_APPS` automatically updates navigation everywhere.

## Architecture

| Component | File | Role |
|-----------|------|------|
| Nav Registry | `apps/smallstack/navigation.py` | Central registry — apps register items here |
| Context Processor | `apps/smallstack/context_processors.py` | Resolves URLs, filters by auth/staff, exposes `nav_items` |
| Sidebar Template | `templates/smallstack/includes/sidebar.html` | Vertical nav in left panel |
| Topbar Template | `templates/smallstack/includes/topbar.html` | Horizontal nav in top bar |
| Base Template | `templates/smallstack/base.html` | Wires everything together with overridable blocks |
| CSS | `static/smallstack/css/theme.css` | Sidebar, submenu, and topbar-nav-auto styles |
| JS | `static/smallstack/js/theme.js` | Sidebar toggle, submenu expand/collapse, state management |

## Registering Nav Items

Register items in your app's `AppConfig.ready()`:

```python
from apps.smallstack.navigation import nav

class MyAppConfig(AppConfig):
    def ready(self):
        nav.register(
            section="main",
            label="Dashboard",
            url_name="myapp:dashboard",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="..."/></svg>',
            order=10,
        )
```

### Registration Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `section` | Yes | — | Section group: `main`, `topbar`, `app`, `page`, `resources`, `admin` |
| `label` | Yes | — | Display text |
| `url_name` | Yes | — | Django URL name (passed to `reverse()`) |
| `icon_svg` | No | `""` | Inline SVG string for the icon |
| `order` | No | `0` | Sort order within section (lower = higher) |
| `parent` | No | `None` | Label string of parent item (creates a submenu) |
| `auth_required` | No | `False` | Only show to authenticated users |
| `staff_required` | No | `False` | Only show to staff users |
| `url_args` | No | `[]` | Positional args for `reverse()` |
| `url_kwargs` | No | `{}` | Keyword args for `reverse()` |

## Sections

Sections control where items appear and in what order:

| Section | Sidebar | Topbar | Purpose |
|---------|---------|--------|---------|
| `main` | Yes | Yes (fallback) | Primary site navigation |
| `topbar` | **No** | Yes (overrides `main`) | Alternate topbar-only items |
| `app` | Yes | No | App-level contextual items |
| `page` | Yes | No | Page-level contextual items |
| `resources` | Yes | Yes (as dropdown) | Help, docs, external links |
| `admin` | Yes | Yes (as dropdown, staff only) | Staff administration |

### The `topbar` Section

When `topbar` items are registered, the topbar renders them **instead of** `main`. The sidebar always renders `main` and ignores `topbar`. This lets you show different navigation in each location:

```python
# Sidebar gets these
nav.register(section="main", label="Dashboard", url_name="dashboard", order=0)
nav.register(section="main", label="Settings", url_name="settings", order=1)

# Topbar gets these instead
nav.register(section="topbar", label="Features", url_name="website:features", order=0)
nav.register(section="topbar", label="Pricing", url_name="website:pricing", order=1)
```

If no `topbar` items are registered, the topbar falls back to rendering `main` items.

## Submenus (Parent/Child Items)

Create nested submenus by setting `parent` to the label of a top-level item in the same section:

```python
# Parent item
nav.register(section="main", label="Schedule", url_name="website:schedule", icon_svg="...", order=10)

# Children
nav.register(section="main", label="Calendar", url_name="website:calendar", parent="Schedule", icon_svg="...", order=0)
nav.register(section="main", label="Results", url_name="website:results", parent="Schedule", icon_svg="...", order=1)
```

**Sidebar behavior:**
- Parent renders as a clickable button (not a link) with a chevron
- Children are hidden by default, revealed with a smooth expand animation
- If a child page is active, the parent auto-opens on page load

**Topbar behavior:**
- Parent renders as a dropdown trigger
- Children appear in a dropdown menu on hover/click

**Defensive:** If a child references a `parent` label that doesn't exist, it's promoted to top-level instead of being silently dropped.

## Active State Detection

The system marks exactly one item as active per page — the one with the longest matching URL:

- **Exact match:** `/help/` highlights "Help"
- **Prefix match:** `/help/smallstack/navigation/` highlights "Help" (longest match)
- **Child active:** When a child is active, the parent gets `has_active_child: True` and auto-opens

## Sidebar

### Sidebar State

The sidebar has three states:

| State | Sidebar | Topbar Nav | Toggle Button |
|-------|---------|------------|---------------|
| `open` | Visible, content pushed right | Controlled by `TOPBAR_NAV_ALWAYS` | Shown |
| `closed` | Hidden | Shown | Shown |
| `disabled` | Never rendered | Shown | Hidden |

**Precedence (highest to lowest):**

1. **Template block** — `{% block sidebar_state %}disabled{% endblock %}` in a child template
2. **View context** — `request._smallstack_sidebar_state = "closed"` in a view
3. **User preference** — localStorage (set by clicking the toggle)
4. **Global setting** — `SMALLSTACK_SIDEBAR_DEFAULT` in Django settings

### Per-Page Sidebar Control

In any template that extends `smallstack/base.html`:

```html
{# Disable sidebar on this page #}
{% block sidebar_state %}disabled{% endblock %}

{# Start closed on this page #}
{% block sidebar_state %}closed{% endblock %}
```

When set via template block or view context, the state is **forced** — JavaScript won't override it with the user's localStorage preference.

### Sidebar Settings

| Setting | Default | Source | Description |
|---------|---------|--------|-------------|
| `SMALLSTACK_SIDEBAR_ENABLED` | `True` | `.env` | Remove sidebar and toggle entirely |
| `SMALLSTACK_SIDEBAR_OPEN` | `True` | `.env` | Legacy: start open or closed |
| `SMALLSTACK_SIDEBAR_DEFAULT` | `"open"` | `.env` | Default state: `open`, `closed`, or `disabled` |

`SMALLSTACK_SIDEBAR_DEFAULT` supersedes `SMALLSTACK_SIDEBAR_OPEN`. If `SMALLSTACK_SIDEBAR_ENABLED = False`, state is forced to `disabled`.

### Template Injection Blocks

The sidebar provides blocks for adding contextual items from child templates:

```html
{# Add app-level items (shown in "App" section) #}
{% block nav_app_items %}
<li class="nav-section-title">My App</li>
<li class="nav-item">
    <a href="..." class="nav-link">Custom Item</a>
</li>
{% endblock %}

{# Add page-level items (shown in "Page" section) #}
{% block nav_page_items %}
<li class="nav-item">
    <a href="..." class="nav-link">Page Action</a>
</li>
{% endblock %}
```

These blocks render between the main section and admin section. You can also register items to the `app` and `page` sections via the registry.

## Topbar Navigation

The topbar renders a horizontal nav bar from the registry data. By default it only appears when the sidebar is closed or disabled. This can be changed.

### Topbar Settings

| Setting | Default | Source | Description |
|---------|---------|--------|-------------|
| `SMALLSTACK_TOPBAR_NAV_ALWAYS` | `False` | `.env` | Show topbar nav even when sidebar is open |

### Per-Page Topbar Control

In any template that extends `smallstack/base.html`:

```html
{# Always show topbar nav on this page #}
{% block topbar_nav_mode %}always{% endblock %}

{# Only when sidebar is closed/disabled (default behavior) #}
{% block topbar_nav_mode %}auto{% endblock %}

{# Never show topbar nav on this page #}
{% block topbar_nav_mode %}hidden{% endblock %}
```

### Topbar Rendering Rules

- `main` section items render as horizontal links (or `topbar` section if registered)
- Items with children render as dropdown menus
- `resources` section → single "Resources" dropdown
- `admin` section → single "Admin" dropdown (staff only, includes Admin Panel link)
- Hidden on mobile (below 768px)

### Replacing the Entire Topbar

```html
{% block topbar %}
<header class="topbar">
    {# your custom topbar here #}
</header>
{% endblock %}
```

### Replacing the Sidebar

```html
{% block sidebar %}
<aside class="sidebar" id="sidebar">
    {# your custom sidebar here #}
</aside>
{% endblock %}
```

## Template Blocks Reference

All overridable blocks in `smallstack/base.html`:

| Block | Purpose | Default |
|-------|---------|---------|
| `sidebar_state` | Sidebar state: `open`, `closed`, `disabled` | From settings |
| `topbar_nav_mode` | Topbar nav: `always`, `auto`, `hidden` | From settings |
| `topbar` | Entire topbar HTML | Includes topbar.html |
| `sidebar` | Entire sidebar HTML | Includes sidebar.html |
| `sidebar_toggle` | Hamburger button in topbar | Shown when sidebar enabled |
| `nav_app_items` | Extra sidebar items (app section) | Empty |
| `nav_page_items` | Extra sidebar items (page section) | Empty |
| `breadcrumbs` | Breadcrumb trail | Includes breadcrumbs.html |
| `content` | Page content | Empty |
| `body_class` | Extra classes on `<body>` | Empty |

## Breadcrumbs

Add breadcrumbs in the `breadcrumbs` block:

```html
{% load theme_tags %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Section" "section_url" %}
{% breadcrumb "Current Page" %}
{% render_breadcrumbs %}
{% endblock %}
```

## Page Headers

Use `.page-header-with-actions` for page titles with action buttons:

```html
<div class="page-header-with-actions">
    <div class="page-header-content">
        <h1>Page Title</h1>
        <p class="page-subtitle">Optional subtitle.</p>
    </div>
    <div class="page-header-actions">
        <a href="/docs/" class="button button-secondary">View Docs</a>
        <button class="button button-primary button-prominent">Create New</button>
    </div>
</div>
```

## CSS Classes Reference

### Sidebar

| Class | Element | Description |
|-------|---------|-------------|
| `.sidebar` | `<aside>` | Sidebar container |
| `.nav-list` | `<ul>` | Nav item list |
| `.nav-section-title` | `<li>` | Section header text |
| `.nav-item` | `<li>` | Single nav item wrapper |
| `.nav-link` | `<a>` | Nav item link |
| `.nav-link.active` | `<a>` | Currently active item |
| `.nav-group` | `<li>` | Submenu parent wrapper |
| `.nav-group.open` | `<li>` | Expanded submenu |
| `.nav-parent` | `<button>` | Submenu toggle button |
| `.nav-submenu` | `<ul>` | Submenu children list |
| `.nav-child` | `.nav-link` | Child item (indented) |
| `.nav-chevron` | `<svg>` | Expand/collapse arrow |

### Topbar

| Class | Element | Description |
|-------|---------|-------------|
| `.topbar-nav-auto` | `<nav>` | Unified nav from registry |
| `.topbar-nav-list` | `<ul>` | Horizontal item list |
| `.topbar-nav-item` | `<li>` | Single topbar item |
| `.topbar-nav-link` | `<a>` or `<button>` | Topbar nav link |
| `.topbar-submenu` | `<ul>` | Dropdown menu |
| `.topbar-submenu-link` | `<a>` | Dropdown item |

## Deprecated Settings

These settings still work but will be removed in a future version:

| Setting | Replacement |
|---------|-------------|
| `SMALLSTACK_TOPBAR_NAV_ENABLED` | Use `SMALLSTACK_TOPBAR_NAV_ALWAYS` + nav registry |
| `SMALLSTACK_TOPBAR_NAV_ITEMS` | Use `nav.register(section="topbar", ...)` |
| `SMALLSTACK_SIDEBAR_OPEN` | Use `SMALLSTACK_SIDEBAR_DEFAULT` |

If the old `SMALLSTACK_TOPBAR_NAV_ITEMS` setting contains items, a deprecation warning is logged at startup.
