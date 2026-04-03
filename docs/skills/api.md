# Skill: REST API

SmallStack includes a lightweight REST API layer built on stock Django views. It provides JSON endpoints for CRUDView models with Bearer token authentication, FK expansion, date range filtering, and aggregation. Designed to be replaced by DRF if the project graduates.

## Overview

The API is opt-in per CRUDView. When enabled, `get_urls()` generates JSON list and detail endpoints alongside the existing HTML views. Authentication uses API tokens (Bearer scheme) or falls back to session auth. The URL prefix is configurable via `SMALLSTACK_API_PREFIX` (default: `"api/"`).

## File Locations

```
apps/smallstack/
├── api.py                 # build_api_urls(), auth, serialization, export, aggregation, docs views
├── openapi.py             # build_openapi_spec() — OpenAPI 3.0.3 generator
├── crud.py                # CRUDView — enable_api flag, get_urls() integration
├── middleware.py           # RequestIDMiddleware — X-Request-ID on every response
├── templates/smallstack/api/
│   ├── swagger.html       # Swagger UI (CDN-loaded, /api/docs/)
│   └── redoc.html         # ReDoc (CDN-loaded, /api/redoc/)
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

Create a token via CLI:

```bash
uv run python manage.py create_api_token <username>                      # default: staff
uv run python manage.py create_api_token <username> --access-level auth  # auth-level (register, password mgmt)
uv run python manage.py create_api_token <username> --access-level readonly
```

The raw key is printed once — copy it immediately. It is validated via `APIToken.authenticate(raw_key)` which looks up by prefix + SHA-256 hash.

### Token Authentication Endpoint

For SPAs and mobile apps that need programmatic login:

```
POST /api/auth/token/
Content-Type: application/json

{"username": "alice", "password": "secret123", "expires_hours": 24}

Success → 200:
{
    "token": "aBcD1234...",
    "user": {"id": 1, "username": "alice", "is_staff": true},
    "expires_at": "2026-03-27T14:00:00+00:00"
}

Bad credentials → 401: {"errors": {"__all__": ["Invalid credentials"]}}
Missing fields → 400: {"errors": {"__all__": ["username and password are required"]}}
```

This endpoint:
- **Upserts** — finds existing active login token for the user, regenerates the key, and updates expiry. The old raw key immediately stops working. One login token per user.
- `expires_hours` is optional (default: `SMALLSTACK_LOGIN_TOKEN_EXPIRY_HOURS`, capped at `SMALLSTACK_LOGIN_TOKEN_MAX_HOURS`)
- Response includes `expires_at` (ISO 8601)
- Validates credentials via Django's `authenticate()`
- Respects `axes` rate limiting (same backend as HTML login)
- Is `@csrf_exempt` for cross-origin use
- To logout, call `POST /api/auth/logout/` to revoke server-side, or call this endpoint again to replace the key.

### Session (Browser)

If the user is logged in via Django session, API endpoints work without a token.

## Token Types & Access Levels

### Token Types

| Type | Created By | Purpose |
|------|-----------|---------|
| `login` | `POST /api/auth/token/` or `POST /api/auth/register/` | User session token. One per user (upserted). Has expiry. No access level — inherits user permissions. |
| `manual` | Token Manager UI or `create_token()` management command | System/service tokens. Can have an access level. No expiry unless explicitly set. |

### Access Levels (Manual Tokens Only)

| Access Level | CRUDView Read | CRUDView Write | Auth Management APIs |
|-------------|--------------|----------------|---------------------|
| `auth` | Yes | Yes | Yes (register, password, deactivate) |
| `staff` | Yes | Yes | No (403) |
| `readonly` | Yes | No (403) | No (403) |

Login tokens have no access level — they inherit the authenticated user's permissions (staff status, per-object checks, etc.).

## Auth Management API

These endpoints handle user lifecycle operations. All are `@csrf_exempt` for cross-origin use.

| Endpoint | Auth Required | Purpose |
|----------|--------------|---------|
| `POST /api/auth/token/` | None (credentials) | Login — upsert token |
| `POST /api/auth/logout/` | Any Bearer | Revoke caller's token |
| `POST /api/auth/register/` | Auth-level token | Create user + login token |
| `GET /api/auth/me/` | Any Bearer | Get current user info |
| `POST /api/auth/password/` | Any Bearer | Change own password |
| `GET /api/auth/password-requirements/` | None (public) | List password validation rules |
| `POST /api/auth/users/<id>/password/` | Auth-level token | System password change |
| `POST /api/auth/users/<id>/deactivate/` | Auth-level token | Deactivate user + revoke tokens |
| `GET /api/auth/users/` | Auth-level token | List/search users |
| `GET /api/auth/users/<id>/` | Auth-level token | User detail |
| `PATCH /api/auth/users/<id>/` | Auth-level token | Update user fields |
| `POST /api/auth/token/refresh/` | Login Bearer | Refresh login token |

### POST /api/auth/logout/

Revokes the caller's token server-side. The token immediately stops working.

```
POST /api/auth/logout/
Authorization: Bearer <any-token>

