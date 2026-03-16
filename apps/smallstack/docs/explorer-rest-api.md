---
title: Explorer REST API
description: Getting started with Explorer's auto-generated REST API — authentication, endpoints, search, filtering, and export
---

# Explorer REST API

Explorer can generate a JSON REST API for any registered model. No serializers, no viewsets, no routers — just set `explorer_enable_api = True` on the ModelAdmin and you get full CRUD endpoints with search, filtering, pagination, and CSV/JSON export.

This is not a replacement for Django REST Framework. It's a lightweight, zero-config API for internal tools, scripts, and quick integrations. If your project graduates to a public API, delete this and write proper DRF viewsets — everything else (models, filters, auth) transfers directly.

## Enabling the API

Add `explorer_enable_api = True` to the ModelAdmin you register with Explorer:

```python
# apps/heartbeat/admin.py
@admin.register(Heartbeat)
class HeartbeatAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "status", "response_time_ms", "note")
    search_fields = ("note", "status")
    explorer_enable_api = True
    explorer_export_formats = ["csv", "json"]
```

That's it. Explorer generates API endpoints alongside the HTML views.

### What Gets Wired Up

For a model registered in the "Monitoring" group:

| Method | URL | Action |
|--------|-----|--------|
| `GET` | `/smallstack/api/explorer/monitoring/heartbeat/` | List (paginated, searchable) |
| `POST` | `/smallstack/api/explorer/monitoring/heartbeat/` | Create |
| `GET` | `/smallstack/api/explorer/monitoring/heartbeat/<pk>/` | Detail |
| `PUT` | `/smallstack/api/explorer/monitoring/heartbeat/<pk>/` | Full update |
| `PATCH` | `/smallstack/api/explorer/monitoring/heartbeat/<pk>/` | Partial update |
| `DELETE` | `/smallstack/api/explorer/monitoring/heartbeat/<pk>/` | Delete (returns 204) |

The URL pattern is `api/{url_base}/` where `url_base` matches the model's Explorer URL.

## Authentication

The API supports two authentication methods, checked in order:

### 1. Bearer Token (Recommended for Scripts)

Generate a token:

```bash
uv run python manage.py create_api_token
```

Use it in requests:

```bash
curl -H "Authorization: Bearer sk_live_abc123..." \
  http://localhost:8005/smallstack/api/explorer/monitoring/heartbeat/
```

### 2. Session Cookie (Browser / Dev Tools)

If you're logged into the web UI, you can use the same session:

```bash
# Grab your sessionid from browser dev tools → Application → Cookies
curl -H "Cookie: sessionid=your_session_id" \
  http://localhost:8005/smallstack/api/explorer/monitoring/heartbeat/
```

### Authentication Errors

| Status | Response | Meaning |
|--------|----------|---------|
| `401` | `{"error": "Invalid token"}` | Bearer token not recognized |
| `401` | `{"error": "Authentication required"}` | No token and no active session |
| `403` | `{"error": "Staff access required"}` | User authenticated but not staff |

## List Endpoint

### Basic List

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8005/smallstack/api/explorer/monitoring/heartbeat/
```

Response:

```json
{
    "count": 5280,
    "next": "/smallstack/api/explorer/monitoring/heartbeat/?page=2",
    "previous": null,
    "results": [
        {
            "id": 10223,
            "timestamp": "2026-03-16T22:10:00+00:00",
            "status": "ok",
            "response_time_ms": 0,
            "note": ""
        }
    ]
}
```

The `results` array contains objects with the model's `list_display` fields plus `id`.

### Pagination

```bash
# Page 2
curl "$BASE_URL/?page=2"

# Page size is controlled by list_per_page or explorer_paginate_by on the ModelAdmin
```

### Search

Search uses the `search_fields` defined on the ModelAdmin. Each field is searched with `__icontains`:

```bash
# Search for heartbeats with "fail" in note or status
curl "$BASE_URL/?q=fail"
```

```json
{
    "count": 78,
    "next": "/smallstack/api/explorer/monitoring/heartbeat/?page=2",
    "previous": null,
    "results": [...]
}
```

### Filtering

If the ModelAdmin defines `list_filter`, those fields become query parameters:

```python
class HeartbeatAdmin(admin.ModelAdmin):
    list_filter = ("status",)
    explorer_enable_api = True
```

```bash
curl "$BASE_URL/?status=fail"
```

Filtering uses [django-filters](https://django-filter.readthedocs.io/) under the hood. You can also provide a custom `FilterSet` via `filter_class` on the CRUDView.

### Export

When `explorer_export_formats` is set, append `?format=` to download the full dataset:

```bash
# CSV export
curl "$BASE_URL/?format=csv" -o heartbeats.csv

# JSON export (flat array, not paginated)
curl "$BASE_URL/?format=json" -o heartbeats.json
```

CSV output uses human-readable column headers (from `verbose_name`):

```csv
Timestamp,Status,Response time ms,Note
2026-03-16T22:10:00+00:00,ok,0,
2026-03-16T22:09:00+00:00,ok,0,
```

Export respects any active search/filter — combine `?q=fail&format=csv` to export filtered results.

## Detail Endpoint

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/10223/"
```

```json
{
    "id": 10223,
    "timestamp": "2026-03-16T22:10:00+00:00",
    "status": "ok",
    "response_time_ms": 0,
    "note": ""
}
```

