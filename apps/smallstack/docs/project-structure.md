---
title: Project Structure
description: Understanding the codebase organization
---

# Project Structure

{{ project_name }} follows Django best practices with a modular app structure. This guide explains how the codebase is organized.

## Directory Overview

```
django-smallstack/
├── apps/                      # Django applications
│   ├── accounts/              # User model & authentication
│   ├── smallstack/           # Theme helpers (pure presentation)
│   ├── profile/               # User profiles
│   ├── help/                  # Documentation system
│   └── tasks/                 # Background tasks
├── config/                    # Project configuration
│   ├── settings/              # Split settings
│   │   ├── base.py           # Shared settings
│   │   ├── development.py    # Dev overrides
│   │   └── production.py     # Prod overrides
│   ├── urls.py               # Root URL routing
│   └── views.py              # Utility views
├── templates/                 # HTML templates
│   ├── smallstack/           # Theme templates
│   │   ├── base.html         # Master layout
│   │   ├── includes/         # Topbar, sidebar, messages
│   │   └── pages/            # SmallStack marketing content (upstream)
│   ├── website/              # Page wrappers (customize these)
│   │   ├── home.html         # Thin wrapper → pages/home_content.html
│   │   └── about.html        # Thin wrapper → pages/about_content.html
│   ├── starter.html          # Thin wrapper → pages/starter_*.html
│   ├── profile/               # Profile templates
│   ├── help/                  # Help templates
│   └── registration/         # Auth templates
├── static/                    # Static assets
│   ├── smallstack/            # UPSTREAM: SmallStack core (don't edit downstream)
│   │   ├── brand/             # Default SmallStack brand assets
│   │   ├── css/theme.css      # Core theme stylesheet
│   │   ├── js/theme.js        # Core UI logic (theme, sidebar, messages)
│   │   ├── js/htmx.min.js    # htmx library (vendored, no CDN)
│   │   └── help/              # Help app assets (css + js)
│   ├── brand/.gitkeep         # DOWNSTREAM: Project brand assets go here
│   ├── css/.gitkeep           # DOWNSTREAM: Project CSS overrides go here
│   └── js/.gitkeep            # DOWNSTREAM: Project JS goes here
├── docs/                      # Additional docs
├── .env                       # Environment variables
├── Dockerfile                 # Docker build
├── docker-compose.yml         # Docker orchestration
└── pyproject.toml            # Dependencies
```

## Apps

### accounts

User authentication and custom User model.

| File | Purpose |
|------|---------|
| `models.py` | Custom User model (extends AbstractBaseUser) |
| `views.py` | SignupView for user registration |
| `forms.py` | SignupForm for user creation |
| `admin.py` | Custom UserAdmin configuration |

### smallstack

Pure presentation - theme helpers only (no models).

| File | Purpose |
|------|---------|
| `templatetags/theme_tags.py` | Breadcrumbs, nav_active tags |
| `management/commands/` | create_dev_superuser command |

### profile

User profile management.

| File | Purpose |
|------|---------|
| `models.py` | UserProfile model (photos, bio, etc.) |
| `views.py` | ProfileView, ProfileEditView, ProfileDetailView |
| `forms.py` | UserProfileForm |
| `signals.py` | Auto-create profile on user creation |
| `urls.py` | Profile URL routing |

### help

