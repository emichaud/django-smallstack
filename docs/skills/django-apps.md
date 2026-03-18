# Skill: Django Apps & CRUD Management Views

This skill describes how to create Django apps and build management CRUD pages following SmallStack conventions.

## Overview

SmallStack uses a modular app structure with all custom apps in `apps/`. For model management pages, the standard is **CRUDView + django-tables2**, producing consistent admin-style pages with a title bar, searchable sortable tables, dashboard stat cards, and modal drilldowns.

## Project Structure

```
django-smallstack/
├── apps/                      # All custom Django apps
│   ├── accounts/              # User model & authentication
│   ├── smallstack/           # Theme helpers, CRUD library, reusable tables
│   ├── profile/               # User profiles
│   ├── help/                  # Documentation system
│   ├── tasks/                 # Background tasks
│   ├── activity/              # Request activity tracking
│   ├── heartbeat/             # Uptime monitoring
│   ├── usermanager/           # User CRUD + timezone dashboard (reference impl)
│   ├── explorer/              # Model Explorer auto-CRUD system
│   └── website/               # Project-specific pages
├── config/                    # Project configuration
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── templates/                 # All templates
│   ├── smallstack/
│   │   ├── includes/         # Topbar, sidebar, search_bar, stat_modal
│   │   └── crud/             # _table_styles.html, _form_styles.html
│   ├── <appname>/            # App-specific templates
│   └── <appname>/partials/   # HTMX partial templates
└── static/                    # Static files
    └── smallstack/            # Core theme, brand, help assets
```

## Creating a CRUD Management Page (Standard Pattern)

This is the standard approach for building model management pages. Follow the **usermanager** app as the reference implementation.

### Step 1: Create the App

```bash
mkdir -p apps/myfeature
touch apps/myfeature/__init__.py
```

```python
# apps/myfeature/apps.py
from django.apps import AppConfig

class MyfeatureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.myfeature"
    verbose_name = "My Feature"
```

### Step 2: Create the Model

```python
# apps/myfeature/models.py
from django.conf import settings
from django.db import models

class Widget(models.Model):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="widgets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Widget"
        verbose_name_plural = "Widgets"

    def __str__(self):
        return self.name
```

### Step 3: Create the Table (django-tables2)

Define a `tables.py` using the reusable column types from `apps.smallstack.tables`:

```python
# apps/myfeature/tables.py
import django_tables2 as tables
from django.utils.html import format_html

from apps.smallstack.tables import ActionsColumn, BooleanColumn, DetailLinkColumn

from .models import Widget


class WidgetTable(tables.Table):
    """Sortable table for the Widget management page."""

    # Link column — clicking the name goes to the edit page
    name = DetailLinkColumn(url_base="manage/widgets", link_view="update")

    # Boolean column — renders ✓ / —
    is_active = BooleanColumn(verbose_name="Active")

    # Custom rendered column
    category = tables.Column(verbose_name="Category")

    # Actions column — edit + delete icons
    actions = ActionsColumn(url_base="manage/widgets")

    class Meta:
        model = Widget
        fields = ("name", "category", "is_active", "owner", "created_at")
        order_by = "-created_at"
        attrs = {"class": "crud-table"}  # Required for theme styling

    def render_category(self, value):
        """Example custom renderer."""
        if not value:
            return format_html('<span style="color: var(--body-quiet-color);">—</span>')
        return value
```

**Available reusable columns** (`apps.smallstack.tables`):

| Column | Purpose |
|--------|---------|
| `DetailLinkColumn(url_base, link_view="detail")` | Wraps cell in a link to detail/update view |
| `BooleanColumn(true_mark="✓", false_mark="—")` | Renders boolean with themed checkmarks |
| `ActionsColumn(url_base, edit=True, delete=True)` | Edit/Delete icon links |

### Step 4: Create the CRUDView

```python
# apps/myfeature/views.py
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin

from .models import Widget
from .tables import WidgetTable


class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active", "owner"]
    url_base = "manage/widgets"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    table_class = WidgetTable
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]

    @classmethod
    def _get_template_names(cls, suffix):
        """Override to use custom templates."""
        if suffix == "list":
            return ["myfeature/widget_list.html"]
        # Fall back to generic CRUD templates for form/detail
        return super()._get_template_names(suffix)
```

**CRUDView options:**

| Option | Purpose |
|--------|---------|
| `model` | Django model class |
| `fields` | Fields for auto-generated forms |
| `url_base` | URL prefix (generates `manage/widgets/`, `manage/widgets/new/`, etc.) |
| `paginate_by` | Rows per page (10 is standard) |
| `mixins` | View mixins (`StaffRequiredMixin`, `LoginRequiredMixin`) |
| `table_class` | django-tables2 Table class (enables sorting, themed rendering) |
| `form_class` | Custom ModelForm (optional, auto-generated if not set) |
| `actions` | Which CRUD actions to enable |

