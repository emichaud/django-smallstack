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
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete, pre_save
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
    if action not in ("post_add", "post_remove", "pre_clear"):
        return
    kind = Kind.PERMISSION_REMOVED if action in ("post_remove", "pre_clear") else Kind.PERMISSION_ADDED
    if reverse:  # perm.user_set.add(user): instance is the permission
        name = f"{instance.content_type.app_label}.{instance.codename}"
        users = User.objects.filter(pk__in=pk_set) if pk_set is not None else instance.user_set.all()
        for user in users:
            record(kind, subject=user, permission=name)
        return
    pks = pk_set if pk_set is not None else set(instance.user_permissions.values_list("pk", flat=True))
    for name in _perm_names(pks):
        record(kind, subject=instance, permission=name)


@receiver(m2m_changed, sender=Group.permissions.through, dispatch_uid="access_group_permissions")
def _group_permissions_changed(
    sender: Any, instance: Any, action: str, reverse: bool, pk_set: set[Any] | None, **kwargs: Any
) -> None:
    if action not in ("post_add", "post_remove", "pre_clear"):
        return
    kind = Kind.GROUP_PERMISSION_REMOVED if action in ("post_remove", "pre_clear") else Kind.GROUP_PERMISSION_ADDED
    if reverse:  # perm.group_set.add(group): instance is the permission
        name = f"{instance.content_type.app_label}.{instance.codename}"
        groups = Group.objects.filter(pk__in=pk_set) if pk_set is not None else instance.group_set.all()
        for group in groups:
            record(kind, group=group, permission=name)
        return
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
    name = instance.get_username()
    record(Kind.USER_DELETED, subject=None, subject_label=name, detail={"username": name, "pk": instance.pk})


@receiver(pre_save, sender=Group, dispatch_uid="access_group_name_before")
def _remember_group_name(sender: Any, instance: Group, raw: bool = False, **kwargs: Any) -> None:
    before = Group.objects.filter(pk=instance.pk).values_list("name", flat=True).first() if instance.pk else None
    setattr(instance, "_access_name_before", before)


@receiver(post_save, sender=Group, dispatch_uid="access_group_created")
def _group_created(sender: Any, instance: Group, created: bool, raw: bool = False, **kwargs: Any) -> None:
    if raw:
        return
    if created:
        record(Kind.GROUP_CREATED, group=instance)
        return
    before = getattr(instance, "_access_name_before", None)
    if before is not None and before != instance.name:
        record(Kind.GROUP_RENAMED, group=instance, detail={"from": before, "to": instance.name})


@receiver(pre_delete, sender=Group, dispatch_uid="access_group_members_removed")
def _group_members_removed(sender: Any, instance: Group, **kwargs: Any) -> None:
    """Deleting a group drops its members' rows without an m2m signal: record
    each account's removal while the members can still be read."""
    for user in instance.user_set.all():
        record(Kind.GROUP_REMOVED, subject=user, group=None, group_label=instance.name, detail={"group_deleted": True})


@receiver(post_delete, sender=Group, dispatch_uid="access_group_deleted")
def _group_deleted(sender: Any, instance: Group, **kwargs: Any) -> None:
    record(
        Kind.GROUP_DELETED, group=None, group_label=instance.name, detail={"group": instance.name, "pk": instance.pk}
    )


def revoke_access(user: Any) -> dict[str, int]:
    """Revoke a deactivated account's API tokens and end its sessions.

    Returns the counts. Called when ``is_active`` flips to False; safe to call
    again (nothing left to revoke records nothing).
    """
    from apps.smallstack.models import APIToken

    revoked = 0
    for token in APIToken.objects.filter(user=user, is_active=True):
        token.revoke()  # recorded by _record_token_revoked
        revoked += 1

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


# --- API tokens ---------------------------------------------------------------
# A token going from active to inactive is recorded once, with the actor, on
# every path that saves the row: the Token Manager's Revoke, the Access page's
# "revoke all access", deactivation, Django admin's action and change form,
# Explorer's edit, REST logout, OAuth /revoke and ``sc token revoke``.
# ``QuerySet.update()`` bypasses it, like every signal here.


def _remember_token_active(
    sender: Any, instance: Any, raw: bool = False, update_fields: Any = None, **kwargs: Any
) -> None:
    if raw or not instance.pk:
        return
    if update_fields is not None and "is_active" not in update_fields:
        return  # a usage stamp (last_used_at, request_count): no extra query
    instance._access_token_was_active = (
        sender.objects.filter(pk=instance.pk).values_list("is_active", flat=True).first()
    )


def _record_token_revoked(sender: Any, instance: Any, created: bool, raw: bool = False, **kwargs: Any) -> None:
    if raw or created:
        return
    was_active = getattr(instance, "_access_token_was_active", None)
    instance._access_token_was_active = None
    if was_active and not instance.is_active:
        record(
            Kind.TOKEN_REVOKED,
            subject=instance.user,
            detail={"token": instance.name, "prefix": instance.prefix, "token_id": instance.pk},
        )


pre_save.connect(_remember_token_active, sender="smallstack.APIToken", dispatch_uid="access_token_active_before")
post_save.connect(_record_token_revoked, sender="smallstack.APIToken", dispatch_uid="access_token_revoked")
