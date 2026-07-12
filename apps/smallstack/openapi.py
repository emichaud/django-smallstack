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


# ---------------------------------------------------------------------------
# Operation-object builders — collapse the repeated OpenAPI boilerplate
# (``content → application/json → schema`` wrappers) that otherwise balloons
# the path builders. Purely structural; output is byte-for-byte equivalent.
# ---------------------------------------------------------------------------


def _json_content(schema: dict) -> dict:
    """An OpenAPI ``application/json`` content object wrapping ``schema``."""
    return {"application/json": {"schema": schema}}


def _response(description: str, schema: dict | None = None) -> dict:
    """An OpenAPI response object, with an optional JSON body ``schema``."""
    resp: dict = {"description": description}
    if schema is not None:
        resp["content"] = _json_content(schema)
    return resp


def _request_body(schema: dict, *, required: bool = False) -> dict:
    """An OpenAPI ``requestBody`` wrapping a JSON ``schema``."""
    body: dict = {}
    if required:
        body["required"] = True
    body["content"] = _json_content(schema)
    return body


def _object_schema(properties: dict, *, required: list[str] | None = None) -> dict:
    """A JSON-Schema ``object`` with ``properties`` and optional ``required``."""
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# A path parameter that reappears across every /users/{id}/... auth endpoint.
_ID_PATH_PARAM: dict = {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}


