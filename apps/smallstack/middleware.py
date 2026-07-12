"""
SmallStack middleware.
"""

import logging
import uuid
import zoneinfo
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

logger = logging.getLogger("smallstack")


def health_response() -> JsonResponse:
    """Build the ``/health/`` response (database connectivity probe).

    Shared by the health view (``config.views.health_check``) and
    ``HealthCheckMiddleware`` so the two can never drift.
    """
    from django.db import connection

    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:  # pragma: no cover - exercised via the view's tests
        db_ok = False
        logger.error("Health check: database unreachable — %s", e)

    payload = {"status": "ok" if db_ok else "error", "database": "ok" if db_ok else "unreachable"}
    return JsonResponse(payload, status=200 if db_ok else 503)


class HealthCheckMiddleware:
    """Answer ``/health/`` before ALLOWED_HOSTS validation runs.

    Proxy / load-balancer health checks (kamal-proxy, ALBs, k8s) hit the
    container by IP, so they send a ``Host`` header that can't be predicted
    and isn't in ``ALLOWED_HOSTS``. Handling ``/health/`` here — first in the
    chain, before SecurityMiddleware/CommonMiddleware call ``get_host()`` —
    lets the probe succeed WITHOUT ``ALLOWED_HOSTS=*`` (which would disable
    Host-header validation for the whole site). Must stay first in MIDDLEWARE.
    (Audit H5.)
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == "/health/":
            return health_response()
        return self.get_response(request)


class RequestIDMiddleware:
    """Attach a unique request ID to every request/response.

    If the incoming request already carries an ``X-Request-ID`` header
    (e.g. from a load balancer), that value is reused.  Otherwise a new
    UUID is generated.

    The ID is stored on ``request.id`` for downstream code and returned
    in the ``X-Request-ID`` response header so clients can reference it.
    """

    HEADER = "X-Request-ID"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.META.get("HTTP_X_REQUEST_ID") or f"req_{uuid.uuid4()}"
        request.id = request_id

        response = self.get_response(request)
        response[self.HEADER] = request_id
        return response


class TimezoneMiddleware:
    """Activate the user's timezone for the duration of each request.

    When a logged-in user has a timezone set on their profile, Django's
    template filters (like |date) will automatically display datetimes in
    that timezone.  Falls back to the system TIME_ZONE setting.

    Caches resolved timezone info on the request object so template tags
    can access it without repeated database queries:
        request._tz_user    – ZoneInfo for display (user or server fallback)
        request._tz_server  – ZoneInfo for server TIME_ZONE
        request._tz_differs – True when user TZ ≠ server TZ
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        server_tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        user_tz = server_tz

        try:
            if hasattr(request, "user") and request.user.is_authenticated:
                user_tz = request.user.profile.get_timezone()
        except Exception:
            # Broad by design: never let a missing profile / bad tz break a request.
            # Log at debug and fall back to the server timezone set above.
            logger.debug("TimezoneMiddleware: falling back to server tz", exc_info=True)

        # Cache on request for template tags
        request._tz_user = user_tz
        request._tz_server = server_tz
        request._tz_differs = str(user_tz) != str(server_tz)

        timezone.activate(user_tz)

        response = self.get_response(request)
        return response


class HtmxLoginRedirectMiddleware:
    """Convert login redirects to full-page navigations for HTMX requests.

    When an HTMX fragment request hits a LoginRequired redirect, Django
    returns a 302 to the login page. HTMX follows it and injects the login
    page HTML into the target element. This middleware detects that case
    and responds with HX-Redirect so the browser does a proper navigation.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        if getattr(request, "htmx", False) and response.status_code in (301, 302) and hasattr(response, "url"):
            redirect_url = response.url
            resp = HttpResponse(status=200)
            resp["HX-Redirect"] = redirect_url
            return resp

        return response
