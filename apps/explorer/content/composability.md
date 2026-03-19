# Composability Guide

Explorer isn't just a standalone data browser — it's a composable toolkit. You can embed Explorer's CRUD tables, display palettes, model cards, and group navigation into any page in your project. This is the key difference from Django admin, which locks you into its own page layout.

## The Composability Stack

Explorer provides four levels of abstraction. Pick whichever fits your use case:

| Level | What | When to use |
|-------|------|-------------|
| **View mixins** | `ExplorerGroupMixin`, `ExplorerAppMixin`, `ExplorerModelMixin` | Most cases. Two-line views with zero boilerplate. |
| **Context helpers** | `explorer.get_group_context()`, `explorer.get_model_context()` | When you need to add custom data or transform results. |
| **Display protocol** | `ListDisplay`, `DetailDisplay` subclasses | Custom visualizations (maps, charts, calendars). |
| **Template tags** | `{% crud_table %}`, `{% crud_detail %}` | Render CRUD tables/detail from context variables. |

## View Mixins

Mixins are the recommended approach. Add one to any `TemplateView` and it populates the template context automatically.

### ExplorerGroupMixin

Shows all models in a custom group (set via `group` parameter in `explorer.register()`).

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

# Hardcoded — always shows the heartbeat app's models
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

# Hardcoded — always shows Heartbeat data
class HeartbeatView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeats.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"
```

**Context variables provided:** `object_list`, `list_fields`, `detail_fields`, `link_field`, `url_base`, `crud_actions`, `field_transforms`, `create_view_url`, `object_verbose_name`, `object_verbose_name_plural`, `model_info`.

Template:

```html
{% load crud_tags %}

<div class="card">
    <div class="card-header">
        <h2>{{ object_verbose_name_plural }}</h2>
    </div>
    <div class="card-body">
        {% crud_table %}
    </div>
</div>
```

## Context Helpers (Manual Approach)

Use these when you need custom logic — filtering the queryset, adding extra context, or combining data from multiple sources.

```python
from apps.explorer.registry import explorer

# Get all models in "Monitoring" group with live counts
ctx = explorer.get_group_context("Monitoring")
if ctx:
    context.update(ctx.as_context())

# Get a specific model's full CRUD context
ctx = explorer.get_model_context("heartbeat", "heartbeat")
if ctx:
    context.update(ctx.as_context())
```

### Available Context Helpers

| Method | Returns | Context keys |
|--------|---------|-------------|
| `explorer.get_group_context("Monitoring")` | `GroupContext` | `group_name`, `models`, `all_groups` |
| `explorer.get_app_context("heartbeat")` | `AppContext` | `app_label`, `app_verbose_name`, `models`, `all_apps` |
| `explorer.get_model_context("heartbeat", "heartbeat")` | `ModelContext` | `object_list`, `list_fields`, `url_base`, `crud_actions`, etc. |

All return `None` if the group/app/model isn't registered.

## Building Custom Display Classes

The display protocol is the most powerful composability feature. Create a display class and it works everywhere — Explorer, CRUDView, and any page that uses the display palette.

### The Protocol

Every display class has three properties and one method:

| Property | Purpose |
|----------|---------|
| `name` | String used in `?display=___` URL parameter |
| `icon` | Inline SVG for the palette button |
| `template_name` | Path to the Django template |
| `get_context()` | Returns a dict merged into the template context |

### List Display

`ListDisplay.get_context(queryset, crud_config, request)` receives the full queryset. Your display can ignore it and query whatever it needs:

```python
from apps.smallstack.displays import ListDisplay

class WeeklySummaryDisplay(ListDisplay):
    name = "weekly"
    icon = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">...</svg>'
    template_name = "heartbeat/displays/weekly_summary.html"

    def get_context(self, queryset, crud_config, request):
        # Build a 7-day Mon-Sun calendar grid
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        records = {d.date: d for d in HeartbeatDaily.objects.filter(...)}

        days = []
        for i in range(7):
            date = monday + timedelta(days=i)
            d = records.get(date)
            days.append({"day": date, "uptime": ..., "meets_sla": ...})

        return {"days": days, "monday": monday, ...}
```

The template is a standalone fragment with its own `<style>` block — no base template extension needed since HTMX swaps it as a fragment.

### Detail Display

`DetailDisplay.get_context(obj, crud_config, request)` receives a single object:

```python
from apps.smallstack.displays import DetailDisplay

class SLACompareDisplay(DetailDisplay):
    name = "sla"
    icon = '<svg>...</svg>'
    template_name = "heartbeat/displays/sla_compare.html"

    def get_context(self, obj, crud_config, request):
        uptime = float(obj.uptime_pct)
        meets_sla = uptime >= minimum
        return {"uptime": uptime, "meets_sla": meets_sla, ...}
```

### Registration

Displays work in both Explorer and standalone CRUDView:

```python
# Explorer — via ModelAdmin
class MyAdmin(admin.ModelAdmin):
    explorer_displays = [Table2Display, WeeklySummaryDisplay()]
    explorer_detail_displays = [DetailTableDisplay, SLACompareDisplay()]

# Standalone CRUDView — directly on the class
class MyCRUDView(CRUDView):
    displays = [TableDisplay, WeeklySummaryDisplay()]
    detail_displays = [DetailTableDisplay, SLACompareDisplay()]
```

Same engine, two entry points.

## Groups vs Apps

| | Groups | Apps |
|---|--------|------|
| **Source** | `group` parameter in `explorer.register()` | Django's `app_label` |
| **Flexibility** | Custom labels — group models however you want | Fixed to Django's app structure |
| **Mixin** | `ExplorerGroupMixin` | `ExplorerAppMixin` |
| **Helper** | `explorer.get_group_context()` | `explorer.get_app_context()` |
| **Use case** | Custom dashboards, cross-app views | Admin-style pages mirroring app layout |

## Mixing CRUD with Custom Content

The real power is combining Explorer's auto-generated CRUD with your own visuals:

```python
class HeartbeatPageView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeat_page.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["chart_days"] = build_7day_chart()
        return context
```

```html
{% load crud_tags %}

{# Your custom chart #}
<div class="card">
    {% for day in chart_days %}
        <div style="height: {{ day.pct }}%; background: var(--primary);"></div>
    {% endfor %}
</div>

{# Auto-generated CRUD table from Explorer #}
<div class="card">
    {% crud_table %}
</div>
```

## See Also

- [Model Explorer](/smallstack/help/smallstack/explorer/) — Overview, registration, and displays
- [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) — Auto-generated JSON API
- [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/) — Full custom CRUD when you outgrow Explorer
