"""Keep one-time credentials out of anything that records a URL.

A password-reset link (``/accounts/reset/<uidb64>/<token>/``), an invite link
(``/accounts/invite/<uidb64>/<token>/``) and the newsletter's confirm and
unsubscribe links (``/blog/subscribe/confirm/<token>/``,
``/blog/unsubscribe/<token>/``) carry the credential in the path itself. Any
log of request paths that a staff account can read is then a list of live keys:
the Activity request log showed full reset links to every staff account, and a
staff account with no permissions replayed one and took over a superuser (G3-1).

Three helpers, all pure Python (``apps.smallstack.logging`` imports this
during ``dictConfig``, before the app registry exists):

``redact_path(path, route="")``
    For a recorded request path. With the matched URL pattern (``route``), every
    path segment captured by a sensitive URL parameter (``token``) is replaced;
    the known shapes above are then redacted by pattern too, which covers a
    path that matched nothing and rows recorded before the route existed.
``redact_text(text)``
    For free text that may contain such a path or a URL with a credential in
    its query string (``?token=…``, ``code=…``): log messages and tracebacks.

The route shape is kept (``/accounts/reset/MQ/***/``) so the log still says
which page was hit; only the credential goes. ``set-password`` is Django's
literal placeholder for the reset step after the redirect, not a secret.
"""

from __future__ import annotations

import re

REDACTED = "***"

#: URL parameters whose captured value is a credential. Every route in the
#: codebase that carries a one-time token names it ``token``.
SENSITIVE_URL_KWARGS = frozenset({"token"})

#: Query-string parameters whose value is a credential (API tokens on feed
#: URLs, OAuth codes and secrets).
SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "code",
        "code_verifier",
        "client_secret",
        "api_key",
        "apikey",
        "key_secret",
        "password",
        "secret",
        "signature",
        "sig",
    }
)

#: Not a credential: Django's PasswordResetConfirmView redirects the token URL
#: to ``…/<uidb64>/set-password/`` and keeps the token in the session.
_PLACEHOLDERS = frozenset({"set-password", REDACTED})

# A path segment: anything up to the next "/", whitespace, quote, "?" or "#".
_SEG = r"[^/\s?#'\"<>]+"

#: The token-bearing shapes, matched anywhere in a string so a mounted prefix
#: (``/smallstack/``, ``/tools/``) doesn't matter.
_TOKEN_PATHS = (
    re.compile(rf"(/accounts/(?:reset|invite)/{_SEG}/)({_SEG})"),
    re.compile(rf"(/blog/subscribe/confirm/)({_SEG})"),
    re.compile(rf"(/blog/unsubscribe/)({_SEG})"),
)

_QUERY = re.compile(
    r"([?&;](?:" + "|".join(sorted(re.escape(p) for p in SENSITIVE_QUERY_PARAMS)) + r")=)([^&#\s'\"<>]+)",
    re.IGNORECASE,
)

_ROUTE_PARAM = re.compile(r"^<(?:\w+:)?(\w+)>$")


def _sub_token(match: re.Match[str]) -> str:
    value = match.group(2)
    if value in _PLACEHOLDERS:
        return match.group(0)
    return match.group(1) + REDACTED


def _by_route(path: str, route: str) -> str:
    """Replace the segments a sensitive ``<…token>`` route parameter captured."""
    if not route or "<" not in route:
        return path
    route_parts = route.strip("/").split("/")
    if not any(
        (m := _ROUTE_PARAM.match(part)) and m.group(1) in SENSITIVE_URL_KWARGS for part in route_parts
    ):
        return path
    leading = path.startswith("/")
    trailing = path.endswith("/")
    path_parts = path.strip("/").split("/")
    if len(path_parts) != len(route_parts):
        return path  # a <path:…> converter or a regex route: leave it to the patterns
    out = []
    for seg, part in zip(path_parts, route_parts, strict=True):
        m = _ROUTE_PARAM.match(part)
        if m and m.group(1) in SENSITIVE_URL_KWARGS and seg not in _PLACEHOLDERS:
            out.append(REDACTED)
        else:
            out.append(seg)
    joined = "/".join(out)
    return ("/" if leading else "") + joined + ("/" if trailing and joined else "")


def redact_path(path: str, route: str = "") -> str:
    """``path`` with any one-time credential replaced by ``***``.

    ``route`` is the matched URL pattern as ``RequestLog.route`` stores it
    (``/smallstack/accounts/reset/<uidb64>/<token>/``), when known.
    """
    if not path:
        return path
    try:
        path = _by_route(path, route)
        for pattern in _TOKEN_PATHS:
            path = pattern.sub(_sub_token, path)
        return _QUERY.sub(lambda m: m.group(1) + REDACTED, path)
    except Exception:  # pragma: no cover - never let redaction break a caller
        return path


def redact_text(text: str) -> str:
    """Free text with token paths and credential query parameters redacted."""
    if not text or not isinstance(text, str):
        return text
    try:
        for pattern in _TOKEN_PATHS:
            text = pattern.sub(_sub_token, text)
        return _QUERY.sub(lambda m: m.group(1) + REDACTED, text)
    except Exception:  # pragma: no cover - defensive
        return text


def contains_secret(text: str) -> bool:
    """True when :func:`redact_text` would change ``text``."""
    return bool(text) and redact_text(text) != text
