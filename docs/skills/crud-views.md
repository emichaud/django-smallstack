# Skill: CRUDView

CRUDView is SmallStack's declarative class for generating Django CRUD views from a single configuration. It produces list, create, detail, update, and delete views with URLs, templates, and wiring.

## Overview

The pattern: define a model, configure displays (or a table class), and a CRUDView config. CRUDView generates views, URL patterns, forms, breadcrumbs, and context collision protection.

## File Locations

```
apps/smallstack/
├── crud.py                # CRUDView, Action enum, base view classes
├── displays.py            # Display protocol: ListDisplay, DetailDisplay, FormDisplay
├── tables.py              # DetailLinkColumn, BooleanColumn, ActionsColumn
├── mixins.py              # StaffRequiredMixin and other access mixins
└── templates/smallstack/crud/
    ├── object_list.html       # Generic list template
    ├── object_detail.html     # Generic detail template
    ├── object_form.html       # Generic create/edit template
    └── object_confirm_delete.html
```

## The Simplest Case

### 1. CRUDView Config

```python
# apps/myfeature/views.py
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import TableDisplay
from apps.smallstack.mixins import StaffRequiredMixin
from .models import Widget

class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active", "owner"]
    url_base = "manage/widgets"
    mixins = [StaffRequiredMixin]
    displays = [TableDisplay]
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
```

### 2. URL Wiring

```python
# apps/myfeature/urls.py
from .views import WidgetCRUDView

urlpatterns = [
    *WidgetCRUDView.get_urls(),
]
```

This generates:

| URL | Name | Purpose |
|-----|------|---------|
| `/manage/widgets/` | `manage/widgets-list` | Sortable, paginated list |
| `/manage/widgets/new/` | `manage/widgets-create` | Create form |
| `/manage/widgets/<pk>/edit/` | `manage/widgets-update` | Edit form |
| `/manage/widgets/<pk>/delete/` | `manage/widgets-delete` | Delete confirmation |

## Configuration Options

| Option | Type | Default | Purpose |
|--------|------|---------|---------|
| `model` | Model class | required | The Django model |
| `fields` | list | required | Fields for auto-generated forms |
| `url_base` | str | model name | URL prefix (e.g., `"manage/widgets"`) |
| `paginate_by` | int | None | Rows per page. When unset, HTML views are unpaginated; API endpoints fall back to 25 |
| `mixins` | list | `[]` | View mixins applied to all views |
| `displays` | list | `[]` | List of display protocol classes for list view |
| `detail_displays` | list | `[]` | List of display protocol classes for detail view |
| `table_class` | Table class | None | django-tables2 Table for list view (legacy, still works) |
| `form_class` | Form class | auto | Custom ModelForm |
| `enable_api` | bool | `False` | Generate REST API endpoints alongside HTML views (warns if no mixins) |
| `actions` | list | all 5 | Which CRUD actions to generate |
| `queryset` | QuerySet | `model.objects.all()` | Base queryset for all views |
| `search_fields` | list | `[]` | Fields for `?q=` text search (API only) |
| `filter_fields` | list | `[]` | Fields for query-param filtering (API only) |
| `filter_class` | FilterSet | None | Custom FilterSet class (API only) |
| `export_formats` | list | `[]` | Export formats, e.g. `["csv", "json"]` (API only) |
| `breadcrumb_parent` | tuple | None | `(label, url_name)` for parent breadcrumb |
| `related_tabs` | `list\|None\|False` | `None` | Related object tabs on detail page. `None`=auto-discover, list=explicit, `False`=disabled |
| `related_tabs_exclude` | list | `[]` | Accessor names to exclude from auto-discovery |
| `related_tabs_paginate_by` | int | `10` | Rows per tab in related object tabs |

## Display Protocol

Displays control how data renders in list and detail views. CRUDView and Explorer use the same protocol.

### Built-in List Displays

| Class | Name | Description |
|-------|------|-------------|
| `TableDisplay` | `table` | Basic HTML table with field transforms and pagination |
| `Table2Display` | `table2` | django-tables2 sortable table (requires `table_class`) |
| `CardDisplay` | `cards` | Card grid — zero-config key-value layout using `list_fields` |
| `AvatarCardDisplay` | `cards` | Card grid with avatar + title + subtitle + optional pill |
| `CalendarDisplay` | `calendar` | Month-grid calendar — events placed on date cells (supports single-date and date-range events) |

### Built-in Detail Displays

| Class | Name | Description |
|-------|------|-------------|
| `DetailTableDisplay` | `table` | Vertical key/value table |
| `DetailCardDisplay` | `card` | 2-column: image left, fields right |

See `card-displays.md` for the full card display protocol, authoring new card variants, and pushing computed fields down to managers/properties. See `calendar-displays.md` for `CalendarDisplay` configuration and date-based list displays.

