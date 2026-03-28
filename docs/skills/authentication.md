# Skill: Authentication System

This skill describes the authentication system in SmallStack, including the custom user model, auth views, and extending authentication.

## Overview

SmallStack uses Django's built-in authentication with a **custom User model** for maximum flexibility. The custom model extends `AbstractBaseUser` and `PermissionsMixin` and lives in the `accounts` app.

## File Locations

```
apps/accounts/
├── models.py              # Custom User model
├── admin.py               # UserAdmin configuration
├── views.py               # SignupView
└── forms.py               # SignupForm

apps/smallstack/
└── management/commands/
    └── create_dev_superuser.py

templates/registration/
├── login.html
├── logout.html
├── password_reset_form.html
├── password_reset_done.html
├── password_reset_confirm.html
├── password_reset_complete.html
└── signup.html

config/settings/base.py    # AUTH_USER_MODEL setting
config/urls.py             # Auth URL routing
```

## Custom User Model

Located in `apps/accounts/models.py`:

```python
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, username, email=None, password=None, **extra_fields):
        if not username:
            raise ValueError("Username is required")
        email = self.normalize_email(email) if email else None
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.username

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username
```

### Settings Configuration

```python
# config/settings/base.py
AUTH_USER_MODEL = "accounts.User"
```

## URL Configuration

Auth views live inside `apps/smallstack/site_urls.py`, which is mounted at `/smallstack/`:

```python
# apps/smallstack/site_urls.py (relevant lines)
path("accounts/", include("django.contrib.auth.urls")),
path("accounts/signup/", SignupView.as_view(), name="signup"),
```

This produces canonical auth URLs under `/smallstack/accounts/`:

| URL | Name | Purpose |
|-----|------|---------|
| `/smallstack/accounts/login/` | `login` | Login form |
| `/smallstack/accounts/logout/` | `logout` | Logout |
| `/smallstack/accounts/signup/` | `signup` | Registration |
| `/smallstack/accounts/password_reset/` | `password_reset` | Password reset flow |

### Public Auth Aliases

`config/urls.py` also registers convenience redirects so `/accounts/login/` works for downstream projects that want cleaner public URLs:

```python
# config/urls.py (public convenience aliases)
path("accounts/login/", RedirectView.as_view(pattern_name="login", permanent=False)),
path("accounts/logout/", RedirectView.as_view(pattern_name="logout", permanent=False)),
path("accounts/signup/", RedirectView.as_view(pattern_name="signup", permanent=False)),
```

Downstream projects can remove these aliases or replace them with direct views.

## Auth Settings

```python
# config/settings/base.py

LOGIN_URL = "/smallstack/accounts/login/"
LOGIN_REDIRECT_URL = "/smallstack/"
LOGOUT_REDIRECT_URL = "/"

# Auth feature flags (default True, configurable via .env)
SMALLSTACK_LOGIN_ENABLED = config("SMALLSTACK_LOGIN_ENABLED", default=True, cast=bool)
SMALLSTACK_SIGNUP_ENABLED = config("SMALLSTACK_SIGNUP_ENABLED", default=True, cast=bool)
```

Downstream projects that use the public aliases can override `LOGIN_URL` to `/accounts/login/` in their settings.

## Auth Feature Flags

Two flags control auth UI visibility:

- `SMALLSTACK_LOGIN_ENABLED` — hides Login/Sign Up buttons from topbar and "Log In Again" from logged-out page
- `SMALLSTACK_SIGNUP_ENABLED` — hides Sign Up button/link and returns 404 on `/accounts/signup/`

Flags are exposed to templates via context processor (`smallstack_login_enabled`, `smallstack_signup_enabled`).

The signup view checks the flag in `dispatch()`:

```python
# apps/accounts/views.py
def dispatch(self, request, *args, **kwargs):
    if not getattr(django_settings, "SMALLSTACK_SIGNUP_ENABLED", True):
        raise Http404
    if request.user.is_authenticated:
        return redirect("home")
    return super().dispatch(request, *args, **kwargs)
```

Login disabled is UI-only — `/accounts/login/` still works (admin depends on it).

## Views

### SignupView

```python
# apps/accounts/views.py

from django.views.generic import CreateView
from django.contrib.auth import login
from django.urls import reverse_lazy
from .forms import SignupForm


class SignupView(CreateView):
    form_class = SignupForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response
```

### SignupForm

```python
# apps/accounts/forms.py

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "vTextField"
```

## Protecting Views

### Function-Based Views

```python
from django.contrib.auth.decorators import login_required

@login_required
def my_view(request):
    return render(request, "my_template.html")
```

### Class-Based Views

```python
from django.contrib.auth.mixins import LoginRequiredMixin

class MyView(LoginRequiredMixin, TemplateView):
    template_name = "my_template.html"
```

