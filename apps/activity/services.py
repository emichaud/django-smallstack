"""Query helpers behind the activity pages.

Everything the dashboard, Requests, Users and Resources views show comes
through here so the numbers agree with each other: one time-window parser,
one status aggregate, one histogram builder, one per-user / per-resource
roll-up, and the probe classifier. Views stay thin and templates never
re-derive a figure.

Vocabulary
----------
window
    The time range every activity page is scoped to (``?window=24h``). See
    :data:`WINDOWS`; :func:`parse_window` reads it off the request.
resource
    What a request was *for*: the matched URL pattern
    (``/smallstack/approvals/requests/<int:pk>/``) so ``/2253/`` and
    ``/2254/`` roll up together, or the raw path when nothing matched
    (:attr:`RequestLog.route` is empty — the 404 candidates).
probe
    Traffic that is scanning the site rather than using it. Classified at
    read time (so the rules can change without a migration) from two kinds
    of signal: *signatures* on a single request (a path like
    ``/wp-login.php``, a scanner user agent) and *behaviour* of an anonymous
    IP over the window (mostly 404s across many distinct paths, bursts of
    401/403, failed logins recorded by django-axes).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db.models import Avg, Case, CharField, Count, F, Max, Min, Q, QuerySet, TextField, Value, When
from django.http import HttpRequest
from django.utils import timezone

from .models import RequestLog

# ---------------------------------------------------------------------------
# Time windows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """A relative time range the activity pages are scoped to."""

    key: str
    label: str
    short: str
    delta: timedelta | None  # None = all time
    bucket: timedelta  # histogram bucket size

    @property
    def since(self) -> datetime | None:
        return None if self.delta is None else timezone.now() - self.delta

    @property
    def is_all(self) -> bool:
        return self.delta is None

    @property
    def phrase(self) -> str:
        """For prose: "in the last 7 days" / "all time"."""
        return "all time" if self.delta is None else f"in the {self.label.lower()}"


WINDOWS: dict[str, Window] = {
    "1h": Window("1h", "Last hour", "1h", timedelta(hours=1), timedelta(minutes=5)),
    "24h": Window("24h", "Last 24 hours", "24h", timedelta(hours=24), timedelta(hours=1)),
    "7d": Window("7d", "Last 7 days", "7d", timedelta(days=7), timedelta(hours=6)),
    "30d": Window("30d", "Last 30 days", "30d", timedelta(days=30), timedelta(days=1)),
    "all": Window("all", "All time", "All", None, timedelta(days=1)),
}
DEFAULT_WINDOW = "7d"


def parse_window(request: HttpRequest | None) -> Window:
    """The window named by ``?window=``, else the configured default, else 7d."""
    key = request.GET.get("window", "").strip() if request is not None else ""
    if not key:
        key = str(getattr(settings, "ACTIVITY_DEFAULT_WINDOW", DEFAULT_WINDOW))
    return WINDOWS.get(key, WINDOWS[DEFAULT_WINDOW])


def window_queryset(window: Window) -> QuerySet[RequestLog]:
    """All request logs inside *window*."""
    qs = RequestLog.objects.all()
    since = window.since
    return qs.filter(timestamp__gte=since) if since else qs


# ---------------------------------------------------------------------------
# Resource grouping
# ---------------------------------------------------------------------------

# The grouping key: the matched route, else the raw path. Annotated as
# ``resource`` so roll-ups can ``values("resource")`` on it.
RESOURCE_EXPR = Case(When(route="", then=F("path")), default=F("route"), output_field=CharField())


def with_resource(qs: QuerySet[RequestLog]) -> QuerySet[Any]:
    """``qs`` with the ``resource`` annotation (typed loosely: the stubs cannot carry it through values())."""
    return qs.annotate(resource=RESOURCE_EXPR)


def for_resource(qs: QuerySet[RequestLog], resource: str) -> QuerySet[RequestLog]:
    """Rows for one resource key, whichever side of the route/path split it is on."""
    if resource.startswith("/") and RequestLog.objects.filter(route=resource).exists():
        return qs.filter(route=resource)
    return qs.filter(route="", path=resource)


# ---------------------------------------------------------------------------
# Ordering + filters shared by the request tables
# ---------------------------------------------------------------------------


def apply_ordering(qs: QuerySet[Any], ordering: str, allowed: set[str], default: str) -> QuerySet[Any]:
    """``?ordering=`` for values()/annotated querysets — unknown fields are ignored."""
    parts = []
    for raw in ordering.split(","):
        part = raw.strip()
        if part.lstrip("-") in allowed:
            parts.append(part)
    return qs.order_by(*(parts or [default]))


STATUS_CLASSES: dict[str, tuple[int, int]] = {
    "2xx": (200, 300),
    "3xx": (300, 400),
    "4xx": (400, 500),
    "5xx": (500, 600),
}


@dataclass(frozen=True)
class RequestFilters:
    """The optional narrowing a request table accepts on top of the window."""

    status: str = ""  # "2xx" | "404" | ""
    method: str = ""
    q: str = ""  # path contains
    ip: str = ""
    anonymous: bool = False
    path: str = ""  # exact path (the Top paths drill-down)

    @property
    def active(self) -> bool:
        return bool(self.status or self.method or self.q or self.ip or self.anonymous or self.path)


def parse_filters(request: HttpRequest) -> RequestFilters:
    get = request.GET
    return RequestFilters(
        status=get.get("status", "").strip(),
        method=get.get("method", "").strip().upper()[:10],
        q=get.get("q", "").strip()[:200],
        ip=get.get("ip", "").strip()[:64],
        anonymous=get.get("anon", "") == "1",
        path=get.get("path", "").strip()[:2048],
    )


def apply_filters(qs: QuerySet[RequestLog], filters: RequestFilters) -> QuerySet[RequestLog]:
    if filters.status in STATUS_CLASSES:
        low, high = STATUS_CLASSES[filters.status]
        qs = qs.filter(status_code__gte=low, status_code__lt=high)
    elif filters.status.isdigit():
        qs = qs.filter(status_code=int(filters.status))
    if filters.method:
        qs = qs.filter(method=filters.method)
    if filters.q:
        qs = qs.filter(path__icontains=filters.q)
    if filters.ip:
        qs = qs.filter(ip_address=filters.ip)
    if filters.anonymous:
        qs = qs.filter(user__isnull=True)
    if filters.path:
        qs = qs.filter(path=filters.path)
    return qs


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusSummary:
    total: int
    c2xx: int
    c3xx: int
    c4xx: int
    c5xx: int
    avg_ms: int
    max_ms: int
    users: int  # distinct authenticated users
    anonymous: int

    @property
    def errors(self) -> int:
        return self.c4xx + self.c5xx

    @property
    def error_rate(self) -> float:
        return round(self.errors * 100 / self.total, 1) if self.total else 0.0

    @property
    def groups(self) -> list[dict[str, Any]]:
        """The non-empty 2xx/3xx/4xx/5xx counts, for the header strip."""
        pairs = (("2xx", self.c2xx), ("3xx", self.c3xx), ("4xx", self.c4xx), ("5xx", self.c5xx))
        return [{"label": label, "count": count} for label, count in pairs if count]


def status_summary(qs: QuerySet[RequestLog]) -> StatusSummary:
    """Every headline number in one aggregate query."""
    agg = qs.aggregate(
        total=Count("pk"),
        c2xx=Count("pk", filter=Q(status_code__gte=200, status_code__lt=300)),
        c3xx=Count("pk", filter=Q(status_code__gte=300, status_code__lt=400)),
        c4xx=Count("pk", filter=Q(status_code__gte=400, status_code__lt=500)),
        c5xx=Count("pk", filter=Q(status_code__gte=500)),
        avg_ms=Avg("response_time_ms"),
        max_ms=Max("response_time_ms"),
        users=Count("user", distinct=True),
        anonymous=Count("pk", filter=Q(user__isnull=True)),
    )
    return StatusSummary(
        total=agg["total"] or 0,
        c2xx=agg["c2xx"] or 0,
        c3xx=agg["c3xx"] or 0,
        c4xx=agg["c4xx"] or 0,
        c5xx=agg["c5xx"] or 0,
        avg_ms=int(round(agg["avg_ms"] or 0)),
        max_ms=int(agg["max_ms"] or 0),
        users=agg["users"] or 0,
        anonymous=agg["anonymous"] or 0,
    )


def status_mix(qs: QuerySet[RequestLog]) -> list[dict[str, Any]]:
    """Per-status-code counts with their share of the total, most common first."""
    rows = list(qs.values("status_code").annotate(count=Count("pk")).order_by("-count", "status_code"))
    total = sum(r["count"] for r in rows) or 1
    return [{**r, "share": round(r["count"] * 100 / total, 1)} for r in rows]


def method_mix(qs: QuerySet[RequestLog]) -> list[dict[str, Any]]:
    rows = qs.values("method").annotate(count=Count("pk"), avg_ms=Avg("response_time_ms")).order_by("-count")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------


@dataclass
class Bucket:
    start: datetime
    end: datetime
    ok: int = 0
    redirect: int = 0
    client_error: int = 0
    server_error: int = 0
    share: float = 0.0  # % of the window's requests, set once counting is done

    @property
    def total(self) -> int:
        return self.ok + self.redirect + self.client_error + self.server_error

    @property
    def errors(self) -> int:
        return self.client_error + self.server_error


@dataclass
class Histogram:
    buckets: list[Bucket]
    bucket: timedelta
    start: datetime
    end: datetime

    @property
    def max_total(self) -> int:
        return max((b.total for b in self.buckets), default=0)

    @property
    def total(self) -> int:
        return sum(b.total for b in self.buckets)

    @property
    def sub_day(self) -> bool:
        return self.bucket < timedelta(days=1)

    @property
    def multi_day(self) -> bool:
        return self.bucket > timedelta(days=1)

    @property
    def bucket_label(self) -> str:
        minutes = int(self.bucket.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes} min"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} h"
        return f"{hours // 24} d"


MAX_BUCKETS = 60


def histogram(qs: QuerySet[RequestLog], window: Window) -> Histogram:
    """Requests per bucket across the window, split by status class.

    One two-column query; bucketing happens in Python so 5-minute and
    6-hour buckets work the same on every backend.
    """
    now = timezone.now()
    if window.delta is not None:
        span = window.delta
        bucket = window.bucket
    else:
        earliest = qs.aggregate(t=Min("timestamp"))["t"]
        span = max(now - earliest, timedelta(hours=24)) if earliest else timedelta(hours=24)
        days = max(1, math.ceil(span.days / MAX_BUCKETS))
        bucket = timedelta(days=days)
    count = max(1, math.ceil(span / bucket))
    start = now - bucket * count
    buckets = [Bucket(start=start + bucket * i, end=start + bucket * (i + 1)) for i in range(count)]
    step = bucket.total_seconds()
    for ts, code in qs.filter(timestamp__gte=start).values_list("timestamp", "status_code"):
        index = int((ts - start).total_seconds() // step)
        if index < 0 or index >= count:
            continue
        b = buckets[index]
        if code >= 500:
            b.server_error += 1
        elif code >= 400:
            b.client_error += 1
        elif code >= 300:
            b.redirect += 1
        else:
            b.ok += 1
    grand_total = sum(b.total for b in buckets)
    if grand_total:
        for b in buckets:
            b.share = round(b.total * 100 / grand_total, 1)
    return Histogram(buckets=buckets, bucket=bucket, start=start, end=now)


# ---------------------------------------------------------------------------
# Roll-ups
# ---------------------------------------------------------------------------

USER_ORDERING = {"user__username", "hits", "errors", "avg_ms", "max_ms", "last_seen", "paths"}
RESOURCE_ORDERING = {"resource", "hits", "users", "errors", "avg_ms", "max_ms", "last_seen"}


def user_rollup(qs: QuerySet[RequestLog], ordering: str = "") -> QuerySet[Any]:
    """One row per authenticated user: volume, errors, latency, reach, recency."""
    rows = (
        qs.filter(user__isnull=False)
        .values("user__pk", "user__username")
        .annotate(
            hits=Count("pk"),
            errors=Count("pk", filter=Q(status_code__gte=400)),
            avg_ms=Avg("response_time_ms"),
            max_ms=Max("response_time_ms"),
            paths=Count("path", distinct=True),
            last_seen=Max("timestamp"),
            first_seen=Min("timestamp"),
        )
    )
    return apply_ordering(rows, ordering, USER_ORDERING, "-hits")


def resource_rollup(qs: QuerySet[RequestLog], ordering: str = "") -> QuerySet[Any]:
    """One row per resource: volume, distinct users, errors, latency, recency.

    ``resolved`` is 1 when the key is a real route and 0 for an unmatched
    path, so the template can mark the latter as noise.
    """
    rows = (
        with_resource(qs)
        .values("resource")
        .annotate(
            hits=Count("pk"),
            users=Count("user", distinct=True),
            errors=Count("pk", filter=Q(status_code__gte=400)),
            server_errors=Count("pk", filter=Q(status_code__gte=500)),
            avg_ms=Avg("response_time_ms"),
            max_ms=Max("response_time_ms"),
            last_seen=Max("timestamp"),
            resolved=Max(Case(When(route="", then=Value(0)), default=Value(1))),
        )
    )
    return apply_ordering(rows, ordering, RESOURCE_ORDERING, "-hits")


def top_values(qs: QuerySet[RequestLog], field_name: str, limit: int = 5) -> list[dict[str, Any]]:
    """The most common non-empty values of one column (IPs, user agents, tokens)."""
    qs = qs.exclude(**{f"{field_name}__isnull": True})
    if isinstance(RequestLog._meta.get_field(field_name), (CharField, TextField)):
        # Only text columns can hold ""; on a GenericIPAddressField the
        # comparison compiles to `= NULL` and silently drops every row.
        qs = qs.exclude(**{field_name: ""})
    rows = (
        qs.values(field_name)
        .annotate(count=Count("pk"), last_seen=Max("timestamp"))
        .order_by("-count")[:limit]
    )
    return [{"value": r[field_name], "count": r["count"], "last_seen": r["last_seen"]} for r in rows]


# ---------------------------------------------------------------------------
# Probe detection
# ---------------------------------------------------------------------------

# Path signatures (case-insensitive regexes). Each one is something this
# site never serves and scanners always try: CMS logins, dotfiles, backup
# dumps, traversal, app-server consoles, old-exploit endpoints.
DEFAULT_PROBE_PATTERNS: tuple[str, ...] = (
    r"\.php[0-9]?(/|$|\?)",
    r"\.(asp|aspx|jsp|jspx|cgi|cfm)(/|$|\?)",
    r"/wp-(admin|login|content|includes|json|config|cron)",
    r"/(wordpress|joomla|drupal|magento|typo3|laravel|phpbb|vbulletin)(/|$)",
    r"/xmlrpc",
    r"/(phpmyadmin|pma|myadmin|mysqladmin|adminer|sqladmin)(/|$|\.)",
    r"/\.(env|git|svn|hg|htaccess|htpasswd|aws|ssh|docker|ds_store|idea|vscode|npmrc|bash_history)(/|$|\.)",
    r"/(cgi-bin|fcgi-bin)/",
    r"(\.\./|%2e%2e|%252e|\.\.\\)",
    r"(etc/passwd|proc/self|windows/win\.ini|boot\.ini)",
    r"\.(sql|bak|old|orig|swp|save|tgz|7z|rar)(\?|$)",
    r"/(backup|dump|database|db|config|configuration|settings|setup|install)\.(sql|zip|tar|gz|json|yml|yaml|xml|txt)(\?|$)",
    r"/(vendor|node_modules)/",
    r"/(actuator|jmx-console|manager/html|solr|jenkins|druid|geoserver|telescope|_ignition|_profiler|debug/default|console)(/|$)",
    r"/(boaform|hnap1|gponform|eval-stdin|think/|tp/|public/index|shell|cmd|webui|remote/login|owa|autodiscover|ecp)(/|$|\.)",
    r"/(server-status|server-info)(/|$)",
    r"/(login|admin|index|upload|config)\.(php|asp|aspx|jsp)",
)

# User agents that only scanners send. Substring, case-insensitive. Generic
# tooling (curl, python-requests, Go-http-client) is deliberately absent — it
# is how legitimate API and MCP clients talk to this site.
DEFAULT_SCANNER_AGENTS: tuple[str, ...] = (
    "zgrab",
    "masscan",
    "zmap",
    "nikto",
    "sqlmap",
    "nmap",
    "nuclei",
    "gobuster",
    "dirbuster",
    "dirb/",
    "wpscan",
    "acunetix",
    "nessus",
    "openvas",
    "netsparker",
    "ffuf",
    "whatweb",
    "censys",
    "internet-measurement",
    "expanse",
    "paloaltonetworks",
    "l9explore",
    "leakix",
    "shodan",
    "projectdiscovery",
    "arachni",
    "jaeles",
)

# Behavioural thresholds for an anonymous IP over the window.
MIN_404_FOR_CLUSTER = 10
MIN_DISTINCT_404 = 5
MIN_DENIED = 10
MIN_FAILED_LOGINS = 3


def _setting_list(name: str) -> list[str]:
    value = getattr(settings, name, None) or []
    return [str(v) for v in value]


@lru_cache(maxsize=1)
def probe_patterns() -> tuple[str, ...]:
    return DEFAULT_PROBE_PATTERNS + tuple(_setting_list("ACTIVITY_PROBE_PATTERNS_EXTRA"))


@lru_cache(maxsize=1)
def scanner_agents() -> tuple[str, ...]:
    return DEFAULT_SCANNER_AGENTS + tuple(_setting_list("ACTIVITY_SCANNER_AGENTS_EXTRA"))


@lru_cache(maxsize=1)
def combined_probe_pattern() -> str:
    """Every signature as one alternation — one regex evaluation per row, not one per pattern."""
    return "|".join(f"(?:{p})" for p in probe_patterns())


@lru_cache(maxsize=1)
def _compiled_pattern() -> re.Pattern[str]:
    return re.compile(combined_probe_pattern(), re.IGNORECASE)


def _ignored_prefixes() -> list[str]:
    return _setting_list("ACTIVITY_PROBE_IGNORE_PATHS")


def probe_path_q() -> Q:
    """Rows whose path matches a probe signature (minus any exempted prefixes).

    Restricted to error responses: a signature path that the site actually
    served is a feature, not a probe, and it keeps the regex off the bulk of
    the table (SQLite evaluates it in Python, row by row).
    """
    q = Q(status_code__gte=400, path__iregex=combined_probe_pattern())
    for prefix in _ignored_prefixes():
        q &= ~Q(path__startswith=prefix)
    return q


def scanner_agent_q() -> Q:
    q = Q()
    for needle in scanner_agents():
        q |= Q(user_agent__icontains=needle)
    return q


def signature_q() -> Q:
    return probe_path_q() | scanner_agent_q()


def flag_request(log: RequestLog) -> list[str]:
    """Per-row reasons a request looks like a probe — [] for ordinary traffic."""
    reasons: list[str] = []
    path = log.path
    if (
        log.status_code >= 400
        and not any(path.startswith(p) for p in _ignored_prefixes())
        and _compiled_pattern().search(path)
    ):
        reasons.append("probe path")
    ua = (log.user_agent or "").lower()
    if ua and any(needle in ua for needle in scanner_agents()):
        reasons.append("scanner agent")
    return reasons


@dataclass
class ProbeCluster:
    """One anonymous IP's behaviour over the window and why it was flagged."""

    ip: str
    hits: int
    not_found: int
    distinct_404: int
    denied: int
    signatures: int
    scanner: int
    failed_logins: int
    locked_out: bool
    last_seen: datetime | None
    reasons: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def not_found_pct(self) -> int:
        return int(round(self.not_found * 100 / self.hits)) if self.hits else 0

    @property
    def severity(self) -> str:
        if self.score >= 8:
            return "danger"
        if self.score >= 4:
            return "warning"
        return "muted"


