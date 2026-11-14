---
title: Customization Guide
description: Make SmallStack your own - customize pages, docs, and branding
---

# Customization Guide

SmallStack is designed to be forked and customized. This guide explains how to make it your own while still receiving upstream updates.

## Project Structure Overview

SmallStack separates "customize freely" areas from "core" areas:

```
apps/
├── website/         # CUSTOMIZE: Your project pages (home, about, etc.)
├── help/
│   ├── content/     # CUSTOMIZE: Your documentation (conflict-free)
│   │   ├── index.md
│   │   └── _config.yaml
│   └── smallstack/  # UPSTREAM: SmallStack reference docs (bundled)
├── profile/         # EXTEND: Add fields, customize templates
├── tasks/           # EXTEND: Add your background tasks
├── accounts/        # CORE: User model (extend carefully)
└── smallstack/     # CORE: Theme system (extend via CSS)

templates/
├── website/         # CUSTOMIZE: Your page templates
└── ...              # EXTEND: Override specific templates

config/
├── deploy.yml       # CUSTOMIZE: Your deployment config
└── settings/        # CUSTOMIZE: Your settings
```

## Customizing Your Homepage

The `apps/website/` app is your project's home. Customize it freely without worrying about upstream conflicts.

### How It Works

Your pages and SmallStack's are kept in different places, so pulling upstream doesn't conflict
with what you've written:

```
apps/
├── website/               # YOURS: the home view and urls, your own pages, chart card types
└── showcase/              # SmallStack's demo pages (about, getting started, starter, search…): delete it
templates/
├── website/
│   ├── base.html          # The public site's base (YOURS)
│   └── home.html          # Thin wrapper → smallstack/pages/home_content.html (YOURS)
└── 404.html               # Optional: YOUR error page (the defaults are in apps/smallstack/templates/)
```

`home.html` uses `{% include %}` to pull in SmallStack's default home content. When you're ready
to customize, **replace the include with your own markup**: the fragment in
`smallstack/pages/` stays untouched, so upstream updates never conflict with your page. The error
pages work the same way from the other side: SmallStack's 400/403/404/500 are app templates, and
a `templates/404.html` of your own takes precedence without upstream ever touching it.

### Edit the Homepage

Open `templates/website/home.html`. By default it looks like this:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags static %}

{% block title %}Home{% endblock %}
{% block breadcrumbs %}{% endblock %}

{% block content %}
{% include "smallstack/pages/home_content.html" %}
{% endblock %}
```

Replace the `{% include %}` with your own content:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Home{% endblock %}
{% block breadcrumbs %}{% endblock %}

{% block content %}
<div class="hero-section">
    <div class="hero-content">
        <h1 class="hero-title">My Project</h1>
        <p class="hero-subtitle">Your tagline here.</p>
    </div>
</div>

<div class="card">
    <div class="card-body">
        <p>Your content here.</p>
    </div>
</div>
{% endblock %}
```

SmallStack's other public pages (about, getting started, prompts, the two platform pages, the
starter pages, the public search) live in **`apps/showcase/`**, which isn't yours to edit: delete it
when you don't want them. That's three steps: the `apps/showcase/` directory, `"apps.showcase"` in
`INSTALLED_APPS` and its `include()` in `config/urls.py`. Nothing outside it links to it
unguarded (the public topbar and the home page reverse its URLs with `{% url … as x %}`, so the
links just go).

**Tip:** Use `{% block breadcrumbs %}{% endblock %}` to hide breadcrumbs on landing pages.

### Add More Pages

1. Create a view in `apps/website/views.py`:

```python
def pricing_view(request):
    return render(request, "website/pricing.html")
```

2. Add the URL in `apps/website/urls.py`:

```python
urlpatterns = [
    path("", views.home_view, name="home"),
    path("about/", views.about_view, name="about"),
    path("pricing/", views.pricing_view, name="pricing"),  # New
]
```

3. Create `templates/website/pricing.html`

### Update Branding

Edit `.env` to set your site name:

```bash
SITE_NAME=My Awesome App
SITE_DOMAIN=myapp.com
```

## Customizing Documentation

The help system loads docs from two separate locations:

- **`apps/help/content/`** - Your project's docs (conflict-free zone)
- **`apps/help/smallstack/`** - SmallStack reference docs (bundled, controlled by setting)

This separation means your docs never conflict with upstream updates.

### Hiding SmallStack Docs

SmallStack reference docs are shown by default. To hide them:

```python
# config/settings/smallstack.py (or in .env)
SMALLSTACK_DOCS_ENABLED = False
```

When disabled, SmallStack docs disappear from navigation and URLs return 404.

