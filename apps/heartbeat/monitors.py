"""Built-in monitors for the heartbeat app.

Registers the **site** service (the application itself) and its
database-connectivity monitor with the pluggable status framework
(:mod:`apps.smallstack.monitors`). This is the same cheap check the per-minute
heartbeat has always run, now expressed as a :class:`Monitor` so it sits in the
same overview as the API / MCP / search monitors.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from django.db import connection

from apps.smallstack.monitors import CheckResult, Monitor, Service

if TYPE_CHECKING:
    from .models import MonitoredEndpoint, MonitoredSurface

# Inline SVG (trusted), matching the DashboardWidget.icon / nav icon_svg convention.
_SITE_ICON: str = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
    '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zm6.93 6h-2.95a15.7 15.7 0 00-1.38-3.56'
    "A8.03 8.03 0 0118.92 8zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 "
    "1.91-3.96zM4.26 14a7.96 7.96 0 010-4h3.38a16.5 16.5 0 000 4H4.26zm.82 2h2.95c.32 1.25"
    ".78 2.45 1.38 3.56A7.99 7.99 0 015.08 16zm2.95-8H5.08a7.99 7.99 0 014.33-3.56A15.7 "
    "15.7 0 008.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 "
    "3.96zM14.34 14H9.66a14.7 14.7 0 010-4h4.68a14.7 14.7 0 010 4zm.25 5.56c.6-1.11 1.06-2.31 "
    "1.38-3.56h2.95a8.03 8.03 0 01-4.33 3.56zM16.36 14a16.5 16.5 0 000-4h3.38a7.96 7.96 0 010 "
    '4h-3.38z"/></svg>'
)


def check_database_connection() -> CheckResult:
    """Cheap liveness check: ensure the DB connection is usable.

    Sub-millisecond in the common case; this is the same probe the heartbeat has
    always run. Reused by :class:`SiteMonitor` and (later) the unified runner.
    """
    start = time.monotonic()
    try:
        connection.ensure_connection()
    except Exception as exc:  # noqa: BLE001 — any failure means "down"
        return CheckResult.down(str(exc), response_time_ms=int((time.monotonic() - start) * 1000))
    return CheckResult.up(response_time_ms=int((time.monotonic() - start) * 1000))


class SiteService(Service):
    """The application itself — database connectivity and overall uptime."""

    key: str = "site"
    title: str = "Site"
    description: str = "The application itself — database connectivity and uptime."
    icon: str = _SITE_ICON
    order: int = 10
    public: bool = True
    category: str = "core"
    detail_url_name: str | None = "heartbeat:dashboard"


class SiteMonitor(Monitor):
    """Database-connectivity liveness for the site.

    ``key`` is ``"site"`` so its timeseries lines up with the existing heartbeat
    rows (which the model migration backfills to ``monitor_key="site"``).
    """

    key: str = "site"
    service: str = "site"
    title: str = "Database connectivity"
    order: int = 10
    public: bool = True
    # The composed, visualization-driven detail page for this monitor.
    detail_url_name: str | None = "heartbeat:monitor_detail"
    detail_url_kwargs: dict | None = {"monitor_key": "site"}

    def check(self) -> CheckResult:
        return check_database_connection()

    def inventory(self) -> dict:
        """Live: the database connection behind the site."""
        import os

        from django.db import connection

        ok = True
        try:
            connection.ensure_connection()
        except Exception:  # noqa: BLE001
            ok = False
        name = connection.settings_dict.get("NAME", "")
        label = os.path.basename(str(name)) if name else (connection.vendor or "database")
        return {
            "ok": ok,
            "summary": "connected" if ok else "unreachable",
            "items": [{"label": label, "meta": connection.vendor}],
        }


class InternalService(Service):
    """Site Monitors — monitors for API endpoints / MCP tools defined in this project.

    Populated by the (forthcoming) source picker, which lets a user select a
    registered endpoint or tool and check it cheaply in-process. Registered now so
    the tier is visible and the taxonomy is established; it has no monitors yet.
    """

    key: str = "internal"
    title: str = "Site Monitors"
    description: str = "Monitors for API endpoints and MCP tools defined in this project."
    icon: str = (
        '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
        '<path d="M4 4h16v4H4zm0 6h16v4H4zm0 6h10v4H4z"/></svg>'
    )
    order: int = 46
    public: bool = False
    category: str = "internal"


class CustomService(Service):
    """External Monitors — generic HTTP probes of arbitrary (external/internal) URLs.

    Home for user-created ``MonitoredEndpoint`` rows. The slug stays ``"custom"`` for
    back-compat (existing rows tag to it); the tier label is "External Monitors".
    """

    key: str = "custom"
    title: str = "External Monitors"
    description: str = "Health/heartbeat checks for external URLs."
    icon: str = (
        '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
        '<path d="M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>'
    )
    order: int = 50
    public: bool = False
    category: str = "external"


def check_http_endpoint(url: str, method: str, expected_status: int, timeout: int) -> CheckResult:
    """Cheap HTTP liveness check: request ``url`` and compare the status code.

    Uses stdlib urllib with a hard timeout. NOTE: staff-only by construction (the
    CRUD is staff-gated), and internal URLs are intentionally allowed so you can
    monitor your own services. For multi-tenant deployments, add an SSRF allowlist
    here before exposing endpoint creation to untrusted users.
    """
    request = urllib.request.Request(url, method=method)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — scheme validated on the model
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code  # got a response, just an error status
        exc.close()  # HTTPError is a file-like response — close it to avoid leaking the fd
    except Exception as exc:  # noqa: BLE001 — any transport failure is "down"
        return CheckResult.down(str(exc)[:200], response_time_ms=int((time.monotonic() - start) * 1000))
    elapsed = int((time.monotonic() - start) * 1000)
    if code == expected_status:
        return CheckResult.up(response_time_ms=elapsed, note=f"HTTP {code}")
    return CheckResult.down(f"HTTP {code} (expected {expected_status})", response_time_ms=elapsed)


class EndpointMonitor(Monitor):
    """Wraps a :class:`~apps.heartbeat.models.MonitoredEndpoint` row as a monitor."""

    def __init__(self, endpoint: MonitoredEndpoint) -> None:
        self.endpoint = endpoint
        self.key = endpoint.monitor_key
        self.service = endpoint.service
        self.title = endpoint.name
        self.order = 50
        self.public = endpoint.public
        self.detail_url_name = "heartbeat:monitor_detail"
        self.detail_url_kwargs = {"monitor_key": endpoint.monitor_key}

    def check(self) -> CheckResult:
        ep = self.endpoint
        return check_http_endpoint(ep.url, ep.method, ep.expected_status, ep.timeout_seconds)


def endpoint_monitor_source() -> list[Monitor]:
    """Yield a live monitor per enabled MonitoredEndpoint row.

    Registered via ``monitors.register_monitor_source`` — called fresh on every
    lookup, so it always reflects the current rows. Resilient to the table not
    existing yet (e.g. before the migration runs).
    """
    try:
        from .models import MonitoredEndpoint

        return [EndpointMonitor(ep) for ep in MonitoredEndpoint.objects.filter(enabled=True)]
    except Exception:  # noqa: BLE001 — pre-migrate / DB unavailable → no dynamic monitors
        return []


class SurfaceMonitor(Monitor):
    """Wraps a :class:`~apps.heartbeat.models.MonitoredSurface` row as a monitor.

    Runs in one of three modes, decided per check:

    - **orphaned** — the picked surface is no longer exposed. ``orphaned`` is True;
      the runner *skips* recording for it (no fail beats, no SLA dent) and the
      overview renders it muted with a "Remove" prompt. A config change, not an
      outage.
    - **deep check** — an app published an override via ``register_surface_check``;
      ``check()`` runs that (it can actually exercise the tool/endpoint).
    - **presence probe** (default) — confirms the surface is still exposed. The
      liveness floor; the value-add is the opt-in deep check.
    """

    def __init__(self, surface: "MonitoredSurface", exposed: bool) -> None:
        self.surface = surface
        self.key = surface.monitor_key
        self.service = "internal"
        self.title = surface.name
        self.order = 50
        self.public = surface.public
        self.kind = surface.kind
        self.target = surface.target
        # Computed once at source time (cheap registry read) so the runner and the
        # overview agree without each re-scanning the exposed set.
        self.orphaned = not exposed
        self.detail_url_name = "heartbeat:monitor_detail"
        self.detail_url_kwargs = {"monitor_key": surface.monitor_key}

    def check(self) -> CheckResult:
        from apps.smallstack.monitors import get_surface_check

        from .surfaces import is_surface_exposed

        override = get_surface_check(self.kind, self.target)
        if override is not None:
            return override()
        # Default presence probe — re-confirm at check time (the registry can change
        # between source build and this call). An exposed surface with no deep check
        # is "up" by virtue of still being wired; if it vanished mid-run it's down.
        if is_surface_exposed(self.kind, self.target):
            return CheckResult.up(note="exposed")
        return CheckResult.down("surface no longer exposed")


def surface_monitor_source() -> list[Monitor]:
    """Yield a live monitor per enabled MonitoredSurface row (Site Monitors tier).

    Each is tagged ``orphaned`` if its surface is no longer exposed, computed from a
    single in-process scan of the exposed set. Resilient to the table not existing
    yet (pre-migrate).
    """
    try:
        from .models import MonitoredSurface
        from .surfaces import exposed_keys

        exposed = exposed_keys()
        return [
            SurfaceMonitor(s, (s.kind, s.target) in exposed)
            for s in MonitoredSurface.objects.filter(enabled=True)
        ]
    except Exception:  # noqa: BLE001 — pre-migrate / DB unavailable → no dynamic monitors
        return []
