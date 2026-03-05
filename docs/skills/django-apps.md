# Skill: Django Apps Structure

This skill describes how to create and organize Django apps following SmallStack conventions.

## Overview

SmallStack uses a modular app structure with all custom apps in the `apps/` directory. Each app follows Django conventions with consistent naming and organization.

## Project Structure

```
django-smallstack/
├── apps/                      # All custom Django apps
│   ├── accounts/              # User model & authentication
│   ├── smallstack/           # Theme helpers (pure presentation)
│   ├── profile/               # User profiles
│   ├── help/                  # Documentation system
│   └── tasks/                 # Background tasks
├── config/                    # Project configuration
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── templates/                 # All templates
│   ├── smallstack/
│   │   ├── includes/         # Topbar, sidebar, messages
│   │   └── pages/            # SmallStack marketing content
│   ├── website/              # Page wrappers (thin include wrappers)
│   ├── profile/
│   └── help/
└── static/                    # Static files
    ├── smallstack/            # Core theme, brand, help assets (upstream)
    ├── brand/                 # Project brand assets (downstream)
    ├── css/                   # Project CSS overrides (downstream)
    └── js/                    # Project JS (downstream)
```

## Naming Convention

- **App directories:** Simple names in `apps/` folder (e.g., `profile`, `help`, `accounts`)
- **Templates:** Match app name in `templates/` folder
- **Static files:** Match app name in `static/` folder
- **URL namespaces:** Use app name (e.g., `help:index`, `profile`)

## Creating a New App

### Step 1: Create Directory Structure

```bash
mkdir -p apps/myfeature
touch apps/myfeature/__init__.py
```

### Step 2: Create apps.py

```python
# apps/myfeature/apps.py

from django.apps import AppConfig


class MyfeatureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.myfeature"
    verbose_name = "My Feature"
```

### Step 3: Create models.py

```python
# apps/myfeature/models.py

from django.db import models
from django.conf import settings


class MyModel(models.Model):
    """Description of the model."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mymodels"
    )
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "My Model"
        verbose_name_plural = "My Models"

    def __str__(self):
        return self.title
```

### Step 4: Create views.py

```python
# apps/myfeature/views.py

from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy

from .models import MyModel
from .forms import MyModelForm


class MyModelListView(LoginRequiredMixin, ListView):
    model = MyModel
    template_name = "myfeature/mymodel_list.html"
    context_object_name = "items"

    def get_queryset(self):
        return MyModel.objects.filter(user=self.request.user)


class MyModelDetailView(LoginRequiredMixin, DetailView):
    model = MyModel
    template_name = "myfeature/mymodel_detail.html"
    context_object_name = "item"


class MyModelCreateView(LoginRequiredMixin, CreateView):
    model = MyModel
    form_class = MyModelForm
    template_name = "myfeature/mymodel_form.html"
    success_url = reverse_lazy("myfeature:list")

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)
```

### Step 5: Create forms.py

```python
# apps/myfeature/forms.py

from django import forms
from .models import MyModel


class MyModelForm(forms.ModelForm):
    class Meta:
        model = MyModel
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "vTextField",
                "placeholder": "Enter title"
            }),
        }
```

### Step 6: Create urls.py

```python
# apps/myfeature/urls.py

from django.urls import path
from . import views

app_name = "myfeature"

urlpatterns = [
    path("", views.MyModelListView.as_view(), name="list"),
    path("create/", views.MyModelCreateView.as_view(), name="create"),
    path("<int:pk>/", views.MyModelDetailView.as_view(), name="detail"),
]
```

### Step 7: Create admin.py (optional)

```python
# apps/myfeature/admin.py

from django.contrib import admin
from .models import MyModel


@admin.register(MyModel)
class MyModelAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["title", "user__username"]
    ordering = ["-created_at"]
```

### Step 8: Register in Settings

Edit `config/settings/base.py`:

```python
INSTALLED_APPS = [
    "apps.accounts",
    "apps.smallstack",
    "apps.profile",
    "apps.help",
    "apps.tasks",
    "apps.myfeature",  # Add here

    "django.contrib.admin",
    # ...
]
```

