# Skill: REST API

SmallStack includes a lightweight REST API layer built on stock Django views (~360 lines of glue code). It provides JSON endpoints for CRUDView models with Bearer token authentication. Designed to be replaced by DRF if the project graduates.

## Overview

The API is opt-in per CRUDView. When enabled, `get_urls()` generates JSON list and detail endpoints alongside the existing HTML views. Authentication uses API tokens (Bearer scheme) or falls back to session auth. The URL prefix is configurable via `SMALLSTACK_API_PREFIX` (default: `"api/"`).

## File Locations

```
apps/smallstack/
├── api.py                 # build_api_urls(), auth, serialization, export
├── crud.py                # CRUDView — enable_api flag, get_urls() integration
```

## How It Works

1. Set `enable_api = True` on your CRUDView
2. `CRUDView.get_urls()` calls `build_api_urls(cls)` to add JSON endpoints
3. Authentication checks Bearer token first, then session
4. Permissions mirror the CRUDView's mixin chain (e.g., `StaffRequiredMixin` → 403 for non-staff)
5. Per-object checks via `can_update()` and `can_delete()` hooks

## Enabling the API

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    url_base = "manage/widgets"
    enable_api = True
```

This generates:

| Method | URL | Action |
|--------|-----|--------|
| GET | `api/manage/widgets/` | List (with search, filter, paginate, export) |
| POST | `api/manage/widgets/` | Create (if `Action.CREATE` in actions) |
| GET | `api/manage/widgets/<pk>/` | Retrieve single object |
| PUT | `api/manage/widgets/<pk>/` | Full update (if `Action.UPDATE` in actions) |
| PATCH | `api/manage/widgets/<pk>/` | Partial update (merges with existing data) |
| DELETE | `api/manage/widgets/<pk>/` | Delete (if `Action.DELETE` in actions) |

URL names: `{url_base}-api-list` and `{url_base}-api-detail`.

## Authentication

### Bearer Token

```bash
curl -H "Authorization: Bearer <token>" https://example.com/api/manage/widgets/
```

The token is validated via `APIToken.authenticate(raw_key)`. On success, `request._api_token_auth = True` is set.

### Session (Browser)

If the user is logged in via Django session, API endpoints work without a token.

### Token Authentication

The API uses Bearer token authentication. Token management is handled via Django admin or management commands. The authentication layer validates tokens and sets `request._api_token_auth = True` on success.

## Permission Checking

1. **Authentication** — Bearer token or session. Returns 401 if neither.
2. **Mixin permissions** — Inspects `crud_config.mixins` for `StaffRequiredMixin`. Returns 403 if user is not staff.
3. **Per-object permissions** — `crud_config.can_update(obj, request)` and `crud_config.can_delete(obj, request)` checked on detail endpoint.
4. **Action checks** — Returns 405 if the HTTP method's action isn't in `crud_config.actions`.

## Request/Response Format

### List

```
GET api/manage/widgets/
Authorization: Bearer <token>

Response:
{
    "count": 42,
    "next": "http://example.com/api/manage/widgets/?page=2",
    "previous": null,
    "results": [
        {"id": 1, "name": "Widget A", "category": "Tools", "is_active": true},
        ...
    ]
}
```

Supports `?q=` search (if `search_fields` set), django-filter parameters (if `filter_fields` set), and `?format=csv` or `?format=json` for file downloads (if `export_formats` set).

### Detail

```
GET api/manage/widgets/1/

Response:
{"id": 1, "name": "Widget A", "category": "Tools", "is_active": true}
```

### Create

```
POST api/manage/widgets/
Content-Type: application/json

{"name": "New Widget", "category": "Tools", "is_active": true}

Success: 201 with serialized object
Errors: 400 with {"errors": {"field": ["message"]}}
```

### Update (PUT/PATCH)

```
PATCH api/manage/widgets/1/
Content-Type: application/json

{"category": "Updated"}

Success: 200 with serialized object
```

PATCH merges incoming data with the existing object's values. PUT requires all fields.

### Delete

```
DELETE api/manage/widgets/1/