### Custom Displays

Subclass `ListDisplay` or `DetailDisplay` to create custom visualizations (charts, calendars, maps):

```python
from apps.smallstack.displays import ListDisplay

class WeeklySummaryDisplay(ListDisplay):
    name = "weekly"
    icon = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">...</svg>'
    template_name = "myapp/displays/weekly_summary.html"

    def get_context(self, queryset, crud_config, request):
        # Can ignore queryset and build custom data
        return {"days": build_weekly_data(), ...}
```

For detail views:

```python
from apps.smallstack.displays import DetailDisplay

class SLACompareDisplay(DetailDisplay):
    name = "sla"
    icon = '<svg>...</svg>'
    template_name = "myapp/displays/sla_compare.html"

    def get_context(self, obj, crud_config, request):
        return {"uptime": float(obj.uptime_pct), ...}
```

Register on CRUDView:

```python
class MyCRUDView(CRUDView):
    displays = [TableDisplay, WeeklySummaryDisplay(), MonthGridDisplay()]
    detail_displays = [DetailTableDisplay, SLACompareDisplay()]
```

When `displays` has more than one entry, a palette of icon buttons appears. Clicking swaps the display via HTMX. The URL updates with `?display=weekly` for bookmarking.

### Display Template Pattern

Display templates are standalone fragments with their own `<style>` — no base template extension needed:

```html
<style>
.my-display { /* scoped styles */ }
</style>
<div class="my-display">
    {% for item in items %}...{% endfor %}
</div>
```

## Column Types (django-tables2)

Used with `Table2Display` or `table_class`. Not needed when using `TableDisplay` or custom displays.

| Column | What It Does |
|--------|-------------|
| `DetailLinkColumn` | Makes cell value a clickable link. `link_view="update"` or `"detail"` |
| `BooleanColumn` | Renders `True` as checkmark, `False` as dash |
| `ActionsColumn` | Edit (pencil) and delete (trash) icon buttons |

All three take `url_base` — must match CRUDView's `url_base`.

## Actions

| Action | URL Pattern | View Type |
|--------|------------|-----------|
| `Action.LIST` | `url_base/` | ListView |
| `Action.CREATE` | `url_base/new/` | CreateView |
| `Action.DETAIL` | `url_base/<pk>/` | DetailView |
| `Action.UPDATE` | `url_base/<pk>/edit/` | UpdateView |
| `Action.DELETE` | `url_base/<pk>/delete/` | DeleteView |

Common: skip DETAIL and link directly to edit via `DetailLinkColumn(link_view="update")`.

## Template Resolution

1. **App-specific:** `<app_label>/crud/<model_name>_<suffix>.html`
2. **Generic fallback:** `smallstack/crud/object_<suffix>.html`

Override with `_get_template_names(cls, suffix)`:

```python
@classmethod
def _get_template_names(cls, suffix):
    if suffix == "list":
        return ["myfeature/widget_list.html"]
    return super()._get_template_names(suffix)
```

## Overriding View Behavior

Use `_make_view` to inject custom logic:

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
                qs = qs.filter(Q(name__icontains=q))
            return qs

        view_class.get_queryset = get_queryset

    return view_class
```

Available base classes: `_CRUDListBase`, `_CRUDCreateBase`, `_CRUDDetailBase`, `_CRUDUpdateBase`, `_CRUDDeleteBase`.

## The Management Page Pattern

Staff-facing list pages follow a consistent layout:

```
┌──────────────────────────────────────────────────────────┐
│  Title                                    [Card] [Button] │
│  Home / Section / Page                                    │
└──────────────────────────────────────────────────────────┘
  ┌─────────┐ ┌─────────┐ ┌─────────┐    ← Stat cards
  │  Total  │ │  Staff  │ │ Recent  │
  └─────────┘ └─────────┘ └─────────┘
  ┌─────────────────────────────────┐     ← Search bar
  │ 🔍 Search...                    │
  └─────────────────────────────────┘
  ┌─────────────────────────────────┐     ← Sortable table
  │ NAME ▲    CATEGORY    ✎ 🗑     │
  └─────────────────────────────────┘
