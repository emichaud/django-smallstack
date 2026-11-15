# Skill: Django Apps & CRUD Management Views

This skill describes how to create Django apps and build management CRUD pages following SmallStack conventions.

## Overview

SmallStack uses a modular app structure with all custom apps in `apps/`. For model management pages, the standard is **CRUDView**: one class produces the list, detail, create, edit and delete pages (a sortable, resizable table with search and filters), and, when you switch them on, REST, MCP, search and webhooks for the same model. There is no `tables.py`: django-tables2 was removed in 0.12.0, and the list table is CRUDView's own `{% crud_table %}`. The full option reference is `docs/skills/crud-views.md`.

## Project Structure

```
django-smallstack/
├── apps/                      # All custom Django apps
│   ├── accounts/              # User model & authentication
│   ├── smallstack/           # Theme helpers, CRUD library (CRUDView, displays)
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
│   │   └── crud/             # Generic object_list/detail/form/confirm_delete pages
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

### Step 3: Create the CRUDView

The list table comes from the CRUDView itself: `list_fields` chooses the columns, `link_field` the
column that links to the row, `field_transforms` how a cell renders. No table class, no template.

```python
# apps/myfeature/views.py
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin

from .models import Widget


class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active", "owner"]           # the create/edit form
    list_fields = ["name", "category", "is_active", "owner", "created_at"]  # the table's columns
    link_field = "name"                                           # links each row to its page
    url_base = "manage/widgets"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    search_fields = ["name", "category"]                          # the list page's search box
    filter_fields = ["category", "is_active"]                     # the list page's filter dropdowns
```

That renders with the generic templates (`smallstack/crud/object_list.html` and friends), which
already carry the title bar, breadcrumbs, search, filters, pagination and row actions, themed for
every palette. To give a page your own template, add `templates/myfeature/crud/widget_list.html`
(`<app_label>/crud/<model_name>_<suffix>.html` is looked up first) or override
`_get_template_names` — see **Template Resolution** in `crud-views.md`.

**CRUDView options you'll reach for first** (the full table is in `crud-views.md`):

| Option | Purpose |
|--------|---------|
| `model` | Django model class |
| `fields` | Fields for the auto-generated create/edit form |
| `list_fields` / `link_field` | The table's columns / the column that links to the row |
| `url_base` | URL prefix (generates `manage/widgets/`, `manage/widgets/new/`, etc.) |
| `paginate_by` | Rows per page (10 is standard) |
| `mixins` | View mixins (`StaffRequiredMixin`, `LoginRequiredMixin`) |
| `model_permissions` | Also require Django's view/add/change/delete permission on every surface |
| `field_transforms` | How a field renders in the table and detail page |
| `form_class` | Custom ModelForm (optional, auto-generated if not set) |
| `actions` | Which CRUD actions to enable |

**Opt-in capability flags** (the SmallStack superpower — one boolean lights up a whole surface):

| Flag | What it lights up | Read first |
|---|---|---|
| `enable_explorer = True` | The model appears in `/smallstack/explorer/` for ad-hoc browsing without a hand-built admin page | `explorer.md` |
| `enable_api = True` | REST endpoints (`GET /list`, `GET /{id}`, `POST`, `PATCH`, `DELETE`) auto-emitted into `/api/docs/` Swagger UI | `custom-api-endpoints.md` |
| `enable_mcp = True` | MCP tools (`list_X`, `get_X`, `create_X`, ...) registered for Claude Desktop / Connectors UI | `mcp/build-mcp-solution.md` |
| `enable_search = True` | Keyword search via FTS5/PG-FTS, a `search_X` MCP tool, results in the topbar omnibar + `/smallstack/search/` page | `search.md` |
| `enable_webhooks = True` | Outbound webhook events (`<app>.<model>.created/updated/deleted`) fired to registered endpoints on every change, from any surface (HTML, REST, MCP, `sc`, ORM) | `webhooks.md` |

You almost always want at least `enable_api = True` + `enable_search = True`. Combined with `enable_mcp = True` they form the "one model → admin + REST + MCP + RAG" pattern that makes SmallStack distinct.

**Generated URL patterns** (from `get_urls()`):

| URL | Name | View |
|-----|------|------|
| `manage/widgets/` | `manage/widgets-list` | ListView |
| `manage/widgets/new/` | `manage/widgets-create` | CreateView |
| `manage/widgets/<pk>/` | `manage/widgets-detail` | DetailView |
| `manage/widgets/<pk>/edit/` | `manage/widgets-update` | UpdateView |
| `manage/widgets/<pk>/delete/` | `manage/widgets-delete` | DeleteView |

### Step 4: Opt into the unified search index

Add three lines to the CRUDView and the model gets:

- A working keyword search box on the list page (`search_fields` powers the toolbar `?q=`)
- A `search_widgets(query, limit)` MCP tool Claude can call
- Results in the topbar omnibar (Ctrl+K) and the dedicated `/smallstack/search/` page
- A row in the Swagger-style accordion on the search page so curious users can see the tool signature, REST endpoint, and live records

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    # ... fields/url_base/etc above ...
    enable_search = True
    search_fields = ["name", "category", "owner__username"]
    search_display = "name"            # row title in results
    search_subtitle = "category"       # secondary line
```

That's it. No `_make_view` override needed. The list-page `?q=` reuses the same `search_fields`, signals keep the index current on save/delete, and the MCP tool registers at startup. Read `search.md` before deciding which fields to index — it has the prescriptive patterns + anti-patterns.

