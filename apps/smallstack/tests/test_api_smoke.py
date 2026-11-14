"""api_smoke: end-to-end mint → GET /api/schema/ → sample call → revoke.

Mocks urllib so the tests don't need a live server. The token-mint and
revoke paths run against the real test DB so the cleanup contract is
verified.
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
    body = json.dumps(payload).encode("utf-8")
    mock = MagicMock()
    mock.__enter__.return_value.read.return_value = body
    mock.__enter__.return_value.status = status
    return mock


@pytest.fixture
def smoke_user():
    return User.objects.create_user(username="api_smoker", password="x", is_staff=True)


def test_api_smoke_happy_path(smoke_user, capsys):
    """/api/schema/ returns an endpoint, sample call succeeds, token revoked."""
    schema_resp = {
        "endpoints": [{"url": "/api/widgets/", "model": "Widget", "methods": ["GET", "POST"]}],
    }
    sample_resp = {"results": [{"id": 1, "name": "test"}], "count": 1}
    with patch(
        "urllib.request.urlopen",
        side_effect=[_fake_urlopen(schema_resp), _fake_urlopen(sample_resp)],
    ):
        call_command("api_smoke", "--base-url", "http://x.example")

    out = capsys.readouterr().out
    assert "[✓] GET /api/schema/" in out
    assert "[✓] GET /api/widgets/" in out
    assert "Result: PASS" in out

    smokes = APIToken.objects.filter(user=smoke_user, name__startswith="api-smoke-")
    assert smokes.exists()
    assert not smokes.filter(is_active=True).exists()


def test_api_smoke_skips_call_when_no_endpoints(smoke_user, capsys):
    """If /api/schema/ has no GET-capable endpoints, the call step SKIPs."""
    empty_resp = {"endpoints": [], "auth": {}}
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(empty_resp)):
        call_command("api_smoke")

    out = capsys.readouterr().out
    assert "[✓] GET /api/schema/" in out
    # Skip is recorded in result, not printed in human mode.


def test_api_smoke_connection_refused_exits_2(smoke_user):
    def fail(*args, **kwargs):
        raise urllib.error.URLError("[Errno 61] Connection refused")

    with patch("urllib.request.urlopen", side_effect=fail):
        with pytest.raises(SystemExit) as excinfo:
            call_command("api_smoke", "--base-url", "http://localhost:39999")
        assert excinfo.value.code == 2

    smokes = APIToken.objects.filter(user=smoke_user, name__startswith="api-smoke-")
    assert smokes.exists()
    assert not smokes.filter(is_active=True).exists()


def test_api_smoke_non_200_exits_4(smoke_user):
    """A 500 from the schema endpoint surfaces as exit 4."""
    err = _fake_urlopen({}, status=500)
    with patch("urllib.request.urlopen", return_value=err):
        with pytest.raises(SystemExit) as excinfo:
            call_command("api_smoke")
        assert excinfo.value.code == 4


def test_api_smoke_json_output_is_parseable(smoke_user):
    schema_resp = {"endpoints": []}
    out = io.StringIO()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(schema_resp)):
        call_command("api_smoke", "--json", stdout=out)

    data = json.loads(out.getvalue())
    assert data["status"] == "PASS"
    assert data["token_revoked"] is True
    assert data["steps"][0]["name"] == "GET /api/schema/"


def test_api_smoke_no_users_errors_out():
    User.objects.all().delete()
    with pytest.raises(CommandError, match="No users exist"):
        call_command("api_smoke")


def test_api_smoke_explicit_endpoint_override(smoke_user, capsys):
    """--endpoint /api/foo/ overrides the schema-driven pick."""
    schema_resp = {"endpoints": [{"url": "/api/widgets/", "methods": ["GET"]}]}
    sample_resp = {"results": []}
    with patch(
        "urllib.request.urlopen",
        side_effect=[_fake_urlopen(schema_resp), _fake_urlopen(sample_resp)],
    ):
        call_command("api_smoke", "--endpoint", "/api/custom/")

    out = capsys.readouterr().out
    assert "[✓] GET /api/custom/" in out
    assert "GET /api/widgets/" not in out


def test_api_smoke_skip_sentinel_skips_call(smoke_user, capsys):
    """--endpoint __skip__ runs only the schema check."""
    schema_resp = {"endpoints": [{"url": "/api/widgets/", "methods": ["GET"]}]}
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(schema_resp)):
        call_command("api_smoke", "--endpoint", "__skip__")

    out = capsys.readouterr().out
    assert "[✓] GET /api/schema/" in out
    assert "GET /api/widgets/" not in out
