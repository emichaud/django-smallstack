# Dashboard Widgets

The SmallStack dashboard at `/smallstack/` is a grid of at-a-glance cards. Each card is a **widget** — a small piece of Python that returns a headline, a detail line, and a link. You can add your own without editing base code.

## Two Ways to Add a Widget

### 1. Attach to an Explorer model

If the widget is about data in a Django model you've registered with Explorer, add it to the admin class:

```python
# apps/myapp/explorer.py
from apps.explorer.registry import explorer
from apps.smallstack.displays import DashboardWidget
from .admin import OrderAdmin
from .models import Order

class OrdersWidget(DashboardWidget):
    title = "Orders"
    icon = '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="..."/></svg>'
    order = 25

    def get_data(self, model_class=None):
        total = model_class.objects.count()
        open_count = model_class.objects.filter(status="open").count()
        return {
            "headline": f"{total:,} orders",
            "detail": f"{open_count} open",
        }

OrderAdmin.explorer_dashboard_widgets = [OrdersWidget()]
explorer.register(Order, OrderAdmin, group="Sales")
```

The card automatically links to the Explorer list page for your model. Override with `url_name = "myapp:orders_dashboard"` to point somewhere else.

### 2. Register a standalone widget

For widgets that aren't about a Django model (file-based docs, external systems, meta-widgets):

```python
# apps/myapp/apps.py
from django.apps import AppConfig

class MyappConfig(AppConfig):
    name = "apps.myapp"

    def ready(self):
        from apps.smallstack import dashboard
        from .widgets import ServerHealthWidget
        dashboard.register(ServerHealthWidget())
```

## Widget Attributes

| Attribute | Purpose |
|-----------|---------|
| `title` | Label on the card |
| `icon` | Inline SVG markup |
| `order` | Lower numbers appear first (defaults to 50) |
| `url_name` | Optional Django URL name to link to |
| `on_dashboard` | Set `False` to hide from the main dashboard but show on scoped views |
| `span` | Grid span (1 = normal, 2 = wide) |
| `group` | For standalone widgets — lets filtered views find them |

## What `get_data()` Returns

For the default card widget, return a dict with:

```python
{
    "headline": "42 requests",    # big text
    "detail": "12 in last 24h",   # small grey text
    "status": "ok",               # optional — adds a badge
}
```

Any additional keys (like `extra`) are passed through to the REST API but ignored by the HTML template. This lets you expose richer machine-readable data to API consumers without cluttering the card UI.

## Ordering

First-party widgets use these orders — leave gaps so your widgets slot in naturally:

| Order | Widget |
|-------|--------|
| 10 | Status |
| 20 | Activity |
| 30 | Users |
| 40 | Backups |
| 50 | Help & Docs |
| 60 | Explorer |
| 70+ | Add-on packages |

## REST API

Widgets are also exposed as JSON for SPAs and external dashboards:

```
GET /api/dashboard/widgets/
Authorization: Bearer <staff-token>
```

Optional query params: `?group=Monitoring`, `?app=heartbeat`, `?dashboard_only=1`.

Each response item includes the title, icon, URL, order, group, and the full `data` dict (headline, detail, plus any API extras).

## Custom Dashboard Views

The dashboard page itself is just a view that consumes the widget registry. You can build your own:

```python
from django.views.generic import TemplateView
from apps.smallstack.dashboard import DashboardWidgetsMixin

class OpsDashboard(DashboardWidgetsMixin, TemplateView):
    template_name = "myapp/ops.html"
    widget_group = "Monitoring"
```

The mixin adds a `widgets` list to the template context. Loop over it and render however you want.

## Scoped Widgets

Set `on_dashboard = False` when you want a widget to show up on filtered pages (per-group, per-app) but not crowd the main dashboard. Example: a low-priority "slow queries" widget that's useful on the Monitoring group page but would be noise on the main `/smallstack/` dashboard.