Success → 200: {"message": "Logged out"}
```

### POST /api/auth/register/

Creates a new user (always non-staff, non-superuser) and returns a login token. Requires an auth-level Bearer token and `SMALLSTACK_API_REGISTER_ENABLED=True`.

```
POST /api/auth/register/
Authorization: Bearer <auth-level-token>
Content-Type: application/json

{"username": "alice", "password": "secret123", "email": "alice@example.com"}

Success → 201:
{
    "token": "aBcD1234...",
    "user": {"id": 2, "username": "alice", "is_staff": false},
    "expires_at": "2026-03-27T14:00:00+00:00"
}

Duplicate username → 400: {"errors": {"username": ["A user with that username already exists."]}}
Registration disabled → 403: {"errors": {"__all__": ["Registration is disabled"]}}
```

### GET /api/auth/me/

Returns the authenticated user's profile. Works with any Bearer token.

```
GET /api/auth/me/
Authorization: Bearer <any-token>

→ 200: {"id": 1, "username": "alice", "is_staff": true}
```

### POST /api/auth/password/

Self-service password change. Requires the current password.

```
POST /api/auth/password/
Authorization: Bearer <any-token>
Content-Type: application/json

{"current_password": "old123", "new_password": "new456"}

Success → 200: {"message": "Password updated"}
Wrong password → 400: {"errors": {"__all__": ["Current password is incorrect"]}}
```

### POST /api/auth/users/\<id\>/password/

System password change (no current password required). Requires an auth-level token.

```
POST /api/auth/users/5/password/
Authorization: Bearer <auth-level-token>
Content-Type: application/json

{"new_password": "new456"}

Success → 200: {"message": "Password updated"}
User not found → 404: {"errors": {"__all__": ["User not found"]}}
```

### POST /api/auth/users/\<id\>/deactivate/

Deactivates a user account and revokes all their active tokens. Requires an auth-level token.

```
POST /api/auth/users/5/deactivate/
Authorization: Bearer <auth-level-token>

Success → 200: {"message": "User deactivated"}
User not found → 404: {"errors": {"__all__": ["User not found"]}}
```

### GET /api/auth/password-requirements/

Returns the active Django password validation rules as a list of human-readable strings. No authentication required — useful for showing requirements in registration/password-change forms before submission.

```
GET /api/auth/password-requirements/

→ 200:
{
    "requirements": [
        "Your password must contain at least 8 characters.",
        "Your password can't be a commonly used password.",
        "Your password can't be entirely numeric."
    ]
}
```

### GET /api/auth/users/

List and search users. Requires an auth-level token. Returns paginated results with extended user fields.

```
GET /api/auth/users/?q=alice&page=1&page_size=25
Authorization: Bearer <auth-level-token>

→ 200:
{
    "count": 1,
    "page": 1,
    "total_pages": 1,
    "next": null,
    "previous": null,
    "results": [
        {
            "id": 2, "username": "alice", "email": "alice@example.com",
            "is_staff": false, "first_name": "Alice", "last_name": "Smith",
            "is_active": true, "date_joined": "2026-03-20T14:00:00+00:00"
        }
    ]
}
```

Query parameters:
- `?q=` — searches `username` and `email` (case-insensitive contains)
- `?page=` / `?page_size=` — pagination (same semantics as CRUDView list)

### GET /api/auth/users/\<id\>/

User detail. Returns extended user JSON (same fields as list results).

```
GET /api/auth/users/2/
Authorization: Bearer <auth-level-token>