```

Custom list template with title bar: see `apps/smallstack/docs/building-crud-pages.md` for the full pattern.

## HTMX Search Integration

Three pieces needed:

1. **Search partial** — table-only template (no page chrome)
2. **View override** — filter queryset, return partial for HTMX requests
3. **Search bar include** — `{% include "smallstack/includes/search_bar.html" with placeholder="Search..." target="#search-results" %}`

## Context Collision Protection

If your model name collides with Django's reserved context names (`user`, `request`, `messages`, `perms`), CRUDView automatically prefixes the context variable with `crud_` (e.g., `crud_user`).

## Reference Implementations

| Page | URL | Demonstrates |
|------|-----|-------------|
| **User Manager** | `/manage/users/` | Full CRUDView + search + stat card drilldowns + custom edit form |
| **Backups** | `/backups/` | Title bar + stat cards + tabbed content |
| **Activity Requests** | `/activity/requests/` | Title bar number cards + tabbed tables2 |

## CRUDView Hooks

Classmethod hooks for injecting custom logic without `_make_view`:

| Hook | Purpose |
|------|---------|
| `get_list_queryset(qs, request)` | Filter/annotate the list queryset (used by API layer) |
| `on_form_valid(request, form, obj, is_create)` | Callback after successful create/update |
| `can_update(obj, request)` | Per-object update permission check |
| `can_delete(obj, request)` | Per-object delete permission check |

## API Endpoints

Set `enable_api = True` to generate REST API endpoints alongside HTML views:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    enable_api = True
```

This adds JSON endpoints at `api/manage/widgets/` and `api/manage/widgets/<pk>/` with:
- Bearer token and session authentication
- GET (list with search/filter/pagination/export), POST (create)
- GET (detail), PUT/PATCH (update), DELETE
- Permissions cascade from CRUDView's `mixins`

See the `api` skill for full details.

## Field Transforms

The `field_transforms` attribute controls how fields render in list/detail views:

```python
class WidgetCRUDView(CRUDView):
    field_transforms = {
        "description": "preview",         # Truncated with click-to-expand
        "config": ("preview", {"max_length": 200}),  # With options
    }
```

Legacy attributes `field_formatters` and `preview_fields` still work but emit deprecation warnings.

## Related Object Tabs

Detail pages can show tabbed sections for reverse FK relations. Each tab displays a paginated table of related objects with links into their own CrudView detail page. Only relations whose model has a registered CRUDView appear.

### Configuration

| Option | Type | Default | Purpose |
|--------|------|---------|---------|
| `related_tabs` | `list\|None\|False` | `None` | `None`=auto-discover, `["accessor_name", ...]`=explicit list+order, `False`=disabled |
| `related_tabs_exclude` | `list` | `[]` | Accessor names to hide from auto-discovery |
| `related_tabs_paginate_by` | `int` | `10` | Rows per tab page |

### How It Works

1. CRUDView maintains a `_registry` mapping Model→CRUDView, populated at URL-config time
2. On the detail page, `_get_related_tabs()` iterates `model._meta.get_fields()` for `ManyToOneRel` (reverse FK) relations
3. Only relations whose related model is in `_registry` are shown
4. Tab counts are eager (indexed FK lookups); tab content loads lazily via HTMX
5. The FK field pointing back to the parent is automatically hidden from tab columns (redundant)

### Example

```python
class CustomerCRUDView(CRUDView):
    model = Customer
    fields = ["name", "email"]
    url_base = "manage/customers"
    # Show only orders and invoices tabs, in that order
    related_tabs = ["order_set", "invoice_set"]
    related_tabs_paginate_by = 20
```

### Context Model

The detail view passes `related_tabs` to the template — a list of dicts with:

| Key | Description |
|-----|-------------|
| `accessor` | Django accessor name (e.g. `"order_set"`) |
| `field_name` | FK field name on the related model |
| `verbose_name` | Plural display name |
| `verbose_name_singular` | Singular display name |
| `count` | Number of related objects |
| `related_model_name` | Model name of the related model |
| `related_app_label` | App label of the related model |
| `related_url_base` | URL base of the related model's CRUDView |
| `related_list_url` | Full URL to the related model's list view |
| `content_url` | Endpoint for fetching tab content |

The tab content endpoint (`<pk>/related/<accessor>/`) returns a partial with `{% crud_table %}` and paginator, plus additional `related_tab_*` context variables for custom templates.

### URL Pattern

When `related_tabs is not False`, an additional URL is registered:

| URL | Name | Purpose |
|-----|------|---------|
| `url_base/<pk>/related/<accessor>/` | `url_base-related-tab` | HTMX partial for one tab's content |

### Custom Templates

Override the tab bar: `smallstack/crud/includes/related_tabs.html`
Override tab content: `smallstack/crud/includes/related_tab_content.html`

The default templates use HTMX for lazy loading, but since the context provides raw URLs and model metadata, custom templates can use any approach (fetch, iframes, inline rendering, links to the related list view).

## Quick Checklist

- [ ] Model in `apps/<appname>/models.py`
- [ ] CRUDView with `displays` configured (or `table_class` for sortable tables)
- [ ] URLs using `*MyCRUDView.get_urls()`
- [ ] URL include in `config/urls.py`
- [ ] Sidebar link (see navigation skill)
- [ ] Migrations created and applied
- [ ] Tests for access control
