"""Groups and access checks an app declares in code.

``register_group`` in an app's ``groups.py`` (imported for every installed
app at startup) ships a Django Group with its permissions, created after each
``migrate`` and kept in step: a permission the code adds is added, one the
code drops is removed, one an administrator added by hand is kept.

``register_check`` in an app's ``access_checks.py`` adds a least-privilege
finding to the Access overview, the report command and the exports, beside
the built-in ones in :mod:`apps.access.checks`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from django.contrib.auth.models import Group, Permission

logger = logging.getLogger(__name__)

#: What a directory role key may look like: the value an identity provider
#: puts in a token claim. Entra app-role values allow no spaces; keeping to
#: this everywhere makes one key work for every provider.
DIRECTORY_ROLE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


@dataclass(frozen=True)
class GroupSpec:
    name: str
    permissions: tuple[str, ...]
    description: str = ""
    app_label: str = ""
    #: The stable key the directory sends for this group (``Events.Planner``);
    #: "" for a group whose membership is managed here.
    directory_role: str = ""
    #: Members of this group are staff (the sync sets ``is_staff``).
    staff: bool = False


_groups: dict[str, GroupSpec] = {}
#: ``map_directory_role`` overlays, by group name: (role, staff or None to keep).
_role_overlays: dict[str, tuple[str, bool | None]] = {}


def validate_directory_role(value: str) -> str:
    """``value`` stripped, or ``ValueError`` when it isn't a usable role key."""
    value = (value or "").strip()
    if value and not DIRECTORY_ROLE_PATTERN.match(value):
        raise ValueError(
            f"directory_role {value!r} must be 1-100 of letters, digits, '.', '_' or '-' (no spaces): "
            "it is the value an identity provider puts in a token claim."
        )
    return value


def _check_role_unique(name: str, role: str) -> None:
    if not role:
        return
    for spec in declared_groups():
        if spec.directory_role == role and spec.name != name:
            raise ValueError(f"directory_role {role!r} is already declared by group {spec.name!r}.")


def register_group(
    name: str,
    *,
    permissions: Iterable[str],
    description: str = "",
    app_label: str = "",
    directory_role: str = "",
    staff: bool = False,
) -> GroupSpec:
    """Declare a group. ``permissions`` are ``app_label.codename`` strings.
    Re-registering the same name replaces the declaration (the last import wins).

    ``directory_role`` makes the group directory-managed: its membership is
    set at sign-in from the roles the identity provider sends (see
    :mod:`apps.access.directory`) and can't be changed here. ``staff=True``
    says members are staff; the sync sets the flag when it adds one."""
    role = validate_directory_role(directory_role)
    _check_role_unique(name, role)
    spec = GroupSpec(
        name=name,
        permissions=tuple(dict.fromkeys(permissions)),
        description=description,
        app_label=app_label,
        directory_role=role,
        staff=staff,
    )
    _groups[name] = spec
    return spec


def map_directory_role(group_name: str, directory_role: str, *, staff: bool | None = None) -> None:
    """Give a group declared elsewhere (one SmallStack ships, say) a directory
    role without re-declaring its permissions, so the declaration stays
    upstream's and the mapping doesn't depend on import order::

        map_directory_role("Access reviewer", "Access.Reviewer")

    Applied when the groups are read; a name no declaration matches is
    reported by ``sync_groups``."""
    role = validate_directory_role(directory_role)
    _role_overlays[group_name] = (role, staff)
    _check_role_unique(group_name, role)


def declared_groups() -> list[GroupSpec]:
    """Every declaration, with ``map_directory_role`` overlays applied."""
    specs = []
    for spec in _groups.values():
        overlay = _role_overlays.get(spec.name)
        if overlay is not None:
            role, staff = overlay
            spec = replace(spec, directory_role=role, staff=spec.staff if staff is None else staff)
        specs.append(spec)
    return sorted(specs, key=lambda g: g.name.lower())


def unmatched_overlays() -> list[str]:
    """Group names ``map_directory_role`` named that no declaration matches."""
    return sorted(name for name in _role_overlays if name not in _groups)


