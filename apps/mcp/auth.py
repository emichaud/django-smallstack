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
        # Round-2 audit §4.6 — distinguish "real token, no longer valid"
        # from "bogus token." The reason string is what the view layer
        # maps into a JSON-RPC error + WWW-Authenticate code; rejected
        # but recognisable tokens get a more actionable reason than
        # the generic "invalid_token".
        if token is not None:
            rejected = token.rejection_reason()
            if rejected == APIToken.REJECT_REVOKED:
                reason = "token_revoked"
            elif rejected == APIToken.REJECT_EXPIRED:
                reason = "token_expired"
            elif rejected == APIToken.REJECT_USER_INACTIVE:
                # Offboarding invalidates the credential, not just web login.
                reason = "account_deactivated"
            else:
                reason = "token_inactive"
        else:
            reason = "invalid_token"
        logger.warning("MCP AUTH failed reason=%s prefix=%s", reason, raw_key[:8])
        return None, None, reason

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
      are rejected. The ladder is ``readonly < auth < staff``.
    - requires_access="staff" ⇒ token.user must ALSO be staff.
      The token's level is a label chosen at mint time; the user's staff flag
      is the live fact. REST gates on the user (``request.user.is_staff``), so
      MCP must too — otherwise a staff-level token held by a non-staff user
      (flag cleared after minting, or minted for them by another staffer)
      keeps staff power over MCP that REST refuses. (Audit 2026-09-13, C1.)
    - tool_def.write=True ⇒ readonly tokens rejected.
    - StaffRequiredMixin on the view ⇒ token.user must be staff.
    """
    # The ladder used to rank {"readonly": 0, "staff": 1, "auth": 2}, so `auth`
    # OUTRANKED `staff`. apps/smallstack/docs/mcp-custom-tools.md documents
    # requires_access="auth" as the way to gate a tool to merely-authenticated
    # callers, and with that ordering NO login token could ever call one: a staff
    # user's token was refused `access_required:auth` (rank 1 < 2) and a non-staff
    # user's was refused `staff_required` — an "any authenticated user" tier that
    # demanded staff, on which staff were strictly LESS capable than non-staff.
    # Latent (nothing in the tree declares "auth" yet, though a dataset author's
    # `mcp_access="auth"` reaches it), so the first tool to use the documented
    # value got nonsense. (F-26.)
    level_rank = {"readonly": 0, "auth": 1, "staff": 2}
    # A login token (POST /api/auth/token/) carries access_level="" — it is not a
    # tier choice, it means "whatever this user is". Ranking it 0 (readonly) made
    # a genuine staff user's login token unable to call staff-tier tools, with an
    # error naming the user's role rather than the token's tier. Derive the level
    # from the account instead; the user's live staff flag is still re-checked
    # below, so this cannot grant more than the account has. (F-14.)
    effective_level = token.access_level or (
        "staff" if getattr(token.user, "is_staff", False) else "auth"
    )
    token_level = level_rank.get(effective_level, 0)

    if tool_def.requires_access:
        needed = level_rank.get(tool_def.requires_access, 0)
        if token_level < needed:
            return f"access_required:{tool_def.requires_access}"
        # Only the `staff` tier implies the staff flag. Re-checking it for any
        # tier "at or above staff" was the same inversion in a second place:
        # `auth` ranked above `staff`, so an auth-tier tool silently demanded
        # staff as well. (F-26.)
        if tool_def.requires_access == "staff" and not getattr(token.user, "is_staff", False):
            return "staff_required"

    # The WRITE gate reads the RAW level on purpose: "readonly" is an explicit
    # promise made at mint time and a derived level must never silently upgrade
    # past it. (The read gate above uses the derived level — two different notions
    # of a token's level in one function, which is deliberate and now stated.)
    if tool_def.write and token.access_level == "readonly":
        return "readonly_blocked"

    if mixins:
        for mixin in mixins:
            if issubclass(mixin, StaffRequiredMixin) or getattr(mixin, "__name__", "") == "StaffRequiredMixin":
                if not getattr(token.user, "is_staff", False):
                    return "staff_required"

    return None
