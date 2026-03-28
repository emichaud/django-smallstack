"""OpenAPI 3.0.3 spec generator for SmallStack API.

Reads the ``_api_registry`` populated by ``build_api_urls()`` and produces a
standard OpenAPI document.  The single public entry point is
``build_openapi_spec()``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, dict[str, str]] = {
    "string": {"type": "string"},
    "text": {"type": "string"},
    "integer": {"type": "integer"},
    "float": {"type": "number", "format": "float"},
    "decimal": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
    "time": {"type": "string", "format": "time"},
    "email": {"type": "string", "format": "email"},
    "url": {"type": "string", "format": "uri"},
    "fk": {"type": "integer"},
    "file": {"type": "string", "format": "binary"},
}


def _smallstack_type_to_openapi(field_schema: dict[str, object]) -> dict[str, object]:
    """Convert a SmallStack field schema dict to an OpenAPI property dict."""
    st = field_schema.get("type", "string")
    base = dict(_TYPE_MAP.get(st, {"type": "string"}))

    if st == "choice" and "choices" in field_schema:
        base["type"] = "string"
        base["enum"] = [c[0] for c in field_schema["choices"]]

    if st == "fk" and "related_model" in field_schema:
        base["description"] = f"FK → {field_schema['related_model']}"

    return base


# ---------------------------------------------------------------------------
# Schema builders
# ---------------------------------------------------------------------------


def _build_crud_schema(crud_config) -> dict:
    """Generate OpenAPI component schema for a model's fields."""
    from .api import _field_to_schema, _model_field_type

    form_class = crud_config.form_class or crud_config._make_form_class()
    form = form_class()

    properties: dict[str, dict] = {"id": {"type": "integer", "readOnly": True}}
    required: list[str] = []

    for name, form_field in form.fields.items():
        field_info = _field_to_schema(name, form_field, crud_config.model)
        prop = _smallstack_type_to_openapi(field_info)
        if field_info.get("max_length"):
            prop["maxLength"] = field_info["max_length"]
        if field_info.get("min_value") is not None:
            prop["minimum"] = field_info["min_value"]
        if field_info.get("max_value") is not None:
            prop["maximum"] = field_info["max_value"]
        properties[name] = prop
        if field_info.get("required"):
            required.append(name)

    # Append api_extra_fields as read-only
    for name in getattr(crud_config, "api_extra_fields", []):
        st = _model_field_type(crud_config.model, name)
        prop = dict(_TYPE_MAP.get(st, {"type": "string"}))
        prop["readOnly"] = True
        properties[name] = prop

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _build_list_response_schema(ref_name: str) -> dict:
    """Build the paginated envelope schema referencing a component."""
    return {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "page": {"type": "integer"},
            "total_pages": {"type": "integer"},
            "next": {"type": "string", "nullable": True},
            "previous": {"type": "string", "nullable": True},
            "results": {
                "type": "array",
                "items": {"$ref": f"#/components/schemas/{ref_name}"},
            },
        },
    }


