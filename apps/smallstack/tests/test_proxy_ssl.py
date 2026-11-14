"""Forwarded-proto trust — request.is_secure() behind a TLS-terminating proxy.

kamal-proxy terminates TLS and forwards over HTTP with ``X-Forwarded-Proto:
https``. Production couples ``SECURE_PROXY_SSL_HEADER`` to ``TRUST_PROXY_HEADERS``
so Django builds ``https://`` absolute URLs (feed self-links, sitemaps, email
links) behind the proxy — while a directly-exposed deploy (flag off, header
unset) never trusts a client-supplied header.
"""

from __future__ import annotations

from django.test import RequestFactory, override_settings

# The exact tuple production.py sets when TRUST_PROXY_HEADERS is on. Guards
# against a typo in the header name/value drifting from what the proxy sends.
_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


@override_settings(SECURE_PROXY_SSL_HEADER=_HEADER)
def test_forwarded_proto_https_makes_request_secure():
    req = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")
    assert req.is_secure() is True
    assert req.build_absolute_uri("/feed/status.rss").startswith("https://")


@override_settings(SECURE_PROXY_SSL_HEADER=_HEADER)
def test_forwarded_proto_http_is_not_secure():
    req = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="http")
    assert req.is_secure() is False


def test_without_the_setting_a_spoofed_header_is_ignored():
    # Test settings don't set SECURE_PROXY_SSL_HEADER (only production does, and
    # only when TRUST_PROXY_HEADERS is on). A spoofed header must not upgrade a
    # plain-HTTP request — the safe default for a direct-exposed deploy.
    req = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")
    assert req.is_secure() is False
