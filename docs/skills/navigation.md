# Skill: Navigation System

SmallStack uses a unified, data-driven navigation system. One registry drives both the sidebar and the topbar — adding or removing an app in `INSTALLED_APPS` automatically updates navigation everywhere.

## Overview

Apps register nav items in their `AppConfig.ready()` method. A context processor resolves URLs, filters by auth/staff status, and exposes `nav_items` to templates. The sidebar and topbar templates render from this shared data.

## File Locations

```
apps/smallstack/
├── navigation.py              # Nav registry — apps register items here
├── context_processors.py      # Resolves URLs, filters by auth/staff, exposes nav_items

templates/smallstack/
├── base.html                  # Wires sidebar + topbar with overridable blocks
└── includes/
    ├── sidebar.html           # Vertical nav in left panel
    └── topbar.html            # Horizontal nav in top bar

static/smallstack/
├── css/theme.css              # Sidebar, submenu, topbar-nav-auto styles
└── js/theme.js                # Sidebar toggle, submenu expand/collapse
```

## Registering Nav Items

```python
# apps/myapp/apps.py
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
| `section` | Yes | — | `main`, `topbar`, `app`, `page`, `resources`, `admin` |
| `label` | Yes | — | Display text |
| `url_name` | Yes | — | Django URL name (passed to `reverse()`) |
| `icon_svg` | No | `""` | Inline SVG string |
| `order` | No | `0` | Sort order (lower = higher) |
| `parent` | No | `None` | Label of parent item (creates submenu) |
| `auth_required` | No | `False` | Only show to authenticated users |
| `staff_required` | No | `False` | Only show to staff users |
| `url_args` | No | `[]` | Positional args for `reverse()` |
| `url_kwargs` | No | `{}` | Keyword args for `reverse()` |

## Sections

| Section | Sidebar | Topbar | Purpose |
|---------|---------|--------|---------|
| `main` | Yes | Yes (fallback) | Primary site navigation |
| `topbar` | **No** | Yes (overrides `main`) | Topbar-only items |
| `app` | Yes | No | App-level contextual items |
| `page` | Yes | No | Page-level contextual items |
| `resources` | Yes | Yes (dropdown) | Help, docs, external links |
| `admin` | Yes | Yes (dropdown, staff only) | Staff administration |

When `topbar` items are registered, the topbar renders them **instead of** `main`. The sidebar always renders `main`.

## Submenus

```python
# Parent
nav.register(section="main", label="Schedule", url_name="schedule", icon_svg="...", order=10)

# Children
nav.register(section="main", label="Calendar", url_name="calendar", parent="Schedule", order=0)
nav.register(section="main", label="Results", url_name="results", parent="Schedule", order=1)
```

- **Sidebar:** Parent is a button with chevron, children expand/collapse
- **Topbar:** Parent is a dropdown trigger
- If child references nonexistent parent, it's promoted to top-level

## Active State Detection

Longest matching URL wins:
- `/help/` highlights "Help"
- `/help/smallstack/navigation/` also highlights "Help" (prefix match)
- Active child sets `has_active_child: True` on parent

## Sidebar

### Three States

| State | Sidebar | Toggle Button |
|-------|---------|---------------|
| `open` | Visible, content pushed right | Shown |
| `closed` | Hidden | Shown |
| `disabled` | Never rendered | Hidden |

### State Precedence (highest to lowest)

1. **Template block** — `{% block sidebar_state %}disabled{% endblock %}`
2. **View context** — `request._smallstack_sidebar_state = "closed"`
3. **User preference** — localStorage
4. **Global setting** — `SMALLSTACK_SIDEBAR_DEFAULT`

### Per-Page Control

```html
{% block sidebar_state %}disabled{% endblock %}  {# No sidebar #}
{% block sidebar_state %}closed{% endblock %}    {# Start closed #}
```

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `SMALLSTACK_SIDEBAR_ENABLED` | `True` | Remove sidebar entirely |
| `SMALLSTACK_SIDEBAR_DEFAULT` | `"open"` | Default state |

## Topbar

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `SMALLSTACK_TOPBAR_NAV_ALWAYS` | `False` | Show topbar nav even when sidebar is open |

### Per-Page Control

```html
{% block topbar_nav_mode %}always{% endblock %}  {# Always show #}
{% block topbar_nav_mode %}auto{% endblock %}    {# Default: when sidebar closed #}
{% block topbar_nav_mode %}hidden{% endblock %}  {# Never show #}
```

### Rendering Rules

- `main` items as horizontal links (or `topbar` if registered)
- Items with children as dropdown menus
- `resources` → "Resources" dropdown
- `admin` → "Admin" dropdown (staff only, includes Admin Panel link)
- Hidden on mobile (below 768px)

## Template Blocks

| Block | Purpose | Default |
|-------|---------|---------|
| `sidebar_state` | Sidebar state | From settings |
| `topbar_nav_mode` | Topbar nav visibility | From settings |
| `topbar` | Entire topbar HTML | Includes topbar.html |
| `sidebar` | Entire sidebar HTML | Includes sidebar.html |
| `nav_app_items` | Extra sidebar items (app section) | Empty |
| `nav_page_items` | Extra sidebar items (page section) | Empty |
| `breadcrumbs` | Breadcrumb trail | Includes breadcrumbs.html |

## Breadcrumbs

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

```html
<div class="page-header-with-actions">
    <div class="page-header-content">
        <h1>Page Title</h1>
        <p class="page-subtitle">Optional subtitle.</p>
    </div>
    <div class="page-header-actions">
        <button class="button button-primary button-prominent">Create New</button>
    </div>
</div>
```

## Best Practices

1. **Register in `AppConfig.ready()`** — nav items appear/disappear with `INSTALLED_APPS`
2. **Use `order`** to control position — lower numbers appear first
3. **Use `staff_required=True`** for admin tools
4. **Use `section="admin"`** for staff-only sidebar items
5. **Disable sidebar** on public/landing pages with `{% block sidebar_state %}disabled{% endblock %}`
6. **Use `topbar` section** when public pages need different nav than the sidebar
