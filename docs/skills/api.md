# Skill: REST API

SmallStack includes a lightweight REST API layer built on stock Django views. It provides JSON endpoints for CRUDView models with Bearer token authentication, FK expansion, date range filtering, and aggregation. Designed to be replaced by DRF if the project graduates.

## Overview

The API is opt-in per CRUDView. When enabled, `get_urls()` generates JSON list and detail endpoints alongside the existing HTML views. Authentication uses API tokens (Bearer scheme) or falls back to session auth. The URL prefix is configurable via `SMALLSTACK_API_PREFIX` (default: `"api/"`).

## File Locations

```
apps/smallstack/
├── api.py                 # build_api_urls(), auth, serialization, export, aggregation
├── crud.py                # CRUDView — enable_api flag, get_urls() integration
```

## How It Works

1. Set `enable_api = True` on your CRUDView
2. `CRUDView.get_urls()` calls `build_api_urls(cls)` to add JSON endpoints
3. Authentication checks Bearer token first, then session
4. Permissions mirror the CRUDView's mixin chain (e.g., `StaffRequiredMixin` → 403 for non-staff)
5. Per-object checks via `can_update()` and `can_delete()` hooks

**Safety warning:** If `enable_api = True` is set with no mixins, a warning is emitted at startup. This catches accidentally public API endpoints.

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
| GET | `api/manage/widgets/` | List (with search, filter, paginate, export, aggregate) |
| POST | `api/manage/widgets/` | Create (if `Action.CREATE` in actions) |
| GET | `api/manage/widgets/<pk>/` | Retrieve single object |
| PUT | `api/manage/widgets/<pk>/` | Full update (if `Action.UPDATE` in actions) |
| PATCH | `api/manage/widgets/<pk>/` | Partial update (merges with existing data) |
| DELETE | `api/manage/widgets/<pk>/` | Delete (if `Action.DELETE` in actions) |

URL names: `{url_base}-api-list` and `{url_base}-api-detail`.

## Authentication

### Bearer Token

```bash
# Token is the raw key returned by create_api_token (a base64url string, ~54 chars)
curl -H "Authorization: Bearer aBcD1234efGh..." https://example.com/api/manage/widgets/
```

Create a token via CLI: `uv run python manage.py create_api_token <username>`. The raw key is printed once — copy it immediately. It is validated via `APIToken.authenticate(raw_key)` which looks up by prefix + SHA-256 hash.

### Token Authentication Endpoint

For SPAs and mobile apps that need programmatic login:

```
POST /api/auth/token/
Content-Type: application/json

{"username": "alice", "password": "secret123"}

Success → 200:
{
    "token": "aBcD1234...",
    "user": {"id": 1, "username": "alice", "is_staff": true}
}

Bad credentials → 401: {"error": "Invalid credentials"}
Missing fields → 400: {"error": "username and password are required"}
```

This endpoint:
- Validates credentials via Django's `authenticate()`
- Creates a new APIToken and returns the raw key
- Respects `axes` rate limiting (same backend as HTML login)
- Is `@csrf_exempt` for cross-origin use

**By design, there is no signup, password reset, or logout endpoint.** Signup stays HTML/admin-provisioned. Password reset stays HTML/email. To "logout", the client discards the token.

### Session (Browser)

