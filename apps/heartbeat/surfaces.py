"""Enumerate the project's *exposed surfaces* — the things a Site Monitor can watch.

The "Site Monitors" tier monitors surfaces SmallStack itself exposes: REST
resources (``enable_api=True`` CRUDViews, tracked in ``_api_registry``) and MCP
tools (``TOOL_REGISTRY``). This module is the single source of truth for "what is
exposed right now", used by:

- the picker form (its choices are *only* currently-exposed surfaces),
- the monitor source (to detect orphans — a saved monitor whose surface is gone),
- the default presence probe.

A surface is identified by a ``(kind, target)`` pair:

- ``("api", <registry_name>)`` — the reversible URL name stored in ``_api_registry``
  (e.g. ``"widgets-api-list"`` or ``"heartbeat:status-endpoints-api-list"``).
- ``("mcp", <tool_name>)`` — the tool's key in ``TOOL_REGISTRY``.

Everything here is cheap + in-process (it reads module-level registries, runs no
queries) so it's safe on page render and in the per-minute loop.
"""

from __future__ import annotations

from dataclasses import dataclass

# Human labels for the two surface kinds (used in the picker's optgroups).
KIND_LABELS: dict[str, str] = {"api": "API endpoints", "mcp": "MCP tools"}


@dataclass(frozen=True)
class Surface:
    """One exposed surface that a Site Monitor can watch."""

    kind: str  # "api" | "mcp"
    target: str  # registry name (api) or tool name (mcp)
    label: str  # display name, e.g. "Widget" or "search_widgets"
    meta: str = ""  # one-line context (verbose-name-plural / tool description)
    url: str | None = None  # deep-link, when one resolves

    @property
    def value(self) -> str:
        """The form-choice value, ``"<kind>:<target>"`` (parsed back in clean())."""
        return f"{self.kind}:{self.target}"


def _api_surfaces() -> list[Surface]:
    """REST resources exposed by ``enable_api=True`` CRUDViews."""
    from django.urls import NoReverseMatch, reverse

    from apps.smallstack.api import _api_registry

    surfaces: list[Surface] = []
    for cfg, name in _api_registry:
        try:
            url = reverse(name)
        except NoReverseMatch:
            url = None
        surfaces.append(
            Surface(
                kind="api",
                target=name,
                label=cfg.model.__name__,
                meta=str(cfg.model._meta.verbose_name_plural),
                url=url,
            )
        )
    return surfaces


def _mcp_surfaces() -> list[Surface]:
    """MCP tools registered with the server."""
    try:
        from apps.mcp.server import TOOL_REGISTRY
    except Exception:  # noqa: BLE001 — mcp app absent/unconfigured → no tools
        return []
    return [
        Surface(kind="mcp", target=name, label=name, meta=(td.description or "")[:90])
        for name, td in sorted(TOOL_REGISTRY.items())
    ]


def get_exposed_surfaces() -> list[Surface]:
    """All currently-exposed surfaces (API resources + MCP tools), API first."""
    return _api_surfaces() + _mcp_surfaces()


def get_surface(kind: str, target: str) -> Surface | None:
    """Look up one exposed surface by ``(kind, target)``, or None if not exposed."""
    for surface in get_exposed_surfaces():
        if surface.kind == kind and surface.target == target:
            return surface
    return None


def exposed_keys() -> set[tuple[str, str]]:
    """The ``(kind, target)`` set of everything exposed right now (orphan check)."""
    return {(s.kind, s.target) for s in get_exposed_surfaces()}


def is_surface_exposed(kind: str, target: str) -> bool:
    """Whether ``(kind, target)`` is currently exposed."""
    return (kind, target) in exposed_keys()
