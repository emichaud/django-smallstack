"""Outbound event source — a global post_save/post_delete observer.

Mirrors apps/search/signals.py: listens to *every* model's save/delete with no
``sender=`` filter, does an O(1) CRUDView-registry lookup, and ignores any model
whose view didn't opt in with ``enable_webhooks = True``. This is the only tap
point that sees creates, updates, deletes AND raw ORM writes across every surface
(HTML / REST / MCP / sc). Handlers swallow exceptions so a webhook can never break
a model save.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

if TYPE_CHECKING:
    from django.db.models import Model

    from apps.smallstack.crud import CRUDView

logger = logging.getLogger(__name__)


def _view_for(sender: type[Model]) -> type[CRUDView] | None:
    """Return the CRUDView for a model iff it opted into webhooks, else None."""
    from apps.smallstack.crud import CRUDView

    view = CRUDView._registry.get(sender)
    if view is None or not getattr(view, "enable_webhooks", False):
        return None
    return view


def _event_type(sender: type[Model], action: str) -> str:
    """"<app_label>.<model_name>.<action>", e.g. scheduler.scheduledjob.created."""
    meta = sender._meta
    return f"{meta.app_label}.{meta.model_name}.{action}"


def _wants(view: type[CRUDView], action: str) -> bool:
    events = getattr(view, "webhook_events", None)
    return events is None or action in events


def _build_payload(
    view: type[CRUDView], instance: Model, action: str, event_type: str, event_id: str
) -> dict[str, Any]:
    """Event envelope. On create/update the record is serialized with the same
    helper the REST API uses; on delete only the pk survives.

    Backward-compatible envelope upgrade: the original keys stay, and stable
    top-level keys are added — ``event_id``, ``origin``, and a ``resource`` block with an
    **absolute** ``url`` — so a consumer (esp. another SmallStack) can dedupe and act
    without reconstructing the path.
    """
    from django.utils import timezone

    from .context import current_origin

    model_label = f"{instance._meta.app_label}.{instance._meta.model_name}"
    data: dict[str, Any] = {}
    if action != "deleted":
        try:
            from apps.smallstack.api import serialize

            fields = view._get_detail_fields() if hasattr(view, "_get_detail_fields") else (view.fields or [])
            data = serialize(
                instance,
                list(fields or []),
                extra_fields=list(getattr(view, "api_extra_fields", []) or []),
                expand_fields=set(getattr(view, "api_expand_fields", []) or []),
            )
        except Exception:  # noqa: BLE001 — fall back to a minimal envelope
            data = {"id": instance.pk}
    else:
        data = {"id": instance.pk}

    return {
        # --- original keys (unchanged, for existing consumers) ---
        "event": event_type,
        "action": action,
        "model": model_label,
        "id": instance.pk,
        "occurred_at": timezone.now().isoformat(),
        "data": data,
        # --- envelope upgrade: stable top-level keys, additive ---
        "event_id": event_id,
        "origin": current_origin(),
        "resource": {
            "type": model_label,
            "id": instance.pk,
            "url": _resource_url(view, instance),
        },
    }


def _resource_url(view: type[CRUDView], instance: Model) -> str | None:
    """Best-effort ABSOLUTE URL to the resource (its REST detail endpoint), so a consumer
    can act without guessing the path. None if it can't be built."""
    from .context import current_origin

    try:
        rest_base = getattr(view, "url_base", "") or ""
        if not rest_base:
            return None
        origin = current_origin()
        if not origin.startswith(("http://", "https://")):
            return None
        return f"{origin.rstrip('/')}/smallstack/api/{rest_base}/{instance.pk}/"
    except Exception:  # noqa: BLE001
        return None


def _fire(sender: type[Model], instance: Model, action: str) -> None:
    from .context import suppressed

    # Loop guard: writes inside suppress_webhooks() (e.g. an inbound handler's write-back)
    # emit no outbound events, so a two-way link can't run away.
    if suppressed():
        return
    view = _view_for(sender)
    if view is None or not _wants(view, action):
        return
    try:
        import uuid

        from . import services

        event_type = _event_type(sender, action)
        # One stable event_id per logical event, shared by every fan-out delivery and
        # reused by replay.
        event_id = str(uuid.uuid4())
        payload = _build_payload(view, instance, action, event_type, event_id)
        services.fan_out(event_type, payload, event_id=event_id)
    except Exception:  # noqa: BLE001 — a webhook must never break the save/delete
        logger.exception("webhooks: failed to fire %s for %s", action, sender)


@receiver(post_save)
def _on_save(sender: type[Model], instance: Model, created: bool, **kwargs: Any) -> None:
    _fire(sender, instance, "created" if created else "updated")


@receiver(post_delete)
def _on_delete(sender: type[Model], instance: Model, **kwargs: Any) -> None:
    _fire(sender, instance, "deleted")
