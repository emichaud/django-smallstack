"""
django-axes client-IP resolution behind a reverse proxy (kamal-proxy).

Production sets AXES_IPWARE_META_PRECEDENCE_ORDER + AXES_IPWARE_PROXY_ORDER so
axes reads the real client from X-Forwarded-For instead of the proxy's
REMOTE_ADDR (see config/settings/production.py). Without that, every request
behind the proxy shares one IP and axes' IP-based lockout is useless.

These tests pin the behavior we rely on: the real client is used, spoofed
X-Forwarded-For entries are ignored, and a direct (no-proxy) connection falls
back to REMOTE_ADDR.
"""

from axes.helpers import get_client_ip_address
from django.test import RequestFactory, override_settings

# The production "behind kamal-proxy" axes config, applied to each test.
PROXY_AXES_SETTINGS = dict(
    AXES_IPWARE_META_PRECEDENCE_ORDER=("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"),
    AXES_IPWARE_PROXY_ORDER="right-to-left",
)

PROXY_IP = "10.0.0.9"  # the internal kamal-proxy address the app actually connects to
CLIENT_IP = "203.0.113.7"  # the real external client


@override_settings(**PROXY_AXES_SETTINGS)
def test_reads_real_client_from_forwarded_for():
    request = RequestFactory().get(
        "/accounts/login/", HTTP_X_FORWARDED_FOR=CLIENT_IP, REMOTE_ADDR=PROXY_IP
    )
    assert get_client_ip_address(request) == CLIENT_IP


@override_settings(**PROXY_AXES_SETTINGS)
def test_ignores_spoofed_leftmost_forwarded_for():
    # An attacker pre-seeds `X-Forwarded-For: <victim>`; kamal-proxy appends the
    # real client on the right. axes must trust the proxy-appended entry, not the
    # attacker's — otherwise lockout buckets can be evaded by rotating fake IPs.
    request = RequestFactory().get(
        "/accounts/login/",
        HTTP_X_FORWARDED_FOR=f"6.6.6.6, 7.7.7.7, {CLIENT_IP}",
        REMOTE_ADDR=PROXY_IP,
    )
    assert get_client_ip_address(request) == CLIENT_IP


@override_settings(**PROXY_AXES_SETTINGS)
def test_falls_back_to_remote_addr_without_proxy_header():
    # Local dev / direct connection: no X-Forwarded-For, so REMOTE_ADDR wins.
    request = RequestFactory().get("/accounts/login/", REMOTE_ADDR="127.0.0.1")
    assert get_client_ip_address(request) == "127.0.0.1"
