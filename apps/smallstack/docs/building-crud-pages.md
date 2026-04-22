---
title: Building CRUD Pages
description: How to create management pages for your models using CRUDView with built-in sortable tables
---

# Building CRUD Pages

> {{ project_name }}'s CRUDView was deeply inspired by [Neapolitan](https://github.com/carltongibson/neapolitan) by [Carlton Gibson](https://github.com/carltongibson) — a clean, declarative approach to generating Django CRUD views from a single class. Carlton is a former Django Fellow, maintainer of [Django REST Framework](https://www.django-rest-framework.org/) and [django-crispy-forms](https://github.com/django-crispy-forms/django-crispy-forms), and co-host of the [Django Chat](https://djangochat.com/) podcast. His work across the Django ecosystem has shaped how we think about building practical, reusable patterns — and Neapolitan's "quick CRUD views" concept is the direct ancestor of what you see here.

Once you have a Django model, {{ project_name }} gives you a fast path to a full management interface: a list page with sorting, search, and pagination, plus create, edit, and delete views. The pattern is declarative — you describe what you want in a single Python class, and the framework generates the views, URLs, templates, and wiring.

This guide walks through the process from simplest to most advanced, starting with the basics and layering in optional features.

## The Simplest Case

You need two things: a model and a CRUDView config. The built-in `TableDisplay` handles sorting, pagination, and rendering automatically. Everything else is optional.

### 1. Define Your Model

```python
# apps/myfeature/models.py
from django.conf import settings
from django.db import models

class Widget(models.Model):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
```

### 2. Define the CRUDView

```python
# apps/myfeature/views.py
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import TableDisplay
from apps.smallstack.mixins import StaffRequiredMixin

from .models import Widget


class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active", "owner"]
    list_fields = ["name", "category", "is_active", "owner", "created_at"]
    url_base = "manage/widgets"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    displays = [TableDisplay]
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
```

The built-in `TableDisplay` renders a sortable table with clickable column headers (for model-backed fields), themed styling, and pagination. The first field in `list_fields` links to the detail view by default (set `link_field` to change this).

That's it. This single class generates four views and four URL patterns (no separate `tables.py` needed):

| URL | Name | Purpose |
|-----|------|---------|
| `/manage/widgets/` | `manage/widgets-list` | Sortable, paginated list |
| `/manage/widgets/new/` | `manage/widgets-create` | Create form |
| `/manage/widgets/<pk>/edit/` | `manage/widgets-update` | Edit form |
| `/manage/widgets/<pk>/delete/` | `manage/widgets-delete` | Delete confirmation |

### 3. Wire Up URLs

```python
# apps/myfeature/urls.py
from .views import WidgetCRUDView

urlpatterns = [
    *WidgetCRUDView.get_urls(),
]
```

Register in your main URL config:

```python
# config/urls.py
urlpatterns = [
    # ...existing urls...
    path("", include("apps.myfeature.urls")),
]
```

### 4. Register the App

```python
# config/settings/base.py
INSTALLED_APPS = [
    # ...
    "apps.myfeature",
]
```

### 5. Run Migrations

```bash
uv run python manage.py makemigrations myfeature
uv run python manage.py migrate
```

At this point you have a working management interface. CRUDView provides generic templates for the list, form, and delete confirmation — they're basic but functional. The list page renders your table with sorting and pagination. The form page renders each field with labels, help text, and validation errors.

## What CRUDView Gives You for Free

Before writing any templates, CRUDView's generic templates handle:

- **List page** — card layout with sortable table, pagination, and an "Add" button
- **Create/Edit form** — styled form with labels, help text, error messages, Save and Cancel buttons
- **Delete confirmation** — "Are you sure?" prompt with Delete and Cancel buttons
- **Breadcrumbs** — automatic Home / Model Name / Action breadcrumbs
- **Context collision protection** — if your model is named `User`, the context variable becomes `crud_user` to avoid shadowing Django's `request.user`

This is enough for many internal tools. You only need custom templates when you want the title bar pattern, stat cards, search, or other enhancements.

## The Management Page Pattern

