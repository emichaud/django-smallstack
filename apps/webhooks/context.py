"""Loop guard — thread-local outbound suppression + the delivery origin.

The outbound event source is a global ``post_save``/``post_delete`` observer with no
origin discrimination, so a handler (or a paired SmallStack) that writes back into a
``enable_webhooks`` model re-triggers the event and can run away (reproduced 1→6 in an
n8n round trip). Two primitives break the loop:

* :func:`suppress_webhooks` — a re-entrant thread-local context manager. Writes made
  inside it emit **no** outbound events. Inbound dispatch runs each handler inside it by
  default (see :func:`apps.webhooks.registry.get_handler`), so a naive write-back can't
  echo. A handler that *wants* to cascade opts out with ``cascade=True``.

* :func:`current_origin` / the ``X-SmallStack-Origin`` header — every delivery is stamped
  with this SmallStack's origin so a receiver can drop self-originated events
  (``WebhookReceiver.ignore_origin``), closing a two-way S2S link.

Thread-local (not a plain module global) so a suppression on one worker thread never
leaks into a concurrently-served request on another. Best-effort by design: if something
about the guard misbehaves it must fail *open* (still deliver) rather than silently drop
real events — so :func:`suppressed` is a simple boolean read with a safe default.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlsplit

from django.conf import settings

_state = threading.local()


def suppressed() -> bool:
    """True iff the current thread is inside a :func:`suppress_webhooks` block."""
    return getattr(_state, "depth", 0) > 0


@contextmanager
def suppress_webhooks() -> Iterator[None]:
    """Suppress outbound webhook fan-out for writes made in this block (re-entrant).

    Public API — re-exported from ``apps.webhooks``. Use it around a write that must not
    emit an event: an inbound handler's write-back, an import, a backfill::

        from apps.webhooks import suppress_webhooks

        with suppress_webhooks():
            ticket.status = "closed"
            ticket.save()          # fires no webhook

    Nesting is safe: only leaving the outermost block re-arms fan-out. The counter is
    always restored, even if the body raises.
    """
    _state.depth = getattr(_state, "depth", 0) + 1
    try:
        yield
    finally:
        _state.depth = max(0, getattr(_state, "depth", 1) - 1)


def current_origin() -> str:
    """This SmallStack's delivery origin (the ``X-SmallStack-Origin`` header value).

    ``SMALLSTACK_WEBHOOK_ORIGIN`` when set; otherwise derived from ``SITE_URL`` /
    ``SMALLSTACK_SITE_URL`` (scheme+host), else the machine hostname. Stable per process
    and cheap, so callers needn't cache it.
    """
    explicit = getattr(settings, "SMALLSTACK_WEBHOOK_ORIGIN", "") or ""
    if explicit:
        return explicit.strip()

    for name in ("SITE_URL", "SMALLSTACK_SITE_URL", "BASE_URL"):
        site = getattr(settings, name, "") or ""
        if site:
            parts = urlsplit(site)
            if parts.scheme and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}"
            if parts.path:  # a bare "host" with no scheme
                return parts.path.strip("/")

    import socket

    try:
        return socket.gethostname()
    except OSError:  # pragma: no cover — hostname lookup should not fail
        return "smallstack"


def origin_is_configured() -> bool:
    """True iff the delivery origin is an explicit absolute URL — i.e. a real base a
    consumer can build ``resource.url`` from and dedupe on.

    False when neither ``SMALLSTACK_WEBHOOK_ORIGIN`` nor a URL-shaped ``SITE_URL`` /
    ``SMALLSTACK_SITE_URL`` / ``BASE_URL`` is set, in which case :func:`current_origin`
    falls back to the bare hostname and ``resource.url`` degrades to ``None``.
    """
    origin = current_origin()
    return origin.startswith(("http://", "https://"))
