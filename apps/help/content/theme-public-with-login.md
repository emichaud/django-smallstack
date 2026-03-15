---
title: "Scenario B: Public Site with User Login"
description: "Users log in and use your app with your theme. Staff accesses SmallStack tools via a link."
---

# Scenario B: Public Site with User Login

You have a public site where users sign up, log in, and use your app — all styled with your own theme. Staff also needs access to SmallStack's admin tools (Dashboard, Explorer, Backups, etc.).

## What You're Building

```
Public pages:     Your theme (homepage, pricing, etc.)
User pages:       Your theme (dashboard, settings, etc.)
Login/Signup:     Your theme
After login:      Your app's start page (e.g., /dashboard/)
Admin tools:      SmallStack theme (via /smallstack/ link)
```

## Step 1: Create Your Base Template

Same as Scenario A — create `templates/mytheme/base.html` with your CSS framework and the three required SmallStack pieces (blocking theme script, `window.SMALLSTACK`, `theme.js`).

See [Adding Your Own Theme](/help/smallstack/adding-your-own-theme/) for the full template.

## Step 2: Set Login Redirect to Your App

Users should land on *your* app after login, not SmallStack's Dashboard. In `config/settings/base.py`:

```python
LOGIN_REDIRECT_URL = "/dashboard/"    # Your app's start page
LOGOUT_REDIRECT_URL = "/"             # Your homepage
```

## Step 3: Create Your Login Page (Optional)

By default, SmallStack's login page lives at `/smallstack/accounts/login/` and uses the SmallStack theme. If you want the login page to match your theme, override the template.

Create `templates/registration/login.html`:

```html
{% extends "mytheme/base.html" %}

{% block title %}Sign In{% endblock %}

{% block content %}
<div class="login-container">
    <h2>Sign In</h2>
    <form method="post">
        {% csrf_token %}
        {{ form.as_p }}
        <button type="submit">Sign In</button>
    </form>
    {% if SMALLSTACK_SIGNUP_ENABLED %}
    <p>Don't have an account? <a href="{% url 'signup' %}">Sign up</a></p>
    {% endif %}
</div>
{% endblock %}
```

The login URL doesn't need to change — Django will find your template override automatically.

## Step 4: Build Your User-Facing Pages

All your app pages extend your base template and live in `apps/website/`:

```html
{% extends "mytheme/base.html" %}

{% block title %}Dashboard{% endblock %}

{% block content %}
<!-- Your app content, your CSS, your way -->
{% endblock %}
```

Protected pages use `LoginRequiredMixin` or `@login_required`:

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

class UserDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "website/dashboard.html"
```

## Step 5: Expose SmallStack Admin Tools

Staff needs a way to reach SmallStack's admin tools. Two options:

### Option A: Admin Link in Your Navigation

Add a link to `/smallstack/` in your navbar (visible to staff only):

```html
{% if user.is_staff %}
<a href="/smallstack/">Admin Tools</a>
{% endif %}
```

When staff clicks it, they'll transition to the SmallStack theme and see the Dashboard with links to Explorer, Backups, Activity, Users, etc.

### Option B: Admin Dropdown

For a richer experience, link directly to specific tools:

```html
{% if user.is_staff %}
<div class="dropdown">
    <button>Admin</button>
    <ul>
        <li><a href="/smallstack/">Dashboard</a></li>
        <li><a href="/smallstack/explorer/">Explorer</a></li>
        <li><a href="/smallstack/activity/">Activity</a></li>
        <li><a href="/smallstack/backups/">Backups</a></li>
    </ul>
</div>
{% endif %}
```

## Step 6: Configure Navigation

SmallStack's sidebar and topbar only appear on SmallStack-themed pages. Your pages use your own navigation. Users move between:

```
Your pages (/dashboard/, /settings/)  →  your navbar
SmallStack (/smallstack/*)            →  SmallStack sidebar + topbar
```

The transition is seamless — same session, same dark mode preference, same user.

## That's It

- Public visitors see your theme
- Users log in and land on your app's start page
- Staff clicks "Admin Tools" to reach SmallStack's Dashboard
- Both themes share dark mode, authentication, and session
- No CSS conflicts — each set of pages uses its own base template

## Related

- [Scenario A: Public Site, No User Login](/help/theme-public-no-login/) — Simpler version without user-facing auth
- [Scenario C: Build on SmallStack's Theme](/help/theme-build-on-smallstack/) — Use SmallStack's theme directly
- [Adding Your Own Theme](/help/smallstack/adding-your-own-theme/) — Full walkthrough with Bootstrap example
- [Authentication](/help/smallstack/authentication/) — Signup control, login URLs, protecting views
