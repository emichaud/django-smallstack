"""Defaults an app ships: its own metrics, saved cards, dashboards, reports, goal
lists and playlists, declared as data and kept in step with the app.

An app declares them in a ``dashboard_defaults.py`` module (found at startup, like
``datasets.py``)::

    from apps.dashboards.defaults import Defaults, register_defaults

    register_defaults(Defaults(
        app="support",                                   # the app's label
        metrics=[{"key": "support_open", "name": "Open tickets", "dataset": "support_tickets",
                  "filter_tree": {"field": "status", "op": "=", "value": "open"}}],
        dashboards=[{"slug": "support-overview", "name": "Support",
                     "layout": [{"type": "metric", "metric": "support_open", "x": 0, "y": 0, "w": 3, "h": 2}]}],
    ))

:func:`sync_defaults` (run after every ``migrate``, and by ``manage.py
dashboard_defaults``) brings the rows in line, shared and stamped with where they
came from (``provided_by``, ``provided_key``):

- **Missing** → created, in dependency order (metrics, then cards, then the rest).
- **Unchanged by anyone** and the app's declaration changed → updated.
- **Changed by someone** (the row no longer matches ``provided_hash``) → left as
  it is; the sync reports a newer default, and **Reset to default** applies it.
- **Deleted by someone** → stays deleted (:class:`RemovedDefault`).
- **Its app turned off** → archived and marked ``provided_parked``; back when the
  app is.

People edit a default in place like anything else; nothing is locked.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, cast

from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.db.models import Field

if TYPE_CHECKING:
    from .models import OwnedModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Kind:
    """One kind of default: its model, the field that names it, and the fields
    that define it (what a declaration may set, and what the fingerprint covers)."""

    name: str
    model: str
    ident: str
    fields: tuple[str, ...]


#: In the order they're applied: a card can name a metric, a dashboard a card,
#: a goal list or report a metric, a playlist a dashboard or goal list.
KINDS: tuple[Kind, ...] = (
    Kind(
        "metric",
        "Metric",
        "key",
        (
            "name",
            "description",
            "source",
            "dataset",
            "numerator",
            "denominator",
            "filter_tree",
            "agg",
            "measure",
            "period_field",
            "format",
            "unit",
            "thresholds",
            "tags",
        ),
    ),
    Kind(
        "component",
        "Component",
        "key",
        (
            "name",
            "description",
            "type",
            "metric",
            "dataset",
            "filter_tree",
            "agg",
            "measure",
            "period_field",
            "options",
            "tags",
        ),
    ),
    Kind(
        "dashboard", "Dashboard", "slug", ("name", "description", "layout", "default_period", "refresh_seconds", "tags")
    ),
    Kind("report", "Report", "slug", ("name", "description", "items", "periods", "tags")),
    Kind("goals", "GoalList", "slug", ("name", "description", "default_period", "sections", "tags")),
    Kind("playlist", "Playlist", "slug", ("name", "description", "items", "seconds", "loop", "auto_start", "tags")),
)
KIND_BY_NAME = {k.name: k for k in KINDS}
#: A Defaults field → the kind it holds.
_BUNDLE_FIELDS = {
    "metrics": "metric",
    "components": "component",
    "dashboards": "dashboard",
    "reports": "report",
    "goal_lists": "goals",
    "playlists": "playlist",
}


@dataclass
class Defaults:
    """What one app ships. ``app`` is its label. Each list holds plain dicts in
    the shape the REST API and agents write, each with its ``key`` (metrics,
    cards) or ``slug`` (the rest).

    ``prefix`` (default: the app label) keeps names from colliding across apps:
    keys must start ``<prefix>_`` and slugs ``<prefix>-`` (underscores as
    hyphens); ``prefix=""`` turns the check off. ``auto=False`` keeps the
    bundle out of the after-migrate sync: it's applied only when asked
    (``dashboard_defaults --app``), as the framework's demo is."""

    app: str
    metrics: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    dashboards: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    goal_lists: list[dict[str, Any]] = field(default_factory=list)
    playlists: list[dict[str, Any]] = field(default_factory=list)
    prefix: Optional[str] = None
    auto: bool = True

    def specs(self, kind: str) -> list[dict[str, Any]]:
        attr = next(a for a, k in _BUNDLE_FIELDS.items() if k == kind)
        items: list[dict[str, Any]] = getattr(self, attr)
        if kind == "metric":
            # A rate names two metrics, so it goes after the plain ones.
            items = sorted(items, key=lambda s: s.get("source") == "rate")
        return items

    def spec(self, kind: str, ident: str) -> Optional[dict[str, Any]]:
        field_name = KIND_BY_NAME[kind].ident
        return next((s for s in self.specs(kind) if s.get(field_name) == ident), None)


