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

logger = logging.getLogger("smallstack.datasets")

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
    # Where a row's object can be viewed. ``None`` (default) resolves
    # generically — the model's CRUDView detail route, else its
    # ``get_absolute_url()``; a callable ``(obj) -> str | None`` or a URL route
    # name (reversed with ``pk=``) overrides that; ``False`` opts out. The
    # resolved URL rides on every row as the ``url`` key (see Dataset.link_for).
    link: Any = None

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
    """
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
            )
        )
        return fn

    return decorator


def get_def(key: str) -> Optional["DatasetDef"]:
    return _dataset_registry.get(key)


def all_defs() -> Iterator["DatasetDef"]:
    return iter(_dataset_registry.values())


def unregister(key: str) -> None:
    """Test helper — remove a dataset from the registry."""
    _dataset_registry.pop(key, None)
