"""Membership from a directory: the identity provider says who holds which
roles, this module makes the directory-managed groups match.

Every identity provider, whatever the protocol, hands a sign-in two things:
who this is (a stable subject) and a list of role strings (an Entra ``roles``
claim, an Okta ``groups`` claim, a header a proxy forwards). Everything from
that list down is the same for all of them and lives here; reading the claim
is the provider's own ten lines, kept in the project that signs in that way::

    from apps.access.directory import resolve_identity, sync_roles

    identity = resolve_identity("entra", claims["oid"], email=claims["email"], name=claims["name"])
    result = sync_roles(identity, claims.get("roles"), "entra")

Rules:

- A group is directory-managed when its declaration carries a
  ``directory_role`` (``register_group(..., directory_role="Events.Planner")``
  or ``map_directory_role``). The sync sets the user's directory-managed
  groups to exactly the roles sent; it never touches a group without a role.
- ``roles=None`` (the claim is missing) changes nothing: that is a
  misconfiguration, not "this person holds no roles", and stripping everyone
  who signs in that morning is the wrong answer to it. An empty list does
  strip: the directory says they hold nothing.
- The sync may set ``is_staff`` (a group declared ``staff=True``) and never
  unsets it or touches ``is_superuser``; a superuser is a local decision.
- Every change is recorded like any other, with ``directory:<provider>`` as
  the source, through the same signals.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from .context import acting_as
from .models import DirectoryIdentity, ManagedGroup
from .registry import declared_groups

logger = logging.getLogger(__name__)

User = get_user_model()

#: Namespace for the app-role ids the manifest emits: ``uuid5(NAMESPACE, role)``,
#: so a rerun produces the same ids and the provider sees an update, not a
#: second role.
MANIFEST_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://django-smallstack/access/directory-role")


def role_map() -> dict[str, str]:
    """``SMALLSTACK_DIRECTORY_ROLE_MAP``: what the provider sends → the declared
    role, for a provider whose values can't be the key (a Google group email,
    an Okta group that can't be renamed)."""
    mapping = getattr(settings, "SMALLSTACK_DIRECTORY_ROLE_MAP", None) or {}
    return {str(k): str(v) for k, v in dict(mapping).items()}


def normalize_roles(roles: Iterable[Any]) -> list[str]:
    """The claim as the sync compares it: strings, stripped, aliased through
    the role map, de-duplicated in order. Empty values are dropped."""
    aliases = role_map()
    out: list[str] = []
    for raw in roles:
        value = str(raw or "").strip()
        value = aliases.get(value, value)
        if value and value not in out:
            out.append(value)
    return out


def recognised_roles(roles: Iterable[Any] | None) -> list[str]:
    """The roles in ``roles`` (as sent, before the role map) that some
    directory-managed group carries. A sign-in middleware that fails closed
    asks this *before* :func:`sign_in`, so a person holding no recognised role
    gets a 403 without an account being created for them (T2-4)::

        if not recognised_roles(roles):
            return HttpResponseForbidden()
        identity, _ = sign_in(provider, subject, roles, email=email, name=name)
    """
    if roles is None:
        return []
    known = set(directory_groups())
    return [r for r in normalize_roles(roles) if r in known]


def local_override_allowed() -> bool:
    """``SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE``: whether a local administrator
    may change a directory-managed group's membership anyway. Off: the
    directory is the one source of truth."""
    return bool(getattr(settings, "SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE", False))


def directory_groups() -> dict[str, ManagedGroup]:
    """Every directory-managed group, by role."""
    return {
        m.directory_role: m
        for m in ManagedGroup.objects.filter(directory_role__isnull=False).select_related("group")
        if m.directory_role
    }


def providers_seen() -> list[str]:
    """Providers that have signed someone in, for the pages ("membership comes
    from entra")."""
    # order_by() first: Meta.ordering would add user__username to the
    # SELECT DISTINCT and return one row per identity (T2-2).
    return sorted(DirectoryIdentity.objects.order_by().values_list("provider", flat=True).distinct())


# --- Identity -------------------------------------------------------------------

_USERNAME_CLEAN = re.compile(r"[^A-Za-z0-9_.@+-]+")


