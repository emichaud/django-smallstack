"""Pluggable status-monitoring framework — protocol + registry.

A pure, import-light module that apps populate from ``AppConfig.ready()``, in the
same spirit as the dashboard-widget registry (:mod:`apps.smallstack.dashboard`)
and the navigation registry (:mod:`apps.smallstack.navigation`). It deliberately
imports no models, so any app can register from ``ready()`` without import cycles.

Two concepts:

- **Service** — a monitored subsystem: the site, the REST API, MCP, search, and
  (later) jobs/scheduler. Each owns its identity (title, icon) and is registered
  in code by the app that provides it.
- **Monitor** — a single, *cheap* liveness check that belongs to one Service. A
  service may have several monitors. Monitors come from two sources, mirroring
  the dashboard's two widget sources:
    1. **code-registered** built-ins (``register_monitor``), and
    2. **dynamic sources** (``register_monitor_source``) — e.g. user-created DB
       rows that are each tagged to a service.

A monitor's :meth:`Monitor.check` must be cheap: it runs every minute via the
heartbeat runner. Expensive, point-in-time diagnostics stay in the per-service
doctors (``api_doctor`` / ``mcp_doctor`` / ``search_doctor``) and are surfaced
on-demand, never in the per-minute loop.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one monitor check.

    Build with the :meth:`up` / :meth:`down` constructors so call sites read as
    intent ("up" / "down") rather than a bare boolean.
    """

    ok: bool
    response_time_ms: int = 0
    note: str = ""  # short context/failure message; the runner truncates to 255

    @classmethod
    def up(cls, response_time_ms: int = 0, note: str = "") -> CheckResult:
        return cls(True, response_time_ms, note)

    @classmethod
    def down(cls, note: str, response_time_ms: int = 0) -> CheckResult:
        return cls(False, response_time_ms, note)


class Service:
    """A monitored subsystem that monitors attach to.

    Subclass and set the attributes, or instantiate with keyword overrides:
    ``Service(key="api", title="REST API", icon=SVG, public=False)``.
    """

    key: str = ""  # slug, unique: "site", "api", "mcp", "search"
    title: str = ""  # human label, e.g. "REST API"
    icon: str = ""  # inline SVG markup (trusted), like DashboardWidget.icon
    description: str = ""  # one-line summary for the overview card
    order: int = 50  # sort order on the overview (lower = earlier)
    public: bool = False  # surface this service on the PUBLIC /status/ page?
    # Which tier this service belongs to on the overview (see CATEGORY_LABELS).
    # Default "core": a service registered by an app via ready() is, by definition,
    # one of the platform's own surfaces → the "Site" tier. The "internal" and
    # "external" values are reserved for the two user-monitor home services.
    category: str = "core"
    # Optional existing page to deep-link to (e.g. a doctor/health page).
    detail_url_name: str | None = None
    detail_url_kwargs: dict | None = None

    def __init__(self, **overrides: Any) -> None:
        for name, value in overrides.items():
            setattr(self, name, value)


class Monitor:
    """A single cheap liveness check belonging to a :class:`Service`.

    Subclass and implement :meth:`check`, or build dynamic instances via a
    monitor source (see :func:`register_monitor_source`).
    """

    key: str = ""  # slug, unique across the registry
    service: str = ""  # the Service.key this monitor relates to ("the tag")
    title: str = ""  # human label, e.g. "OpenAPI schema reachable"
    order: int = 50  # sort order within its service
    public: bool = False  # show this monitor on the PUBLIC status page?
    # The monitor's own detail/timeline page. Built-ins point this at
    # "heartbeat:monitor_detail" with detail_url_kwargs={"monitor_key": key}.
    detail_url_name: str | None = None
    detail_url_kwargs: dict | None = None

    def __init__(self, **overrides: Any) -> None:
        for name, value in overrides.items():
            setattr(self, name, value)

    def check(self) -> CheckResult:
        """Run the liveness check. Must be cheap — runs once per minute."""
        raise NotImplementedError

    def inventory(self) -> dict[str, Any]:
        """Optional: what this monitor is *backed by*, for the Site-card drill-down.

        Returns a dict ``{"ok": bool, "summary": str, "items": [{"label", "meta"?,
        "url"?}]}``. ``ok`` is the **live** on/off (computed in-process from the
        relevant registry/connection, independent of the recorded heartbeat), and
        ``items`` is the list revealed when a core service is expanded (the
        endpoints / tools / models behind it). Must be CHEAP + in-process — it runs
        on page render, not in the per-minute loop. Default: nothing to expand.
        """
        return {"ok": True, "summary": "", "items": []}


