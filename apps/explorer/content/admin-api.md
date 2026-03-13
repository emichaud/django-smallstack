# Explorer ModelAdmin API Reference

Explorer provides a staff-facing data browser that piggybacks on Django's admin registry. Instead of building a parallel registration system, Explorer reads your existing `ModelAdmin` classes and reuses what it can.

## How Discovery Works

Explorer uses an **admin-first** approach:

1. When the app starts, `ExplorerRegistry.discover()` walks `admin.site._registry`.
2. For each registered model, it checks for `explorer_enabled = True` on the `ModelAdmin`.
3. Models without that flag are ignored entirely -- Explorer is opt-in.
4. For opted-in models, Explorer reads supported `ModelAdmin` attributes (like `list_display`) to configure the generated CRUD views.
5. If a `ModelAdmin` attribute is missing or contains unsupported entries (like callables in `list_display`), Explorer falls back to auto-detection from the model's fields.

This means you register your model in `admin.py` once, add `explorer_enabled = True`, and Explorer builds list/detail/create/update/delete views automatically.

## Custom Explorer Attributes

These attributes are specific to Explorer and are set directly on your `ModelAdmin` subclass.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `explorer_enabled` | `bool` | `False` | Opt this model into Explorer. Required. |
| `explorer_fields` | `list[str]` | `None` | Override which fields Explorer shows. Falls back to `list_display` (real fields only), then auto-detection. |
| `explorer_readonly` | `bool` | `None` | Force readonly mode (list + detail only). When `None`, Explorer auto-detects by checking `has_add_permission` and `has_change_permission`. |
| `explorer_accessories` | -- | -- | Reserved for future use (charts, maps, visualizations). |

## Django ModelAdmin Attribute Support

### Supported

These attributes are read by Explorer today and affect the generated views.

| Attribute | Django Admin Behavior | Explorer Behavior | Notes |
|-----------|-----------------------|-------------------|-------|
| `list_display` | Columns shown in the changelist | Fields shown in Explorer list and forms | Only real model fields are used. Callables, `__str__`, and non-field entries are silently skipped. Falls back to auto-detected fields if none remain. |
| `has_add_permission()` | Controls whether the "Add" button appears | Auto-detects readonly mode | If overridden to return `False`, Explorer removes create/update/delete actions. |
| `has_change_permission()` | Controls whether editing is allowed | Auto-detects readonly mode | If overridden to return `False`, Explorer removes create/update/delete actions. |

### Planned

These are low-hanging fruit that Explorer could read from your existing `ModelAdmin` with relatively small implementation effort.

| Attribute | Django Admin Behavior | Explorer Behavior | Notes |
|-----------|-----------------------|-------------------|-------|
| `ordering` | Default sort order for the changelist | Default sort for Explorer list | Straightforward to pass through to the queryset. |
| `search_fields` | Enables a search box, searches across listed fields | Search box in Explorer | Requires adding a search input to the list template. |
| `list_per_page` | Number of rows per page (default 100) | Pagination size | Explorer currently hardcodes `paginate_by = 25`. This would override it. |
| `list_filter` | Sidebar filters in the changelist | Filter controls in Explorer | Requires building filter UI components. |
| `date_hierarchy` | Date-based drilldown navigation | Date navigation in Explorer | Requires building date nav UI. |
| `list_display_links` | Which columns link to the detail/change page | Which columns link to Explorer detail view | Currently Explorer links the first column; this would make it configurable. |
| `list_editable` | Inline editing of fields directly in the changelist | Inline editing in Explorer list | Requires form handling in the list view. |

### Not Supported

These attributes are unlikely to be supported because they are tightly coupled to Django admin internals, require significant new UI, or don't map to Explorer's design.

| Attribute | Django Admin Behavior | Why Not Supported |
|-----------|-----------------------|-------------------|
| `list_display` (callables) | Columns can be methods that compute display values | Would require invoking arbitrary methods and handling their output formatting. Significant complexity. |
| `list_max_show_all` | Threshold for the "Show all" link | Explorer uses standard pagination; no "show all" concept. |
| `fieldsets` | Groups fields into sections on the add/change form | Explorer uses a flat field list. Different UX model. |
| `inlines` | Embedded related-model forms on the change page | Major feature requiring nested form handling and related-object UI. |
| `actions` | Bulk operations (e.g., "Delete selected") on the changelist | Explorer's CRUD actions are per-object. Bulk actions are a different concept. |
| `autocomplete_fields` | AJAX-powered select widgets for ForeignKey/M2M fields | Tied to Django admin's widget and URL system. |
| `raw_id_fields` | Replaces select dropdowns with a raw ID input + lookup popup | Admin-specific widget pattern. |
| `form` | Custom form class for add/change views | Explorer generates its own forms from the field list. |
| `formfield_overrides` | Override form field types/widgets by model field type | Coupled to Django admin's form generation pipeline. |
| `filter_horizontal` / `filter_vertical` | Dual-pane M2M selector widgets | Admin-specific widgets. |
| `prepopulated_fields` | Auto-fills fields (e.g., slug from title) via JavaScript | Admin-specific JavaScript behavior. |
| `readonly_fields` | Per-field readonly on the change form | Explorer treats the whole model as readonly or not. Per-field control is not yet supported. |
| `save_on_top` | Shows save buttons at the top of the change form | Layout-specific to admin. |
| `save_as` | Adds a "Save as new" button | Admin-specific workflow. |
| `view_on_site` | Adds a "View on site" link using `get_absolute_url` | Could be added as a future enhancement but not currently planned. |

## Usage Examples

### Minimal Registration

Add `explorer_enabled = True` to any existing `ModelAdmin`. Explorer will auto-detect fields and permissions.

```python
# apps/tickets/admin.py
from django.contrib import admin
from .models import Ticket

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "priority", "created_at"]
    explorer_enabled = True
```

Explorer will show the `title`, `status`, `priority`, and `created_at` columns (all real model fields), and allow full CRUD.

### With Field Overrides

Use `explorer_fields` to show a different set of fields in Explorer than in Django admin.

```python
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "priority", "assignee", "created_at"]
    explorer_enabled = True
    explorer_fields = ["title", "status", "priority"]  # simpler view for Explorer
```

### Auto-Detected Readonly

Override `has_change_permission` or `has_add_permission` on the `ModelAdmin` and Explorer will detect it automatically. The model will only get list and detail views (no create, update, or delete).

```python
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "user", "action", "detail"]
    explorer_enabled = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

### Explicit Readonly Override

Force readonly mode directly, regardless of what the permission methods return.

```python
@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "updated_at"]
    explorer_enabled = True
    explorer_readonly = True
```

## Field Auto-Detection

When `explorer_fields` is not set and `list_display` contains no real model fields (or only unsupported entries), Explorer falls back to auto-detection. The auto-detection logic:

1. Iterates over `model._meta.get_fields()`.
2. Skips reverse relations and many-to-many fields.
3. Skips `AutoField` and `BigAutoField` (primary keys).
4. Skips the `password` field.
5. Skips non-editable fields.
6. Returns the remaining field names.

This produces a reasonable default for most models without any configuration.
