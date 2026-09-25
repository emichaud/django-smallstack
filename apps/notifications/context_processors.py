"""Template context for the topbar bell.

Registered in TEMPLATES context_processors, so every page can render the bell
without per-view wiring. Cost: one indexed COUNT per authenticated page render
(anonymous requests and disabled installs pay nothing).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest


def notifications(request: HttpRequest) -> dict[str, Any]:
    enabled = bool(getattr(settings, "SMALLSTACK_NOTIFICATIONS_ENABLED", True))
    user = getattr(request, "user", None)
    if not enabled or user is None or not user.is_authenticated:
        return {"notifications_enabled": False, "notifications_unread": 0}
    try:
        from .services import unread_count

        return {"notifications_enabled": True, "notifications_unread": unread_count(user)}
    except Exception:  # noqa: BLE001 — the bell must never break page rendering
        return {"notifications_enabled": False, "notifications_unread": 0}