For staff-facing management pages, {{ project_name }} uses a consistent layout across all built-in apps. Here's what it looks like on the User Manager:

![User Manager list page](/static/smallstack/docs/images/crud-user-list.png)

Every management list page follows this structure:

```
┌──────────────────────────────────────────────────────────────────┐
│  Title                                    [Card] [Card] [Button] │
│  Subtitle (optional)                                             │
│  Home / Section / Page                                           │
└──────────────────────────────────────────────────────────────────┘
  ┌─────────┐ ┌─────────┐ ┌─────────┐        ← Stat cards (opt.)
  │   24    │ │    5    │ │    3    │
  │  Total  │ │  Staff  │ │ Recent  │
  └─────────┘ └─────────┘ └─────────┘
  ┌─────────────────────────────────────┐     ← Search bar (opt.)
  │ 🔍 Search widgets...                │
  └─────────────────────────────────────┘
  ┌─────────────────────────────────────┐     ← Sortable table
  │ NAME ▲    CATEGORY    ACTIVE    ✎ 🗑 │
  │ ...                                 │
  └─────────────────────────────────────┘
  │              1  2  3  next          │     ← Pagination
```

To use this pattern, you write a custom list template instead of using the generic one.

### Custom List Template

```html
{# templates/myfeature/widget_list.html #}
{% extends "smallstack/base.html" %}
{% load theme_tags crud_tags %}

{% block title %}Widgets{% endblock %}

{# Clear the breadcrumbs block — we use inline breadcrumbs in the title bar #}
{% block breadcrumbs %}{% endblock %}

{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}
{% endblock %}

{% block content %}
{# ── Title Bar ── #}
<div style="background: color-mix(in srgb, var(--primary) 15%, var(--body-bg));
            margin: -24px -24px 24px -24px; padding: 24px;
            border-radius: 8px 8px 0 0;
            display: flex; align-items: center; justify-content: space-between;">
    <div>
        <h1>Widgets</h1>
        <nav style="margin-top: 0.5rem; font-size: 0.8rem;">
            <a href="{% url 'website:home' %}"
               style="color: var(--body-quiet-color); text-decoration: none;">Home</a>
            <span style="color: var(--body-quiet-color); margin: 0 0.3rem;">/</span>
            <span style="color: var(--body-fg);">Widgets</span>
        </nav>
    </div>
    <div style="display: flex; gap: 0.5rem; align-items: center;">
        {% if create_view_url %}
        <a href="{{ create_view_url }}" class="btn-primary"
           style="text-decoration: none; font-size: 0.85rem;">
            + Add Widget
        </a>
        {% endif %}
    </div>
</div>

{# ── Table (rendered by display or crud_table tag) ── #}
{% if display_template %}
    {% include display_template %}
{% else %}
    {% crud_table %}
{% endif %}
{% endblock %}
```

Then tell CRUDView to use it:

```python
class WidgetCRUDView(CRUDView):
    # ...same config as before...

    @classmethod
    def _get_template_names(cls, suffix):
        if suffix == "list":
            return ["myfeature/widget_list.html"]
        return super()._get_template_names(suffix)
```

This gives you the title bar with breadcrumbs and an Add button, while the create/edit/delete views still use the generic templates. You can override those too when needed.

## Detail Pages

Detail pages follow the same title bar pattern but show information about a single record instead of a table. Here's the Backup detail page:

![Backup detail page](/static/smallstack/docs/images/crud-backup-detail.png)

The right side of the title bar shows **summary cards** with key values — status, size, or other at-a-glance data. These use a slightly smaller font (1.1rem) than the list page stat cards (1.5rem) since they're showing item-level data rather than aggregate counts.

The User edit page shows another variation — tabbed content with Account, Profile, and Activity sections:

![User edit page](/static/smallstack/docs/images/crud-user-edit.png)

### Title Bar Cards for Detail Pages

```html
<div style="text-align: center; padding: 8px 16px;
     background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
     border-radius: var(--radius-sm, 6px);">
    <div style="font-size: 1.1rem; font-weight: 700;
         color: var(--primary);">{{ value }}</div>
    <div style="font-size: 0.7rem; color: var(--body-quiet-color);
         text-transform: uppercase; letter-spacing: 0.3px;">Label</div>
</div>
```

