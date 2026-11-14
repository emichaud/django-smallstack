---
title: Theming & Customization
description: Customize colors, dark mode, and components
---

# Theming & Customization

The {{ project_name }} theme is built on Django admin's CSS foundation with custom CSS variables for easy customization and automatic dark/light mode support.

## First: which "theme" job are you doing?

"Theme" is an overloaded word, so pin down your goal before you dig in — the three jobs live in three different docs, and reading the wrong one is the main reason theming feels confusing.

| Your goal | The job | Read |
|---|---|---|
| Change the accent **colors** — add a brand palette or tune an existing one | **Palette** | [`docs/skills/modify-palettes.md`](../../../docs/skills/modify-palettes.md) |
| Build **new pages/components** that match the built-in admin look | **Consume the theme** | [`docs/skills/modern-dark-theme.md`](../../../docs/skills/modern-dark-theme.md) |
| Ship your **own** look — Bootstrap, Tailwind, a bespoke base template | **Bring your own** | [`docs/skills/adding-your-own-theme.md`](../../../docs/skills/adding-your-own-theme.md) |

The positioning behind those three: SmallStack's theme is a **batteries-included admin skin for people who don't want to build one** — Django-admin app builders, and headless/API builders who still want a management UI without hand-rolling it. Adopt it and topbar, sidebar, dark mode, and the six palettes come for free. If you already have a design system, you don't rip ours out — you mount yours **alongside** (the bring-your-own path), and the built-in pages (Activity, Status, Backups, Users, Help) keep their skin.

Everything below is the **reference** for that built-in theme — its colors, variables, and branding.

> **As of v0.9.x SmallStack ships a modern-dark theme system** with six palettes (Django, Blue, Purple/default, Orange, Contrast, Gold), cool-biased near-black surfaces, and vibrant Tailwind-style accents. For the design philosophy behind the new defaults, read [`theme-architecture.md`](theme-architecture.md). For the variable values per palette, read [`theme-color-reference.md`](theme-color-reference.md). To switch palettes as a user, use the swatch grid in the user-menu dropdown (avatar in top-right).

## Key Files

| File | Purpose |
|------|---------|
| `static/smallstack/css/core.css` | All the custom properties (design tokens), imported by `theme.css` |
| `static/smallstack/css/theme.css` | Main theme CSS: layout and the page shell |
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
# config/settings/smallstack.py
BRAND_NAME = "My Project"
BRAND_LOGO_TEXT = "brand/my-logo-text.svg"  # Topbar (32px height)
```

For complete branding documentation including logo specifications and asset creation, see the [Customization Guide](/smallstack/help/smallstack/customization/#customizing-branding).

## The Logo Follows the Palette

The stock SmallStack logo is drawn from the theme, so it changes with the palette and with
dark or light mode: the four-square mark and the word *SmallStack* take the palette's accent.
You see it in the top bar and on the sign-in pages. Switch palette from the user menu and the
logo changes with everything else.

A project that sets its own `BRAND_LOGO_TEXT` (or `BRAND_LOGO` and `BRAND_LOGO_DARK`) keeps its
own image, in its own colours.

For anywhere outside the app (a README, a slide, an email) the same logo ships as files, one set
for each palette, in `static/smallstack/brand/palettes/`:

<table>
<thead><tr><th scope="col">Palette</th><th scope="col">On a dark background</th><th scope="col">On a light background</th></tr></thead>
<tbody>
<tr><th scope="row">Django</th><td style="background:#0d1117;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-django-dark.svg" alt="Django logo for a dark background" height="34"></td><td style="background:#ffffff;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-django-light.svg" alt="Django logo for a light background" height="34"></td></tr>
<tr><th scope="row">Blue</th><td style="background:#0d1117;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-dark-blue-dark.svg" alt="Blue logo for a dark background" height="34"></td><td style="background:#ffffff;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-dark-blue-light.svg" alt="Blue logo for a light background" height="34"></td></tr>
<tr><th scope="row">Purple</th><td style="background:#0d1117;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-purple-dark.svg" alt="Purple logo for a dark background" height="34"></td><td style="background:#ffffff;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-purple-light.svg" alt="Purple logo for a light background" height="34"></td></tr>
<tr><th scope="row">Orange</th><td style="background:#0d1117;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-orange-dark.svg" alt="Orange logo for a dark background" height="34"></td><td style="background:#ffffff;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-orange-light.svg" alt="Orange logo for a light background" height="34"></td></tr>
<tr><th scope="row">Contrast</th><td style="background:#0d1117;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-high-contrast-dark.svg" alt="Contrast logo for a dark background" height="34"></td><td style="background:#ffffff;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-high-contrast-light.svg" alt="Contrast logo for a light background" height="34"></td></tr>
<tr><th scope="row">Gold</th><td style="background:#0d1117;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-gold-dark.svg" alt="Gold logo for a dark background" height="34"></td><td style="background:#ffffff;padding:10px 14px;"><img src="/static/smallstack/brand/palettes/logo-gold-light.svg" alt="Gold logo for a light background" height="34"></td></tr>
</tbody>
</table>

Each palette has four files: `logo-<palette>-dark.svg` and `logo-<palette>-light.svg` (the mark
and the name), and `icon-<palette>-dark.svg` and `icon-<palette>-light.svg` (the mark alone).
After adding or retuning a palette, `uv run python manage.py brand_logos` writes them again from
the palette's colours.

## Changing Colors

All colors are defined as CSS custom properties in `static/smallstack/css/core.css`. To customize:

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
# config/settings/smallstack.py (or in .env)
SMALLSTACK_COLOR_PALETTE = "purple"
```

