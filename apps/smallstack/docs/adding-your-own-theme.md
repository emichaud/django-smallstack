---
title: Adding Your Own Theme
description: Add a custom CSS framework alongside SmallStack's built-in theme
---

# Adding Your Own Theme

{{ project_name }} ships with a complete theme — topbar, sidebar, cards, dark mode, palettes. That theme powers all the built-in apps: Activity, Status, Backups, User Manager, Help, and Profile.

You don't need to rewrite those pages. Instead, add your own theme **alongside** SmallStack's. Your new pages use your theme. SmallStack's built-in pages keep using `smallstack/base.html`. Both themes share dark mode, palettes, and authentication — users move between them seamlessly.

```
┌──────────────────────────────────────────────────┐
│  Your Custom Theme (mytheme/base.html)           │
│  ├── Homepage, dashboards, public pages          │
│  └── Anything you build in apps/website/         │
├──────────────────────────────────────────────────┤
│  SmallStack Theme (smallstack/base.html)         │
│  ├── Activity dashboard     (/activity/)         │
│  ├── Status / Heartbeat     (/status/)           │
│  ├── Backups                (/backups/)           │
│  ├── User Manager           (/manage/users/)     │
│  ├── Help & Docs            (/help/)             │
│  ├── Profile                (/profile/)          │
│  └── Django Admin           (/admin/)            │
└──────────────────────────────────────────────────┘
```

## Where Your Pages Go

SmallStack has a designated app for project-specific pages: `apps/website/`. This is the conflict-free zone for your custom pages.

```
apps/website/
├── urls.py          # Your routes (mounted at /)
├── views.py         # Your views
└── templates/
    └── website/     # Your page templates
```

**Best practice:** New pages go in `apps/website/`. New templates go in `templates/website/`. Your custom base template goes in `templates/mytheme/` (or whatever you name it). Website pages extend your custom base.

