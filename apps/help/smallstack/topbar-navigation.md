# Topbar Navigation

Add a horizontal navigation menu to the topbar — perfect for marketing sites, landing pages, or any layout where the sidebar is closed by default.

## When to Use

- **Marketing / hero sites** — sidebar closed, navigation in the topbar
- **Public-facing pages** — visitors see nav links without needing to open a sidebar
- Pairs well with `SMALLSTACK_SIDEBAR_OPEN = False` or `SMALLSTACK_SIDEBAR_ENABLED = False`

## Quick Start

In your project's settings (e.g., `config/settings/base.py`):

```python
SMALLSTACK_TOPBAR_NAV_ENABLED = True  # or set via .env

SMALLSTACK_TOPBAR_NAV_ITEMS = [
    {"label": "Features", "url": "website:features"},
    {"label": "Docs", "url": "help:index"},
    {"label": "About", "url": "website:about"},
]
```

## Item Format

Each item is a dictionary with these keys:

| Key | Required | Description |
|-----|----------|-------------|
| `label` | Yes | Display text |
| `url` | Yes* | URL name (reversed), absolute path, or full URL |
| `children` | No | List of child items (creates a submenu) |
| `external` | No | `True` to open in new tab with `rel="noopener"` |
| `auth_required` | No | `True` to show only to authenticated users |
| `staff_required` | No | `True` to show only to staff users |
| `url_args` | No | List of args passed to `reverse()` |

*Not required for parent items with `children`.

### URL Types

```python
# Django URL name (resolved via reverse())
{"label": "Features", "url": "website:features"}

# Absolute path
{"label": "Docs", "url": "/docs/"}

# External URL
{"label": "GitHub", "url": "https://github.com/...", "external": True}
```

### Submenus

```python
{"label": "Resources", "children": [
    {"label": "Documentation", "url": "help:index"},
    {"label": "About", "url": "website:about"},
    {"label": "GitHub", "url": "https://github.com/...", "external": True},
]}
```

Submenus open on click and close when clicking outside or pressing Escape.

### Conditional Visibility

```python
# Only visible to logged-in users
{"label": "Dashboard", "url": "website:dashboard", "auth_required": True}

# Only visible to staff
{"label": "Admin", "url": "admin:index", "staff_required": True}
```

## Active State

Links are automatically highlighted when the current page matches:
- **Exact match**: `/about/` highlights the "About" link
- **Prefix match**: `/help/getting-started/` highlights a link to `/help/`
- **Submenu parents**: highlighted when any child is active

## Responsive Behavior

The topbar nav is **hidden on mobile** (below 768px). On small screens, use the sidebar for navigation instead.

## Theming

The nav uses existing CSS variables — no palette overrides needed:
- Links: `var(--header-fg)` on `var(--header-bg)`
- Hover: `rgba(255,255,255,0.1)` (matches hamburger/theme toggle)
- Active: `rgba(255,255,255,0.15)`
- Submenu dropdown: `var(--card-bg)`, `var(--card-border)`, `var(--shadow-lg)`
- Submenu hover: `var(--sidebar-hover-bg)`
- Submenu active: `var(--sidebar-active-bg)` / `var(--sidebar-active-fg)`

Works across all palettes and both light/dark themes automatically.

## Settings Reference

| Setting | Default | Source |
|---------|---------|--------|
| `SMALLSTACK_TOPBAR_NAV_ENABLED` | `False` | `.env` or settings |
| `SMALLSTACK_TOPBAR_NAV_ITEMS` | `[]` | Settings only (Python list) |
