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


@pytest.mark.parametrize("body", [[1, 2, 3], "a string", 5, True])
def test_non_object_body_returns_invalid_request(body):
    """Audit L2: a valid-JSON but non-object body (e.g. a batch array) must
    return -32600 Invalid Request, not an uncaught 500."""
    resp = _post(Client(), body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == -32600


def test_non_dict_params_returns_invalid_request():
    """Non-object params must also be rejected with -32600, not crash."""
    resp = _post(Client(), {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1, 2]})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == -32600


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


def test_tools_list_filters_out_staff_only_tools_for_readonly_caller(readonly_token):
    """Per-token tools/list filtering (v0.11.10) — a readonly token must
    not see staff-required tools in the list. Hides the tool *name* from
    casual enumeration and removes LLM-surface noise for end-user tokens."""

    @tool(
        "staff_only_probe",
        "Staff-only probe tool",
        input_schema={"type": "object", "properties": {}},
        requires_access="staff",
    )
    async def staff_only_probe(args):
        return {"ok": True}

    _, raw = readonly_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    payload = resp.json()
    names = [t["name"] for t in payload["result"]["tools"]]
    # Staff-required tool MUST be hidden from readonly caller.
    assert "staff_only_probe" not in names


def test_tools_list_shows_staff_only_tools_to_staff_token(staff_token):
    """Regression guard: staff tokens still see staff-only tools."""

    @tool(
        "staff_only_probe_2",
        "Staff-only probe tool",
        input_schema={"type": "object", "properties": {}},
        requires_access="staff",
    )
    async def staff_only_probe_2(args):
        return {"ok": True}

    _, raw = staff_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = [t["name"] for t in resp.json()["result"]["tools"]]
    assert "staff_only_probe_2" in names


def test_tools_list_filters_out_write_tools_for_readonly_caller(readonly_token):
    """A readonly token can't call write tools — they're filtered out of
    tools/list to match the call-time enforcement."""

    @tool(
        "write_probe",
        "Write probe tool",
        input_schema={"type": "object", "properties": {}},
        write=True,
    )
    async def write_probe(args):
        return {"ok": True}

    _, raw = readonly_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = [t["name"] for t in resp.json()["result"]["tools"]]
    assert "write_probe" not in names


def test_tools_list_respects_visible_to_callback(readonly_token):
    """When a tool declares ``visible_to=(user) -> bool``, tools/list MUST
    include it when the callback returns True.

    This + the next test pin the gate that closes the round-2 audit §3.3
    carry-over: search_users used to appear in alice's tools/list as
    "visible-but-non-functional" because check_tool_access only saw the
    flat ``requires_access="readonly"`` and not the underlying view's
    ``search_access=STAFF`` tier. visible_to lifts the per-view gate to
    the listing layer."""

    @tool(
        "always_visible_probe",
        "Tool whose visible_to always returns True",
        input_schema={"type": "object", "properties": {}},
        visible_to=lambda u: True,
    )
    async def always_visible_probe(args):
        return {"ok": True}

    _, raw = readonly_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = [t["name"] for t in resp.json()["result"]["tools"]]
    assert "always_visible_probe" in names


def test_tools_list_hides_tool_when_visible_to_returns_false(readonly_token):
    """The negative case: visible_to returns False → the tool is omitted."""

    @tool(
        "never_visible_probe",
        "Tool whose visible_to always returns False",
        input_schema={"type": "object", "properties": {}},
        visible_to=lambda u: False,
    )
    async def never_visible_probe(args):
        return {"ok": True}

    _, raw = readonly_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = [t["name"] for t in resp.json()["result"]["tools"]]
    assert "never_visible_probe" not in names


def test_tools_list_visible_to_callback_fails_safe(readonly_token):
    """Round-4 hardening: a raising visible_to callback hides the tool
    from the list rather than exposing it — fail-safe under bugs."""

    @tool(
        "buggy_visibility",
        "Tool with a buggy visibility check",
        input_schema={"type": "object", "properties": {}},
        visible_to=lambda u: 1 / 0,   # will raise ZeroDivisionError
    )
    async def buggy_visibility(args):
        return {"ok": True}

    _, raw = readonly_token
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = [t["name"] for t in resp.json()["result"]["tools"]]
    assert "buggy_visibility" not in names


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
