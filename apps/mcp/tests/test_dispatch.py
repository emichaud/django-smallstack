"""HTTP/JSON-RPC dispatch behaviour for /mcp."""

import json

import pytest
from django.test import Client

from apps.mcp.server import clear_registry_for_tests, tool

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _wipe():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _post(client, body, **extra):
    return client.post(
        "/mcp",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST="localhost",
        **extra,
    )


def test_get_banner_returns_json():
    resp = Client().get("/mcp", HTTP_HOST="localhost")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["transport"] == "http+json-rpc"
    assert "supported_protocol_versions" in payload


def test_missing_bearer_returns_401_with_wwwauth():
    resp = _post(Client(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers
    assert "Bearer" in resp.headers["WWW-Authenticate"]
    assert "resource_metadata" in resp.headers["WWW-Authenticate"]


def test_invalid_bearer_returns_401(readonly_token):
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION="Bearer not-a-real-key",
    )
    assert resp.status_code == 401


def test_initialize_echoes_supported_version(readonly_token):
    _, raw = readonly_token
    resp = _post(
        Client(),
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["protocolVersion"] == "2025-03-26"


def test_initialize_falls_back_on_unsupported_version():
    resp = _post(
        Client(),
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        },
    )
    assert resp.status_code == 200
    # Fallback is the first in MCP_SUPPORTED_PROTOCOL_VERSIONS
    assert resp.json()["result"]["protocolVersion"] == "2025-06-18"


def test_notifications_return_202_empty_body():
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert resp.status_code == 202
    assert resp.content == b""


def test_ping_returns_empty_result():
    resp = _post(Client(), {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp.status_code == 200
    assert resp.json()["result"] == {}


def test_resources_list_returns_empty_success():
    resp = _post(Client(), {"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    assert resp.status_code == 200
    assert resp.json()["result"] == {"resources": []}


def test_prompts_list_returns_empty_success():
    resp = _post(Client(), {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})
    assert resp.status_code == 200
    assert resp.json()["result"] == {"prompts": []}


def test_unknown_method_returns_method_not_found(readonly_token):
    _, raw = readonly_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "no/such/thing"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    body = resp.json()
    assert body["error"]["code"] == -32601


def test_tools_list_returns_registered_tools(readonly_token):
    @tool("ping_alt", "Alt ping")
    async def ping_alt(args):
        return {"ok": True}

    _, raw = readonly_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    payload = resp.json()
    names = [t["name"] for t in payload["result"]["tools"]]
    assert "ping_alt" in names


def test_unknown_tool_call_returns_method_not_found(readonly_token):
    _, raw = readonly_token
    resp = _post(
        Client(),
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        },
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert resp.json()["error"]["code"] == -32601


def test_no_trailing_slash_works_for_post():
    """Most critical compat check: /mcp without trailing slash must NOT 301."""
    resp = Client().post(
        "/mcp",
        data="{}",
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert resp.status_code in (200, 400, 401)
    assert resp.status_code != 301