def _free_username(preferred: str, fallback: str) -> str:
    base = _USERNAME_CLEAN.sub("", preferred or "")[:140] or _USERNAME_CLEAN.sub("", fallback)[:140]
    candidate = base
    n = 2
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f"{base}{n}"
        n += 1
    return candidate


def _split_name(name: str) -> tuple[str, str]:
    first, _, last = (name or "").strip().partition(" ")
    return first[:150], last.strip()[:150]


def resolve_identity(
    provider: str,
    subject: str,
    *,
    email: str = "",
    name: str = "",
    create: bool = True,
) -> DirectoryIdentity | None:
    """The account behind ``(provider, subject)``, created or linked on first
    sight. Returns ``None`` only when ``create=False`` and nothing matches.

    Matching is by subject. On a miss, and when
    ``SMALLSTACK_DIRECTORY_LINK_BY_EMAIL`` is on (default), an existing account
    whose email equals the provider's (one account, no identity for this
    provider yet) is linked, so an account made before single sign-on keeps
    its history; the subject is pinned from then on and a later email change
    doesn't move it. Otherwise a new account is created (unusable password,
    not staff, not superuser), recorded from ``directory:<provider>``.

    Email and display name are refreshed on every call; ``last_seen_at`` is
    stamped by :func:`sync_roles`, which should follow.
    """
    provider = (provider or "").strip().lower()
    subject = (subject or "").strip()
    if not provider or not subject:
        raise ValueError("resolve_identity needs a provider and the provider's subject for the user.")
    email = (email or "").strip()
    source = f"directory:{provider}"
    with transaction.atomic():
        identity = DirectoryIdentity.objects.select_related("user").filter(provider=provider, subject=subject).first()
        if identity is None:
            if not create:
                return None
            user = None
            if email and getattr(settings, "SMALLSTACK_DIRECTORY_LINK_BY_EMAIL", True):
                matches = list(User.objects.filter(email__iexact=email)[:2])
                if len(matches) == 1 and not matches[0].directory_identities.filter(provider=provider).exists():
                    user = matches[0]
                    logger.info("access: %s linked to existing account %s by email", source, user.get_username())
            if user is None:
                first, last = _split_name(name)
                taken = bool(email) and User.objects.filter(email__iexact=email).exists()
                with acting_as(None, source):
                    # password=None → unusable: the directory is the only way in.
                    user = User.objects.create_user(
                        _free_username(email.lower(), f"{provider}-{subject}"),
                        email=None if (taken or not email) else email.lower(),
                        first_name=first,
                        last_name=last,
                    )
                logger.info("access: %s created account %s", source, user.get_username())
            identity = DirectoryIdentity(
                user=user, provider=provider, subject=subject, last_seen_at=timezone.now(), last_roles=[]
            )
        changed: list[str] = []
        if email and identity.email != email:
            identity.email = email
            changed.append("email")
        if name and identity.display_name != name[:150]:
            identity.display_name = name[:150]
            changed.append("display_name")
        if identity.pk is None:
            identity.save()
        elif changed:
            identity.save(update_fields=changed)
    return identity


# --- The sync -------------------------------------------------------------------


@dataclass
class SyncResult:
    """What one sync did. ``skipped`` means the claim was missing and nothing
    was touched."""

    provider: str
    roles: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    staff_granted: bool = False
    skipped: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.staff_granted)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "roles": list(self.roles),
            "added": list(self.added),
            "removed": list(self.removed),
            "unknown": list(self.unknown),
            "staff_granted": self.staff_granted,
            "skipped": self.skipped,
        }


_unknown_logged: set[tuple[str, str]] = set()