_REGISTRY: dict[str, Defaults] = {}


def register_defaults(defaults: Defaults) -> None:
    """Register what an app ships (call it from the app's ``dashboard_defaults.py``).
    Registering an app again replaces its bundle. Raises ``ImproperlyConfigured``
    for an app that isn't installed, a declaration without its key or slug, an
    unknown field, or a name outside the app's prefix."""
    try:
        django_apps.get_app_config(defaults.app)
    except LookupError as exc:
        raise ImproperlyConfigured(f"Dashboard defaults for {defaults.app!r}: no installed app has that label") from exc
    problems = _declaration_problems(defaults)
    if problems:
        raise ImproperlyConfigured(f"Dashboard defaults for {defaults.app!r}: " + "; ".join(problems))
    _REGISTRY[defaults.app] = defaults


def registered_defaults() -> dict[str, Defaults]:
    return dict(_REGISTRY)


def unregister_defaults(app: str) -> None:
    """Forget an app's bundle (tests; an app turned off at runtime)."""
    _REGISTRY.pop(app, None)


def _declaration_problems(defaults: Defaults) -> list[str]:
    prefix = defaults.app if defaults.prefix is None else defaults.prefix
    problems: list[str] = []
    for attr, kind_name in _BUNDLE_FIELDS.items():
        kind = KIND_BY_NAME[kind_name]
        seen: set[str] = set()
        for n, spec in enumerate(getattr(defaults, attr)):
            where = f"{attr}[{n}]"
            if not isinstance(spec, dict):
                problems.append(f"{where}: a dict")
                continue
            ident = spec.get(kind.ident)
            if not isinstance(ident, str) or not ident:
                problems.append(f"{where}: needs its {kind.ident}")
                continue
            if ident in seen:
                problems.append(f"{where}: {kind.ident} {ident!r} twice")
            seen.add(ident)
            extra = set(spec) - {kind.ident, *kind.fields}
            if extra:
                problems.append(f"{where}: unknown field(s) {', '.join(sorted(extra))}")
            if prefix:
                want = f"{prefix}_" if kind.ident == "key" else f"{prefix.replace('_', '-')}-"
                if not ident.startswith(want):
                    problems.append(f"{where}: {kind.ident} {ident!r} must start with {want!r}")
    return problems


# -- fingerprints --------------------------------------------------------------


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def spec_fingerprint(kind: Kind, spec: dict[str, Any]) -> str:
    """The declaration as the app wrote it."""
    return _digest({f: spec[f] for f in (kind.ident, *kind.fields) if f in spec})


def row_fingerprint(kind: Kind, obj: Any) -> str:
    """The row's defining fields as they are now. A placed saved card counts by
    its placement only: the design copied into the cell follows the card, and an
    edit to the card isn't an edit to the dashboard."""
    from .components import _PLACEMENT_KEYS

    values: dict[str, Any] = {}
    for name in kind.fields:
        value = getattr(obj, name)
        if name == "layout" and isinstance(value, list):
            value = [
                {k: v for k, v in c.items() if k in _PLACEMENT_KEYS or k == "component"}
                if isinstance(c, dict) and c.get("component")
                else c
                for c in value
            ]
        values[name] = value
    return _digest(values)


# -- applying ------------------------------------------------------------------


