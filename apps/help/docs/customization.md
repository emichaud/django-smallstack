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
│   └── docs/        # UPSTREAM: SmallStack reference docs (bundled)
├── profile/         # EXTEND: Add fields, customize templates
├── tasks/           # EXTEND: Add your background tasks
├── accounts/        # CORE: User model (extend carefully)
└── admin_theme/     # CORE: Theme system (extend via CSS)

templates/
├── website/         # CUSTOMIZE: Your page templates
└── ...              # EXTEND: Override specific templates

config/
├── deploy.yml       # CUSTOMIZE: Your deployment config
└── settings/        # CUSTOMIZE: Your settings
```

## Customizing Your Homepage

The `apps/website/` app is your project's home. Customize it freely without worrying about upstream conflicts.

### Edit the Homepage

1. Open `templates/website/home.html`
2. Replace the SmallStack landing page content with your own
3. The template already extends `base.html` so theming works automatically

```html
{% extends "admin_theme/base.html" %}
{% load theme_tags %}

{% block title %}Home{% endblock %}

{% block breadcrumbs %}{% endblock %}

{% block content %}
<!-- Hero Section -->
<div class="hero-section">
    <div class="hero-content">
        <h1 class="hero-title">My Project</h1>
        <p class="hero-subtitle">Your project tagline here.</p>
    </div>
</div>

<!-- Your custom content -->
<div class="card">
    <div class="card-body">
        <p>Your content here.</p>
    </div>
</div>
{% endblock %}
```

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
- **`apps/help/docs/`** - SmallStack reference docs (bundled, controlled by setting)

This separation means your docs never conflict with upstream updates.

### Hiding SmallStack Docs

SmallStack reference docs are shown by default. To hide them:

```python
# config/settings/base.py (or in .env)
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
├── index.md           # /help/index/
├── user-guide.md      # /help/user-guide/
└── dev/
    └── api.md         # /help/dev/api/
```

SmallStack docs automatically appear at `/help/smallstack/*` when enabled.

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
- **Links**: [Getting Started](/help/getting-started/)
- **Code blocks**: With syntax highlighting
- **Tables**: Standard markdown tables
```

### Editing the Welcome Page

The root `index.md` is your documentation home. Update it for your project:

```markdown
# Welcome to {{ project_name }}

Your project documentation lives here.

## Quick Links

- [User Guide](/help/user-guide/) - Learn how to use the app
- [API Reference](/help/dev/api/) - Developer documentation
- [SmallStack Docs](/help/smallstack/readme/) - Framework reference
```

## Customizing Branding

SmallStack uses a settings-based branding system that makes customization easy. No template editing required!

### Quick Branding (Settings-Based)

The easiest way to rebrand is via settings. Add these to `config/settings/base.py` or your `.env` file:

```python
# config/settings/base.py (or in .env)
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
| `BRAND_LOGO` | `brand/django-smallstack-logo.svg` | Full logo with icon (for marketing pages) |
| `BRAND_LOGO_DARK` | `brand/django-smallstack-logo-dark.svg` | Full logo for dark backgrounds |
| `BRAND_LOGO_TEXT` | `brand/django-smallstack-text.svg` | **Text-only logo for topbar** |
| `BRAND_ICON` | `brand/django-smallstack-icon.svg` | Icon-only mark (for small spaces) |
| `BRAND_FAVICON` | `brand/django-smallstack-icon.ico` | Browser favicon |
| `BRAND_SOCIAL_IMAGE` | `brand/django-smallstack-social.png` | OpenGraph/Twitter preview |

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

1. Create your brand assets folder:
```bash
mkdir -p static/brand
```

2. Add your files:
```
static/brand/
├── my-logo-text.svg      # Text logo for topbar (32px height)
├── my-logo.svg           # Full logo with icon
├── my-logo-dark.svg      # Full logo for dark backgrounds
├── my-icon.svg           # Icon only (32-48px)
├── my-icon.ico           # Favicon (32x32, 16x16)
└── my-social.png         # Social preview (1200x630px)
```

3. Update your settings:
```python
BRAND_NAME = "My Project"
BRAND_LOGO_TEXT = "brand/my-logo-text.svg"  # Topbar logo
BRAND_LOGO = "brand/my-logo.svg"
BRAND_LOGO_DARK = "brand/my-logo-dark.svg"
BRAND_ICON = "brand/my-icon.svg"
BRAND_FAVICON = "brand/my-icon.ico"
BRAND_SOCIAL_IMAGE = "brand/my-social.png"
```

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
# config/settings/base.py (or in .env)
SMALLSTACK_DOCS_ENABLED = False  # Hide SmallStack docs
```

No files to delete - just toggle the setting.

### Registration Page Branding

Auth pages (`login.html`, `signup.html`, etc.) use the `brand.name` variable automatically. No manual find-and-replace needed!

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
| `templates/admin_theme/base.html` | Keep your branding changes |
| `templates/admin_theme/includes/topbar.html` | Keep your logo |
| `templates/registration/*.html` | Keep your branding |
| `config/deploy.yml` | Keep your deployment config |

### Conflict-Free Zones

These areas are designed for customization and won't conflict:

- `apps/website/` - Your project pages
- `templates/website/` - Your page templates
- `apps/help/content/` - Your documentation (entire folder is yours)
- `.kamal/secrets` - Your secrets (gitignored)

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
ALLOWED_HOSTS=myproject.com,www.myproject.com,123.45.67.89,*
CSRF_TRUSTED_ORIGINS=https://myproject.com,https://www.myproject.com
```

## Quick Reference

### Conflict-Free (Safe to Customize)

| What to Customize | Where |
|------------------|-------|
| Homepage & pages | `templates/website/home.html`, `apps/website/` |
| Your documentation | `apps/help/content/` (entire folder is yours) |
| Deployment config | `config/deploy.yml`, `.kamal/secrets` |
| User profile fields | `apps/profile/models.py` |
| Background tasks | `apps/tasks/` |

### Will Conflict on Upstream Merge (Expected)

| What to Customize | Where |
|------------------|-------|
| Site title & footer | `templates/admin_theme/base.html` |
| Header logo | `templates/admin_theme/includes/topbar.html` |
| Auth page titles | `templates/registration/*.html` |
| Sidebar navigation | `templates/admin_theme/includes/sidebar.html` |
| Theme colors | `static/css/theme.css` |

## Next Steps

- [Getting Started](/help/smallstack/getting-started/) - Quick setup guide
- [Theming](/help/smallstack/theming/) - Customize colors and dark mode
- [Kamal Deployment](/help/smallstack/kamal-deployment/) - Deploy to production
