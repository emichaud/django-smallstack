# Skill: API Discovery Endpoints

SmallStack provides three public endpoints for discovering the API — no authentication required. Each serves a different use case: runtime configuration, dynamic form generation, and tooling/code generation.

## Overview

| Endpoint | Format | Use Case |
|----------|--------|----------|
| `GET /api/schema/` | SmallStack JSON | Runtime discovery — list endpoints, fields, filters, ordering |
| `OPTIONS /api/{endpoint}/` | SmallStack JSON | Dynamic forms — field types, constraints, allowed methods |
| `GET /api/schema/openapi.json` | OpenAPI 3.0.3 | Tooling — Swagger UI, Postman, code generators |

All three are unauthenticated. They expose metadata only, not data.

## File Locations

```
apps/smallstack/
├── api.py                 # GET /api/schema/, OPTIONS handler, Swagger/ReDoc views
├── openapi.py             # OpenAPI 3.0.3 spec builder
├── templates/smallstack/api/
│   ├── swagger.html       # Swagger UI page (CDN-loaded)
│   └── redoc.html         # ReDoc page (CDN-loaded)
config/
├── urls.py                # URL registration for schema, docs, and redoc
```

## GET /api/schema/ — SmallStack Native Schema

Returns all registered CRUDView API endpoints and auth endpoint URLs.

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
            "list_fields": ["timestamp", "status", "response_time_ms", "note"],
            "detail_fields": ["timestamp", "status", "response_time_ms", "note"],
            "search_fields": ["note", "status"],
            "filter_fields": ["status"],
            "expand_fields": [],
            "aggregate_fields": [],
            "extra_fields": [],
            "export_formats": ["csv", "json"],
            "ordering_fields": ["timestamp", "status", "response_time_ms", "note"]
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

**When to use:** Runtime configuration in SPAs — build navigation from the API, discover available filters and ordering fields, check which methods are allowed before rendering UI controls.

## OPTIONS /api/{endpoint}/ — Field Metadata

Returns field types, constraints, allowed methods, and ordering fields for a single endpoint.

```
OPTIONS /api/explorer/monitoring/heartbeat/

→ 200:
{
    "fields": {
        "timestamp": {"type": "datetime", "required": true},
        "status": {"type": "choice", "required": true, "choices": [["ok", "Ok"], ["fail", "Fail"]]},
        "response_time_ms": {"type": "integer", "required": true, "min_value": 0},
        "note": {"type": "string", "required": false, "max_length": 200}
    },
    "methods": ["DELETE", "GET", "PATCH", "POST", "PUT"],
    "ordering_fields": ["timestamp", "status", "response_time_ms", "note"]
}
```

Field types: `string`, `text`, `integer`, `float`, `decimal`, `boolean`, `date`, `datetime`, `time`, `email`, `url`, `choice`, `fk`, `file`. Extra fields (from `api_extra_fields`) are marked `read_only: true`.

**When to use:** Dynamic form generation — render create/edit forms with correct input types, validation constraints, and choice dropdowns without hardcoding field metadata in the frontend.

## GET /api/schema/openapi.json — OpenAPI 3.0.3 Specification

Returns a standard OpenAPI document covering all CRUD and auth endpoints.

```
GET /api/schema/openapi.json

→ 200:
{
    "openapi": "3.0.3",
    "info": {
        "title": "SmallStack API",
        "version": "1.0.0",
        "description": "Auto-generated API documentation for SmallStack."
    },
    "paths": {
        "/api/explorer/monitoring/heartbeat/": {
            "get": {
                "tags": ["Heartbeat"],
                "summary": "List Heartbeat records",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                    {"name": "page_size", "in": "query", "schema": {"type": "integer"}},
                    {"name": "ordering", "in": "query", "schema": {"type": "string"}}
                ],
                "security": [{"bearerAuth": []}],
                "responses": {"200": {"description": "Paginated list", ...}}
            },
            "post": {...}
        },
        "/api/auth/token/": {...},
        ...
    },
    "components": {
        "schemas": {
            "Heartbeat": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "readOnly": true},
                    "status": {"type": "string", "enum": ["ok", "fail"]},
                    "response_time_ms": {"type": "integer", "minimum": 0},
                    ...
                },
                "required": ["status", "response_time_ms"]
            },
            "Error": {
                "type": "object",
                "properties": {
                    "errors": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}}
                }
            }
        },
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "SmallStack API Token"}
        }
    }
}
```