For more on the conflict-free zones, see the [Customization Guide](/help/smallstack/customization/#conflict-free-zones).

## Step 1: Create the Theme Directory

Create a directory for your theme's base template and partials:

```bash
mkdir -p templates/mytheme/includes
```

Your template tree will look like this:

```
templates/
├── smallstack/              # DON'T TOUCH — upstream SmallStack theme
│   ├── base.html
│   └── includes/
│       ├── topbar.html
│       ├── sidebar.html
│       └── ...
├── mytheme/                 # YOUR NEW THEME
│   ├── base.html
│   └── includes/
│       └── navbar.html
└── website/                 # YOUR PAGES (extend mytheme/base.html)
    ├── home.html
    └── dashboard.html
```

## Step 2: Create the Custom Base Template

Create `templates/mytheme/base.html`. This is the foundation all your custom pages will extend.

There are three **required** pieces that must be present for dark mode, palettes, and `theme.js` to work. They're marked with `REQUIRED` comments below.

```html
{% load static theme_tags %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{% endblock %} | {{ brand.name }}</title>

    <!-- ============================================================
         REQUIRED: Blocking theme script — prevents flash of wrong theme.
         This MUST be in <head> before any stylesheets load.
         Copy this verbatim — it reads localStorage and sets data-theme
         and data-palette on <html> before the browser paints.
         ============================================================ -->
    <script>
    (function() {
        var theme = localStorage.getItem('smallstack-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', theme);
        var palette = localStorage.getItem('smallstack-palette') || '{{ color_palette }}';
        if (palette && palette !== 'django') {
            document.documentElement.setAttribute('data-palette', palette);
        }
    })();
    </script>

    <!-- Favicon -->
    <link rel="icon" type="image/x-icon" href="{% static brand.favicon %}">

    <!-- Your framework CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
          rel="stylesheet">

    <!-- SmallStack palette CSS — gives you palette color variables -->
    <link rel="stylesheet" href="{% static 'smallstack/css/palettes.css' %}">

    <!-- Your custom overrides (created in step 3) -->
    <link rel="stylesheet" href="{% static 'css/mytheme.css' %}">

    {% block extra_css %}{% endblock %}
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>

    {% include "mytheme/includes/navbar.html" %}

    <main class="container-fluid py-4">
        {% block breadcrumbs %}{% endblock %}

        <!-- Reuse SmallStack's flash messages — they're framework-agnostic -->
        {% include "smallstack/includes/messages.html" %}

        {% block content %}{% endblock %}
    </main>

    <footer class="container-fluid py-3 mt-auto border-top"
            style="border-color: var(--card-border) !important;">
        <div class="d-flex justify-content-between text-muted small">
            <span>&copy; {% now "Y" %} {{ brand.name }}</span>
            <span>
                {% if user.is_staff %}
                <a href="{% url 'activity:dashboard' %}"
                   style="color: var(--link-color);">Admin</a>
                {% endif %}
            </span>
        </div>
    </footer>

    <!-- ============================================================
         REQUIRED: window.SMALLSTACK config object.
         Must come BEFORE theme.js. Provides theme.js with the
         current user's saved preferences.
         ============================================================ -->
    <script>
        window.SMALLSTACK = {
            userTheme: {% if user.is_authenticated and user.profile %}'{{ user.profile.theme_preference }}'{% else %}null{% endif %},
            userPalette: {% if user.is_authenticated and user.profile %}'{{ user.profile.color_palette }}'{% else %}null{% endif %},
            colorPalette: '{{ color_palette }}',
            isAuthenticated: {% if user.is_authenticated %}true{% else %}false{% endif %},
            sidebarEnabled: false,
            sidebarOpen: false,
            topbarNavEnabled: false
        };
    </script>

    <!-- ============================================================
         REQUIRED: SmallStack theme.js — handles dark mode toggle,
         palette switching, and profile sync for authenticated users.
         ============================================================ -->
    <script src="{% static 'smallstack/js/theme.js' %}"></script>

    <!-- htmx — needed if you use hx-get, hx-post, etc. -->
    <script src="{% static 'smallstack/js/htmx.min.js' %}" defer></script>

    <!-- Your framework JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
            defer></script>

    {% block extra_js %}{% endblock %}
</body>
</html>
```

> **CDN vs local:** CDN stylesheet and font links work out of the box — SmallStack's CSP allows external styles, fonts, and images over HTTPS. However, **CDN script tags are blocked** by default (scripts are restricted to `'self'` to prevent XSS). For Bootstrap JS or other third-party scripts, either download them locally into `static/mytheme/` or add the CDN origin to `script-src` in `config/settings/base.py`.

### Why These Three Pieces Are Required

| Piece | What Happens Without It |
|-------|------------------------|
| **Blocking `<script>` in `<head>`** | Flash of wrong theme (FOUC) — page briefly shows light mode then snaps to dark, or vice versa |
| **`window.SMALLSTACK` object** | `theme.js` throws JavaScript errors, dark mode toggle and palette switching break |
| **`theme.js`** | No dark mode toggle, no palette switching, no profile sync for authenticated users |

For the full technical details on the persistence mechanism, see [Theming & Customization — Dark/Light Mode](/help/smallstack/theming/#darklight-mode).

## Step 3: Create Your Theme's CSS Override File

Create `static/css/mytheme.css`. This file bridges your framework's styling with SmallStack's dark mode and palette system.

SmallStack sets `data-theme="dark"` or `data-theme="light"` on the `<html>` element. Use these selectors to adapt your framework's look:

```css
/*
 * mytheme.css — Dark mode and palette integration for Bootstrap.
 */

/* ── Dark mode ──────────────────────────────────── */

[data-theme="dark"] body {
    background-color: var(--body-bg, #121212);
    color: var(--body-fg, #f5f5f5);
}

[data-theme="dark"] .navbar {
    background-color: var(--primary, #44b78b) !important;
}

[data-theme="dark"] .card {
    background-color: var(--card-bg, #212121);
    border-color: var(--card-border, #3d3d3d);
    color: var(--body-fg, #f5f5f5);
}

[data-theme="dark"] .text-muted {
    color: var(--text-muted, #b0b0b0) !important;
}

[data-theme="dark"] a:not(.btn):not(.nav-link):not(.navbar-brand) {
    color: var(--link-color, #81d4fa);
}

/* ── Light mode ─────────────────────────────────── */

[data-theme="light"] body {
    background-color: var(--body-bg, #f7f7f7);
    color: var(--body-fg, #333333);
}

[data-theme="light"] .navbar {
    background-color: var(--primary, #417690) !important;
}

/* ── Palette-aware accent color ─────────────────── */
/* var(--primary) automatically changes with the active palette,
   so anything using it adapts without extra selectors. */

.btn-primary {
    background-color: var(--primary) !important;
    border-color: var(--primary) !important;
}

.btn-primary:hover {
    background-color: var(--primary-hover) !important;
    border-color: var(--primary-hover) !important;
}

```

The key insight: use SmallStack's CSS variables (`var(--body-bg)`, `var(--card-bg)`, `var(--primary)`, etc.) instead of hardcoding colors. This way your theme automatically adapts to dark mode and palette changes. See [Theming & Customization — Available CSS Variables](/help/smallstack/theming/#available-css-variables) for the full list.

## Step 4: Create Your Navbar Partial

Create `templates/mytheme/includes/navbar.html`:

```html
{% load static theme_tags %}
<nav class="navbar navbar-expand-lg navbar-dark" style="background: var(--primary);">
    <div class="container-fluid">
        <a class="navbar-brand" href="{% url 'website:home' %}">{{ brand.name }}</a>

        <button class="navbar-toggler" type="button"
                data-bs-toggle="collapse" data-bs-target="#navMain">
            <span class="navbar-toggler-icon"></span>
        </button>

        <div class="collapse navbar-collapse" id="navMain">
            <ul class="navbar-nav me-auto">
                <li class="nav-item">
                    <a class="nav-link {% nav_active 'website:home' %}"
                       href="{% url 'website:home' %}">Home</a>
                </li>
                {% if user.is_authenticated %}
                <li class="nav-item">
                    <a class="nav-link {% nav_active 'website:about' %}"
                       href="{% url 'website:about' %}">About</a>
                </li>
                {% endif %}
            </ul>

            <ul class="navbar-nav">
                {% if user.is_authenticated %}
                <!-- Link to SmallStack admin pages -->
                {% if user.is_staff %}
                <li class="nav-item dropdown">
                    <a class="nav-link dropdown-toggle" href="#"
                       data-bs-toggle="dropdown">Admin</a>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><a class="dropdown-item"
                               href="{% url 'activity:dashboard' %}">Activity</a></li>
                        <li><a class="dropdown-item"
                               href="{% url 'heartbeat:dashboard' %}">Status</a></li>
                        <li><a class="dropdown-item"
                               href="{% url 'smallstack:backups' %}">Backups</a></li>
                        <li><a class="dropdown-item"
                               href="{% url 'manage/users-list' %}">Users</a></li>
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item"
                               href="{% url 'admin:index' %}">Django Admin</a></li>
                    </ul>
                </li>
                {% endif %}

                <li class="nav-item">
                    <a class="nav-link" href="{% url 'profile' %}">Profile</a>
                </li>
                <li class="nav-item">
                    <!-- theme.js finds this by id and wires up the toggle -->
                    <button id="theme-toggle"
                            class="btn btn-outline-light btn-sm ms-2">
                        Dark/Light
                    </button>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="{% url 'logout' %}">Logout</a>
                </li>
                {% else %}
                <li class="nav-item">
                    <a class="nav-link" href="{% url 'login' %}">Login</a>
                </li>
                {% endif %}
            </ul>
        </div>
    </div>
</nav>
```

Notice the **Admin dropdown** — this gives staff users quick access to SmallStack's built-in apps (Activity, Status, Backups, Users) without needing the sidebar. When they click those links, they'll land on pages using the SmallStack theme. That's expected and by design — those are operational/admin pages that SmallStack maintains.

## Step 5: Update Your Homepage

Edit `templates/website/home.html` to extend your new base instead of SmallStack's:

```html
{% extends "mytheme/base.html" %}
{% load static %}

{% block title %}Home{% endblock %}

{% block content %}
<div class="row">
    <div class="col-lg-8 mx-auto">
        <div class="card shadow-sm"
             style="background: var(--card-bg); border-color: var(--card-border);">
            <div class="card-body text-center py-5">
                <h1 style="color: var(--body-fg);">Welcome to {{ brand.name }}</h1>
                <p class="lead" style="color: var(--text-muted);">
                    This page uses your custom Bootstrap theme.
                </p>
                {% if not user.is_authenticated %}
                <a href="{% url 'login' %}" class="btn btn-primary btn-lg">
                    Get Started
                </a>
                {% endif %}
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

## Step 6: Verify Everything Works

Start the dev server and check both themes:

```bash
make run
```

**Check your custom theme pages:**

| URL | What You Should See |
|-----|-------------------|
| `http://localhost:8005/` | Your homepage with Bootstrap layout and custom navbar |
| Toggle the Dark/Light button | Theme switches instantly, no flash on reload |
| Profile > change palette | Colors update across the navbar and buttons |

**Check SmallStack admin pages still work** (log in as staff):

| URL | What You Should See |
|-----|-------------------|
| `/activity/` | Activity dashboard with SmallStack sidebar |
| `/status/` | Status/Heartbeat dashboard |
| `/backups/` | Backup manager |
| `/manage/users/` | User manager |
| `/help/` | Help & documentation |
| `/profile/` | Profile edit (theme, palette, timezone) |

**Verify dark mode persists across both themes:**

1. Set dark mode on your custom homepage
2. Navigate to `/activity/` (SmallStack theme) — should also be dark
3. Toggle to light on the activity page
4. Go back to `/` — should also be light

This works because both bases read from the same `localStorage` keys (`smallstack-theme` and `smallstack-palette`).

## Step 7: Vendor Assets for Production

Before deploying, download the CDN files and serve them locally:

```bash
mkdir -p static/mytheme/css static/mytheme/js

curl -o static/mytheme/css/bootstrap.min.css \
  https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css

curl -o static/mytheme/js/bootstrap.bundle.min.js \
  https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js
```

Then update your base template to use the local paths:

```html
<!-- Before (CDN) — fine for development: -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
      rel="stylesheet">

<!-- After (local) — required for production: -->
<link rel="stylesheet" href="{% static 'mytheme/css/bootstrap.min.css' %}">
```

### Where Static Files Go

```
static/
├── smallstack/          # NEVER MODIFY — upstream SmallStack assets
│   ├── css/
│   │   ├── theme.css
│   │   └── palettes.css
│   └── js/
│       ├── theme.js
│       └── htmx.min.js
├── css/                 # Your small overrides
│   └── mytheme.css
├── mytheme/             # Vendored framework files
│   ├── css/
│   │   └── bootstrap.min.css
│   └── js/
│       └── bootstrap.bundle.min.js
└── brand/               # Your logo, favicon, social image
```

## Adding More Pages

All new pages follow the same pattern — view, URL, template extending your base.

### Add a View

Edit `apps/website/views.py`:

```python
def dashboard_view(request):
    return render(request, "website/dashboard.html")
```

### Add a URL

Edit `apps/website/urls.py`:

```python
urlpatterns = [
    path("", views.home_view, name="home"),
    path("about/", views.about_view, name="about"),
    path("dashboard/", views.dashboard_view, name="dashboard"),  # new
]
```

### Add a Template

Create `templates/website/dashboard.html`:

```html
{% extends "mytheme/base.html" %}
{% load theme_tags %}

{% block title %}Dashboard{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Dashboard" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="row g-4">
    <div class="col-md-4">
        <div class="card"
             style="background: var(--card-bg); border-color: var(--card-border);">
            <div class="card-body">
                <h5 style="color: var(--body-fg);">Users</h5>
                <p class="display-6" style="color: var(--primary);">42</p>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card"
             style="background: var(--card-bg); border-color: var(--card-border);">
            <div class="card-body">
                <h5 style="color: var(--body-fg);">Tasks</h5>
                <p class="display-6" style="color: var(--primary);">7</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

SmallStack template tags like `{% breadcrumb %}` and `{% render_breadcrumbs %}` work in your custom theme. The breadcrumb markup uses Bootstrap-compatible classes (`<ol class="breadcrumb">` + `<li class="breadcrumb-item">`), so Bootstrap themes get styled breadcrumbs automatically.

## Linking to SmallStack Apps

Staff users need access to SmallStack's admin apps. Two approaches:

### Admin Dropdown in Your Navbar (Recommended)

This is what the navbar in Step 4 uses. A dropdown menu lists SmallStack admin pages. When users click them, they transition to the SmallStack theme — that's expected for admin/ops pages.

### Footer Admin Link (Simpler)

Put a single link in your footer that takes staff to the activity dashboard (which has the sidebar with all links):

```html
{% if user.is_staff %}
<a href="{% url 'activity:dashboard' %}">Admin Dashboard</a>
{% endif %}
```

### SmallStack App URL Reference

| App | URL Name | Path | Access |
|-----|----------|------|--------|
| Activity | `activity:dashboard` | `/activity/` | Staff |
| Status | `heartbeat:dashboard` | `/status/` | Staff |
| Backups | `smallstack:backups` | `/backups/` | Staff |
| User Manager | `manage/users-list` | `/manage/users/` | Staff |
| Help & Docs | `help:index` | `/help/` | All users |
| Profile | `profile` | `/profile/` | Authenticated |
| Django Admin | `admin:index` | `/admin/` | Staff |

## How the Two Themes Coexist

Understanding the routing helps when things don't work as expected:

```
User visits /                  → apps/website/urls.py
                               → views.home_view
                               → templates/website/home.html
                               → {% extends "mytheme/base.html" %}  ← YOUR THEME

User visits /activity/         → apps/activity/urls.py
                               → views.dashboard
                               → templates/activity/dashboard.html
                               → {% extends "smallstack/base.html" %}  ← SMALLSTACK
```

**What's shared** between both bases:

- Dark mode — same `localStorage` key (`smallstack-theme`), same `data-theme` attribute
- Palettes — same `localStorage` key (`smallstack-palette`), same `data-palette` attribute
- Authentication — same Django session, same user object
- `theme.js` — same script handles toggle buttons on both bases
- Template tags — `{% breadcrumb %}`, `{% nav_active %}`, `{% render_breadcrumbs %}`

**What's different:**

- Layout — your theme uses its own navbar/grid; SmallStack uses topbar + sidebar
- CSS — your theme loads Bootstrap (or Tailwind, etc.); SmallStack loads `theme.css`
- Navigation — your theme has its own nav; SmallStack apps use the sidebar

## What NOT to Do

**Don't override SmallStack app templates.** Don't create `templates/activity/dashboard.html` to restyle the activity page with Bootstrap. Those pages are maintained upstream and will conflict on updates.

**Don't modify `templates/smallstack/base.html`.** That's the upstream base for SmallStack's built-in apps. If you change it, you'll get merge conflicts on every upstream pull.

**Don't reimplement dark mode.** If your purchased theme has its own dark mode JS, remove it. SmallStack's `theme.js` handles localStorage persistence, profile sync, and palette switching. Reimplementing breaks the persistence between themes.

**Don't put custom pages in other apps.** Keep all your project pages in `apps/website/`. This is the designated project-specific app that won't conflict with upstream. See the [Customization Guide](/help/smallstack/customization/) for the full list of conflict-free zones.

## Next Steps

- [Theming & Customization](/help/smallstack/theming/) — CSS variables reference, palettes, dark mode internals
- [Customization Guide](/help/smallstack/customization/) — Branding, documentation, conflict-free zones
- [Components](/help/smallstack/components/) — SmallStack's built-in UI components
- [Getting Started](/help/smallstack/getting-started/) — Initial project setup
