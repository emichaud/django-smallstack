# Skill: Theming System

This skill describes how to customize the SmallStack theme, including colors, dark mode, and UI components.

## Overview

The theme is built on Django admin's CSS foundation with CSS custom properties (variables) for easy customization. All theming is done through CSS - no build tools required.

## File Locations

```
static/
├── smallstack/                 # UPSTREAM: Core SmallStack assets
│   ├── css/
│   │   └── theme.css           # Main theme - variables, layout, components
│   ├── js/
│   │   ├── theme.js            # Dark mode toggle, sidebar, dropdowns
│   │   └── htmx.min.js         # htmx library (vendored, no CDN)
│   └── help/
│       └── css/help.css        # Help system specific styles
├── css/                        # DOWNSTREAM: Project CSS overrides
├── js/                         # DOWNSTREAM: Project JS
└── brand/                      # DOWNSTREAM: Project brand assets

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

## Changing the Primary Color

To rebrand the entire app:

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

1. A blocking inline `<script>` in `<head>` reads `localStorage` and sets `data-theme` on `<html>` **before CSS renders** — no flash
2. `theme.js` initializes toggle buttons and listens for changes
3. CSS variables change based on `[data-theme="dark"]` selector
4. Toggle button in topbar switches between modes
5. For authenticated users, theme changes are saved to their profile via htmx (`POST /profile/theme/`)

### JavaScript API

```javascript
// Get current theme
const theme = document.documentElement.getAttribute('data-theme');

// Set theme programmatically
document.documentElement.setAttribute('data-theme', 'dark');
localStorage.setItem('smallstack-theme', 'dark');

// Toggle theme
const current = localStorage.getItem('smallstack-theme') || 'light';
const next = current === 'dark' ? 'light' : 'dark';
document.documentElement.setAttribute('data-theme', next);
localStorage.setItem('smallstack-theme', next);
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
3. **Mobile first** - Test on small screens
4. **Extend, don't override** - Add new classes rather than changing existing
5. **Keep Django admin CSS** - It provides useful form styling