def resolve_permissions(names: Iterable[str]) -> tuple[dict[str, Permission], list[str]]:
    """``app_label.codename`` strings → Permission rows, and the names that
    match nothing (a typo, or an app that isn't installed)."""
    found: dict[str, Permission] = {}
    missing: list[str] = []
    wanted = list(names)
    by_app: dict[str, set[str]] = {}
    for name in wanted:
        app, _, codename = name.partition(".")
        by_app.setdefault(app, set()).add(codename)
    for app, codenames in by_app.items():
        for perm in Permission.objects.filter(content_type__app_label=app, codename__in=codenames).select_related(
            "content_type"
        ):
            found[f"{app}.{perm.codename}"] = perm
    for name in wanted:
        if name not in found:
            missing.append(name)
    return found, missing


def sync_groups(*, source: str = "migrate") -> dict[str, Any]:
    """Create and update every declared group. Returns a summary.

    Removes only a permission the declaration itself dropped (so one an
    administrator added by hand is kept, and shows as drift), and never
    deletes a group: a declaration that disappears leaves its group in place,
    marked as no longer declared on the Access pages. The sync doesn't know
    who added a permission, though: if an administrator added one by hand
    that the code later declares and then drops again, the sync removes it.

    A declared name with no matching permission (a typo, or an app not yet
    migrated) is logged, returned under ``missing_permissions`` and kept in
    the stored declaration, so the group shows it as missing drift.
    """
    from .context import acting_as
    from .models import ManagedGroup

    summary: dict[str, Any] = {
        "created": [],
        "updated": [],
        "missing_permissions": {},
        "unmatched_overlays": unmatched_overlays(),
    }
    for name in summary["unmatched_overlays"]:
        logger.warning("access: map_directory_role(%r, …) names a group no declaration matches", name)
    with acting_as(None, source):
        for spec in declared_groups():
            group, created = Group.objects.get_or_create(name=spec.name)
            managed, _ = ManagedGroup.objects.get_or_create(group=group)
            perms, missing = resolve_permissions(spec.permissions)
            if missing:
                summary["missing_permissions"][spec.name] = missing
                logger.warning(
                    "access: group %r declares permissions that don't exist: %s", spec.name, ", ".join(missing)
                )
            declared_now = set(perms) | set(missing)
            declared_before = set(managed.declared_permissions or [])
            current = {
                f"{p.content_type.app_label}.{p.codename}": p for p in group.permissions.select_related("content_type")
            }
            to_add = [perms[n] for n in declared_now if n in perms and n not in current]
            to_remove = [current[n] for n in declared_before - declared_now if n in current]
            if to_add:
                group.permissions.add(*to_add)
            if to_remove:
                group.permissions.remove(*to_remove)
            managed.description = spec.description
            managed.app_label = spec.app_label
            managed.declared_permissions = sorted(declared_now)
            managed.directory_role = spec.directory_role or None
            managed.grants_staff = spec.staff
            managed.save()
            (summary["created"] if created else summary["updated"]).append(spec.name)
    return summary


# --- Checks -------------------------------------------------------------------

Severity = str  # "ok" | "info" | "warning" | "danger"


@dataclass
class Finding:
    """One least-privilege finding on the Access overview.

    ``rows`` are the items behind the number, each ``{"label", "href", "meta"}``,
    shown in the drill-down and written to the report.
    """

    key: str
    title: str
    severity: Severity
    count: int
    summary: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    advice: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "severity": self.severity,
            "count": self.count,
            "summary": self.summary,
            "advice": self.advice,
            "rows": [{"label": r.get("label", ""), "meta": r.get("meta", "")} for r in self.rows],
        }


CheckFn = Callable[[], Finding]
_checks: dict[str, CheckFn] = {}


def register_check(fn: CheckFn) -> CheckFn:
    """Register a finding. The function takes nothing and returns a
    :class:`Finding`; its ``key`` must be unique. Usable as a decorator."""
    _checks[fn.__name__] = fn
    return fn


def run_checks() -> list[Finding]:
    """Every finding, worst first. A check that raises becomes a finding of
    its own rather than taking the page down."""
    order = {"danger": 0, "warning": 1, "info": 2, "ok": 3}
    findings: list[Finding] = []
    for name, fn in _checks.items():
        try:
            findings.append(fn())
        except Exception as exc:
            logger.exception("access: check %s failed", name)
            findings.append(
                Finding(key=name, title=name, severity="warning", count=0, summary=f"This check failed: {exc}")
            )
    findings.sort(key=lambda f: (order.get(f.severity, 9), f.title))
    return findings
