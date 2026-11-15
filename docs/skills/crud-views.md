# Skill: CRUDView

CRUDView is SmallStack's declarative class for generating Django CRUD views from a single configuration. It produces list, create, detail, update, and delete views with URLs, templates, and wiring.

## Overview

The pattern: define a model and a CRUDView config. CRUDView generates the views, URL patterns, forms, breadcrumbs and a sortable, resizable list table, and, when you switch them on, the REST API and MCP tools for the same model.

## File Locations

```
apps/smallstack/
├── crud.py                # CRUDView, Action enum, base view classes
├── displays.py            # Display protocol: ListDisplay, DetailDisplay, FormDisplay
├── templatetags/crud_tags.py  # {% crud_table %}: the list table (sorting, widths, row actions)
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
| `list_fields` | list | `fields` | The list table's columns |
| `link_field` | str | None | The column that links each row to its detail page (or its edit page when there's no DETAIL action) |
| `url_base` | str | model name | URL prefix (e.g., `"manage/widgets"`) |
| `paginate_by` | int | `25` | Rows per page, on the HTML list and the API |
| `page_sizes` | tuple[int] | `()` | Opt-in "Rows per page" choice on the HTML list: `page_sizes = PAGE_SIZE_CHOICES` (`apps.smallstack.pagination`, 15/25/50/100). `?per_page=` picks one (anything else → the first, which becomes the default); the framework pager shows the control. A custom display paginates with `crud_config.page_size_for(request)` |
| `mixins` | list | `[]` | View mixins applied to all views (e.g. `[StaffRequiredMixin]`) |
| `model_permissions` | bool | `False` | Also require the user's Django model permission (view / add / change / delete) on every surface: pages, bulk actions, REST, MCP, `sc --user`. Adds to `mixins`; see **Model permissions** |
| `enable_history` | bool | `False` | A **History** page per row (`<pk>/history/`, linked from the detail page) listing its `LogEntry` audit trail. Opt-in: it names who edited a row to everyone who can open it |
| `view_mixins` | dict | `{}` | Extra mixins for one action's view, e.g. `{Action.DELETE: [MyDeleteMixin]}` (see **Overriding View Behavior**) |
| `displays` | list | `[]` | List displays to switch between. Empty: the built-in table |
| `detail_displays` | list | `[]` | List of display protocol classes for detail view |
| `list_accessories` | list | `[]` | Panels drawn above the list toolbar (`ListAccessory` instances): stats, a tag bar |
| `field_transforms` | dict | `{}` | How a field renders in lists and details (see **Field Transforms**) |
| `bulk_actions` | list | `[]` | Opt in to row checkboxes: `[BulkAction.DELETE, BulkAction.UPDATE]` |
| `form_class` | Form class | auto | Custom ModelForm |
| `enable_api` | bool | `False` | Generate REST API endpoints alongside HTML views (warns if no mixins) |
| `actions` | list | all 5 | Which CRUD actions to generate |
| `queryset` | QuerySet | `model.objects.all()` | Base queryset for all views |
| `search_fields` | list | `[]` | Fields for `?q=` text search: the list page's search box and the API |
| `filter_fields` | list | `[]` | Fields for query-param filtering: the list page's filter dropdowns and the API |
| `ordering_fields` | list | sortable `list_fields` | Fields allowed in `?ordering=` |
| `filter_class` | FilterSet | None | Custom FilterSet class (API only) |
| `export_formats` | list | `[]` | Export formats, e.g. `["csv", "json"]` (API only) |
| `enable_mcp` | bool | `False` | Generate MCP tools (`list_*`, `get_*`, `create_*`, …) for AI clients |
| `column_widths` | dict | None | `{field: "140px" \| "20%" \| "auto"}` for the table view. Unset: compact types (dates, numbers, booleans, choices) get a px default, the `link_field` 240px, the rest share what's left, never below 140px: the table gets a minimum width and its wrapper scrolls rather than crush a column. Prefer px; with `table-layout: fixed` a % column out-bids the unsized ones for the slack |
| `wrap_fields` | list | None | Table columns whose text wraps onto more lines instead of clipping with an ellipsis, e.g. `["title"]` for a long name column. Give it room too (`column_widths = {"title": "40%"}`): an unsized column bottoms out at 140px and a long title there becomes a tall stack of short lines. The rest stay one line with a tooltip while clipped; the table's "Wrap text" tool still wraps them all |
| `column_labels` | dict | None | `{field: "Updated"}`: a table header shorter than the field's verbose name |
| `breadcrumb_parent` | tuple | None | `(label, url_name)` for parent breadcrumb |
| `related_tabs` | `list\|None\|False` | `None` | Related object tabs on detail page. `None`=auto-discover, list=explicit, `False`=disabled |
| `related_tabs_exclude` | list | `[]` | Accessor names to exclude from auto-discovery |
| `related_tabs_paginate_by` | int | `10` | Rows per tab in related object tabs |

## Display Protocol

Displays control how data renders in list and detail views. CRUDView and Explorer use the same protocol.

### Built-in List Displays

| Class | Name | Description |
|-------|------|-------------|
| `TableDisplay` | `table` | The built-in table: sortable, resizable columns, field transforms, pagination |
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

## Actions

| Action | URL Pattern | View Type |
|--------|------------|-----------|
| `Action.LIST` | `url_base/` | ListView |
| `Action.CREATE` | `url_base/new/` | CreateView |
| `Action.DETAIL` | `url_base/<pk>/` | DetailView |
| `Action.UPDATE` | `url_base/<pk>/edit/` | UpdateView |
| `Action.DELETE` | `url_base/<pk>/delete/` | DeleteView |

Common: leave out `Action.DETAIL`; the `link_field` column then links straight to the edit page.

## URL namespaces (`app_name` in your `urls.py`)

CRUDView's internal URL reverses use **bare URL names** (e.g.
`reverse("widgets-list")`) by default. If your app's `urls.py` declares
`app_name = "myapp"`, Django automatically namespaces those names — and
those bare reverses will raise `NoReverseMatch`.

Two ways to handle this:

**Option 1 — Don't set `app_name` in the urls.py that hosts your
CRUDViews** (simplest). Use globally-unique URL names instead:

```python
# apps/knowledge/urls.py
urlpatterns = [
    # No app_name = "knowledge" line.
    path("featured/", FeaturedView.as_view(), name="knowledge-featured"),
    *KnowledgeCRUDView.get_urls(),
]
```

**Option 2 — Set `namespace` on every CRUDView in the namespaced
urls.py** (when you want the namespace badly enough that the prefix
collisions are worth it):

```python
# apps/knowledge/urls.py
app_name = "knowledge"
urlpatterns = [
    path("featured/", FeaturedView.as_view(), name="featured"),
    *KnowledgeCRUDView.get_urls(),
]