This documentation system (you're reading it!).

| File | Purpose |
|------|---------|
| `content/` | Your project's documentation (conflict-free) |
| `smallstack/` | SmallStack reference docs (bundled) |
| `utils.py` | Markdown processing, variable substitution |
| `views.py` | HelpIndexView, HelpDetailView |
| `urls.py` | Help URL routing |

### tasks

Background tasks using Django 6 Tasks framework.

| File | Purpose |
|------|---------|
| `tasks.py` | Task definitions (send_email_task, send_welcome_email, etc.) |

## Configuration

### Settings Architecture

Settings are split into three files:

- **base.py** - Shared settings (apps, middleware, templates)
- **development.py** - Debug mode, local database
- **production.py** - Security settings, production database

Set active settings via environment:

```bash
DJANGO_SETTINGS_MODULE=config.settings.development
# or
DJANGO_SETTINGS_MODULE=config.settings.production
```

### Key Settings

```python
# Custom user model
AUTH_USER_MODEL = "accounts.User"

# Authentication URLs
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Static/Media files
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
```

## Templates

### Inheritance Structure

```
base.html (smallstack)
├── includes/topbar.html
├── includes/sidebar.html
├── includes/messages.html
└── includes/breadcrumbs.html

Child templates extend base.html:
├── website/home.html        → {% include "smallstack/pages/home_content.html" %}
├── website/about.html       → {% include "smallstack/pages/about_content.html" %}
├── starter.html             → {% include "smallstack/pages/starter_*.html" %}
├── profile/profile.html
├── help/help_detail.html
└── registration/login.html
```

Marketing pages use thin wrappers that `{% include %}` content from `smallstack/pages/`. Downstream projects replace the wrappers with their own content — SmallStack's marketing fragments update independently via upstream.

### Template Blocks

| Block | Purpose |
|-------|---------|
| `title` | Page title |
| `extra_css` | Additional stylesheets |
| `breadcrumbs` | Breadcrumb navigation |
| `content` | Main page content |
| `extra_js` | Additional scripts |

Example:

```html
{% extends "smallstack/base.html" %}

{% block title %}My Page{% endblock %}

{% block content %}
<h1>Hello World</h1>
{% endblock %}
```

## URL Patterns

### Main URLs (config/urls.py)

| Pattern | View/Include | Name |
|---------|--------------|------|
| `/admin/` | Django admin | - |
| `/accounts/` | Auth URLs | login, logout, etc. |
| `/accounts/signup/` | SignupView | signup |
| `/profile/` | profile.urls | profile, profile_edit |
| `/help/` | help.urls | help:index, help:detail |
| `/health/` | health_check | health_check |
| `/` | home_view | home |

### Profile URLs

| Pattern | View | Name |
|---------|------|------|
| `/profile/` | ProfileView | profile |
| `/profile/edit/` | ProfileEditView | profile_edit |
| `/profile/<username>/` | ProfileDetailView | profile_detail |

### Help URLs

| Pattern | View | Name |
|---------|------|------|
| `/help/` | HelpIndexView | help:index |
| `/help/<slug>/` | HelpDetailView | help:detail |

## Static Files

### Organization

SmallStack uses **namespaced static files** to separate upstream core assets from downstream project assets:

```
static/
├── smallstack/                  # UPSTREAM: SmallStack core (don't edit downstream)
│   ├── brand/                   # Default SmallStack brand assets (logos, icons)
│   ├── css/theme.css            # Core theme styles
│   ├── js/theme.js              # Theme toggle, sidebar, dropdowns
│   └── help/                    # Help app static files
│       ├── css/help.css
│       └── js/help.js
├── brand/.gitkeep               # DOWNSTREAM: Project brand assets go here
├── css/.gitkeep                 # DOWNSTREAM: Project CSS overrides go here
├── js/.gitkeep                  # DOWNSTREAM: Project JS goes here
└── robots.txt                   # Project-specific, stays at root
```

**Upstream vs. Downstream:**
- `static/smallstack/` contains SmallStack's core assets. These update from upstream and should not be edited in downstream projects.
- `static/brand/`, `static/css/`, `static/js/` are empty by default (`.gitkeep` files). Drop your project assets here.

**Downstream branding workflow:**
1. Drop custom logos into `static/brand/` (e.g., `static/brand/my-logo.svg`)
2. Set in `.env`: `BRAND_LOGO_TEXT=brand/my-logo.svg`
3. SmallStack's originals stay untouched in `static/smallstack/brand/`
4. For theme CSS overrides: add `static/css/project.css`, load via `{% block extra_css %}`

### CSS Architecture

The theme uses CSS custom properties for all colors and spacing, defined in `static/smallstack/css/theme.css`:

```css
:root {
    --primary: #417690;
    --body-bg: #f7f7f7;
    /* ... */
}

[data-theme="dark"] {
    --primary: #44b78b;
    --body-bg: #121212;
    /* ... */
}
```

## Adding a New App

1. **Create the app:**
   ```bash
   mkdir apps/myapp
   ```

2. **Add required files:**
   - `__init__.py`
   - `apps.py` (with AppConfig)
   - `models.py`
   - `views.py`
   - `urls.py`

3. **Register in settings:**
   ```python
   # config/settings/base.py
   INSTALLED_APPS = [
       "apps.accounts",
       "apps.smallstack",
       "apps.profile",
       "apps.help",
       "apps.tasks",
       "apps.myapp",  # Add here
       ...
   ]
   ```

4. **Add URL routing:**
   ```python
   # config/urls.py
   path("myapp/", include("apps.myapp.urls")),
   ```

5. **Create templates:**
   ```
   templates/myapp/my_template.html
   ```

6. **Run migrations:**
   ```bash
   python manage.py makemigrations myapp
   python manage.py migrate
   ```

## Key Conventions

1. **App naming:** Simple names in `apps/` folder (e.g., `profile`, `help`, `accounts`)
2. **Templates:** Match app name in templates folder
3. **URL names:** Use app namespace (e.g., `help:index`)
4. **Models:** Include `__str__` and `Meta` class
5. **Views:** Prefer class-based views
6. **Settings:** Use `python-decouple` for env vars
