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


def test_staff_level_token_held_by_non_staff_user_is_refused(user_a):
    """A staff-*level* token whose *user* is not staff (flag cleared after
    minting, or minted for them by another staffer) must not reach staff tools
    — REST refuses the same caller. The tool is neither listed nor callable.
    (Audit 2026-09-13, C1.)"""
    from apps.smallstack.models import APIToken

    calls = []

    @tool(
        "staff_write_probe",
        "Staff-only write probe",
        input_schema={"type": "object", "properties": {}},
        write=True,
        requires_access="staff",
    )
    async def staff_write_probe(args):
        calls.append(args)
        return {"ok": True}

    _, raw = APIToken.create_token(user=user_a, name="stale-staff", access_level="staff")
    auth = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}

    listed = _post(Client(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, **auth)
    assert "staff_write_probe" not in [t["name"] for t in listed.json()["result"]["tools"]]

    called = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "staff_write_probe", "arguments": {}}},
        **auth,
    )
    assert called.status_code == 403
    assert calls == [], "handler ran for a non-staff user"


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


# --- F-20: a refusal must not look like a success ----------------------------


def test_tool_returning_an_error_key_sets_is_error(staff_token):
    """`isError` is the documented MCP way to say "this call failed".

    Hard-coding it to False made a refusal — "you are not eligible", "already
    decided" — indistinguishable from success at the protocol level, so a model
    checking isError would read "approval refused" as "approved". For a gate,
    that is the one failure you cannot have.
    """
    @tool("refuses", "Always refuses.", {"type": "object", "properties": {}})
    def refuses(args):
        return {"error": {"code": "not_eligible", "message": "nope"}}

    @tool("succeeds", "Always succeeds.", {"type": "object", "properties": {}})
    def succeeds(args):
        return {"ok": True}

    _token, raw = staff_token

    def call(name):
        resp = _post(
            Client(),
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": {}}},
            HTTP_AUTHORIZATION=f"Bearer {raw}",
        )
        assert resp.status_code == 200
        return resp.json()["result"]

    assert call("refuses")["isError"] is True
    # Negative control: a normal result is still isError=False.
    assert call("succeeds")["isError"] is False


# --- F-14: a login token inherits its user's tier ---------------------------


def test_login_token_can_call_a_staff_tier_tool(staff_user):
    """A token minted by POST /api/auth/token/ carries access_level="" — not a
    tier choice, but "whatever this user is". Ranking it as readonly refused a
    genuine staff user's own login token, with a message that blamed their role.
    """
    from apps.smallstack.models import APIToken

    @tool("staff_only", "Staff tool.", {"type": "object", "properties": {}},
          requires_access="staff")
    def staff_only(args):
        return {"ok": True}

    _t, raw = APIToken.create_token(
        user=staff_user, name="Login token", token_type="login", access_level=""
    )
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "staff_only", "arguments": {}}},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["result"]["isError"] is False


def test_login_token_of_a_non_staff_user_is_still_refused(user_a):
    """The derived tier can never exceed the account: `auth` < `staff`."""
    from apps.smallstack.models import APIToken

    @tool("staff_only2", "Staff tool.", {"type": "object", "properties": {}},
          requires_access="staff")
    def staff_only2(args):
        return {"ok": True}

    _t, raw = APIToken.create_token(
        user=user_a, name="Login token", token_type="login", access_level=""
    )
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "staff_only2", "arguments": {}}},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert resp.status_code == 403


# --- F-10: MCP refuses a deactivated account's token ------------------------


def test_deactivated_account_cannot_use_mcp(staff_token):
    token, raw = staff_token
    ok = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert ok.status_code == 200  # negative control

    token.user.is_active = False
    token.user.save()
    resp = _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert resp.status_code == 401


