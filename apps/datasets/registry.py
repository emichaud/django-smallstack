"""Dataset registry — the canonical list of ``@dataset`` queryset providers.

A dataset is a named function returning a Django ``QuerySet``. The decorator
registers it here; the registry then drives the picker list (``list_datasets``),
the REST surface, and the opt-in MCP tools. This mirrors ``apps/search/registry``
(first-wins keying + an ``add_register_hook`` seam so datasets declared from a
later app's ``ready()`` still self-expose to MCP, independent of INSTALLED_APPS
ordering).

Only stdlib is imported at module load — no Django models — so importing this
during app-package init is safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger(__name__)

# key -> DatasetDef. First-wins (see register()).
_dataset_registry: dict[str, "DatasetDef"] = {}

# Callbacks fired with each DatasetDef as it registers. Lets order-sensitive
# consumers (the MCP tool factory) react to *late* registrations from another
# app's ready(), instead of only seeing the datasets present at that instant.
_on_register_hooks: list = []


@dataclass
class DatasetDef:
    """A registered dataset: a queryset provider plus its exposure config."""

    key: str
    fn: Callable[..., Any]
    label: str = ""
    description: str = ""
    # Optional explicit columns. Each entry is a field name, or a
    # ``(name, type)`` tuple for a computed/annotated column whose type the
    # model helpers can't infer. None => derive from the queryset's model.
    columns: Optional[list] = None
    # Optional explicit filterable column names (which columns MAY be filtered).
    # None => all columns. This is the *declaration* side; the *runtime* active
    # filter values are the ``filters=`` arg on rows()/series()/scalar().
    filterable: Optional[list] = None
    # Optional declared *ratio* measures, computed in-DB as
    # ``sum(numerator) / sum(denominator)`` per group (never the average of
    # per-row ratios). Each entry: ``(name, numerator, denominator, fmt)`` where
    # ``fmt`` is ``"percent"`` (×100) or ``"ratio"``. Empty denominator → None.
    measures: Optional[list] = None
    enable_api: bool = False
    enable_mcp: bool = False
    # MCP access tier for the generated tool. Secure default: staff-only.
    mcp_access: str = "staff"
    # Who may read this dataset through in-app surfaces that evaluate it on a
    # user's behalf — metrics, dashboards and reports (apps.dashboards).
    # ``"staff"`` (secure default) or ``"auth"`` (any signed-in user; the
    # dataset fn still receives the request for per-user scoping).
    access: str = "staff"
    # Where a row's object can be viewed. ``None`` (default) resolves
    # generically — the model's CRUDView detail route, else its
    # ``get_absolute_url()``; a callable ``(obj) -> str | None`` or a URL route
    # name (reversed with ``pk=``) overrides that; ``False`` opts out. The
    # resolved URL rides on every row as the ``url`` key (see Dataset.link_for).
    link: Any = None
    # Optional semantic units by column name (``{"talk_seconds": "seconds",
    # "fee": "currency"}``), surfaced as each schema column's ``unit`` so a
    # builder offers unit-appropriate formats. Undeclared columns fall back to
    # a name heuristic (``*_seconds`` → seconds, ``*_minutes`` → minutes).
    units: Optional[dict] = None

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.key.replace("_", " ").title()


def add_register_hook(hook: Callable[["DatasetDef"], None]) -> None:
    """Register a callback invoked with each DatasetDef as it registers.

    Idempotent. Fires for *future* register() calls, not retroactively — call
    it after processing the datasets already present.
    """
    if hook not in _on_register_hooks:
        _on_register_hooks.append(hook)


def register(dfn: "DatasetDef") -> "DatasetDef":
    """Register a DatasetDef. First-wins on key (mirrors CRUDView._registry)."""
    existing = _dataset_registry.get(dfn.key)
    if existing is not None:
        logger.warning("dataset %r already registered — keeping the first", dfn.key)
        return existing
    _dataset_registry[dfn.key] = dfn
    for hook in _on_register_hooks:
        try:
            hook(dfn)
        except Exception:
            logger.exception("dataset register hook failed for %s", dfn.key)
    return dfn


def dataset(
    key: str,
    *,
    label: str = "",
    description: str = "",
    columns: Optional[list] = None,
    filterable: Optional[list] = None,
    filters: Optional[list] = None,  # deprecated alias for filterable
    measures: Optional[list] = None,
    enable_api: bool = False,
    enable_mcp: bool = False,
    mcp_access: str = "staff",
    link: Any = None,
    access: str = "staff",
    units: Optional[dict] = None,
) -> Callable[[Callable], Callable]:
    """Decorator: register a function returning a QuerySet as a named dataset.

    Example::

        @dataset("open_tickets", label="Open Tickets",
                 filterable=["status"], enable_mcp=True)
        def open_tickets(request=None):
            return Ticket.objects.filter(status="open")

    The function may take zero args or a single ``request`` arg (used for
    per-request scoping). The model is derived from the returned queryset, so
    no model/CRUDView declaration is needed.

    ``filterable=`` declares which columns MAY be filtered. (The *runtime* active
    filter values are the ``filters=`` arg on ``rows()``/``series()``/``scalar()``.)
    The old ``filters=`` decorator kwarg is a deprecated alias — accepted with a
    ``DeprecationWarning`` — kept for ≥2 minor releases.

    ``link=`` says where a row's object can be viewed. Left at ``None`` the
    framework resolves it: the model's CRUDView detail page, else the model's
    ``get_absolute_url()``. Pass a callable ``(obj) -> str | None``, or a URL
    route name reversed with ``pk=<obj.pk>``, to override; ``link=False`` opts
    out. The result is the ``url`` key on every row (rows, REST, MCP, CSV).

    ``access=`` says who may read the dataset through metrics, dashboards and
    reports: ``"staff"`` (default) or ``"auth"`` (any signed-in user — scope
    rows per user via the ``request`` arg). See :func:`user_may_read`.

    ``units=`` names a column's semantic unit (``"seconds"``, ``"minutes"``,
    ``"currency"``, ``"percent"``, …), shown as the schema column's ``unit``.
    """
    if access not in ACCESS_LEVELS:
        raise ValueError(f"@dataset({key!r}): access must be one of {sorted(ACCESS_LEVELS)}, got {access!r}")
    if filters is not None:
        import warnings

        warnings.warn(
            "@dataset(filters=...) is deprecated; use filterable=... "
            "(the runtime rows()/series()/scalar() filters= arg is unchanged).",
            DeprecationWarning,
            stacklevel=2,
        )
        if filterable is None:
            filterable = filters

    def decorator(fn: Callable) -> Callable:
        register(
            DatasetDef(
                key=key,
                fn=fn,
                label=label,
                description=description,
                columns=columns,
                filterable=filterable,
                measures=measures,
                enable_api=enable_api,
                enable_mcp=enable_mcp,
                mcp_access=mcp_access,
                link=link,
                access=access,
                units=units,
            )
        )
        return fn

    return decorator


#: The in-app read tiers a dataset may declare (see ``DatasetDef.access``).
ACCESS_LEVELS = frozenset({"staff", "auth"})


def user_may_read(dfn: "DatasetDef", user: Any) -> bool:
    """Whether *user* may read *dfn* through an in-app surface (a metric card,
    a dashboard, a report). Staff may, and ``access="auth"`` admits any
    signed-in user, as long as :func:`user_may_view_model` holds. Anonymous
    users never may."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not user_may_view_model(dfn, user):
        return False
    if getattr(user, "is_staff", False):
        return True
    return dfn.access == "auth"