Options: `django`, `light-blue`, `dark-blue`, `orange`, `purple`

### Per-User Override

Authenticated users can choose their own palette on the **Profile Edit** page. A swatch selector shows all available palettes with preview colors. The user's choice overrides the system default and persists across sessions.

If a user clears their selection (sets it to blank), they fall back to the system default.

### Palette Precedence

The effective palette is resolved in this order (first match wins):

1. **User profile override** — saved on the Profile Edit page (`color_palette` field)
2. **Browser localStorage** — key `smallstack-palette` (persists anonymous choices, can be stale)
3. **System default** — `SMALLSTACK_COLOR_PALETTE` setting (default: `django`)

For authenticated users, the profile choice is synced to localStorage automatically, so these stay aligned. After changing the system default, anonymous users (or users without a profile override) may still see the old palette until their browser localStorage is cleared.

The Profile Edit page also lets users set their **timezone**, which controls how dates and times are displayed throughout the site. See [Working with Timezones](/smallstack/help/smallstack/timezones/) for details.

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

Register it from your app's `AppConfig.ready()`; don't edit `sidebar.html`, which is SmallStack's and is replaced on every upgrade. The registry orders the link, hides it from people who can't open the page, and puts it in the sidebar and the topbar:

```python
# apps/myapp/apps.py
from django.apps import AppConfig


class MyAppConfig(AppConfig):
    name = "apps.myapp"

    def ready(self):
        from apps.smallstack.navigation import nav

        nav.register(
            section="main",            # or "resources", "admin"
            label="Your Page",
            url_name="myapp:index",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="..."/></svg>',
            order=20,
            auth_required=True,        # staff_required=True for staff-only pages
        )
```

Sections and submenus: [Navigation](/smallstack/help/smallstack/navigation/).

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

> **Step-by-step guide:** See [Adding Your Own Theme](/smallstack/help/smallstack/adding-your-own-theme/) for a complete tutorial with code examples, including how to preserve access to SmallStack admin apps from your custom navbar.

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

## User Preferences Summary

The Profile Edit page groups three user-level preferences that affect the entire UI. Each has a system default that applies when the user hasn't made a choice:

| Preference | System Default Setting | Profile Field | Fallback |
|------------|----------------------|---------------|----------|
| **Theme** (dark/light) | Browser `prefers-color-scheme` | `theme_preference` | Dark |
| **Color palette** | `SMALLSTACK_COLOR_PALETTE` | `color_palette` | `django` |
| **Timezone** | `TIME_ZONE` | `timezone` | `America/New_York` |

All three follow the same pattern: system default → user override → persisted on profile. Theme and palette are applied via `data-theme` and `data-palette` attributes on `<html>`. Timezone is activated per-request by `TimezoneMiddleware`.

When a user's timezone differs from the server timezone, dates display with a dotted underline and a hover tooltip showing the server time and UTC. See [Working with Timezones](/smallstack/help/smallstack/timezones/) for the full architecture.

## Best Practices

1. **Use CSS Variables** - Always use variables instead of hard-coded colors
2. **Test Both Themes** - Always test changes in light and dark modes
3. **Mobile First** - Test on mobile screens; the theme is responsive
4. **Extend, Don't Override** - Add new classes rather than overriding existing ones
5. **Keep Admin CSS** - Django admin CSS provides useful form styling

## Troubleshooting

### Palette default not applying

If you changed `SMALLSTACK_COLOR_PALETTE` but the UI still shows the old palette:

1. **Restart the dev server** — settings and `.env` changes require a server restart. Template and CSS changes hot-reload, but Python settings do not.
2. **Check user profile** — if you're logged in, your profile palette override takes priority over the system default. Set it to "System Default" on the Profile Edit page to fall back.
3. **Clear browser localStorage** — open DevTools → Application → Local Storage → delete `smallstack-palette`. This can hold a stale value from a previous session.
4. **Verify the palette ID** — valid options: `django`, `light-blue`, `dark-blue`, `orange`, `purple`.