### Related Object Tabs

When a model has reverse FK relationships (other models with ForeignKeys pointing to it), the detail page automatically shows a tabbed section below the detail card. Each tab displays a paginated table of related objects with links to their own detail pages.

Tabs are auto-discovered by default — only relations whose related model has a registered CRUDView (standalone or via Explorer) appear. No configuration needed for the common case.

```python
class CustomerCRUDView(CRUDView):
    model = Customer
    fields = ["name", "email"]
    url_base = "manage/customers"
    # Default: related_tabs = None (auto-discover)
    # Or explicitly control which tabs appear and their order:
    related_tabs = ["order_set", "invoice_set"]
    related_tabs_exclude = ["internal_note_set"]  # hide specific tabs
    related_tabs_paginate_by = 20  # default is 10
```

Set `related_tabs = False` to disable tabs entirely for a CRUDView.

The tab content loads lazily via HTMX — only the active tab fetches data. Tab counts are the only eager queries. The FK field pointing back to the parent is automatically hidden from table columns.

## Adding Optional Features

The basic pattern above covers most needs. The following features are optional — add them only when the page benefits from them.

### HTMX Search

The search bar lets users filter the table without a page reload. It requires three things:

1. **A search partial template** — just the table, no page chrome
2. **A view override** — filter the queryset and return the partial for HTMX requests
3. **The search bar include** — a reusable template partial

**The partial** (`templates/myfeature/_widget_table.html`):

```html
{% load crud_tags %}
{% if object_list %}
    {% crud_table %}
{% else %}
    <p style="color: var(--body-quiet-color); padding: 2rem 0;
              text-align: center;">No widgets found.</p>
{% endif %}
```

**The view override** — add to your CRUDView class:

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

**In the list template** — add the search bar and wrap the table:

```html
{% include "smallstack/includes/search_bar.html" with placeholder="Search widgets..." target="#search-results" %}

<div id="search-results">
{% include "myfeature/_widget_table.html" %}
</div>
```

The search bar fires on keyup with a 300ms debounce, pushes the query to the URL, and swaps just the table content.

### Dashboard Stat Cards

Stat cards show aggregate counts above the table. They can be plain display or clickable with modal drilldowns.

![Backups page with stat cards](/static/smallstack/docs/images/crud-backups.png)

**Plain stat card** (display only):

```html
<div class="card">
    <div class="card-body" style="text-align: center; padding: 14px 8px;">
        <div style="font-size: 1.75rem; font-weight: 700;
             color: var(--primary);">{{ stats.total }}</div>
        <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Total</div>
    </div>
</div>
```

**Clickable stat card** (opens a modal with detail):

```html
<div class="card stat-card-clickable"
     hx-get="{% url 'myfeature:stat-detail' 'total' %}"
     hx-target="#stat-modal-body"
     onclick="openStatModal('All Widgets')">
    <div class="card-body" style="text-align: center; padding: 14px 8px;">
        <div style="font-size: 1.75rem; font-weight: 700;
             color: var(--primary);">{{ stats.total }}</div>
        <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Total</div>
    </div>
</div>
```

For clickable cards, you need:

1. Add `{% include "smallstack/includes/stat_modal.html" %}` at the bottom of your content block
2. Create a view that returns an HTML table fragment for the drilldown content
3. Wire the URL (e.g., `path("manage/widgets/stats/<str:stat_type>/", stat_detail_view, name="myfeature:stat-detail")`)

The stat modal is a fixed-size popup (80% width, 520px height) that loads content via HTMX when the card is clicked.

### Title Bar Number Cards

For list pages, you may want summary numbers in the title bar itself (not as separate stat cards). The Activity Requests page uses this pattern:

![Activity requests with title bar cards](/static/smallstack/docs/images/crud-activity-requests.png)

```html
<div style="display: flex; gap: 0.5rem; align-items: center;">
    <div style="text-align: center; padding: 8px 16px;
         background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
         border-radius: var(--radius-sm, 6px);">
        <div style="font-size: 1.5rem; font-weight: 700;
             color: var(--primary);">{{ total_count }}</div>
        <div style="font-size: 0.7rem; color: var(--body-quiet-color);
             text-transform: uppercase;">Total</div>
    </div>
</div>
```

