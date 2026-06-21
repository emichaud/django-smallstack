"""OAuth + discovery endpoints."""

import base64
import hashlib
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.mcp.models import OAuthAuthorizationCode
from apps.smallstack.models import APIToken

User = get_user_model()
pytestmark = pytest.mark.django_db


def _chal(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_as_metadata_shape():
    resp = Client().get("/.well-known/oauth-authorization-server", HTTP_HOST="localhost")
    body = resp.json()
    assert body["issuer"].endswith("localhost")
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["grant_types_supported"] == ["authorization_code"]


def test_prm_resource_has_no_trailing_slash():
    resp = Client().get("/.well-known/oauth-protected-resource", HTTP_HOST="localhost")
    body = resp.json()
    assert body["resource"].endswith("/mcp")
    assert not body["resource"].endswith("/mcp/")


def test_dcr_returns_mcp_prefixed_client_id():
    resp = Client().post(
        "/mcp/oauth/register",
        data=json.dumps({"client_name": "Test", "redirect_uris": ["https://x.example/cb"]}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 201
    assert resp.json()["client_id"].startswith("mcp_")


def test_dcr_rejects_bad_redirect_uris():
    resp = Client().post(
        "/mcp/oauth/register",
        data=json.dumps({"redirect_uris": "not-a-list"}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 400


def test_authorize_get_requires_login():
    resp = Client().get(
        "/mcp/oauth/authorize"
        "?client_id=mcp_abc&redirect_uri=https://x.example/cb"
        "&code_challenge=abc&code_challenge_method=S256&state=xyz",
        HTTP_HOST="localhost",
    )
    # Redirect to LOGIN_URL
    assert resp.status_code in (301, 302)


def test_authorize_get_with_login_renders_csp_with_redirect_origin():
    user = User.objects.create_user(username="u", password="p")
    client = Client()
    client.force_login(user)
    resp = client.get(
        "/mcp/oauth/authorize"
        "?client_id=mcp_x&redirect_uri=https://claude.ai/cb"
        "&code_challenge=abc&code_challenge_method=S256&state=s1",
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 200
    csp = resp.get("Content-Security-Policy", "")
    assert "form-action" in csp
    assert "https://claude.ai" in csp


def test_authorize_bad_params_return_400():
    user = User.objects.create_user(username="u2", password="p")
    client = Client()
    client.force_login(user)
    resp = client.get("/mcp/oauth/authorize", HTTP_HOST="localhost")
    assert resp.status_code == 400


def test_authorize_post_deny_redirects_with_error():
    user = User.objects.create_user(username="u3", password="p")
    client = Client()
    client.force_login(user)
    resp = client.post(
        "/mcp/oauth/authorize",
        {
            "client_id": "mcp_x",
            "redirect_uri": "https://claude.ai/cb",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            "state": "s1",
            "scope": "read",
            "decision": "deny",
        },
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 302
    assert "error=access_denied" in resp["Location"]


def test_authorize_get_rejects_unsafe_redirect_uri():
    """Audit H1: javascript:/data:/non-loopback-http redirect_uri is rejected
    at the consent page (open-redirect / code-interception guard)."""
    user = User.objects.create_user(username="u_rr1", password="p")
    client = Client()
    client.force_login(user)
    for bad in ("javascript:alert(1)", "http://evil.example/cb", "data:text/html,x"):
        resp = client.get(
            "/mcp/oauth/authorize"
            f"?client_id=mcp_x&redirect_uri={bad}&code_challenge=abc&code_challenge_method=S256",
            HTTP_HOST="localhost",
        )
        assert resp.status_code == 400, bad
        assert resp.json()["error"] == "invalid_request"


def test_authorize_get_allows_https_and_loopback_http():
    """https (any host) and http on a loopback host are valid redirect targets."""
    user = User.objects.create_user(username="u_rr2", password="p")
    client = Client()
    client.force_login(user)
    for ok in ("https://claude.ai/cb", "http://127.0.0.1:8765/callback", "http://localhost:9000/cb"):
        resp = client.get(
            "/mcp/oauth/authorize"
            f"?client_id=mcp_x&redirect_uri={ok}&code_challenge=abc&code_challenge_method=S256",
            HTTP_HOST="localhost",
        )
        assert resp.status_code == 200, ok
        # destination host is surfaced on the consent page (anti-phishing)
        assert b"Authorization code will be sent to" in resp.content


def test_authorize_post_rejects_unsafe_redirect_uri_without_minting():
    """A poisoned redirect_uri at POST must 400 and NOT mint a token or 302."""
    user = User.objects.create_user(username="u_rr3", password="p")
    client = Client()
    client.force_login(user)
    resp = client.post(
        "/mcp/oauth/authorize",
        {
            "client_id": "mcp_x",
            "redirect_uri": "http://evil.example/cb",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            "state": "s1",
            "scope": "read",
            "decision": "allow",
        },
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 400
    assert APIToken.objects.filter(user=user).count() == 0


def test_token_rejects_redirect_uri_mismatch():
    """Audit H1: if the client sends redirect_uri at /token it must match the
    one bound to the code at /authorize."""
    user = User.objects.create_user(username="u_rr4", password="p")
    client = Client()
    client.force_login(user)
    verifier = "v" * 64
    chal = _chal(verifier)
    auth = client.post(
        "/mcp/oauth/authorize",
        {
            "client_id": "mcp_x", "redirect_uri": "https://claude.ai/cb",
            "code_challenge": chal, "code_challenge_method": "S256",
            "state": "s1", "scope": "read", "decision": "allow",
        },
        HTTP_HOST="localhost",
    )
    code = auth["Location"].split("code=")[1].split("&")[0]
    resp = client.post(
        "/mcp/oauth/token",
        {
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "redirect_uri": "https://claude.ai/EVIL",  # != the bound URI
        },
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


def test_full_token_exchange_yields_bearer():
    user = User.objects.create_user(username="u4", password="p")
    client = Client()
    client.force_login(user)
    verifier = "v" * 64
    chal = _chal(verifier)

    auth_resp = client.post(
        "/mcp/oauth/authorize",
        {
            "client_id": "mcp_x",
            "redirect_uri": "https://claude.ai/cb",
            "code_challenge": chal,
            "code_challenge_method": "S256",
            "state": "s1",
            "scope": "read",
            "decision": "allow",
        },
        HTTP_HOST="localhost",
    )
    assert auth_resp.status_code == 302
    code = auth_resp["Location"].split("code=")[1].split("&")[0]

    tok_resp = client.post(
        "/mcp/oauth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": "mcp_x",
        },
        HTTP_HOST="localhost",
    )
    assert tok_resp.status_code == 200
    body = tok_resp.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]


def test_code_single_use():
    user = User.objects.create_user(username="u5", password="p")
    client = Client()
    client.force_login(user)
    verifier = "v" * 64
    chal = _chal(verifier)

    auth = client.post(
        "/mcp/oauth/authorize",
        {
            "client_id": "mcp_x", "redirect_uri": "https://claude.ai/cb",
            "code_challenge": chal, "code_challenge_method": "S256",
            "state": "s1", "scope": "read", "decision": "allow",
        },
        HTTP_HOST="localhost",
    )
    code = auth["Location"].split("code=")[1].split("&")[0]
    first = client.post(
        "/mcp/oauth/token",
        {"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
        HTTP_HOST="localhost",
    )
    assert first.status_code == 200
    second = client.post(
        "/mcp/oauth/token",
        {"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
        HTTP_HOST="localhost",
    )
    assert second.status_code == 400


def test_wrong_verifier_rejected():
    user = User.objects.create_user(username="u6", password="p")
    client = Client()
    client.force_login(user)
    verifier = "v" * 64
    chal = _chal(verifier)
    auth = client.post(
        "/mcp/oauth/authorize",
        {
            "client_id": "mcp_x", "redirect_uri": "https://claude.ai/cb",
            "code_challenge": chal, "code_challenge_method": "S256",
            "state": "s1", "scope": "read", "decision": "allow",
        },
        HTTP_HOST="localhost",
    )
    code = auth["Location"].split("code=")[1].split("&")[0]
    resp = client.post(
        "/mcp/oauth/token",
        {"grant_type": "authorization_code", "code": code, "code_verifier": "wrong" * 13},
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 400


def test_expired_code_rejected():
    user = User.objects.create_user(username="u7", password="p")
    client = Client()
    client.force_login(user)
    verifier = "v" * 64
    chal = _chal(verifier)
    auth = client.post(
        "/mcp/oauth/authorize",
        {
            "client_id": "mcp_x", "redirect_uri": "https://claude.ai/cb",
            "code_challenge": chal, "code_challenge_method": "S256",
            "state": "s1", "scope": "read", "decision": "allow",
        },
        HTTP_HOST="localhost",
    )
    code = auth["Location"].split("code=")[1].split("&")[0]

    row = OAuthAuthorizationCode.objects.get(code=code)
    row.created_at = timezone.now() - timezone.timedelta(hours=1)
    row.save(update_fields=["created_at"])

    resp = client.post(
        "/mcp/oauth/token",
        {"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 400


def test_revoke_soft_deletes_apitoken():
    user = User.objects.create_user(username="u8", password="p")
    token, raw = APIToken.create_token(user=user, name="t", access_level="readonly")
    resp = Client().post(
        "/mcp/oauth/revoke",
        {"token": raw},
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 200
    token.refresh_from_db()
    assert token.is_active is False
    assert token.revoked_at is not None