**Heuristic for vibe coders**: if the model has a `name`, `title`, `description`, `body`, or any text field a human would type to find a record, opt in. If it's a junction table or purely numeric/datetime, don't.

### Step 5: Create the URL Config

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

### Step 6: Register in Settings

```python
# config/settings/base.py
INSTALLED_APPS = [
    # ...existing apps...
    "apps.myfeature",
]
```

### Step 7: Add to Sidebar

Register the nav entry from your `AppConfig.ready()` — **do not edit
`templates/smallstack/includes/sidebar.html`.** A hand-pasted `<li>` is ungated
(it shows for users who can't open the page), unordered, and overwritten by the
next base upgrade. `nav.register()` is the supported API and handles all three:

```python
# apps/widgets/apps.py
from django.apps import AppConfig


class WidgetsConfig(AppConfig):
    name = "apps.widgets"

    def ready(self) -> None:
        from apps.smallstack.navigation import nav

        nav.register(
            section="admin",              # which sidebar group
            label="Widgets",
            url_name="manage/widgets-list",
            icon_svg=(
                '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                '<path d="..."/></svg>'
            ),
            staff_required=True,          # hidden from non-staff
            active_prefix="/manage/widgets/",   # drives the `active` class (a tuple for several paths)
            order=50,                     # optional; lower sorts first
        )
```

Wrap it in `try/except Exception` with a logged warning if you want one broken
registration never to block startup — see `apps/approvals/apps.py` for the
house pattern. Full reference: `docs/skills/navigation.md`.

### Step 8: Run Migrations

```bash
make migrations                                    # Creates migrations for ALL apps
make migrate                                       # Applies pending migrations
```

> **Tip:** To create migrations for just your new app, use `uv run python manage.py makemigrations myfeature`. `make migrations` runs `makemigrations` without an app label, which picks up changes across all apps — fine in most cases.

### Step 9: Write Tests

```python
# apps/myfeature/tests.py
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.myfeature.models import Widget

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

    def test_lists_widgets(self, client, staff_user):
        Widget.objects.create(name="Sprocket", owner=staff_user)
        client.force_login(staff_user)
        response = client.get(reverse("manage/widgets-list"))
        assert "Sprocket" in response.content.decode()

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

The generic CRUD pages draw this for you. On a page of your own, use `.page-header-bleed`
(it takes `var(--accent-band-bg)`, which each palette tunes) rather than an inline
`color-mix(...)` background: AGENTS.md anti-pattern #3. For number cards use the
`{% stat_card %}` tag (`docs/skills/dashboard-cards.md`).

**Dashboard stat cards** (clickable, below title bar):
```html
<div class="card stat-card-clickable"
     hx-get="{% url 'app:stat-detail' 'key' %}"
     hx-target="#stat-modal-body"
     data-stat-modal="Title">
    <div class="card-body" style="text-align: center; padding: 14px 8px;">
        <div style="font-size: 1.75rem; font-weight: 700; color: var(--primary);">{{ value }}</div>
        <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Label</div>
    </div>
</div>
```

## Stat Modal Drilldowns

To enable clickable stat cards that pop up a detail modal:

1. Nothing to include on `smallstack/base.html`, which renders the modal. On a base template of your own, put `{% smallstack_modal %}` near the end of `<body>`
2. Add `class="stat-card-clickable"` to the card
3. Add `hx-get="url"` and `hx-target="#stat-modal-body"` for HTMX content loading
4. Add `data-stat-modal="Title"` to open the modal with that title (no inline `onclick` — theme.js handles the click; `data-stat-modal-close` on a button closes it)
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
| `forms.py` | `UserAccountForm`, `UserProfileForm` |
| `timezone_views.py` | Standalone dashboard with HTMX search |
| `urls.py` | CRUDView URLs + timezones + stat detail endpoint |
| `tests.py` | Permission, search, breadcrumb, context tests |

### activity

Request logging and analytics with tabbed views:

| File | Purpose |
|------|---------|
| `views.py` | `RequestListView` (tabs with HTMX), `UserActivityView` |

### accounts

| File | Purpose |
|------|---------|
| `models.py` | Custom User model (AbstractBaseUser) |
| `views.py` | SignupView |

### smallstack

Core library — theme helpers, the CRUD framework:

| File | Purpose |
|------|---------|
| `crud.py` | `CRUDView`, `Action` — generates views + URLs from config |
| `displays.py` | `TableDisplay`, `CardDisplay`, … — how a list or detail page renders |
| `templatetags/crud_tags.py` | `{% crud_table %}`, the list table (sorting, column widths, row actions) |
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

1. **Use CRUDView** for all model management pages (its own table; no django-tables2)
2. **Use `StaffRequiredMixin`** for admin/management views
3. **Use `LoginRequiredMixin`** for user-facing views
4. **Choose columns with `list_fields`**, not a hand-written table
5. **Set `paginate_by = 10`** as the standard page size
6. **Include breadcrumbs** in the title bar (not the breadcrumbs block)
7. **Empty the breadcrumbs block** (`{% block breadcrumbs %}{% endblock %}`) when using inline breadcrumbs
8. **Reference user with `settings.AUTH_USER_MODEL`** — never direct import
9. **Namespace URLs** — use `app_name` in urls.py or `url_base` prefix in CRUDView
10. **Support HTMX** — return partials for `HX-Request` headers
11. **Use `|pluralize`** on count labels (e.g., `{{ count }} Widget{{ count|pluralize }}`)
12. **Only hand-write a table** when a `field_transforms` entry or a custom display can't do it (see `crud-views.md`)