The spec includes:
- All CRUDView endpoints with request/response schemas derived from Django model/form fields
- All auth endpoints (token, register, me, password, users, logout, etc.)
- Component schemas with field types, constraints (`maxLength`, `minimum`, `maximum`), enums, and required markers
- Bearer token security scheme
- Paginated list response envelope

**When to use:** Import into Swagger UI, Postman, or feed to code generators.

## Built-In Interactive Documentation

SmallStack includes Swagger UI and ReDoc pages that consume the OpenAPI spec:

| URL | Tool | Purpose |
|-----|------|---------|
| `/api/docs/` | Swagger UI | Interactive "try it out" explorer — send real requests from the browser |
| `/api/redoc/` | ReDoc | Clean three-panel API reference for sharing with teams |

Both load from CDN (`cdn.jsdelivr.net`) — no Python packages required. The views set a per-response CSP header to allow the CDN scripts. Templates are at `apps/smallstack/templates/smallstack/api/swagger.html` and `redoc.html`.

See the help page at `/help/smallstack/api-documentation/` for theming options, CSP details, and troubleshooting.

## Comparison Table

| | `/api/schema/` | `OPTIONS` | `/api/schema/openapi.json` |
|---|---|---|---|
| **Scope** | All endpoints | Single endpoint | All endpoints |
| **Field detail** | Names only | Types + constraints | Types + constraints |
| **Format** | SmallStack JSON | SmallStack JSON | OpenAPI 3.0.3 |
| **Auth required** | No | No | No |
| **Best for** | Runtime nav/config | Dynamic forms | Tooling/code gen |

## Using with Frontend Tooling

### Swagger UI (CDN)

```html
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "http://localhost:8005/api/schema/openapi.json",
      dom_id: '#swagger-ui',
    });
  </script>
</body>
</html>
```

### openapi-typescript

Generate TypeScript types from the OpenAPI spec:

```bash
npx openapi-typescript http://localhost:8005/api/schema/openapi.json -o src/api-types.ts
```

Then use the generated types in your frontend code for type-safe API calls.

### Postman

Import the spec URL directly:

1. Open Postman → Import → Link
2. Enter `http://localhost:8005/api/schema/openapi.json`
3. All endpoints are imported with parameters, request bodies, and auth headers

## Spec Validity Gate

`apps/smallstack/test_openapi_validity.py` runs `openapi-spec-validator` against both `build_openapi_spec()` and the live `/api/schema/openapi.json` endpoint on every test run. The spec MUST stay valid OpenAPI 3.0.3 — Swagger UI silently renders garbage if it isn't, so this test is the only thing standing between "Swagger looks fine in dev" and "Swagger shows a blank page in prod."

If you touch any of these and the test fails, that's the regression:
- `apps/smallstack/openapi.py` (the builder)
- `apps/smallstack/api.py:api_openapi_schema` (the view)
- Any CRUDView attribute that participates in schema generation (`fields`, `list_fields`, `filter_fields`, `api_extra_fields`, etc.)

The validator catches missing required keys, malformed `$ref` paths, unknown type names, empty operations, and most other structural issues. Read its output as "the spec is broken in this specific way," not "the tests are flaky."

## CORS — calling the API from a browser SPA

`django-cors-headers` ships in `INSTALLED_APPS` but the settings it reads
aren't surfaced anywhere obvious — adding them is one of the more common
first-time-setup blockers when wiring a SPA against the API.

### When you need it

You need CORS configuration when **a browser-side caller** (a SPA at
a different origin, an iframe widget hosted on another site, a browser
extension, etc.) calls the SmallStack API. You do *not* need it when:

- The caller is server-side (curl, Python `requests`, a Rust client) —
  same-origin policy is browser-only.
- The caller is hosted at the same origin (e.g. you serve the SPA from
  Django itself via `templates/`).
- The caller is Claude Desktop / a native MCP client — those don't run
  inside a browser at all.

### The minimal setup

Add the following to `config/settings/development.py` (or per-env equivalent):

