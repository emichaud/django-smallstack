"""Proxy-aware client IP resolution (apps/smallstack/client_ip.py).

One helper resolves the client IP for both the activity request log and
django-axes' login lockout. These tests pin the behavior we rely on:

- behind a trusted proxy, the real client is read from X-Forwarded-For;
- a spoofed (client-injected) X-Forwarded-For entry is ignored;
- without a trusted proxy, or with no header, REMOTE_ADDR is used;
- axes resolves the IP through the very same helper (wired via
  AXES_CLIENT_IP_CALLABLE), so lockout buckets match the activity log.
"""

from axes.helpers import get_client_ip_address
from django.test import RequestFactory, override_settings

from apps.smallstack.client_ip import get_client_ip

PROXY_IP = "10.0.0.9"  # the internal kamal-proxy address the app connects to
CLIENT_IP = "203.0.113.7"  # the real external client


def _request(xff=None, remote=PROXY_IP):
    extra = {"HTTP_X_FORWARDED_FOR": xff} if xff is not None else {}
    return RequestFactory().get("/", REMOTE_ADDR=remote, **extra)


@override_settings(TRUST_PROXY_HEADERS=True)
def test_reads_real_client_from_forwarded_for():
    assert get_client_ip(_request(xff=CLIENT_IP)) == CLIENT_IP


@override_settings(TRUST_PROXY_HEADERS=True)
def test_ignores_spoofed_leftmost_forwarded_for():
    # Attacker pre-seeds `X-Forwarded-For: <victim>`; the proxy appends the real
    # client on the right. We must trust the proxy-appended (rightmost) entry.
    xff = f"6.6.6.6, 7.7.7.7, {CLIENT_IP}"
    assert get_client_ip(_request(xff=xff)) == CLIENT_IP


@override_settings(TRUST_PROXY_HEADERS=True)
def test_falls_back_to_remote_addr_without_header():
    assert get_client_ip(_request(xff=None, remote="127.0.0.1")) == "127.0.0.1"


@override_settings(TRUST_PROXY_HEADERS=False)
def test_untrusted_proxy_ignores_forwarded_for():
    # No trusted proxy in front: X-Forwarded-For is attacker-controlled, so it
    # must be ignored entirely — REMOTE_ADDR (unspoofable) wins.
    assert get_client_ip(_request(xff=f"6.6.6.6, {CLIENT_IP}", remote=PROXY_IP)) == PROXY_IP


@override_settings(TRUST_PROXY_HEADERS=True)
def test_axes_resolves_through_the_same_helper():
    # axes is wired to the helper via AXES_CLIENT_IP_CALLABLE, so its lockout key
    # and the activity log agree on the client IP — including spoof-resistance.
    req = _request(xff=f"6.6.6.6, {CLIENT_IP}")
    assert get_client_ip_address(req) == CLIENT_IP == get_client_ip(req)