# apps/knowledge/views.py
class KnowledgeCRUDView(CRUDView):
    model = Article
    url_base = "articles"
    namespace = "knowledge"   # ← matches app_name; CRUDView prepends it on internal reverses
```

`namespace` is a class attribute on `CRUDView`. When set, every internal
`reverse()` becomes `reverse("knowledge:widgets-list")` instead of
`reverse("widgets-list")`. Without it, internal navigation breaks the
moment `app_name` is set.

A common AI-vibe-coding footgun: declaring `app_name` reflexively
because Django docs encourage it. CRUDView's bare-name convention is
deliberate (it lets the same CRUDView serve both namespaced and
root-mounted URL configs), but it requires this opt-in.

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

First reach for a classmethod hook (`get_list_queryset`, `can_update`, `on_form_valid`,
`on_delete`, `row_actions` — see **CRUDView Hooks** below): those apply to REST and MCP as
well as the HTML page. When only one HTML view needs different behaviour, write an ordinary
Django mixin and list it under its action in `view_mixins`:

```python
from apps.smallstack.crud import Action, CRUDView


class WidgetDeleteMixin:
    """Show what deleting would break; answer htmx with a modal fragment."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["used_by"] = self.object.dependents.all()
        return context

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["myfeature/widget_confirm_delete_modal.html"]
        return super().get_template_names()


class WidgetCRUDView(CRUDView):
    model = Widget
    view_mixins = {Action.DELETE: [WidgetDeleteMixin]}
```

The mixin sits after the auth mixins and before the generated base, so `super()` reaches the
framework's behaviour. Keys are `Action.LIST`, `CREATE`, `DETAIL`, `UPDATE`, `DELETE`.

**Don't** override `_make_view` and assign functions onto the class it returns. Older apps
(usermanager, tokenmgr) still do. It works, but it isn't idiomatic Django, it breaks
`super()`, and it hides the override from anyone reading the class.

**The form gets the user for free:** the HTML create/edit views pass `user=request.user` to a
form whose `__init__` accepts `user`, the same rule REST, MCP and `sc` follow
(`form_bridge.build_form`). Don't inject it yourself.

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
| **User Manager** | `/smallstack/manage/users/` | Full CRUDView + search + stat card drilldowns + custom edit form |
| **Backups** | `/smallstack/backups/` | Title bar + stat cards + tabbed content |
| **Activity Requests** | `/smallstack/activity/requests/` | Title bar number cards + tabbed tables |

## CRUDView Hooks

Classmethod hooks for injecting custom logic (they apply on every surface — HTML, REST, MCP):

| Hook | Purpose |
|------|---------|
| `get_list_queryset(qs, request)` | Filter/annotate the list queryset — the read scoper |
| `get_detail_queryset(qs, request)` | Scope a SINGLE-object fetch; defaults to `get_list_queryset` |
| `on_form_valid(request, form, obj, is_create)` | Callback after successful create/update — **every** transport |
| `on_delete(request, obj)` | Runs before a delete, on every surface, in the delete's transaction |
| `can_update(obj, request)` | Per-object update permission check (also hides the row's edit icon) |
| `can_delete(obj, request)` | Per-object delete permission check (also hides the row's delete icon) |
| `row_actions(obj, request, default_actions)` | The icons a row shows; return a changed list to add or drop some |

`get_list_queryset` is the one read scoper: the HTML list, the REST list, the
`list_*` MCP tool and the list accessories all route through it. Single-object
fetches (detail, edit, delete, related tabs, field preview, bulk actions, REST
detail, `get_*`/`update_*`/`delete_*` MCP tools) go through
`get_detail_queryset`, which **defaults to `get_list_queryset`** — so a row
hidden from the list is not silently readable, or editable, at its own URL.
Override `get_detail_queryset` only when the list hook does list-specific work
you don't want on a detail load (e.g. approvals' lazy expiry sweep); keep the
*scoping* identical, or you have reopened the hole.

`on_form_valid` fires from the HTML create/update views **and** REST, MCP and
bulk update. (Before v0.20.2 the web path skipped it, so a hook used to stamp an
owner or file an approval had a data-integrity hole reachable from the UI.)

## Model permissions

`model_permissions = True` makes every surface ask Django's permission system
before acting, the check Django admin makes:

| Surface | Needs |
|---|---|
| list, detail, related tab, history, field preview; REST `GET`; `list_*` / `get_*` tools; `sc ls/get --user` | `view` (or `change`) |
| create page; REST `POST`; `create_*`; `sc new --user` | `add` |
| edit page, bulk update; REST `PUT`/`PATCH`; `update_*`; `sc set --user` | `change` |
| delete page and modal, bulk delete; REST `DELETE`; `delete_*`; `sc rm --user` | `delete` |

Buttons, row actions, bulk actions and related tabs follow the same answers, so
a page doesn't offer what would answer 403. A delete that would cascade into
rows of an admin-registered model the user may not delete is refused too
(`check_cascade_permission`). Superusers hold every permission. The flag adds to
`mixins` (a `StaffRequiredMixin` view still needs staff first) and to the
per-row hooks (`can_update`, `can_delete`, `check_object_permission`), which
still decide row by row. Off by default, because a member-facing view's users
usually hold no model permissions. `has_model_permission(request, action)` is
the hook to override for a rule of your own.

## Audit trail

The create, edit and delete pages write a Django `LogEntry` (create and edit
record which fields changed, in Django admin's format), so the trail is the same
whichever surface made the change: REST, MCP, `sc` and the bulk views already
wrote one. Set `enable_history = True` for a per-row History page listing them.
Don't also add `AuditMixin` to a CRUDView, or log the write in `on_form_valid`:
it would be recorded twice.

## What a delete removes

The delete confirmation, both the page and the modal the list and detail pages
open, lists what Django's deletion collector says goes with the row: how many
rows of each model cascade and, for staff, a few of them by name (other users
see counts only). A row protected by a `PROTECT` or `RESTRICT` foreign key gets
no Delete button and a list of what protects it. The modal fetches this from the
delete URL with an `X-SmallStack-Delete-Summary` header; a custom delete template
can include `smallstack/crud/includes/delete_summary.html` with `deletion` in
context.

## API Endpoints

Set `enable_api = True` to generate REST API endpoints alongside HTML views:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    enable_api = True
```

This adds JSON endpoints at `<include-prefix>/api/manage/widgets/` and `<include-prefix>/api/manage/widgets/<pk>/` with:
- Bearer token and session authentication
- GET (list with search/filter/pagination/export), POST (create)
- GET (detail), PUT/PATCH (update), DELETE
- Permissions cascade from CRUDView's `mixins`

### URL anatomy

The final REST URL is composed of three parts:

```
<include-prefix> + SMALLSTACK_API_PREFIX + url_base + "/"
```

| Piece | Source | Example |
|---|---|---|
| `<include-prefix>` | Wherever your app's `urls.py` is mounted in `config/urls.py` | `path("support/", include("apps.support.urls"))` → `/support/` |
| `SMALLSTACK_API_PREFIX` | Setting in `config/settings/smallstack.py` (default `"api/"`) | `api/` |
| `url_base` | The CRUDView attribute | `tickets` |

So a `TicketCRUDView` with `url_base = "tickets"` included under
`path("support/", ...)` lands at `/support/api/tickets/`. If the same
CRUDView's `urls.py` is mounted at the project root (`path("",
include(...))`), it lands at `/api/tickets/`. This is the most common
source of "I followed the docs but my API endpoint 404s" — always look
at where your `urls.py` is `include()`'d in `config/urls.py`.

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
- [ ] CRUDView with `list_fields` and a `link_field` (add `displays` only for a view beyond the table)
- [ ] URLs using `*MyCRUDView.get_urls()`
- [ ] URL include in `config/urls.py`
- [ ] Sidebar link (see navigation skill)
- [ ] Migrations created and applied
- [ ] Tests for access control
