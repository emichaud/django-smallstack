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
- **Background Tasks** - Django 6's task framework pre-configured
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

1. **Clone and enter the project:**
   ```bash
   cd django-smallstack
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Run migrations:**
   ```bash
   uv run python manage.py migrate
   ```

5. **Create a superuser:**
   ```bash
   uv run python manage.py create_dev_superuser
   ```

6. **Start the development server:**
   ```bash
   uv run python manage.py runserver
   ```

7. **Open your browser:**
   - Homepage: [http://localhost:8000](http://localhost:8000)
   - Admin: [http://localhost:8000/admin](http://localhost:8000/admin)

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
│   └── admin_theme/       # CORE: Theme system
├── templates/
│   └── website/           # CUSTOMIZE: Your page templates
├── config/                # CUSTOMIZE: Settings & deployment
├── static/                # CSS, JS, images
└── docs/                  # Additional documentation
```

## Making It Your Own

SmallStack is designed to be forked and customized. Here's what to do first:

### 1. Customize Your Homepage

Edit `templates/website/home.html` with your own content:

```html
{% extends "base.html" %}

{% block content %}
<div class="container mx-auto px-4 py-12">
    <h1>Welcome to My App</h1>
    <p>Your content here.</p>
</div>
{% endblock %}
```

### 2. Update Your Branding

Edit `.env`:

```bash
SITE_NAME=My Awesome App
SITE_DOMAIN=myapp.com
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

For admin-style pages, copy the starter template:

1. **Copy the template:**
   ```bash
   cp templates/starter.html templates/my_page.html
   ```

2. **Create a view** (see above)

3. **Add to sidebar** in `templates/admin_theme/includes/sidebar.html`

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