def sync_roles(identity: DirectoryIdentity | Any, roles: Iterable[Any] | None, provider: str) -> SyncResult:
    """Set the user's directory-managed groups to exactly ``roles``.

    ``identity`` is a :class:`DirectoryIdentity` (preferred: its
    ``last_seen_at`` and ``last_roles`` are updated) or a user. ``roles`` is
    the claim as sent; ``None`` means the claim was absent and nothing is
    changed (see the module docstring). A role no declared group carries is
    returned under ``unknown``, logged once per process, and kept on the
    identity for the review; it is not an error.

    Groups without a ``directory_role`` are never touched, so a locally
    granted group survives the sync. Changes are made inside
    ``acting_as(None, "directory:<provider>")`` and recorded by the signals.
    """
    provider = (provider or "").strip().lower()
    if not provider:
        raise ValueError("sync_roles needs the provider's name (the <provider> in directory:<provider>).")
    is_identity = isinstance(identity, DirectoryIdentity)
    user: Any = identity.user if isinstance(identity, DirectoryIdentity) else identity
    result = SyncResult(provider=provider)
    if roles is None:
        logger.warning(
            "access: directory:%s sent no roles claim for %s; membership left as it was", provider, user.get_username()
        )
        result.skipped = True
        if is_identity:
            identity.last_seen_at = timezone.now()
            identity.save(update_fields=["last_seen_at"])
        return result

    result.roles = normalize_roles(roles)
    by_role = directory_groups()
    wanted: dict[int, Group] = {}
    grants_staff = False
    for role in result.roles:
        managed = by_role.get(role)
        if managed is None:
            result.unknown.append(role)
            if (provider, role) not in _unknown_logged:
                _unknown_logged.add((provider, role))
                logger.warning("access: directory:%s sent role %r, which no declared group carries", provider, role)
            continue
        wanted[managed.group_id] = managed.group
        grants_staff = grants_staff or managed.grants_staff

    current = {g.pk: g for g in user.groups.filter(managed__directory_role__isnull=False)}
    to_add = [g for pk, g in wanted.items() if pk not in current]
    to_remove = [g for pk, g in current.items() if pk not in wanted]
    with transaction.atomic(), acting_as(None, f"directory:{provider}"):
        if to_add:
            user.groups.add(*to_add)
            result.added = sorted(g.name for g in to_add)
        if to_remove:
            user.groups.remove(*to_remove)
            result.removed = sorted(g.name for g in to_remove)
        if grants_staff and not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
            result.staff_granted = True
        if is_identity:
            identity.last_seen_at = timezone.now()
            identity.last_roles = list(result.roles)
            identity.save(update_fields=["last_seen_at", "last_roles"])
    if result.changed:
        logger.info(
            "access: directory:%s synced %s: +%s -%s%s",
            provider,
            user.get_username(),
            result.added,
            result.removed,
            " staff" if result.staff_granted else "",
        )
    return result


def sign_in(
    provider: str,
    subject: str,
    roles: Iterable[Any] | None,
    *,
    email: str = "",
    name: str = "",
) -> tuple[DirectoryIdentity, SyncResult]:
    """:func:`resolve_identity` then :func:`sync_roles`, the two calls a
    sign-in backend makes, then the account's ``last_login`` is stamped (at
    most every :data:`LAST_LOGIN_EVERY`, since a proxy may call this on every
    request), so a directory user doesn't read as never signed in and the
    dormancy findings see the sign-in (T2-5)."""
    identity = resolve_identity(provider, subject, email=email, name=name)
    assert identity is not None  # create=True
    result = sync_roles(identity, roles, provider)
    _stamp_last_login(identity.user)
    return identity, result


def sign_in_or_refuse(
    provider: str,
    subject: str,
    roles: Iterable[Any] | None,
    *,
    email: str = "",
    name: str = "",
) -> DirectoryIdentity | None:
    """The fail-closed sign-in: the identity to sign in, or ``None`` to refuse.

    - A subject seen before is **always synced first** (G4-4), so a person IT
      removed from every role (``[]``) loses their directory groups now, not
      never; then refused if no recognised role remains.
    - A subject never seen is refused **before** anything is created when no
      recognised role was sent (T2-4), and signed in otherwise.
    - A missing claim (``None``) changes nothing and is refused.
    """
    known = DirectoryIdentity.objects.filter(provider=provider, subject=subject).exists()
    recognised = recognised_roles(roles)
    if not known and not recognised:
        return None
    identity, _result = sign_in(provider, subject, roles, email=email, name=name)
    return identity if recognised else None


#: How stale ``last_login`` may get before :func:`sign_in` writes it again.
LAST_LOGIN_EVERY = timedelta(minutes=15)