If the user is logged in via Django session, API endpoints work without a token.

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
    "page": 1,
    "total_pages": 2,
    "next": "/api/manage/widgets/?page=2",
    "previous": null,
    "results": [
        {"id": 1, "name": "Widget A", "category": {"id": 3, "name": "Tools"}, "is_active": true},
        ...
    ]
}
```

Supports `?q=` search (if `search_fields` set), django-filter parameters (if `filter_fields` set), `?expand=` for FK expansion, `?count_by=`/`?sum=`/`?avg=` for aggregation, and `?format=csv` or `?format=json` for file downloads (if `export_formats` set).

#### Filter Value Formats

| Field Type | Filter Value | Example |
|------------|-------------|---------|
| ForeignKey | Primary key (integer) | `?category=1` |
| BooleanField | `true` or `false` (lowercase) | `?in_stock=true` |
| CharField with choices | Choice **value**, not display name | `?status=active` (not `?status=Active`) |
| DateField | ISO date string | `?due_date=2026-03-20` |
| DateField (range) | `__gte`, `__lte`, `__gt`, `__lt` suffixes | `?created_at__gte=2026-03-01` |

#### Smart Date Filtering

Date and DateTime fields in `filter_fields` automatically get range lookups:

```
?created_at__gte=2026-03-01                              → on or after March 1
?created_at__lte=2026-03-31                              → on or before March 31
?created_at__gte=2026-03-01&created_at__lte=2026-03-31  → March only
?created_at=2026-03-20                                   → exact (still works)
```

This is automatic — no configuration needed. Any Date/DateTime field in `filter_fields` gets `exact`, `gte`, `lte`, `gt`, and `lt` lookups. Non-date fields keep exact match only.

#### Pagination

The `page_size` parameter overrides the default page size (capped at 1000):

```
GET /api/tasks/?page_size=200    → up to 200 results per page
GET /api/tasks/?page_size=9999   → capped at 1000
```

Useful for populating `<select>` dropdowns where you need all options in one call:

```js
const allTasks = await fetch('/api/tasks/?page_size=500').then(r => r.json());
// allTasks.results has up to 500 items — enough for any dropdown
```

The `page` parameter accepts numbers or named aliases:

| Value | Resolves to |
|-------|-------------|
| `1`, `2`, ... | That page number (clamped to valid range) |
| `first` | Page 1 |
| `last` | Last page |
| `next` | Current page + 1 (clamped) |
| `prev` / `previous` | Current page - 1 (clamped) |

Out-of-range numbers are clamped (e.g., `?page=9999` returns the last page, `?page=0` returns page 1). Invalid strings default to page 1. Aliases are case-insensitive.

The response includes `page` (current) and `total_pages` alongside `count`, `next`, and `previous`.

### Detail

```
GET api/manage/widgets/1/

Response:
{"id": 1, "name": "Widget A", "category": {"id": 3, "name": "Tools"}, "is_active": true}
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

The `_serialize()` function converts model instances:

| Field Type | JSON Value |
|------------|------------|
| Datetime/Date | ISO 8601 string |
| ForeignKey | Primary key (`.pk`) — or `{"id": pk, "name": str(obj)}` when expanded |
| Boolean | JSON boolean |
| None | JSON null |
| Everything else | String or raw value |

Always includes `id` field.

## FK Expansion

By default, ForeignKey fields serialize as integer PKs. FK expansion lets you get the related object's ID and name inline, eliminating the need for separate lookup API calls.

### Configuration

```python
class ProductCRUDView(CRUDView):
    model = Product
    fields = ["name", "category", "owner"]
    enable_api = True
    api_expand_fields = ["category"]  # always expand these FKs
```

### Query Parameter

Clients can request additional expansions per-request:

```
GET /api/products/?expand=category,owner
```

Both `api_expand_fields` (defaults) and `?expand=` (per-request) work together — the sets are merged.

### Expanded Format

```json
// Without expansion:
{"id": 1, "name": "Widget", "category": 3}

// With expansion:
{"id": 1, "name": "Widget", "category": {"id": 3, "name": "Electronics"}}
```

Nullable FKs expand to `null`. Non-FK fields in the expand list are silently ignored. The API adds `select_related()` automatically for expanded FK fields to avoid N+1 queries.

### Expansion and Edit Forms

`api_expand_fields` applies to **all** responses — list, detail, create, and update. When an edit form loads a record, FK fields arrive as objects instead of integers. Handle both formats in your frontend:

```js
// Works whether category is expanded {"id": 3, "name": "Electronics"} or raw 3
formData.category = typeof data.category === 'object' ? data.category.id : data.category
```

This pattern is safe to use unconditionally on any FK field.

## Smart Date Filtering

Date and DateTime fields in `filter_fields` automatically support range lookups — no configuration needed:

```python
filter_fields = ["status", "created_at"]
# status → exact match only
# created_at → exact, gte, lte, gt, lt (auto-detected)
```

## Aggregation

Dashboards and reports can compute aggregates server-side instead of fetching all pages client-side.

### count_by

Group counts by a field (must be in `filter_fields`):

```
GET /api/tasks/?count_by=status
→ {"counts": {"todo": 30, "in_progress": 18, "done": 12}, "count": 60, ...results...}
```

### sum / avg / min / max

