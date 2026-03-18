# Skill: Filtering & Export

CRUDView supports built-in search, filtering, and data export via its REST API layer. These features are declarative — set a few attributes on your CRUDView and the API handles the logic. For HTML views, use the `_make_view` override pattern for search (see crud-views skill).

## Overview

Three related features that layer onto CRUDView's **API endpoints** (requires `enable_api = True`):

| Feature | Attribute | What It Does |
|---------|-----------|-------------|
| **Search** | `search_fields` | Adds `?q=` text search across specified fields |
| **Filtering** | `filter_fields` / `filter_class` | Adds sidebar filters via django-filter |
| **Export** | `export_formats` | Adds download buttons for CSV, JSON, etc. |

All three are `None` by default (disabled). Enable only what you need.

## File Locations

```
apps/smallstack/
├── crud.py                # CRUDView — search, filter, export attribute definitions
├── api.py                 # API layer — search, filter, export implementation
└── templates/smallstack/crud/
    └── object_list.html   # Generic list template
```

> **Note:** Search, filter, and export are implemented in the API layer (`api.py`), not in the HTML list views. For HTML search, use the `_make_view` override pattern described in the crud-views skill.

## Search (`search_fields`)

Add a list of model field names to enable `?q=` search:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    search_fields = ["name", "category"]  # Searches with __icontains
```

### How It Works (API)

1. The API list endpoint checks for the `?q=` parameter
2. Builds a `Q` object with `__icontains` for each field in `search_fields`
3. Filters are OR'd together — matching any field returns the row

### HTMX Integration

For instant search (no page reload), combine with the HTMX search pattern:

```html
{% include "smallstack/includes/search_bar.html" with placeholder="Search widgets..." target="#search-results" %}

<div id="search-results">
    {% include "myfeature/_widget_table.html" %}
</div>
```

The search bar fires on keyup with 300ms debounce and pushes the query to the URL.

## Filtering (`filter_fields` / `filter_class`)

### Simple: Auto-Generated Filters

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    filter_fields = ["category", "is_active"]  # Auto-generates FilterSet
```

This auto-generates a `django_filters.FilterSet` with the specified fields. The filterset is available in template context as `filterset`.

### Advanced: Custom FilterSet

```python
import django_filters
from .models import Widget

class WidgetFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    created_after = django_filters.DateFilter(field_name="created_at", lookup_expr="gte")

    class Meta:
        model = Widget
        fields = ["name", "category", "is_active", "created_after"]


class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    filter_class = WidgetFilter  # Use custom FilterSet instead of auto-generated
```

### Dependencies

Filtering requires `django-filter`:

```bash
uv add django-filter
```

Add `"django_filters"` to `INSTALLED_APPS`.

## Export (`export_formats`)

Add a tuple of format strings to enable data export:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    export_formats = ("csv", "json")
```

### How It Works (API)

1. The API list endpoint checks for `?format=csv` (or `json`)
2. Builds a `tablib.Dataset` from the filtered queryset
3. Uses `list_fields` for columns, `verbose_name` for headers
4. Returns a file download response with timestamped filename

### Supported Formats

Any format supported by `tablib` — common ones are `csv` and `json`.

### Dependencies

Export requires `tablib`:

```bash
uv add tablib
```

### Template Context

When `export_formats` is set, `export_formats` is available in the template context. The generic list template renders download links automatically.

### Export Respects Filters

Export downloads contain the **currently filtered** data. If the user has an active search query or filter, the export reflects that subset — not the full dataset.

## Combining All Three

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active", "owner", "created_at"]
    url_base = "manage/widgets"
    paginate_by = 10
    table_class = WidgetTable

    # Search
    search_fields = ["name", "category"]

    # Filtering
    filter_fields = ["is_active", "owner"]

    # Export
    export_formats = ("csv", "json")
```

## Field Type Handling in Export

| Field Type | Export Value |
|------------|-------------|
| Datetime | ISO 8601 string |
| ForeignKey | String representation (`__str__`) |
| Boolean | `"true"` / `"false"` |
| None | Empty string |

## Best Practices

1. **Start with `search_fields`** — it's the simplest and covers most needs
2. **Use `filter_fields`** for exact-match dropdown filters (status, category, owner)
3. **Use `filter_class`** when you need custom lookups (date ranges, partial matches)
4. **Export formats** — `("csv",)` is usually enough; add `"json"` for API-like access
5. **Filters apply to exports** — users get exactly what they see
