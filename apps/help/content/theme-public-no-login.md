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

Create `templates/mytheme/base.html` with your own CSS framework. Three pieces are required for dark mode and palette persistence:

1. **Blocking theme script** in `<head>` (prevents flash of wrong theme)
2. **`window.SMALLSTACK` config object** before `theme.js`
3. **SmallStack's `theme.js`** script

See [Adding Your Own Theme](/help/smallstack/adding-your-own-theme/) for the full template with all three pieces marked.

A minimal example:

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{% endblock %} | {{ brand.name }}</title>
    <script>
    (function() {
        var theme = localStorage.getItem('smallstack-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', theme);
    })();
    </script>
    <!-- Your CSS here -->
    {% block extra_css %}{% endblock %}
</head>
<body>
    {% block content %}{% endblock %}

    <script>
    window.SMALLSTACK = {
        userTheme: null, userPalette: null,
        colorPalette: '{{ color_palette }}',
        isAuthenticated: {% if user.is_authenticated %}true{% else %}false{% endif %},
        sidebarEnabled: false, sidebarOpen: false, topbarNavEnabled: false
    };
    </script>
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

- [Adding Your Own Theme](/help/smallstack/adding-your-own-theme/) — Full walkthrough with Bootstrap example
- [Settings & Configuration](/help/smallstack/settings-configuration/) — All BRAND_* and SMALLSTACK_* settings
- [Authentication](/help/smallstack/authentication/) — Signup control, login URLs