→ 200:
{
    "id": 2, "username": "alice", "email": "alice@example.com",
    "is_staff": false, "first_name": "Alice", "last_name": "Smith",
    "is_active": true, "date_joined": "2026-03-20T14:00:00+00:00"
}
```

### PATCH /api/auth/users/\<id\>/

Update user fields. Only these fields are allowed: `email`, `first_name`, `last_name`, `is_staff`, `is_active`. Unknown fields return 400 with per-field errors.

```
PATCH /api/auth/users/2/
Authorization: Bearer <auth-level-token>
Content-Type: application/json

{"first_name": "Alice", "is_staff": true}

Success → 200: (updated user JSON)
Unknown field → 400: {"errors": {"username": ["Field 'username' is not allowed"]}}
Duplicate email → 400: {"errors": {"email": ["A user with that email already exists."]}}
```

Empty body `{}` returns 200 with the unchanged user.

### POST /api/auth/token/refresh/

Refresh a login token — regenerates the key and extends the expiry. The old key immediately stops working. Only login tokens can be refreshed; manual tokens are rejected with 403.

```
POST /api/auth/token/refresh/
Authorization: Bearer <login-token>
Content-Type: application/json

{"expires_hours": 48}   ← optional

Success → 200:
{
    "token": "newKey1234...",
    "user": {"id": 1, "username": "alice", "is_staff": false},
    "expires_at": "2026-03-29T14:00:00+00:00"
}

Manual token → 403: {"errors": {"__all__": ["Only login tokens can be refreshed"]}}
Expired token → 401: {"errors": {"__all__": ["Invalid token"]}}
```

- `expires_hours` defaults to `SMALLSTACK_LOGIN_TOKEN_EXPIRY_HOURS`, capped at `SMALLSTACK_LOGIN_TOKEN_MAX_HOURS`
- Response shape matches the login endpoint (`POST /api/auth/token/`)
- Expired tokens are rejected at the auth layer (401) — they cannot be refreshed

### GET /api/schema/

Returns a schema of all registered CRUDView API endpoints and auth endpoints. No authentication required.

```
GET /api/schema/

→ 200:
{
    "endpoints": [
        {
            "url": "/api/explorer/monitoring/heartbeat/",
            "model": "Heartbeat",
            "methods": ["DELETE", "GET", "PATCH", "POST", "PUT"],
            "fields": ["timestamp", "status", "response_time_ms", "note"],
            "list_fields": [...],
            "detail_fields": [...],
            "search_fields": [...],
            "filter_fields": [...],
            "expand_fields": [...],
            "aggregate_fields": [...],
            "extra_fields": [...],
            "export_formats": [...],
            "ordering_fields": [...]
        }
    ],
    "auth": {
        "login": "/api/auth/token/",
        "logout": "/api/auth/logout/",
        "register": "/api/auth/register/",
        "me": "/api/auth/me/",
        "password": "/api/auth/password/",
        "password_requirements": "/api/auth/password-requirements/",
        "users": "/api/auth/users/",
        "token_refresh": "/api/auth/token/refresh/"
    }
}
```

### OPTIONS on CRUDView Endpoints

`OPTIONS` on any CRUDView API endpoint returns field types and constraints without authentication. Useful for building dynamic forms.

```
OPTIONS /api/explorer/monitoring/heartbeat/

→ 200:
{
    "fields": {
        "timestamp": {"type": "datetime", "required": true},
        "status": {"type": "choice", "required": true, "choices": [["ok", "Ok"], ["fail", "Fail"]]},
        "response_time_ms": {"type": "integer", "required": true, "min_value": 0}
    },
    "methods": ["DELETE", "GET", "PATCH", "POST", "PUT"],
    "ordering_fields": ["timestamp", "status", "response_time_ms", "note"]
}
```

Field types include: `string`, `text`, `integer`, `float`, `decimal`, `boolean`, `date`, `datetime`, `time`, `email`, `url`, `choice`, `fk`, `file`. Extra fields (from `api_extra_fields`) are marked `read_only: true`.

### GET /api/schema/openapi.json

Returns an OpenAPI 3.0.3 specification for all registered API endpoints. No authentication required. Useful for code generation, Swagger UI, and frontend SDK tooling.

```
GET /api/schema/openapi.json

