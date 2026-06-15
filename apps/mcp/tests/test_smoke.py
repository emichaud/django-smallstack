"""mcp_smoke: end-to-end mint → call → revoke against a real HTTP endpoint.

Tests mock urllib so we don't need a live server, but the token-mint and
revoke paths are real (against the test database) so we can verify the
cleanup contract.
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()


def _fake_urlopen(payload: dict, status: int = 200):
    """Build a context-manager-shaped mock matching urllib.request.urlopen."""
    body = json.dumps(payload).encode("utf-8")
    mock = MagicMock()
    mock.__enter__.return_value.read.return_value = body
    mock.__enter__.return_value.status = status
    return mock


@pytest.fixture
def smoke_user():
    return User.objects.create_user(username="smoker", password="x", is_staff=True)


def test_smoke_happy_path_mints_calls_and_revokes(smoke_user, capsys):
    """tools/list returns a tool, tools/call succeeds, token is revoked."""
    list_resp = {
        "jsonrpc": "2.0", "id": 1,
        "result": {"tools": [{"name": "list_widgets", "description": "x"}]},
    }
    call_resp = {
        "jsonrpc": "2.0", "id": 1,
        "result": {"content": [{"type": "text", "text": "{}"}], "isError": False},
    }
    with patch("urllib.request.urlopen", side_effect=[_fake_urlopen(list_resp), _fake_urlopen(call_resp)]):
        call_command("mcp_smoke", "--url", "http://x.example/mcp")

    out = capsys.readouterr().out
    assert "[✓] tools/list" in out
    assert "[✓] tools/call list_widgets" in out
    assert "Result: PASS" in out

    # The mint+revoke contract: a smoke token was created AND revoked.
    smokes = APIToken.objects.filter(user=smoke_user, name__startswith="mcp-smoke-")
    assert smokes.exists()
    assert not smokes.filter(is_active=True).exists()


def test_smoke_skips_call_when_no_list_tool_registered(smoke_user, capsys):
    """If tools/list returns nothing useful, the call step SKIPs instead of
    failing — useful when the upstream has 0 tools registered."""
    empty_resp = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(empty_resp)):
        call_command("mcp_smoke")

    out = capsys.readouterr().out
    assert "[✓] tools/list" in out
    assert "SKIP" not in out  # not printed in human mode, only in JSON


def test_smoke_connection_refused_exits_2(smoke_user):
    """When the server isn't running, exit with EXIT_CONNECT=2."""

    def fail(*args, **kwargs):
        raise urllib.error.URLError("[Errno 61] Connection refused")

    with patch("urllib.request.urlopen", side_effect=fail):
        with pytest.raises(SystemExit) as excinfo:
            call_command("mcp_smoke", "--url", "http://localhost:39999/mcp")
        assert excinfo.value.code == 2

    # Token still got minted and revoked even on connection failure.
    smokes = APIToken.objects.filter(user=smoke_user, name__startswith="mcp-smoke-")
    assert smokes.exists()
    assert not smokes.filter(is_active=True).exists()


def test_smoke_rpc_error_exits_4(smoke_user):
    """A JSON-RPC error response (not a connection issue) exits EXIT_RPC=4."""
    err_resp = {
        "jsonrpc": "2.0", "id": 1,
        "error": {"code": -32601, "message": "Method not found"},
    }
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(err_resp)):
        with pytest.raises(SystemExit) as excinfo:
            call_command("mcp_smoke")
        assert excinfo.value.code == 4


def test_smoke_json_output_is_parseable(smoke_user):
    """--json emits a single structured object with steps + token_revoked."""
    list_resp = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    out = io.StringIO()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(list_resp)):
        call_command("mcp_smoke", "--json", stdout=out)

    data = json.loads(out.getvalue())
    assert data["status"] == "PASS"
    assert data["token_revoked"] is True
    names = [s["name"] for s in data["steps"]]
    assert "tools/list" in names


def test_smoke_no_users_errors_out():
    """Empty user table → CommandError with actionable hint."""
    User.objects.all().delete()
    with pytest.raises(CommandError, match="No users exist"):
        call_command("mcp_smoke")


def test_smoke_prefers_staff_user(smoke_user):
    """When multiple users exist, the smoke test prefers staff for the token."""
    User.objects.create_user(username="non_staff", password="x", is_staff=False)
    list_resp = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    out = io.StringIO()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(list_resp)):
        call_command("mcp_smoke", "--json", stdout=out)

    data = json.loads(out.getvalue())
    assert data["user"] == "smoker"  # the is_staff one


def test_smoke_explicit_user_override(smoke_user):
    """--user <username> overrides the default staff-first selection."""
    target = User.objects.create_user(username="explicit_target", password="x")
    list_resp = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    out = io.StringIO()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(list_resp)):
        call_command("mcp_smoke", "--user", "explicit_target", "--json", stdout=out)

    data = json.loads(out.getvalue())
    assert data["user"] == "explicit_target"
    assert APIToken.objects.filter(user=target, name__startswith="mcp-smoke-").exists()
