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
__all__ = ["log_action", "AuditMixin", "ADDITION", "CHANGE", "DELETION"]


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
    entry = LogEntry.objects.log_action(
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