Numeric aggregates (field must be in `api_aggregate_fields`):

```
GET /api/time-entries/?sum=hours
→ {"sum_hours": 681.4, "count": 166, ...results...}

GET /api/time-entries/?sum=hours&avg=hours&min=hours&max=hours
→ {"sum_hours": 681.4, "avg_hours": 4.1, "min_hours": 0.5, "max_hours": 24.0, ...}
```

### Configuration

```python
class TimeEntryCRUDView(CRUDView):
    model = TimeEntry
    fields = ["task", "hours", "date", "note"]
    enable_api = True
    api_aggregate_fields = ["hours"]   # fields that support sum/avg/min/max
    filter_fields = ["task", "date"]   # count_by works on any filter_field
```

### Composing with Filters

Filters apply before aggregation:

```
GET /api/time-entries/?status=done&date__gte=2026-03-01&sum=hours&count_by=task
→ {"counts": {"1": 45, "2": 38}, "sum_hours": 83.0, "count": 83, ...}
```

### Validation

- `count_by` on a field not in `filter_fields` → 400
- `sum`/`avg`/`min`/`max` on a field not in `api_aggregate_fields` → 400
- Empty queryset → `counts: {}`, aggregate values are `null`
- No aggregate params → response unchanged (backward compatible)

## Extra API Fields

By default, API responses only include fields from `fields` (or `list_fields`/`detail_fields`). To include read-only fields like timestamps without adding them to forms, use `api_extra_fields`:

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "category", "is_active"]
    enable_api = True
    api_extra_fields = ["created_at", "updated_at"]
```

These fields are appended to every API response (list, detail, create, update) but don't appear in create/edit forms. Works with any model attribute, property, or method that returns a serializable value. Datetime fields are serialized as ISO 8601 strings (e.g., `"2026-03-20T14:26:14.308662+00:00"`).

## JSON Body Parsing

JSON request bodies are parsed and converted to Django's `QueryDict` for ModelForm compatibility:
- Lists become `.setlist()` entries (multi-value fields)
- `null` values become empty string `""`
- All values stringified for form processing

## CRUDView Integration

The API layer calls these CRUDView methods:
- `_get_url_base()`, `_get_queryset()` — base configuration
- `get_list_queryset(qs, request)` — view-level queryset filtering
- `search_fields`, `filter_fields`, `filter_class` — search and filter
- `export_formats` — allowed export types
- `paginate_by` — page size. The API respects the CRUDView's `paginate_by` value; if unset, falls back to 25 (the HTML list view is unpaginated when unset)
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
| `api_expand_fields` | `[]` | FK fields always expanded as `{"id": pk, "name": str(obj)}` |
| `api_aggregate_fields` | `[]` | Numeric fields that support `?sum=`, `?avg=`, `?min=`, `?max=` |
| `search_fields` | `[]` | Fields for `?q=` search |
| `filter_fields` | `[]` | Fields for query-param filtering (django-filter). Date/DateTime fields auto-get range lookups. Also used for `?count_by=`. |
| `filter_class` | `None` | Custom django-filters FilterSet class |
| `export_formats` | `[]` | `["csv", "json"]` for `?format=` export |

### Explorer API Attributes

When using Explorer registration, prefix with `explorer_`:

| ModelAdmin Attribute | Maps to |
|---------------------|---------|
| `explorer_enable_api` | `enable_api` |
| `explorer_export_formats` | `export_formats` |
| `explorer_api_extra_fields` | `api_extra_fields` |
| `explorer_api_expand_fields` | `api_expand_fields` |
| `explorer_api_aggregate_fields` | `api_aggregate_fields` |

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
2. **Token management** — create tokens via CLI, auth endpoint, or Django admin
3. **Permissions cascade** — API respects the same `mixins` as HTML views. A warning is emitted if `enable_api=True` with no mixins.
4. **No third-party dependency** — built on stock Django views, not DRF
5. **CSRF exempt** — API views use `@csrf_exempt` (required for external API clients)
6. **Filters apply to exports and aggregates** — `?q=search&format=csv` exports only matching rows; `?status=done&sum=hours` aggregates only matching rows
7. **Designed to be replaced** — if you need DRF, delete `api.py` and write viewsets; filters, tokens, and models transfer directly. No conflicts with DRF, dj-rest-auth, or allauth.
