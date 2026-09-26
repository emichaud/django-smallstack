"""Turn remote-surface payload values into the objects the service wants.

``services.request_approval`` has always accepted ``target=`` and
``assignees=``; neither remote surface exposed them, so every downstream app had
to ship a bespoke filing endpoint just to attach an approval to a business row —
the exact duplication a primitive exists to prevent. (F-03.)

REST and MCP share these resolvers so the two surfaces accept the same spellings
and produce the same errors. Transport-free by design (no request objects, no
MCP imports) so either surface can be disabled independently.
"""

from __future__ import annotations

from typing import Any

from .registry import get_kind


def resolve_target(spec: Any) -> tuple[Any, str | None]:
    """Resolve ``"app_label.model:pk"`` or ``{app_label, model, pk}`` → instance.

    Returns ``(instance, None)`` on success (``(None, None)`` when nothing was
    asked for) or ``(None, message)`` with a caller-fixable explanation.
    """
    from django.contrib.contenttypes.models import ContentType

    if spec in (None, ""):
        return None, None
    if isinstance(spec, str):
        if ":" not in spec or "." not in spec.split(":")[0]:
            return None, f"target {spec!r} must look like 'app_label.model:pk'."
        dotted, _, pk = spec.partition(":")
        app_label, _, model = dotted.partition(".")
    elif isinstance(spec, dict):
        app_label = str(spec.get("app_label") or "")
        model = str(spec.get("model") or "")
        pk = str(spec.get("pk") or "")
    else:
        return None, "target must be a string or an object."
    if not (app_label and model and pk):
        return None, "target needs app_label, model and pk."
    try:
        ct = ContentType.objects.get(app_label=app_label, model=model.lower())
    except ContentType.DoesNotExist:
        return None, f"Unknown model {app_label}.{model}."
    model_class = ct.model_class()
    if model_class is None:  # stale ContentType row (the app/model is gone)
        return None, f"Unknown model {app_label}.{model}."
    obj = model_class._default_manager.filter(pk=pk).first()
    if obj is None:
        return None, f"No {app_label}.{model} with pk={pk}."
    return obj, None


def resolve_assignees(names: Any, *, kind_key: str) -> tuple[list[Any], str | None]:
    """Resolve usernames → active users, gated by the kind's allowlist.

    A remote caller must not be able to route a request at an arbitrary account,
    so a kind opts in with ``assignable=["finance", …]`` or
    ``assignable=lambda user: user.groups.filter(name="Finance").exists()``. With
    nothing declared, remote assignee selection is refused and the default policy
    (the assignees the app itself sets, else any staff) applies unchanged.
    """
    from django.contrib.auth import get_user_model

    if not names:
        return [], None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return [], "assignees must be a list of usernames."
    kind = get_kind(kind_key)
    allow = getattr(kind, "assignable", None)
    if allow is None:
        return [], (
            f"Kind {kind_key!r} does not accept remote assignees. Declare "
            "assignable=[…] on the @approval_kind to allow it."
        )
    users = list(get_user_model().objects.filter(username__in=names, is_active=True))
    found = {u.username for u in users}
    missing = [n for n in names if n not in found]
    if missing:
        return [], f"Unknown or inactive user(s): {', '.join(sorted(missing))}."
    if callable(allow):
        refused = [u.username for u in users if not allow(u)]
    else:
        allowed = set(allow)
        refused = [u.username for u in users if u.username not in allowed]
    if refused:
        return [], f"Kind {kind_key!r} does not allow assigning: {', '.join(sorted(refused))}."
    return users, None
