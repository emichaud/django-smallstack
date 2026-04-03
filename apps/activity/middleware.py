"""Middleware for tracking HTTP request activity."""

import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)


class ActivityMiddleware:
    """Records HTTP requests to the RequestLog table.

    Skips excluded paths and captures timing. Pruning is handled
    separately by the `prune_activity` management command on a schedule.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.exclude_paths = getattr(
            settings,
            "ACTIVITY_EXCLUDE_PATHS",
            ["/static/", "/media/", "/favicon.ico", "/health/", "/admin/jsi18n/", "/__debug__/"],
        )

    def __call__(self, request):
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

    def _should_skip(self, path):
        return any(path.startswith(prefix) for prefix in self.exclude_paths)

    def _record(self, request, response, elapsed_ms):
        from .models import RequestLog

        user = getattr(request, "user", None)
        if user and not user.is_authenticated:
            user = None

        RequestLog.objects.create(
            path=request.path[:2048],
            method=request.method,
            status_code=response.status_code,
            user=user,
            api_token=getattr(request, "_api_token", None),
            request_id=getattr(request, "id", ""),
            response_time_ms=elapsed_ms,
            ip_address=self._get_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:4096],
        )

    def _get_ip(self, request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
