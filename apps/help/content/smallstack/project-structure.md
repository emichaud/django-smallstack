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
│   ├── admin_theme/           # Theme helpers (pure presentation)
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
│   ├── admin_theme/           # Theme templates
│   ├── profile/               # Profile templates
│   ├── help/                  # Help templates
│   └── registration/         # Auth templates
├── static/                    # Static assets
│   ├── css/theme.css         # Main stylesheet
│   └── js/theme.js           # Theme JavaScript
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

### admin_theme

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
| `content/` | Markdown documentation files |
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
base.html (admin_theme)
├── includes/topbar.html
├── includes/sidebar.html
├── includes/messages.html
└── includes/breadcrumbs.html

Child templates extend base.html:
├── home.html
├── profile/profile.html
├── help/help_detail.html
└── registration/login.html
```

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
{% extends "admin_theme/base.html" %}

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

```
static/
├── css/
│   └── theme.css        # Main theme styles
├── js/
│   └── theme.js         # Theme toggle, sidebar, dropdowns
├── help/                # Help app static files
│   ├── css/help.css
│   └── js/help.js
└── robots.txt           # Search engine directives
```

### CSS Architecture

The theme uses CSS custom properties for all colors and spacing:

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
       "apps.admin_theme",
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
