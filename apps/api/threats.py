"""Threat heuristics for the API admin Activity panel.

Pure functions over ``apps.activity.models.RequestLog`` and
``axes.models.AccessAttempt``. Each detector returns a list of
``ThreatSignal`` instances; the view aggregates them and renders by
severity.

Scope: we surface signals derived from data we already have. No new
instrumentation, no geoip, no request-body sampling, no active response
(blocking IPs / revoking tokens is the operator's call).

False positives are honest about themselves — the docs accompanying
this module describe the precise threshold and decay of each heuristic
so an operator can read the panel without misinterpreting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from django.db.models import Count, Q
from django.utils import timezone

Severity = Literal["high", "medium", "low"]


# Scanner / fuzzer user-agent fingerprints. Substring match (icontains)
# against the UA string; case-insensitive. Pragmatic list — covers the
# bots that crawl the public internet hammering for SQLi/RCE/etc.
SCANNER_UA_PATTERNS: tuple[str, ...] = (
    "sqlmap",
    "nikto",
    "nmap",
    "masscan",
    "zgrab",
    "dirbuster",
    "gobuster",
    "ffuf",
    "wpscan",
    "acunetix",
    "nessus",
    "burpsuite",
    "metasploit",
    "openvas",
)

SCANNER_UA_REGEX = re.compile("|".join(re.escape(p) for p in SCANNER_UA_PATTERNS), re.IGNORECASE)


@dataclass
class ThreatSignal:
    """One row in the Threat panel.

    Designed to render in a table: severity badge + label + IP + count
    + first/last seen + a tiny preview of paths the IP touched.
    """

    severity: Severity
    label: str
    ip: str | None
    count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    sample_paths: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def severity_class(self) -> str:
        return {"high": "threat-high", "medium": "threat-medium", "low": "threat-low"}[self.severity]


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_auth_failure_burst(*, window_hours: int = 1, threshold: int = 10) -> list[ThreatSignal]:
    """IPs with >= threshold 401/403 responses on /api/* within window."""
    try:
        from apps.activity.models import RequestLog
    except ImportError:
        return []
    cutoff = timezone.now() - timedelta(hours=window_hours)
    rows = (
        RequestLog.objects.filter(
            path__startswith="/api",
            status_code__in=(401, 403),
            timestamp__gte=cutoff,
            ip_address__isnull=False,
        )
        .values("ip_address")
        .annotate(n=Count("id"), first_seen=Count("id"))
    )
    # Use a separate aggregation for first/last seen since Count("id") doesn't give us min/max timestamp.
    top_rows = cast("list[dict[str, Any]]", list(rows.filter(n__gte=threshold).order_by("-n")[:20]))
    signals: list[ThreatSignal] = []
    for r in top_rows:
        ip = r["ip_address"]
        log_qs = RequestLog.objects.filter(
            path__startswith="/api",
            status_code__in=(401, 403),
            timestamp__gte=cutoff,
            ip_address=ip,
        ).order_by("-timestamp")
        first = log_qs.last()
        last = log_qs.first()
        paths = list(log_qs.order_by().values_list("path", flat=True).distinct()[:3])
        signals.append(
            ThreatSignal(
                severity="high",
                label=f"{r['n']} auth failures (401/403) in last {window_hours}h",
                ip=ip,
                count=r["n"],
                first_seen=first.timestamp if first else None,
                last_seen=last.timestamp if last else None,
                sample_paths=paths,
            )
        )
    return signals


def detect_path_scanning(
    *, window_hours: int = 1, threshold_distinct: int = 10, threshold_404: int = 20
) -> list[ThreatSignal]:
    """IPs hitting many distinct /api paths with many 404s — classic fuzzer."""
    try:
        from apps.activity.models import RequestLog
    except ImportError:
        return []
    cutoff = timezone.now() - timedelta(hours=window_hours)
    rows = (
        RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
            ip_address__isnull=False,
        )
        .values("ip_address")
        .annotate(
            distinct_paths=Count("path", distinct=True),
            errors=Count("id", filter=Q(status_code=404)),
        )
        .filter(distinct_paths__gte=threshold_distinct, errors__gte=threshold_404)
        .order_by("-errors")[:20]
    )
    signals: list[ThreatSignal] = []
    for r in rows:
        ip = r["ip_address"]
        log_qs = RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
            ip_address=ip,
            status_code=404,
        ).order_by("-timestamp")
        first = log_qs.last()
        last = log_qs.first()
        paths = list(log_qs.order_by().values_list("path", flat=True).distinct()[:3])
        signals.append(
            ThreatSignal(
                severity="medium",
                label=f"Path scanning — {r['distinct_paths']} paths, {r['errors']} × 404 in last {window_hours}h",
                ip=ip,
                count=r["errors"],
                first_seen=first.timestamp if first else None,
                last_seen=last.timestamp if last else None,
                sample_paths=paths,
            )
        )
    return signals


def detect_request_burst(
    *, window_minutes: int = 1, threshold: int = 200
) -> list[ThreatSignal]:
    """Single IP with > threshold requests inside a window_minutes-second window.

    Coarse — uses a single window-now-minus-N rather than a rolling
    window. Catches obvious bursts without the cost of a windowed query.
    """
    try:
        from apps.activity.models import RequestLog
    except ImportError:
        return []
    cutoff = timezone.now() - timedelta(minutes=window_minutes)
    rows = (
        RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
            ip_address__isnull=False,
        )
        .values("ip_address")
        .annotate(n=Count("id"))
        .filter(n__gte=threshold)
        .order_by("-n")[:20]
    )
    signals: list[ThreatSignal] = []
    for r in rows:
        ip = r["ip_address"]
        log_qs = RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
            ip_address=ip,
        ).order_by("-timestamp")
        first = log_qs.last()
        last = log_qs.first()
        paths = list(log_qs.order_by().values_list("path", flat=True).distinct()[:3])
        signals.append(
            ThreatSignal(
                severity="medium",
                label=f"Request burst — {r['n']} requests in last {window_minutes}m",
                ip=ip,
                count=r["n"],
                first_seen=first.timestamp if first else None,
                last_seen=last.timestamp if last else None,
                sample_paths=paths,
            )
        )
    return signals


def detect_scanner_user_agents(*, window_hours: int = 24) -> list[ThreatSignal]:
    """Requests on /api with a UA string matching a known scanner."""
    try:
        from apps.activity.models import RequestLog
    except ImportError:
        return []
    cutoff = timezone.now() - timedelta(hours=window_hours)
    # SQLite doesn't support regex by default — fall back to a series of
    # icontains queries unioned via Q. Cheap given the small pattern list.
    ua_q = Q()
    for pattern in SCANNER_UA_PATTERNS:
        ua_q |= Q(user_agent__icontains=pattern)
    rows = (
        RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
        )
        .filter(ua_q)
        .values("ip_address", "user_agent")
        .annotate(n=Count("id"))
        .order_by("-n")[:20]
    )
    signals: list[ThreatSignal] = []
    for r in rows:
        ip = r["ip_address"]
        ua = (r["user_agent"] or "").strip()
        # Pull a short preview of the UA for the label.
        ua_short = ua[:60] + ("…" if len(ua) > 60 else "")
        match = SCANNER_UA_REGEX.search(ua)
        matched_tool = match.group(0).lower() if match else "scanner"
        log_qs = RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
            user_agent=ua,
            ip_address=ip,
        ).order_by("-timestamp")
        first = log_qs.last()
        last = log_qs.first()
        paths = list(log_qs.order_by().values_list("path", flat=True).distinct()[:3])
        signals.append(
            ThreatSignal(
                severity="medium",
                label=f"Scanner UA ({matched_tool}) — {r['n']} requests in last {window_hours}h",
                ip=ip,
                count=r["n"],
                first_seen=first.timestamp if first else None,
                last_seen=last.timestamp if last else None,
                sample_paths=paths,
                extra={"user_agent": ua_short},
            )
        )
    return signals


def detect_revoked_token_use(*, window_hours: int = 24) -> list[ThreatSignal]:
    """Requests authenticated with a revoked APIToken — someone retrying after revoke."""
    try:
        from apps.activity.models import RequestLog
    except ImportError:
        return []
    cutoff = timezone.now() - timedelta(hours=window_hours)
    rows = (
        RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
            api_token__isnull=False,
            api_token__is_active=False,
        )
        .values("ip_address", "api_token__name", "api_token__prefix")
        .annotate(n=Count("id"))
        .order_by("-n")[:20]
    )
    signals: list[ThreatSignal] = []
    for r in rows:
        ip = r["ip_address"]
        token_label = f"{r['api_token__prefix']} ({r['api_token__name']})"
        log_qs = RequestLog.objects.filter(
            path__startswith="/api",
            timestamp__gte=cutoff,
            api_token__prefix=r["api_token__prefix"],
        ).order_by("-timestamp")
        first = log_qs.last()
        last = log_qs.first()
        paths = list(log_qs.order_by().values_list("path", flat=True).distinct()[:3])
        signals.append(
            ThreatSignal(
                severity="low",
                label=f"Revoked token used — {token_label}, {r['n']} requests in last {window_hours}h",
                ip=ip,
                count=r["n"],
                first_seen=first.timestamp if first else None,
                last_seen=last.timestamp if last else None,
                sample_paths=paths,
                extra={"token": token_label},
            )
        )
    return signals


def detect_axes_lockouts() -> list[ThreatSignal]:
    """IPs currently locked out by django-axes."""
    try:
        from axes.models import AccessAttempt
        from django.conf import settings
    except ImportError:
        return []
    failure_limit = getattr(settings, "AXES_FAILURE_LIMIT", 5)
    cooloff_hours = float(getattr(settings, "AXES_COOLOFF_TIME", 0.25))
    cutoff = timezone.now() - timedelta(hours=cooloff_hours)
    try:
        rows = list(
            AccessAttempt.objects.filter(
                failures_since_start__gte=failure_limit,
                attempt_time__gte=cutoff,
            ).order_by("-attempt_time")[:20]
        )
    except Exception:
        return []
    signals: list[ThreatSignal] = []
    for a in rows:
        signals.append(
            ThreatSignal(
                severity="high",
                label=f"Axes lockout — {a.failures_since_start} failed auth ({a.username or 'unknown'})",
                ip=getattr(a, "ip_address", None),
                count=a.failures_since_start,
                first_seen=getattr(a, "attempt_time", None),
                last_seen=getattr(a, "attempt_time", None),
                sample_paths=[getattr(a, "path_info", "") or ""][:1],
                extra={"username": a.username or ""},
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def collect_threats(*, window_hours: int = 24) -> list[ThreatSignal]:
    """Run every detector and return the combined list, severity-ordered."""
    signals: list[ThreatSignal] = []
    signals.extend(detect_axes_lockouts())
    signals.extend(detect_auth_failure_burst(window_hours=1))
    signals.extend(detect_request_burst(window_minutes=1))
    signals.extend(detect_path_scanning(window_hours=1))
    signals.extend(detect_scanner_user_agents(window_hours=window_hours))
    signals.extend(detect_revoked_token_use(window_hours=window_hours))
    order = {"high": 0, "medium": 1, "low": 2}
    signals.sort(key=lambda s: (order[s.severity], -s.count))
    return signals


def count_high_severity_threats(*, window_hours: int = 24) -> int:
    """Cheap sum used by the dashboard widget — just the high-severity rows."""
    return len(detect_axes_lockouts()) + len(detect_auth_failure_burst(window_hours=1))
