"""Heartbeat visualizations — pluggable panels over a monitor's timeseries.

These read the heartbeat computation helpers and render the timeline bars and
uptime stat cards that used to live only on the staff dashboard. Registered with
the framework visualization registry, so a monitor's detail page composes them
generically. New panels (sparkline, heatmap, …) are added here without touching
any monitor. Each ``get_context`` reads the ``status`` helpers scoped to its
``monitor_key``.
"""

from __future__ import annotations

from typing import Any

from apps.smallstack.visualizations import Visualization

_STATUS_STATE: dict[str, str] = {"operational": "success", "degraded": "warning", "down": "danger"}


def _pct(value: float | None) -> str:
    return f"{value}%" if value is not None else "—"


class UptimeStatsVisualization(Visualization):
    """Headline stat cards: current status, overall / 24h / 7d uptime, response."""

    key: str = "uptime_stats"
    title: str = "Uptime"
    order: int = 10
    template: str = "heartbeat/visualizations/uptime_stats.html"
    public_safe: bool = True

    def get_context(self, monitor_key: str) -> dict[str, Any]:
        from .status import _calc_overall_uptime, _calc_uptime, _get_status_data, _sla_state

        status = _get_status_data(monitor_key)
        overall = _calc_overall_uptime(monitor_key)
        u24, u7 = _calc_uptime(24, monitor_key), _calc_uptime(168, monitor_key)
        return {
            "status_label": status.get("status_label", "No Data"),
            "status_state": _STATUS_STATE.get(status.get("status", ""), "muted"),
            "response_time_ms": status.get("response_time_ms"),
            "uptime_overall_display": _pct(overall),
            "uptime_overall_state": _sla_state(overall, use_target=True, monitor_key=monitor_key),
            "uptime_24h_display": _pct(u24),
            "uptime_24h_state": _sla_state(u24, use_target=True, monitor_key=monitor_key),
            "uptime_7d_display": _pct(u7),
            "uptime_7d_state": _sla_state(u7, use_target=True, monitor_key=monitor_key),
        }


class TimelineVisualization(Visualization):
    """Stacked 1d / 7d / 90d uptime bars — the same format as the public board.

    Renders ``heartbeat/_site_timelines.html`` (shared with the public status page
    and the staff dashboard) scoped to this monitor, so every monitor's detail page
    shows Last 24 hours / Last 7 days / Last 90 days in one consistent style.
    """

    key: str = "timeline"
    title: str = "Timeline"
    order: int = 20
    template: str = "heartbeat/_site_timelines.html"
    public_safe: bool = True

    def get_context(self, monitor_key: str) -> dict[str, Any]:
        from .status import build_stacked_timelines

        return {"site_timelines": build_stacked_timelines(monitor_key)}
