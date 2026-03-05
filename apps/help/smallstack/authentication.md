---
title: Authentication
description: Built-in Django authentication, signup control, and feature flags
---

# Authentication

{{ project_name }} uses **Django's built-in authentication system** — the same one that powers the admin. Login, logout, password reset, and signup all work out of the box with no extra packages.

## How It Works

Authentication is handled by Django's `django.contrib.auth` framework. SmallStack adds:

- A **custom User model** (`apps/accounts/models.py`) extending `AbstractBaseUser` for flexibility
- A **SignupView** (`apps/accounts/views.py`) for public registration
- Pre-styled **templates** in `templates/registration/` matching the SmallStack theme
- **Feature flags** to control login and signup visibility per project

### URL Routes

All auth URLs live under `/accounts/`:

| URL | Purpose | Source |
|-----|---------|--------|
| `/accounts/login/` | Log in | Django built-in |
| `/accounts/logout/` | Log out | Django built-in |
| `/accounts/signup/` | Create account | SmallStack `SignupView` |
| `/accounts/password_reset/` | Request reset email | Django built-in |
| `/accounts/password_change/` | Change password (logged in) | Django built-in |
| `/admin/` | Admin login | Django admin (always available) |

### Settings

```python
# config/settings/base.py
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
```

## Controlling Auth UI with Feature Flags

SmallStack provides two feature flags for controlling authentication visibility. This is useful for downstream projects that aren't ready for public signup, or internal tools that use a different auth flow.

### Available Flags

| Setting | Default | Effect |
|---------|---------|--------|
| `SMALLSTACK_LOGIN_ENABLED` | `True` | Shows/hides Login and Sign Up buttons in the topbar and "Log In Again" on the logged-out page |
| `SMALLSTACK_SIGNUP_ENABLED` | `True` | Shows/hides Sign Up button and signup link on the login page. Returns 404 for `/accounts/signup/` when disabled |

### Disable Public Signup

The most common case — you want staff to log in, but not allow anyone to create accounts:

```bash
# .env
SMALLSTACK_SIGNUP_ENABLED=False
```

Or in settings:

```python
# config/settings/base.py
SMALLSTACK_SIGNUP_ENABLED = False
```

**What changes:**
- Topbar shows **Login** button only (no Sign Up)
- Login page hides the "Don't have an account? Sign up" link
- `/accounts/signup/` returns **404**
- Admin login still works normally
- Existing users can still log in

### Disable Login UI

For projects that don't need public-facing login at all (e.g., a static marketing site):

```bash
# .env
SMALLSTACK_LOGIN_ENABLED=False
```

**What changes:**
- Topbar shows **neither** Login nor Sign Up buttons
- Logged-out page hides the "Log In Again" link
- `/accounts/login/` **still works** when accessed directly (admin depends on it)
- You can combine both flags to hide all auth UI

### Disable Both

```bash
# .env
SMALLSTACK_LOGIN_ENABLED=False
SMALLSTACK_SIGNUP_ENABLED=False
```

This hides all auth UI from the theme. Staff and admins can still navigate to `/accounts/login/` or `/admin/` directly.

## Full URL Removal (Advanced)

The feature flags above hide the **UI** but keep the URL routes registered. If you need to completely remove auth URLs (beyond just hiding buttons), you can modify `config/urls.py` in your downstream project:

### Remove Signup URL Entirely

```python
# config/urls.py
# Comment out or remove the signup path:

urlpatterns = [
    # path("accounts/signup/", SignupView.as_view(), name="signup"),  # Removed
    path("accounts/", include("django.contrib.auth.urls")),
    # ...
]
```

> **Note:** If you remove the signup URL, also remove any `{% url 'signup' %}` references in your templates, or Django will raise a `NoReverseMatch` error. The feature flag approach avoids this problem — the URL stays registered but returns 404.

### Remove All Auth URLs

```python
# config/urls.py
# Remove both signup and Django auth includes:

urlpatterns = [
    path("admin/", admin.site.urls),  # Keep admin (has its own login)
    # path("accounts/signup/", ...),  # Removed
    # path("accounts/", include("django.contrib.auth.urls")),  # Removed
    # ...
]
```

> **Warning:** Removing `django.contrib.auth.urls` breaks admin logout and password change. Only do this if you also remove the admin or provide your own auth views.

## How Feature Flags Work

The flags follow the same pattern as `SMALLSTACK_DOCS_ENABLED`:

1. **Setting** defined in `config/settings/base.py` with `python-decouple` (reads from `.env` or environment)
2. **Context processor** in `apps/smallstack/context_processors.py` exposes the flag to all templates
3. **Templates** use `{% if smallstack_signup_enabled %}` to conditionally render UI elements
4. **View** checks the flag in `dispatch()` and raises `Http404` when disabled (signup only)

### Template Variables

These are available in every template:

| Variable | Type | Description |
|----------|------|-------------|
| `smallstack_login_enabled` | bool | Whether login UI should be shown |
| `smallstack_signup_enabled` | bool | Whether signup UI should be shown |
| `smallstack_docs_enabled` | bool | Whether SmallStack reference docs are shown |

## Creating Users When Signup Is Disabled

With signup disabled, you can still create users through:

1. **Django Admin** — `/admin/` → Users → Add User
2. **Management command** — `uv run python manage.py createsuperuser`
3. **Dev superuser** — `uv run python manage.py create_dev_superuser` (uses `.env` credentials)
4. **Django shell** — `User.objects.create_user("username", password="...")`

## Protecting Views

Regardless of feature flag settings, protect views that require authentication:

```python
# Function-based views
from django.contrib.auth.decorators import login_required

@login_required
def dashboard(request):
    return render(request, "dashboard.html")

# Class-based views
from django.contrib.auth.mixins import LoginRequiredMixin

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"
```

## Next Steps

- [Email Authentication](/help/smallstack/email-auth/) — Configure SMTP, password reset, and email login
- [Settings & Configuration](/help/smallstack/settings-configuration/) — How environment variables and feature flags work
- [Customization Guide](/help/smallstack/customization/) — Make SmallStack your own
