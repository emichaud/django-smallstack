"""Who is making the current change, for the audit trail.

Django's signals carry the object that changed but not the request, so the
receivers in :mod:`apps.access.signals` read the acting user from a context
variable bound per request by :class:`ActorMiddleware`. Code that changes
access outside a request (a directory sync, a management command) binds it
with :func:`acting_as`.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from django.http import HttpRequest, HttpResponse

from apps.smallstack.redaction import redact_path

_actor: contextvars.ContextVar[Any] = contextvars.ContextVar("smallstack_access_actor", default=None)
_source: contextvars.ContextVar[str] = contextvars.ContextVar("smallstack_access_source", default="")


def current_actor() -> Any:
    """The user making the current change, or ``None`` outside a request.

    Within a request this is ``request.user`` *as it is now*, not as it was
    when the middleware ran: the REST and MCP layers authenticate a bearer
    token inside the view and replace ``request.user`` then, and a change made
    with that token belongs to its owner."""
    actor = _actor.get()
    if isinstance(actor, HttpRequest):
        actor = getattr(actor, "user", None)
    return actor if actor is not None and getattr(actor, "is_authenticated", False) else None


def current_source() -> str:
    """Where the current change comes from: ``web:<path>``, ``rest:<path>`` (a
    request authenticated by an API token), ``shell``, or what
    :func:`acting_as` set."""
    actor = _actor.get()
    if isinstance(actor, HttpRequest) and getattr(actor, "_api_token_auth", False):
        return f"rest:{actor.path}"
    return _source.get() or "shell"


@contextmanager
def acting_as(actor: Any, source: str) -> Iterator[None]:
    """Attribute access changes made in the block to ``actor`` and ``source``::

        with acting_as(None, "directory:entra"):
            user.groups.set(groups)
    """
    actor_token = _actor.set(actor)
    source_token = _source.set(source)
    try:
        yield
    finally:
        _actor.reset(actor_token)
        _source.reset(source_token)


class ActorMiddleware:
    """Binds the request's user as the actor for access changes made during it.
    Sits after ``AuthenticationMiddleware``."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # The request itself, so current_actor() reads request.user when the
        # change is made (after any token authentication in the view).
        # The path is redacted: a token-bearing link must not land in an
        # AccessEvent's source (G3-1).
        with acting_as(request, f"web:{redact_path(request.path)}"):
            return self.get_response(request)