def _build_crud_paths(crud_config, list_url_name: str) -> dict[str, dict]:
    """Generate path objects for a single CRUDView (list + detail)."""
    from django.urls import reverse

    from .api import _get_methods_from_actions
    from .crud import Action

    list_url = reverse(list_url_name)
    detail_url = list_url.rstrip("/") + "/{id}/"
    model_name = crud_config.model.__name__
    ref = f"#/components/schemas/{model_name}"
    ref_schema = {"$ref": ref}
    error_ref = {"$ref": "#/components/schemas/Error"}
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
            {
                "name": "ordering",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Comma-separated fields, prefix with - for descending",
            },
        ]
        search_fields = crud_config._resolve_search_fields()
        if search_fields:
            parameters.append(
                {
                    "name": "q",
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": f"Search {', '.join(search_fields)}",
                },
            )

        # Filter parameters
        filter_fields = crud_config._resolve_filter_fields()
        for field_name in filter_fields:
            parameters.append(
                {
                    "name": field_name,
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": f"Filter by {field_name}",
                },
            )

        # Expand parameter
        expand_fields = getattr(crud_config, "api_expand_fields", [])
        if expand_fields:
            parameters.append(
                {
                    "name": "expand",
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": f"Comma-separated FK fields to expand: {', '.join(expand_fields)}",
                },
            )

        # Export format parameter
        export_formats = getattr(crud_config, "export_formats", [])
        if export_formats:
            parameters.append(
                {
                    "name": "format",
                    "in": "query",
                    "schema": {"type": "string", "enum": list(export_formats)},
                    "description": "Export format (returns file download)",
                },
            )

        # Aggregation parameters
        agg_fields = getattr(crud_config, "api_aggregate_fields", [])
        if agg_fields:
            for agg in ["sum", "avg", "min", "max"]:
                parameters.append(
                    {
                        "name": agg,
                        "in": "query",
                        "schema": {"type": "string"},
                        "description": f"Compute {agg} of a numeric field ({', '.join(agg_fields)})",
                    },
                )
            parameters.append(
                {
                    "name": "count_by",
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": "Group counts by field",
                },
            )
        list_ops["get"] = {
            "tags": [tag],
            "summary": f"List {model_name} records",
            "parameters": parameters,
            "security": [{"bearerAuth": []}],
            "responses": {
                "200": _response("Paginated list", _build_list_response_schema(model_name)),
            },
        }

    if "POST" in methods and Action.CREATE in actions:
        list_ops["post"] = {
            "tags": [tag],
            "summary": f"Create a {model_name}",
            "security": [{"bearerAuth": []}],
            "requestBody": _request_body(ref_schema, required=True),
            "responses": {
                "201": _response("Created", ref_schema),
                "400": _response("Validation error", error_ref),
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
                "200": _response("Detail", ref_schema),
                "404": _response("Not found"),
            },
        }

    if Action.UPDATE in actions:
        detail_ops["put"] = {
            "tags": [tag],
            "summary": f"Update a {model_name}",
            "parameters": detail_params,
            "security": [{"bearerAuth": []}],
            "requestBody": _request_body(ref_schema, required=True),
            "responses": {
                "200": _response("Updated", ref_schema),
                "400": _response("Validation error", error_ref),
            },
        }
        detail_ops["patch"] = {
            "tags": [tag],
            "summary": f"Partially update a {model_name}",
            "parameters": detail_params,
            "security": [{"bearerAuth": []}],
            "requestBody": _request_body(ref_schema, required=True),
            "responses": {
                "200": _response("Updated", ref_schema),
            },
        }

    if Action.DELETE in actions:
        detail_ops["delete"] = {
            "tags": [tag],
            "summary": f"Delete a {model_name}",
            "parameters": detail_params,
            "security": [{"bearerAuth": []}],
            "responses": {"204": _response("Deleted")},
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
    error_ref = {"$ref": "#/components/schemas/Error"}
    auth_user_ref = {"$ref": "#/components/schemas/AuthUser"}
    auth_user_ext_ref = {"$ref": "#/components/schemas/AuthUserExtended"}

    token_response_schema = _object_schema(
        {
            "token": {"type": "string"},
            "user": auth_user_ref,
            "expires_at": {"type": "string", "format": "date-time"},
        }
    )
    message_schema = _object_schema({"message": {"type": "string"}})

    return {
        "/api/auth/token/": {
            "post": {
                "tags": [tag],
                "summary": "Login — exchange credentials for a Bearer token",
                "requestBody": _request_body(
                    _object_schema(
                        {
                            "username": {"type": "string"},
                            "password": {"type": "string"},
                            "expires_hours": {"type": "integer"},
                        },
                        required=["username", "password"],
                    ),
                    required=True,
                ),
                "responses": {
                    "200": _response("Token issued", token_response_schema),
                    "400": _response("Missing fields", error_ref),
                    "401": _response("Invalid credentials", error_ref),
                },
            },
        },
        "/api/auth/token/refresh/": {
            "post": {
                "tags": [tag],
                "summary": "Refresh a login token",
                "security": bearer,
                "requestBody": _request_body(
                    _object_schema({"expires_hours": {"type": "integer"}})
                ),
                "responses": {
                    "200": _response("Token refreshed", token_response_schema),
                },
            },
        },
        "/api/auth/register/": {
            "post": {
                "tags": [tag],
                "summary": "Register a new user",
                "security": bearer,
                "requestBody": _request_body(
                    _object_schema(
                        {
                            "username": {"type": "string"},
                            "password": {"type": "string"},
                            "email": {"type": "string", "format": "email"},
                        },
                        required=["username", "password"],
                    ),
                    required=True,
                ),
                "responses": {
                    "201": _response("User created", token_response_schema),
                    "400": _response("Validation error", error_ref),
                },
            },
        },
        "/api/auth/me/": {
            "get": {
                "tags": [tag],
                "summary": "Get current user profile",
                "security": bearer,
                "responses": {
                    "200": _response("User profile", auth_user_ref),
                },
            },
        },
        "/api/auth/password/": {
            "post": {
                "tags": [tag],
                "summary": "Change own password",
                "security": bearer,
                "requestBody": _request_body(
                    _object_schema(
                        {
                            "current_password": {"type": "string"},
                            "new_password": {"type": "string"},
                        },
                        required=["current_password", "new_password"],
                    ),
                    required=True,
                ),
                "responses": {
                    "200": _response("Password updated", message_schema),
                    "400": _response("Validation error", error_ref),
                },
            },
        },
        "/api/auth/password-requirements/": {
            "get": {
                "tags": [tag],
                "summary": "Get password validation rules",
                "responses": {
                    "200": _response(
                        "Password requirements",
                        _object_schema(
                            {
                                "requirements": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            }
                        ),
                    ),
                },
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
                    {
                        "name": "ordering",
                        "in": "query",
                        "schema": {"type": "string"},
                        "description": "Order by: username, email, pk",
                    },
                ],
                "responses": {
                    "200": _response(
                        "Paginated user list",
                        _object_schema(
                            {
                                "count": {"type": "integer"},
                                "page": {"type": "integer"},
                                "total_pages": {"type": "integer"},
                                "next": {"type": "string", "nullable": True},
                                "previous": {"type": "string", "nullable": True},
                                "results": {
                                    "type": "array",
                                    "items": auth_user_ext_ref,
                                },
                            }
                        ),
                    ),
                },
            },
        },
        "/api/auth/users/{id}/": {
            "get": {
                "tags": [tag],
                "summary": "Get user detail",
                "security": bearer,
                "parameters": [_ID_PATH_PARAM],
                "responses": {
                    "200": _response("User detail", auth_user_ext_ref),
                    "404": _response("Not found"),
                },
            },
            "patch": {
                "tags": [tag],
                "summary": "Update a user",
                "security": bearer,
                "parameters": [_ID_PATH_PARAM],
                "requestBody": _request_body(
                    _object_schema(
                        {
                            "email": {"type": "string", "format": "email"},
                            "first_name": {"type": "string"},
                            "last_name": {"type": "string"},
                            "is_staff": {"type": "boolean"},
                            "is_active": {"type": "boolean"},
                        }
                    )
                ),
                "responses": {
                    "200": _response("User updated", auth_user_ext_ref),
                    "400": _response("Validation error", error_ref),
                },
            },
        },
        "/api/auth/users/{id}/password/": {
            "post": {
                "tags": [tag],
                "summary": "Set a user's password (admin)",
                "security": bearer,
                "parameters": [_ID_PATH_PARAM],
                "requestBody": _request_body(
                    _object_schema(
                        {"new_password": {"type": "string"}},
                        required=["new_password"],
                    ),
                    required=True,
                ),
                "responses": {
                    "200": _response("Password updated", message_schema),
                    "400": _response("Validation error", error_ref),
                },
            },
        },
        "/api/auth/users/{id}/deactivate/": {
            "post": {
                "tags": [tag],
                "summary": "Deactivate a user and revoke tokens",
                "security": bearer,
                "parameters": [_ID_PATH_PARAM],
                "responses": {
                    "200": _response("User deactivated", message_schema),
                },
            },
        },
        "/api/auth/logout/": {
            "post": {
                "tags": [tag],
                "summary": "Revoke current login token",
                "security": bearer,
                "responses": {
                    "200": _response("Logged out", message_schema),
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _build_custom_paths(custom_registry: list[dict]) -> dict[str, dict]:
    """Turn ``register_api_path`` entries into OpenAPI path objects.

    The base path is resolved by reversing each entry's ``url_name`` (so the
    host's mount prefix is picked up), then ``subpath`` is appended.
    """
    from django.urls import NoReverseMatch, reverse

    paths: dict[str, dict] = {}
    for entry in custom_registry:
        try:
            base = reverse(entry["url_name"])
        except NoReverseMatch:
            continue
        subpath = entry.get("subpath", "")
        path = base.rstrip("/") + "/" + subpath.lstrip("/") if subpath else base

        operations: dict[str, dict] = {}
        for method in entry["methods"]:
            op: dict = {
                "tags": entry["tags"],
                "summary": entry["summary"],
                "parameters": entry["parameters"],
                "responses": entry["responses"],
                "security": [{"bearerAuth": []}],
            }
            if entry.get("request_body") and method not in ("GET", "DELETE"):
                op["requestBody"] = entry["request_body"]
            operations[method.lower()] = op
        paths.setdefault(path, {}).update(operations)
    return paths


def build_openapi_spec(
    api_registry: list[tuple[object, str]],
    server_url: str | None = None,
    custom_paths: list[dict] | None = None,
) -> dict:
    """Build a complete OpenAPI 3.0.3 spec from the SmallStack API registry.

    Parameters
    ----------
    api_registry:
        List of ``(crud_config, list_url_name)`` tuples from ``_api_registry``.
    server_url:
        Optional base URL (e.g. ``http://localhost:8005/``).
    custom_paths:
        Optional list of ``register_api_path`` entries (``_custom_api_registry``)
        for hand-rolled function views that opt into the schema.

    Returns
    -------
    dict
        OpenAPI 3.0.3 specification as a JSON-serialisable dict.
    """
    from django.conf import settings

    spec: dict = {
        "openapi": "3.0.3",
        "info": {
            "title": "SmallStack API",
            # Derived from the package version (settings.SMALLSTACK_VERSION) so the
            # published contract never drifts from the release — same reconciliation
            # applied to MCP_SERVER_VERSION.
            "version": getattr(settings, "SMALLSTACK_VERSION", "0.0.0"),
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

    # Custom (non-CRUDView) paths registered via register_api_path
    if custom_paths:
        paths.update(_build_custom_paths(custom_paths))

    # Auth schemas
    schemas["AuthUser"] = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "username": {"type": "string"},
            "email": {"type": "string", "format": "email"},
            "is_staff": {"type": "boolean"},
        },
    }
    schemas["AuthUserExtended"] = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "username": {"type": "string"},
            "email": {"type": "string", "format": "email"},
            "is_staff": {"type": "boolean"},
            "first_name": {"type": "string"},
            "last_name": {"type": "string"},
            "is_active": {"type": "boolean"},
            "date_joined": {"type": "string", "format": "date-time", "nullable": True},
        },
    }

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
