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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from django.contrib.auth.models import Group, Permission

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupSpec:
    name: str
    permissions: tuple[str, ...]
    description: str = ""
    app_label: str = ""


_groups: dict[str, GroupSpec] = {}


def register_group(name: str, *, permissions: Iterable[str], description: str = "", app_label: str = "") -> GroupSpec:
    """Declare a group. ``permissions`` are ``app_label.codename`` strings.
    Re-registering the same name replaces the declaration (the last import wins)."""
    spec = GroupSpec(
        name=name, permissions=tuple(dict.fromkeys(permissions)), description=description, app_label=app_label
    )
    _groups[name] = spec
    return spec


def declared_groups() -> list[GroupSpec]:
    return sorted(_groups.values(), key=lambda g: g.name.lower())


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

    summary: dict[str, Any] = {"created": [], "updated": [], "missing_permissions": {}}
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