def _build_error_schema() -> dict:
    """Standard error envelope."""
    return {
        "type": "object",
        "properties": {
            "errors": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    }


def _build_crud_paths(crud_config, list_url_name: str) -> dict[str, dict]:
    """Generate path objects for a single CRUDView (list + detail)."""
    from django.urls import reverse

    from .api import _get_methods_from_actions
    from .crud import Action

    list_url = reverse(list_url_name)
    detail_url = list_url.rstrip("/") + "/{id}/"
    model_name = crud_config.model.__name__
    ref = f"#/components/schemas/{model_name}"
    methods = _get_methods_from_actions(crud_config)
    actions = set(crud_config.actions)
    tag = model_name

    paths: dict[str, dict] = {}

    # List endpoint
    list_ops: dict[str, dict] = {}
    if "GET" in methods and Action.LIST in actions:
        parameters: list[dict] = [
            {"name": "page", "in": "query", "schema": {"type": "integer"}},
            {"name": "page_size", "in": "query", "schema": {"type": "integer"}},
            {"name": "ordering", "in": "query", "schema": {"type": "string"},
             "description": "Comma-separated fields, prefix with - for descending"},
        ]
        search_fields = crud_config._resolve_search_fields()
        if search_fields:
            parameters.append(
                {"name": "q", "in": "query", "schema": {"type": "string"},
                 "description": f"Search {', '.join(search_fields)}"},
            )

        # Filter parameters
        filter_fields = crud_config._resolve_filter_fields()
        for field_name in filter_fields:
            parameters.append(
                {"name": field_name, "in": "query", "schema": {"type": "string"},
                 "description": f"Filter by {field_name}"},
            )

        # Expand parameter
        expand_fields = getattr(crud_config, "api_expand_fields", [])
        if expand_fields:
            parameters.append(
                {"name": "expand", "in": "query", "schema": {"type": "string"},
                 "description": f"Comma-separated FK fields to expand: {', '.join(expand_fields)}"},
            )

        # Export format parameter
        export_formats = getattr(crud_config, "export_formats", [])
        if export_formats:
            parameters.append(
                {"name": "format", "in": "query",
                 "schema": {"type": "string", "enum": list(export_formats)},
                 "description": "Export format (returns file download)"},
            )

        # Aggregation parameters
        agg_fields = getattr(crud_config, "api_aggregate_fields", [])
        if agg_fields:
            for agg in ["sum", "avg", "min", "max"]:
                parameters.append(
                    {"name": agg, "in": "query", "schema": {"type": "string"},
                     "description": f"Compute {agg} of a numeric field ({', '.join(agg_fields)})"},
                )
            parameters.append(
                {"name": "count_by", "in": "query", "schema": {"type": "string"},
                 "description": "Group counts by field"},
            )
        list_ops["get"] = {
            "tags": [tag],
            "summary": f"List {model_name} records",
            "parameters": parameters,
            "security": [{"bearerAuth": []}],
            "responses": {
                "200": {
                    "description": "Paginated list",
                    "content": {"application/json": {
                        "schema": _build_list_response_schema(model_name),
                    }},
                },
            },
        }

    if "POST" in methods and Action.CREATE in actions:
        list_ops["post"] = {
            "tags": [tag],
            "summary": f"Create a {model_name}",
            "security": [{"bearerAuth": []}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": ref}}},
            },
            "responses": {
                "201": {
                    "description": "Created",
                    "content": {"application/json": {"schema": {"$ref": ref}}},
                },
                "400": {
                    "description": "Validation error",
                    "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"},
                    }},
                },
            },
        }

    if list_ops:
        paths[list_url] = list_ops

    # Detail endpoint
    detail_ops: dict[str, dict] = {}
    detail_params = [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
    ]

    if Action.DETAIL in actions:
        detail_ops["get"] = {
            "tags": [tag],
            "summary": f"Get a {model_name}",
            "parameters": detail_params,
            "security": [{"bearerAuth": []}],
            "responses": {
                "200": {
                    "description": "Detail",
                    "content": {"application/json": {"schema": {"$ref": ref}}},
                },
                "404": {"description": "Not found"},
            },
        }

    if Action.UPDATE in actions:
        detail_ops["put"] = {
            "tags": [tag],
            "summary": f"Update a {model_name}",
            "parameters": detail_params,
            "security": [{"bearerAuth": []}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": ref}}},
            },
            "responses": {
                "200": {
                    "description": "Updated",
                    "content": {"application/json": {"schema": {"$ref": ref}}},
                },
                "400": {
                    "description": "Validation error",
                    "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"},
                    }},
                },
            },
        }
        detail_ops["patch"] = {
            "tags": [tag],
            "summary": f"Partially update a {model_name}",
            "parameters": detail_params,
            "security": [{"bearerAuth": []}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": ref}}},
            },
            "responses": {
                "200": {
                    "description": "Updated",
                    "content": {"application/json": {"schema": {"$ref": ref}}},
                },
            },
        }

    if Action.DELETE in actions:
        detail_ops["delete"] = {
            "tags": [tag],
            "summary": f"Delete a {model_name}",
            "parameters": detail_params,
            "security": [{"bearerAuth": []}],
            "responses": {"204": {"description": "Deleted"}},
        }

    if detail_ops:
        paths[detail_url] = detail_ops

    return paths


# ---------------------------------------------------------------------------
# Auth paths (static)
# ---------------------------------------------------------------------------


