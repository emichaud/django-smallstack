"""Pluggable visualization registry for monitor data.

Separates *how a monitor is drawn* from *what a monitor checks*. A
:class:`~apps.smallstack.monitors.Monitor` emits a uniform timeseries (heartbeat
rows); a :class:`Visualization` turns that timeseries into a rendered panel via a
template partial. Because the data shape is identical for every monitor, every
visualization works for every monitor automatically — and a new chart is a new
``Visualization`` subclass plus a partial, **registered without touching any
monitor**.

Mirrors :mod:`apps.smallstack.monitors` / :mod:`apps.smallstack.dashboard`: a
pure, import-light module apps populate from ``AppConfig.ready()``.
"""

from __future__ import annotations

from typing import Any


class Visualization:
    """A pluggable renderer for a monitor's timeseries.

    Subclass, point ``template`` at a partial, and implement :meth:`get_context`.
    The detail page renders each registered visualization in ``order``.
    """

    key: str = ""  # slug, unique across the registry
    title: str = ""  # panel heading, e.g. "Timeline"
    order: int = 50  # render order on the detail page (lower = earlier)
    template: str = ""  # partial template path, rendered with get_context()
    public_safe: bool = True  # may this panel appear on the PUBLIC status page?

    def __init__(self, **overrides: Any) -> None:
        for name, value in overrides.items():
            setattr(self, name, value)

    def get_context(self, monitor_key: str) -> dict:
        """Return the template context for ``monitor_key``'s timeseries.

        Must be cheap-ish (it runs on page load, not per minute). The same
        ``monitor_key`` keys every monitor's heartbeat data.
        """
        raise NotImplementedError


# --- singleton registry (mirrors monitors._monitors) --------------------------

_visualizations: dict[str, Visualization] = {}


def register(visualization: Visualization) -> None:
    """Register a visualization. Idempotent on ``visualization.key``."""
    _visualizations[visualization.key] = visualization


def get_visualizations(public_only: bool = False) -> list[Visualization]:
    """All registered visualizations, ordered. ``public_only`` drops non-public-safe panels."""
    items = _visualizations.values()
    if public_only:
        items = [v for v in items if v.public_safe]
    return sorted(items, key=lambda v: (v.order, v.key))


def get_visualization(key: str) -> Visualization | None:
    return _visualizations.get(key)
