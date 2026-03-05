---
title: Getting Started
description: Quick start guide for Django SmallStack
---

# Getting Started with {{ project_name }}

Welcome to **{{ project_name }}** v{{ version }}! This is a Django {{ django_version }}+ starter project that provides a solid foundation for building admin-style web applications.

## What's Included

- **Custom User Model** - Flexible user authentication out of the box
- **User Profiles** - Profile management with photo uploads
- **Admin Theme** - Clean, modern UI with dark/light mode
- **Help System** - Built-in documentation with markdown support
- **htmx** - Progressive enhancement with [htmx](https://htmx.org/) — partial page updates with no build tools
- **Background Tasks** - Django 6's task framework pre-configured
- **Activity Dashboard** - Lightweight request tracking with auto-pruning, staff-only dashboard with htmx live-refresh, user activity and theme stats
- **Logging & Audit Trail** - Sensible logging defaults and built-in activity tracking using Django's LogEntry
- **Website App** - Scaffold for your project's pages (home, about, etc.)
- **Starter Template** - [Copy-paste template](/starter/) for creating new pages
- **Responsive Design** - Works on desktop and mobile
- **Docker Ready** - Deploy anywhere with Docker

## Quick Start

### Prerequisites

- Python {{ python_version }}+
- [UV](https://github.com/astral-sh/uv) package manager (recommended)
- Docker Desktop (for containerized deployment)

### Local Development

SmallStack includes a `Makefile` with shortcuts for all common commands. See [Make Commands](/help/smallstack/make-commands/) for the full reference.

1. **Clone and enter the project:**
   ```bash
   cd django-smallstack
   ```

2. **Run setup** (installs all dependencies including dev tools, runs migrations, creates superuser):
   ```bash
   make setup
   ```

3. **Set up environment variables** (optional — defaults work out of the box):
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Start the development server:**
   ```bash
   make run
   ```

5. **Open your browser:**
   - Homepage: [http://localhost:8005](http://localhost:8005)
   - Admin: [http://localhost:8005/admin](http://localhost:8005/admin)

That's it — two commands to go from clone to running app.

### Verify Everything Works

```bash
make test         # Run the test suite (33 tests)
make lint         # Check code style
```

## Project Structure Overview

SmallStack separates "customize freely" areas from "core" areas:

```
django-smallstack/
├── apps/
│   ├── website/           # CUSTOMIZE: Your pages (home, about, etc.)
│   ├── help/
│   │   └── content/
│   │       ├── index.md   # CUSTOMIZE: Your welcome page
│   │       └── smallstack/ # REFERENCE: SmallStack docs
│   ├── profile/           # EXTEND: User profiles
│   ├── tasks/             # EXTEND: Background tasks
│   ├── accounts/          # CORE: User authentication
│   └── smallstack/       # CORE: Theme system
├── templates/
│   ├── website/           # CUSTOMIZE: Your page templates (thin wrappers)
│   └── smallstack/
│       └── pages/         # UPSTREAM: SmallStack marketing content
├── config/                # CUSTOMIZE: Settings & deployment
├── static/
│   ├── smallstack/        # UPSTREAM: Core theme, brand, help assets
│   ├── brand/             # CUSTOMIZE: Your brand assets
│   ├── css/               # CUSTOMIZE: Your CSS overrides
│   └── js/                # CUSTOMIZE: Your JS
└── docs/                  # Additional documentation
```

## Making It Your Own

SmallStack is designed to be forked and customized. Here's what to do first:

### 0. Configure Authentication

By default, login and signup are enabled — anyone can create an account. For public-facing projects where you're not ready for signups, disable it in your `.env`:

```bash
# .env
SMALLSTACK_SIGNUP_ENABLED=False
```

This hides the Sign Up button, removes the signup link from the login page, and returns 404 on `/accounts/signup/`. Login and admin still work normally.

See [Authentication](/help/smallstack/authentication/) for all options including hiding the login UI entirely.

### 1. Customize Your Homepage

SmallStack's page templates use a **thin wrapper + include pattern**. The default `templates/website/home.html` includes SmallStack's marketing content via `{% include %}`. To customize, replace the include with your own markup:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Home{% endblock %}
{% block breadcrumbs %}{% endblock %}

{% block content %}
<div class="hero-section">
    <div class="hero-content">
        <h1 class="hero-title">My App</h1>
        <p class="hero-subtitle">Your tagline here.</p>
    </div>
</div>
{% endblock %}
```

Do the same for `templates/website/about.html` and `templates/starter.html`. Once replaced, upstream SmallStack updates to marketing content (in `templates/smallstack/pages/`) won't cause merge conflicts with your pages.

### 2. Update Your Branding

Replace "SmallStack" in these files:

| File | What to Change |
|------|----------------|
| `templates/smallstack/base.html` | Title suffix, footer copyright |
| `templates/smallstack/includes/topbar.html` | Logo text |
| `templates/registration/*.html` | Page titles |

**Quick replace:**
```bash
# Replace in all registration templates
find templates/registration -name "*.html" -exec sed -i '' 's/SmallStack/MyApp/g' {} \;
```

### 3. Set Up Your Documentation

Edit `apps/help/content/index.md` to create your project's welcome page. You can:
- Keep SmallStack docs as reference in `/help/smallstack/`
- Add your own docs at `/help/your-page/`
- Remove SmallStack docs entirely

See the [Customization Guide](/help/smallstack/customization/) for detailed instructions.

## Creating New Pages

### In the Website App (Recommended)

For project-specific pages like landing pages, pricing, features:

1. **Add a view** in `apps/website/views.py`:
   ```python
   def pricing_view(request):
       return render(request, "website/pricing.html")
   ```

2. **Add a URL** in `apps/website/urls.py`:
   ```python
   urlpatterns = [
       path("", views.home_view, name="home"),
       path("pricing/", views.pricing_view, name="pricing"),
   ]
   ```

3. **Create the template** `templates/website/pricing.html`

### Using the Starter Template

The starter page at [/starter/](/starter/) demonstrates all available UI components. To create a new page based on it:

1. **Create a new template** (don't copy `starter.html` — it's a thin wrapper). Instead, create a fresh template:
   ```html
   {% extends "smallstack/base.html" %}
   {% load static theme_tags %}

   {% block title %}My Page{% endblock %}

   {% block breadcrumbs %}
   {% breadcrumb "Home" "website:home" %}
   {% breadcrumb "My Page" %}
   {% render_breadcrumbs %}
   {% endblock %}

   {% block content %}
   <!-- Copy components from /starter/ that you need -->
   {% endblock %}
   ```

2. **Create a view** (see above)

3. **Add to sidebar** in `templates/smallstack/includes/sidebar.html`

Visit [/starter/](/starter/) to see all available components in action.

## Deployment Setup

Before deploying, update the Kamal configuration:

### config/deploy.yml

```yaml
service: myapp              # Your app name

servers:
  web:
    - 123.45.67.89          # Your VPS IP

volumes:
  - /root/myapp_data/media:/app/media   # Update path
  - /root/myapp_data/db:/app/data

proxy:
  hosts:
    - myapp.com             # Your domain
    - www.myapp.com
```

### .kamal/secrets

Copy from `secrets.example` and configure:

```bash
cp .kamal/secrets.example .kamal/secrets
# Edit with your values
```

See [Kamal Deployment](/help/smallstack/kamal-deployment/) for full instructions.

## Next Steps

- [Authentication](/help/smallstack/authentication/) - Control login, signup, and feature flags
- [Customization Guide](/help/smallstack/customization/) - Make SmallStack your own
- [View the Starter Page](/starter/) - See all components in action
- [Customize the theme](/help/smallstack/theming/) - Colors, dark mode, components
- [Deploy with Kamal](/help/smallstack/kamal-deployment/) - Zero-downtime VPS deployment
- [Explore the structure](/help/smallstack/project-structure/) - Understand the codebase

## Getting Help

If you run into issues:

1. Check the [FAQ](/help/smallstack/faq/) for common questions
2. Review the [project structure](/help/smallstack/project-structure/)
3. Open an issue on GitHub
