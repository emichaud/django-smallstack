"""Status RSS/Atom feed — the reference integration for :mod:`apps.feeds`.

Publishes the public status page's human-readable events — service **incidents**
and scheduled **maintenance windows** — so anyone can subscribe to status
instead of polling the page. Public (``SearchAccess.ANONYMOUS``), matching the
public ``/status/`` page, and registered from ``HeartbeatConfig.ready()``.

This is a worked example of a curated feed provider: it merges two models and
derives incidents, which a raw per-model dump can't express. Build your own feed
the same way — subclass :class:`apps.feeds.Feed`, implement :meth:`items` over a
queryset you scope, ``register_feed``. (The blog is the other example.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from django.http import HttpRequest
from django.utils.timezone import now

from apps.feeds import Feed, FeedItem
from apps.search.access import SearchAccess

from .models import Heartbeat, MaintenanceWindow

# A gap longer than this between consecutive failed beats ends one incident and
# starts the next (heartbeats land ~once per minute).
_INCIDENT_GAP = timedelta(minutes=5)
# How far back incidents are surfaced in the feed.
_LOOKBACK = timedelta(days=90)


@dataclass
class Incident:
    """A contiguous run of failed heartbeats for one monitor."""

    monitor_key: str
    started: datetime
    ended: datetime
    note: str
    beats: int  # number of failed beats collapsed into this incident


def recent_incidents(limit: int = 25) -> list[Incident]:
    """Collapse consecutive failed heartbeats (per monitor) into incidents.

    Failed beats arrive roughly once a minute during an outage; publishing each
    one would swamp the feed. Grouping by monitor and time-adjacency yields one
    feed item per outage. Returned newest-first.
    """
    since = now() - _LOOKBACK
    fails = (
        Heartbeat.objects.filter(status="fail", timestamp__gte=since)
        .order_by("monitor_key", "timestamp")
        .values("monitor_key", "timestamp", "note")
    )

    incidents: list[Incident] = []
    current: Incident | None = None
    for beat in fails:
        key, ts, note = beat["monitor_key"], beat["timestamp"], beat["note"] or ""
        if (
            current is not None
            and key == current.monitor_key
            and ts - current.ended <= _INCIDENT_GAP
        ):
            current.ended = ts
            current.beats += 1
            if note:
                current.note = note
        else:
            current = Incident(
                monitor_key=key, started=ts, ended=ts, note=note or "Check failed", beats=1
            )
            incidents.append(current)

    incidents.sort(key=lambda inc: inc.started, reverse=True)
    return incidents[:limit]


class StatusFeed(Feed):
    """Public feed of incidents + scheduled maintenance for the status page."""

    slug = "status"
    title = "Service status"
    description = "Service incidents and scheduled maintenance."
    access = SearchAccess.ANONYMOUS
    link = "/status/"
    limit = 50

    def items(self, request: HttpRequest | None = None) -> Iterable[FeedItem]:
        items: list[FeedItem] = []

        for inc in recent_incidents():
            description = f"{inc.monitor_key}: {inc.note}"
            if inc.beats > 1:
                mins = int((inc.ended - inc.started).total_seconds() // 60) + 1
                description += f" — lasted ~{mins} min ({inc.beats} failed checks)"
            items.append(FeedItem(
                title=f"Incident · {inc.monitor_key}",
                link="/status/",
                # Stable GUID: monitor + incident-start instant.
                unique_id=f"incident:{inc.monitor_key}:{inc.started.isoformat()}",
                description=description,
                pubdate=inc.started,
            ))

        for window in MaintenanceWindow.objects.order_by("-start")[:25]:
            body = window.note or ""
            schedule = f"{window.start:%b %d %H:%M}–{window.end:%b %d %H:%M}"
            items.append(FeedItem(
                title=f"Maintenance · {window.title}",
                link="/status/maintenance/",
                unique_id=f"maintenance:{window.pk}",
                description=(f"{body} ({schedule})" if body else schedule).strip(),
                pubdate=window.start,
            ))

        items.sort(key=lambda item: item.pubdate or now(), reverse=True)
        return items[: self.limit]
