# Getting Started

Welcome aboard. This guide walks you through the first things to do after cloning SmallStack — from configuration to creating your first page. It's meant to be a friendly stroll, not a deep dive. Links to the detailed docs are sprinkled throughout.

## First Things First

After you've cloned the repo and run `make setup`, you'll have a working site at `http://localhost:8005` with a default admin account (`admin` / `admin`). Here's what to tackle next.

### 1. Update Your Branding

Open `config/settings/base.py` and change the brand name:

```python
BRAND_NAME = "My App"
```

This updates the sidebar, topbar, page titles, and anywhere else SmallStack references the project name. One setting, everywhere at once.

For the full list of settings you can tweak, see [Settings & Configuration](/smallstack/help/smallstack/settings-configuration/).

### 2. Pick a Layout

SmallStack ships with sidebar + topbar combinations you can mix and match. Set the layout in your settings:

```python
SMALLSTACK_LAYOUT = "sidebar"  # or "topbar", "both", "minimal"
```

**See them all:** Visit the [Layout Gallery](/smallstack/layouts/) to preview every combination live. The [Nav Guide](/smallstack/nav-guide/) explains how navigation items flow into the sidebar and topbar.

### 3. Customize Your Homepage

The default homepage is a thin wrapper that includes SmallStack's welcome content. Replace it with your own:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Home{% endblock %}
{% block breadcrumbs %}{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header"><h2>Welcome</h2></div>
    <div class="card-body">
        <p>This is my app. There are many like it, but this one is mine.</p>
    </div>
</div>
{% endblock %}
```

Save it to `templates/website/home.html` and refresh. That's it.

### 4. Configure Authentication

By default, anyone can sign up. If you're not ready for public signups yet:

```bash
# .env
SMALLSTACK_SIGNUP_ENABLED=False
```

This hides the signup button and returns 404 on the signup URL. Login and admin still work normally. See [Authentication](/smallstack/help/smallstack/authentication/) for all the options.

### 5. Set Your Timezone

SmallStack defaults to `America/New_York`. Override it in `.env`:

```bash
TIME_ZONE=America/Chicago
```

Users can also set their own timezone in their profile. See [Working with Timezones](/smallstack/help/smallstack/timezones/) for the full story.

## Creating Pages

The pattern is always the same: **view → template → URL → nav item**.

**Add a view** in `apps/website/views.py`:

```python
def pricing_view(request):
    return render(request, "website/pricing.html")
```

**Add a URL** in `apps/website/urls.py`:

```python
path("pricing/", views.pricing_view, name="pricing"),
```

**Create the template** at `templates/website/pricing.html`:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Pricing{% endblock %}

{% block content %}
<!-- Your content here -->
{% endblock %}
```

**Register a nav item** (optional) in `apps/website/apps.py`:

```python
nav.register(
    section="main",
    label="Pricing",
    url_name="website:pricing",
    order=50,
)
```

Need a head start? Check out the [Starter Page](/starter/) for copy-paste examples of every component, or the [Basic Template](/starter/basic/) for a minimal starting point.

## Theming

SmallStack supports dark and light modes with 5 built-in color palettes. Users pick their preference from the topbar dropdown.

All components use CSS variables like `--primary`, `--card-bg`, and `--body-fg`, so your custom pages automatically match the selected theme. You can also create your own palettes.

- [Theming Guide](/smallstack/help/smallstack/theming/) — Colors, dark mode, how it all works
- [Custom Themes](/smallstack/help/smallstack/adding-your-own-theme/) — Add your own CSS framework

## What's Next

You've got the basics. Here are the natural next steps depending on what you're building:

| Goal | Guide |
|------|-------|
| Build data management pages | [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/) |
| Browse and manage models quickly | [Model Explorer](/smallstack/help/smallstack/explorer/) |
| Set up production backups | [Database Backups](/smallstack/help/smallstack/database-backups/) |
| Deploy to a VPS | [Kamal Deployment](/smallstack/help/smallstack/kamal-deployment/) |
| Understand the project layout | [Project Structure](/smallstack/help/smallstack/project-structure/) |
| Add your own documentation | [Help System Guide](/smallstack/help/smallstack/help-system/) |

And if you just want the shortest path from clone to live site, check out the [Quick Setup (TL;DR)](/help/quick-setup/).
