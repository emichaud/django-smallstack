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

Core layout and component variables are defined in `static/smallstack/css/theme.css`. Color variables that adapt to palettes (including `--body-quiet-color`) are defined in `static/smallstack/css/palettes.css`.

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

### Palette Precedence

The effective palette is resolved differently on the server and client, but they stay aligned for authenticated users.

**Server-side** — `_get_effective_palette()` in `context_processors.py`:

1. User profile `color_palette` (if set)
2. `SMALLSTACK_COLOR_PALETTE` setting (from `base.py` / `.env`)
3. `"django"` (hardcoded fallback)

**Client-side** — `getPreferredPalette()` in `theme.js`:

1. `window.SMALLSTACK.userPalette` (set from server-resolved profile value)
2. `localStorage('smallstack-palette')` (persists anonymous choices)
3. `window.SMALLSTACK.colorPalette` (system default from context)
4. `"django"` (hardcoded fallback)

For authenticated users, JS priority 1 (`userPalette`) is the server-resolved value, so server and client stay in sync. For anonymous users or after a settings change, `localStorage` can hold a stale value from a previous session.

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

> **Restart required:** `settings.py` and `.env` changes require a dev server restart to take effect. Template and CSS file changes hot-reload in development, but Python settings do not.

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

You can add a second CSS framework (Bootstrap, Tailwind, Tabler) alongside SmallStack's default theme. Your custom pages use your theme; SmallStack's built-in apps (Activity, Status, Backups, User Manager, Help) keep using `smallstack/base.html`.

> **Full guide:** See [adding-your-own-theme.md](adding-your-own-theme.md) for a step-by-step tutorial with complete code examples, including how to preserve access to SmallStack admin apps from your custom navbar.

Two common patterns:

**Pattern A — Single file in your app's template directory** (simple):
1. Create `templates/website/base_bootstrap.html` — loads the new framework's CSS/JS
2. New pages extend it: `{% extends "website/base_bootstrap.html" %}`

**Pattern B — Theme directory with its own partials** (for larger themes):
1. Create `templates/mytheme/base.html` + `templates/mytheme/includes/` for framework-specific partials
2. New pages extend it: `{% extends "mytheme/base.html" %}`

In both cases, existing SmallStack pages continue using `templates/smallstack/base.html` unchanged. All new project pages go in `apps/website/` — the designated project-specific app.

### Required Pieces for a Custom Base Template

Your parallel base must include three things for dark mode and palettes to work:

1. **Blocking `<script>` in `<head>`** — reads `localStorage` and sets `data-theme`/`data-palette` on `<html>` before CSS renders (prevents FOUC)
2. **`window.SMALLSTACK` config object** — placed before `theme.js`, provides user preferences
3. **`theme.js`** — handles dark mode toggle, palette switching, and profile sync

See [adding-your-own-theme.md](adding-your-own-theme.md) for the exact code to copy into your base template.

### Dark Mode Persistence Contract

Both themes share the same localStorage keys, so dark mode and palette choices persist as users navigate between your pages and SmallStack admin pages:

| localStorage Key | HTML Attribute | Purpose |
|-----------------|---------------|---------|
| `smallstack-theme` | `data-theme` on `<html>` | Controls light/dark CSS variables |
| `smallstack-palette` | `data-palette` on `<html>` | Controls color palette CSS variables |
| `smallstack-sidebar-closed` | Class `sidebar-will-close` on `<html>` | Sidebar initial state (SmallStack pages only) |

### Porting a Tailwind or React Theme

When adapting a Tailwind template or React dashboard, map framework-specific patterns to SmallStack equivalents:

| Tailwind Class | SmallStack Equivalent | Notes |
|---------------|----------------------|-------|
| `bg-gray-900` / `bg-white` | `background: var(--body-bg)` | Adapts to light/dark automatically |
| `bg-gray-800` / `bg-gray-50` | `background: var(--card-bg)` | Card and panel backgrounds |
| `text-gray-100` / `text-gray-900` | `color: var(--body-fg)` | Primary text color |
| `bg-blue-600` | `background: var(--primary)` | Adapts to palette |
| `border-gray-700` / `border-gray-200` | `border-color: var(--card-border)` | Adapts to light/dark |
| `text-blue-500` | `color: var(--link-color)` | Link color, adapts to palette |