Use title bar cards for high-level summary numbers. Use stat cards (below the title bar) when you want clickable drilldowns or more cards than fit in the title bar.

### Tabs

The Activity Requests page uses tabs to show different views of the same data (Recent, Top Paths, Errors, By Method). Tabs are useful when a single page has multiple related views that share the same title bar context.

### Custom Form Templates

The generic form template works for simple CRUD. For complex forms (multiple related models, tabs, custom layout), override the template:

```python
@classmethod
def _get_template_names(cls, suffix):
    if suffix == "form":
        return ["myfeature/widget_form.html"]
    if suffix == "list":
        return ["myfeature/widget_list.html"]
    return super()._get_template_names(suffix)
```

The User Manager demonstrates this — its edit form has three tabs (Account, Profile, Activity) that each render different forms and data.

## CRUDView Reference

### Configuration Options

| Option | Type | Default | Purpose |
|--------|------|---------|---------|
| `model` | Model class | required | The Django model |
| `admin_class` | ModelAdmin | `None` | Config source — reads `list_display`, `search_fields`, `list_per_page`, etc. |
| `fields` | list | required* | Fields for forms (*auto-resolved from `admin_class` if set) |
| `list_fields` | list | `None` | List view columns (falls back to `admin_class.list_display` or `fields`) |
| `detail_fields` | list | `None` | Detail view fields (falls back to `admin_class.fields`/`fieldsets` or `fields`) |
| `url_base` | str | model name | URL prefix (e.g., `"manage/widgets"`) |
| `paginate_by` | int | None | Rows per page (falls back to `admin_class.list_per_page`) |
| `mixins` | list | `[]` | View mixins applied to all views |
| `column_widths` | dict | `None` | Custom column proportions, e.g. `{"name": "30%", "description": "50%"}` |
| `ordering_fields` | list | `[]` | Fields allowed for column sorting (defaults to sortable list_fields) |
| `form_class` | Form class | auto | Custom ModelForm (auto-generated if None) |
| `actions` | list | all 5 | Which CRUD actions to generate |
| `queryset` | QuerySet | `model.objects.all()` | Base queryset for all views |
| `displays` | list | `[]` | Display classes for list view (enables palette) |
| `detail_displays` | list | `[]` | Display classes for detail view |
| `bulk_actions` | list | `["delete"]` | Bulk actions on list view. Options: `"delete"`, `"update"`. Set to `[]` to disable. |
| `related_tabs` | `list\|None\|False` | `None` | Related object tabs on detail page. `None`=auto-discover, list=explicit, `False`=disabled |
| `related_tabs_exclude` | list | `[]` | Accessor names to exclude from auto-discovery |
| `related_tabs_paginate_by` | int | `10` | Rows per tab in related object tabs |
| `enable_api` | bool | `False` | Generate REST API endpoints |
| `search_fields` | list | `[]` | API search fields (falls back to `admin_class.search_fields`) |
| `export_formats` | list | `[]` | API export formats: `["csv", "json"]` |

### Using admin_class

Instead of defining `fields`, `list_fields`, and `paginate_by` separately, you can point CRUDView at a `ModelAdmin`:

```python
from django.contrib import admin
from apps.smallstack.crud import CRUDView
from apps.smallstack.mixins import StaffRequiredMixin

class WidgetAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_active", "created_at"]
    fields = ["name", "category", "is_active", "owner"]
    search_fields = ["name", "category"]
    list_per_page = 10

class WidgetCRUDView(CRUDView):
    admin_class = WidgetAdmin
    model = Widget
    url_base = "manage/widgets"
    mixins = [StaffRequiredMixin]
    enable_api = True
```

CRUDView reads `list_display` for list columns, `fields` for forms, `search_fields` for API search, and `list_per_page` for pagination. You can still override any of these with explicit CRUDView attributes — they take precedence over admin_class.

### Actions