### Step 9: Add URL Routing

Edit `config/urls.py`:

```python
urlpatterns = [
    # ...existing urls...
    path("myfeature/", include("apps.myfeature.urls")),
]
```

### Step 10: Create Templates

```
templates/myfeature/
├── mymodel_list.html
├── mymodel_detail.html
└── mymodel_form.html
```

**Example template:**

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}My Feature{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "home" %}
{% breadcrumb "My Feature" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <h2>My Feature</h2>
    </div>
    <div class="card-body">
        {% for item in items %}
            <p>{{ item.title }}</p>
        {% empty %}
            <p>No items yet.</p>
        {% endfor %}
    </div>
</div>
{% endblock %}
```

### Step 11: Run Migrations

```bash
uv run python manage.py makemigrations myfeature
uv run python manage.py migrate
```

## Existing App Reference

### accounts

User authentication and custom User model:

| File | Purpose |
|------|---------|
| `models.py` | Custom User model (AbstractBaseUser) |
| `views.py` | SignupView |
| `forms.py` | SignupForm |
| `admin.py` | UserAdmin configuration |

### smallstack

Pure presentation - theme helpers only (no models):

| File | Purpose |
|------|---------|
| `templatetags/theme_tags.py` | Breadcrumbs, nav_active |
| `context_processors.py` | Branding, palette data, site config |
| `palettes.yaml` | Color palette registry (metadata for UI) |
| `management/commands/` | create_dev_superuser |

### profile

User profile management:

| File | Purpose |
|------|---------|
| `models.py` | UserProfile (photo, bio, theme_preference, color_palette, etc.) |
| `views.py` | ProfileView, ProfileEditView, ProfileDetailView, ThemePreferenceView, PalettePreferenceView |
| `forms.py` | UserProfileForm |
| `signals.py` | Auto-create profile on user creation |

### help

Documentation system:

| File | Purpose |
|------|---------|
| `content/` | Markdown documentation files |
| `utils.py` | Markdown processing |
| `views.py` | HelpIndexView, HelpDetailView |

### tasks

Background tasks using Django 6 Tasks framework:

| File | Purpose |
|------|---------|
| `tasks.py` | Task definitions (send_email_task, etc.) |

## htmx View Pattern

SmallStack includes htmx for progressive enhancement. When adding views that should support both full-page and htmx partial responses, use `request.htmx`:

```python
# apps/myfeature/views.py

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

from .models import MyModel


class MyModelListView(LoginRequiredMixin, ListView):
    model = MyModel
    context_object_name = "items"

    def get_template_names(self):
        if self.request.htmx:
            return ["myfeature/partials/mymodel_table.html"]
        return ["myfeature/mymodel_list.html"]
```

The partial template (`partials/mymodel_table.html`) returns just the content fragment. The full template (`mymodel_list.html`) extends `base.html` and includes the full page layout.

See [htmx-patterns.md](htmx-patterns.md) for CSRF handling, OOB messages, and more examples.

## Best Practices

1. **Use class-based views** - More reusable and consistent
2. **Include `__str__`** - Always define for models
3. **Add Meta class** - Define ordering and verbose names
4. **Use LoginRequiredMixin** - Protect views that need auth
5. **Reference user with settings.AUTH_USER_MODEL** - Not direct import
6. **Create signals.py** - For auto-creation patterns (like profiles)
7. **Namespace URLs** - Use `app_name` in urls.py
8. **Match template folder to app name** - Keep organized
9. **Support htmx** - Use `request.htmx` for dual-response views when adding interactive features

## Signals Pattern

For auto-creating related objects:

```python
# apps/myfeature/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

from .models import MyModel


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_mymodel(sender, instance, created, **kwargs):
    if created:
        MyModel.objects.create(user=instance)
```

Register in apps.py:

```python
class MyfeatureConfig(AppConfig):
    # ...

    def ready(self):
        import apps.myfeature.signals  # noqa
```