For Tailwind `dark:` classes, use `[data-theme="dark"]` selectors — or better, just use CSS variables that adapt automatically. For React components, extract JSX into Django template partials and replace `useState`/`useEffect` data fetching with htmx. See [adding-your-own-theme.md](adding-your-own-theme.md) for detailed guidance.

## Tables

SmallStack has a standard table style that works across light mode, dark mode, and all color palettes. **Always use it.** Do not write custom table CSS — it will look wrong in at least one theme mode.

### The Standard: `.crud-table`

The shared stylesheet lives at `templates/smallstack/crud/_table_styles.html`. Include it and use the `crud-table` class:

```html
{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}
{% endblock %}

{% block content %}
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
{% endblock %}
```

### What `.crud-table` provides

| Element | Style | How |
|---------|-------|-----|
| Header row | Tinted background | `color-mix(in srgb, var(--primary) 15%, var(--body-bg))` |
| Header text | Uppercase, muted | `0.8rem`, `600 weight`, `var(--body-quiet-color)` |
| Odd rows | Subtle tint | `color-mix(in srgb, var(--primary) 4%, var(--body-bg))` |
| Even rows | Slightly darker tint | `color-mix(in srgb, var(--primary) 12%, var(--body-bg))` |
| Hover | Highlighted | `color-mix(in srgb, var(--primary) 20%, var(--body-bg))` |
| Links | Primary color | `var(--primary)`, underline on hover |
| Borders | None | All borders explicitly removed with `!important` |
| Cell padding | Consistent | `10px 16px` for all `th` and `td` |

### Why it works in all themes

Every color is derived from `var(--primary)` and `var(--body-bg)` using `color-mix()`. When the user switches between light/dark mode or changes their color palette, the table automatically adapts — no separate dark mode overrides needed.

### Common mistakes

**Don't do this:**
```html
<!-- Custom table with hardcoded colors — breaks in dark mode -->
<table style="width: 100%; border-collapse: collapse;">
    <thead>
        <tr style="background: #f5f5f5;">  <!-- White header in dark mode -->
```

**Don't do this either:**
```css
/* Custom table class that duplicates crud-table behavior */
.my-table thead tr {
    background: var(--card-header-bg);  /* Wrong variable — too light in dark mode */
}
.my-table td {
    border-bottom: 1px solid var(--hairline-color);  /* crud-table uses no borders */
}
```

**Do this:**
```html
{% include "smallstack/crud/_table_styles.html" %}
<table class="crud-table">...</table>
```

### When you need custom table styling

If a page needs table styling that differs from `crud-table` (e.g., a modal with a denser layout), derive your colors the same way:

```css
.my-dense-table thead tr {
    background-color: color-mix(in srgb, var(--primary) 15%, var(--body-bg));
}
.my-dense-table tbody tr:nth-child(odd) {
    background-color: color-mix(in srgb, var(--primary) 4%, var(--body-bg));
}
.my-dense-table tbody tr:nth-child(even) {
    background-color: color-mix(in srgb, var(--primary) 12%, var(--body-bg));
}
```

Never use `var(--card-header-bg)`, `var(--card-bg)`, or hardcoded hex values for table backgrounds. The `color-mix()` pattern with `--primary` and `--body-bg` is what makes tables look correct across all theme combinations.

### CRUD views and django-tables2

Tables generated by `CRUDView` (via `{% crud_table %}`) and the explorer app already use `crud-table` automatically. If you're using `django-tables2` with `{% render_table %}`, the CRUD list template includes `_table_styles.html` and the table inherits the styles.

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

## User Preferences — Theme, Palette, and Timezone

The Profile Edit page groups three user-level preferences that affect the entire UI. Each has a system default that applies when the user hasn't made a choice:

| Preference | System Default Setting | Profile Field | Applied Via |
|------------|----------------------|---------------|-------------|
| Theme (dark/light) | Browser `prefers-color-scheme` | `theme_preference` | `data-theme` attribute on `<html>` |
| Color palette | `SMALLSTACK_COLOR_PALETTE` | `color_palette` | `data-palette` attribute on `<html>` |
| Timezone | `TIME_ZONE` | `timezone` | `TimezoneMiddleware` per request |

Theme and palette are visual — applied client-side via `data-*` attributes and CSS selectors. Timezone is server-side — activated per-request by middleware, affects how Django's `|date` filter renders datetimes.

### How Preferences Are Saved

- **Theme** — toggle in topbar sends `POST /profile/theme/` via htmx
- **Palette** — swatch selector on Profile Edit sends `POST /profile/palette/` via htmx
- **Timezone** — dropdown on Profile Edit, saved with the profile form

### Timezone Tooltip

When a user's timezone differs from the server timezone, all dates rendered with `{% localtime_tooltip %}` show a dotted underline and a CSS hover tooltip with the server time and UTC time.

The tooltip uses the `.tz-tip` class in `theme.css`:

```css
.tz-tip {
    position: relative;
    border-bottom: 1px dotted var(--body-quiet-color);
    cursor: help;
}
.tz-tip::after {
    content: attr(data-tz-server) "\A" attr(data-tz-utc);
    white-space: pre;
    position: absolute;
    bottom: calc(100% + 6px);
    left: 0;
    background: var(--card-bg);
    color: var(--body-quiet-color);
    border: 1px solid var(--hairline-color);
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 0.75rem;
    line-height: 1.6;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.tz-tip:hover::after {
    opacity: 1;
}
```

The tooltip is pure CSS — no JavaScript. It uses two `data-*` attributes (`data-tz-server`, `data-tz-utc`) combined with `"\A"` for a two-line stacked display. It inherits theme colors via `var(--card-bg)`, `var(--hairline-color)`, etc., so it works in both light and dark modes and all palettes.

See `docs/skills/timezones.md` for the full timezone architecture.

## Best Practices

1. **Use CSS variables** - Never hardcode colors
2. **Test both themes** - Always check light and dark modes
3. **Test multiple palettes** - Verify your components look good with different primary colors
4. **Mobile first** - Test on small screens
5. **Extend, don't override** - Add new classes rather than changing existing
6. **Keep Django admin CSS** - It provides useful form styling
7. **Use `var(--primary)` for branded elements** - They'll automatically adapt to palette changes
8. **Use `{% localtime_tooltip %}` for dates** - It inherits theme variables and works in all modes

## Troubleshooting

### Palette default not applying

If you changed `SMALLSTACK_COLOR_PALETTE` but the UI still shows the old palette:

1. **Restart the dev server** — `settings.py` and `.env` changes require a server restart. Template and CSS changes hot-reload in development, but Python settings do not.
2. **Check user profile override** — a user's profile `color_palette` takes priority over the system default. Set it to blank (empty string) to fall back to the system default.
3. **Clear browser localStorage** — open DevTools → Application → Local Storage → delete `smallstack-palette`. This key can hold a stale value from a previous session, especially for anonymous users.
4. **Verify the palette ID** — valid options: `django`, `high-contrast`, `dark-blue`, `orange`, `purple`. An invalid ID silently falls back to `django`.
5. **Check `data-palette` in DevTools** — inspect the `<html>` element and confirm the `data-palette` attribute matches what you expect.

### CDN stylesheets not applying

SmallStack's Content Security Policy (CSP) controls which external resources the browser will load. By default, CDN **stylesheets, fonts, and images** are allowed over HTTPS. CDN **scripts** are blocked (`script-src` is `'self'` only). If a CDN stylesheet isn't working, check the browser console for CSP violations. See `config/settings/base.py` for the full policy and [adding-your-own-theme.md](adding-your-own-theme.md#content-security-policy) for details.
