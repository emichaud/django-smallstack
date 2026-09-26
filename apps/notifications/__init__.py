"""SmallStack notifications — a generic in-app notification primitive.

Any app can hand a user (or several) a notification row that shows up under
the topbar bell and in the inbox at /smallstack/notifications/:

    from apps.notifications import notify
    notify([user], title="Approval needed", url="/smallstack/approvals/requests/4/",
           kind="approvals.requested", actor=request.user)

The first producer is the approvals app; the primitive is deliberately
app-agnostic. Delivery is best-effort: ``notify`` never raises, so a
notification failure can never break the write that triggered it.

The service symbols are re-exported lazily (PEP 562) — importing this package
at Django app-load time must not touch models.
"""

from typing import Any

__all__ = ["notify", "mark_read", "resolve", "unread_count"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import services

        return getattr(services, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
