# Skill: Dashboard Widgets

SmallStack's dashboard (`/smallstack/`) is assembled from a registry of widgets. Apps publish widgets either by attaching them to an Explorer-registered `ModelAdmin`, or by registering standalone widgets in their `AppConfig.ready()`. The same data layer also powers the per-group/per-app widget toggle in Explorer and a REST API endpoint.

## Overview

Two widget sources feed one collector:

1. **Explorer widgets** — `ModelAdmin` classes declare `explorer_dashboard_widgets = [MyWidget()]`. The Explorer registry discovers them automatically (same pattern as `explorer_displays`, `explorer_list_accessories`).
2. **Standalone widgets** — apps without an Explorer model register via `dashboard.register(widget)` in `AppConfig.ready()`.

The data layer (`get_widget_contexts()`) collects from both, sorts by `order`, and returns rich context dicts. Three consumers:

- **Default view** — `SmallStackDashboardView` renders `smallstack/dashboard.html`
- **Mixin** — `DashboardWidgetsMixin` adds `widgets` to any template context
- **API** — `GET /api/dashboard/widgets/` serves widget data as JSON

## File Locations

```
apps/smallstack/
├── displays.py                    # DashboardWidget base class
├── dashboard.py                   # Registry, data layer, mixin, API view
├── dashboard_widgets.py           # Built-in standalone widgets (Backups, Help)
├── apps.py                        # Registers standalone widgets in ready()
├── views.py                       # SmallStackDashboardView
├── templates/smallstack/
│   ├── dashboard.html             # Default dashboard template
│   └── widgets/
│       └── card.html              # Card partial (widget_type="card")
└── static/smallstack/css/
    └── components.css             # Dashboard widget grid + card styles

apps/explorer/
├── registry.py                    # ExplorerSite.get_dashboard_widgets()
├── apps.py                        # Registers Explorer meta-widget
└── views.py                       # ExplorerIndexView — widget toggle
```

## The DashboardWidget Class

Lives in `apps/smallstack/displays.py`. Subclass it and override `get_data()`:

```python
from apps.smallstack.displays import DashboardWidget

class ActivityDashboardWidget(DashboardWidget):
    title = "Activity"
    icon = '<svg viewBox="0 0 24 24" ...>...</svg>'
    order = 20
    url_name = "activity:dashboard"

    def get_data(self, model_class=None):
        from django.utils import timezone
        now = timezone.now()
        total = model_class.objects.count()
        recent = model_class.objects.filter(
            timestamp__gte=now - timezone.timedelta(hours=24)
        ).count()
        return {
            "headline": f"{total:,} requests",
            "detail": f"{recent:,} in last 24h",
        }
```