Success: 204 No Content
```

### Error Responses

| Status | Body | When |
|--------|------|------|
| 400 | `{"errors": form.errors}` | Validation failure |
| 401 | `{"error": "Invalid token"}` | Bad Bearer token |
| 403 | `{"error": "Staff access required"}` | Non-staff user |
| 404 | `{"error": "Not found"}` | Object doesn't exist |
| 405 | `{"error": "Method not allowed"}` | Action not in `actions` |

## Serialization

The `_serialize(obj, fields)` function converts model instances:

| Field Type | JSON Value |
|------------|------------|
| Datetime/Date | ISO 8601 string |
| ForeignKey | Primary key (`.pk`) |
| Boolean | JSON boolean |
| None | JSON null |
| Everything else | String or raw value |

Always includes `id` field.

### ForeignKey Fields

ForeignKey fields are serialized as their primary key (integer). To display related object names in a frontend, fetch the related objects separately and build a lookup map:

```javascript
// Fetch categories once, build lookup
const categories = await fetch('/api/manage/categories/').then(r => r.json());
const categoryMap = Object.fromEntries(categories.results.map(c => [c.id, c.name]));

// Resolve in product list
products.results.map(p => ({
  ...p,
  categoryName: categoryMap[p.category] ?? 'Unknown',
}));
```

> **Note:** There is no built-in FK expansion. This is by design — the API is intentionally minimal. If you need nested serialization, consider graduating to DRF.

## JSON Body Parsing

JSON request bodies are parsed and converted to Django's `QueryDict` for ModelForm compatibility:
- Lists become `.setlist()` entries (multi-value fields)
- `null` values become empty string `""`
- All values stringified for form processing

## Extra API Fields

By default, API responses only include fields from `fields` (or `list_fields`/`detail_fields`). To include read-only fields like timestamps without adding them to forms, use `api_extra_fields`:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    enable_api = True
    api_extra_fields = ["created_at", "updated_at"]
```

These fields are appended to every API response (list, detail, create, update) but don't appear in create/edit forms. Works with any model attribute, property, or method that returns a serializable value.

## CRUDView Integration

The API layer calls these CRUDView methods:
- `_get_url_base()`, `_get_queryset()` — base configuration
- `get_list_queryset(qs, request)` — view-level queryset filtering
- `search_fields`, `filter_fields`, `filter_class` — search and filter
- `export_formats` — allowed export types
- `paginate_by` — page size (default 25 for API)
- `form_class` / `_make_form_class()` — forms for create/update
- `on_form_valid(request, form, obj, is_create)` — post-save hook
- `can_update(obj, request)`, `can_delete(obj, request)` — per-object permissions

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `SMALLSTACK_API_PREFIX` | `"api/"` | URL prefix for all API endpoints |

### CRUDView API Attributes

| Attribute | Default | Description |
|-----------|---------|-------------|
| `enable_api` | `False` | Generate JSON API endpoints |
| `api_extra_fields` | `[]` | Read-only fields appended to API responses |
| `search_fields` | `[]` | Fields for `?q=` search |
| `filter_fields` | `[]` | Fields for query-param filtering (django-filter) |
| `filter_class` | `None` | Custom django-filters FilterSet class |
| `export_formats` | `[]` | `["csv", "json"]` for `?format=` export |

## CORS Configuration

SmallStack includes `django-cors-headers` for cross-origin API access. If your frontend runs on a different origin (e.g., React on port 3000, Django on port 8000), set `CORS_ALLOWED_ORIGINS` in your `.env`:

```bash
# .env
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
```

This is already wired up in `config/settings/base.py` — no code changes needed. The middleware is installed and reads from the environment variable. By default (empty string), no cross-origin requests are allowed.

For production, set the actual frontend domain:

```bash
CORS_ALLOWED_ORIGINS=https://app.example.com
```

## Best Practices

1. **Use `enable_api` only on CRUDViews that need external access** — not every model needs an API
2. **Token management** — create tokens via Django admin or management commands
3. **Permissions cascade** — API respects the same `mixins` as HTML views
4. **No third-party dependency** — built on stock Django views, not DRF
5. **CSRF exempt** — API views use `@csrf_exempt` (required for external API clients)
6. **Filters apply to exports** — `?q=search&format=csv` exports only matching rows
7. **Designed to be replaced** — if you need DRF, delete `api.py` and write viewsets; filters, tokens, and models transfer directly
