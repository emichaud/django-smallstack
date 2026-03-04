# Theming Guide

This guide explains how the SmallStack theme is structured and how to customize it.

## Theme Architecture

The theme is built on Django admin's existing CSS as a foundation, with custom CSS variables for easy customization and dark/light mode support.

### Key Files

| File | Purpose |
|------|---------|
| `static/css/theme.css` | Main theme CSS with all custom properties |
| `static/js/theme.js` | Dark mode toggle and UI interactions |
| `templates/smallstack/base.html` | Master layout template |
| `templates/smallstack/includes/` | Reusable template partials |

## CSS Custom Properties (Variables)

All colors and key measurements are defined as CSS custom properties in `static/css/theme.css`. This makes theme customization straightforward.

### Variable Naming Convention

Variables mirror Django admin naming where possible:
- `--primary` - Primary brand color
- `--secondary` - Secondary brand color
- `--body-bg` - Body background color
- `--body-fg` - Body foreground (text) color

### Changing Colors

To change the color scheme, edit the `:root` section in `static/css/theme.css`:

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
    /* ... more variables ... */
}
```

### Dark Mode Colors

Dark mode colors are defined in the `[data-theme="dark"]` selector:

```css
[data-theme="dark"] {
    --primary: #79aec8;
    --body-bg: #121212;
    --body-fg: #e0e0e0;
    /* ... more variables ... */
}
```

### Available Variables

**Colors:**
- `--primary`, `--primary-hover` - Primary brand colors
- `--secondary` - Secondary brand color
- `--accent` - Accent/highlight color
- `--body-bg`, `--body-fg` - Body background and foreground
- `--content-bg` - Content area background
- `--header-bg`, `--header-fg` - Header colors
- `--sidebar-*` - Sidebar-specific colors
- `--card-*` - Card component colors
- `--input-*` - Form input colors
- `--success-*`, `--warning-*`, `--error-*`, `--info-*` - Message colors
- `--button-*` - Button colors
- `--text-muted` - Muted text color
- `--link-color`, `--link-hover` - Link colors

**Spacing & Layout:**
- `--topbar-height` - Height of the top navigation bar
- `--sidebar-width` - Width of the sidebar
- `--sidebar-collapsed-width` - Width when sidebar is collapsed

**Effects:**
- `--shadow-sm`, `--shadow-md`, `--shadow-lg` - Box shadows
- `--transition-fast`, `--transition-normal` - Transition timing
- `--radius-sm`, `--radius-md`, `--radius-lg` - Border radius

## Dark/Light Mode

### How It Works

1. Theme preference is stored in `localStorage` under `smallstack-theme`
2. On page load, the theme is applied via `data-theme` attribute on `<html>`
3. CSS custom properties change based on the `data-theme` value
4. Users can toggle via the sun/moon icon in the top bar

### JavaScript API

The theme toggle is handled in `static/js/theme.js`:

```javascript
// Programmatically set theme
document.documentElement.setAttribute('data-theme', 'dark');

// Get current theme
const theme = document.documentElement.getAttribute('data-theme');
```

### System Preference Detection

The theme respects the user's system preference (`prefers-color-scheme`) when no explicit choice has been saved.

## Adding Navigation Items

### Sidebar Navigation

Edit `templates/smallstack/includes/sidebar.html`:

```html
<li class="nav-item">
    <a href="{% url 'your_url_name' %}" class="nav-link {% nav_active 'your_url_name' %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <!-- Your icon path here -->
        </svg>
        <span>Your Link</span>
    </a>
</li>
```

### Nav Section Titles

Add section dividers:

```html
<li class="nav-section-title">Section Name</li>
```

### Active State

Use the `{% nav_active 'url_name' %}` template tag to automatically add the `active` class when on that page.

## Template Tags

### Breadcrumbs

Available in `smallstack/templatetags/theme_tags.py`:

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

## Swapping to a Different CSS Framework

If you want to use a different CSS framework (Bootstrap, Tailwind, etc.):

### Step 1: Remove Current CSS

In `templates/smallstack/base.html`, remove or comment out:

```html
<link rel="stylesheet" href="{% static 'admin/css/base.css' %}">
<link rel="stylesheet" href="{% static 'css/theme.css' %}">
```

### Step 2: Add Your Framework

Add your framework's CSS:

```html
<link href="https://cdn.example.com/framework.css" rel="stylesheet">
```

Or for local files:

```html
<link rel="stylesheet" href="{% static 'css/your-framework.css' %}">
```

### Step 3: Update Component Classes

Update the HTML classes in template files to match your new framework's conventions.

### Step 4: Update Dark Mode

If your framework has its own dark mode system, update `static/js/theme.js` accordingly.

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

## Best Practices

1. **Use CSS Variables** - Always use the defined variables instead of hard-coded colors
2. **Test Both Themes** - Always test changes in both light and dark modes
3. **Mobile First** - The theme is responsive; test on mobile screens
4. **Extend, Don't Override** - Add new classes rather than overriding existing ones
5. **Keep Admin CSS** - The Django admin CSS provides useful form styling; keep it unless you're fully replacing the framework
