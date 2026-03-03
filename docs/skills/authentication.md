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

apps/admin_theme/
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
    email = models.EmailField(blank=True, null=True)
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

```python
# config/urls.py

from django.contrib.auth import views as auth_views
from apps.accounts.views import SignupView

urlpatterns = [
    # Custom signup
    path("accounts/signup/", SignupView.as_view(), name="signup"),

    # Django's built-in auth views
    path("accounts/", include("django.contrib.auth.urls")),

    # This includes:
    # - accounts/login/
    # - accounts/logout/
    # - accounts/password_reset/
    # - accounts/password_reset/done/
    # - accounts/reset/<uidb64>/<token>/
    # - accounts/reset/done/
    # - accounts/password_change/
    # - accounts/password_change/done/
]
```

## Auth Settings

```python
# config/settings/base.py

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
```

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
uv run python manage.py makemigrations accounts
uv run python manage.py migrate
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
    bio = models.TextField(blank=True)
    photo = models.ImageField(upload_to="profiles/", blank=True)
```

Access in templates:
```html
{{ user.profile.bio }}
{% if user.profile.photo %}
    <img src="{{ user.profile.photo.url }}">
{% endif %}
```

## Best Practices

1. **Always use `settings.AUTH_USER_MODEL`** - Not direct User import
2. **Use `get_user_model()`** - For runtime user model access
3. **Extend with profiles** - Keep User model lean
4. **Hash passwords properly** - Use `set_password()`, never store plain text
5. **Use mixins** - `LoginRequiredMixin` for class-based views
6. **Check `is_active`** - Disabled users shouldn't authenticate