| Action | URL Pattern | View Type |
|--------|------------|-----------|
| `Action.LIST` | `url_base/` | ListView |
| `Action.CREATE` | `url_base/new/` | CreateView |
| `Action.DETAIL` | `url_base/<pk>/` | DetailView |
| `Action.UPDATE` | `url_base/<pk>/edit/` | UpdateView |
| `Action.DELETE` | `url_base/<pk>/delete/` | DeleteView |

You don't have to enable all five. A common pattern is `[Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]` — skipping the read-only detail view in favor of linking directly to the edit page.

### Template Resolution

CRUDView looks for templates in this order:

1. **App-specific:** `<app_label>/crud/<model_name>_<suffix>.html` (e.g., `myfeature/crud/widget_list.html`)
2. **Generic fallback:** `smallstack/crud/object_<suffix>.html`

The `crud/` subdirectory prevents collisions with public-facing templates that use Django's standard naming convention (e.g., `myfeature/widget_detail.html` for a public view won't be picked up by the CRUD system).

Override `_get_template_names(cls, suffix)` to customize. The suffix is one of: `list`, `detail`, `form`, `confirm_delete`.

### Overriding View Behavior

The `_make_view` classmethod is your hook for injecting custom logic into any generated view. It receives the base view class and returns a modified version:

```python
@classmethod
def _make_view(cls, base_class):
    from apps.smallstack.crud import _CRUDListBase, _CRUDUpdateBase

    view_class = super()._make_view(base_class)

    if base_class is _CRUDListBase:
        # Customize the list view...
        pass
    elif base_class is _CRUDUpdateBase:
        # Customize the update view...
        pass

    return view_class
```

Available base classes: `_CRUDListBase`, `_CRUDCreateBase`, `_CRUDDetailBase`, `_CRUDUpdateBase`, `_CRUDDeleteBase`.

## Sidebar Link

Add your page to the sidebar in `templates/smallstack/includes/sidebar.html`:

```html
<li class="nav-item">
    <a href="{% url 'manage/widgets-list' %}"
       class="nav-link {% if '/manage/widgets/' in request.path %}active{% endif %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="...your icon..."/>
        </svg>
        <span>Widgets</span>
    </a>
</li>
```

Place it in the ADMIN section (inside `{% if user.is_staff %}`) for staff-only pages, or in the main nav for user-facing pages.

## Tests

Test the essential behaviors — access control, table rendering, and any custom logic:

```python
# apps/myfeature/tests.py
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff", password="testpass123", is_staff=True
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

    def test_table_in_context(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/widgets-list"))
        assert "table" in response.context

    def test_search_filters_results(self, client, staff_user):
        # ...create test widgets, search by name, verify filtered results...
        pass

    def test_htmx_returns_partial(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(
            reverse("manage/widgets-list"),
            HTTP_HX_REQUEST="true",
        )
        content = response.content.decode()
        # Partial should not contain full page chrome
        assert "<html" not in content

    def test_breadcrumbs(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/widgets-list"))
        content = response.content.decode()
        assert "Home" in content
        assert "Widgets" in content
```

## Reference Implementations

These built-in apps demonstrate the pattern at different complexity levels:

| Page | URL | What It Demonstrates |
|------|-----|---------------------|
| **User Manager** | `/manage/users/` | Full CRUDView + search + stat card drilldowns + custom edit form with tabs |
| **Backups** | `/backups/` | Title bar with action cards + stat cards + tabbed content + detail pages with timeline |
| **Activity Requests** | `/activity/requests/` | Title bar number cards + tabbed sortable tables + HTMX live refresh |
| **Activity Users** | `/activity/users/` | Title bar number cards + multiple tables per page |
| **Timezone Dashboard** | `/manage/users/timezones/` | Standalone sortable table + search (not CRUDView, but uses the same table/search pattern) |

The **User Manager** (`apps/usermanager/`) is the canonical reference for CRUDView. The **Backups** page demonstrates the pattern applied to a non-CRUDView context (custom views using the same visual conventions). The **Activity** pages show sortable manual tables with tabs and live refresh.

## Quick Checklist

When adding a new CRUD management page:

