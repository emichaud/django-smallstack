"""Access control records: the audit trail of who may do what, and the groups
an app declares in code.

Django's Groups and Permissions stay the source of truth for access. This app
adds the two things they lack: a durable, typed record of every change to
them (``AccessEvent``), and a way for an app to ship a group with its
permissions and keep it in step (``ManagedGroup``, declared with
``register_group``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


class AccessEvent(models.Model):
    """One change to someone's access, from whatever surface made it.

    Written by the signal receivers in :mod:`apps.access.signals`, so a change
    made in Django admin, the Access pages, the User Manager, a shell or a
    directory sync is recorded the same way. Names are stored as text beside
    the foreign keys so the record outlives a deleted user or group.
    """

    class Kind(models.TextChoices):
        GROUP_ADDED = "group_added", "Added to group"
        GROUP_REMOVED = "group_removed", "Removed from group"
        PERMISSION_ADDED = "permission_added", "Permission granted directly"
        PERMISSION_REMOVED = "permission_removed", "Direct permission removed"
        GROUP_PERMISSION_ADDED = "group_permission_added", "Permission added to group"
        GROUP_PERMISSION_REMOVED = "group_permission_removed", "Permission removed from group"
        STAFF_ON = "staff_on", "Made staff"
        STAFF_OFF = "staff_off", "Staff removed"
        SUPERUSER_ON = "superuser_on", "Made superuser"
        SUPERUSER_OFF = "superuser_off", "Superuser removed"
        ACTIVATED = "activated", "Account activated"
        DEACTIVATED = "deactivated", "Account deactivated"
        TOKEN_REVOKED = "token_revoked", "API token revoked"
        SESSIONS_ENDED = "sessions_ended", "Sessions ended"
        GROUP_CREATED = "group_created", "Group created"
        GROUP_DELETED = "group_deleted", "Group deleted"
        GROUP_RENAMED = "group_renamed", "Group renamed"
        USER_CREATED = "user_created", "Account created"
        USER_DELETED = "user_deleted", "Account deleted"

    #: Kinds that widen access. They log at WARNING and head the review list.
    GRANTS = frozenset(
        {
            Kind.GROUP_ADDED,
            Kind.PERMISSION_ADDED,
            Kind.GROUP_PERMISSION_ADDED,
            Kind.STAFF_ON,
            Kind.SUPERUSER_ON,
            Kind.ACTIVATED,
        }
    )

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_changes_made",
    )
    actor_label = models.CharField(max_length=150, blank=True)
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_events",
    )
    subject_label = models.CharField(max_length=150, blank=True, db_index=True)
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="access_events")
    group_label = models.CharField(max_length=150, blank=True, db_index=True)
    #: ``app_label.codename`` for permission events.
    permission = models.CharField(max_length=200, blank=True, db_index=True)
    #: Where the change came from: ``web:<path>``, ``shell``, ``migrate``,
    #: ``directory:<provider>``, ``system``.
    source = models.CharField(max_length=200, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at", "-pk"]
        verbose_name = "access event"
        verbose_name_plural = "access events"

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.subject_label or self.group_label}"

    @property
    def is_grant(self) -> bool:
        return self.kind in self.GRANTS

    @property
    def object_label(self) -> str:
        """What the event is about: the group, the permission, or the account."""
        if self.permission:
            return self.permission
        if self.group_label and self.subject_label:
            return self.group_label
        return self.group_label or self.subject_label


class ManagedGroup(models.Model):
    """A group an app declares in code with ``register_group``.

    ``declared_permissions`` is what the declaration said at the last sync, so
    the next sync can tell a permission the code dropped (removed from the
    group) from one an administrator added by hand (kept).
    """

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="managed")
    description = models.CharField(max_length=300, blank=True)
    #: The app whose ``groups.py`` declared it.
    app_label = models.CharField(max_length=100, blank=True)
    declared_permissions = models.JSONField(default=list, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["group__name"]

    def __str__(self) -> str:
        return self.group.name

    def drift(self) -> dict[str, list[str]]:
        """Permissions on the group that differ from the declaration:
        ``{"added": [...], "missing": [...]}`` as ``app_label.codename``."""
        current = {
            f"{p.content_type.app_label}.{p.codename}" for p in self.group.permissions.select_related("content_type")
        }
        declared = set(self.declared_permissions or [])
        return {"added": sorted(current - declared), "missing": sorted(declared - current)}

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group.name,
            "app_label": self.app_label,
            "description": self.description,
            "declared_permissions": list(self.declared_permissions or []),
        }