**Generated URL patterns** (from `get_urls()`):

| URL | Name | View |
|-----|------|------|
| `manage/widgets/` | `manage/widgets-list` | ListView |
| `manage/widgets/new/` | `manage/widgets-create` | CreateView |
| `manage/widgets/<pk>/` | `manage/widgets-detail` | DetailView |
| `manage/widgets/<pk>/edit/` | `manage/widgets-update` | UpdateView |
| `manage/widgets/<pk>/delete/` | `manage/widgets-delete` | DeleteView |

### Step 5: Add Search (Optional)

Override `_make_view` to add HTMX search filtering:

```python
    @classmethod
    def _make_view(cls, base_class):
        from apps.smallstack.crud import _CRUDListBase

        view_class = super()._make_view(base_class)

        if base_class is _CRUDListBase:
            def get_queryset(self):
                qs = super(view_class, self).get_queryset()
                q = self.request.GET.get("q", "").strip()
                if q:
                    from django.db.models import Q
                    qs = qs.filter(
                        Q(name__icontains=q) | Q(category__icontains=q)
                    )
                return qs

            def get_context_data(self, **kwargs):
                context = super(view_class, self).get_context_data(**kwargs)
                context["search_query"] = self.request.GET.get("q", "")
                return context

            def get_template_names(self):
                if self.request.headers.get("HX-Request"):
                    return ["myfeature/_widget_table.html"]
                return super(view_class, self).get_template_names()

            view_class.get_queryset = get_queryset
            view_class.get_context_data = get_context_data
            view_class.get_template_names = get_template_names

        return view_class
```

### Step 6: Create the URL Config

```python
# apps/myfeature/urls.py
from django.urls import path

from .views import WidgetCRUDView

urlpatterns = [
    *WidgetCRUDView.get_urls(),
]
```

Register in `config/urls.py`:

```python
urlpatterns = [
    # ...existing urls...
    path("", include("apps.myfeature.urls")),
]
```

### Step 7: Create the List Template

The list page follows the **manager title bar** pattern:

```html
{# templates/myfeature/widget_list.html #}
{% extends "smallstack/base.html" %}
{% load theme_tags crud_tags django_tables2 %}

{% block title %}Widgets{% endblock %}

{% block breadcrumbs %}{% endblock %}

{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}
<style>
    /* django-tables2 sort indicators */
    .crud-table thead th a { color: var(--body-quiet-color); text-decoration: none; }
    .crud-table thead th a:hover { color: var(--primary); }
    .crud-table thead th.asc a::after { content: " \25B2"; font-size: 0.65rem; }
    .crud-table thead th.desc a::after { content: " \25BC"; font-size: 0.65rem; }
    /* django-tables2 pagination */
    .table-container ul.pagination,
    ul.pagination {
        display: flex; justify-content: center; gap: 0.25rem;
        list-style: none !important; padding: 1rem 0 0 !important; margin: 0 !important;
    }
    .table-container ul.pagination li,
    ul.pagination li { list-style: none !important; }
    .table-container ul.pagination li a,
    .table-container ul.pagination li span,
    ul.pagination li a,
    ul.pagination li span {
        display: inline-block; padding: 0.3rem 0.75rem;
        border-radius: var(--radius-sm, 4px); color: var(--body-quiet-color);
        text-decoration: none; font-size: 0.85rem;
    }
    .table-container ul.pagination li a:hover,
    ul.pagination li a:hover {
        color: var(--primary);
        background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
    }
    .table-container ul.pagination li.active a,
    .table-container ul.pagination li.active span,
    ul.pagination li.active a,
    ul.pagination li.active span {
        background: var(--primary); color: var(--button-fg);
    }
</style>
{% endblock %}

{% block content %}
{# ── Title Bar ── #}
<div class="page-header-with-actions" style="background: color-mix(in srgb, var(--primary) 15%, var(--body-bg)); margin: -24px -24px 24px -24px; padding: 24px; border-radius: 8px 8px 0 0; display: flex; align-items: center; justify-content: space-between;">
    <div class="page-header-content">
        <h1>Widgets</h1>
        <nav style="margin-top: 0.5rem; font-size: 0.8rem;">
            <a href="{% url 'website:home' %}" style="color: var(--body-quiet-color); text-decoration: none;">Home</a>
            <span style="color: var(--body-quiet-color); margin: 0 0.3rem;">/</span>
            <span style="color: var(--body-fg);">Widgets</span>
        </nav>
    </div>
    <div style="display: flex; gap: 0.5rem; align-items: center;">
        {% if create_view_url %}
        <a href="{{ create_view_url }}" class="btn" style="background: var(--primary); color: var(--button-fg); padding: 0.5rem 1rem; border: none; border-radius: var(--radius-sm, 4px); text-decoration: none; font-size: 0.85rem;">
            + Add Widget
        </a>
        {% endif %}
    </div>
</div>

{# ── Dashboard Stat Cards (optional) ── #}
{# Cards can be plain display or clickable with modal drilldowns #}
<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 24px;">
    <div class="card stat-card-clickable"
         hx-get="{% url 'myfeature:stat-detail' 'total' %}"
         hx-target="#stat-modal-body"
         onclick="openStatModal('All Widgets')">
        <div class="card-body" style="text-align: center; padding: 14px 8px;">
            <div style="font-size: 1.75rem; font-weight: 700; color: var(--primary);">{{ stats.total }}</div>
            <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Total</div>
        </div>
    </div>
    <div class="card stat-card-clickable"
         hx-get="{% url 'myfeature:stat-detail' 'active' %}"
         hx-target="#stat-modal-body"
         onclick="openStatModal('Active Widgets')">
        <div class="card-body" style="text-align: center; padding: 14px 8px;">
            <div style="font-size: 1.75rem; font-weight: 700; color: var(--success-fg);">{{ stats.active }}</div>
            <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Active</div>
        </div>
    </div>
    <div class="card">
        <div class="card-body" style="text-align: center; padding: 14px 8px;">
            <div style="font-size: 1.75rem; font-weight: 700; color: var(--body-fg);">{{ stats.categories }}</div>
            <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Categories</div>
        </div>
    </div>
</div>

{# ── Search Bar (optional, requires _make_view search override) ── #}
{% include "smallstack/includes/search_bar.html" with placeholder="Search widgets..." target="#search-results" %}

{# ── Table ── #}
<div id="search-results">
{% include "myfeature/_widget_table.html" %}
</div>

{# ── Stat Modal (required if using stat-card-clickable cards) ── #}
{% include "smallstack/includes/stat_modal.html" %}
{% endblock %}
```

