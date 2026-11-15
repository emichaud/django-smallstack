"""Record every change to access, wherever it is made.

These receivers watch the Django models that hold access (the user's groups,
permissions and flags; a group's permissions) so a change made in Django
admin, the Access pages, the User Manager, a shell or a directory sync is
recorded the same way. Deactivating an account also revokes its API tokens
and ends its sessions: an account that may not sign in must not keep working
through a token minted earlier.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import AccessEvent
from .record import record

User = get_user_model()
Kind = AccessEvent.Kind

_FLAG_EVENTS = {
    "is_staff": (Kind.STAFF_ON, Kind.STAFF_OFF),
    "is_superuser": (Kind.SUPERUSER_ON, Kind.SUPERUSER_OFF),
    "is_active": (Kind.ACTIVATED, Kind.DEACTIVATED),
}


def _perm_names(pks: set[Any]) -> list[str]:
    return [
        f"{p.content_type.app_label}.{p.codename}"
        for p in Permission.objects.filter(pk__in=pks).select_related("content_type").order_by("pk")
    ]


@receiver(m2m_changed, sender=User.groups.through, dispatch_uid="access_user_groups")
def _user_groups_changed(
    sender: Any, instance: Any, action: str, reverse: bool, pk_set: set[Any] | None, **kwargs: Any
) -> None:
    if action not in ("post_add", "post_remove", "pre_clear"):
        return
    kind = Kind.GROUP_REMOVED if action in ("post_remove", "pre_clear") else Kind.GROUP_ADDED
    if reverse:  # group.user_set.add(user): instance is the group
        users = User.objects.filter(pk__in=pk_set) if pk_set is not None else instance.user_set.all()
        for user in users:
            record(kind, subject=user, group=instance)
        return
    groups = Group.objects.filter(pk__in=pk_set) if pk_set is not None else instance.groups.all()
    for group in groups:
        record(kind, subject=instance, group=group)


@receiver(m2m_changed, sender=User.user_permissions.through, dispatch_uid="access_user_permissions")
def _user_permissions_changed(
    sender: Any, instance: Any, action: str, reverse: bool, pk_set: set[Any] | None, **kwargs: Any
) -> None:
    if action not in ("post_add", "post_remove", "pre_clear") or reverse:
        return
    kind = Kind.PERMISSION_REMOVED if action in ("post_remove", "pre_clear") else Kind.PERMISSION_ADDED
    pks = pk_set if pk_set is not None else set(instance.user_permissions.values_list("pk", flat=True))
    for name in _perm_names(pks):
        record(kind, subject=instance, permission=name)


@receiver(m2m_changed, sender=Group.permissions.through, dispatch_uid="access_group_permissions")
def _group_permissions_changed(
    sender: Any, instance: Any, action: str, reverse: bool, pk_set: set[Any] | None, **kwargs: Any
) -> None:
    if action not in ("post_add", "post_remove", "pre_clear") or reverse:
        return
    kind = Kind.GROUP_PERMISSION_REMOVED if action in ("post_remove", "pre_clear") else Kind.GROUP_PERMISSION_ADDED
    pks = pk_set if pk_set is not None else set(instance.permissions.values_list("pk", flat=True))
    for name in _perm_names(pks):
        record(kind, group=instance, permission=name)


@receiver(pre_save, sender=User, dispatch_uid="access_user_flags_before")
def _remember_flags(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Keep the stored flags on the instance so post_save can see what flipped."""
    if instance.pk is None:
        instance._access_flags_before = None
        return
    before = User.objects.filter(pk=instance.pk).values("is_staff", "is_superuser", "is_active").first()
    instance._access_flags_before = before


@receiver(post_save, sender=User, dispatch_uid="access_user_flags_after")
def _record_flags(sender: Any, instance: Any, created: bool, raw: bool = False, **kwargs: Any) -> None:
    if raw:
        return
    if created:
        record(
            Kind.USER_CREATED,
            subject=instance,
            detail={"is_staff": instance.is_staff, "is_superuser": instance.is_superuser},
        )
        for field, (on, _off) in _FLAG_EVENTS.items():
            if field != "is_active" and getattr(instance, field):
                record(on, subject=instance)
        return
    before = getattr(instance, "_access_flags_before", None)
    if not before:
        return
    for field, (on, off) in _FLAG_EVENTS.items():
        now_value = bool(getattr(instance, field))
        if now_value != bool(before[field]):
            record(on if now_value else off, subject=instance)
            if field == "is_active" and not now_value:
                revoke_access(instance)


@receiver(post_delete, sender=User, dispatch_uid="access_user_deleted")
def _user_deleted(sender: Any, instance: Any, **kwargs: Any) -> None:
    record(Kind.USER_DELETED, subject=None, detail={"username": instance.get_username(), "pk": instance.pk})


@receiver(post_save, sender=Group, dispatch_uid="access_group_created")
def _group_created(sender: Any, instance: Group, created: bool, raw: bool = False, **kwargs: Any) -> None:
    if created and not raw:
        record(Kind.GROUP_CREATED, group=instance)


@receiver(post_delete, sender=Group, dispatch_uid="access_group_deleted")
def _group_deleted(sender: Any, instance: Group, **kwargs: Any) -> None:
    record(Kind.GROUP_DELETED, group=None, detail={"group": instance.name, "pk": instance.pk})


def revoke_access(user: Any) -> dict[str, int]:
    """Revoke a deactivated account's API tokens and end its sessions.

    Returns the counts. Called when ``is_active`` flips to False; safe to call
    again (nothing left to revoke records nothing).
    """
    from apps.smallstack.models import APIToken

    revoked = 0
    for token in APIToken.objects.filter(user=user, is_active=True):
        token.revoke()
        revoked += 1
        record(Kind.TOKEN_REVOKED, subject=user, detail={"token": token.name, "prefix": token.prefix})

    ended = 0
    user_pk = str(user.pk)
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        try:
            if session.get_decoded().get("_auth_user_id") == user_pk:
                session.delete()
                ended += 1
        except Exception:  # noqa: BLE001 — an undecodable session isn't this user's
            continue
    if ended:
        record(Kind.SESSIONS_ENDED, subject=user, detail={"count": ended})
    return {"tokens": revoked, "sessions": ended}