### Adding Your Own Documentation

Your docs live in `apps/help/content/`. Edit `_config.yaml` to define your structure:

```yaml
# apps/help/content/_config.yaml
title: "Documentation"

variables:
  version: "1.0.0"
  project_name: "My Project"

sections:
  # Root section (your main docs)
  - slug: ""
    title: "Project Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
      - slug: user-guide
        title: "User Guide"
        icon: "book"

  # Additional sections
  - slug: dev
    title: "Developer Docs"
    pages:
      - slug: api
        title: "API Reference"
        icon: "code"
```

Create the files:
```
apps/help/content/
├── _config.yaml
├── index.md           # /smallstack/help/index/
├── user-guide.md      # /smallstack/help/user-guide/
└── dev/
    └── api.md         # /smallstack/help/dev/api/
```

SmallStack docs automatically appear at `/smallstack/help/smallstack/*` when enabled.

### Writing Documentation Pages

Each `.md` file can have optional frontmatter:

```markdown
---
title: My Custom Title
description: A brief description for navigation
---

# Page Content

Your markdown content here. You can use:

- **Variables**: {{ project_name }} renders from _config.yaml
- **Links**: [Getting Started](/smallstack/help/smallstack/getting-started/)
- **Code blocks**: With syntax highlighting
- **Tables**: Standard markdown tables
```

### Editing the Welcome Page

The root `index.md` is your documentation home. Update it for your project:

```markdown
# Welcome to {{ project_name }}

Your project documentation lives here.

## Quick Links

- [User Guide](/smallstack/help/user-guide/) - Learn how to use the app
- [API Reference](/smallstack/help/dev/api/) - Developer documentation
- [SmallStack Docs](/smallstack/help/smallstack/readme/) - Framework reference
```

## Customizing Branding

SmallStack uses a settings-based branding system that makes customization easy. No template editing required!

### Quick Branding (Settings-Based)

The easiest way to rebrand is via settings. Add these to `config/settings/smallstack.py` or your `.env` file:

```python
# config/settings/smallstack.py (or in .env)
BRAND_NAME = "My Project"           # Site name in header, footer, titles
BRAND_TAGLINE = "Your tagline"      # Social preview description
BRAND_LOGO_TEXT = "brand/my-logo.svg"  # Text logo for topbar (relative to static/)
BRAND_FAVICON = "brand/favicon.ico" # Browser tab icon
```

### All Branding Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `BRAND_NAME` | `SmallStack` | Site name shown in header, footer, page titles |
| `BRAND_TAGLINE` | `A minimal Django starter stack` | Social preview description |
| `BRAND_LOGO` | `smallstack/brand/django-smallstack-logo.svg` | Full logo with icon (for marketing pages) |
| `BRAND_LOGO_DARK` | `smallstack/brand/django-smallstack-logo-dark.svg` | Full logo for dark backgrounds |
| `BRAND_LOGO_TEXT` | `smallstack/brand/django-smallstack-text.svg` | **Text-only logo for topbar** |
| `BRAND_ICON` | `smallstack/brand/django-smallstack-icon.svg` | Icon-only mark (for small spaces) |
| `BRAND_FAVICON` | `smallstack/brand/django-smallstack-icon.ico` | Browser favicon |
| `BRAND_SOCIAL_IMAGE` | `smallstack/brand/django-smallstack-social.png` | OpenGraph/Twitter preview |

### Logo Specifications

The topbar displays `BRAND_LOGO_TEXT` at **32px height**. Design your logos accordingly:

| Logo Type | Used In | Recommended Size | Format |
|-----------|---------|------------------|--------|
| `logo_text` | Topbar | Height: 32px, Width: auto | SVG |
| `logo` / `logo_dark` | Marketing pages | Height: 40-60px | SVG |
| `icon` | Small spaces, mobile | 32x32px or 48x48px | SVG |
| `favicon` | Browser tab | 32x32px, 16x16px | ICO |
| `social_image` | Social previews | 1200x630px | PNG |

**SVG Logo Tips:**
- Use `viewBox` for scalability (e.g., `viewBox="0 0 200 28"`)
- Keep text as actual `<text>` elements or convert to paths
- For dark topbar backgrounds, use white text with colored accent
- Test at 32px height to ensure readability

**Changing Logo Display Size:**

The logo size is controlled by CSS, not the SVG dimensions. SmallStack has no project-wide stylesheet hook: a `static/css/project.css` of your own applies only on pages that load it in `{% block extra_css %}`, which SmallStack's own pages don't. So for the topbar on every page, the rule below goes in `static/smallstack/css/theme.css` (and is yours to carry across upgrades):

