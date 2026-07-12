"""Proxy-aware client IP resolution.

Single source of truth for "what is this request's client IP" — used by both
the activity request log (apps/activity/middleware.py) and django-axes' login
lockout (wired via AXES_CLIENT_IP_CALLABLE), so the two never disagree.

Behind a reverse proxy (kamal-proxy) the socket peer is the proxy, so
REMOTE_ADDR is the same for every request and useless for telling clients
apart. When TRUST_PROXY_HEADERS is set we instead read the client from
X-Forwarded-For, trusting the *rightmost* entry — the one the proxy itself
appended. A client that pre-seeds a bogus ``X-Forwarded-For: <victim>`` header
can't forge its address that way: the proxy appends the real peer to the right,
so the injected values sit to the left and are ignored.

Without a trusted proxy in front (TRUST_PROXY_HEADERS off — the default) we use
REMOTE_ADDR, which a client cannot spoof. This assumes a single trusted proxy
(the default kamal-proxy deployment); a multi-proxy topology (e.g. a CDN in
front of kamal-proxy) would need the trusted hop count made configurable.
"""

from django.conf import settings
from django.http import HttpRequest


def get_client_ip(request: HttpRequest) -> str | None:
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if parts:
                return parts[-1]
    return request.META.get("REMOTE_ADDR")