@dataclass
class SyncReport:
    """What a sync did, per default: ``(app, kind, key, outcome, detail)``.
    Outcomes: created, updated, current, customised, removed, parked, restored,
    conflict, adopted, error."""

    lines: list[tuple[str, str, str, str, str]] = field(default_factory=list)

    def add(self, app: str, kind: str, key: str, outcome: str, detail: str = "") -> None:
        self.lines.append((app, kind, key, outcome, detail))

    def count(self, outcome: str) -> int:
        return sum(1 for line in self.lines if line[3] == outcome)


def _model(kind: Kind) -> type["OwnedModel"]:
    model: type[OwnedModel] = django_apps.get_model("smallstack_dashboards", kind.model)
    return model


def _find(kind: Kind, app: str, ident: str) -> Any:
    model = _model(kind)
    return model.objects.filter(provided_by=app, provided_key=ident).first()


def _assign(kind: Kind, obj: Any, spec: dict[str, Any]) -> None:
    """Every defining field from *spec*, or the model's default where it says
    nothing, so a field the app drops goes back to empty."""
    model = _model(kind)
    for name in kind.fields:
        value = spec[name] if name in spec else cast(Field, model._meta.get_field(name)).get_default()
        setattr(obj, name, value)


def _apply(kind: Kind, app: str, spec: dict[str, Any], obj: Any = None) -> Any:
    """Create or overwrite one default from *spec* and stamp it."""
    model = _model(kind)
    ident = spec[kind.ident]
    if obj is None:
        obj = model(**{kind.ident: ident})
        obj.owner = None
    _assign(kind, obj, spec)
    obj.provided_by, obj.provided_key = app, ident
    obj.provided_spec = spec_fingerprint(kind, spec)
    with transaction.atomic():
        obj.save()
        obj.refresh_from_db()
        obj.provided_hash = row_fingerprint(kind, obj)
        type(obj).objects.filter(pk=obj.pk).update(provided_hash=obj.provided_hash)
    return obj


def _error_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError) and hasattr(exc, "error_dict"):
        return "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)
    return str(exc)


def sync_defaults(
    apps: Optional[list[str]] = None, *, dry_run: bool = False, restore: bool = False, adopt: bool = False
) -> SyncReport:
    """Bring every registered app's defaults (or *apps*') in line; see the module
    docstring. Bundles registered with ``auto=False`` run only when named in
    *apps*. ``restore`` first forgets which of them people deleted, so they come
    back. ``dry_run`` reports without writing. ``adopt`` takes over a row made
    here that has a default's name (a ``conflict`` otherwise) and makes it match
    the default."""
    from .models import RemovedDefault

    report = SyncReport()
    bundles = [d for d in _REGISTRY.values() if (d.app in apps if apps is not None else d.auto)]
    for bundle in bundles:
        if restore and not dry_run:
            RemovedDefault.objects.filter(app=bundle.app).delete()
        removed = set(RemovedDefault.objects.filter(app=bundle.app).values_list("kind", "key"))
        for kind in KINDS:
            for spec in bundle.specs(kind.name):
                ident = spec[kind.ident]
                if (kind.name, ident) in removed:
                    report.add(bundle.app, kind.name, ident, "removed", "deleted by someone; --restore brings it back")
                    continue
                _sync_one(kind, bundle.app, spec, report, dry_run=dry_run, adopt=adopt)
    if apps is None:
        _park_and_unpark(report, dry_run=dry_run)
    return report