```css
.site-logo .logo-img {
    height: 64px;  /* Change from default 32px */
    width: auto;
}
```

### Creating Your Text Logo

The topbar text logo should be a horizontal SVG with your brand name. Example structure:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 28">
  <text x="0" y="22" font-family="Segoe UI, system-ui, sans-serif" font-size="22" font-weight="600">
    <tspan fill="#ffffff">Your </tspan>
    <tspan fill="#4FD1A5">Brand</tspan>
  </text>
</svg>
```

**Key points:**
- `viewBox` width depends on your text length (adjust 200 as needed)
- `viewBox` height of 28 works well for 32px display height
- Use web-safe fonts or convert text to paths for consistency
- White (`#ffffff`) text works on the dark topbar background
- Add a colored accent for your brand color

### Adding Your Brand Assets

SmallStack's default brand assets live in `static/smallstack/brand/` and should not be edited directly. Instead, drop your custom assets into the downstream `static/brand/` directory:

1. Add your files to the downstream brand folder:
```
static/brand/
├── my-logo-text.svg      # Text logo for topbar (32px height)
├── my-logo.svg           # Full logo with icon
├── my-logo-dark.svg      # Full logo for dark backgrounds
├── my-icon.svg           # Icon only (32-48px)
├── my-icon.ico           # Favicon (32x32, 16x16)
└── my-social.png         # Social preview (1200x630px)
```

2. Update your settings:
```python
BRAND_NAME = "My Project"
BRAND_LOGO_TEXT = "brand/my-logo-text.svg"  # Topbar logo
BRAND_LOGO = "brand/my-logo.svg"
BRAND_LOGO_DARK = "brand/my-logo-dark.svg"
BRAND_ICON = "brand/my-icon.svg"
BRAND_FAVICON = "brand/my-icon.ico"
BRAND_SOCIAL_IMAGE = "brand/my-social.png"
```

SmallStack's original logos remain untouched in `static/smallstack/brand/`.

### Using Branding in Templates

Branding is available in all templates via the `brand` context variable:

```html
<!-- Access branding anywhere -->
<img src="{% static brand.logo %}" alt="{{ brand.name }}">
<h1>{{ brand.name }}</h1>
<p>{{ brand.tagline }}</p>

<!-- The base template handles these automatically -->
<title>Page Title | {{ brand.name }}</title>
<link rel="icon" href="{% static brand.favicon %}">
<meta property="og:image" content="{% static brand.social_image %}">
```

### Hide SmallStack Documentation

SmallStack reference docs are bundled separately and controlled by a setting:

```python
# config/settings/smallstack.py (or in .env)
SMALLSTACK_DOCS_ENABLED = False  # Hide SmallStack docs
```

No files to delete - just toggle the setting.

### Registration Page Branding

Auth pages (`login.html`, `signup.html`, etc.) use the `brand.name` variable automatically. No manual find-and-replace needed!

### Changing the Color Palette

SmallStack includes 5 built-in color palettes that change the primary accent colors site-wide. Set the system default via settings:

```python
# config/settings/smallstack.py (or in .env)
SMALLSTACK_COLOR_PALETTE = "purple"  # Options: django, light-blue, dark-blue, orange, purple
```

Individual users can override the system palette from their **Profile Edit** page using the palette swatch selector. Their choice persists across sessions and overrides the system default.

