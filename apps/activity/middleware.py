"""Middleware for tracking HTTP request activity."""

import logging
import time
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class ActivityMiddleware:
    """Records HTTP requests to the RequestLog table.

    Skips excluded paths and captures timing. Pruning is handled
    separately by the `prune_activity` management command on a schedule.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.exclude_paths = getattr(
            settings,
            "ACTIVITY_EXCLUDE_PATHS",
            ["/static/", "/media/", "/favicon.ico", "/health/", "/admin/jsi18n/", "/__debug__/"],
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self._should_skip(request.path):
            return self.get_response(request)

        start = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        try:
            self._record(request, response, elapsed_ms)
        except Exception:
            logger.exception("Failed to record activity log")

        return response

    def _should_skip(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.exclude_paths)

    def _record(self, request: HttpRequest, response: HttpResponse, elapsed_ms: int) -> None:
        from .models import RequestLog

        user = getattr(request, "user", None)
        if user and not user.is_authenticated:
            user = None

        RequestLog.objects.create(
            path=request.path[:2048],
            route=self._route(request),
            method=request.method or "",
            status_code=response.status_code,
            user=user,
            api_token=getattr(request, "_api_token", None),
            request_id=getattr(request, "id", ""),
            response_time_ms=elapsed_ms,
            ip_address=self._get_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:4096],
        )

    @staticmethod
    def _route(request: HttpRequest) -> str:
        """The matched URL pattern, "/"-prefixed, or "" when the URLconf had no match."""
        match = getattr(request, "resolver_match", None)
        if match is None:
            return ""
        return ("/" + (match.route or ""))[:255]

    def _get_ip(self, request: HttpRequest) -> str | None:
        from apps.smallstack.client_ip import get_client_ip

        return get_client_ip(request)