def _build_auth_paths() -> dict[str, dict]:
    """Static path definitions for all auth endpoints."""
    tag = "Auth"
    bearer = [{"bearerAuth": []}]

    return {
        "/api/auth/token/": {
            "post": {
                "tags": [tag],
                "summary": "Login — exchange credentials for a Bearer token",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string"},
                            "password": {"type": "string"},
                            "expires_hours": {"type": "integer"},
                        },
                        "required": ["username", "password"],
                    }}},
                },
                "responses": {
                    "200": {"description": "Token issued"},
                    "401": {"description": "Invalid credentials"},
                },
            },
        },
        "/api/auth/token/refresh/": {
            "post": {
                "tags": [tag],
                "summary": "Refresh a login token",
                "security": bearer,
                "responses": {"200": {"description": "Token refreshed"}},
            },
        },
        "/api/auth/register/": {
            "post": {
                "tags": [tag],
                "summary": "Register a new user",
                "security": bearer,
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string"},
                            "password": {"type": "string"},
                            "email": {"type": "string", "format": "email"},
                        },
                        "required": ["username", "password"],
                    }}},
                },
                "responses": {
                    "201": {"description": "User created"},
                    "400": {"description": "Validation error"},
                },
            },
        },
        "/api/auth/me/": {
            "get": {
                "tags": [tag],
                "summary": "Get current user profile",
                "security": bearer,
                "responses": {"200": {"description": "User profile"}},
            },
        },
        "/api/auth/password/": {
            "post": {
                "tags": [tag],
                "summary": "Change own password",
                "security": bearer,
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "current_password": {"type": "string"},
                            "new_password": {"type": "string"},
                        },
                        "required": ["current_password", "new_password"],
                    }}},
                },
                "responses": {
                    "200": {"description": "Password updated"},
                    "400": {"description": "Validation error"},
                },
            },
        },
        "/api/auth/password-requirements/": {
            "get": {
                "tags": [tag],
                "summary": "Get password validation rules",
                "responses": {"200": {"description": "Password requirements"}},
            },
        },
        "/api/auth/users/": {
            "get": {
                "tags": [tag],
                "summary": "List and search users",
                "security": bearer,
                "parameters": [
                    {"name": "q", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                    {"name": "page_size", "in": "query", "schema": {"type": "integer"}},
                    {"name": "ordering", "in": "query", "schema": {"type": "string"},
                     "description": "Order by: username, email, pk"},
                ],
                "responses": {"200": {"description": "Paginated user list"}},
            },
        },
        "/api/auth/users/{id}/": {
            "get": {
                "tags": [tag],
                "summary": "Get user detail",
                "security": bearer,
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {"description": "User detail"},
                    "404": {"description": "Not found"},
                },
            },
            "patch": {
                "tags": [tag],
                "summary": "Update a user",
                "security": bearer,
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                ],
                "requestBody": {
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string", "format": "email"},
                            "first_name": {"type": "string"},
                            "last_name": {"type": "string"},
                            "is_staff": {"type": "boolean"},
                            "is_active": {"type": "boolean"},
                        },
                    }}},
                },
                "responses": {"200": {"description": "User updated"}},
            },
        },
        "/api/auth/users/{id}/password/": {
            "post": {
                "tags": [tag],
                "summary": "Set a user's password (admin)",
                "security": bearer,
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                ],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {"new_password": {"type": "string"}},
                        "required": ["new_password"],
                    }}},
                },
                "responses": {"200": {"description": "Password updated"}},
            },
        },
        "/api/auth/users/{id}/deactivate/": {
            "post": {
                "tags": [tag],
                "summary": "Deactivate a user and revoke tokens",
                "security": bearer,
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                ],
                "responses": {"200": {"description": "User deactivated"}},
            },
        },
        "/api/auth/logout/": {
            "post": {
                "tags": [tag],
                "summary": "Revoke current login token",
                "security": bearer,
                "responses": {"200": {"description": "Logged out"}},
            },
        },
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_openapi_spec(api_registry: list[tuple[object, str]], server_url: str | None = None) -> dict:
    """Build a complete OpenAPI 3.0.3 spec from the SmallStack API registry.

    Parameters
    ----------
    api_registry:
        List of ``(crud_config, list_url_name)`` tuples from ``_api_registry``.
    server_url:
        Optional base URL (e.g. ``http://localhost:8005/``).

    Returns
    -------
    dict
        OpenAPI 3.0.3 specification as a JSON-serialisable dict.
    """
    spec: dict = {
        "openapi": "3.0.3",
        "info": {
            "title": "SmallStack API",
            "version": "1.0.0",
            "description": "Auto-generated API documentation for SmallStack.",
        },
    }

    if server_url:
        spec["servers"] = [{"url": server_url.rstrip("/")}]

    # Paths
    paths: dict[str, dict] = {}
    schemas: dict[str, dict] = {}

    for crud_config, list_url_name in api_registry:
        model_name = crud_config.model.__name__
        crud_paths = _build_crud_paths(crud_config, list_url_name)
        paths.update(crud_paths)
        schemas[model_name] = _build_crud_schema(crud_config)

    # Auth paths
    paths.update(_build_auth_paths())

    # Error schema
    schemas["Error"] = _build_error_schema()

    spec["paths"] = paths
    spec["components"] = {
        "schemas": schemas,
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "SmallStack API Token",
            },
        },
    }

    return spec