For full details on adding custom palettes, see [Theming & Customization](/smallstack/help/smallstack/theming/#color-palettes).

### Adding Topbar Navigation

For marketing sites or layouts without a sidebar, add horizontal navigation links to the topbar:

```python
# config/settings/smallstack.py
SMALLSTACK_TOPBAR_NAV_ENABLED = True  # or set via .env
SMALLSTACK_TOPBAR_NAV_ITEMS = [
    {"label": "Features", "url": "website:features"},
    {"label": "Docs", "url": "help:index"},
    {"label": "About", "url": "website:about"},
]
```

Pairs well with `SMALLSTACK_SIDEBAR_OPEN = False` or `SMALLSTACK_SIDEBAR_ENABLED = False` for a hero-style website layout. See [Topbar Navigation](/smallstack/help/smallstack/topbar-navigation/) for submenus, conditional visibility, and the full item format.

### Controlling Auth Visibility

If your project doesn't need public signup or visible login buttons, use the auth feature flags:

```bash
# .env
SMALLSTACK_SIGNUP_ENABLED=False   # Hide Sign Up, 404 the signup URL
SMALLSTACK_LOGIN_ENABLED=False    # Hide Login button too (admin still works)
```

See [Authentication](/smallstack/help/smallstack/authentication/) for all options.

> **Note:** With settings-based branding, most template files won't create merge conflicts on upstream pulls.

## Receiving Upstream Updates

SmallStack is designed for fork-based development. You can receive upstream updates while keeping your customizations.

### Initial Setup (One Time)

```bash
# Add SmallStack as upstream remote
git remote add upstream https://github.com/emichaud/django-smallstack.git

# Your remotes should look like:
# origin    -> your fork (e.g., github.com/you/yourproject.git)
# upstream  -> django-smallstack (github.com/emichaud/django-smallstack.git)
```

### Pulling Updates

```bash
git fetch upstream
git merge upstream/main
```

### Expected Conflicts

When merging upstream, you may see conflicts in:

| File | Resolution |
|------|------------|
| `uv.lock` | Take upstream version: `git checkout --theirs uv.lock` |
| `config/deploy.yml` | Keep your deployment config |

Branding and navigation don't need SmallStack's templates edited, so they don't conflict: the name, logo, icons and footer links are `BRAND_*` settings, and sidebar links are `nav.register()` calls in your own app. If you did edit `smallstack/base.html` or `includes/topbar.html`, move the change to those, then take upstream's template.

**Note:** `templates/website/home.html` is a thin wrapper. Once you've replaced the `{% include %}` with your own content, upstream changes to SmallStack's home content land in `smallstack/pages/`, which you don't touch, so no conflicts. SmallStack's demo pages are in `apps/showcase/`: delete it, or take upstream's version on a merge.

### Conflict-Free Zones

These areas are designed for customization and won't conflict:

- `apps/website/` - Your project pages and views
- `templates/website/` - Your page templates
- `templates/400.html` … `500.html` - Your own error pages, if you want them (they override SmallStack's)
- `apps/help/content/` - Your documentation (entire folder is yours)
- `.kamal/secrets` - Your secrets (gitignored)

SmallStack's home content lives in `smallstack/pages/` and its demo pages in `apps/showcase/`; both update from upstream without touching your pages.

## Kamal Deployment Configuration

When deploying, update these files with your project info:

### config/deploy.yml

```yaml
service: myproject          # Your app name
image: myproject

servers:
  web:
    - 123.45.67.89          # Your VPS IP

volumes:
  - /root/myproject_data/media:/app/media
  - /root/myproject_data/db:/app/data

proxy:
  hosts:
    - myproject.com         # Your domain
    - www.myproject.com
```

### .kamal/secrets

Copy from `secrets.example` and fill in:

```bash
SECRET_KEY=your-unique-secret-key
ALLOWED_HOSTS=myproject.com,www.myproject.com,123.45.67.89,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://myproject.com,https://www.myproject.com
```

## Quick Reference

### Conflict-Free (Safe to Customize)

| What to Customize | Where |
|------------------|-------|
| Homepage & pages | `templates/website/home.html` — replace the `{% include %}` with your own content; add pages in `apps/website/` |
| Error pages | `templates/404.html` (etc.) — yours override SmallStack's defaults |
| SmallStack's demo pages | `apps/showcase/` — delete the app (and its two lines) |
| Your documentation | `apps/help/content/` (entire folder is yours) |
| Deployment config | `config/deploy.yml`, `.kamal/secrets` |
| User profile fields | `apps/profile/models.py` |
| Background tasks | `apps/tasks/` |

### Customizing Without Touching SmallStack's Files

| What to Customize | Where (no merge conflict) |
|------------------|-------|
| Site name, logo, icons, tagline | `BRAND_*` in `config/settings/smallstack.py` or the environment (`BRAND_NAME`, `BRAND_LOGO`, …) |
| Footer privacy / terms links | `BRAND_PRIVACY_URL`, `BRAND_TERMS_URL` |
| Sidebar and topbar links | `nav.register()` in your app's `AppConfig.ready()` ([Navigation](/smallstack/help/smallstack/navigation/)) |
| Theme colors | A palette ([Theming](/smallstack/help/smallstack/theming/)) |
| A page's layout | Your own template in `templates/website/` (or your app), extending `smallstack/base.html` |

Editing a file under `apps/smallstack/templates/` or `apps/smallstack/static/` will conflict on the next merge; reach for the rows above first.

## Next Steps

- [Getting Started](/smallstack/help/smallstack/getting-started/) - Quick setup guide
- [Theming](/smallstack/help/smallstack/theming/) - Customize colors and dark mode
- [Adding Your Own Theme](/smallstack/help/smallstack/adding-your-own-theme/) - Use Bootstrap, Tailwind, or any CSS framework alongside SmallStack
- [Kamal Deployment](/smallstack/help/smallstack/kamal-deployment/) - Deploy to production