→ 200:
{
    "openapi": "3.0.3",
    "info": {"title": "SmallStack API", "version": "1.0.0", ...},
    "paths": {
        "/api/explorer/monitoring/heartbeat/": {...},
        "/api/auth/token/": {...},
        ...
    },
    "components": {
        "schemas": {"Heartbeat": {...}, "Error": {...}},
        "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}
    }
}
```

The spec includes:
- All CRUDView endpoints with request/response schemas
- All auth endpoints (token, register, me, password, users, logout, etc.)
- Component schemas derived from Django model/form fields
- Bearer token security scheme
- Paginated list response envelope

Import into Swagger UI, Postman, or use with code generators like `openapi-typescript` or `openapi-generator`.

### Interactive API Documentation

SmallStack includes built-in Swagger UI and ReDoc pages — no Python packages needed:

| URL | Tool | Purpose |
|-----|------|---------|
| `/api/docs/` | Swagger UI | Interactive "try it out" explorer |
| `/api/redoc/` | ReDoc | Clean, readable API reference |

Both load from CDN and consume the OpenAPI spec at `/api/schema/openapi.json`. Templates are at `apps/smallstack/templates/smallstack/api/`. The views set a per-response CSP to allow `cdn.jsdelivr.net`. See the `api-discovery.md` skill for details.

### Request ID (X-Request-ID)

Every API response includes an `X-Request-ID` header. The `RequestIDMiddleware` (first in the middleware stack) either reuses an incoming `X-Request-ID` from a load balancer or generates `req_{uuid}`. The ID is:

- Stored on `request.id` for use in any downstream code
- Returned in the `X-Request-ID` response header
- Recorded in `RequestLog.request_id` by `ActivityMiddleware`

This allows correlating client-reported errors to specific server-side log entries. Clients should capture and log the `X-Request-ID` from error responses for debugging.

### Architecture Notes

**Single-session token upsert:** The login endpoint (`POST /api/auth/token/`) maintains one active login token per user. Calling it again regenerates the key and immediately invalidates the previous one. This is a security feature — not a bug. Clients should store the token and re-authenticate when it expires rather than expecting multiple concurrent sessions.

**Registration requires auth-level token by design:** The `POST /api/auth/register/` endpoint requires an auth-level Bearer token because registration is a privileged, system-initiated operation — not public self-service. Auth-level tokens belong on servers, never in browser JavaScript. For frontend apps that need user registration, use a backend proxy:

1. React/frontend calls YOUR backend's registration endpoint (no token in the browser)
2. Your backend holds the auth-level token server-side
3. Your backend calls SmallStack's `/api/auth/register/` on behalf of the user

**Token lifecycle:** Login → token → use → refresh (extends session) → logout (revokes). Login tokens are for user sessions (one per user, upserted). Manual tokens are for system/service use (can have access levels). Auth-level tokens gate privileged operations like user management and registration.

**Staff requirement for CRUD APIs:** CRUDViews that use `StaffRequiredMixin` (the default in most SmallStack examples) return 403 for non-staff users. Newly registered users are always non-staff. To give API users access to CRUD endpoints, either promote them to staff via Django admin, or use `LoginRequiredMixin` instead of `StaffRequiredMixin` on CRUDViews that should be accessible to all authenticated users.

## Permission Checking

1. **Authentication** — Bearer token or session. Returns 401 if neither.
2. **Mixin permissions** — Inspects `crud_config.mixins` for `StaffRequiredMixin`. Returns 403 if user is not staff.
3. **Access level enforcement** — Manual tokens with `readonly` access level are blocked from POST/PUT/PATCH/DELETE on CRUDView endpoints (403). Staff tokens can read+write CRUDView endpoints but cannot access auth management APIs. Auth tokens can do everything.
4. **Per-object permissions** — `crud_config.can_update(obj, request)` and `crud_config.can_delete(obj, request)` checked on detail endpoint.
5. **Action checks** — Returns 405 if the HTTP method's action isn't in `crud_config.actions`.

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

#### Ordering

Sort results with `?ordering=`:

```
GET /api/tasks/?ordering=-created_at          → newest first
GET /api/tasks/?ordering=name                 → alphabetical
GET /api/tasks/?ordering=-status,name         → by status desc, then name asc
```

- Comma-separated fields, each optionally prefixed with `-` for descending
- Only fields in `list_fields` and `api_extra_fields` are orderable
- Invalid fields are silently ignored (no 400 — matches Django/DRF convention)
- Ordering is preserved in `next`/`previous` pagination URLs
- Available ordering fields are listed in `GET /api/schema/` and `OPTIONS` responses

User list endpoint (`GET /api/auth/users/`) also supports ordering by `username`, `email`, `pk`.

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

### Bulk Operations

Bulk delete and update use a single endpoint. Bulk delete is enabled by default.

```
POST api/manage/widgets/bulk/
Content-Type: application/json