# --- F-26: the tier ladder has to be a ladder --------------------------------
#
# It ranked {"readonly": 0, "staff": 1, "auth": 2}, so `auth` outranked `staff`.
# mcp-custom-tools.md documents requires_access="auth" as "gate this to
# merely-authenticated callers", and with that ordering NO login token could ever
# call such a tool — a staff user's was refused access_required:auth, a non-staff
# user's staff_required. An "any authenticated user" tier that demands staff, on
# which staff are strictly less capable than non-staff.


def _tool(name, requires_access=None, write=False):
    from apps.mcp.server import ToolDef

    return ToolDef(
        name=name,
        description=name,
        input_schema={"type": "object", "properties": {}},
        write=write,
        requires_access=requires_access,
    )


@pytest.mark.django_db
def test_the_auth_tier_admits_any_authenticated_login_token(django_user_model):
    """Both halves of the documented meaning of requires_access="auth"."""
    from apps.mcp.auth import check_tool_access
    from apps.smallstack.models import APIToken

    staffer = django_user_model.objects.create_user("f26-staff", password="p", is_staff=True)
    plain = django_user_model.objects.create_user("f26-plain", password="p")
    auth_tool = _tool("auth_tier", requires_access="auth")

    for user in (staffer, plain):
        token, _ = APIToken.create_token(
            user=user, name=f"login-{user.username}", access_level=""
        )
        assert token.access_level == "", "a login token must carry no tier"
        assert check_tool_access(token, auth_tool) is None, (
            f"{user.username}'s login token was refused an auth-tier tool"
        )


@pytest.mark.django_db
def test_the_staff_tier_still_demands_the_live_staff_flag(django_user_model):
    """Negative control — fixing the ordering must not widen the staff gate."""
    from apps.mcp.auth import check_tool_access
    from apps.smallstack.models import APIToken

    plain = django_user_model.objects.create_user("f26-plain2", password="p")
    staff_tool = _tool("staff_tier", requires_access="staff")

    login_token, _ = APIToken.create_token(user=plain, name="login2", access_level="")
    assert check_tool_access(login_token, staff_tool) is not None

    # …and a token MINTED at "staff" for a non-staff user is still refused: the
    # live flag beats the mint-time label.
    mislabelled, _ = APIToken.create_token(user=plain, name="mint-staff", access_level="staff")
    assert check_tool_access(mislabelled, staff_tool) == "staff_required"


@pytest.mark.django_db
def test_the_ladder_orders_readonly_below_auth_below_staff(django_user_model):
    """The full truth table, so an ordering change cannot pass unnoticed."""
    from apps.mcp.auth import check_tool_access
    from apps.smallstack.models import APIToken

    staffer = django_user_model.objects.create_user("f26-s3", password="p", is_staff=True)
    tools = {
        "readonly": _tool("t_ro", requires_access="readonly"),
        "auth": _tool("t_auth", requires_access="auth"),
        "staff": _tool("t_staff", requires_access="staff"),
    }
    expected = {
        "readonly": {"readonly": True, "auth": False, "staff": False},
        "auth": {"readonly": True, "auth": True, "staff": False},
        "staff": {"readonly": True, "auth": True, "staff": True},
    }
    for level, wanted in expected.items():
        token, _ = APIToken.create_token(
            user=staffer, name=f"tier-{level}", access_level=level
        )
        actual = {tier: check_tool_access(token, tool) is None for tier, tool in tools.items()}
        assert actual == wanted, f"token level {level!r}: expected {wanted}, got {actual}"


@pytest.mark.django_db
def test_a_readonly_token_still_cannot_write_whatever_its_derived_level(django_user_model):
    """The write gate reads the RAW level on purpose — an explicit 'readonly'
    promise must not be upgraded by derivation."""
    from apps.mcp.auth import check_tool_access
    from apps.smallstack.models import APIToken

    staffer = django_user_model.objects.create_user("f26-s4", password="p", is_staff=True)
    token, _ = APIToken.create_token(user=staffer, name="ro", access_level="readonly")
    assert check_tool_access(token, _tool("w", write=True)) == "readonly_blocked"