def _stamp_last_login(user: Any) -> None:
    now = timezone.now()
    if user.last_login is None or now - user.last_login >= LAST_LOGIN_EVERY:
        # update(): last_login is not an access change, so no signal is wanted.
        type(user).objects.filter(pk=user.pk).update(last_login=now)
        user.last_login = now


# --- The manifest ---------------------------------------------------------------
# What a directory administrator needs to create the roles and groups: one
# formatter per provider, each a few lines. Nothing in it is a secret.


@dataclass(frozen=True)
class ManifestRole:
    role: str
    group: str
    description: str
    staff: bool
    #: The suggested directory group name, from ``SMALLSTACK_DIRECTORY_GROUP_PREFIX``.
    directory_group: str

    @property
    def id(self) -> str:
        return str(uuid.uuid5(MANIFEST_NAMESPACE, self.role))


def group_prefix() -> str:
    prefix = getattr(settings, "SMALLSTACK_DIRECTORY_GROUP_PREFIX", "") or ""
    if not prefix:
        prefix = f"APP - {getattr(settings, 'BRAND_NAME', 'SmallStack')} - "
    return str(prefix)


def manifest_roles() -> list[ManifestRole]:
    """Every directory-managed group, as the manifest lists them: the ones
    declared in code and the ones marked on the Access pages."""
    prefix = group_prefix()
    roles = [
        ManifestRole(
            role=spec.directory_role,
            group=spec.name,
            description=spec.description,
            staff=spec.staff,
            directory_group=f"{prefix}{spec.name}",
        )
        for spec in declared_groups()
        if spec.directory_role
    ]
    for managed in ManagedGroup.objects.filter(
        source=ManagedGroup.Source.PAGE, directory_role__isnull=False
    ).select_related("group"):
        roles.append(
            ManifestRole(
                role=managed.directory_role or "",
                group=managed.group.name,
                description=managed.description or f"Members of {managed.group.name}",
                staff=managed.grants_staff,
                directory_group=f"{prefix}{managed.group.name}",
            )
        )
    return sorted(roles, key=lambda r: r.group.lower())


ManifestFormatter = Callable[[list[ManifestRole]], dict[str, Any]]
_formatters: dict[str, ManifestFormatter] = {}


def register_manifest_formatter(provider: str) -> Callable[[ManifestFormatter], ManifestFormatter]:
    """Add a provider's manifest shape: ``@register_manifest_formatter("okta")``
    on a function taking the :class:`ManifestRole` list and returning the
    JSON the provider's administrator feeds to their tooling."""

    def wrap(fn: ManifestFormatter) -> ManifestFormatter:
        _formatters[provider.lower()] = fn
        return fn

    return wrap


def manifest_providers() -> list[str]:
    return sorted(_formatters)


def manifest(provider: str) -> dict[str, Any]:
    """The manifest for ``provider``; ``LookupError`` names the known ones."""
    fn = _formatters.get((provider or "").lower())
    if fn is None:
        raise LookupError(f"No manifest format {provider!r}. Known: {', '.join(manifest_providers())}.")
    return fn(manifest_roles())


@register_manifest_formatter("generic")
def _generic(roles: list[ManifestRole]) -> dict[str, Any]:
    """The plain list: role key, group, suggested directory group name."""
    return {
        "roles": [
            {
                "role": r.role,
                "group": r.group,
                "description": r.description,
                "staff": r.staff,
                "directory_group": r.directory_group,
            }
            for r in roles
        ]
    }


@register_manifest_formatter("entra")
def _entra(roles: list[ManifestRole]) -> dict[str, Any]:
    """Microsoft Entra: the ``appRoles`` array to PATCH onto the app
    registration (ids stable across reruns), and the security group to create
    and assign to each role. Group-to-role assignment needs Entra ID P1."""
    return {
        "appRoles": [
            {
                "id": r.id,
                "allowedMemberTypes": ["User"],
                "description": r.description or f"Members of the {r.group} group.",
                "displayName": r.group,
                "isEnabled": True,
                "value": r.role,
            }
            for r in roles
        ],
        "groups": [{"displayName": r.directory_group, "role": r.role, "roleId": r.id} for r in roles],
    }
