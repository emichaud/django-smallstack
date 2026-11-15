"""What deleting a row takes with it, for the delete confirmation.

Runs Django's own deletion collector (the one ``Model.delete()`` and Django
admin's confirmation page use) without deleting anything, and summarises the
result per model: how many rows of each would cascade, a few of them by name,
which rows protect the target from being deleted at all and, when asked, which
of the cascaded models the user has no delete permission on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from django.contrib.admin.utils import NestedObjects
from django.db import router
from django.db.models import Model

from .model_permissions import has_model_permission

#: Rows named per model; the rest are counted.
SAMPLE_SIZE = 5


@dataclass
class ModelGroup:
    """Rows of one model that a delete would touch."""

    verbose_name: str
    count: int
    samples: list[str] = field(default_factory=list)

    @property
    def more(self) -> int:
        return max(self.count - len(self.samples), 0)


@dataclass
class DeletionSummary:
    """Everything that goes with one delete. ``cascades`` excludes the row itself."""

    cascades: list[ModelGroup] = field(default_factory=list)
    protected: list[ModelGroup] = field(default_factory=list)
    #: Plural names of cascaded models the user may not delete (only filled
    #: when :func:`summarize_deletion` is given a user to check).
    perms_needed: list[str] = field(default_factory=list)

    @property
    def cascade_count(self) -> int:
        return sum(g.count for g in self.cascades)

    @property
    def blocked(self) -> bool:
        return bool(self.protected or self.perms_needed)


def _group(objs: list[Model] | set[Model], *, names: bool) -> list[ModelGroup]:
    by_model: dict[type[Model], list[Model]] = {}
    for obj in objs:
        by_model.setdefault(type(obj), []).append(obj)
    groups = []
    for model, rows in by_model.items():
        opts = model._meta
        label = opts.verbose_name if len(rows) == 1 else opts.verbose_name_plural
        reprs = sorted(str(o)[:120] for o in rows)
        groups.append(
            ModelGroup(
                verbose_name=str(label),
                count=len(rows),
                samples=reprs[:SAMPLE_SIZE] if names else [],
            )
        )
    groups.sort(key=lambda g: (-g.count, g.verbose_name))
    return groups


def _checked(model: type[Model]) -> bool:
    """Whether a cascaded model's delete permission counts. As in Django admin,
    only models registered with the admin site do: the rest (a profile row, an
    audit row) have no admin page anyone could have been granted access to."""
    from django.contrib import admin

    return admin.site.is_registered(model)


def summarize_deletion(obj: Model, *, user: Any = None, names: bool = True) -> DeletionSummary:
    """What deleting ``obj`` would also delete, and what would stop it.

    ``names=False`` counts the rows without naming them, for a reader who may
    not be entitled to see them. With ``user``, ``perms_needed`` lists the
    cascaded admin-registered models that user holds no delete permission on,
    the check Django admin makes before it lets a delete through.

    Many-to-many link rows (the auto-created ``through`` tables) are left out:
    deleting a row always unlinks it, and listing "user-group relationships"
    tells the reader nothing. Rows of a model with a real ``through`` table
    are listed like any other.
    """
    collector = NestedObjects(using=router.db_for_write(type(obj)))
    collector.collect([obj])
    others: list[Model] = []
    perms_needed: set[str] = set()
    # The stubs type the keys as str; at runtime they are model classes.
    model_objs = cast("dict[type[Model], set[Model]]", collector.model_objs)
    for model, instances in model_objs.items():
        if model._meta.auto_created:
            continue
        rows = [o for o in instances if not (type(o) is type(obj) and o.pk == obj.pk)]
        others.extend(rows)
        if rows and user is not None and _checked(model) and not has_model_permission(user, model, "delete"):
            perms_needed.add(str(model._meta.verbose_name_plural))
    return DeletionSummary(
        cascades=_group(others, names=names),
        protected=_group(collector.protected, names=names),
        perms_needed=sorted(perms_needed),
    )