### Step 8: Create the Table Partial (for HTMX)

```html
{# templates/myfeature/_widget_table.html #}
{% load django_tables2 %}
{% if table %}
    {% render_table table %}
{% else %}
    <p style="color: var(--body-quiet-color); padding: 2rem 0; text-align: center;">
        No widgets found.
        {% if create_view_url %}
        <a href="{{ create_view_url }}" style="color: var(--primary);">Create one now?</a>
        {% endif %}
    </p>
{% endif %}
```

### Step 9: Register in Settings

```python
# config/settings/base.py
INSTALLED_APPS = [
    # ...existing apps...
    "apps.myfeature",
]
```

### Step 10: Add to Sidebar

Edit `templates/smallstack/includes/sidebar.html` — add a nav item in the admin section:

```html
<li class="nav-item">
    <a href="{% url 'manage/widgets-list' %}" class="nav-link {% if '/manage/widgets/' in request.path %}active{% endif %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="..."/>
        </svg>
        <span>Widgets</span>
    </a>
</li>
```

### Step 11: Run Migrations

```bash
uv run python manage.py makemigrations myfeature
uv run python manage.py migrate
```

### Step 12: Write Tests

```python
# apps/myfeature/tests.py
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staffuser", email="staff@example.com",
        password="testpass123", is_staff=True,
    )

class TestWidgetListView:
    def test_requires_staff(self, client, db):
        user = User.objects.create_user(username="regular", password="testpass123")
        client.force_login(user)
        response = client.get(reverse("manage/widgets-list"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/widgets-list"))
        assert response.status_code == 200

    def test_has_table_context(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/widgets-list"))
        assert "table" in response.context

    def test_breadcrumbs_present(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/widgets-list"))
        content = response.content.decode()
        assert "Home" in content
        assert "Widgets" in content
```

## Title Bar Pattern Reference

Every management page uses this consistent title bar structure:

```
┌──────────────────────────────────────────────────────────────────┐
│  Title                                    [Card] [Card] [Card]  │
│  Subtitle (optional)                                            │
│  Home / Section / Page                                          │
└──────────────────────────────────────────────────────────────────┘
```

**Left side:** Title (h1), optional subtitle, inline breadcrumbs
**Right side:** Dashboard number cards, action buttons, or links

**Title bar number cards** (used in title bar right side):
```html
<div style="text-align: center; padding: 8px 16px; background: color-mix(in srgb, var(--primary) 10%, var(--body-bg)); border-radius: var(--radius-sm, 6px);">
    <div style="font-size: 1.5rem; font-weight: 700; color: var(--primary);">{{ count }}</div>
    <div style="font-size: 0.7rem; color: var(--body-quiet-color); text-transform: uppercase; letter-spacing: 0.3px;">Label</div>
</div>
```

