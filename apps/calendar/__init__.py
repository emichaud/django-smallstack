"""Calendar — datasets with a time axis, merged onto one month grid.

A *calendar dataset* is an ordinary ``@dataset`` plus a small protocol: which
column is the event's start, optionally which is its end, and how to title and
tint a chip. Declare one with ``@calendar_dataset`` (a superset of ``@dataset``)
or attach the protocol to a dataset declared elsewhere with
``register_calendar``. The app then offers every calendar dataset the viewer
may see as an additive toggle on ``/smallstack/calendar/``, lets a user save a
selection as a named view, and publishes the normalised events over REST, ICS
and MCP.

The ladder is CRUDView → dataset → calendar dataset: a model gets pages, a
dataset makes it a typed, filterable table, and the calendar protocol puts it
on a date grid. Only stdlib is imported here so an app's ``datasets.py`` can
import the decorator during autodiscovery.
"""

from __future__ import annotations

from .registry import CalendarSpec, calendar_dataset, calendar_provider, register_calendar  # noqa: F401

__all__ = ["CalendarSpec", "calendar_dataset", "calendar_provider", "register_calendar"]
