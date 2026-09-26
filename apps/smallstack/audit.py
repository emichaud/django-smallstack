"""
Audit utilities using Django's built-in LogEntry model.

Provides log_action() for creating audit records from non-admin code,
and AuditMixin for automatic audit logging in class-based views.

Usage:
    from apps.smallstack.audit import log_action, ADDITION, CHANGE, DELETION

    # Manual logging
    log_action(request.user, obj, CHANGE, "Updated status to closed")

    # Automatic logging in CBVs
    class TicketUpdateView(AuditMixin, LoginRequiredMixin, UpdateView):
        model = Ticket
        fields = ["status", "priority"]
"""

import logging

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)

# Re-export for convenience
__all__ = [
    "log_action",
    "log_write",
    "log_system_write",
    "system_audit_user",
    "AuditMixin",
    "ADDITION",
    "CHANGE",
    "DELETION",
]


def log_action(user, obj, action_flag, message=""):
    """
    Create a LogEntry record, the same way Django admin does internally.

    Args:
        user: The user performing the action.
        obj: The model instance being acted on.
        action_flag: ADDITION, CHANGE, or DELETION.
        message: Optional description of what changed.

    Returns:
        The created LogEntry instance.
    """
    ct = ContentType.objects.get_for_model(obj)
    # Construct the LogEntry directly rather than via the manager's log_action()
    # helper, which Django 6.0 removed (replaced by the batch log_actions()).
    # Creating the row directly is equivalent and version-stable.
    entry = LogEntry.objects.create(
        user_id=user.pk,
        content_type_id=ct.pk,
        object_id=str(obj.pk),
        object_repr=str(obj)[:200],
        action_flag=action_flag,
        change_message=message,
    )
    logger.debug(
        "Audit: user=%s action=%s obj=%s.%s pk=%s %s",
        user,
        {ADDITION: "add", CHANGE: "change", DELETION: "delete"}.get(action_flag, "?"),
        ct.app_label,
        ct.model,
        obj.pk,
        message,
    )
    return entry


def log_write(user, obj, action_flag, source=""):
    """Best-effort audit log for a programmatic write (REST API / MCP tools).

    Unlike :func:`log_action`, this NEVER raises — audit logging must not break
    the write it records — and it no-ops when there's no real acting user
    (e.g. an anonymous/session-less context). ``source`` labels the channel
    ("REST API", "MCP") in the change message. (Audit L9.)
    """
    try:
        if getattr(user, "pk", None) is None:
            return None
        return log_action(user, obj, action_flag, f"via {source}" if source else "")
    except Exception:
        logger.exception("Audit log_write failed for %r", obj)
        return None


def system_audit_user():
    """The reserved account system-caused writes are attributed to.

    ``LogEntry.user`` is a non-null FK, so a write that no human caused (an
    expiry sweep, a scheduled job) had no way to leave a durable audit row at
    all — the trail simply ended. This returns (creating on first use) a
    deactivated, non-staff, password-less account named by
    ``SMALLSTACK_AUDIT_SYSTEM_USERNAME``. It is deliberately ``is_active=False``:
    nothing can authenticate as it on any surface (web login, API token, MCP),
    so it is a label, not a credential.

    Returns ``None`` — and the caller skips logging — when the setting is blank.
    """
    from django.conf import settings
    from django.contrib.auth import get_user_model

    username = getattr(settings, "SMALLSTACK_AUDIT_SYSTEM_USERNAME", "system")
    if not username:
        return None
    User = get_user_model()
    user = User.objects.filter(username=username).first()
    if user is not None:
        return user
    user = User(username=username, is_active=False, is_staff=False, is_superuser=False)
    user.set_unusable_password()
    user.save()
    return user


def log_system_write(obj, action_flag, source=""):
    """Audit a write no human caused (``actor is None``). NEVER raises.

    ``log_write`` no-ops without an acting user, which silently dropped every
    system transition — the expiry of an approval request being the case that
    matters most, since "why was this never approved?" is exactly the question
    an auditor asks. (F-15.)
    """
    try:
        user = system_audit_user()
        if user is None:
            logger.info(
                "Audit: system write on %r (%s) not recorded — "
                "SMALLSTACK_AUDIT_SYSTEM_USERNAME is blank",
                obj,
                source,
            )
            return None
        return log_action(user, obj, action_flag, f"via {source}" if source else "")
    except Exception:
        logger.exception("Audit log_system_write failed for %r", obj)
        return None


class AuditMixin:
    """
    CBV mixin that auto-creates a LogEntry on form_valid().

    Detects create vs update and builds a change message from
    form.changed_data. Place before the Django view class in MRO:

        class MyView(AuditMixin, LoginRequiredMixin, UpdateView):
            ...

    Override get_audit_message(form) to customize the logged message.
    """

    def get_audit_message(self, form):
        """Build the change message for the LogEntry."""
        if form.changed_data:
            return f"Changed {', '.join(form.changed_data)}."
        return ""

    def form_valid(self, form):
        is_new = not form.instance.pk
        response = super().form_valid(form)
        action_flag = ADDITION if is_new else CHANGE
        message = self.get_audit_message(form)
        log_action(self.request.user, self.object, action_flag, message)
        return response
