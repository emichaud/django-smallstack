"""OpenAPI spec validity: the generated spec must be a valid OpenAPI 3.0.3
document. Catches regressions where someone adds a field that breaks
Swagger UI rendering — Swagger silently renders garbage instead of erroring,
so the only safe place to catch malformed specs is a CI check.

Uses openapi-spec-validator (the canonical Python tool). Tests both the
runtime view (`/api/schema/openapi.json`) and the underlying builder
function so regressions surface whether the bug is in the serializer or
the builder.
"""

import pytest
from django.test import Client
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

from apps.smallstack.api import _api_registry
from apps.smallstack.openapi import build_openapi_spec

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Builder-level checks (no HTTP, no DB rows needed)
# ---------------------------------------------------------------------------


def test_build_openapi_spec_returns_valid_openapi_3_0_3():
    """The generated spec passes the openapi-spec-validator gauntlet."""
    spec = build_openapi_spec(_api_registry, server_url="http://localhost:8005/")
    try:
        validate(spec)
    except OpenAPIValidationError as exc:
        pytest.fail(f"OpenAPI spec is invalid: {exc}")


def test_spec_declares_openapi_3_0_3_version():
    spec = build_openapi_spec(_api_registry)
    assert spec["openapi"].startswith("3.0")


def test_spec_has_required_top_level_keys():
    """OpenAPI 3.x requires openapi, info, and paths (paths can be empty)."""
    spec = build_openapi_spec(_api_registry)
    assert "openapi" in spec
    assert "info" in spec
    assert "paths" in spec
    # info requires title + version
    assert spec["info"].get("title")
    assert spec["info"].get("version")


def test_each_path_has_at_least_one_http_method():
    """Empty path objects are valid OpenAPI but useless and almost always
    a builder bug. Surface them in tests."""
    spec = build_openapi_spec(_api_registry)
    valid_methods = {
        "get", "put", "post", "delete", "options", "head", "patch", "trace",
        "parameters", "summary", "description", "servers",
    }
    for path, ops in spec["paths"].items():
        method_keys = [k for k in ops.keys() if k in valid_methods - {
            "parameters", "summary", "description", "servers",
        }]
        assert method_keys, f"path {path!r} has no HTTP method operations"


def test_server_url_included_when_passed():
    spec = build_openapi_spec(_api_registry, server_url="https://prod.example/")
    assert spec["servers"][0]["url"] == "https://prod.example"


# ---------------------------------------------------------------------------
# Endpoint-level check — the HTTP view must serve a valid spec
# ---------------------------------------------------------------------------


def test_openapi_json_endpoint_serves_valid_spec():
    """End-to-end: GET /api/schema/openapi.json returns a spec that
    passes validation. Catches serializer regressions in addition to
    builder bugs."""
    resp = Client().get("/api/schema/openapi.json", HTTP_HOST="localhost")
    assert resp.status_code == 200
    spec = resp.json()
    try:
        validate(spec)
    except OpenAPIValidationError as exc:
        pytest.fail(f"/api/schema/openapi.json returned an invalid spec: {exc}")


def test_openapi_endpoint_advertises_smallstack_title():
    """Sanity: the served spec is the SmallStack one, not an empty default."""
    resp = Client().get("/api/schema/openapi.json", HTTP_HOST="localhost")
    spec = resp.json()
    assert "SmallStack" in spec["info"]["title"]
