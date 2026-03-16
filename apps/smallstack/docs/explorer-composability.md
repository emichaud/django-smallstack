---
title: Explorer Composability
description: Embed Explorer displays, CRUD tables, and model navigation into any page using mixins and context helpers
---

# Explorer Composability Guide

Explorer isn't just a standalone data browser — it's a composable toolkit. You can embed Explorer's display-swapping tables, model cards, and group navigation into any page in your project. This is the key difference from Django admin, which locks you into its own page layout.

## Why This Matters

Django admin gives you CRUD for free, but you're stuck inside its UI. If you want a heartbeat chart above a data table, or a custom dashboard mixing models from different apps, admin can't help. You'd need to build everything from scratch — views, templates, URLs, pagination.

Explorer solves this. Register your models once, then compose their CRUD tables, display palettes, and detail views into any page you design. The data pipeline (querysets, field resolution, pagination) is handled — you just focus on layout.

## The Composability Stack

Pick the level of abstraction that fits your use case:

| Level | What | When to use |
|-------|------|-------------|
| **View mixins** | `ExplorerGroupMixin`, `ExplorerAppMixin`, `ExplorerModelMixin` | Most cases. Two-line views with zero boilerplate. |
| **Context helpers** | `explorer.get_group_context()`, `explorer.get_model_context()` | When you need custom data or transforms. |
| **Display protocol** | `ListDisplay`, `DetailDisplay` subclasses | When you want custom visualizations (maps, charts). |
| **Template tags** | `{% crud_table %}`, `{% crud_detail %}` | Render CRUD tables/detail from context variables. |

## View Mixins

Mixins are the fastest path. Add one to any `TemplateView` and it populates the template context automatically.

### ExplorerGroupMixin

Shows all models in a custom group.

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

URL pattern (dynamic mode):

```python
path("dashboard/<str:group>/", GroupDashboardView.as_view(), name="group-dashboard")
```

**Context variables:** `group_name`, `models` (list of `ModelCardInfo`), `all_groups`.

Template example:

```html
{% load crud_tags %}

<h1>{{ group_name }}</h1>

<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;">
    {% for model in models %}
    <a href="{{ model.list_url }}" class="card" style="text-decoration: none;">
        <div class="card-body" style="text-align: center;">
            <div style="font-size: 1.75rem; font-weight: 700; color: var(--primary);">
                {{ model.count }}
            </div>
            <div style="color: var(--body-quiet-color);">{{ model.verbose_name_plural }}</div>
        </div>
    </a>
    {% endfor %}
</div>
```

### ExplorerAppMixin

Shows all models from a Django app.

```python
from apps.explorer.mixins import ExplorerAppMixin

# Hardcoded — always shows the heartbeat app's models
class HeartbeatAppView(ExplorerAppMixin, TemplateView):
    template_name = "myapp/heartbeat_app.html"
    explorer_app = "heartbeat"
```

**Context variables:** `app_label`, `app_verbose_name`, `models`, `all_apps`.

### ExplorerModelMixin

Provides everything needed to render a CRUD table for a single model — including the display palette.

```python
from apps.explorer.mixins import ExplorerModelMixin

# Hardcoded — always shows Heartbeat data
class HeartbeatView(ExplorerModelMixin, TemplateView):
    template_name = "myapp/heartbeats.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"
```

**Context variables:** `object_list`, `list_fields`, `detail_fields`, `link_field`, `url_base`, `crud_actions`, `field_transforms`, `create_view_url`, `object_verbose_name`, `object_verbose_name_plural`, `model_info`.

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

The `{% crud_table %}` tag reads from the context variables the mixin provides. All CRUD links (detail, edit, delete) just work.

## Mixing CRUD with Custom Content

The real power is combining Explorer's auto-generated CRUD with your own visuals. Example: a monitoring dashboard with a chart above the data table.

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
    <div class="card-body">
        {% for day in chart_days %}
            <div style="height: {{ day.pct }}%; background: var(--primary);"></div>
        {% endfor %}
    </div>
</div>

