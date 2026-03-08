# Skill: Theming System

This skill describes how to customize the SmallStack theme, including colors, color palettes, dark mode, and UI components.

## Overview

The theme is built on Django admin's CSS foundation with CSS custom properties (variables) for easy customization. All theming is done through CSS - no build tools required.

SmallStack supports **selectable color palettes** (django, high-contrast, dark-blue, orange, purple) with a system-wide default and per-user override.

## File Locations

```
static/
├── smallstack/                 # UPSTREAM: Core SmallStack assets
│   ├── css/
│   │   ├── theme.css           # Main theme - variables, layout, components
│   │   └── palettes.css        # Color palette overrides (per-palette variables)
│   ├── js/
│   │   ├── theme.js            # Dark mode toggle, palette switching, sidebar, dropdowns
│   │   └── htmx.min.js         # htmx library (vendored, no CDN)
│   └── help/
│       └── css/help.css        # Help system specific styles
├── css/                        # DOWNSTREAM: Project CSS overrides
├── js/                         # DOWNSTREAM: Project JS
└── brand/                      # DOWNSTREAM: Project brand assets

apps/smallstack/
├── palettes.yaml               # Palette registry (metadata for UI)
├── context_processors.py       # Exposes palette data to templates

apps/profile/
├── models.py                   # UserProfile.color_palette field
├── views.py                    # PalettePreferenceView (htmx POST)

templates/smallstack/
├── base.html               # Master layout template
└── includes/
    ├── topbar.html         # Top navigation bar
    ├── sidebar.html        # Left sidebar navigation
    ├── messages.html       # Flash messages
    └── breadcrumbs.html    # Breadcrumb navigation
```

## CSS Custom Properties

All colors and key values are defined as CSS variables in `static/smallstack/css/theme.css`.

### Light Mode (`:root`)

```css
:root {
    /* Primary colors */
    --primary: #417690;
    --primary-hover: #205067;
    --secondary: #79aec8;
    --accent: #f5dd5d;

    /* Background colors */
    --body-bg: #f7f7f7;
    --body-fg: #333333;
    --content-bg: #ffffff;

    /* Sidebar */
    --sidebar-bg: #ffffff;
    --sidebar-fg: #333333;
    --sidebar-hover-bg: #f0f0f0;
    --sidebar-active-bg: #417690;
    --sidebar-active-fg: #ffffff;

    /* Cards */
    --card-bg: #ffffff;
    --card-border: #e0e0e0;
    --card-header-bg: #f5f5f5;

    /* Forms */
    --input-bg: #ffffff;
    --input-border: #cccccc;

    /* Messages */
    --success-bg: #dff0d8;
    --success-fg: #3c763d;
    --error-bg: #f2dede;
    --error-fg: #a94442;

    /* Text */
    --text-muted: #666666;
    --link-color: #417690;

    /* Layout */
    --topbar-height: 56px;
    --sidebar-width: 250px;

    /* Effects */
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
    --radius-sm: 4px;
    --radius-md: 8px;
    --transition-fast: 0.15s ease;
}
```

### Dark Mode (`[data-theme="dark"]`)

```css
[data-theme="dark"] {
    --primary: #44b78b;
    --primary-hover: #5fcfa1;

    --body-bg: #121212;
    --body-fg: #f5f5f5;
    --content-bg: #1e1e1e;

    --sidebar-bg: #1e1e1e;
    --sidebar-fg: #f5f5f5;
    --sidebar-hover-bg: #303030;

    --card-bg: #212121;
    --card-border: #3d3d3d;

    --text-muted: #b0b0b0;
    --link-color: #81d4fa;
}
```

## Color Palettes

SmallStack includes 5 built-in color palettes that override the primary color variables for both light and dark modes.

### Available Palettes

| Palette | Light Primary | Dark Primary | Description |
|---------|--------------|-------------|-------------|
| `django` (default) | `#417690` | `#44b78b` | Classic Django admin colors |
| `high-contrast` | `#212121` | `#e0e0e0` | Monochrome for accessibility |
| `dark-blue` | `#1565c0` | `#42a5f5` | Deep ocean blue |
| `orange` | `#e65100` | `#ff9800` | Warm sunset orange |
| `purple` | `#7e57c2` | `#b39ddb` | Rich violet tones |