def user_may_view_model(dfn: "DatasetDef", user: Any) -> bool:
    """Whether *user* may see the rows of the model *dfn* reads.

    A dataset over a model that checks Django model permissions (accounts,
    API tokens and the other access models always do; otherwise when the
    model's CRUDView sets ``model_permissions``) needs that model's ``view``
    permission on every dataset surface, staff included, so a dataset can't
    show what the model's own pages refuse. ``user=None`` is a trusted
    internal call. A dataset whose model can't be resolved is refused.
    """
    if user is None:
        return True
    from apps.smallstack.model_permissions import has_model_permission, model_checks_permissions

    from .core import get_dataset

    try:
        ds = get_dataset(dfn.key)
        model = ds.model if ds is not None else None
    except Exception:  # noqa: BLE001 — fail closed
        logger.warning("dataset %r: couldn't resolve its model; refusing", dfn.key, exc_info=True)
        return False
    if model is None:
        return False
    if not model_checks_permissions(model):
        return True
    return has_model_permission(user, model, "view")


def get_def(key: str) -> Optional["DatasetDef"]:
    return _dataset_registry.get(key)


def all_defs() -> Iterator["DatasetDef"]:
    return iter(_dataset_registry.values())


def unregister(key: str) -> None:
    """Test helper — remove a dataset from the registry."""
    _dataset_registry.pop(key, None)