@dataclass
class ProbeReport:
    window: Window
    flagged_requests: int
    signature_hits: int
    clusters: list[ProbeCluster]
    top_paths: list[dict[str, Any]]
    top_agents: list[dict[str, Any]]

    @property
    def any(self) -> bool:
        return self.flagged_requests > 0 or bool(self.clusters)

    @property
    def cluster_ips(self) -> list[str]:
        return [c.ip for c in self.clusters]

    @property
    def severity(self) -> str:
        if any(c.severity == "danger" for c in self.clusters):
            return "danger"
        return "warning" if self.any else "muted"


def _axes_failures(since: datetime | None) -> dict[str, tuple[int, bool]]:
    """Failed-login counts per IP from django-axes, when it is installed."""
    if not apps.is_installed("axes"):
        return {}
    try:
        from axes.models import AccessAttempt
    except Exception:  # pragma: no cover — axes present but unimportable
        return {}
    qs = AccessAttempt.objects.all()
    if since is not None:
        qs = qs.filter(attempt_time__gte=since)
    limit = int(getattr(settings, "AXES_FAILURE_LIMIT", 5) or 5)
    out: dict[str, tuple[int, bool]] = {}
    for row in qs.values("ip_address").annotate(n=Count("pk"), worst=Max("failures_since_start")):
        ip = row["ip_address"]
        if ip:
            out[ip] = (int(row["worst"] or 0), int(row["worst"] or 0) >= limit)
    return out