**Dashboard stat cards** (clickable, below title bar):
```html
<div class="card stat-card-clickable"
     hx-get="{% url 'app:stat-detail' 'key' %}"
     hx-target="#stat-modal-body"
     onclick="openStatModal('Title')">
    <div class="card-body" style="text-align: center; padding: 14px 8px;">
        <div style="font-size: 1.75rem; font-weight: 700; color: var(--primary);">{{ value }}</div>
        <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Label</div>
    </div>
</div>
```

## Stat Modal Drilldowns

To enable clickable stat cards that pop up a detail modal:

1. Include the modal template: `{% include "smallstack/includes/stat_modal.html" %}`
2. Add `class="stat-card-clickable"` to the card
3. Add `hx-get="url"` and `hx-target="#stat-modal-body"` for HTMX content loading
4. Add `onclick="openStatModal('Title')"` to set the modal title
5. Create a backend view that returns an HTML table fragment

The modal is 80% page width with a fixed height (~12 rows), consistent across all pages.

## HTMX Search Pattern

The reusable search bar provides progressive filtering without page reload:

```html
{% include "smallstack/includes/search_bar.html" with placeholder="Search..." target="#search-results" %}
```

**Requirements:**
- View must check `request.GET.get("q")` and filter the queryset
- View must add `search_query` to context
- View must return a table partial for HTMX requests (`request.headers.get("HX-Request")`)
- Table must be wrapped in a `<div id="search-results">` target

## Existing App Reference

### usermanager (Reference Implementation)

Full CRUD management page with all patterns:

| File | Purpose |
|------|---------|
| `views.py` | `UserCRUDView` + search + profile form + activity stats |
| `tables.py` | `UserTable` with DetailLink, Boolean, Actions columns |
| `forms.py` | `UserAccountForm`, `UserProfileForm` |
| `timezone_views.py` | Standalone dashboard with tables2 + HTMX search |
| `urls.py` | CRUDView URLs + timezones + stat detail endpoint |
| `tests.py` | Permission, search, breadcrumb, context tests |

### activity

Request logging and analytics with tabbed views:

| File | Purpose |
|------|---------|
| `tables.py` | `RecentRequestsTable`, `TopPathsTable` (tables2) |
| `views.py` | `RequestListView` (tabs with HTMX), `UserActivityView` |

### accounts

| File | Purpose |
|------|---------|
| `models.py` | Custom User model (AbstractBaseUser) |
| `views.py` | SignupView |

### smallstack

Core library — theme helpers, CRUD framework, reusable tables:

| File | Purpose |
|------|---------|
| `crud.py` | `CRUDView`, `Action` — generates views + URLs from config |
| `tables.py` | `BooleanColumn`, `DetailLinkColumn`, `ActionsColumn` |
| `mixins.py` | `StaffRequiredMixin` |
| `pagination.py` | `paginate_queryset` helper |
| `templatetags/theme_tags.py` | Breadcrumbs, nav_active, localtime_tooltip |

### profile

| File | Purpose |
|------|---------|
| `models.py` | UserProfile (photo, bio, theme, timezone) |
| `views.py` | Profile CRUD views |
| `signals.py` | Auto-create profile on user creation |

### help

| File | Purpose |
|------|---------|
| `content/` | Markdown documentation files |
| `utils.py` | Markdown processing |
| `views.py` | HelpIndexView, HelpDetailView |

### tasks

| File | Purpose |
|------|---------|
| `tasks.py` | Background task definitions (django-tasks-db) |

### website

| File | Purpose |
|------|---------|
| `views.py` | `home_view`, `about_view` — project-specific pages |

## Best Practices

1. **Use CRUDView + tables2** for all model management pages
2. **Use `StaffRequiredMixin`** for admin/management views
3. **Use `LoginRequiredMixin`** for user-facing views
4. **Always set `attrs = {"class": "crud-table"}`** on Table Meta for theme styling
5. **Set `paginate_by = 10`** as the standard page size
6. **Include breadcrumbs** in the title bar (not the breadcrumbs block)
7. **Empty the breadcrumbs block** (`{% block breadcrumbs %}{% endblock %}`) when using inline breadcrumbs
8. **Reference user with `settings.AUTH_USER_MODEL`** — never direct import
9. **Namespace URLs** — use `app_name` in urls.py or `url_base` prefix in CRUDView
10. **Support HTMX** — return partials for `HX-Request` headers
11. **Use `|pluralize`** on count labels (e.g., `{{ count }} Widget{{ count|pluralize }}`)
12. **Only use hand-written tables** when the use case requires manual customization beyond what tables2 provides
