"""JSON-RPC dispatcher for `/mcp` and `/mcp/`.

Both paths point at McpHttpView. This is deliberate: Django's APPEND_SLASH
301s POST → GET on /mcp, which breaks JSON-RPC silently. Claude.ai and
several other clients send POST /mcp (no trailing slash); we must accept it.

GET is a friendly JSON banner used by humans (and a couple of clients) to
sanity-check the server is reachable. POST is the JSON-RPC entry point.

The compat list in the spec is enforced here. Each bullet is a real
failure mode observed downstream — please don't "simplify" them away.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .auth import authenticate, check_tool_access
from .oauth import absolute_url
from .server import (
    TOOL_HANDLERS,
    TOOL_REGISTRY,
    ToolContext,
    reset_context,
    set_context,
)

logger = logging.getLogger("smallstack.mcp.views")

# -32xxx error codes per JSON-RPC 2.0
_RPC_PARSE_ERROR = -32700
_RPC_INVALID_REQUEST = -32600
_RPC_METHOD_NOT_FOUND = -32601
_RPC_INTERNAL_ERROR = -32603


def _truncate(value: str | bytes, limit: int = 256) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            value = repr(value)
    if len(value) > limit:
        return value[:limit] + "…"
    return value


def _rpc_error(rpc_id: Any, code: int, message: str, status: int = 200) -> JsonResponse:
    body = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
    return JsonResponse(body, status=status)


def _rpc_result(rpc_id: Any, result: Any, status: int = 200) -> JsonResponse:
    body = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    return JsonResponse(body, status=status)


def _wwwauth_header(request: HttpRequest) -> str:
    """RFC 9728 WWW-Authenticate header pointing the client at PRM metadata."""
    prm_url = absolute_url(request, "/.well-known/oauth-protected-resource")
    return f'Bearer realm="mcp", error="invalid_token", resource_metadata="{prm_url}"'


def _negotiate_protocol_version(client_version: str | None) -> str:
    supported = list(getattr(settings, "MCP_SUPPORTED_PROTOCOL_VERSIONS", ["2025-06-18"]))
    if client_version and client_version in supported:
        return client_version
    return supported[0]


def _server_info() -> dict[str, Any]:
    return {
        "name": getattr(settings, "MCP_SERVER_NAME", "smallstack"),
        "version": getattr(settings, "MCP_SERVER_VERSION", "1.0.0"),
    }


def _capabilities() -> dict[str, Any]:
    return {
        "tools": {"listChanged": False},
        "resources": {"listChanged": False},
        "prompts": {"listChanged": False},
    }


@method_decorator(csrf_exempt, name="dispatch")
class McpHttpView(View):
    """JSON-RPC over HTTP for MCP. Mounted at both /mcp and /mcp/."""

    http_method_names = ["get", "post", "options"]

    def get(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        banner = {
            **_server_info(),
            "transport": "http+json-rpc",
            "supported_protocol_versions": list(
                getattr(settings, "MCP_SUPPORTED_PROTOCOL_VERSIONS", [])
            ),
            "endpoints": {
                "rpc": absolute_url(request, "/mcp"),
                "oauth_authorization_server": absolute_url(
                    request, "/.well-known/oauth-authorization-server"
                ),
                "oauth_protected_resource": absolute_url(
                    request, "/.well-known/oauth-protected-resource"
                ),
            },
            "docs": "/smallstack/help/smallstack/mcp/",
        }
        return JsonResponse(banner)

    def options(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        resp = HttpResponse(status=204)
        resp["Allow"] = "GET, POST, OPTIONS"
        return resp

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        started = time.perf_counter()
        ua = _truncate(request.META.get("HTTP_USER_AGENT", ""))
        accept = _truncate(request.META.get("HTTP_ACCEPT", ""))
        has_auth = bool(request.META.get("HTTP_AUTHORIZATION"))
        body_bytes = request.body or b""
        logger.info(
            "MCP REQ ua=%s accept=%s has_auth=%s body_len=%d",
            ua, accept, has_auth, len(body_bytes),
        )

        # Parse JSON body
        try:
            payload = json.loads(body_bytes or b"{}")
        except (json.JSONDecodeError, ValueError):
            logger.warning("MCP REQ parse_error body=%s", _truncate(body_bytes))
            return _rpc_error(None, _RPC_PARSE_ERROR, "Parse error", status=400)

        method = payload.get("method", "")
        rpc_id = payload.get("id")
        params = payload.get("params") or {}
        logger.info("MCP REQ method=%s id=%s params_keys=%s", method, rpc_id, list(params.keys()))

        response: HttpResponse | None = None
        try:
            # notifications/* — must return 202 + EMPTY body. Don't authenticate
            # them; some clients send notifications/initialized before any auth.
            if method.startswith("notifications/"):
                response = HttpResponse(status=202)
                return response

            # initialize doesn't require auth — it's a handshake. But we still
            # accept Bearer if provided (so the rest of the session has user ctx).
            if method == "initialize":
                client_version = (params.get("protocolVersion") or "").strip() or None
                negotiated = _negotiate_protocol_version(client_version)
                result = {
                    "protocolVersion": negotiated,
                    "serverInfo": _server_info(),
                    "capabilities": _capabilities(),
                }
                response = _rpc_result(rpc_id, result)
                return response

            # ping is auth-free
            if method == "ping":
                response = _rpc_result(rpc_id, {})
                return response

            # Capability probes — return empty success rather than -32601.
            if method == "resources/list":
                response = _rpc_result(rpc_id, {"resources": []})
                return response
            if method == "prompts/list":
                response = _rpc_result(rpc_id, {"prompts": []})
                return response
        finally:
            if response is not None:
                duration = (time.perf_counter() - started) * 1000
                logger.info(
                    "MCP RESP method=%s status=%d duration_ms=%.2f",
                    method, response.status_code, duration,
                )

        # Everything below requires authentication.
        user, token, auth_err = authenticate(request)
        if auth_err is not None:
            resp = _rpc_error(rpc_id, _RPC_INVALID_REQUEST, f"Unauthorized: {auth_err}", status=401)
            resp["WWW-Authenticate"] = _wwwauth_header(request)
            logger.warning("MCP AUTH failed method=%s reason=%s", method, auth_err)
            return resp

        # Bind a per-request ToolContext for any tool callback.
        ctx_token = set_context(ToolContext(user=user, token=token))
        try:
            if method == "tools/list":
                # Round-2 surfaces audit §3.3 follow-up + quality review:
                # filter tools/list so the caller only sees tools their
                # token is actually allowed to invoke. Hides write tools
                # from readonly tokens and staff-required tools from
                # non-staff tokens — the audit's "tool-name leak" concern,
                # plus a real LLM-surface-noise win when an end-user
                # token sees only the four tools it can call instead of
                # all 13 registered ones.
                tools = [
                    {
                        "name": td.name,
                        "description": td.description,
                        "inputSchema": td.input_schema,
                    }
                    for td in TOOL_REGISTRY.values()
                    if check_tool_access(token, td, mixins=None) is None
                ]
                return _rpc_result(rpc_id, {"tools": tools})

            if method == "tools/call":
                name = (params.get("name") or "").strip()
                args = params.get("arguments") or {}
                tdef = TOOL_REGISTRY.get(name)
                if tdef is None:
                    return _rpc_error(rpc_id, _RPC_METHOD_NOT_FOUND, f"Unknown tool: {name}")

                # Tool-level access check
                deny = check_tool_access(token, tdef, mixins=None)
                if deny:
                    logger.warning("MCP TOOL deny tool=%s reason=%s", name, deny)
                    return _rpc_error(rpc_id, _RPC_INVALID_REQUEST, f"Forbidden: {deny}", status=403)

                handler = TOOL_HANDLERS.get(name)
                if handler is None:
                    return _rpc_error(rpc_id, _RPC_INTERNAL_ERROR, f"Tool {name} has no handler")

                tool_started = time.perf_counter()
                try:
                    if inspect.iscoroutinefunction(handler):
                        result_value = asyncio.run(handler(args))
                    else:
                        result_value = handler(args)
                except Exception as exc:
                    logger.exception("MCP TOOL exception tool=%s", name)
                    return _rpc_error(
                        rpc_id,
                        _RPC_INTERNAL_ERROR,
                        f"Tool {name} raised: {exc.__class__.__name__}: {exc}",
                    )
                duration = (time.perf_counter() - tool_started) * 1000
                # Wrap the value in TextContent for MCP clients
                text = json.dumps(result_value, default=str)
                logger.info(
                    "MCP TOOL tool=%s user_pk=%s duration_ms=%.2f result_len=%d",
                    name, getattr(user, "pk", None), duration, len(text),
                )
                return _rpc_result(
                    rpc_id,
                    {"content": [{"type": "text", "text": text}], "isError": False},
                )

            # Unknown method
            return _rpc_error(rpc_id, _RPC_METHOD_NOT_FOUND, f"Method not found: {method}")
        finally:
            reset_context(ctx_token)
            duration = (time.perf_counter() - started) * 1000
            logger.info("MCP RESP method=%s duration_ms=%.2f", method, duration)


# Backstop for any remaining linter complaints about unused asyncio import in
# pure-sync test paths — asyncio.run is the dispatch path for async tools.
_ = asyncio