# --- category taxonomy (the three overview tiers) -----------------------------

# A Service's ``category`` places it in one of three tiers on the status overview.
# "core" is the platform's own surfaces (site/api/mcp/search/scheduler); "internal"
# is monitors for project-defined endpoints/tools (the Site Monitors tier); "external"
# is generic HTTP probes of arbitrary URLs.
CATEGORY_LABELS: dict[str, str] = {
    "core": "Site",
    "internal": "Site Monitors",
    "external": "External Monitors",
}
CATEGORY_ORDER: dict[str, int] = {"core": 0, "internal": 1, "external": 2}
# Shown when a tier has no monitors yet, so the concept is discoverable.
CATEGORY_HINTS: dict[str, str] = {
    "internal": "Monitors for API endpoints and MCP tools defined in this project.",
    "external": "Health/heartbeat checks for external URLs. Add one with “+ Add monitor”.",
}


# --- singleton registries (mirror dashboard._standalone_widgets / nav) --------

_services: dict[str, Service] = {}
_monitors: dict[str, Monitor] = {}
_monitor_sources: list[Callable[[], Iterable[Monitor]]] = []
# Override checks for *exposed surfaces* (API resources / MCP tools), keyed by
# (kind, target). When a user picks a surface to monitor (the "Site Monitors"
# tier) and an app has published a deep checker here, the picked monitor runs
# this instead of the default presence probe — so it catches "server up but this
# tool is broken" false positives. See apps/heartbeat/surfaces.py for the
# (kind, target) vocabulary and register_surface_check() below.
_surface_checks: dict[tuple[str, str], Callable[[], "CheckResult"]] = {}


def register_service(service: Service) -> None:
    """Register a monitored subsystem. Idempotent on ``service.key``."""
    _services[service.key] = service


def register_monitor(monitor: Monitor) -> None:
    """Register a code-defined monitor. Idempotent on ``monitor.key``."""
    _monitors[monitor.key] = monitor


def register_monitor_source(source: Callable[[], Iterable[Monitor]]) -> None:
    """Register a callable that yields monitors at lookup time.

    Used for dynamic, data-backed monitors (e.g. user-created DB rows tagged to a
    service). Called fresh on every :func:`get_monitors`, so it always reflects
    the current data. Keep it cheap (a single query).
    """
    _monitor_sources.append(source)


def get_services() -> list[Service]:
    """All registered services, ordered for display."""
    return sorted(_services.values(), key=lambda s: (s.order, s.key))


def get_service(key: str) -> Service | None:
    return _services.get(key)


def get_monitors(service: str | None = None) -> list[Monitor]:
    """All monitors (code-registered + dynamic sources), ordered.

    Pass ``service`` to filter to one Service.key. Dynamic-source monitors win
    over a code monitor with the same key (lets a DB row override a built-in).
    """
    merged: dict[str, Monitor] = dict(_monitors)
    for source in _monitor_sources:
        for monitor in source():
            merged[monitor.key] = monitor
    monitors = list(merged.values())
    if service is not None:
        monitors = [m for m in monitors if m.service == service]
    return sorted(monitors, key=lambda m: (m.order, m.key))


def get_monitor(key: str) -> Monitor | None:
    """Look up a single monitor by key (searches code + dynamic sources)."""
    for monitor in get_monitors():
        if monitor.key == key:
            return monitor
    return None


def register_surface_check(kind: str, target: str, check: Callable[[], CheckResult]) -> None:
    """Publish a deep liveness check for one exposed surface (Site Monitors tier).

    ``kind`` / ``target`` identify the surface (e.g. ``("mcp", "search_widgets")``
    for an MCP tool, ``("api", "widgets-api-list")`` for a REST resource — see
    :mod:`apps.heartbeat.surfaces`). When a user adds a Site Monitor for that
    surface and enables it, its per-minute check runs ``check`` — which can
    actually exercise the tool/endpoint — instead of the default "is it still
    registered?" presence probe. ``check`` must be CHEAP and return a
    :class:`CheckResult`. Idempotent on ``(kind, target)``; the last registration
    wins. Call from ``AppConfig.ready()`` like the other registries.
    """
    _surface_checks[(kind, target)] = check


def get_surface_check(kind: str, target: str) -> Callable[[], CheckResult] | None:
    """Return the published override check for ``(kind, target)``, or None."""
    return _surface_checks.get((kind, target))
