---
title: Theming & Customization
description: Customize colors, dark mode, and components
---

# Theming & Customization

The {{ project_name }} theme is built on Django admin's CSS foundation with custom CSS variables for easy customization and automatic dark/light mode support.

## Key Files

| File | Purpose |
|------|---------|
| `static/smallstack/css/theme.css` | Main theme CSS with all custom properties |
| `static/smallstack/css/palettes.css` | Color palette overrides (per-palette variables) |
| `static/smallstack/js/theme.js` | Dark mode toggle, palette switching, UI interactions |
| `apps/smallstack/palettes.yaml` | Palette registry (metadata for the palette selector UI) |
| `templates/smallstack/base.html` | Master layout template |
| `templates/smallstack/includes/` | Reusable template partials |
| `static/smallstack/brand/` | Default SmallStack brand assets |
| `static/brand/` | Your project's brand assets (downstream overrides) |

## Branding Quick Reference

The topbar displays your text logo at **32px height**. Replace with your own:

```python
# config/settings/base.py
BRAND_NAME = "My Project"
BRAND_LOGO_TEXT = "brand/my-logo-text.svg"  # Topbar (32px height)
```

For complete branding documentation including logo specifications and asset creation, see the [Customization Guide](/help/smallstack/customization/#customizing-branding).

## Changing Colors

All colors are defined as CSS custom properties in `static/smallstack/css/theme.css`. To customize:

### Edit Light Mode Colors

```css
:root {
    /* Primary colors - change these for your brand */
    --primary: #417690;        /* Your primary color */
    --primary-hover: #205067;  /* Darker variant for hover */
    --secondary: #79aec8;      /* Accent/secondary color */
    --accent: #f5dd5d;         /* Highlight color */

    /* Background colors */
    --body-bg: #f7f7f7;
    --body-fg: #333333;
    /* ... */
}
```

### Edit Dark Mode Colors

```css
[data-theme="dark"] {
    --primary: #44b78b;
    --body-bg: #121212;
    --body-fg: #f5f5f5;
    /* ... */
}
```

## Available CSS Variables

### Colors

| Variable | Purpose |
|----------|---------|
| `--primary`, `--primary-hover` | Primary brand colors |
| `--secondary` | Secondary brand color |
| `--accent` | Accent/highlight color |
| `--body-bg`, `--body-fg` | Body background and text |
| `--content-bg` | Content area background |
| `--header-bg`, `--header-fg` | Top bar colors |
| `--sidebar-*` | Sidebar-specific colors |
| `--card-*` | Card component colors |
| `--input-*` | Form input colors |
| `--success-*`, `--warning-*`, `--error-*`, `--info-*` | Message colors |
| `--button-*` | Button colors |
| `--text-muted` | Muted text color |
| `--link-color`, `--link-hover` | Link colors |

### Spacing & Layout

| Variable | Default | Purpose |
|----------|---------|---------|
| `--topbar-height` | 56px | Height of the top navigation |
| `--sidebar-width` | 250px | Sidebar width |
| `--sidebar-collapsed-width` | 60px | Collapsed sidebar width |

### Effects

| Variable | Purpose |
|----------|---------|
| `--shadow-sm`, `--shadow-md`, `--shadow-lg` | Box shadows |
| `--transition-fast`, `--transition-normal` | Animation timing |
| `--radius-sm`, `--radius-md`, `--radius-lg` | Border radius |

## Color Palettes

SmallStack includes 5 selectable color palettes that change the primary accent colors across the entire UI — topbar, sidebar, buttons, links, and more.

### Available Palettes

| Palette | Light Mode | Dark Mode | Description |
|---------|-----------|-----------|-------------|
| `django` (default) | Teal | Green | Classic Django admin colors |
| `light-blue` | Sky blue | Light cyan | Clean sky blue tones |
| `dark-blue` | Navy | Blue | Deep ocean blue |
| `orange` | Deep orange | Amber | Warm sunset orange |
| `purple` | Violet | Lavender | Rich violet tones |

### Setting the System Default

Set the default palette for all users via settings or `.env`:

```python
# config/settings/base.py (or in .env)
SMALLSTACK_COLOR_PALETTE = "purple"
```

Options: `django`, `light-blue`, `dark-blue`, `orange`, `purple`

### Per-User Override

Authenticated users can choose their own palette on the **Profile Edit** page. A swatch selector shows all available palettes with preview colors. The user's choice overrides the system default and persists across sessions.

If a user clears their selection (sets it to blank), they fall back to the system default.

### How It Works

Palettes use a `data-palette` attribute on `<html>`, separate from the `data-theme` attribute:

```html
<html data-theme="dark" data-palette="purple">
```

A blocking `<script>` in `<head>` applies the palette from `localStorage` before CSS renders, preventing any flash. For authenticated users, palette changes are saved to their profile via htmx POST.

### Adding a Custom Palette

1. Add entry to `apps/smallstack/palettes.yaml`:
```yaml
  - id: my-palette
    label: My Palette
    description: My custom colors
    preview:
      light: "#1a73e8"
      dark: "#8ab4f8"
```

2. Add CSS blocks to `static/smallstack/css/palettes.css`:
```css
html[data-palette="my-palette"] {
    --primary: #1a73e8;
    --primary-hover: #1557b0;
    --header-bg: #1a73e8;
    --sidebar-active-bg: #1a73e8;
    --sidebar-active-fg: #ffffff;
    --input-focus-border: #1a73e8;
    --button-bg: #1a73e8;
    --button-fg: #ffffff;
    --button-hover-bg: #1557b0;
    --link-color: #1a73e8;
    --link-hover: #1557b0;
    --breadcrumb-link: #1a73e8;
}

html[data-palette="my-palette"][data-theme="dark"] {
    --primary: #8ab4f8;
    --primary-hover: #aecbfa;
    --header-bg: #0d3b7a;
    --hero-gradient-end: #1557b0;
    --sidebar-active-bg: #8ab4f8;
    --sidebar-active-fg: #000000;
    --input-focus-border: #8ab4f8;
    --button-bg: #8ab4f8;
    --button-fg: #000000;
    --button-hover-bg: #aecbfa;
    --link-color: #aecbfa;
    --link-hover: #c6dafc;
    --breadcrumb-link: #aecbfa;
}
```

3. Add choice to `UserProfile.COLOR_PALETTE_CHOICES` in `apps/profile/models.py` and create a migration
4. Add id to `PalettePreferenceView.VALID_PALETTES` in `apps/profile/views.py`

> **Note for downstream projects:** Steps 1-4 modify core SmallStack files. If you pull upstream updates, you may get merge conflicts. Keep your custom palette additions at the end of `palettes.css` and `palettes.yaml` to minimize friction.

## Dark/Light Mode

### How It Works

1. Theme preference is stored in `localStorage` as `smallstack-theme`
2. On page load, theme is applied via `data-theme` attribute on `<html>`
3. CSS variables change based on `data-theme` value
4. Users toggle via the sun/moon icon in the top bar

### JavaScript API

```javascript
// Set theme programmatically
document.documentElement.setAttribute('data-theme', 'dark');

// Get current theme
const theme = document.documentElement.getAttribute('data-theme');
```

### System Preference

The theme respects the user's system preference (`prefers-color-scheme`) when no explicit choice has been saved.

## Adding Navigation Items

### Sidebar Links

Edit `templates/smallstack/includes/sidebar.html`:

```html
<li class="nav-item">
    <a href="{% url 'your_url_name' %}" class="nav-link {% nav_active 'your_url_name' %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <!-- SVG icon path -->
        </svg>
        <span>Your Link</span>
    </a>
</li>
```

### Section Titles

```html
<li class="nav-section-title">Section Name</li>
```

### Active State

Use `{% nav_active 'url_name' %}` to highlight the current page:

```html
<a href="{% url 'home' %}" class="nav-link {% nav_active 'home' %}">Home</a>
```

## Template Tags

### Breadcrumbs

```html
{% load theme_tags %}

{% breadcrumb "Home" "home" %}
{% breadcrumb "Profile" "profile" %}
{% breadcrumb "Edit" %}  {# No URL for current page #}
{% render_breadcrumbs %}
```

### Navigation Active State

```html
{% load theme_tags %}

<a href="{% url 'home' %}" class="{% nav_active 'home' %}">Home</a>
```

## Component Reference

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
<button class="button">Default Button</button>
<button class="button button-primary">Primary Button</button>
<button class="button button-secondary">Secondary Button</button>
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
    <label for="field">Field Label</label>
    <input type="text" id="field" class="vTextField">
    <span class="helptext">Help text here</span>
</div>
```

## Creating a Parallel Theme

SmallStack ships with a Django admin-based CSS theme, but you can add a second CSS framework (Bootstrap, Tailwind, Tabler, etc.) **alongside** the default without removing it. This lets you build new pages with the new framework while existing pages continue to work.

### Strategy: A Parallel Base Template

Instead of replacing `templates/smallstack/base.html`, create a new base template for your framework. Two common patterns:

```
# Pattern A: Single file in your app's template directory
templates/
├── smallstack/
│   └── base.html              ← SmallStack default (keep as-is)
├── website/
│   └── base_tabler.html       ← Your new framework base

# Pattern B: Theme directory with its own partials (for larger themes)
templates/
├── smallstack/
│   └── base.html              ← SmallStack default (keep as-is)
├── tabler/
│   ├── base.html              ← Your new framework base
│   └── includes/
│       ├── navbar.html        ← Framework-specific partials
│       └── footer.html
```

Pattern A is simpler and works well for a single base template with a few pages. Pattern B is better when your theme needs its own set of reusable partials.

Your new base template loads its own CSS/JS, but can still use SmallStack's sidebar, topbar, and template tags if you want:

```html
{# templates/website/base_tabler.html #}
{% load static theme_tags %}
<!DOCTYPE html>
<html lang="en" data-theme="{{ theme }}" data-palette="{{ color_palette }}">
<head>
    <link rel="stylesheet" href="{% static 'css/tabler.min.css' %}">
    {% block extra_css %}{% endblock %}
</head>
<body>
    {% include "smallstack/includes/topbar.html" %}
    <div class="page-body">
        {% block content %}{% endblock %}
    </div>
    <script src="{% static 'js/tabler.min.js' %}"></script>
    {% block extra_js %}{% endblock %}
</body>
</html>
```

New pages extend your framework base:

```html
{# templates/website/dashboard.html #}
{% extends "website/base_tabler.html" %}
{% block content %}
    <div class="container-xl">...</div>
{% endblock %}
```

### What to Keep, What to Replace

| Component | Keep from SmallStack? | Notes |
|-----------|----------------------|-------|
| Topbar / sidebar | Your choice | Include the SmallStack partials, or build your own |
| Dark/light mode | Yes | `data-theme` attribute and `theme.js` work with any CSS |
| Color palettes | Yes | `data-palette` attribute is framework-agnostic |
| Template tags | Yes | `{% breadcrumb %}`, `{% nav_active %}` are pure logic |
| `theme.css` | No (for new pages) | Your framework provides its own styles |
| `admin/css/base.css` | No (for new pages) | Only needed for SmallStack's default look |

### Tips

- **Vendor CSS/JS locally for production** — download framework files into `static/css/` and `static/js/` rather than relying on CDNs. CDN links are fine for prototyping and development, but vendor locally before deploying. SmallStack does this with htmx.
- **Share the topbar** — if you include `smallstack/includes/topbar.html`, the dark mode toggle and palette selector work automatically.
- **Gradual migration** — move pages one at a time from `base.html` to your new base. No need to convert everything at once.

## Swapping CSS Frameworks Entirely

If you want to fully replace SmallStack's CSS (not run in parallel):

### Step 1: Remove Current CSS

In `templates/smallstack/base.html`:

```html
<!-- Remove or comment out -->
<link rel="stylesheet" href="{% static 'admin/css/base.css' %}">
<link rel="stylesheet" href="{% static 'smallstack/css/theme.css' %}">
```

### Step 2: Add Your Framework

```html
<link href="{% static 'css/framework.min.css' %}" rel="stylesheet">
```

### Step 3: Update Component Classes

Update HTML classes in templates to match your framework's conventions.

### Step 4: Update Dark Mode

If your framework has its own dark mode system, update `static/smallstack/js/theme.js` accordingly.

## Best Practices

1. **Use CSS Variables** - Always use variables instead of hard-coded colors
2. **Test Both Themes** - Always test changes in light and dark modes
3. **Mobile First** - Test on mobile screens; the theme is responsive
4. **Extend, Don't Override** - Add new classes rather than overriding existing ones
5. **Keep Admin CSS** - Django admin CSS provides useful form styling
