---
title: Building CRUD Pages
description: How to create management pages for your models using CRUDView and django-tables2
---

# Building CRUD Pages

> {{ project_name }}'s CRUDView was deeply inspired by [Neapolitan](https://github.com/carltongibson/neapolitan) by [Carlton Gibson](https://github.com/carltongibson) — a clean, declarative approach to generating Django CRUD views from a single class. Carlton is a former Django Fellow, maintainer of [Django REST Framework](https://www.django-rest-framework.org/) and [django-crispy-forms](https://github.com/django-crispy-forms/django-crispy-forms), and co-host of the [Django Chat](https://djangochat.com/) podcast. His work across the Django ecosystem has shaped how we think about building practical, reusable patterns — and Neapolitan's "quick CRUD views" concept is the direct ancestor of what you see here.

Once you have a Django model, {{ project_name }} gives you a fast path to a full management interface: a list page with sorting, search, and pagination, plus create, edit, and delete views. The pattern is declarative — you describe what you want in a single Python class, and the framework generates the views, URLs, templates, and wiring.

This guide walks through the process from simplest to most advanced, starting with the basics and layering in optional features.

## The Simplest Case

You need three things: a model, a table class, and a CRUDView config. Everything else is optional.

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

### 2. Define the Table

The table controls what columns appear in the list view, how they render, and what actions are available. {{ project_name }} provides three reusable column types in `apps.smallstack.tables`:

```python
# apps/myfeature/tables.py
import django_tables2 as tables

from apps.smallstack.tables import ActionsColumn, BooleanColumn, DetailLinkColumn

from .models import Widget


class WidgetTable(tables.Table):
    name = DetailLinkColumn(url_base="manage/widgets", link_view="update")
    is_active = BooleanColumn(verbose_name="Active")
    actions = ActionsColumn(url_base="manage/widgets")

    class Meta:
        model = Widget
        fields = ("name", "category", "is_active", "owner", "created_at")
        order_by = "-created_at"
        attrs = {"class": "crud-table"}   # Required for theme styling
```

| Column | What It Does |
|--------|-------------|
| `DetailLinkColumn` | Makes the cell value a clickable link. Set `link_view="update"` to link to the edit page, or `"detail"` for a read-only detail page. |
| `BooleanColumn` | Renders `True` as a themed checkmark and `False` as a dash. |
| `ActionsColumn` | Adds edit (pencil) and delete (trash) icon buttons. Pass `edit=False` or `delete=False` to hide either. |

All three take `url_base` — the same string you set on CRUDView. This is how columns know which URLs to link to.

### 3. Define the CRUDView

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
```

That's it. This single class generates four views and four URL patterns:

| URL | Name | Purpose |
|-----|------|---------|
| `/manage/widgets/` | `manage/widgets-list` | Sortable, paginated list |
| `/manage/widgets/new/` | `manage/widgets-create` | Create form |
| `/manage/widgets/<pk>/edit/` | `manage/widgets-update` | Edit form |
| `/manage/widgets/<pk>/delete/` | `manage/widgets-delete` | Delete confirmation |

### 4. Wire Up URLs

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

### 5. Register the App

```python
# config/settings/base.py
INSTALLED_APPS = [
    # ...
    "django_tables2",
    "apps.myfeature",
]
```

### 6. Run Migrations

```bash
uv run python manage.py makemigrations myfeature
uv run python manage.py migrate
```

At this point you have a working management interface. CRUDView provides generic templates for the list, form, and delete confirmation — they're basic but functional. The list page renders your table with sorting and pagination. The form page renders each field with labels, help text, and validation errors.

## What CRUDView Gives You for Free

Before writing any templates, CRUDView's generic templates handle:

- **List page** — card layout with your django-tables2 table, sorting, pagination, and an "Add" button
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
{% load theme_tags django_tables2 %}

{% block title %}Widgets{% endblock %}

{# Clear the breadcrumbs block — we use inline breadcrumbs in the title bar #}
{% block breadcrumbs %}{% endblock %}

{% block extra_css %}
{% include "smallstack/crud/_table_styles.html" %}
<style>
    .crud-table thead th a { color: var(--body-quiet-color); text-decoration: none; }
    .crud-table thead th a:hover { color: var(--primary); }
    .crud-table thead th.asc a::after { content: " \25B2"; font-size: 0.65rem; }
    .crud-table thead th.desc a::after { content: " \25BC"; font-size: 0.65rem; }
    ul.pagination {
        display: flex; justify-content: center; gap: 0.25rem;
        list-style: none !important; padding: 1rem 0 0 !important; margin: 0 !important;
    }
    ul.pagination li { list-style: none !important; }
    ul.pagination li a, ul.pagination li span {
        display: inline-block; padding: 0.3rem 0.75rem;
        border-radius: var(--radius-sm, 4px); color: var(--body-quiet-color);
        text-decoration: none; font-size: 0.85rem;
    }
    ul.pagination li a:hover {
        color: var(--primary);
        background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
    }
    ul.pagination li.active a, ul.pagination li.active span {
        background: var(--primary); color: var(--button-fg);
    }
</style>
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
        <a href="{{ create_view_url }}" class="btn"
           style="background: var(--primary); color: var(--button-fg);
                  padding: 0.5rem 1rem; border: none;
                  border-radius: var(--radius-sm, 4px);
                  text-decoration: none; font-size: 0.85rem;">
            + Add Widget
        </a>
        {% endif %}
    </div>
</div>

{# ── Table ── #}
{% if table %}
    {% render_table table %}
{% else %}
    <p style="color: var(--body-quiet-color); padding: 2rem 0; text-align: center;">
        No widgets found.
    </p>
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

## Adding Optional Features

The basic pattern above covers most needs. The following features are optional — add them only when the page benefits from them.

### HTMX Search

The search bar lets users filter the table without a page reload. It requires three things:

1. **A search partial template** — just the table, no page chrome
2. **A view override** — filter the queryset and return the partial for HTMX requests
3. **The search bar include** — a reusable template partial

**The partial** (`templates/myfeature/_widget_table.html`):

```html
{% load django_tables2 %}
{% if table %}
    {% render_table table %}
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
| `fields` | list | required | Fields for auto-generated forms |
| `url_base` | str | model name | URL prefix (e.g., `"manage/widgets"`) |
| `paginate_by` | int | None | Rows per page (10 is standard) |
| `mixins` | list | `[]` | View mixins applied to all views |
| `table_class` | Table class | None | django-tables2 Table for the list view |
| `form_class` | Form class | auto | Custom ModelForm (auto-generated if None) |
| `actions` | list | all 5 | Which CRUD actions to generate |
| `queryset` | QuerySet | `model.objects.all()` | Base queryset for all views |