### Two Tiers of Control

1. **System default** — `SMALLSTACK_COLOR_PALETTE` setting in `base.py` / `.env` (default: `"django"`)
2. **User override** — `color_palette` field on `UserProfile` (blank = use system default)

### How Palettes Work

Palettes use a `data-palette` attribute on `<html>`, orthogonal to the existing `data-theme="dark|light"` attribute:

```html
<html lang="en" data-theme="dark" data-palette="purple">
```

CSS overrides in `palettes.css` use `html[data-palette="X"]` selectors to beat `:root` specificity:

```css
html[data-palette="purple"] {
    --primary: #7e57c2;
    --primary-hover: #5e35b1;
    --header-bg: #7e57c2;
    --sidebar-active-bg: #7e57c2;
    --button-bg: #7e57c2;
    --link-color: #7e57c2;
    /* ... */
}

html[data-palette="purple"][data-theme="dark"] {
    --primary: #b39ddb;
    --primary-hover: #ce93d8;
    --header-bg: #2a1a4a;
    /* ... */
}
```

### Setting the System Default

```python
# config/settings/base.py (or in .env)
SMALLSTACK_COLOR_PALETTE = "purple"  # Options: django, high-contrast, dark-blue, orange, purple
```

### Adding a New Palette

1. Add entry to `apps/smallstack/palettes.yaml` (id, label, preview colors)
2. Add `html[data-palette="X"]` and `html[data-palette="X"][data-theme="dark"]` blocks to `static/smallstack/css/palettes.css`
3. Add choice to `UserProfile.COLOR_PALETTE_CHOICES` in `apps/profile/models.py` + create migration
4. Add id to `PalettePreferenceView.VALID_PALETTES` set in `apps/profile/views.py`

> **Downstream note:** Steps 1-4 all modify files inside `apps/smallstack/` and `apps/profile/` — these are core SmallStack files. If you pull upstream updates, you may get merge conflicts on these files. To minimize friction, keep your custom palette additions clearly separated (e.g., append to the end of `palettes.css` and `palettes.yaml`).

### Palette Context Variables

The `branding` context processor provides these template variables:

| Variable | Description |
|----------|-------------|
| `palettes` | List of all palette definitions from `palettes.yaml` |
| `color_palette` | Effective palette for current request (user override > system default) |
| `system_color_palette` | System default palette from settings |

### JavaScript API

```javascript
// Get current palette
const palette = document.documentElement.getAttribute('data-palette');

// Set palette programmatically (also saves to profile via htmx)
setPalette('purple');

// Keys in window.SMALLSTACK
window.SMALLSTACK.userPalette;   // User's saved palette preference
window.SMALLSTACK.colorPalette;  // Effective palette for this page load
```

## Changing the Primary Color

To rebrand the entire app without using the palette system:

1. Edit `static/smallstack/css/theme.css` (or add overrides in `static/css/project.css`)
2. Change `--primary` and `--primary-hover` in both `:root` and `[data-theme="dark"]`

```css
:root {
    --primary: #your-brand-color;
    --primary-hover: #darker-variant;
}

[data-theme="dark"] {
    --primary: #lighter-variant-for-dark;
    --primary-hover: #even-lighter;
}
```

## Dark Mode Implementation

### How It Works

1. A blocking inline `<script>` in `<head>` reads `localStorage` and sets `data-theme` and `data-palette` on `<html>` **before CSS renders** — no flash
2. `theme.js` initializes toggle buttons, palette swatches, and listens for changes
3. CSS variables change based on `[data-theme="dark"]` and `[data-palette="X"]` selectors
4. Toggle button in topbar switches between modes
5. For authenticated users, theme and palette changes are saved to their profile via htmx (`POST /profile/theme/` and `POST /profile/palette/`)

### JavaScript API

```javascript
// Get current theme
const theme = document.documentElement.getAttribute('data-theme');

// Set theme programmatically
document.documentElement.setAttribute('data-theme', 'dark');
localStorage.setItem('smallstack-theme', 'dark');
```

## UI Components

### Cards

```html
<div class="card">
    <div class="card-header">
        <h2>Card Title</h2>
    </div>
    <div class="card-body">
        Card content here
    </div>
</div>
```

### Buttons

