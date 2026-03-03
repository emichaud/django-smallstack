---
title: Theming & Customization
description: Customize colors, dark mode, and components
---

# Theming & Customization

The {{ project_name }} theme is built on Django admin's CSS foundation with custom CSS variables for easy customization and automatic dark/light mode support.

## Key Files

| File | Purpose |
|------|---------|
| `static/css/theme.css` | Main theme CSS with all custom properties |
| `static/js/theme.js` | Dark mode toggle and UI interactions |
| `templates/admin_theme/base.html` | Master layout template |
| `templates/admin_theme/includes/` | Reusable template partials |

## Changing Colors

All colors are defined as CSS custom properties in `static/css/theme.css`. To customize:

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

## Dark/Light Mode

### How It Works

1. Theme preference is stored in `localStorage` as `admin-starter-theme`
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

Edit `templates/admin_theme/includes/sidebar.html`:

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

## Swapping CSS Frameworks

To use Bootstrap, Tailwind, or another framework:

### Step 1: Remove Current CSS

In `templates/admin_theme/base.html`:

```html
<!-- Remove or comment out -->
<link rel="stylesheet" href="{% static 'admin/css/base.css' %}">
<link rel="stylesheet" href="{% static 'css/theme.css' %}">
```

### Step 2: Add Your Framework

```html
<link href="https://cdn.example.com/framework.css" rel="stylesheet">
```

### Step 3: Update Component Classes

Update HTML classes in templates to match your framework's conventions.

### Step 4: Update Dark Mode

If your framework has its own dark mode system, update `static/js/theme.js` accordingly.

## Best Practices

1. **Use CSS Variables** - Always use variables instead of hard-coded colors
2. **Test Both Themes** - Always test changes in light and dark modes
3. **Mobile First** - Test on mobile screens; the theme is responsive
4. **Extend, Don't Override** - Add new classes rather than overriding existing ones
5. **Keep Admin CSS** - Django admin CSS provides useful form styling
