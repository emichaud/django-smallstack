"""The four extension seams — named-registry hooks the foundation is built on.

SmallStack ships a *solid* webhook engine and four documented seams so a Zapier / n8n /
Azure / AWS integration is a small plug-in, not a core fork. Each seam is a named
registry, exactly like ``@webhook_handler`` / ``mcp_tools.py``: decorate a function with a
name, drop it in an app's ``webhook_*.py``, and it's discovered at ``ready()``. Every seam
ships a **built-in default** (registered here) so with no selection the engine behaves
exactly as it did before this change.

Selected per endpoint / per receiver by name:

===================  ==================================  =========================
Seam                 Model field                         Default
===================  ==================================  =========================
``@webhook_transform``  ``WebhookEndpoint.transform``    ``"smallstack"``  (current envelope)
``@webhook_auth``       ``WebhookEndpoint.auth_scheme``  ``"hmac"``        (X-SmallStack-Signature)
``@webhook_verifier``   ``WebhookReceiver.verifier``     ``"hmac"``        (raw-body HMAC)
``@webhook_challenge``  ``WebhookReceiver.challenge``    ``""``            (none)
===================  ==================================  =========================

An unknown selector name falls back to the default with a logged warning — a typo must
not silently drop a delivery.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

    from .models import WebhookEndpoint, WebhookReceiver

logger = logging.getLogger("smallstack.webhooks")


# ---------------------------------------------------------------------------
# The verifier's headers argument
# ---------------------------------------------------------------------------


class CaseInsensitiveDict(dict):
    """A mutable ``dict`` whose key lookups ignore ASCII case.

    This is the argument the inbound view hands a verifier. It has to satisfy two
    contracts at once:

    * **Case-insensitive**, because HTTP header names are. A plain
      ``dict(request.headers)`` froze Django's canonicalisation, so a receiver
      configured with the documented ``X-SmallStack-Signature`` spelling silently
      401'd while an undocumented ``X-Smallstack-Signature`` worked. (F-06.)
    * **A real, mutable dict**, because the seam was documented as
      ``dict[str, str]`` from the start. The first fix reached for
      ``django.utils.datastructures.CaseInsensitiveMapping``, which is immutable —
      so a third-party verifier doing the ordinary
      ``headers.pop("X-Smallstack-Signature", "")`` raised ``AttributeError``
      inside the verifier, was swallowed by the view's ``except Exception``, and
      became a bare ``401 invalid signature`` with nothing in the log. Failing
      closed is right; failing closed *silently* on a correct credential, after a
      contract change nobody announced, is not. (F-37.)

    Keys keep the casing they were inserted with, so ``.items()`` still shows the
    wire spelling. Header maps are a few dozen entries, so the case-folded index
    is rebuilt lazily rather than maintained on every mutation.
    """

    def _fold(self) -> dict[str, Any]:
        return {str(k).lower(): k for k in super().keys()}

    def _actual_key(self, key: Any) -> Any:
        if super().__contains__(key):
            return key
        if isinstance(key, str):
            return self._fold().get(key.lower())
        return None

    def __getitem__(self, key: Any) -> Any:
        actual = self._actual_key(key)
        if actual is None:
            raise KeyError(key)
        return super().__getitem__(actual)

    def __contains__(self, key: Any) -> bool:
        return self._actual_key(key) is not None

    def __delitem__(self, key: Any) -> None:
        actual = self._actual_key(key)
        if actual is None:
            raise KeyError(key)
        super().__delitem__(actual)

    def get(self, key: Any, default: Any = None) -> Any:
        actual = self._actual_key(key)
        return default if actual is None else super().__getitem__(actual)

    def pop(self, key: Any, *default: Any) -> Any:
        actual = self._actual_key(key)
        if actual is None:
            if default:
                return default[0]
            raise KeyError(key)
        return super().pop(actual)

    def setdefault(self, key: Any, default: Any = None) -> Any:
        actual = self._actual_key(key)
        if actual is None:
            super().__setitem__(key, default)
            return default
        return super().__getitem__(actual)

    def __setitem__(self, key: Any, value: Any) -> None:
        actual = self._actual_key(key)
        super().__setitem__(actual if actual is not None else key, value)

    # __init__ and update() must route through __setitem__ by hand: CPython's
    # dict.__init__/dict.update write straight to the C storage, so a
    # differently-cased key would SHADOW the existing one instead of replacing
    # it (two entries, and the original spelling reading back stale). That is
    # F-06's failure class one method over, and silent — see F-48.
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.update(*args, **kwargs)

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if len(args) > 1:
            raise TypeError(f"update expected at most 1 argument, got {len(args)}")
        if args:
            other = args[0]
            items = other.items() if isinstance(other, Mapping) else other
            for key, value in items:
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def copy(self) -> "CaseInsensitiveDict":
        return CaseInsensitiveDict(self)


# ---------------------------------------------------------------------------
# Value objects passed to / returned from the seams
# ---------------------------------------------------------------------------


@dataclass
class Transformed:
    """Result of an outbound transform: the wire body + its content type."""

    body: bytes
    content_type: str = "application/json"


@dataclass
class OutgoingRequest:
    """The request an auth seam signs — mutable view the seam reads to compute a
    credential (it returns headers/params via :class:`AuthResult`, it does not mutate
    this in place)."""

    url: str
    body: bytes
    headers: dict[str, str]
    event_type: str


@dataclass
class AuthResult:
    """Credentials an auth seam adds to the outgoing request."""

    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)


# A transform takes the event envelope dict and returns a Transformed.
Transform = Callable[[dict[str, Any]], "Transformed"]
# An auth seam takes the OutgoingRequest + endpoint and returns credentials.
Auth = Callable[["OutgoingRequest", "WebhookEndpoint"], "AuthResult"]
# A verifier takes raw body + headers + receiver and returns bool (constant-time
# inside). ``headers`` is a :class:`CaseInsensitiveDict` — a real ``dict``
# subclass, so everything a verifier written against the original ``dict[str, str]``
# contract does still works (``pop``, ``setdefault``, ``update``, ``del``), and
# lookups additionally ignore header-name casing so a verifier can use whatever
# spelling it was written against (F-06).
Verifier = Callable[[bytes, "MutableMapping[str, str]", "WebhookReceiver"], bool]
# A challenge takes the request and returns a response to short-circuit, or None.
Challenge = Callable[["HttpRequest", "WebhookReceiver"], "HttpResponse | None"]


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

_TRANSFORMS: dict[str, Transform] = {}
_AUTHS: dict[str, Auth] = {}
_VERIFIERS: dict[str, Verifier] = {}
_CHALLENGES: dict[str, Challenge] = {}


def _register(registry: dict[str, Any], kind: str, name: str) -> Callable[[Any], Any]:
    def decorator(fn: Any) -> Any:
        if name in registry:
            logger.warning("webhook %s %r already registered — keeping the first", kind, name)
            return fn
        registry[name] = fn
        logger.debug("webhooks: registered %s %r", kind, name)
        return fn

    return decorator


def webhook_transform(name: str) -> Callable[[Transform], Transform]:
    """Register an outbound payload transform under ``name`` (``endpoint.transform``)."""
    return _register(_TRANSFORMS, "transform", name)


def webhook_auth(name: str) -> Callable[[Auth], Auth]:
    """Register an outbound per-request auth scheme under ``name`` (``endpoint.auth_scheme``)."""
    return _register(_AUTHS, "auth", name)


def webhook_verifier(name: str) -> Callable[[Verifier], Verifier]:
    """Register an inbound signature verifier under ``name`` (``receiver.verifier``)."""
    return _register(_VERIFIERS, "verifier", name)


def webhook_challenge(name: str) -> Callable[[Challenge], Challenge]:
    """Register an inbound challenge/handshake under ``name`` (``receiver.challenge``)."""
    return _register(_CHALLENGES, "challenge", name)


# ---------------------------------------------------------------------------
# Lookups — resolve a selector to a callable, falling back to the default
# ---------------------------------------------------------------------------


def get_transform(name: str | None) -> Transform:
    return _resolve(_TRANSFORMS, name or DEFAULT_TRANSFORM, DEFAULT_TRANSFORM, "transform")


def get_auth(name: str | None) -> Auth:
    return _resolve(_AUTHS, name or DEFAULT_AUTH, DEFAULT_AUTH, "auth")


def get_verifier(name: str | None) -> Verifier:
    return _resolve(_VERIFIERS, name or DEFAULT_VERIFIER, DEFAULT_VERIFIER, "verifier")


def get_challenge(name: str | None) -> Challenge | None:
    """Challenge is opt-in: blank ⇒ no handshake (returns None)."""
    if not name:
        return None
    fn = _CHALLENGES.get(name)
    if fn is None:
        logger.warning("webhooks: unknown challenge %r — no handshake will run", name)
    return fn


def _resolve(registry: dict[str, Any], name: str, default: str, kind: str) -> Any:
    fn = registry.get(name)
    if fn is not None:
        return fn
    if name != default:
        logger.warning("webhooks: unknown %s %r — falling back to %r", kind, name, default)
    return registry[default]


def registered() -> dict[str, list[str]]:
    """All registered seam names by kind (for the doctor / --explain)."""
    return {
        "transforms": sorted(_TRANSFORMS),
        "auths": sorted(_AUTHS),
        "verifiers": sorted(_VERIFIERS),
        "challenges": sorted(_CHALLENGES),
    }


def clear_hooks_for_tests() -> None:
    """Test helper — wipe custom hooks and re-register the built-in defaults."""
    _TRANSFORMS.clear()
    _AUTHS.clear()
    _VERIFIERS.clear()
    _CHALLENGES.clear()
    register_default_hooks()


# ---------------------------------------------------------------------------
# Built-in defaults — reproduce today's behavior exactly
# ---------------------------------------------------------------------------

DEFAULT_TRANSFORM = "smallstack"
DEFAULT_AUTH = "hmac"
DEFAULT_VERIFIER = "hmac"


def _default_transform(event: dict[str, Any]) -> Transformed:
    """The current SmallStack envelope, JSON-encoded (identity transform)."""
    import json

    return Transformed(
        body=json.dumps(event, default=str).encode(),
        content_type="application/json",
    )


def _default_auth(req: OutgoingRequest, endpoint: WebhookEndpoint) -> AuthResult:
    """The current HMAC signature header (``X-SmallStack-Signature: sha256=…``)."""
    from . import services

    return AuthResult(
        headers={services.SIGNATURE_HEADER: services.signature_header_value(endpoint.secret, req.body)}
    )


def _default_verifier(body: bytes, headers: Mapping[str, str], receiver: WebhookReceiver) -> bool:
    """The current raw-body HMAC check against ``signature_header`` (GitHub-compatible).

    HTTP header names are case-insensitive, so the lookup is too. The view used
    to hand us ``dict(request.headers)``, which collapses Django's
    case-insensitive ``HttpHeaders`` into a plain dict keyed by Django's own
    canonicalisation — so configuring ``X-SmallStack-Signature`` (the spelling
    the constant and three ``help_text`` strings tell you to use) failed while an
    undocumented ``X-Smallstack-Signature`` worked. (F-06.)
    """
    from . import services

    wanted = (receiver.signature_header or "").lower()
    provided = ""
    for name, value in headers.items():
        if name.lower() == wanted:
            provided = value
            break
    return services.verify(receiver.secret, body, provided)


def register_default_hooks() -> None:
    """Register the built-in defaults if absent. Idempotent and quiet, so safe to call at
    import time and again from ``ready()`` / the test suite."""
    if DEFAULT_TRANSFORM not in _TRANSFORMS:
        webhook_transform(DEFAULT_TRANSFORM)(_default_transform)
    if DEFAULT_AUTH not in _AUTHS:
        webhook_auth(DEFAULT_AUTH)(_default_auth)
    if DEFAULT_VERIFIER not in _VERIFIERS:
        webhook_verifier(DEFAULT_VERIFIER)(_default_verifier)


register_default_hooks()
