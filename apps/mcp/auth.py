"""MCP bearer-only auth wrapper around smallstack's APIToken authentication.

The REST API at apps/smallstack/api.py allows session-cookie auth as a
fallback; MCP rejects that — every /mcp request MUST present a Bearer
token. This also lets the WWW-Authenticate 401 path stay consistent for
Claude.ai's discovery flow (RFC 9728).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from django.http import HttpRequest

from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.models import APIToken

from .server import ToolDef

logger = logging.getLogger("smallstack.mcp.auth")


def authenticate(request: HttpRequest) -> tuple[Optional[Any], Optional[APIToken], Optional[str]]:
    """Authenticate an /mcp request via Bearer token only.

    Returns (user, token, error_reason). On success error_reason is None;
    on failure user and token are None. The view layer maps the reason
    onto a JSON-RPC error + HTTP 401 with WWW-Authenticate.
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None, None, "missing_bearer"

    raw_key = auth_header[7:].strip()
    if not raw_key:
        return None, None, "empty_bearer"

    user, token = APIToken.authenticate(raw_key)
    if user is None:
        logger.warning("MCP AUTH failed reason=invalid_token prefix=%s", raw_key[:8])
        return None, None, "invalid_token"

    # Stash on request so downstream code (logging, tools) can read it.
    request.user = user
    request._api_token = token  # type: ignore[attr-defined]
    request._api_token_auth = True  # type: ignore[attr-defined]
    return user, token, None


def check_tool_access(
    token: APIToken,
    tool_def: ToolDef,
    mixins: list[type] | None = None,
) -> Optional[str]:
    """Decide whether `token` is allowed to call `tool_def`.

    Returns an error string on rejection, or None on allow. The view layer
    converts the string into a JSON-RPC -32600 with HTTP 403.

    Rules (most-restrictive wins):
    - tool_def.requires_access overrides everything; tokens below that level
      are rejected. Order: readonly < staff < auth.
    - tool_def.write=True ⇒ readonly tokens rejected.
    - StaffRequiredMixin on the view ⇒ token.user must be staff.
    """
    level_rank = {"readonly": 0, "staff": 1, "auth": 2}
    token_level = level_rank.get(token.access_level, 0)

    if tool_def.requires_access:
        needed = level_rank.get(tool_def.requires_access, 0)
        if token_level < needed:
            return f"access_required:{tool_def.requires_access}"

    if tool_def.write and token.access_level == "readonly":
        return "readonly_blocked"

    if mixins:
        for mixin in mixins:
            if issubclass(mixin, StaffRequiredMixin) or getattr(mixin, "__name__", "") == "StaffRequiredMixin":
                if not getattr(token.user, "is_staff", False):
                    return "staff_required"

    return None