def _score_cluster(c: ProbeCluster) -> None:
    if c.signatures:
        c.reasons.append(f"{c.signatures} probe-path hit{'s' if c.signatures != 1 else ''}")
        c.score += 3 + min(c.signatures, 20)
    if c.scanner:
        c.reasons.append("scanner user agent")
        c.score += 4
    if c.not_found >= MIN_404_FOR_CLUSTER and c.distinct_404 >= MIN_DISTINCT_404 and c.not_found * 2 >= c.hits:
        c.reasons.append(f"{c.not_found_pct}% not found across {c.distinct_404} paths")
        c.score += 2 + min(c.distinct_404 // 5, 6)
    # A ratio, not a count: one anonymous 401 per MCP/OAuth discovery is normal,
    # a client that is denied a fifth of the time is guessing.
    if c.denied >= MIN_DENIED and c.denied * 5 >= c.hits:
        c.reasons.append(f"{c.denied} denied (401/403)")
        c.score += 2
    if c.locked_out:
        c.reasons.append("locked out by axes")
        c.score += 4
    elif c.failed_logins >= MIN_FAILED_LOGINS:
        c.reasons.append(f"{c.failed_logins} failed logins")
        c.score += 2


def probe_report(qs: QuerySet[RequestLog], window: Window, limit: int = 10) -> ProbeReport:
    """Classify the window's traffic. One aggregate over anonymous rows + one count."""
    sig = signature_q()
    anon = qs.filter(user__isnull=True, ip_address__isnull=False)
    candidates = (
        anon.values("ip_address")
        .annotate(
            hits=Count("pk"),
            not_found=Count("pk", filter=Q(status_code=404)),
            distinct_404=Count("path", distinct=True, filter=Q(status_code=404)),
            denied=Count("pk", filter=Q(status_code__in=(401, 403))),
            signatures=Count("pk", filter=probe_path_q()),
            scanner=Count("pk", filter=scanner_agent_q()),
            last_seen=Max("timestamp"),
        )
        .filter(
            Q(signatures__gt=0)
            | Q(scanner__gt=0)
            | Q(not_found__gte=MIN_404_FOR_CLUSTER)
            | Q(denied__gte=MIN_DENIED)
        )
        .order_by("-hits")[:200]
    )
    failures = _axes_failures(window.since)
    clusters: list[ProbeCluster] = []
    seen: set[str] = set()
    for row in candidates:
        ip = str(row["ip_address"])
        seen.add(ip)
        failed, locked = failures.get(ip, (0, False))
        c = ProbeCluster(
            ip=ip,
            hits=row["hits"],
            not_found=row["not_found"],
            distinct_404=row["distinct_404"],
            denied=row["denied"],
            signatures=row["signatures"],
            scanner=row["scanner"],
            failed_logins=failed,
            locked_out=locked,
            last_seen=row["last_seen"],
        )
        _score_cluster(c)
        if c.reasons:
            clusters.append(c)
    # IPs that only show up as failed logins (their requests may be excluded or pruned).
    for ip, (failed, locked) in failures.items():
        if ip in seen or (failed < MIN_FAILED_LOGINS and not locked):
            continue
        c = ProbeCluster(ip, 0, 0, 0, 0, 0, 0, failed, locked, None)
        _score_cluster(c)
        clusters.append(c)
    clusters.sort(key=lambda c: (-c.score, -c.hits))
    clusters = clusters[:limit]

    # A flagged IP contributes only its *evidence* (error rows), never its whole
    # traffic — a NAT or a dev box shares one address with legitimate use.
    flagged = qs.filter(sig | _cluster_evidence_q([c.ip for c in clusters]))
    top_paths = [dict(r) for r in flagged.values("path").annotate(hits=Count("pk")).order_by("-hits")[:limit]]
    top_agents = top_values(flagged, "user_agent", limit=5)
    return ProbeReport(
        window=window,
        flagged_requests=flagged.count(),
        signature_hits=qs.filter(sig).count(),
        clusters=clusters,
        top_paths=top_paths,
        top_agents=top_agents,
    )


def _cluster_evidence_q(ips: list[str]) -> Q:
    if not ips:
        return Q(pk__in=[])
    return Q(user__isnull=True, ip_address__in=ips, status_code__gte=400)


def probe_requests(qs: QuerySet[RequestLog], report: ProbeReport) -> QuerySet[RequestLog]:
    """The rows a :class:`ProbeReport` counted, for the Probes tab."""
    return qs.filter(signature_q() | _cluster_evidence_q(report.cluster_ips))


def annotate_probe_flags(rows: list[RequestLog], cluster_ips: set[str] | None = None) -> list[RequestLog]:
    """Attach ``probe_reasons`` to each row on a page (cheap: one regex per row)."""
    for row in rows:
        reasons = flag_request(row)
        if cluster_ips and row.user_id is None and row.status_code >= 400 and row.ip_address in cluster_ips:
            reasons.append("flagged IP")
        setattr(row, "probe_reasons", reasons)
    return rows
