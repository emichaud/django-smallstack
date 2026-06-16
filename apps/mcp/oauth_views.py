"""OAuth 2.0 endpoints for MCP: discovery, DCR, authorize, token, revoke.

These are the Claude.ai-compatible surface. Several behaviors look surprising
in isolation but each one is required by a real client we've already shipped
to:

- PRM `resource` MUST NOT have a trailing slash — Claude.ai literally sends
  `resource=https://host/mcp` in its authorize call and compares verbatim.
- DCR is stateless; we don't persist the client. PKCE binds everything that
  matters at /authorize anyway.
- The consent page needs `form-action <redirect_uri_origin>` in its CSP or
  the browser silently blocks the post-Authorize redirect to Claude.ai.
"""

from __future__ import annotations

import json
import logging
import secrets
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.smallstack.models import APIToken

from .models import OAuthAuthorizationCode
from .oauth import absolute_url, issuer_url, verify_pkce

logger = logging.getLogger("smallstack.mcp.oauth")


# ---------------------------------------------------------------------------
# Discovery: AS metadata + PRM metadata
# ---------------------------------------------------------------------------


def authorization_server_metadata(request: HttpRequest) -> JsonResponse:
    """RFC 8414 — Authorization Server Metadata."""
    issuer = issuer_url(request)
    body = {
        "issuer": issuer,
        "authorization_endpoint": absolute_url(request, "/mcp/oauth/authorize"),
        "token_endpoint": absolute_url(request, "/mcp/oauth/token"),
        "registration_endpoint": absolute_url(request, "/mcp/oauth/register"),
        "revocation_endpoint": absolute_url(request, "/mcp/oauth/revoke"),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["read", "write"],
    }
    return JsonResponse(body)


def protected_resource_metadata(request: HttpRequest) -> JsonResponse:
    """RFC 9728 — Protected Resource Metadata.

    `resource` MUST NOT have a trailing slash. Claude.ai compares this
    verbatim to its own `resource=` param in /authorize.
    """
    body = {
        "resource": absolute_url(request, "/mcp"),  # NO trailing slash
        "authorization_servers": [issuer_url(request)],
        "scopes_supported": ["read", "write"],
        "bearer_methods_supported": ["header"],
    }
    return JsonResponse(body)


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def register(request: HttpRequest) -> JsonResponse:
    """Stateless DCR — we trust PKCE to bind everything at /authorize."""
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_client_metadata"}, status=400)

    client_name = (payload.get("client_name") or "anonymous").strip()[:200]
    redirect_uris = payload.get("redirect_uris") or []
    if not isinstance(redirect_uris, list):
        return JsonResponse({"error": "invalid_redirect_uri"}, status=400)

    client_id = f"mcp_{secrets.token_urlsafe(12)}"
    logger.info(
        "OAUTH REGISTER client_id=%s redirect_uris=%s client_name=%s",
        client_id, redirect_uris, client_name,
    )
    return JsonResponse(
        {
            "client_id": client_id,
            "client_id_issued_at": int(timezone.now().timestamp()),
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# /authorize — consent page (GET) + decision (POST)
# ---------------------------------------------------------------------------


def _add_csp_for_redirect(resp: HttpResponse, redirect_uri: str) -> HttpResponse:
    """Allow the post-Authorize form to navigate to `redirect_uri` origin."""
    parsed = urlparse(redirect_uri)
    if not parsed.scheme or not parsed.netloc:
        return resp
    origin = f"{parsed.scheme}://{parsed.netloc}"
    # django-csp middleware sets the header from settings — override per-response.
    resp["Content-Security-Policy"] = (
        f"default-src 'self'; "
        f"script-src 'self' 'unsafe-inline'; "
        f"style-src 'self' 'unsafe-inline' https:; "
        f"img-src 'self' data: https:; "
        f"form-action 'self' {origin}; "
        f"frame-ancestors 'none'"
    )
    return resp


@method_decorator(csrf_exempt, name="dispatch")
class AuthorizeView(View):
    """OAuth authorize endpoint. login_required via decorator on get/post."""

    @staticmethod
    def _tokens_url() -> str:
        """Resolve where the consent page sends users for token management.

        Prefers the self-service tokenmgr surface (any authenticated user
        can manage their own tokens). Falls back to the staff-only
        Explorer view if tokenmgr isn't installed — so downstream projects
        that don't install apps.tokenmgr still get a valid link.
        """
        try:
            from django.urls import NoReverseMatch, reverse

            return reverse("tokenmgr:tokens-list")
        except (ImportError, NoReverseMatch):
            return "/explorer/auth/apitoken/"

    @method_decorator(login_required)
    def get(self, request: HttpRequest) -> HttpResponse:
        params = request.GET
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "S256")
        state = params.get("state", "")
        scope = params.get("scope", "read")

        if not client_id or not redirect_uri or not code_challenge:
            return JsonResponse(
                {"error": "invalid_request", "error_description": "missing required params"},
                status=400,
            )
        if code_challenge_method != "S256":
            return JsonResponse(
                {"error": "invalid_request", "error_description": "S256 required"},
                status=400,
            )

        ctx = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": state,
            "scope": scope,
            "scope_human": _scope_to_prose(scope),
            "user": request.user,
            "base_template": getattr(settings, "MCP_BASE_TEMPLATE", "website/base.html"),
            # Self-service token mgmt — works for any authenticated user.
            # Falls back to Explorer (staff-only) if tokenmgr isn't installed.
            "tokens_url": self._tokens_url(),
        }
        resp = render(request, "mcp/authorize.html", ctx)
        return _add_csp_for_redirect(resp, redirect_uri)

    @method_decorator(login_required)
    def post(self, request: HttpRequest) -> HttpResponse:
        post = request.POST
        client_id = post.get("client_id", "")
        redirect_uri = post.get("redirect_uri", "")
        code_challenge = post.get("code_challenge", "")
        state = post.get("state", "")
        scope = post.get("scope", "read")
        decision = post.get("decision", "deny")

        if decision != "allow":
            qs = urlencode({"error": "access_denied", "state": state})
            sep = "&" if "?" in redirect_uri else "?"
            logger.info(
                "OAUTH AUTHORIZE denied user_pk=%s client_id=%s",
                getattr(request.user, "pk", None), client_id,
            )
            return redirect(f"{redirect_uri}{sep}{qs}")

        # Mint APIToken (access_level depends on requested scope)
        prefix = getattr(settings, "MCP_TOKEN_NAME_PREFIX", "MCP")
        access_level = "staff" if "write" in scope.split() else "readonly"
        token, raw_key = APIToken.create_token(
            user=request.user,
            name=f"{prefix} — {client_id}",
            description=f"Auto-minted via OAuth (scope={scope})",
            token_type="manual",
            access_level=access_level,
        )

        code = secrets.token_urlsafe(32)
        OAuthAuthorizationCode.objects.create(
            code=code,
            user=request.user,
            api_token=token,
            raw_key=raw_key,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            scope=scope,
            client_id=client_id,
        )

        parsed = urlparse(redirect_uri)
        host = parsed.netloc
        logger.info(
            "OAUTH AUTHORIZE allowed user_pk=%s client_id=%s token_pk=%s redirect_uri=%s",
            request.user.pk, client_id, token.pk, host,
        )

        qs = urlencode({"code": code, "state": state})
        sep = "&" if "?" in redirect_uri else "?"
        return redirect(f"{redirect_uri}{sep}{qs}")