### Actions

| Action | URL Pattern | View Type |
|--------|------------|-----------|
| `Action.LIST` | `url_base/` | ListView |
| `Action.CREATE` | `url_base/new/` | CreateView |
| `Action.DETAIL` | `url_base/<pk>/` | DetailView |
| `Action.UPDATE` | `url_base/<pk>/edit/` | UpdateView |
| `Action.DELETE` | `url_base/<pk>/delete/` | DeleteView |

You don't have to enable all five. A common pattern is `[Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]` — skipping the read-only detail view in favor of linking directly to the edit page via `DetailLinkColumn(link_view="update")`.

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
| **User Manager** | `/manage/users/` | Full CRUDView + tables2 + search + stat card drilldowns + custom edit form with tabs |
| **Backups** | `/backups/` | Title bar with action cards + stat cards + tabbed content + detail pages with timeline |
| **Activity Requests** | `/activity/requests/` | Title bar number cards + tabbed tables2 views + HTMX live refresh |
| **Activity Users** | `/activity/users/` | Title bar number cards + multiple tables per page |
| **Timezone Dashboard** | `/manage/users/timezones/` | Standalone tables2 + search (not CRUDView, but uses the same table/search pattern) |

The **User Manager** (`apps/usermanager/`) is the canonical reference for CRUDView. The **Backups** page demonstrates the pattern applied to a non-CRUDView context (custom views using the same visual conventions). The **Activity** pages show how far you can push tables2 with tabs and live refresh.

## Quick Checklist

When adding a new CRUD management page:

- [ ] Model in `apps/<appname>/models.py`
- [ ] Table class in `apps/<appname>/tables.py` with `attrs = {"class": "crud-table"}`
- [ ] CRUDView in `apps/<appname>/views.py` with `paginate_by = 10`
- [ ] URLs in `apps/<appname>/urls.py` using `*MyCRUDView.get_urls()`
- [ ] App registered in `INSTALLED_APPS` (and `"django_tables2"` if not already there)
- [ ] URL include in `config/urls.py`
- [ ] Sidebar link in `templates/smallstack/includes/sidebar.html`
- [ ] Migrations created and applied
- [ ] Tests for access control and table rendering
- [ ] Custom list template (optional — only if you want the title bar pattern)
- [ ] Search partial template (optional — only if you add HTMX search)

## See Also: Explorer

If you want CRUD views without writing any of the above, Explorer can auto-generate everything from your existing `ModelAdmin` registrations. Add `explorer_enabled = True` to your admin class and you get list, detail, create, update, and delete views at `/smallstack/explorer/`. Explorer's composability mixins also let you embed auto-generated CRUD tables into your own custom pages — bridging the gap between zero-config Explorer and fully custom CRUDView.

- [Explorer Overview](/smallstack/help/explorer/) — How Explorer works and when to use it
- [Enabling Models for Explorer](/smallstack/help/explorer/admin-api/) — ModelAdmin API reference
- [Composability Guide](/smallstack/help/explorer/composability/) — Embed Explorer tables into custom pages
