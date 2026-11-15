"""Django model permissions for CRUDView surfaces.

A CRUDView that sets ``model_permissions = True`` asks Django's permission
system on every surface (HTML pages, REST, MCP and ``sc``) before acting, the
same check Django admin makes: ``view``, ``add``, ``change`` or ``delete`` on
the model. Superusers hold every permission; groups and per-user grants come
from ``django.contrib.auth`` as usual.

``view`` is also granted by ``change``, as in Django admin, so a person who can
edit a model can always see it.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_permission_codename
from django.db.models import Model

#: The four permission actions, in Django's own vocabulary.
PERMISSION_ACTIONS = ("view", "add", "change", "delete")

#: Which permission an HTTP method needs on a REST route.
METHOD_PERMISSION = {
    "GET": "view",
    "HEAD": "view",
    "OPTIONS": "view",
    "POST": "add",
    "PUT": "change",
    "PATCH": "change",
    "DELETE": "delete",
}


def perm_name(model: type[Model], action: str) -> str:
    """``"<app_label>.<codename>"``, e.g. ``"blog.change_post"``."""
    opts = model._meta
    return f"{opts.app_label}.{get_permission_codename(action, opts)}"


def has_model_permission(user: Any, model: type[Model], action: str) -> bool:
    """Whether ``user`` holds ``action`` on ``model``. Anonymous users hold none."""
    if action not in PERMISSION_ACTIONS:
        raise ValueError(f"unknown permission action {action!r}; expected one of {PERMISSION_ACTIONS}")
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if action == "view":
        return bool(user.has_perm(perm_name(model, "view")) or user.has_perm(perm_name(model, "change")))
    return bool(user.has_perm(perm_name(model, action)))


#: Models that hold who-may-do-what: accounts, groups and permissions, API
#: tokens, and the two audit trails. Explorer (and the surfaces that follow its
#: rule: search, datasets) always checks Django model permissions on these,
#: whatever ``SMALLSTACK_EXPLORER_MODEL_PERMISSIONS`` or a ModelAdmin says, so
#: being staff is never enough to edit an account or reassign a token.
#: ``settings.AUTH_USER_MODEL`` is always included.
ALWAYS_CHECKED_MODELS = frozenset(
    {
        "auth.group",
        "auth.permission",
        "smallstack.apitoken",
        "admin.logentry",
        "access.accessevent",
        "access.managedgroup",
    }
)


def always_checks_permissions(model: type[Model]) -> bool:
    """Whether ``model`` is one of :data:`ALWAYS_CHECKED_MODELS` (or the user model)."""
    from django.conf import settings

    label = model._meta.label_lower
    return label in ALWAYS_CHECKED_MODELS or label == settings.AUTH_USER_MODEL.lower()


def model_checks_permissions(model: type[Model]) -> bool:
    """Whether reading ``model`` anywhere needs its ``view`` permission: it is
    always checked, or the CRUDView that serves it sets ``model_permissions``."""
    if always_checks_permissions(model):
        return True
    from .crud import CRUDView

    view = CRUDView._registry.get(model)
    try:
        return bool(view is not None and view.uses_model_permissions())
    except Exception:  # noqa: BLE001 — a broken view must not open its rows
        return True