Detail uses `fields` or `detail_fields` from the CRUDView config (which reads from ModelAdmin's `fields` or `fieldsets`). If neither is set, it falls back to `list_display` fields.

## Create

```bash
curl -X POST "$BASE_URL/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "ok",
    "response_time_ms": 42,
    "note": "manual check"
  }'
```

Returns `201` with the created object:

```json
{
    "id": 10224,
    "timestamp": "2026-03-16T23:00:00+00:00",
    "status": "ok",
    "response_time_ms": 42,
    "note": "manual check"
}
```

Validation errors return `400`:

```json
{
    "errors": {
        "status": ["This field is required."]
    }
}
```

## Update

### Full Update (PUT)

All fields required:

```bash
curl -X PUT "$BASE_URL/10224/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "fail",
    "response_time_ms": 5000,
    "note": "timeout"
  }'
```

### Partial Update (PATCH)

Only changed fields:

```bash
curl -X PATCH "$BASE_URL/10224/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"note": "updated note"}'
```

## Delete

```bash
curl -X DELETE "$BASE_URL/10224/" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `204 No Content` on success.

## Permissions

API permissions mirror the CRUDView configuration:

- **Staff-only models** (Explorer default) require `is_staff=True`
- **Readonly models** reject POST, PUT, PATCH, DELETE with `405 Method Not Allowed`
- **Row-level permissions** via `can_update(obj, request)` and `can_delete(obj, request)` hooks return `403`

## Using the API with CRUDView

The API isn't Explorer-specific. Any `CRUDView` subclass can enable it:

```python
from apps.smallstack.crud import CRUDView, Action
from apps.smallstack.mixins import StaffRequiredMixin

class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    mixins = [StaffRequiredMixin]
    enable_api = True
    search_fields = ["name", "category"]
    export_formats = ["csv"]
```

This generates both HTML views and API endpoints from the same config.

### CRUDView API Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `enable_api` | `bool` | `False` | Generate API endpoints |
| `search_fields` | `list` | `[]` | Fields for `?q=` search (reads from `admin_class.search_fields` when using admin_class) |
| `filter_fields` | `list` | `[]` | Fields for query-param filtering (reads from `admin_class.list_filter`) |
| `filter_class` | `FilterSet` | `None` | Custom django-filters class |
| `export_formats` | `list` | `[]` | Enabled formats: `["csv", "json"]` |

### CRUDView Hook Methods

Override these for custom behavior:

```python
class WidgetCRUDView(CRUDView):
    # ...

    @classmethod
    def can_update(cls, obj, request):
        """Row-level update permission."""
        return obj.owner == request.user or request.user.is_superuser

    @classmethod
    def can_delete(cls, obj, request):
        """Row-level delete permission."""
        return request.user.is_superuser

    @classmethod
    def get_list_queryset(cls, qs, request):
        """Filter queryset per-request (tenant scoping, etc.)."""
        if not request.user.is_superuser:
            return qs.filter(owner=request.user)
        return qs

    @classmethod
    def on_form_valid(cls, request, form, obj, is_create=False):
        """Side effects after create/update."""
        if is_create:
            obj.created_by = request.user
            obj.save(update_fields=["created_by"])
```

## Quick Testing Guide

### With curl

```bash
# Set your token
export TOKEN="sk_live_..."
export BASE="http://localhost:8005/smallstack/api/explorer/monitoring/heartbeat"

# List
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/" | python3 -m json.tool

# Search
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/?q=fail" | python3 -m json.tool

# Detail
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/10223/" | python3 -m json.tool

# Create
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"ok","response_time_ms":42,"note":"test"}' \
  "$BASE/" | python3 -m json.tool

# Export CSV
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/?format=csv" -o heartbeats.csv
```

### With Python

```python
import requests

BASE = "http://localhost:8005/smallstack/api/explorer/monitoring/heartbeat"
HEADERS = {"Authorization": "Bearer sk_live_..."}

# List
r = requests.get(f"{BASE}/", headers=HEADERS)
data = r.json()
print(f"{data['count']} records, showing {len(data['results'])}")

# Search
r = requests.get(f"{BASE}/", params={"q": "fail"}, headers=HEADERS)
print(f"{r.json()['count']} failures")

# Create
r = requests.post(f"{BASE}/", json={
    "status": "ok", "response_time_ms": 42, "note": "scripted check"
}, headers=HEADERS)
print(f"Created: {r.json()}")
```

### With JavaScript (from browser console)

```javascript
// Uses session cookie automatically when logged in
const resp = await fetch('/smallstack/api/explorer/monitoring/heartbeat/');
const data = await resp.json();
console.log(`${data.count} records`);
```

## Architecture Notes

The API layer (`apps/smallstack/api.py`) is intentionally thin — ~200 lines of glue code. It reads all config from CRUDView's `_resolve_*` methods, which in turn read from the `admin_class` when available:

```
Request → authenticate → check permissions → route to handler
                                                    ↓
                                    CRUDView._resolve_search_fields()
                                    CRUDView._resolve_filter_fields()
                                    CRUDView._resolve_paginate_by()
                                    CRUDView._get_list_fields()
                                    CRUDView._get_detail_fields()
```

This means any config you set on the ModelAdmin (search fields, filters, pagination) automatically works in both the HTML views and the API.

## See Also

- [Model Explorer](/smallstack/help/smallstack/explorer/) — Overview and display palette
- [Explorer ModelAdmin API](/smallstack/help/smallstack/explorer-admin-api/) — Full attribute reference
- [Authentication](/smallstack/help/smallstack/authentication/) — Django auth, feature flags, and API tokens
