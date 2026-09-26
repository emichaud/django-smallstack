"""Mark a notification read only once its target actually opened.

``open_notification`` used to mark the row read and *then* redirect. When the
target turned out to be unreachable for that recipient (a 403 or a stale 404)
the click consumed the only pointer the user had: the badge went down by one and
the actionable row vanished from "unread", with nothing to show for it.

Reading a notification is an outcome, not an intention — so the view now hands
the decision to this middleware via a ``?_notification=<pk>`` marker on the
redirect target, and only a successful arrival (2xx) retires the row. A 403/404
leaves it unread, which is the truthful state: the user still has work to do.

Cheap by construction: one dict lookup on requests that don't carry the marker.
"""

from __future__ import annotations

from typing import Any, Callable

from django.http import HttpRequest, HttpResponse

PARAM = "_notification"


class NotificationReadOnArrivalMiddleware:
    """Marks the notification named by ``?_notification=<pk>`` read on a 2xx."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw: Any = request.GET.get(PARAM) if request.method in ("GET", "HEAD") else None
        response = self.get_response(request)
        if not raw or not 200 <= response.status_code < 300:
            return response
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return response
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            return response
        try:
            from . import services

            services.mark_read(user, ids=[pk])
        except Exception:  # noqa: BLE001 — never break the page being viewed
            pass
        return response