def _sync_one(
    kind: Kind, app: str, spec: dict[str, Any], report: SyncReport, *, dry_run: bool, adopt: bool = False
) -> None:
    ident = spec[kind.ident]
    obj = _find(kind, app, ident)
    try:
        if obj is None:
            taken = _model(kind).objects.filter(**{kind.ident: ident}).first()
            if taken is not None and taken.provided_by:
                report.add(app, kind.name, ident, "conflict", f"{taken.provided_by} ships a {kind.name} with this name")
                return
            if taken is not None and not adopt:
                report.add(app, kind.name, ident, "conflict", f"a {kind.name} with this {kind.ident} already exists")
                return
            if taken is not None:
                if not dry_run:
                    _apply(kind, app, spec, taken)
                report.add(app, kind.name, ident, "adopted", "the existing row now matches the default")
                return
            if not dry_run:
                _apply(kind, app, spec)
            report.add(app, kind.name, ident, "created")
            return
        back = obj.provided_parked
        if back and not dry_run:
            obj.provided_parked = False
            type(obj).objects.filter(pk=obj.pk).update(provided_parked=False, archived_at=None)
        touched = row_fingerprint(kind, obj) != obj.provided_hash
        changed = spec_fingerprint(kind, spec) != obj.provided_spec
        if not changed:
            settled = "customised" if touched else "current"
            report.add(app, kind.name, ident, "restored" if back else settled, "its app is back" if back else "")
        elif touched:
            report.add(app, kind.name, ident, "customised", "a newer default is available: Reset to default applies it")
        else:
            if not dry_run:
                _apply(kind, app, spec, obj)
            report.add(app, kind.name, ident, "updated")
    except (ValidationError, ValueError) as exc:
        report.add(app, kind.name, ident, "error", _error_text(exc))
        logger.warning("dashboard default %s:%s:%s not applied: %s", app, kind.name, ident, exc)


def _park_and_unpark(report: SyncReport, *, dry_run: bool) -> None:
    """Archive the defaults of apps no longer installed; bring back those whose
    app is installed again (rows the bundle no longer names are left alone)."""
    from django.utils import timezone

    for kind in KINDS:
        model = _model(kind)
        for obj in model.objects.exclude(provided_by=""):
            installed = _label_installed(obj.provided_by)
            if not installed and not obj.provided_parked and obj.archived_at is None:
                if not dry_run:
                    model.objects.filter(pk=obj.pk).update(provided_parked=True, archived_at=timezone.now())
                report.add(obj.provided_by, kind.name, obj.provided_key, "parked", "its app is turned off")
            elif installed and obj.provided_parked and obj.provided_by not in _REGISTRY:
                if not dry_run:
                    model.objects.filter(pk=obj.pk).update(provided_parked=False, archived_at=None)
                report.add(obj.provided_by, kind.name, obj.provided_key, "restored", "its app is back")


def _label_installed(label: str) -> bool:
    try:
        django_apps.get_app_config(label)
    except LookupError:
        return False
    return True


# -- one row: its state, and putting it back ---------------------------------------


def kind_of(obj: Any) -> Optional[Kind]:
    return next((k for k in KINDS if k.model == type(obj).__name__), None)


def default_state(obj: Any) -> Optional[dict[str, Any]]:
    """For a row an app ships: ``{app, app_name, customised, newer, shipped}`` —
    whether someone changed it, whether the app now ships a different
    definition, and whether the app still ships it at all. ``None`` for a row
    made here."""
    kind = kind_of(obj)
    if kind is None or not getattr(obj, "provided_by", ""):
        return None
    try:
        app_name = str(django_apps.get_app_config(obj.provided_by).verbose_name)
    except LookupError:
        app_name = obj.provided_by
    bundle = _REGISTRY.get(obj.provided_by)
    spec = bundle.spec(kind.name, obj.provided_key) if bundle else None
    return {
        "app": obj.provided_by,
        "app_name": app_name,
        "customised": row_fingerprint(kind, obj) != obj.provided_hash,
        "newer": spec is not None and spec_fingerprint(kind, spec) != obj.provided_spec,
        "shipped": spec is not None,
    }


def reset_default(obj: Any) -> Any:
    """Put a default back as its app ships it now, over anyone's changes.
    Raises ``LookupError`` when the app no longer ships it, ``ValidationError``
    when the declaration doesn't apply."""
    kind = kind_of(obj)
    bundle = _REGISTRY.get(getattr(obj, "provided_by", ""))
    spec = bundle.spec(kind.name, obj.provided_key) if (bundle and kind) else None
    if kind is None or bundle is None or spec is None:
        raise LookupError("Its app no longer ships this default.")
    return _apply(kind, bundle.app, spec, obj)


def remember_removed(obj: Any) -> None:
    """A default was deleted: the sync leaves it deleted."""
    from .models import RemovedDefault

    kind = kind_of(obj)
    if kind is None or not getattr(obj, "provided_by", ""):
        return
    RemovedDefault.objects.get_or_create(app=obj.provided_by, kind=kind.name, key=obj.provided_key)
