"""Background tasks — the outbound HTTP send and the inbound handler dispatch.

The framework has no automatic task retry (db_worker marks a failing result
FAILED and moves on), so ``deliver_webhook`` owns its own retry: on failure it
sets the delivery to ``retrying`` with a ``next_attempt_at`` cursor, and the tick
(services.run_due_deliveries) re-enqueues it when due.

Uses urllib from the stdlib for the POST so the app adds no new dependency.
"""

from __future__ import annotations

import http.client
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from django.db.models import F
from django.tasks import task
from django.utils import timezone

from . import services
from .models import WebhookDelivery, WebhookEndpoint, WebhookReceipt

logger = logging.getLogger("smallstack.webhooks")

# Fields written on every attempt outcome (success / retry / dead).
_ATTEMPT_FIELDS = [
    "attempt",
    "response_status",
    "response_ms",
    "error",
    "status",
    "next_attempt_at",
    "updated_at",
]


@task(queue_name="default")
def deliver_webhook(delivery_id: int) -> dict[str, Any]:
    """POST one WebhookDelivery to its endpoint with an HMAC signature.

    Returns a small status dict (also captured as the DBTaskResult return value).
    """
    try:
        delivery = WebhookDelivery.objects.select_related("endpoint").get(pk=delivery_id)
    except WebhookDelivery.DoesNotExist:
        return {"error": f"delivery {delivery_id} not found"}

    if delivery.is_terminal:
        return {"skipped": "already terminal", "status": delivery.status}

    from urllib.parse import urlencode, urlsplit, urlunsplit

    from . import hooks
    from .context import current_origin

    endpoint = delivery.endpoint
    attempt = delivery.attempt + 1

    # 1. Transform seam — the wire body + content type (default: current envelope).
    transform = hooks.get_transform(endpoint.transform)
    transformed = transform(delivery.payload)
    body = transformed.body

    headers = {
        "Content-Type": transformed.content_type,
        services.EVENT_HEADER: delivery.event_type,
        services.DELIVERY_HEADER: str(delivery.pk),
        services.ORIGIN_HEADER: current_origin(),
        "User-Agent": "SmallStack-Webhooks/1.0",
    }
    if delivery.event_id:
        headers[services.EVENT_ID_HEADER] = str(delivery.event_id)

    # 2. Auth seam — credentials for the destination (default: HMAC signature header).
    auth = hooks.get_auth(endpoint.auth_scheme)
    auth_result = auth(
        hooks.OutgoingRequest(
            url=endpoint.target_url, body=body, headers=dict(headers), event_type=delivery.event_type
        ),
        endpoint,
    )
    headers.update(auth_result.headers)
    target_url = endpoint.target_url
    if auth_result.params:
        parts = urlsplit(target_url)
        query = "&".join(filter(None, [parts.query, urlencode(auth_result.params)]))
        target_url = urlunsplit(parts._replace(query=query))

    # Endpoint-supplied static headers, but never let them clobber our signing/auth.
    for k, v in (endpoint.headers or {}).items():
        if k not in headers:
            headers[k] = str(v)

    timeout = int(getattr(settings, "SMALLSTACK_WEBHOOK_TIMEOUT", 10))
    started = time.monotonic()
    status_code: int | None = None
    error = ""
    retry_after: int | None = None

    # Re-check the target against the SSRF guard at send time (config may have
    # tightened since the endpoint was created).
    ok, reason = services.url_is_allowed(target_url)
    if not ok:
        error = f"blocked by SSRF guard: {reason}"
    else:
        req = urllib.request.Request(target_url, data=body, headers=headers, method="POST")
        try:
            with _open(req, timeout=timeout) as resp:
                status_code = resp.status
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            # Honor Retry-After on rate-limit / unavailable responses (F-022).
            if exc.code in (429, 503):
                retry_after = services.parse_retry_after(exc.headers.get("Retry-After"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = str(getattr(exc, "reason", exc))
        except Exception as exc:  # noqa: BLE001
            error = repr(exc)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    succeeded = status_code is not None and 200 <= status_code < 300
    _record_attempt(delivery, attempt, status_code, elapsed_ms, error, succeeded, retry_after)
    return {
        "delivery": delivery.pk,
        "attempt": attempt,
        "response_status": status_code,
        "success": succeeded,
    }


# ---------------------------------------------------------------------------
# Guarded HTTP: no redirects, and the connected peer is re-checked
# ---------------------------------------------------------------------------
#
# url_is_allowed() vets the URL's host by resolving it, but urllib resolves
# again when it connects (a DNS-rebinding window), and the default opener
# follows 3xx into wherever Location points — e.g. cloud metadata at
# 169.254.169.254. The delivery record's status/latency then served as a
# blind-SSRF oracle. So: redirects are refused (a 3xx is a failed delivery,
# never followed), and the socket's actual peer address is checked right after
# connect, before any request byte (or TLS handshake) is sent. (Audit C4.)


class _BlockedPeer(OSError):
    pass


def _check_peer(sock: Any) -> None:
    if getattr(settings, "SMALLSTACK_WEBHOOK_ALLOW_PRIVATE", False):
        return
    peer = sock.getpeername()[0]
    if services.ip_is_blocked(peer):
        sock.close()
        raise _BlockedPeer(f"blocked by SSRF guard: connected peer {peer} is a private/loopback address")


class _PeerCheckedHTTPConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        super().connect()
        _check_peer(self.sock)


class _PeerCheckedHTTPSConnection(http.client.HTTPSConnection, _PeerCheckedHTTPConnection):
    # MRO: HTTPSConnection.connect → super().connect() lands in the peer check
    # above, which runs before HTTPSConnection wraps the socket in TLS.
    pass


def _via_proxy(req: urllib.request.Request) -> bool:
    # Through an env-configured proxy the socket's peer is the proxy, not the
    # target — the pre-send url_is_allowed() check is what applies then.
    return bool(getattr(req, "_tunnel_host", None)) or req.has_proxy()


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(http.client.HTTPConnection if _via_proxy(req) else _PeerCheckedHTTPConnection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        conn = http.client.HTTPSConnection if _via_proxy(req) else _PeerCheckedHTTPSConnection
        return self.do_open(conn, req, context=self._context)  # type: ignore[attr-defined]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None  # urllib then raises HTTPError(3xx) — recorded as a failed attempt


def _open(req: urllib.request.Request, *, timeout: int) -> Any:
    """Send ``req`` through the guarded opener. Patched in tests."""
    opener = urllib.request.build_opener(_GuardedHTTPHandler, _GuardedHTTPSHandler, _NoRedirectHandler)
    return opener.open(req, timeout=timeout)


def _record_attempt(
    delivery: WebhookDelivery,
    attempt: int,
    status_code: int | None,
    elapsed_ms: int,
    error: str,
    succeeded: bool,
    retry_after: int | None = None,
) -> None:
    """Persist the attempt outcome and schedule a retry (or retire) on failure.

    ``retry_after`` (parsed from a 429/503 ``Retry-After`` header) overrides the backoff
    table for this attempt, clamped to ``SMALLSTACK_WEBHOOK_MAX_BACKOFF`` (F-022).
    """
    now = timezone.now()
    delivery.attempt = attempt
    delivery.response_status = status_code
    delivery.response_ms = elapsed_ms
    delivery.error = error[:2000]

    if succeeded:
        delivery.status = WebhookDelivery.Status.SUCCESS
        delivery.next_attempt_at = None
        delivery.save(update_fields=_ATTEMPT_FIELDS)
        _bump_endpoint(delivery, ok=True)
        return

    if attempt >= delivery.max_attempts:
        delivery.status = WebhookDelivery.Status.DEAD
        delivery.next_attempt_at = None
        delivery.save(update_fields=_ATTEMPT_FIELDS)
        _bump_endpoint(delivery, ok=False, dead=True)
        _notify_dead(delivery)
        return

    # Schedule the next retry — Retry-After wins over the backoff table when present.
    from datetime import timedelta

    if retry_after is not None:
        wait = services.clamp_backoff(retry_after)
    else:
        wait = services.backoff_seconds(attempt)
    delivery.status = WebhookDelivery.Status.RETRYING
    delivery.next_attempt_at = now + timedelta(seconds=wait)
    delivery.save(update_fields=_ATTEMPT_FIELDS)
    _bump_endpoint(delivery, ok=False)


def _bump_endpoint(delivery: WebhookDelivery, *, ok: bool, dead: bool = False) -> None:
    """Update the endpoint's rollup counters and auto-disable a persistently
    failing endpoint."""
    now = timezone.now()
    ep_qs = WebhookEndpoint.objects.filter(pk=delivery.endpoint_id)
    if ok:
        ep_qs.update(
            last_delivery_at=now,
            last_status=WebhookEndpoint.Status.SUCCESS,
            total_deliveries=F("total_deliveries") + 1,
            consecutive_failures=0,
        )
        return

    status = WebhookEndpoint.Status.DEAD if dead else WebhookEndpoint.Status.RETRYING
    ep_qs.update(
        last_delivery_at=now,
        last_status=status,
        total_deliveries=F("total_deliveries") + 1,
        consecutive_failures=F("consecutive_failures") + 1,
    )
    threshold = int(getattr(settings, "SMALLSTACK_WEBHOOK_AUTO_DISABLE_AFTER", 20))
    if threshold:
        ep = WebhookEndpoint.objects.filter(pk=delivery.endpoint_id).first()
        if ep and ep.consecutive_failures >= threshold and ep.enabled:
            WebhookEndpoint.objects.filter(pk=ep.pk).update(enabled=False)
            logger.warning(
                "webhooks: endpoint %s auto-disabled after %s consecutive failures",
                ep.name,
                ep.consecutive_failures,
            )


def _notify_dead(delivery: WebhookDelivery) -> None:
    """Email configured recipients when a delivery exhausts its retries."""
    recipients = getattr(settings, "SMALLSTACK_WEBHOOK_FAILURE_EMAILS", None)
    if not recipients:
        return
    try:
        from apps.tasks.tasks import send_email_task

        send_email_task.enqueue(
            recipient=list(recipients),
            subject=f"[webhooks] delivery failed: {delivery.event_type}",
            message=(
                f"Webhook delivery to “{delivery.endpoint.name}” gave up after "
                f"{delivery.attempt} attempts.\n\n"
                f"Event: {delivery.event_type}\n"
                f"Last response: {delivery.response_status}\n"
                f"Error: {delivery.error}\n"
            ),
        )
    except Exception:  # noqa: BLE001
        logger.warning("webhooks: dead-delivery notification could not be enqueued", exc_info=True)


# ---------------------------------------------------------------------------
# Inbound dispatch
# ---------------------------------------------------------------------------


@task(queue_name="default")
def dispatch_incoming(receipt_id: int) -> dict[str, Any]:
    """Run the registered handler for an accepted inbound receipt."""
    try:
        receipt = WebhookReceipt.objects.select_related("receiver").get(pk=receipt_id)
    except WebhookReceipt.DoesNotExist:
        return {"error": f"receipt {receipt_id} not found"}

    import contextlib

    from .context import suppress_webhooks
    from .registry import get_handler, handler_cascades

    handler_name = receipt.receiver.handler_name
    handler = get_handler(handler_name)
    if handler is None:
        receipt.status = WebhookReceipt.Status.FAILED
        receipt.error = f"no handler registered for {handler_name!r}"
        receipt.save(update_fields=["status", "error"])
        return {"error": receipt.error}

    # Loop-safe by default: run the handler inside suppress_webhooks() so a write-back
    # emits no outbound event (F-020). A handler that wants to cascade opts out with
    # @webhook_handler("slug", cascade=True).
    guard = contextlib.nullcontext() if handler_cascades(handler_name) else suppress_webhooks()

    try:
        with guard:
            handler(receipt)
    except Exception as exc:  # noqa: BLE001 — a handler error is recorded, not fatal
        receipt.status = WebhookReceipt.Status.FAILED
        receipt.error = repr(exc)[:2000]
        receipt.save(update_fields=["status", "error"])
        logger.exception("webhooks: handler %s failed", handler_name)
        return {"error": receipt.error}

    receipt.status = WebhookReceipt.Status.PROCESSED
    receipt.save(update_fields=["status"])
    return {"receipt": receipt.pk, "status": "processed"}