# Bulk delete
{"action": "delete", "ids": [1, 2, 3]}

Success: {"deleted": [1, 2, 3], "errors": {}, "message": "Deleted 3 items"}
Partial: {"deleted": [1, 3], "errors": {"2": "Cannot delete: referenced by other records"}, "message": "Deleted 2 items, 1 error"}

# Bulk update (requires "update" in bulk_actions)
{"action": "update", "ids": [1, 2, 3], "fields": {"status": "closed"}}

Success: {"updated": [1, 2, 3], "errors": {}, "message": "Updated 3 items"}
```

Each object is processed individually — failures don't block other objects. Controlled by `bulk_actions` on CRUDView or `explorer_bulk_actions` on ModelAdmin (default: `["delete"]`).

### Error Responses

All errors use a consistent format: `{"errors": {"__all__": ["message"]}}` for general errors, or `{"errors": {"field": ["message"]}}` for field-specific validation errors. Frontend code only needs to handle one shape.

| Status | Body | When |
|--------|------|------|
| 400 | `{"errors": {"field": ["message"]}}` | Field validation failure |
| 400 | `{"errors": {"__all__": ["message"]}}` | General validation error |
| 401 | `{"errors": {"__all__": ["Invalid token"]}}` | Bad Bearer token |
| 403 | `{"errors": {"__all__": ["Staff access required"]}}` | Non-staff user |
| 404 | `{"errors": {"__all__": ["Not found"]}}` | Object doesn't exist |
| 405 | `{"errors": {"__all__": ["Method not allowed"]}}` | Action not in `actions` |

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
| `SMALLSTACK_LOGIN_TOKEN_EXPIRY_HOURS` | `24` | Default expiry for login tokens |
| `SMALLSTACK_LOGIN_TOKEN_MAX_HOURS` | `168` | Maximum expiry hours (caps `expires_hours` parameter) |
| `SMALLSTACK_API_REGISTER_ENABLED` | `False` | Enable `POST /api/auth/register/` endpoint |

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

**Dev mode auto-config:** In development (`DEBUG=True`), if no `CORS_ALLOWED_ORIGINS` are set, SmallStack automatically allows requests from any `localhost` or `127.0.0.1` port. This means React on port 3000, Vite on port 5173, etc. all work out of the box with no configuration needed.

For production, set the actual frontend domain:

```bash
CORS_ALLOWED_ORIGINS=https://app.example.com
```

## Custom (Non-CRUD) Endpoints

Not every endpoint fits the CRUD pattern. For actions, integrations, reports, and multi-model workflows, use the `api_view` decorator instead of `enable_api`. It provides the same auth, error handling, and JSON conventions without requiring a CRUDView.

```python
from apps.smallstack.api import api_view, api_error

@api_view(methods=["POST"], require_staff=True)
def run_sync(request):
    target = request.json.get("target")
    if not target:
        return api_error("target is required", 400)
    count = sync_external_system(target)
    return {"synced": count}
```

See **`custom-api-endpoints.md`** for the full reference: parameters, return conventions, error handling, and examples.

## Best Practices

1. **Use `enable_api` only on CRUDViews that need external access** — not every model needs an API
2. **Use `@api_view` for non-CRUD endpoints** — actions, webhooks, reports, orchestration. See `custom-api-endpoints.md`.
3. **Token management** — create tokens via CLI, auth endpoint, or Django admin
4. **Permissions cascade** — API respects the same `mixins` as HTML views. A warning is emitted if `enable_api=True` with no mixins.
5. **No third-party dependency** — built on stock Django views, not DRF
6. **CSRF exempt** — API views use `@csrf_exempt` (required for external API clients)
7. **Filters apply to exports and aggregates** — `?q=search&format=csv` exports only matching rows; `?status=done&sum=hours` aggregates only matching rows
8. **Designed to be replaced** — if you need DRF, delete `api.py` and write viewsets; filters, tokens, and models transfer directly. No conflicts with DRF, dj-rest-auth, or allauth.