### Staff Only

```python
from django.contrib.auth.mixins import UserPassesTestMixin

class StaffOnlyView(UserPassesTestMixin, TemplateView):
    template_name = "staff_only.html"

    def test_func(self):
        return self.request.user.is_staff
```

## Template Context

In templates, the user is always available:

```html
{% if user.is_authenticated %}
    <p>Welcome, {{ user.username }}!</p>
    <a href="{% url 'logout' %}">Logout</a>
{% else %}
    <a href="{% url 'login' %}">Login</a>
    <a href="{% url 'signup' %}">Sign Up</a>
{% endif %}
```

## Adding Fields to User Model

### Step 1: Add Field

```python
# apps/accounts/models.py

class User(AbstractBaseUser, PermissionsMixin):
    # ...existing fields...
    phone_number = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=200, blank=True)
```

### Step 2: Create Migration

```bash
make migrations          # Or: uv run python manage.py makemigrations accounts
make migrate
```

### Step 3: Update Admin

```python
# apps/accounts/admin.py

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "email", "phone_number", "company")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
```

## Email Login (Optional)

To allow login with email instead of username:

### Create Backend

```python
# apps/accounts/backends.py

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        try:
            if "@" in username:
                user = User.objects.get(email__iexact=username)
            else:
                user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            User().set_password(password)  # Timing attack mitigation
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
```

### Register Backend

```python
# config/settings/base.py

AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]
```

## Password Reset

Already configured. Requires email settings:

**Development (console):**
```python
# config/settings/development.py
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

**Production (SMTP):**
```python
# config/settings/production.py
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST")
EMAIL_PORT = config("EMAIL_PORT", cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD")
```

## Create Dev Superuser

Custom management command for development:

```bash
uv run python manage.py create_dev_superuser
```

Uses credentials from `.env`:
```bash
DEV_SUPERUSER_USERNAME=admin
DEV_SUPERUSER_PASSWORD=change-me-for-dev
DEV_SUPERUSER_EMAIL=admin@example.com
```

## User Profile Relationship

The `profile` app extends user data:

```python
# apps/profile/models.py

class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile"
    )
    theme_preference = models.CharField(max_length=10, choices=THEME_CHOICES, default="dark")
    color_palette = models.CharField(max_length=20, choices=COLOR_PALETTE_CHOICES, default="", blank=True)
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    profile_photo = models.ImageField(upload_to="profiles/photos/", blank=True, null=True)
    background_photo = models.ImageField(upload_to="profiles/backgrounds/", blank=True, null=True)
    # ... location, website, date_of_birth
```

Access in templates:
```html
{{ user.profile.bio }}
{{ user.profile.theme_preference }}
{{ user.profile.color_palette }}
{% if user.profile.profile_photo %}
    <img src="{{ user.profile.profile_photo.url }}">
{% endif %}
```

## API Authentication

SmallStack includes Bearer token authentication for the REST API layer. See the `api` skill for full details.

### Token Creation

```bash
# Via CLI
uv run python manage.py create_api_token <username>
```

### Programmatic Login (SPA / Mobile)

```
POST /api/auth/token/
Content-Type: application/json

{"username": "alice", "password": "secret123"}

→ 200: {"token": "aBcD1234...", "user": {"id": 1, "username": "alice", "is_staff": true}}
→ 400: {"errors": {"__all__": ["username and password are required"]}}
→ 401: {"errors": {"__all__": ["Invalid credentials"]}}
```

The endpoint uses Django's `authenticate()` under the hood, so custom auth backends (e.g., email login) work automatically.

### Using the Token

```bash
curl -H "Authorization: Bearer <token>" https://example.com/api/manage/widgets/
```

### Token Refresh

Login tokens can be refreshed via `POST /api/auth/token/refresh/` — this regenerates the key and extends the expiry. The old key immediately stops working. Only login tokens can be refreshed; manual tokens are rejected. See the `api` skill for full details.

### User Management API

Auth-level tokens can list, search, and update users via `GET /api/auth/users/` and `PATCH /api/auth/users/<id>/`. See the `api` skill for full details.

### What's Not Included (By Design)

- No JSON password reset — stays HTML/email flow

These are intentionally omitted to keep SmallStack simple. If you need full REST auth flows, add `dj-rest-auth` — it coexists without conflicts.

## Best Practices

1. **Always use `settings.AUTH_USER_MODEL`** - Not direct User import
2. **Use `get_user_model()`** - For runtime user model access
3. **Extend with profiles** - Keep User model lean
4. **Hash passwords properly** - Use `set_password()`, never store plain text
5. **Use mixins** - `LoginRequiredMixin` for class-based views
6. **Check `is_active`** - Disabled users shouldn't authenticate
