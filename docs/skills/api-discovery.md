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
├── api.py                 # GET /api/schema/ and OPTIONS handler
├── openapi.py             # OpenAPI 3.0.3 spec builder
config/
├── urls.py                # URL registration for /api/schema/openapi.json
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

## Best Practices

1. **Use `/api/schema/` for runtime discovery** — it's lightweight and returns only what you need for building dynamic navigation or config
2. **Use `OPTIONS` for form generation** — it gives you field types, constraints, and choices per-endpoint
3. **Use the OpenAPI spec for tooling** — Swagger UI for interactive docs, code generators for type-safe clients
4. **Cache discovery responses** — these endpoints return metadata that changes only when the server code changes, not with data mutations
5. **Prefer OpenAPI for external integrations** — it's a standard format that any API tool understands