### Class Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | `str` | `""` | Label shown above the headline |
| `icon` | `str` | `""` | SVG icon markup (trusted HTML, `mark_safe`'d automatically) |
| `order` | `int` | `50` | Sort order among widgets (lower = earlier) |
| `widget_type` | `str` | `"card"` | Template partial selector — today only `"card"` ships |
| `span` | `int` | `1` | CSS grid column span (1 = normal, 2 = wide) |
| `url_name` | `str \| None` | `None` | Named URL; overrides the auto-resolved Explorer list URL |
| `url_kwargs` | `dict \| None` | `None` | kwargs for `reverse()` |
| `group` | `str \| None` | `None` | Group name for filtered views (standalone widgets only — Explorer widgets inherit group from `ModelInfo`) |
| `on_dashboard` | `bool` | `True` | Surface on main `/smallstack/` dashboard. Set `False` to scope a widget to its group/app/model page only |

### Methods

- **`get_data(model_class=None) -> dict`** — Return widget data. For `widget_type="card"`, the template reads `headline`, `detail`, and optionally `status`. Any additional keys (e.g. `extra`) pass through to the API but are ignored by the HTML template. For Explorer widgets, `model_class` is the registered Django model. For standalone widgets, it is `None`.

- **`get_api_extras(model_class=None) -> dict | None`** — Return additional API-only data merged into the serialized widget's `data` field. Override only when extras are expensive to compute and you don't want them slowing HTML renders. Default returns `None`.

### URL Resolution

Priority:
1. `widget.url_name` (with `widget.url_kwargs`) if set
2. Explorer model list URL (e.g. `/explorer/monitoring/heartbeat/`) for Explorer widgets
3. `None` (card renders unlinked)

## Registering Widgets

### Explorer widgets (on ModelAdmin)

```python
# apps/activity/explorer.py
from apps.explorer.registry import explorer
from apps.smallstack.displays import DashboardWidget
from .admin import RequestLogAdmin
from .models import RequestLog

class ActivityDashboardWidget(DashboardWidget):
    title = "Activity"
    icon = "<svg>...</svg>"
    order = 20
    url_name = "activity:dashboard"

    def get_data(self, model_class=None):
        return {"headline": f"{model_class.objects.count():,} requests",
                "detail": "last 24h"}

RequestLogAdmin.explorer_dashboard_widgets = [ActivityDashboardWidget()]
explorer.register(RequestLog, RequestLogAdmin, group="Monitoring")
```

A single admin class can publish multiple widgets — `explorer_dashboard_widgets` is a list.

### Standalone widgets (no Explorer model)

```python
# apps/smallstack/apps.py
from django.apps import AppConfig

class SmallstackConfig(AppConfig):
    name = "apps.smallstack"

    def ready(self):
        from apps.smallstack import dashboard
        from .dashboard_widgets import BackupsDashboardWidget, HelpDashboardWidget
        dashboard.register(BackupsDashboardWidget())
        dashboard.register(HelpDashboardWidget())
```

Standalone widgets are great for things that have no canonical Django model (docs/help, filesystem backups, meta-widgets like "Explorer" itself).

### Third-party packages

Packages register their widgets in their own `AppConfig.ready()` — the base doesn't need to know about them. The ordering convention is:

| Order | Widget |
|-------|--------|
| 10 | Status (heartbeat) |
| 20 | Activity |
| 30 | Users |
| 40 | Backups |
| 50 | Help & Docs |
| 60 | Explorer (meta) |
| 70+ | Third-party packages |

## Data Layer

### `get_widget_contexts(group=None, app=None, model=None, dashboard_only=False)`

Returns a sorted list of widget contexts:

```python
{
    "widget": <DashboardWidget>,
    "data": {"headline": "...", "detail": "...", ...},  # from get_data()
    "url": "/explorer/monitoring/heartbeat/",            # resolved URL
    "model_info": <ModelInfo>,                           # None for standalone
    "group": "Monitoring",
    "app_label": "heartbeat",
    "model_name": "heartbeat",
    "icon_safe": <SafeString>,                           # mark_safe'd icon
}
```

Filters:
- `group` — restrict to widgets whose group (Explorer: from `ModelInfo`; standalone: from `widget.group`) matches case-insensitively
- `app` — restrict to Explorer widgets on models with this `app_label`
- `model` — restrict to Explorer widgets on this model class
- `dashboard_only` — drop widgets with `on_dashboard=False`

**Widget visibility rules:**
- Main `/smallstack/` dashboard: `dashboard_only=True` — only top-level widgets
- Filtered views (group/app/model): `dashboard_only=False` — show all widgets scoped to that filter

### `DashboardWidgetsMixin`

Adds `widgets` to template context. Mirrors `ExplorerGroupMixin`:

```python
from django.views.generic import TemplateView
from apps.smallstack.dashboard import DashboardWidgetsMixin

class MyDashboardView(DashboardWidgetsMixin, TemplateView):
    template_name = "myapp/dashboard.html"
    widget_group = "Monitoring"    # optional
    widget_app = None              # optional
    widget_model = None            # optional
    widget_dashboard_only = None   # optional — auto-defaults
```

Auto-default for `widget_dashboard_only`: `True` when no filter is set (main dashboard), `False` when any filter is active (filtered view shows everything).

## API Endpoint

```
GET /api/dashboard/widgets/
Authorization: Bearer <staff-token>

Query params:
  ?group=Monitoring
  ?app=heartbeat
  ?dashboard_only=1

→ 200:
{
  "widgets": [
    {
      "title": "Activity",
      "icon": "<svg>...</svg>",
      "order": 20,
      "widget_type": "card",
      "span": 1,
      "on_dashboard": true,
      "url": "/activity/",
      "data": {
        "headline": "1,234 requests",
        "detail": "42 in last 24h",
        "extra": {"total": 1234, "last_24h": 42, "window_hours": 24}
      },
      "group": "Monitoring",
      "app_label": "activity",
      "model_name": "requestlog"
    }
  ]
}
```

Staff-only (`require_staff=True`). Wired in `config/urls.py` at `api-dashboard-widgets`.

### API Extras

Two ways to add richer data for API consumers that the HTML template will ignore:

**Inline** — add keys to `get_data()`'s return dict. The card template only reads `headline`/`detail`/`status`; everything else passes through:

```python
def get_data(self, model_class=None):
    return {
        "headline": "42 requests",
        "detail": "last 24h",
        "extra": {"total": 42, "window_hours": 24},  # API only
    }
```

**Separate method** — override `get_api_extras()` when the data is expensive and shouldn't run on page renders:

```python
def get_api_extras(self, model_class=None):
    return {"trend": compute_expensive_trend(model_class)}
```

The serializer merges `get_api_extras()` output into `data`.

## Explorer Widget Toggle

The Explorer group/app index pages (`/smallstack/explorer/?by=group&group=X`) detect widgets scoped to the active filter and surface a **Models | Widgets** toggle. The search bar filters both views (search models on the models tab, search widgets on the widgets tab).

Implementation is in `apps/explorer/views.py` (`ExplorerIndexView.get_context_data`) and `apps/explorer/templates/explorer/index.html`. The stat strip always shows Models/Records; adds a Widgets card when widgets exist.

## Custom Dashboard Pages

Since the data layer is separate from presentation, you can throw away the default dashboard and build your own:

```python
# Option 1: mixin
class MyDashboardView(DashboardWidgetsMixin, TemplateView):
    template_name = "myapp/ops_dashboard.html"
    widget_group = "Monitoring"

# Option 2: direct function call
def my_view(request):
    contexts = get_widget_contexts(group="Monitoring")
    return render(request, "myapp/ops.html", {"widgets": contexts})

# Option 3: API consumer (React/etc.)
# fetch('/api/dashboard/widgets/?group=Monitoring')
```

## Extensibility

- **`widget_type` + `span`** — future widget types (chart, table, status grid) add a new subclass plus a template partial at `smallstack/widgets/{widget_type}.html`. No protocol change needed. `span` lets any widget claim more grid columns.
- **Group/app/model filtered views** — `get_widget_contexts()` already supports these filters. URLs and templates can be added without touching the widget classes.

## Best Practices

1. **Attach widgets to Explorer models when one exists** — you get URL auto-resolution, group inheritance, and zero wiring
2. **Use standalone widgets for meta/system things** — help docs, filesystem backups, Explorer itself
3. **Set `on_dashboard=False` for granular widgets** — they show up on scoped views but don't clutter the main dashboard
4. **Order deliberately** — leave gaps (10, 20, 30) so third-party packages can slot in (15, 25, 35)
5. **Keep `get_data()` cheap** — it runs on every dashboard render. Move expensive computation to `get_api_extras()`
6. **Icons are trusted HTML** — keep them to inline `<svg>` markup, no external URLs