{# Auto-generated CRUD table from Explorer #}
<div class="card">
    <div class="card-body">
        {% crud_table %}
    </div>
</div>
```

## Context Helpers

Use these when you need to transform data or combine multiple sources:

```python
from apps.explorer.registry import explorer

class DashboardView(TemplateView):
    template_name = "myapp/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get all models in "Monitoring" group with live counts
        group_ctx = explorer.get_group_context("Monitoring")
        if group_ctx:
            context.update(group_ctx.as_context())

        # Get a specific model's full CRUD context
        model_ctx = explorer.get_model_context("heartbeat", "heartbeat")
        if model_ctx:
            context["heartbeat"] = model_ctx.as_context()

        # Add your own data
        context["alert_count"] = get_active_alerts()
        return context
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

### List Display

```python
from apps.smallstack.displays import ListDisplay

class MapDisplay(ListDisplay):
    name = "map"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">'
        '<path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z'
        'm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>'
        '</svg>'
    )
    template_name = "myapp/displays/map.html"

    def __init__(self, lat_field="latitude", lng_field="longitude"):
        self.lat_field = lat_field
        self.lng_field = lng_field

    def get_context(self, queryset, crud_config, request):
        markers = []
        for obj in queryset:
            lat = getattr(obj, self.lat_field, None)
            lng = getattr(obj, self.lng_field, None)
            if lat and lng:
                markers.append({
                    "lat": float(lat),
                    "lng": float(lng),
                    "label": str(obj),
                    "pk": obj.pk,
                })
        return {"markers": markers}
```

The template (`myapp/displays/map.html`):

```html
<div id="map" style="height: 400px; border-radius: var(--radius-sm, 6px);"></div>
<script>
    const markers = {{ markers|safe }};
    // Initialize your map library here
</script>
```

Register it:

```python
class LocationAdmin(admin.ModelAdmin):
    explorer_displays = [
        Table2Display,
        MapDisplay(lat_field="lat", lng_field="lon"),
    ]
```

### Detail Display

```python
from apps.smallstack.displays import DetailDisplay

class TimelineDisplay(DetailDisplay):
    name = "timeline"
    icon = '<svg>...</svg>'
    template_name = "myapp/displays/timeline.html"

    def get_context(self, obj, crud_config, request):
        return {
            "events": obj.events.order_by("-created_at")[:20]
        }
```

## Display Palette Behavior

When a model has multiple displays, the palette appears automatically. Here's how it works:

1. **Initial load** — renders the first display (or the user's saved preference from localStorage)
2. **User clicks icon** — HTMX sends `GET ?display={name}` with `HX-Request` header
3. **Server responds** — returns just the display template (no page chrome)
4. **HTMX swaps** — the display area updates in place
5. **localStorage saves** — the choice persists across page navigation

The same mechanism works on both list and detail views. You get display switching for free by configuring `explorer_displays` and `explorer_detail_displays`.

## Groups vs Apps

Explorer supports two ways to organize models:

| | Groups | Apps |
|---|--------|------|
| **Source** | `group` parameter in `explorer.register()` | Django's `app_label` |
| **Flexibility** | Custom labels — group models however you want | Fixed to Django's app structure |
| **Mixin** | `ExplorerGroupMixin` | `ExplorerAppMixin` |
| **Use case** | Custom dashboards, cross-app views | Admin-style pages mirroring app layout |

Groups are more flexible. A model registered in "Monitoring" alongside models from three different apps creates a unified cross-app view that Django admin can't do.

## Patterns and Ideas

### Operations Dashboard

Combine models from different apps into a single monitoring page:

```python
class OpsDashboardView(ExplorerGroupMixin, TemplateView):
    template_name = "ops/dashboard.html"
    explorer_group = "Monitoring"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["latest_heartbeat"] = Heartbeat.objects.order_by("-timestamp").first()
        context["error_count"] = RequestLog.objects.filter(status_code__gte=500).count()
        return context
```

### Model with Multiple Visualizations

Register a model with table + map + chart displays:

```python
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "latitude", "longitude", "status")
    explorer_displays = [
        Table2Display,
        MapDisplay(lat_field="latitude", lng_field="longitude"),
        ChartDisplay(group_by="status"),
    ]
```

Users pick the view that makes sense for their task. The data is the same — only the rendering changes.

### Embedded CRUD in a Custom Page

Use `ExplorerModelMixin` to embed a full CRUD table (with sorting, pagination, and links) inside a page you control:

```python
class ProjectDetailView(ExplorerModelMixin, DetailView):
    model = Project
    template_name = "projects/detail.html"
    explorer_app_label = "tasks"
    explorer_model_name = "task"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Override object_list to filter by this project
        context["object_list"] = Task.objects.filter(project=self.object)
        return context
```

The CRUD table shows only tasks for this project, but all the sorting, pagination, and action links work normally.

## See Also

- [Model Explorer](/smallstack/help/smallstack/explorer/) — Overview, registration, and displays
- [Explorer REST API](/smallstack/help/smallstack/explorer-rest-api/) — Auto-generated JSON API
- [Building CRUD Pages](/smallstack/help/smallstack/building-crud-pages/) — Full custom CRUD when you outgrow Explorer
