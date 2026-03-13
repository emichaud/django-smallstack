# Composability Guide

Explorer isn't just a standalone data browser — it's a composable toolkit. You can embed Explorer's CRUD tables, model cards, and group navigation into any page in your project. This is the key difference from Django admin, which locks you into its own page layout.

## The Composability Stack

Explorer provides four levels of abstraction. Pick whichever fits your use case:

| Level | What | When to use |
|-------|------|-------------|
| **View mixins** | `ExplorerGroupMixin`, `ExplorerAppMixin`, `ExplorerModelMixin` | Most cases. Two-line views with zero boilerplate. |
| **Context helpers** | `get_group_context()`, `get_app_context()`, `get_model_context()` | When you need to add custom data or transform results. |
| **Dataclasses** | `GroupContext`, `AppContext`, `ModelContext`, `ModelCardInfo` | When you need typed access to the raw data. |
| **Template tags** | `{% crud_table %}` | Renders the CRUD list table from context variables. |

## View Mixins

Mixins are the recommended approach. Add one to any `TemplateView` and it populates the template context automatically.

### ExplorerGroupMixin

Shows all models in a custom group (set via `explorer_group` on ModelAdmin).

```python
from django.views.generic import TemplateView
from apps.explorer.mixins import ExplorerGroupMixin

# Dynamic — reads group name from URL parameter
class GroupDashboardView(ExplorerGroupMixin, TemplateView):
    template_name = "myapp/group_dashboard.html"

# Hardcoded — always shows "Monitoring"
class MonitoringView(ExplorerGroupMixin, TemplateView):
    template_name = "myapp/monitoring.html"
    explorer_group = "Monitoring"
```

**URL pattern** (dynamic mode):

```python
path("dashboard/<str:group>/", GroupDashboardView.as_view(), name="group-dashboard")
```

**Context variables provided:** `group_name`, `models` (list of `ModelCardInfo`), `all_groups`.

### ExplorerAppMixin

Shows all models from a Django app (grouped by `app_label`).

```python
from django.views.generic import TemplateView
from apps.explorer.mixins import ExplorerAppMixin

# Dynamic — reads app_label from URL
class AppPageView(ExplorerAppMixin, TemplateView):
    template_name = "myapp/app_page.html"

# Hardcoded — always shows the heartbeat app
class HeartbeatAppView(ExplorerAppMixin, TemplateView):
    template_name = "myapp/heartbeat_app.html"
    explorer_app = "heartbeat"
```

**Context variables provided:** `app_label`, `app_verbose_name`, `models` (list of `ModelCardInfo`), `all_apps`.

### ExplorerModelMixin

Provides everything the `{% crud_table %}` template tag needs for a single model.

```python
from django.views.generic import TemplateView
from apps.explorer.mixins import ExplorerModelMixin

# Dynamic — reads app_label and model_name from URL
class ModelPageView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/model_page.html"

# Hardcoded — always shows Heartbeat
class HeartbeatView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeats.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"
```

**Context variables provided:** `object_list`, `list_fields`, `detail_fields`, `link_field`, `url_base`, `crud_actions`, `field_formatters`, `create_view_url`, `object_verbose_name`, `object_verbose_name_plural`, `model_info`.

## Context Helpers (Manual Approach)

Use these when you need custom logic — filtering the queryset, adding extra context, or combining data from multiple sources.

### get_group_context()

```python
from apps.explorer.registry import explorer_registry

ctx = explorer_registry.get_group_context("Monitoring")
if ctx:
    context.update(ctx.as_context())
```

Returns a `GroupContext` dataclass (or `None` if the group doesn't exist). Case-insensitive lookup.

### get_app_context()

```python
ctx = explorer_registry.get_app_context("heartbeat")
if ctx:
    context.update(ctx.as_context())
```

Returns an `AppContext` dataclass (or `None`).

### get_model_context()

```python
ctx = explorer_registry.get_model_context("heartbeat", "heartbeat")
if ctx:
    context.update(ctx.as_context())
    # Add your own data alongside
    context["my_chart_data"] = build_chart()
```

Returns a `ModelContext` dataclass (or `None`). The `as_context()` method returns a dict with all the variables `{% crud_table %}` expects.

## Groups vs Apps

Explorer supports two ways to organize models in a sidebar:

| | Groups | Apps |
|---|--------|------|
| **Source** | `explorer_group` attribute on ModelAdmin | Django's built-in `app_label` |
| **Flexibility** | Custom labels — group models however you want | Fixed to Django's app structure |
| **Mixin** | `ExplorerGroupMixin` | `ExplorerAppMixin` |
| **Helper** | `get_group_context()` | `get_app_context()` |
| **URL param** | `<str:group>` | `<str:app_label>` |
| **Use case** | Dashboard pages with custom categories | Admin-style pages mirroring Django's app layout |

## Mixing CRUD with Custom Content

The real power is combining Explorer's auto-generated CRUD with your own visuals. Example: a heartbeat monitoring page with a chart above the data table.

```python
class HeartbeatPageView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeat_page.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"

    def get_context_data(self, **kwargs):
        # Mixin provides: object_list, list_fields, crud_actions, etc.
        context = super().get_context_data(**kwargs)
        # Add your own data
        context["chart_days"] = build_7day_chart()
        return context
```

In the template, place your chart anywhere and use `{% crud_table %}` for the data table:

```html
{% load crud_tags %}

<div class="card">
    <!-- Your custom chart -->
    {% for day in chart_days %}
        ...
    {% endfor %}
</div>

<div class="card">
    <!-- Auto-generated CRUD table -->
    {% crud_table %}
</div>
```

The detail, create, update, and delete views are already wired up by Explorer — all links in the table just work.

## Example Pages

Explorer ships with working example pages that demonstrate each pattern:

- **Group Page** — Sidebar of groups + model cards for the selected group
- **App Page** — Sidebar of Django apps + model cards for the selected app
- **Model Page** — Single model CRUD list with header and actions
- **Heartbeat Compose** — Custom chart + CRUD table on the same page

Each example page has an "Overview" tab showing the live page and a "Code Examples" tab with copy-pasteable code.