```html
<button class="button">Default</button>
<button class="button button-primary">Primary</button>
<button class="button button-secondary">Secondary</button>
<a href="#" class="button">Link Button</a>
```

### Messages/Alerts

```html
<div class="message success">Success message</div>
<div class="message error">Error message</div>
<div class="message warning">Warning message</div>
<div class="message info">Info message</div>
```

### Forms

```html
<div class="form-group">
    <label for="field">Label</label>
    <input type="text" id="field" class="vTextField">
    <span class="helptext">Help text</span>
</div>
```

## Adding Sidebar Navigation Items

Edit `templates/smallstack/includes/sidebar.html`:

```html
<li class="nav-item">
    <a href="{% url 'your_url_name' %}" class="nav-link {% nav_active 'your_url_name' %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <!-- SVG icon path -->
        </svg>
        <span>Link Text</span>
    </a>
</li>
```

Sidebar nav icons are automatically tinted with the palette's `--primary` color. Active links use `--sidebar-active-bg/fg`. Hover states shift text to `--primary`.

### Section Titles

```html
<li class="nav-section-title">Section Name</li>
```

### Active State

The `{% nav_active 'url_name' %}` template tag adds the `active` class when on that page.

## Template Tags

Load with `{% load theme_tags %}`:

### Breadcrumbs

```html
{% breadcrumb "Home" "home" %}
{% breadcrumb "Profile" "profile" %}
{% breadcrumb "Edit" %}  {# Current page, no link #}
{% render_breadcrumbs %}
```

### Navigation Active

```html
<a class="nav-link {% nav_active 'home' %}">Home</a>
<a class="nav-link {% nav_active 'help:index' 'help:detail' %}">Help</a>
```

## Creating a Parallel Theme

You can add a second CSS framework (Bootstrap, Tailwind, Tabler) alongside SmallStack's default theme by creating a parallel base template. Two common patterns:

**Pattern A — Single file in your app's template directory** (simple):
1. Create `templates/website/base_tabler.html` — loads the new framework's CSS/JS
2. New pages extend it: `{% extends "website/base_tabler.html" %}`

**Pattern B — Theme directory with its own partials** (for larger themes):
1. Create `templates/tabler/base.html` + `templates/tabler/includes/` for framework-specific partials
2. New pages extend it: `{% extends "tabler/base.html" %}`

In both cases, existing SmallStack pages continue using `templates/smallstack/base.html` unchanged.

What works across both bases:
- `data-theme` / `data-palette` attributes and `theme.js` (framework-agnostic)
- SmallStack template tags (`{% breadcrumb %}`, `{% nav_active %}`)
- SmallStack partials (`topbar.html`, `sidebar.html`) can be included in either base

Vendor framework CSS/JS locally in `static/css/` and `static/js/` for production. CDN links are fine for prototyping and development, but vendor locally before deploying.

## Adding New CSS

### For Global Styles

Add to `static/smallstack/css/theme.css` at the end, or better yet, create a project-specific CSS file in `static/css/` and load it via `{% block extra_css %}`.

### For App-Specific Styles

Create `static/yourapp/css/yourapp.css` and include in template:

```html
{% block extra_css %}
<link rel="stylesheet" href="{% static 'yourapp/css/yourapp.css' %}">
{% endblock %}
```

### Dark Mode Support

Always include dark mode variants:

```css
.my-component {
    background: var(--card-bg);
    color: var(--body-fg);
}

/* If custom colors needed */
[data-theme="dark"] .my-component {
    /* dark mode overrides */
}
```

### Palette Support

Components that use `var(--primary)`, `var(--link-color)`, etc. automatically adapt to palette changes. If you hardcode colors, they won't change with the palette.

## Responsive Breakpoints

```css
/* Tablet */
@media (max-width: 900px) {
    /* Sidebar collapses to overlay */
}

/* Mobile */
@media (max-width: 600px) {
    /* Single column layouts */
}
```

## Best Practices

1. **Use CSS variables** - Never hardcode colors
2. **Test both themes** - Always check light and dark modes
3. **Test multiple palettes** - Verify your components look good with different primary colors
4. **Mobile first** - Test on small screens
5. **Extend, don't override** - Add new classes rather than changing existing
6. **Keep Django admin CSS** - It provides useful form styling
7. **Use `var(--primary)` for branded elements** - They'll automatically adapt to palette changes
