---
title: "Scenario A: Public Site, No User Login"
description: "Use your own theme for public pages. Login only to manage with SmallStack tools."
---

# Scenario A: Public Site, No User Login

You have a public website with no user-facing login. Visitors browse your pages using your own theme. You (or staff) log in behind the scenes to manage the site using SmallStack's built-in tools.

## What You're Building

```
Visitors see:     Your theme (Bootstrap, Tailwind, plain CSS, etc.)
Staff logs in:    SmallStack theme (Dashboard, Explorer, Backups, etc.)
Login page:       /smallstack/accounts/login/
After login:      /smallstack/ (SmallStack Dashboard)
```

## Step 1: Disable Public Signup

You don't want visitors creating accounts. In `.env`:

```bash
SMALLSTACK_SIGNUP_ENABLED=False
```

## Step 2: Create Your Base Template

Create `templates/mytheme/base.html` with your own CSS framework. Two pieces are required for dark mode and palette persistence, both `<script src>` tags (the CSP refuses inline `<script>` blocks):

1. **`theme-init.js`** in `<head>` — sets the theme before first paint
2. **`config.js`, then `theme.js`** — `config.js`'s `data-theme-url` / `data-palette-url` are where the toggle saves a signed-in user's choice. Leave them out and the choice flips back on the next page load.

See [Adding Your Own Theme](/smallstack/help/smallstack/adding-your-own-theme/) for the full template with each piece marked.

A minimal example:

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{% endblock %} | {{ brand.name }}</title>
    <script src="{% static 'smallstack/js/theme-init.js' %}"
            data-user-theme="{% if user.is_authenticated and user.profile %}{{ user.profile.theme_preference }}{% endif %}"
            data-user-palette="{% if user.is_authenticated and user.profile %}{{ user.profile.color_palette }}{% endif %}"
            data-palette="{{ color_palette }}" data-default-palette="django"></script>
    <!-- Your CSS here -->
    {% block extra_css %}{% endblock %}
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
    {% block content %}{% endblock %}

    <script src="{% static 'smallstack/js/config.js' %}"
            data-user-theme="{% if user.is_authenticated and user.profile %}{{ user.profile.theme_preference }}{% endif %}"
            data-user-palette="{% if user.is_authenticated and user.profile %}{{ user.profile.color_palette }}{% endif %}"
            data-color-palette="{{ color_palette }}"
            data-authenticated="{% if user.is_authenticated %}true{% else %}false{% endif %}"
            data-theme-url="{% url 'theme_preference' %}"
            data-palette-url="{% url 'palette_preference' %}"></script>
    <script src="{% static 'smallstack/js/htmx.min.js' %}" defer></script>
    <script src="{% static 'smallstack/js/theme.js' %}"></script>
    {% block extra_js %}{% endblock %}
</body>
</html>
```

## Step 3: Update Your Homepage

Edit `templates/website/home.html` to extend your base instead of SmallStack's:

```html
{% extends "mytheme/base.html" %}

{% block title %}Home{% endblock %}

{% block content %}
<h1>Welcome to {{ brand.name }}</h1>
<p>Your public content here.</p>
{% endblock %}
```

Do the same for any other public pages (about, pricing, contact, etc.).

## Step 4: Set Login Redirect

The default `LOGIN_REDIRECT_URL` already points to `/smallstack/`, which is the SmallStack Dashboard. Staff members log in and land there. No change needed.

If you want the login page itself to live at a different URL, you can change `LOGIN_URL` in `config/settings/base.py`:

```python
LOGIN_URL = "/smallstack/accounts/login/"      # default
LOGIN_REDIRECT_URL = "/smallstack/"             # default — the Dashboard
LOGOUT_REDIRECT_URL = "/"                       # default — your homepage
```

## Step 5: Link Staff to Admin

Put a discreet admin link somewhere on your site — footer, hidden page, or just tell staff to bookmark `/smallstack/`. Example footer link:

```html
{% if user.is_staff %}
<a href="/smallstack/">Admin</a>
{% endif %}
```

Or simply don't link at all. Staff knows the URL.

## That's It

- Visitors see your theme, your pages, no login UI anywhere
- Staff navigates to `/smallstack/accounts/login/`, logs in, lands on the Dashboard
- From the Dashboard, staff accesses Explorer, Backups, Activity, Users, etc.
- Logout sends them back to your homepage

## Related

- [Adding Your Own Theme](/smallstack/help/smallstack/adding-your-own-theme/) — Full walkthrough with Bootstrap example
- [Settings & Configuration](/smallstack/help/smallstack/settings-configuration/) — All BRAND_* and SMALLSTACK_* settings
- [Authentication](/smallstack/help/smallstack/authentication/) — Signup control, login URLs
