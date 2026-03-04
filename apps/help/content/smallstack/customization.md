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
│   └── content/
│       ├── index.md          # CUSTOMIZE: Your welcome page
│       ├── _config.yaml      # CUSTOMIZE: Your doc structure
│       └── smallstack/       # UPSTREAM: SmallStack reference docs
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
{% extends "base.html" %}

{% block content %}
<div class="container mx-auto px-4 py-12">
    <h1>Welcome to My Project</h1>
    <p>Your custom content here.</p>
</div>
{% endblock %}
```

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

The help system supports hierarchical sections. You can:
- Replace SmallStack docs with your own
- Add your own docs alongside SmallStack
- Create multiple documentation sections

### Option 1: Replace SmallStack Docs Entirely

If you don't want SmallStack reference docs:

1. Delete the `apps/help/content/smallstack/` folder
2. Edit `apps/help/content/_config.yaml`:

```yaml
title: "Documentation"

variables:
  version: "1.0.0"
  project_name: "My Project"

sections:
  - slug: ""
    title: "Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
      - slug: getting-started
        title: "Getting Started"
        icon: "rocket"
      # Add your pages here
```

3. Create your docs in `apps/help/content/`:
   - `index.md` - Welcome page
   - `getting-started.md` - Your getting started guide
   - etc.

### Option 2: Add Your Docs Alongside SmallStack

Keep SmallStack docs as a reference while adding your own:

```yaml
# apps/help/content/_config.yaml
title: "Documentation"

sections:
  # Your project docs (root level)
  - slug: ""
    title: "Project Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
      - slug: user-guide
        title: "User Guide"
        icon: "book"
      - slug: api-reference
        title: "API Reference"
        icon: "code"

  # SmallStack reference (in subfolder)
  - slug: smallstack
    title: "SmallStack Reference"
    folder: smallstack/
    config: smallstack/_config.yaml
```

Your docs live at `/help/index/`, `/help/user-guide/`, etc.
SmallStack docs live at `/help/smallstack/getting-started/`, etc.

### Option 3: Multiple Documentation Sections

Create multiple sections for different audiences:

```yaml
sections:
  # User documentation
  - slug: ""
    title: "User Guide"
    pages:
      - slug: index
        title: "Getting Started"
        icon: "rocket"
      - slug: features
        title: "Features"
        icon: "star"

  # Developer documentation
  - slug: dev
    title: "Developer Docs"
    pages:
      - slug: api
        title: "API Reference"
        icon: "code"
      - slug: contributing
        title: "Contributing"
        icon: "git"

  # SmallStack reference
  - slug: smallstack
    title: "Framework Reference"
    folder: smallstack/
    config: smallstack/_config.yaml
```

Create the folder structure:
```
apps/help/content/
├── _config.yaml
├── index.md           # User: Getting Started
├── features.md        # User: Features
├── dev/
│   ├── api.md         # Dev: API Reference
│   └── contributing.md # Dev: Contributing
└── smallstack/        # SmallStack reference
```

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

## Hiding SmallStack Branding

### Remove SmallStack Section from Docs

Edit `apps/help/content/_config.yaml` and remove the SmallStack section:

```yaml
sections:
  - slug: ""
    title: "Documentation"
    pages:
      - slug: index
        title: "Welcome"
        icon: "home"
  # Remove the smallstack section entirely
```

Then delete `apps/help/content/smallstack/`.

### Update Footer Links

Edit `templates/admin_theme/includes/footer.html` to remove or change the "Built with SmallStack" link.

### Update Login/Signup Pages

The auth templates are in `templates/registration/`. Customize them with your branding.

## Receiving Upstream Updates

If you keep the `smallstack/` folder, you can receive upstream updates:

```bash
# Add SmallStack as upstream remote (one time)
git remote add upstream https://github.com/emichaud/django-smallstack.git

# Fetch and merge updates
git fetch upstream
git merge upstream/main

# Resolve any conflicts in your customized files
```

Files in `apps/website/` and `apps/help/content/` (except `smallstack/`) are yours to customize and won't conflict with upstream changes.

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

| What to Customize | Where |
|------------------|-------|
| Homepage & landing pages | `apps/website/`, `templates/website/` |
| Your documentation | `apps/help/content/` (root level) |
| Site name & domain | `.env` |
| Deployment config | `config/deploy.yml`, `.kamal/secrets` |
| User profile fields | `apps/profile/models.py` |
| Background tasks | `apps/tasks/` |
| Theme colors | `static/admin_theme/css/theme.css` |
| Sidebar navigation | `templates/admin_theme/includes/sidebar.html` |

## Next Steps

- [Getting Started](/help/smallstack/getting-started/) - Quick setup guide
- [Theming](/help/smallstack/theming/) - Customize colors and dark mode
- [Kamal Deployment](/help/smallstack/kamal-deployment/) - Deploy to production