- [ ] Model in `apps/<appname>/models.py`
- [ ] CRUDView in `apps/<appname>/views.py` with `displays = [TableDisplay]` and `paginate_by = 10`
- [ ] URLs in `apps/<appname>/urls.py` using `*MyCRUDView.get_urls()`
- [ ] App registered in `INSTALLED_APPS`
- [ ] URL include in `config/urls.py`
- [ ] Sidebar link in `templates/smallstack/includes/sidebar.html`
- [ ] Migrations created and applied
- [ ] Tests for access control and table rendering
- [ ] Custom list template (optional — only if you want the title bar pattern)
- [ ] Search partial template (optional — only if you add HTMX search)

## Bulk Actions

CRUDView list pages include bulk delete by default. When users select rows via checkboxes, a compact action bar appears with the selection count and a "Delete" button.

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"

    # Default — bulk delete enabled (like Django admin)
    bulk_actions = ["delete"]

    # Enable both delete and update
    bulk_actions = ["delete", "update"]

    # Disable bulk actions
    bulk_actions = []
```

Bulk delete processes each object individually, catching `ProtectedError` per row so that FK-constrained objects report errors while the rest are deleted.

When using `admin_class`, set `explorer_bulk_actions` on the ModelAdmin instead — CRUDView reads it automatically.

## Display Palette

CRUDView supports the same display palette as Explorer. Configure multiple displays and users can swap between them at runtime:

```python
from apps.smallstack.displays import (
    TableDisplay, CardDisplay, AvatarCardDisplay, CalendarDisplay,
)

class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    displays = [
        TableDisplay,
        CardDisplay,  # zero-config key-value card grid using list_fields
        # Or, for records with a hero field + image:
        # AvatarCardDisplay(title_field="name", subtitle_field="category"),
        # Or, for models with a date/datetime field:
        # CalendarDisplay(date_field="scheduled_for", title_field="name"),
    ]
```

When `displays` has more than one entry, a palette of icon buttons appears above the table. Clicking an icon swaps the display via HTMX. The user's choice is saved to localStorage and persists across page navigation.

You can also create custom displays — maps, charts, or any visualization. See [Explorer Composability](/smallstack/help/smallstack/explorer-composability/) for the full display protocol.

## REST API

Add `enable_api = True` to generate JSON endpoints alongside the HTML views:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    enable_api = True
    search_fields = ["name", "category"]
    export_formats = ["csv", "json"]
```

This adds:

| Method | URL | Action |
|--------|-----|--------|
| `GET` | `/api/manage/widgets/` | List (paginated, searchable) |
| `POST` | `/api/manage/widgets/` | Create |
| `GET` | `/api/manage/widgets/<pk>/` | Detail |
| `PUT/PATCH` | `/api/manage/widgets/<pk>/` | Update |
| `DELETE` | `/api/manage/widgets/<pk>/` | Delete |

See [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) for authentication, testing, and the full API guide.

### Beyond CRUD

For endpoints that don't map to a model — actions, webhooks, reports, multi-step workflows — use the `@api_view` decorator. It provides the same authentication, error format, and token system without requiring a CRUDView:

```python
from apps.smallstack.api import api_view, api_error

@api_view(methods=["POST"], require_staff=True)
def run_sync(request):
    count = sync_from_external(request.json["target"])
    return {"synced": count}
```

Wire it up in your `urls.py` like any Django view. See [Explorer REST API — Custom API Endpoints](/smallstack/help/smallstack/explorer-rest-api/#custom-api-endpoints) for the full guide.

## See Also: Explorer

If you want CRUD views without writing any of the above, Explorer can auto-generate everything from `ModelAdmin` registrations — including the display palette, REST API, and CSV export. Register a model with `explorer.register()` and you get the full stack at `/smallstack/explorer/`.

- [Model Explorer](/smallstack/help/smallstack/explorer/) — Overview, registration, and display palette
- [Explorer ModelAdmin API](/smallstack/help/smallstack/explorer-admin-api/) — Full attribute reference
- [Explorer Composability](/smallstack/help/smallstack/explorer-composability/) — Embed Explorer displays into custom pages
- [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) — Auto-generated JSON API with search and export
