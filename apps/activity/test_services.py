"""Unit tests for apps.activity.services — the numbers every activity page shows.

Windows, resource grouping (route vs raw path), the one-query status
summary, histogram bucketing, the per-user / per-resource roll-ups, and the
probe classifier (signatures, scanner agents, per-IP behaviour, the
evidence-only rule that keeps a shared address's legitimate traffic out).
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from django.utils import timezone

from . import services
from .models import RequestLog

pytestmark = pytest.mark.django_db

User = get_user_model()


def _log(path="/x/", *, route=None, status=200, user=None, ip="10.0.0.1", ua="Mozilla/5.0", ms=10, ago=None):
    row = RequestLog.objects.create(
        path=path,
        route=("/" + path.strip("/") + "/") if route is None and status < 400 else (route or ""),
        method="GET",
        status_code=status,
        user=user,
        ip_address=ip,
        user_agent=ua,
        response_time_ms=ms,
    )
    if ago is not None:
        RequestLog.objects.filter(pk=row.pk).update(timestamp=timezone.now() - ago)
        row.refresh_from_db()
    return row


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def test_parse_window_reads_param_and_falls_back():
    rf = RequestFactory()
    assert services.parse_window(rf.get("/", {"window": "24h"})).key == "24h"
    assert services.parse_window(rf.get("/", {"window": "bogus"})).key == services.DEFAULT_WINDOW
    assert services.parse_window(rf.get("/")).key == services.DEFAULT_WINDOW
    assert services.parse_window(None).key == services.DEFAULT_WINDOW
    with override_settings(ACTIVITY_DEFAULT_WINDOW="30d"):
        assert services.parse_window(rf.get("/")).key == "30d"


def test_window_queryset_scopes_by_time():
    _log("/new/")
    _log("/old/", ago=timedelta(days=3))
    assert services.window_queryset(services.WINDOWS["24h"]).count() == 1
    assert services.window_queryset(services.WINDOWS["7d"]).count() == 2
    assert services.window_queryset(services.WINDOWS["all"]).count() == 2


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def test_resource_rollup_groups_by_route_and_keeps_unmatched_paths_apart():
    for pk in (1, 2, 3):
        _log(f"/things/{pk}/", route="/things/<int:pk>/")
    _log("/wp-login.php", status=404)
    _log("/wp-login.php", status=404)
    rows = {r["resource"]: r for r in services.resource_rollup(RequestLog.objects.all())}
    assert rows["/things/<int:pk>/"]["hits"] == 3
    assert rows["/things/<int:pk>/"]["resolved"] == 1
    assert rows["/wp-login.php"]["hits"] == 2
    assert rows["/wp-login.php"]["resolved"] == 0
    assert rows["/wp-login.php"]["errors"] == 2


def test_for_resource_finds_either_side_of_the_split():
    _log("/things/1/", route="/things/<int:pk>/")
    _log("/nothing/", status=404)
    qs = RequestLog.objects.all()
    assert services.for_resource(qs, "/things/<int:pk>/").count() == 1
    assert services.for_resource(qs, "/nothing/").count() == 1
    assert services.for_resource(qs, "/absent/").count() == 0


def test_model_resource_property():
    assert RequestLog(path="/a/1/", route="/a/<int:pk>/").resource_key == "/a/<int:pk>/"
    assert RequestLog(path="/a/1/", route="").resource_key == "/a/1/"


# ---------------------------------------------------------------------------
# Summaries + histogram
# ---------------------------------------------------------------------------


def test_status_summary_is_one_aggregate_with_the_right_buckets(django_assert_num_queries):
    user = User.objects.create_user("u1", password="x")
    _log("/ok/", status=200, user=user, ms=10)
    _log("/moved/", status=302, ms=20)
    _log("/missing/", status=404, ms=30)
    _log("/boom/", status=500, ms=40)
    with django_assert_num_queries(1):
        s = services.status_summary(RequestLog.objects.all())
    assert (s.total, s.c2xx, s.c3xx, s.c4xx, s.c5xx) == (4, 1, 1, 1, 1)
    assert s.errors == 2 and s.error_rate == 50.0
    assert s.avg_ms == 25 and s.max_ms == 40
    assert s.users == 1 and s.anonymous == 3
    assert [g["label"] for g in s.groups] == ["2xx", "3xx", "4xx", "5xx"]


def test_histogram_buckets_cover_the_window_and_split_by_class():
    _log("/ok/", status=200)
    _log("/missing/", status=404)
    _log("/boom/", status=500)
    _log("/ancient/", status=200, ago=timedelta(days=9))  # outside 7d
    h = services.histogram(RequestLog.objects.all(), services.WINDOWS["7d"])
    assert len(h.buckets) == 28  # 7d / 6h
    assert h.total == 3
    last = h.buckets[-1]
    assert (last.ok, last.client_error, last.server_error) == (1, 1, 1)
    assert h.bucket_label == "6 h"


def test_histogram_all_time_caps_bucket_count():
    _log("/a/", ago=timedelta(days=400))
    _log("/b/")
    h = services.histogram(RequestLog.objects.all(), services.WINDOWS["all"])
    assert len(h.buckets) <= services.MAX_BUCKETS + 1
    assert h.total == 2


def test_user_rollup_and_ordering():
    a = User.objects.create_user("alice", password="x")
    b = User.objects.create_user("bob", password="x")
    for _ in range(3):
        _log("/p/", user=a, ms=100)
    _log("/q/", user=b, status=500, ms=10)
    _log("/anon/")
    rows = list(services.user_rollup(RequestLog.objects.all()))
    assert [r["user__username"] for r in rows] == ["alice", "bob"]
    assert rows[1]["errors"] == 1
    rows = list(services.user_rollup(RequestLog.objects.all(), ordering="-errors"))
    assert rows[0]["user__username"] == "bob"
    # unknown ordering fields are ignored, not 500s
    rows = list(services.user_rollup(RequestLog.objects.all(), ordering="password"))
    assert rows[0]["user__username"] == "alice"


def test_filters_narrow_and_report_active():
    rf = RequestFactory()
    f = services.parse_filters(rf.get("/", {"status": "4xx", "method": "post", "q": "api", "anon": "1"}))
    assert f.active and f.method == "POST"
    user = User.objects.create_user("u", password="x")
    _log("/api/a/", status=404, user=None)
    _log("/api/b/", status=404, user=user)
    _log("/web/", status=404)
    RequestLog.objects.update(method="POST")
    assert services.apply_filters(RequestLog.objects.all(), f).count() == 1
    exact = services.parse_filters(rf.get("/", {"path": "/web/"}))
    assert services.apply_filters(RequestLog.objects.all(), exact).count() == 1
    assert not services.parse_filters(rf.get("/")).active


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def test_flag_request_signatures():
    assert services.flag_request(RequestLog(path="/wp-login.php", status_code=404)) == ["probe path"]
    assert services.flag_request(RequestLog(path="/.env", status_code=404)) == ["probe path"]
    assert services.flag_request(RequestLog(path="/a/../../etc/passwd", status_code=400)) == ["probe path"]
    # A served page is never a probe, whatever its name.
    assert services.flag_request(RequestLog(path="/wp-login.php", status_code=200)) == []
    assert services.flag_request(RequestLog(path="/smallstack/", status_code=200)) == []
    assert services.flag_request(RequestLog(path="/x/", status_code=200, user_agent="Mozilla zgrab/0.1")) == [
        "scanner agent"
    ]
    # Generic tooling is not a scanner.
    assert services.flag_request(RequestLog(path="/api/", status_code=200, user_agent="python-requests/2.3")) == []


def test_probe_report_signature_hits_and_cluster():
    for p in ("/wp-login.php", "/.env", "/phpmyadmin/", "/xmlrpc.php"):
        _log(p, status=404, ip="203.0.113.9", ua="nikto/2.1")
    _log("/", status=200, ip="203.0.113.9", ua="nikto/2.1")  # its one non-error row
    _log("/", status=200, ip="10.0.0.1")  # unrelated legit traffic
    window = services.WINDOWS["24h"]
    report = services.probe_report(services.window_queryset(window), window)
    assert report.any
    assert report.signature_hits == 5  # 4 paths + the scanner-agent 200
    assert [c.ip for c in report.clusters] == ["203.0.113.9"]
    c = report.clusters[0]
    assert c.signatures == 4 and c.scanner == 5
    assert any("probe-path" in r for r in c.reasons) and "scanner user agent" in c.reasons
    assert c.severity in ("warning", "danger")
    assert {p["path"] for p in report.top_paths} >= {"/wp-login.php", "/.env"}
    assert "nikto/2.1" in {a["value"] for a in report.top_agents}


def test_behavioural_cluster_counts_only_its_error_rows():
    # 12 distinct 404s and 4 OK pages from one anonymous address.
    for i in range(12):
        _log(f"/missing-{i}/", status=404, ip="198.51.100.5", ua="")
    for i in range(4):
        _log(f"/ok-{i}/", status=200, ip="198.51.100.5", ua="")
    window = services.WINDOWS["24h"]
    qs = services.window_queryset(window)
    report = services.probe_report(qs, window)
    assert [c.ip for c in report.clusters] == ["198.51.100.5"]
    assert report.clusters[0].not_found_pct == 75
    assert report.signature_hits == 0
    # Only the 404s are evidence; the four OK rows are never swept in.
    assert report.flagged_requests == 12
    assert services.probe_requests(qs, report).filter(status_code=200).count() == 0
    flagged = services.annotate_probe_flags(list(qs), {"198.51.100.5"})
    assert sum(1 for r in flagged if r.probe_reasons) == 12


def test_denied_rule_is_a_ratio_not_a_count():
    # 15 denials in 300 requests (5%) — normal MCP/OAuth discovery, not a probe.
    for _ in range(15):
        _log("/mcp", status=401, ip="10.1.1.1")
    for i in range(285):
        _log("/", status=200, ip="10.1.1.1")
    window = services.WINDOWS["24h"]
    report = services.probe_report(services.window_queryset(window), window)
    assert not report.any
    # 15 denials in 30 requests (50%) — guessing.
    keep = list(RequestLog.objects.filter(status_code=200).values_list("pk", flat=True)[:15])
    RequestLog.objects.filter(status_code=200).exclude(pk__in=keep).delete()
    report = services.probe_report(services.window_queryset(window), window)
    assert [c.ip for c in report.clusters] == ["10.1.1.1"]
    assert any("denied" in r for r in report.clusters[0].reasons)


def test_signed_in_users_are_never_clusters():
    user = User.objects.create_user("curious", password="x")
    for i in range(20):
        _log(f"/typo-{i}/", status=404, user=user, ip="10.2.2.2")
    window = services.WINDOWS["24h"]
    report = services.probe_report(services.window_queryset(window), window)
    assert report.clusters == []


@override_settings(ACTIVITY_PROBE_PATTERNS_EXTRA=[r"/secret-sauce"], ACTIVITY_PROBE_IGNORE_PATHS=["/legacy.php"])
def test_patterns_are_extendable_and_exemptable():
    services.probe_patterns.cache_clear()
    services.combined_probe_pattern.cache_clear()
    services._compiled_pattern.cache_clear()
    try:
        assert services.flag_request(RequestLog(path="/secret-sauce/", status_code=404)) == ["probe path"]
        assert services.flag_request(RequestLog(path="/legacy.php", status_code=404)) == []
        _log("/legacy.php", status=404, ip="203.0.113.1")
        _log("/secret-sauce/", status=404, ip="203.0.113.1")
        assert RequestLog.objects.filter(services.probe_path_q()).count() == 1
    finally:
        services.probe_patterns.cache_clear()
        services.combined_probe_pattern.cache_clear()
        services._compiled_pattern.cache_clear()


def test_axes_failures_feed_the_report():
    from axes.models import AccessAttempt

    AccessAttempt.objects.create(
        username="admin",
        ip_address="203.0.113.44",
        user_agent="x",
        http_accept="*/*",
        path_info="/accounts/login/",
        failures_since_start=7,
    )
    window = services.WINDOWS["24h"]
    report = services.probe_report(services.window_queryset(window), window)
    assert [c.ip for c in report.clusters] == ["203.0.113.44"]
    assert "locked out by axes" in report.clusters[0].reasons