def _scope_to_prose(scope: str) -> list[str]:
    scopes = [s for s in (scope or "").split() if s]
    mapping = {
        "read": "Read — list and view your data",
        "write": "Write — create, edit, and delete records on your behalf",
    }
    return [mapping.get(s, s) for s in scopes] or ["Read — list and view your data"]


# ---------------------------------------------------------------------------
# /token — code exchange
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def token(request: HttpRequest) -> JsonResponse:
    grant_type = request.POST.get("grant_type", "")
    if grant_type != "authorization_code":
        return JsonResponse({"error": "unsupported_grant_type"}, status=400)

    code = request.POST.get("code", "")
    code_verifier = request.POST.get("code_verifier", "")
    client_id = request.POST.get("client_id", "")

    try:
        row = OAuthAuthorizationCode.objects.select_related("api_token", "user").get(code=code)
    except OAuthAuthorizationCode.DoesNotExist:
        logger.warning("OAUTH TOKEN reject reason=unknown_code client_id=%s", client_id)
        return JsonResponse({"error": "invalid_grant", "error_description": "Unknown code"}, status=400)

    if row.used_at is not None:
        logger.warning("OAUTH TOKEN reject reason=code_reused client_id=%s", client_id)
        return JsonResponse(
            {"error": "invalid_grant", "error_description": "Code already used"}, status=400
        )

    ttl = int(getattr(settings, "MCP_OAUTH_CODE_TTL_SECONDS", 600))
    age = (timezone.now() - row.created_at).total_seconds()
    if age > ttl:
        logger.warning("OAUTH TOKEN reject reason=code_expired client_id=%s", client_id)
        return JsonResponse(
            {"error": "invalid_grant", "error_description": "Code expired"}, status=400
        )

    if not verify_pkce(code_verifier, row.code_challenge, "S256"):
        logger.warning("OAUTH TOKEN reject reason=pkce_mismatch client_id=%s", client_id)
        return JsonResponse(
            {"error": "invalid_grant", "error_description": "PKCE verification failed"}, status=400
        )

    raw_key = row.raw_key
    if not raw_key:
        return JsonResponse(
            {"error": "invalid_grant", "error_description": "Key already revealed"}, status=400
        )

    # One-shot: mark used, wipe the raw key.
    row.used_at = timezone.now()
    row.raw_key = ""
    row.save(update_fields=["used_at", "raw_key"])

    logger.info(
        "OAUTH TOKEN issued user_pk=%s token_pk=%s scope=%s",
        row.user.pk, row.api_token.pk, row.scope,
    )
    return JsonResponse(
        {
            "access_token": raw_key,
            "token_type": "Bearer",
            "scope": row.scope or "read",
        }
    )


# ---------------------------------------------------------------------------
# /revoke — RFC 7009
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def revoke(request: HttpRequest) -> HttpResponse:
    raw_key = request.POST.get("token", "")
    if raw_key:
        user, tok = APIToken.authenticate(raw_key)
        if tok is not None:
            tok.revoke()
            logger.info("OAUTH REVOKE token_pk=%s user_pk=%s", tok.pk, getattr(user, "pk", None))
    # RFC 7009: respond 200 even on unknown tokens to avoid token enumeration.
    return HttpResponse(status=200)
