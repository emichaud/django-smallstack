"""Send-time SSRF guard: redirects are never followed, and the connected peer
is re-checked (audit 2026-09-13, C4).

A real localhost server stands in for both "the attacker's endpoint" and
"the internal service": the pre-send url_is_allowed() check is forced to pass,
exactly as it would for a public host that redirects or DNS-rebinds.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from apps.webhooks import services
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint
from apps.webhooks.tasks import deliver_webhook

pytestmark = pytest.mark.django_db

_HITS: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        _HITS.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/internal-metadata")
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        _HITS.clear()


def _deliver(url):
    ep = WebhookEndpoint.objects.create(name="t", target_url=url, secret="s", event_filter=["*"])
    d = WebhookDelivery.objects.create(endpoint=ep, event_type="a.b.created", payload={}, max_attempts=1)
    result = deliver_webhook.func(d.pk)
    d.refresh_from_db()
    return result, d


def test_redirect_is_not_followed(server, settings):
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = True
    host, port = server
    result, delivery = _deliver(f"http://{host}:{port}/redirect")

    assert _HITS == ["/redirect"], "the Location target must never be requested"
    assert result["success"] is False
    assert delivery.response_status == 302


def test_connected_private_peer_is_refused_even_if_precheck_passed(server, settings, monkeypatch):
    """Models DNS rebinding: the pre-check saw a public address, the connect
    lands on loopback. The peer check must stop it before any request byte."""
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = False
    monkeypatch.setattr(services, "url_is_allowed", lambda url: (True, ""))
    host, port = server
    result, delivery = _deliver(f"http://{host}:{port}/hook")

    assert _HITS == [], "request reached a private address"
    assert result["success"] is False
    assert "SSRF" in delivery.error