```python
# config/settings/development.py
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",      # vite default
    "http://localhost:3000",      # next/cra/etc.
    "http://localhost:4173",      # vite preview
]

# Only required if the SPA sends credentials (cookies, Authorization with
# session). For Bearer-only flows you can leave this False.
CORS_ALLOW_CREDENTIALS = False

# These are django-cors-headers defaults — listed here so you know what
# the API actually advertises:
# CORS_ALLOW_HEADERS = default_headers + ("Authorization", "Content-Type", ...)
# CORS_ALLOW_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]
```

In production, replace the localhost entries with your real frontend
origins:

```python
# config/settings/production.py
import os
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
```

### Worked example — Vite + fetch + Bearer

```javascript
// frontend/src/api.js (Vite project at http://localhost:5173)
const API = "http://localhost:8005";
const token = localStorage.getItem("smallstack_token");   // see "Minting" below

export async function listTickets() {
  const response = await fetch(`${API}/api/tickets/`, {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Accept": "application/json",
    },
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}

export async function createTicket(body) {
  const response = await fetch(`${API}/api/tickets/`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}
```

Two browser-only gotchas this avoids:

1. **Preflight failures.** Any non-simple request (POST with JSON body,
   any custom headers including `Authorization`) triggers an OPTIONS
   preflight. The django-cors-headers middleware responds correctly only
   if your origin is in `CORS_ALLOWED_ORIGINS`. A missing entry surfaces
   as a CORS error in the browser console with **no useful message in
   the network tab** — always check `CORS_ALLOWED_ORIGINS` first.

2. **Credentialed requests with wildcard origins.** If you ever set
   `CORS_ALLOW_ALL_ORIGINS = True`, the spec forbids
   `CORS_ALLOW_CREDENTIALS = True`. The browser will silently fail the
   preflight. Use specific origins when you need credentials.

### Minting a token for the SPA

The SPA needs a token to send. Three patterns by trust level:

| Pattern | Token source | Suitable for |
|---|---|---|
| User mints in UI | `/smallstack/tokens/` → reveal-once form, paste into SPA settings | Internal tooling, dev/staging |
| Login form → API mint | SPA POSTs to `/api/auth/login/` with username+password, receives a Bearer token | User-facing SaaS |
| OAuth/PKCE | SPA implements the authorize-code-exchange flow against `/.well-known/oauth-authorization-server` | Third-party clients |

For most user-facing SPAs, pattern 2 is right. The login endpoint is
documented in `manage-api-tokens.md`; the relevant view is
`api/auth/login/` and it returns the same shape as a manual mint.

### CSRF + cookies (the path you probably *don't* want)

If your SPA shares an origin with Django (e.g. `app.example.com` for
the SPA and the same domain for Django) and you set
`CORS_ALLOW_CREDENTIALS = True`, you're back in CSRF territory: the
browser will send the session cookie, Django enforces CSRF, and the
SPA needs to read the `csrftoken` cookie and send it as the
`X-CSRFToken` header on every state-changing request.

This works but is the most failure-prone pattern. **Prefer Bearer
tokens** — they sidestep CSRF entirely (the API view auth path checks
the Authorization header *before* enforcing CSRF, by design). Reserve
the cookie+CSRF path for cases where the SPA is genuinely embedded in
the same trust domain as the Django site.

## Smoke-Testing the API

When you need to verify the API is actually serving from a running server (not just that `pytest` passes against the test client), use `make api-test`:

```bash
make run             # one terminal
make api-test        # another — mints readonly token, GETs /api/schema/,
                     # GETs a sample endpoint, revokes the token
```

Exit codes: `0` clean, `2` connection refused, `4` malformed response or non-200. Catches reverse-proxy bugs, header-stripping middleware, port conflicts — the stuff `pytest` can't see because it runs in-process. The companion command for MCP is `make mcp-test`. Wire both into CI for one signal per deploy.

## Best Practices

1. **Use `/api/schema/` for runtime discovery** — it's lightweight and returns only what you need for building dynamic navigation or config
2. **Use `OPTIONS` for form generation** — it gives you field types, constraints, and choices per-endpoint
3. **Use the OpenAPI spec for tooling** — Swagger UI for interactive docs, code generators for type-safe clients
4. **Cache discovery responses** — these endpoints return metadata that changes only when the server code changes, not with data mutations
5. **Prefer OpenAPI for external integrations** — it's a standard format that any API tool understands
6. **Run `make api-test` before merging** — proves the API actually serves a real HTTP request, not just that pytest passes in-process
