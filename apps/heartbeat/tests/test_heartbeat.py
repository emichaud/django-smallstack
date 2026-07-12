"""Tests for the heartbeat app."""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.timezone import activate, deactivate, localdate, now

from apps.heartbeat import status as status_mod
from apps.heartbeat.forms import SLAForm
from apps.heartbeat.models import Heartbeat, HeartbeatEpoch, MonitoredEndpoint
from apps.heartbeat.services import run_all_monitors, run_monitor_check
from apps.heartbeat.status import _calc_overall_uptime, _calc_uptime, _sla_color

User = get_user_model()

EDT = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client


@pytest.fixture
def epoch(db):
    """Create an epoch 1 hour ago."""
    return HeartbeatEpoch.objects.create(
        started_at=now() - timedelta(hours=1),
        service_target=Decimal("99.9"),
        service_minimum=Decimal("99.5"),
    )


@pytest.fixture
def full_heartbeats(epoch):
    """Create heartbeats every 60s for the full epoch window (1 hour = 60 beats)."""
    base = epoch.started_at
    beats = []
    for i in range(60):
        beats.append(
            Heartbeat(
                status="ok",
                response_time_ms=1,
                timestamp=base + timedelta(seconds=i * 60),
            )
        )
    Heartbeat.objects.bulk_create(beats)
    return Heartbeat.objects.all()


# ─── Model tests ────────────────────────────────────────────────────


class TestHeartbeatEpoch:
    def test_get_epoch_returns_started_at(self, epoch):
        assert HeartbeatEpoch.get_epoch() == epoch.started_at

    def test_get_epoch_none_when_empty(self, db):
        assert HeartbeatEpoch.get_epoch() is None

    def test_get_sla_targets_defaults(self, db):
        target, minimum = HeartbeatEpoch.get_sla_targets()
        assert target == 99.9
        assert minimum == 99.5

    def test_get_sla_targets_from_config(self, epoch):
        target, minimum = HeartbeatEpoch.get_sla_targets()
        assert target == 99.9
        assert minimum == 99.5

    def test_reset_replaces_epoch(self, epoch):
        old_pk = epoch.pk
        new_epoch = HeartbeatEpoch.reset(
            started_at=now(),
            note="test reset",
            service_target=Decimal("99.95"),
            service_minimum=Decimal("99.9"),
        )
        assert HeartbeatEpoch.objects.count() == 1
        assert new_epoch.pk != old_pk
        assert new_epoch.note == "test reset"
        assert float(new_epoch.service_target) == 99.95

    def test_reset_preserves_targets_if_not_specified(self, epoch):
        new_epoch = HeartbeatEpoch.reset(note="just reset time")
        assert float(new_epoch.service_target) == 99.9
        assert float(new_epoch.service_minimum) == 99.5

    def test_ensure_epoch_creates_from_first_heartbeat(self, db):
        beat = Heartbeat.objects.create(status="ok", response_time_ms=1)
        epoch = HeartbeatEpoch.ensure_epoch()
        assert epoch is not None
        assert epoch.started_at == beat.timestamp

    def test_ensure_epoch_noop_when_exists(self, epoch):
        old_started = epoch.started_at
        result = HeartbeatEpoch.ensure_epoch()
        assert result.started_at == old_started


# ─── Uptime calculation tests ───────────────────────────────────────


class TestUptimeCalculation:
    def test_overall_uptime_100_percent(self, full_heartbeats):
        uptime = _calc_overall_uptime()
        assert uptime == 100.0

    def test_overall_uptime_none_without_epoch(self, db):
        assert _calc_overall_uptime() is None

    def test_overall_uptime_drops_with_gap(self, epoch):
        """If epoch is 1 hour ago but only 30 heartbeats exist, uptime ~50%."""
        base = epoch.started_at
        # Heartbeats only in the first 30 minutes of the 1-hour epoch
        for i in range(30):
            Heartbeat.objects.create(status="ok", response_time_ms=1, timestamp=base + timedelta(seconds=i * 60))
        uptime = _calc_overall_uptime()
        assert uptime is not None
        assert uptime < 100.0
        # ~30 ok out of ~60 expected = ~50%
        assert 40.0 < uptime < 60.0

    def test_calc_uptime_24h(self, epoch, full_heartbeats):
        uptime = _calc_uptime(24)
        assert uptime is not None
        assert uptime == 100.0

    def test_calc_uptime_clamps_to_epoch(self, db):
        """If epoch is 30 min ago, 24h uptime should only count from epoch."""
        epoch = HeartbeatEpoch.objects.create(
            started_at=now() - timedelta(minutes=30),
        )
        base = epoch.started_at
        for i in range(30):
            Heartbeat.objects.create(status="ok", response_time_ms=1, timestamp=base + timedelta(seconds=i * 60))
        uptime = _calc_uptime(24)
        assert uptime is not None
        assert uptime == 100.0

    def test_failures_reduce_uptime(self, epoch):
        """Mix of ok and fail heartbeats should reduce uptime."""
        base = epoch.started_at
        for i in range(60):
            status = "ok" if i < 50 else "fail"
            Heartbeat.objects.create(status=status, response_time_ms=1, timestamp=base + timedelta(seconds=i * 60))
        uptime = _calc_overall_uptime()
        assert uptime is not None
        # 50 ok out of ~60 expected = ~83%
        assert 75.0 < uptime < 90.0


# ─── SLA color tests ────────────────────────────────────────────────


class TestSLAColor:
    """Test _sla_color with use_target flag."""

    @pytest.fixture(autouse=True)
    def setup_epoch(self, db):
        HeartbeatEpoch.objects.create(
            started_at=now(),
            service_target=Decimal("99.9"),
            service_minimum=Decimal("99.5"),
        )

    def test_none_returns_quiet(self):
        assert _sla_color(None) == "var(--body-quiet-color)"

    # use_target=False (public/SLA pages): 2-tier
    def test_above_minimum_is_green(self):
        assert _sla_color(99.6, use_target=False) == "var(--success-fg)"

    def test_at_minimum_is_green(self):
        assert _sla_color(99.5, use_target=False) == "var(--success-fg)"

    def test_below_minimum_is_red(self):
        assert _sla_color(99.4, use_target=False) == "var(--error-fg)"

    def test_between_target_and_minimum_is_green_without_target(self):
        """Between target and minimum should be green when not using target."""
        assert _sla_color(99.7, use_target=False) == "var(--success-fg)"

    # use_target=True (dashboard): 3-tier
    def test_above_target_is_green_with_target(self):
        assert _sla_color(99.95, use_target=True) == "var(--success-fg)"

    def test_between_target_and_minimum_is_yellow_with_target(self):
        assert _sla_color(99.7, use_target=True) == "var(--warning-fg)"

    def test_below_minimum_is_red_with_target(self):
        assert _sla_color(99.4, use_target=True) == "var(--error-fg)"

    def test_at_target_is_green_with_target(self):
        assert _sla_color(99.9, use_target=True) == "var(--success-fg)"

    def test_at_minimum_is_yellow_with_target(self):
        assert _sla_color(99.5, use_target=True) == "var(--warning-fg)"


# ─── Form timezone tests ────────────────────────────────────────────


class TestSLAFormTimezone:
    """Test that the SLA form correctly handles timezones."""

    def test_form_returns_aware_datetime(self, db):
        """datetime-local input should produce a timezone-aware datetime."""
        activate(EDT)
        try:
            form = SLAForm(
                data={
                    "started_at": "2026-03-10T14:30",
                    "service_target": "99.9",
                    "service_minimum": "99.5",
                    "note": "",
                }
            )
            assert form.is_valid(), form.errors
            dt = form.cleaned_data["started_at"]
            assert dt.tzinfo is not None
        finally:
            deactivate()

    def test_form_datetime_interpreted_in_user_timezone(self, db):
        """2:30 PM with EDT active should be 6:30 PM UTC."""
        activate(EDT)
        try:
            form = SLAForm(
                data={
                    "started_at": "2026-03-10T14:30",
                    "service_target": "99.9",
                    "service_minimum": "99.5",
                    "note": "",
                }
            )
            assert form.is_valid(), form.errors
            dt = form.cleaned_data["started_at"]
            # Convert to UTC and check
            dt_utc = dt.astimezone(UTC)
            assert dt_utc.hour == 18  # 2:30 PM EDT = 6:30 PM UTC
            assert dt_utc.minute == 30
        finally:
            deactivate()

    def test_form_datetime_different_timezone(self, db):
        """Same local time in different timezone should produce different UTC."""
        activate(ZoneInfo("US/Pacific"))  # PDT = UTC-7
        try:
            form = SLAForm(
                data={
                    "started_at": "2026-03-10T14:30",
                    "service_target": "99.9",
                    "service_minimum": "99.5",
                    "note": "",
                }
            )
            assert form.is_valid(), form.errors
            dt = form.cleaned_data["started_at"]
            dt_utc = dt.astimezone(UTC)
            assert dt_utc.hour == 21  # 2:30 PM PDT = 9:30 PM UTC
        finally:
            deactivate()


# ─── View integration tests ─────────────────────────────────────────


class TestResetEpochView:
    def test_reset_epoch_saves_correct_timezone(self, staff_client, db):
        """Submitting the form should store the epoch in correct UTC."""
        # Activate EDT for the request
        activate(EDT)
        try:
            response = staff_client.post(
                reverse("heartbeat:reset_epoch"),
                data={
                    "started_at": "2026-03-10T14:30",
                    "service_target": "99.9",
                    "service_minimum": "99.5",
                    "note": "test",
                },
            )
            assert response.status_code == 302  # redirect
            epoch = HeartbeatEpoch.get_epoch()
            assert epoch is not None
            # Should be stored as 18:30 UTC
            epoch_utc = epoch.astimezone(UTC)
            assert epoch_utc.hour == 18
            assert epoch_utc.minute == 30
        finally:
            deactivate()

    def test_reset_epoch_forbidden_for_non_staff(self, client, db):
        user = User.objects.create_user(
            username="regular",
            password="testpass123",
        )
        client.force_login(user)
        response = client.post(
            reverse("heartbeat:reset_epoch"),
            data={
                "started_at": "2026-03-10T14:30",
                "service_target": "99.9",
                "service_minimum": "99.5",
            },
        )
        assert response.status_code == 403

    def test_uptime_100_after_reset_to_recent(self, staff_client, db):
        """Reset epoch to recent past + heartbeats = 100% uptime."""
        # Create heartbeats for the last 10 minutes
        base = now() - timedelta(minutes=10)
        for i in range(10):
            Heartbeat.objects.create(status="ok", response_time_ms=1, timestamp=base + timedelta(seconds=i * 60))
        # Set epoch to 10 minutes ago
        HeartbeatEpoch.objects.create(started_at=base)
        uptime = _calc_overall_uptime()
        assert uptime == 100.0


class TestStatusPages:
    def test_status_page_public(self, client, epoch, full_heartbeats):
        response = client.get(reverse("heartbeat:status"))
        assert response.status_code == 200

    def test_dashboard_requires_staff(self, client, db):
        response = client.get(reverse("heartbeat:dashboard"))
        assert response.status_code == 302  # redirect to login

    def test_sla_requires_staff(self, client, db):
        response = client.get(reverse("heartbeat:sla"))
        assert response.status_code == 302

    def test_dashboard_accessible_by_staff(self, staff_client, epoch, full_heartbeats):
        response = staff_client.get(reverse("heartbeat:dashboard"))
        assert response.status_code == 200

    def test_sla_accessible_by_staff(self, staff_client, epoch, full_heartbeats):
        response = staff_client.get(reverse("heartbeat:sla"))
        assert response.status_code == 200

    def test_status_json(self, client, epoch, full_heartbeats):
        response = client.get(reverse("heartbeat:status_json"))
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "operational"
        assert data["uptime_overall"] == 100.0
        assert data["sla_target"] == 99.9
        assert data["sla_minimum"] == 99.5

    def test_dashboard_uses_target_colors(self, staff_client, db):
        """Dashboard should use 3-tier coloring (green/yellow/red)."""
        # Epoch 100 minutes ago, target=100% (impossible), minimum=90%
        base = now() - timedelta(minutes=100)
        HeartbeatEpoch.objects.create(
            started_at=base,
            service_target=Decimal("100.00"),
            service_minimum=Decimal("90.0"),
        )
        # Create 95 ok beats → ~95% (below target 100%, above minimum 90%)
        for i in range(95):
            Heartbeat.objects.create(status="ok", response_time_ms=1, timestamp=base + timedelta(seconds=i * 60))
        response = staff_client.get(reverse("heartbeat:dashboard"))
        # Should show warning color (yellow) on dashboard — below target, above minimum
        assert response.context["uptime_overall_color"] == "var(--warning-fg)"

    def test_sla_uses_minimum_colors(self, staff_client, db):
        """SLA page should use 2-tier coloring (green/red only)."""
        base = now() - timedelta(minutes=100)
        HeartbeatEpoch.objects.create(
            started_at=base,
            service_target=Decimal("100.00"),
            service_minimum=Decimal("90.0"),
        )
        # Create 95 ok beats → ~95% (below target, above minimum)
        for i in range(95):
            Heartbeat.objects.create(status="ok", response_time_ms=1, timestamp=base + timedelta(seconds=i * 60))
        response = staff_client.get(reverse("heartbeat:sla"))
        # The uptime color values should be green (success), not yellow (warning).
        # Check the context directly — uptime_*_color should all be success-fg.
        assert response.context["uptime_overall_color"] == "var(--success-fg)"
        assert response.context["uptime_24h_color"] == "var(--success-fg)"
        assert response.context["uptime_7d_color"] == "var(--success-fg)"


# ─── Pluggable monitoring framework ──────────────────────────────────


class TestPerMonitorIsolation:
    """status.py helpers must scope strictly to their monitor_key."""

    def test_status_data_isolated_by_monitor(self, db):
        t = now().replace(second=0, microsecond=0)
        Heartbeat.objects.create(monitor_key="alpha", timestamp=t, status="ok", response_time_ms=5)
        Heartbeat.objects.create(monitor_key="beta", timestamp=t, status="fail")
        assert status_mod._get_status_data("alpha")["status"] == "operational"
        assert status_mod._get_status_data("beta")["status"] == "down"
        assert status_mod._get_status_data("missing")["status"] == "unknown"

    def test_timeline_isolated_by_monitor(self, db):
        t = now().replace(second=0, microsecond=0)
        Heartbeat.objects.create(monitor_key="alpha", timestamp=t, status="ok")
        alpha = [s for s in status_mod._build_24h_timeline("alpha") if s["total"]]
        beta = [s for s in status_mod._build_24h_timeline("beta") if s["total"]]
        assert len(alpha) == 1
        assert len(beta) == 0


class TestRunner:
    """run_monitor_check / run_all_monitors record one beat per monitor and isolate failures."""

    def test_run_monitor_check_records_ok_beat(self, db):
        from apps.smallstack.monitors import CheckResult, Monitor

        class OkMonitor(Monitor):
            key = "runner_ok"
            service = "s"

            def check(self) -> CheckResult:
                return CheckResult.up(9)

        res = run_monitor_check(OkMonitor())
        assert res["status"] == "ok"
        assert res["response_time_ms"] == 9
        assert Heartbeat.objects.filter(monitor_key="runner_ok", status="ok").count() == 1

    def test_raising_monitor_records_fail_beat(self, db):
        from apps.smallstack.monitors import Monitor

        class BoomMonitor(Monitor):
            key = "runner_boom"
            service = "s"

            def check(self):
                raise RuntimeError("kaboom")

        res = run_monitor_check(BoomMonitor())
        assert res["status"] == "fail"
        beat = Heartbeat.objects.get(monitor_key="runner_boom")
        assert beat.status == "fail"
        assert "kaboom" in beat.note

    def test_idempotent_within_minute(self, db):
        from apps.smallstack.monitors import CheckResult, Monitor

        class OkMonitor(Monitor):
            key = "runner_idem"
            service = "s"

            def check(self) -> CheckResult:
                return CheckResult.up()

        run_monitor_check(OkMonitor())
        run_monitor_check(OkMonitor())
        assert Heartbeat.objects.filter(monitor_key="runner_idem").count() == 1

    def test_run_all_monitors_isolates_failures(self, db, monkeypatch):
        from apps.smallstack import monitors as registry
        from apps.smallstack.monitors import CheckResult, Monitor

        class Good(Monitor):
            key = "all_good"
            service = "s"

            def check(self) -> CheckResult:
                return CheckResult.up()

        class Bad(Monitor):
            key = "all_bad"
            service = "s"

            def check(self):
                raise RuntimeError("x")

        monkeypatch.setattr(registry, "get_monitors", lambda service=None: [Good(), Bad()])
        res = run_all_monitors()
        assert res["all_good"]["status"] == "ok"
        assert res["all_bad"]["status"] == "fail"
        assert Heartbeat.objects.filter(monitor_key="all_good").exists()
        assert Heartbeat.objects.filter(monitor_key="all_bad", status="fail").exists()


class TestMonitoredEndpoint:
    """The user-created endpoint model + its dynamic monitor source."""

    def test_monitor_key_property(self, db):
        assert MonitoredEndpoint(slug="my-svc").monitor_key == "ep_my-svc"

    def test_clean_rejects_non_http_scheme(self, db):
        from django.core.exceptions import ValidationError

        ep = MonitoredEndpoint(name="x", slug="x", url="ftp://example.com/")
        with pytest.raises(ValidationError):
            ep.clean()

    def test_source_yields_enabled_only(self, db):
        MonitoredEndpoint.objects.create(name="On", slug="on", url="https://e.com/", enabled=True)
        MonitoredEndpoint.objects.create(name="Off", slug="off", url="https://e.com/", enabled=False)
        from apps.heartbeat.monitors import endpoint_monitor_source

        keys = [m.key for m in endpoint_monitor_source()]
        assert "ep_on" in keys
        assert "ep_off" not in keys

    def test_endpoint_monitor_passes_row_fields_to_check(self, db, monkeypatch):
        from apps.heartbeat import monitors as mon
        from apps.smallstack.monitors import CheckResult

        captured: dict = {}

        def fake_http(url, method, expected, timeout):
            captured.update(url=url, method=method, expected=expected, timeout=timeout)
            return CheckResult.up(1, "HTTP 204")

        monkeypatch.setattr(mon, "check_http_endpoint", fake_http)
        ep = MonitoredEndpoint.objects.create(
            name="E", slug="e", url="https://e.com/health", method="HEAD", expected_status=204, timeout_seconds=3
        )
        result = mon.EndpointMonitor(ep).check()
        assert result.ok
        assert captured == {"url": "https://e.com/health", "method": "HEAD", "expected": 204, "timeout": 3}


class TestStatusMonitorViews:
    """The overview, per-monitor detail, dev links, and endpoint CRUD pages."""

    def test_overview_lists_builtin_services(self, staff_client, db):
        response = staff_client.get(reverse("heartbeat:status_overview"))
        assert response.status_code == 200
        assert b"Site" in response.content

    def test_overview_requires_staff(self, client, db):
        assert client.get(reverse("heartbeat:status_overview")).status_code == 302

    def test_monitor_detail_renders_panels(self, staff_client, db):
        response = staff_client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "site"}))
        assert response.status_code == 200
        assert b"Timeline" in response.content

    def test_monitor_detail_uses_public_stacked_timelines(self, staff_client, db):
        # The Timeline panel renders the public-board stacked 1d/7d/90d format
        # (heartbeat/_site_timelines.html), not the old 24h + last-hour bars.
        body = staff_client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "site"})).content.decode()
        for window in ("Last 24 hours", "Last 7 days", "Last 90 days"):
            assert window in body
        assert "status-window" in body  # the shared partial's marker class
        assert "Last Hour" not in body  # the old per-minute panel is gone

    def test_stacked_timelines_helper_is_monitor_scoped(self, db):
        from apps.heartbeat.status import build_stacked_timelines

        rows = build_stacked_timelines("ep_anything")
        assert [r["window"] for r in rows] == ["Last 24 hours", "Last 7 days", "Last 90 days"]
        assert all("slots" in r for r in rows)

    def test_monitor_detail_unknown_returns_404(self, staff_client, db):
        response = staff_client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "nope-xyz"}))
        assert response.status_code == 404

    def test_overview_renders_hour_sparklines(self, staff_client, db):
        # One last-hour sparkline in the Site hero, plus a per-row column for
        # user monitors. The hero one stands in for the whole Site card.
        from apps.heartbeat.models import MonitoredEndpoint

        MonitoredEndpoint.objects.create(name="Spark EP", slug="spark-ep", service="custom", url="https://e.com/")
        body = staff_client.get(reverse("heartbeat:status_overview")).content.decode()
        assert "site-hero-spark" in body  # the hero sparkline line
        assert "hour-spark" in body
        assert "stat-spark" in body  # the per-row sparkline column

    def test_endpoint_crud_list_renders(self, staff_client, db):
        assert staff_client.get(reverse("heartbeat:status/endpoints-list")).status_code == 200


class TestSiteScopingAndConstraints:
    """Legacy site pages must not blend other monitors; one beat per monitor/minute."""

    def test_dashboard_counts_exclude_other_monitors(self, staff_client, db):
        t = now().replace(second=0, microsecond=0)
        Heartbeat.objects.create(monitor_key="site", timestamp=t, status="ok")
        Heartbeat.objects.create(monitor_key="api", timestamp=t, status="fail")
        response = staff_client.get(reverse("heartbeat:dashboard"))
        assert response.context["total_heartbeats"] == 1  # only the site beat
        assert response.context["fail_count"] == 0  # the api failure is excluded

    def test_unique_beat_per_monitor_minute(self, db):
        from django.db import IntegrityError, transaction

        t = now().replace(second=0, microsecond=0)
        Heartbeat.objects.create(monitor_key="site", timestamp=t, status="ok")
        with pytest.raises(IntegrityError), transaction.atomic():
            Heartbeat.objects.create(monitor_key="site", timestamp=t, status="ok")

    def test_same_minute_allowed_for_different_monitors(self, db):
        t = now().replace(second=0, microsecond=0)
        Heartbeat.objects.create(monitor_key="site", timestamp=t, status="ok")
        Heartbeat.objects.create(monitor_key="api", timestamp=t, status="ok")  # no collision
        assert Heartbeat.objects.filter(timestamp=t).count() == 2


class TestEndpointCRUD:
    """Create / edit / delete an endpoint monitor through the CRUD UI.

    The edit case is the regression guard for the DETAIL-less get_success_url
    500 (NoReverseMatch on the missing `-detail` route).
    """

    def _payload(self, **over) -> dict:
        data = {
            "mode": "custom",
            "name": "E",
            "slug": "e-crud",
            "url": "https://example.com/",
            "method": "GET",
            "expected_status": "200",
            "timeout_seconds": "5",
        }
        data.update(over)
        return data

    def test_create_redirects_and_persists(self, staff_client, db):
        response = staff_client.post(reverse("heartbeat:status/endpoints-create"), self._payload())
        assert response.status_code == 302
        assert MonitoredEndpoint.objects.filter(slug="e-crud").exists()

    def test_edit_redirects_to_list_not_500(self, staff_client, db):
        ep = MonitoredEndpoint.objects.create(name="E", slug="e-crud", service="custom", url="https://example.com/")
        response = staff_client.post(
            reverse("heartbeat:status/endpoints-update", kwargs={"pk": ep.pk}),
            self._payload(name="Edited", public="on"),
        )
        assert response.status_code == 302  # was 500: NoReverseMatch on the missing -detail route
        ep.refresh_from_db()
        assert ep.name == "Edited"
        assert ep.public is True

    def test_delete_removes_row(self, staff_client, db):
        ep = MonitoredEndpoint.objects.create(name="E", slug="e-crud", service="custom", url="https://example.com/")
        response = staff_client.post(reverse("heartbeat:status/endpoints-delete", kwargs={"pk": ep.pk}))
        assert response.status_code == 302
        assert not MonitoredEndpoint.objects.filter(pk=ep.pk).exists()

    def test_list_row_links_to_monitor_detail_not_edit(self, staff_client, db):
        MonitoredEndpoint.objects.create(name="Docs site", slug="docs-site", service="custom", url="https://d/health/")
        body = staff_client.get(reverse("heartbeat:status/endpoints-list")).content.decode()
        detail = reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "ep_docs-site"})
        assert f'<a href="{detail}">Docs site</a>' in body  # name links to the timeline

    def test_form_ignores_posted_service_defaults_external(self, staff_client, db):
        # The Tier picker is gone — a posted ``service`` is ignored and the endpoint
        # lands in the default "custom" (External Monitors) tier.
        response = staff_client.post(
            reverse("heartbeat:status/endpoints-create"), self._payload(service="nonexistent-svc")
        )
        assert response.status_code == 302  # created, redirects to the list
        assert MonitoredEndpoint.objects.get(slug="e-crud").service == "custom"


class TestRetentionAwareUptime:
    """Overall/7d uptime must fold pruned HeartbeatDaily, not divide recent beats
    by an epoch-length denominator (the >retention-window drift bug)."""

    def test_overall_folds_pruned_daily_summaries(self, db):
        import datetime

        from apps.heartbeat.models import HeartbeatDaily
        from apps.heartbeat.status import _calc_overall_uptime, _calc_uptime

        # Epoch 25 days ago; only ~2h of recent raw beats survive retention.
        HeartbeatEpoch.objects.create(started_at=now() - timedelta(days=25))
        base = now().replace(second=0, microsecond=0) - timedelta(hours=2)
        Heartbeat.objects.bulk_create(
            [Heartbeat(status="ok", response_time_ms=1, timestamp=base + timedelta(minutes=i)) for i in range(120)]
        )
        # Pruned days are preserved as 100% daily summaries.
        HeartbeatDaily.objects.bulk_create(
            [
                HeartbeatDaily(
                    date=datetime.date.today() - timedelta(days=d),
                    ok_count=1440,
                    expected_count=1440,
                    uptime_pct=100,
                )
                for d in range(2, 25)
            ]
        )
        # Was ~4% before the fix; now reflects the real ~100%.
        assert _calc_overall_uptime() > 99.0
        assert _calc_uptime(168) > 99.0


class TestPublicStatusBoard:
    """The public /status/ board shows only public monitors; internals are hidden."""

    def test_public_overview_shows_only_public_monitors(self, client, db):
        response = client.get(reverse("heartbeat:status"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "SmallStack Status" in body  # branded header; site labelled by brand name
        assert "MCP Server" not in body  # mcp is internal — hidden publicly
        assert "Manage endpoints" not in body  # staff chrome hidden on the public board

    def test_public_root_status_page_renders(self, client, db):
        assert client.get(reverse("public_status")).status_code == 200

    def test_anon_can_view_public_monitor_detail(self, client, db):
        assert client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "site"})).status_code == 200

    def test_anon_cannot_view_internal_monitor_detail(self, client, db):
        # 404 (not 403) so an internal monitor isn't even disclosed to anon.
        assert client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "mcp"})).status_code == 404

    def test_staff_can_view_internal_monitor_detail(self, staff_client, db):
        assert staff_client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "mcp"})).status_code == 200

    def test_status_json_lists_public_monitors_only(self, client, db):
        keys = [m["key"] for m in client.get(reverse("heartbeat:status_json")).json()["monitors"]]
        assert "site" in keys
        assert "mcp" not in keys

    def test_public_board_renders_stacked_timelines(self, client, db):
        resp = client.get(reverse("public_status"))
        assert resp.status_code == 200
        windows = resp.context["site_timelines"]
        # Top-to-bottom: 1 day, 7 day, 90 day.
        assert [w["window"] for w in windows] == ["Last 24 hours", "Last 7 days", "Last 90 days"]
        assert len(windows[0]["slots"]) == 24  # hourly
        assert len(windows[1]["slots"]) == 168  # hourly over 7 days
        assert len(windows[2]["slots"]) == 90  # daily
        assert "day-bar" in resp.content.decode()

    def test_public_board_is_standalone_no_admin_sidebar(self, client, db):
        body = client.get(reverse("public_status")).content.decode()
        assert "main-content" not in body  # not the admin shell
        assert "SmallStack Status" in body


class TestDailyTimeline:
    """The 90-day daily timeline backing the public board."""

    def test_returns_one_slot_per_day_oldest_first(self, db):
        slots = status_mod._build_daily_timeline(days=90)
        assert len(slots) == 90
        assert slots[0]["date"] < slots[-1]["date"]
        assert all({"date", "status", "uptime", "label"} <= set(s) for s in slots)

    def test_classifies_days_against_sla(self, db):
        from apps.heartbeat.models import HeartbeatDaily

        today = localdate()
        HeartbeatDaily.objects.create(
            monitor_key="site", date=today, ok_count=1440, expected_count=1440, uptime_pct=100
        )
        HeartbeatDaily.objects.create(
            monitor_key="site", date=today - timedelta(days=1), ok_count=700, expected_count=1440, uptime_pct=48
        )
        by_date = {s["date"]: s for s in status_mod._build_daily_timeline(days=90)}
        assert by_date[today]["status"] == "up"
        assert by_date[today - timedelta(days=1)]["status"] == "down"


class TestCalendarView:
    """The rolling 3-month calendar on the public board."""

    def test_builds_three_months_oldest_first(self, db):
        months = status_mod._build_calendar_months("site", 2026, 6, months=3)
        assert [(m["year"], m["month"]) for m in months] == [(2026, 4), (2026, 5), (2026, 6)]
        # each month is weeks of 7 cells
        assert all(len(week) == 7 for m in months for week in m["weeks"])

    def test_maintenance_day_flagged_with_details(self, db):
        from datetime import datetime

        from django.utils.timezone import make_aware

        from apps.heartbeat.models import MaintenanceWindow

        today = localdate()
        start = make_aware(datetime(today.year, today.month, today.day, 1, 0))
        MaintenanceWindow.objects.create(
            monitor_key="site", title="DB upgrade", start=start, end=start + timedelta(hours=2)
        )
        months = status_mod._build_calendar_months("site", today.year, today.month, months=1)
        cells = [c for m in months for w in m["weeks"] for c in w if c and c.get("date") == today]
        assert cells and cells[0]["status"] == "maintenance"
        assert cells[0]["maintenance"][0]["title"] == "DB upgrade"

    def test_public_board_renders_calendar(self, client, db):
        resp = client.get(reverse("public_status"))
        assert resp.status_code == 200
        assert len(resp.context["calendar_months"]) == 3
        assert "cal-cell" in resp.content.decode()

    def test_calendar_nav_param(self, client, db):
        resp = client.get(reverse("public_status") + "?cal=2026-03")
        months = resp.context["calendar_months"]
        assert (months[-1]["year"], months[-1]["month"]) == (2026, 3)
        assert resp.context["cal_next"] is not None  # a past range can page forward


class TestHourlyTimeline:
    """The short-term (1d / 7d) hourly timeline."""

    def test_returns_one_slot_per_hour(self, db):
        assert len(status_mod._build_hourly_timeline(hours=24)) == 24
        assert len(status_mod._build_hourly_timeline(hours=168)) == 168

    def test_failures_not_completeness_drive_status(self, db):
        # A stalled runner (no beats) reads "nodata", not "down".
        slots = status_mod._build_hourly_timeline(hours=3)
        assert all(s["status"] == "nodata" for s in slots)
        # A failure in the last hour reads "down".
        Heartbeat.objects.create(monitor_key="site", status="fail", timestamp=now())
        last = status_mod._build_hourly_timeline(hours=1)[-1]
        assert last["status"] == "down"


class TestPublicMaintenancePage:
    """The public scheduled-maintenance page + its link from the status board."""

    def _make_window(self, **kw):


        from apps.heartbeat.models import MaintenanceWindow

        defaults = dict(monitor_key="site", title="Upgrade")
        defaults.update(kw)
        return MaintenanceWindow.objects.create(**defaults)

    def test_upcoming_lists_future_and_in_progress(self, db):
        current = now()
        self._make_window(title="Soon", start=current + timedelta(days=3), end=current + timedelta(days=3, hours=2))
        self._make_window(title="Live now", start=current - timedelta(hours=1), end=current + timedelta(hours=1))
        self._make_window(title="Long past", start=current - timedelta(days=10), end=current - timedelta(days=10))
        titles = [w["title"] for w in status_mod._upcoming_maintenance(90)]
        assert "Soon" in titles and "Live now" in titles
        assert "Long past" not in titles  # already finished

    def test_maintenance_page_renders(self, client, db):
        self._make_window(title="DB upgrade", start=now() + timedelta(days=2), end=now() + timedelta(days=2, hours=1))
        resp = client.get(reverse("public_maintenance"))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Scheduled Maintenance" in body
        assert "DB upgrade" in body

    def test_status_page_links_to_maintenance(self, client, db):
        body = client.get(reverse("public_status")).content.decode()
        assert reverse("public_maintenance") in body
        assert "Scheduled maintenance" in body


class TestMaintenanceCalendar:
    """The 6-month maintenance-only calendar."""

    def test_builds_six_months_marking_maintenance_and_today(self, db):
        from datetime import datetime

        from django.utils.timezone import make_aware

        from apps.heartbeat.models import MaintenanceWindow

        today = localdate()
        s = make_aware(datetime(today.year, today.month, today.day, 1, 0))
        MaintenanceWindow.objects.create(monitor_key="site", title="Patch", start=s, end=s + timedelta(hours=1))

        months = status_mod._build_maintenance_calendar(months_back=2, months_forward=3)
        assert len(months) == 6  # 2 back + current + 3 forward
        cells = [c for m in months for w in m["weeks"] for c in w if c]
        today_cell = next(c for c in cells if c.get("is_today"))
        assert today_cell["maintenance"]  # the window seeded for today is flagged
        assert sum(m["count"] for m in months) >= 1

    def test_calendar_page_renders_and_cross_links(self, client, db):
        resp = client.get(reverse("public_maintenance_calendar"))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Maintenance Calendar" in body
        assert reverse("public_maintenance") in body  # links back to the list

    def test_list_page_links_to_calendar(self, client, db):
        body = client.get(reverse("public_maintenance")).content.decode()
        assert reverse("public_maintenance_calendar") in body


class TestEndpointWizardForm:
    """The polished Add-monitor form: SmallStack shortcut + custom mode + auto-slug."""

    def _form(self, **overrides):
        from apps.heartbeat.forms import MonitoredEndpointForm

        data = {
            "mode": "smallstack",
            "name": "Prod Site",
            "url": "https://example.com",
            # hidden custom-mode defaults the template would submit
            "method": "GET",
            "expected_status": "200",
            "timeout_seconds": "10",
            "service": "custom",
            "enabled": "on",
        }
        data.update(overrides)
        return MonitoredEndpointForm(data)

    def test_smallstack_mode_targets_health(self, db):
        form = self._form(mode="smallstack", name="Prod", url="https://ex.com")
        assert form.is_valid(), form.errors
        ep = form.save()
        assert ep.url == "https://ex.com/health/"
        assert ep.method == "GET"
        assert ep.expected_status == 200
        assert ep.service == "custom"
        assert ep.enabled is True

    def test_smallstack_strips_trailing_slash(self, db):
        form = self._form(mode="smallstack", name="X", url="https://ex.com/")
        assert form.is_valid(), form.errors
        assert form.save().url == "https://ex.com/health/"

    def test_auto_slug_from_name(self, db):
        form = self._form(name="My Cool Site", url="https://a.com")
        assert form.is_valid(), form.errors
        assert form.save().slug == "my-cool-site"

    def test_auto_slug_dedupes(self, db):
        MonitoredEndpoint.objects.create(name="Dup", slug="dup", service="custom", url="https://x.com/health/")
        form = self._form(name="Dup", url="https://y.com")
        assert form.is_valid(), form.errors
        assert form.save().slug == "dup-2"

    def test_custom_mode_keeps_url_and_method(self, db):
        form = self._form(mode="custom", name="Router", url="https://device.local/api", method="HEAD",
                          expected_status="204", service="custom", slug="router")
        assert form.is_valid(), form.errors
        ep = form.save()
        assert ep.url == "https://device.local/api"  # not rewritten to /health/
        assert ep.method == "HEAD"
        assert ep.expected_status == 204

    def test_create_page_uses_segmented_radio_not_dropdown(self, staff_client, db):
        body = staff_client.get(reverse("heartbeat:status/endpoints-create")).content.decode()
        assert 'type="radio" name="method"' in body
        assert '<select name="method"' not in body
        assert 'type="radio" name="mode"' in body  # the SmallStack/Custom toggle is rendered

    def test_edit_page_hides_mode_toggle(self, staff_client, db):
        ep = MonitoredEndpoint.objects.create(name="E", slug="e", service="custom", url="https://e.com/health/")
        body = staff_client.get(reverse("heartbeat:status/endpoints-update", kwargs={"pk": ep.pk})).content.decode()
        assert 'type="radio" name="mode"' not in body  # no SmallStack/Custom toggle when editing


class TestDetailGridBooleanRendering:
    """Regression (base smallstack): DetailGridDisplay must render False booleans
    as raw values so the template shows '—', not '✓'.

    Bug: ``_get_field_value`` pre-rendered a bool to a "✓"/"—" *string*, which
    ``detail_grid.html`` then re-tested as truthy → every boolean (e.g. an
    endpoint's ``public=False``) displayed ✓. Surfaced on the Explorer detail page.
    """

    def test_false_boolean_passes_through_raw(self, db):
        from apps.heartbeat.views import MonitoredEndpointCRUDView
        from apps.smallstack.displays import DetailGridDisplay

        ep = MonitoredEndpoint.objects.create(
            name="h", slug="h-grid", service="custom", url="https://h/health/", public=False, enabled=True
        )
        ctx = DetailGridDisplay().get_context(ep, MonitoredEndpointCRUDView, None)
        rows = {r["label"]: r for r in ctx["field_rows"]}
        # Raw booleans, not pre-rendered "✓"/"—" strings.
        assert rows["Public"]["value"] is False and rows["Public"]["is_bool"] is True
        assert rows["Enabled"]["value"] is True and rows["Enabled"]["is_bool"] is True

    def test_template_renders_false_as_dash(self, db):
        from django.template.loader import render_to_string

        from apps.heartbeat.views import MonitoredEndpointCRUDView
        from apps.smallstack.displays import DetailGridDisplay

        ep = MonitoredEndpoint.objects.create(
            name="h", slug="h-grid2", service="custom", url="https://h/health/", public=False, enabled=True
        )
        ctx = DetailGridDisplay().get_context(ep, MonitoredEndpointCRUDView, None)
        html = render_to_string("smallstack/crud/displays/detail_grid.html", ctx)
        pub_cell = html[html.find("Public") : html.find("Public") + 240]
        assert "—" in pub_cell and "&#10003;" not in pub_cell  # False → dash, not check


class TestVerifySmallStack:
    """The non-blocking /health/ verify probe."""

    def _fake_urlopen(self, status, body):
        import json

        class FakeResp:
            def __init__(s):
                s.status = status

            def read(s, n=None):
                return json.dumps(body).encode() if isinstance(body, dict) else body

            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

        return lambda req, timeout=5: FakeResp()

    def test_requires_staff(self, client, db):
        assert client.post(reverse("heartbeat:verify_smallstack"), {"url": "https://e.com"}).status_code == 403

    def test_verified_for_smallstack_health(self, staff_client, db, monkeypatch):
        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", self._fake_urlopen(200, {"status": "ok", "database": "ok"}))
        body = staff_client.post(reverse("heartbeat:verify_smallstack"), {"url": "https://e.com"}).content.decode()
        assert "verify-ok" in body and "Verified" in body

    def test_unverified_for_wrong_shape(self, staff_client, db, monkeypatch):
        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", self._fake_urlopen(200, {"hello": "world"}))
        body = staff_client.post(reverse("heartbeat:verify_smallstack"), {"url": "https://e.com"}).content.decode()
        assert "verify-bad" in body

    def test_rejects_missing_scheme(self, staff_client, db):
        body = staff_client.post(reverse("heartbeat:verify_smallstack"), {"url": "example.com"}).content.decode()
        assert "verify-bad" in body


class TestCoverageAndWarmup:
    """Data-coverage signal (O1) + warming-up display (O3)."""

    def test_coverage_full_when_continuous(self, epoch):
        base = epoch.started_at
        Heartbeat.objects.bulk_create(
            [Heartbeat(status="ok", response_time_ms=1, timestamp=base + timedelta(seconds=i * 60)) for i in range(60)]
        )
        cov = status_mod._coverage_since_epoch()
        assert cov is not None and cov > 0.9

    def test_coverage_drops_with_uncovered_gap(self, db):
        # Epoch 20d ago, raw beats only the last 2h, no daily summaries for the gap.
        HeartbeatEpoch.objects.create(started_at=now() - timedelta(days=20))
        base = now().replace(second=0, microsecond=0) - timedelta(hours=2)
        Heartbeat.objects.bulk_create(
            [Heartbeat(status="ok", timestamp=base + timedelta(minutes=i)) for i in range(120)]
        )
        cov = status_mod._coverage_since_epoch()
        assert cov is not None and cov < 0.1  # ~2h / 20d
        # ...but overall uptime is NOT penalized for the uncovered span.
        assert (status_mod._calc_overall_uptime() or 0) > 99.0

    def test_warming_up_for_young_monitor(self, db):
        from apps.heartbeat.views import _monitor_overview_state
        from apps.smallstack.monitors import Monitor

        HeartbeatEpoch.objects.create(monitor_key="young", started_at=now() - timedelta(minutes=5))
        Heartbeat.objects.create(monitor_key="young", status="ok")

        class Young(Monitor):
            key = "young"
            service = "s"

        state = _monitor_overview_state(Young())
        assert state["warming_up"] is True
        assert state["uptime_24h"] is None  # suppressed while warming up

    def test_aged_monitor_not_warming_up(self, db):
        from apps.heartbeat.views import _monitor_overview_state
        from apps.smallstack.monitors import Monitor

        HeartbeatEpoch.objects.create(monitor_key="aged", started_at=now() - timedelta(hours=3))
        t = now().replace(second=0, microsecond=0)
        Heartbeat.objects.bulk_create(
            [Heartbeat(monitor_key="aged", timestamp=t - timedelta(minutes=i), status="ok") for i in range(120)]
        )

        class Aged(Monitor):
            key = "aged"
            service = "s"

        assert _monitor_overview_state(Aged())["warming_up"] is False


class TestEndpointFormAndJson:
    """N2 service select + O2 status_json shape."""

    def test_endpoint_form_has_no_tier_field(self, db):
        # The Tier/service picker was removed — user endpoints default to the model's
        # "custom" (External Monitors) tier; the field is no longer on the form.
        from apps.heartbeat.forms import MonitoredEndpointForm

        assert "service" not in MonitoredEndpointForm().fields

    def test_new_endpoint_defaults_to_external_monitors(self, db):
        ep = MonitoredEndpoint.objects.create(name="Probe", slug="probe", url="https://x.com/health/")
        assert ep.service == "custom"

    def test_status_json_shape(self, client, epoch, full_heartbeats):
        data = client.get(reverse("heartbeat:status_json")).json()
        assert "generated_at" in data
        assert "uptime_overall" in data and "sla_target" in data  # site top-level retained
        site = next(m for m in data["monitors"] if m["key"] == "site")
        assert {"key", "service", "title", "status", "uptime_24h", "uptime_7d", "uptime_overall"} <= set(site)


# ─── Polish + CRUDView-alignment pass (banners, breadcrumbs, API/MCP, per-monitor SLA) ───


class TestRunnerHealthBanner:
    """Stale-heartbeat self-diagnostic (3a) — tell the user when the runner stops."""

    def test_no_beats_reports_never_run(self, db):
        from apps.heartbeat.views import _runner_health

        h = _runner_health()
        assert h["runner_never_run"] is True
        assert h["runner_stale"] is False

    def test_fresh_beat_not_stale(self, db):
        from apps.heartbeat.views import _runner_health

        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now())
        h = _runner_health()
        assert h["runner_never_run"] is False
        assert h["runner_stale"] is False

    def test_old_beat_is_stale(self, db):
        from apps.heartbeat.views import _runner_health

        # Settings interval is 60s; > 5× (300s) old → stale.
        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now() - timedelta(minutes=10))
        h = _runner_health()
        assert h["runner_stale"] is True
        assert h["runner_last_beat_age_minutes"] >= 9

    def test_overview_renders_stale_banner_for_staff(self, staff_client):
        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now() - timedelta(minutes=10))
        html = staff_client.get(reverse("heartbeat:status_overview")).content.decode()
        assert "per-minute check may not be running" in html

    def test_public_board_never_shows_stale_banner(self, client, db):
        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now() - timedelta(minutes=10))
        html = client.get(reverse("heartbeat:status")).content.decode()
        assert "per-minute check may not be running" not in html


class TestOverallHealthBanner:
    """At-a-glance health roll-up (B3.1)."""

    def test_operational_when_site_ok(self, db):
        from apps.heartbeat.views import _status_overview_context

        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now())
        ctx = _status_overview_context()
        assert ctx["overall_state"] == "operational"
        assert ctx["overall_down_count"] == 0

    def test_down_when_endpoint_failing(self, db):
        from apps.heartbeat.views import _status_overview_context

        MonitoredEndpoint.objects.create(name="Foo", slug="foo", service="custom", url="https://example.com")
        Heartbeat.objects.create(monitor_key="ep_foo", status="fail", timestamp=now())
        ctx = _status_overview_context()
        assert ctx["overall_state"] == "down"
        assert ctx["overall_down_count"] == 1

    def test_unknown_when_no_data(self, db):
        from apps.heartbeat.views import _status_overview_context

        ctx = _status_overview_context()
        assert ctx["overall_state"] == "unknown"


class TestStatusBreadcrumbs:
    """Consistent 'Status / …' rooting (B1)."""

    def test_crudview_breadcrumb_parent(self):
        from apps.heartbeat.views import MonitoredEndpointCRUDView

        assert MonitoredEndpointCRUDView.breadcrumb_parent == ("Status", "heartbeat:status_overview")

    def test_endpoint_list_roots_at_status(self, staff_client):
        html = staff_client.get(reverse("heartbeat:status/endpoints-list")).content.decode()
        assert reverse("heartbeat:status_overview") in html

    def test_sla_breadcrumb_links_overview(self, staff_client, epoch):
        html = staff_client.get(reverse("heartbeat:sla")).content.decode()
        assert reverse("heartbeat:status_overview") in html


class TestMonitoredEndpointApiMcp:
    """CRUDView magic on the monitoring model (§4)."""

    def test_in_api_registry(self):
        from apps.smallstack.api import _api_registry

        names = [name for _, name in _api_registry]
        assert "heartbeat:status-endpoints-api-list" in names

    def test_api_list_url_reverses(self):
        # Namespaced reverse must resolve (the bug the registry-namespace fix closed).
        assert reverse("heartbeat:status-endpoints-api-list")

    def test_mcp_tools_registered(self):
        # Re-register from the factory (idempotent) rather than relying on the live
        # TOOL_REGISTRY state — the MCP suite's clean_registry fixture wipes it, so a
        # bare read would be test-order-dependent.
        from apps.heartbeat.views import MonitoredEndpointCRUDView
        from apps.mcp.factory import register_mcp_tools_from_crudview

        assert MonitoredEndpointCRUDView.enable_mcp is True
        names = register_mcp_tools_from_crudview(MonitoredEndpointCRUDView)
        assert "list_status_endpoints" in names
        assert "create_monitored_endpoint" in names
        assert "delete_monitored_endpoint" in names

    def test_api_list_returns_rows_for_staff(self, staff_client, db):
        MonitoredEndpoint.objects.create(name="Foo", slug="foo", service="custom", url="https://example.com")
        resp = staff_client.get(reverse("heartbeat:status-endpoints-api-list"))
        assert resp.status_code == 200


class TestServiceDropdownDefault:
    """User endpoints default to the 'custom' (External Monitors) tier."""

    def test_service_defaults_to_custom_on_model(self, db):
        from apps.heartbeat.models import MonitoredEndpoint

        assert MonitoredEndpoint._meta.get_field("service").default == "custom"


class TestPerMonitorSLA:
    """Per-monitor SLA editor (A2) — surface the dormant per-monitor epoch."""

    def test_resolve_unknown_monitor_falls_back_to_site(self):
        from apps.heartbeat.views import _resolve_status_monitor

        key, _ = _resolve_status_monitor("does-not-exist")
        assert key == "site"

    def test_reset_writes_per_monitor_epoch(self, staff_client, db):
        MonitoredEndpoint.objects.create(name="Foo", slug="foo", service="custom", url="https://example.com")
        resp = staff_client.post(
            reverse("heartbeat:reset_epoch"),
            {
                "monitor": "ep_foo",
                "started_at": "2026-01-01T00:00",
                "service_target": "99.5",
                "service_minimum": "99.0",
            },
        )
        assert resp.status_code == 302
        assert "monitor=ep_foo" in resp["Location"]
        ep_epoch = HeartbeatEpoch.objects.get(monitor_key="ep_foo")
        assert float(ep_epoch.service_target) == 99.5
        # Site epoch is untouched (none created for it).
        assert not HeartbeatEpoch.objects.filter(monitor_key="site").exists()

    def test_sla_page_scopes_to_monitor(self, staff_client, db):
        MonitoredEndpoint.objects.create(name="Foo", slug="foo", service="custom", url="https://example.com")
        Heartbeat.objects.create(monitor_key="ep_foo", status="ok", timestamp=now())
        resp = staff_client.get(reverse("heartbeat:sla") + "?monitor=ep_foo")
        assert resp.status_code == 200
        assert resp.context["monitor_key"] == "ep_foo"
        assert resp.context["is_site_sla"] is False

    def test_monitor_detail_has_edit_and_sla_links_for_endpoint(self, staff_client, db):
        MonitoredEndpoint.objects.create(name="Foo", slug="foo", service="custom", url="https://example.com")
        resp = staff_client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "ep_foo"}))
        assert resp.context["edit_url"] is not None
        assert "monitor=ep_foo" in resp.context["sla_url"]

    def test_site_monitor_detail_has_no_edit_link(self, staff_client, db):
        resp = staff_client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "site"}))
        assert resp.context["edit_url"] is None
        assert resp.context["sla_url"] is not None


# ─── 3-tier taxonomy (Site / Site Monitors / External Monitors) ───


class TestCategoryTaxonomy:
    """Service.category + the 3-section overview grouping."""

    def test_service_category_default_is_core(self):
        from apps.smallstack.monitors import Service

        assert Service.category == "core"

    def test_core_services_resolve_to_core(self):
        from apps.smallstack.monitors import get_service

        for key in ("site", "api", "mcp", "search"):
            svc = get_service(key)
            assert svc is not None, f"{key} service not registered"
            assert svc.category == "core"

    def test_external_service_reframed_keeps_custom_key(self):
        from apps.smallstack.monitors import get_service

        svc = get_service("custom")
        assert svc is not None
        assert svc.category == "external"
        assert svc.title == "External Monitors"

    def test_internal_service_registered(self):
        from apps.smallstack.monitors import get_service

        svc = get_service("internal")
        assert svc is not None
        assert svc.category == "internal"
        assert svc.title == "Site Monitors"

    def test_overview_groups_into_three_ordered_tiers(self, db):
        from apps.heartbeat.views import _status_overview_context

        ctx = _status_overview_context()
        cats = {c["key"]: c for c in ctx["categories"]}
        assert {"core", "internal", "external"} <= set(cats)
        # Ordered Site → Site Monitors → External Monitors.
        keys_in_order = [c["key"] for c in ctx["categories"]]
        assert keys_in_order.index("core") < keys_in_order.index("internal") < keys_in_order.index("external")
        assert cats["core"]["label"] == "Site"
        assert cats["internal"]["label"] == "Site Monitors"
        assert cats["external"]["label"] == "External Monitors"

    def test_category_label_not_clobbered_by_state_label(self, db):
        # The tier label ("Site") must stay distinct from the rolled-up state label.
        from apps.heartbeat.views import _status_overview_context

        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now())
        core = next(c for c in _status_overview_context()["categories"] if c["key"] == "core")
        assert core["label"] == "Site"
        assert core["state_label"] in {"Operational", "Degraded", "Down", "No data"}

    def test_category_rollup_state(self, db):
        from apps.heartbeat.views import _status_overview_context

        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now())
        core = next(c for c in _status_overview_context()["categories"] if c["key"] == "core")
        assert core["state"] == "operational"

    def test_overall_keys_preserved(self, db):
        # The dashboard banners depend on these — grouping must be purely additive.
        from apps.heartbeat.views import _status_overview_context

        ctx = _status_overview_context()
        for key in ("services", "service_count", "monitor_count", "overall_state", "overall_variant"):
            assert key in ctx

    def test_public_board_drops_empty_internal_external(self, db):
        from apps.heartbeat.views import _status_overview_context

        Heartbeat.objects.create(monitor_key="site", status="ok", timestamp=now())
        ctx = _status_overview_context(public_only=True)
        cat_keys = {c["key"] for c in ctx["categories"]}
        # Internal/external have no public monitors → not shown publicly; core is.
        assert "core" in cat_keys
        assert "internal" not in cat_keys
        assert "external" not in cat_keys

    def test_status_json_includes_category(self, client, epoch, full_heartbeats):
        data = client.get(reverse("heartbeat:status_json")).json()
        site = next(m for m in data["monitors"] if m["key"] == "site")
        assert site["category"] == "core"

    def test_overview_renders_three_section_headers(self, staff_client, db):
        html = staff_client.get(reverse("heartbeat:status_overview")).content.decode()
        assert "Site Monitors" in html
        assert "External Monitors" in html

    def test_core_tier_collapses_to_one_row_per_surface(self, db):
        # Each core service (Site/api/mcp/search) is one rolled-up row, not its own card.
        from apps.heartbeat.views import _status_overview_context

        core = next(c for c in _status_overview_context()["categories"] if c["key"] == "core")
        labels = {r["label"] for r in core["rows"]}
        assert {"Site", "REST API", "MCP Server", "Search"} <= labels
        # One row per core service, each carrying exactly one check today.
        assert all(r["check_count"] == 1 for r in core["rows"])

    def test_external_tier_lists_one_row_per_endpoint(self, db):
        from apps.heartbeat.views import _status_overview_context

        MonitoredEndpoint.objects.create(name="Foo", slug="foo", service="custom", url="https://example.com")
        MonitoredEndpoint.objects.create(name="Bar", slug="bar", service="custom", url="https://example.org")
        external = next(c for c in _status_overview_context()["categories"] if c["key"] == "external")
        labels = {r["label"] for r in external["rows"]}
        assert {"Foo", "Bar"} <= labels  # each endpoint is its own surface row


class TestSiteCard:
    """The Site (core) tier renders as a hero + drillable on/off sub-services."""

    def test_core_category_has_site_card(self, db):
        from apps.heartbeat.views import _status_overview_context

        core = next(c for c in _status_overview_context()["categories"] if c["key"] == "core")
        assert core["site_card"] is not None
        labels = {s["label"] for s in core["site_card"]["services"]}
        assert {"Site", "REST API", "MCP Server", "Search"} <= labels

    def test_site_card_hero_links_sla_and_timeline(self, db):
        from apps.heartbeat.views import _status_overview_context

        core = next(c for c in _status_overview_context()["categories"] if c["key"] == "core")
        hero = core["site_card"]["hero"]
        assert hero is not None
        assert hero["sla_url"] == reverse("heartbeat:sla")
        assert hero["timeline_url"] == reverse("heartbeat:dashboard")

    def test_core_services_carry_live_inventory(self, db):
        # on/off + "what's behind" come from the live registries, not stale beats.
        from apps.heartbeat.views import _status_overview_context

        core = next(c for c in _status_overview_context()["categories"] if c["key"] == "core")
        by_label = {s["label"]: s for s in core["site_card"]["services"]}
        # MCP lists its registered tools; it's "on" because tools exist by default.
        mcp = by_label["MCP Server"]
        assert mcp["ok"] is True
        assert mcp["state_label"] == "on"
        assert len(mcp["items"]) >= 1  # the search_* tools at minimum
        # Database reports connected.
        assert by_label["Site"]["ok"] is True

    def test_inventory_methods_shape(self):
        from apps.api.monitors import ApiMonitor
        from apps.mcp.monitors import McpMonitor
        from apps.search.monitors import SearchMonitor

        for inv in (ApiMonitor().inventory(), McpMonitor().inventory(), SearchMonitor().inventory()):
            assert set(inv) >= {"ok", "summary", "items"}
            assert isinstance(inv["items"], list)


class TestSiteMonitors:
    """The Site Monitors tier: pick an exposed surface, orphan handling, override checks."""

    def _surface(self, kind="mcp", target="demo_tool", label="Demo Tool"):
        from apps.heartbeat.surfaces import Surface

        return Surface(kind=kind, target=target, label=label, meta="a demo")

    def test_monitor_key_format(self):
        from apps.heartbeat.models import MonitoredSurface

        assert MonitoredSurface(slug="search-all").monitor_key == "sm_search-all"

    def test_unique_per_target(self, db):
        from django.db import IntegrityError

        from apps.heartbeat.models import MonitoredSurface

        MonitoredSurface.objects.create(kind="mcp", target="t1", name="A", slug="a")
        with pytest.raises(IntegrityError):
            MonitoredSurface.objects.create(kind="mcp", target="t1", name="B", slug="b")

    def test_source_tags_orphan_and_presence_check(self, db, monkeypatch):
        from apps.heartbeat import surfaces
        from apps.heartbeat.models import MonitoredSurface
        from apps.heartbeat.monitors import surface_monitor_source

        monkeypatch.setattr(surfaces, "exposed_keys", lambda: {("mcp", "live_tool")})
        monkeypatch.setattr(surfaces, "is_surface_exposed", lambda k, t: (k, t) == ("mcp", "live_tool"))

        MonitoredSurface.objects.create(kind="mcp", target="live_tool", name="Live", slug="live")
        MonitoredSurface.objects.create(kind="mcp", target="gone_tool", name="Gone", slug="gone")
        mons = {m.key: m for m in surface_monitor_source()}

        assert mons["sm_live"].orphaned is False
        assert mons["sm_live"].check().ok is True
        assert mons["sm_gone"].orphaned is True
        assert mons["sm_gone"].check().ok is False

    def test_override_check_runs_when_registered(self, db, monkeypatch):
        from apps.heartbeat import surfaces
        from apps.heartbeat.models import MonitoredSurface
        from apps.heartbeat.monitors import surface_monitor_source
        from apps.smallstack import monitors as M
        from apps.smallstack.monitors import CheckResult

        monkeypatch.setattr(surfaces, "exposed_keys", lambda: {("mcp", "deep")})
        monkeypatch.setattr(M, "_surface_checks", {("mcp", "deep"): lambda: CheckResult.down("tool broken")})
        MonitoredSurface.objects.create(kind="mcp", target="deep", name="Deep", slug="deep")
        mon = next(iter(surface_monitor_source()))
        result = mon.check()
        assert result.ok is False
        assert result.note == "tool broken"

    def test_runner_skips_orphans(self, db, monkeypatch):
        from apps.heartbeat import surfaces
        from apps.heartbeat.models import Heartbeat, MonitoredSurface
        from apps.heartbeat.services import run_all_monitors

        monkeypatch.setattr(surfaces, "exposed_keys", lambda: set())  # everything orphaned
        monkeypatch.setattr(surfaces, "is_surface_exposed", lambda k, t: False)
        MonitoredSurface.objects.create(kind="mcp", target="gone", name="Gone", slug="gone")
        results = run_all_monitors()
        assert "sm_gone" not in results
        assert not Heartbeat.objects.filter(monitor_key="sm_gone").exists()

    def test_form_only_offers_exposed_surfaces(self, db, monkeypatch):
        import apps.heartbeat.surfaces as surfaces_mod
        from apps.heartbeat.forms import MonitoredSurfaceForm

        monkeypatch.setattr(surfaces_mod, "get_exposed_surfaces", lambda: [self._surface()])
        form = MonitoredSurfaceForm()
        values = [v for group, opts in form.fields["surface"].choices for v, _ in opts]
        assert values == ["mcp:demo_tool"]

    def test_form_creates_with_derived_fields(self, db, monkeypatch):
        import apps.heartbeat.surfaces as surfaces_mod
        from apps.heartbeat.forms import MonitoredSurfaceForm

        s = self._surface()
        monkeypatch.setattr(surfaces_mod, "get_exposed_surfaces", lambda: [s])
        monkeypatch.setattr(surfaces_mod, "get_surface", lambda k, t: s if (k, t) == ("mcp", "demo_tool") else None)
        form = MonitoredSurfaceForm({"surface": "mcp:demo_tool", "name": "", "enabled": "on"})
        assert form.is_valid(), form.errors
        obj = form.save()
        assert obj.kind == "mcp" and obj.target == "demo_tool"
        assert obj.name == "Demo Tool"  # defaulted to the surface label
        assert obj.slug == "demo-tool"

    def test_create_and_delete_via_crud(self, staff_client, db, monkeypatch):
        import apps.heartbeat.surfaces as surfaces_mod
        from apps.heartbeat.models import MonitoredSurface

        s = self._surface()
        monkeypatch.setattr(surfaces_mod, "get_exposed_surfaces", lambda: [s])
        monkeypatch.setattr(surfaces_mod, "get_surface", lambda k, t: s if (k, t) == ("mcp", "demo_tool") else None)
        resp = staff_client.post(
            reverse("heartbeat:status/site-monitors-create"),
            {"surface": "mcp:demo_tool", "name": "", "enabled": "on"},
        )
        assert resp.status_code == 302
        obj = MonitoredSurface.objects.get(target="demo_tool")
        resp = staff_client.post(reverse("heartbeat:status/site-monitors-delete", kwargs={"pk": obj.pk}))
        assert resp.status_code == 302
        assert not MonitoredSurface.objects.filter(pk=obj.pk).exists()

    def test_orphan_renders_muted_with_remove(self, staff_client, db, monkeypatch):
        from apps.heartbeat import surfaces
        from apps.heartbeat.models import MonitoredSurface

        monkeypatch.setattr(surfaces, "exposed_keys", lambda: set())
        MonitoredSurface.objects.create(kind="mcp", target="gone", name="Ghost Tool", slug="ghost")
        body = staff_client.get(reverse("heartbeat:status_overview")).content.decode()
        assert "not exposed" in body
        assert reverse("heartbeat:status/site-monitors-delete", kwargs={"pk": 1}) in body


class TestAddMonitorModal:
    """The overview "+ Add" buttons open the create forms in a modal (AJAX fragment)."""

    @pytest.mark.parametrize(
        "name", ["heartbeat:status/site-monitors-create", "heartbeat:status/endpoints-create"]
    )
    def test_ajax_get_returns_bare_fragment(self, staff_client, db, name):
        resp = staff_client.get(reverse(name), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        body = resp.content.decode()
        assert "<html" not in body.lower()  # no full-page chrome
        # Assert on the structural sidebar selector, not a link label — downstreams
        # rebrand the nav copy (e.g. smallstack_web's marketing sidebar), but the
        # `id="sidebar"` wrapper is stable across every SmallStack sidebar.
        assert 'id="sidebar"' not in body  # no sidebar nav
        assert "<form" in body
        assert "page-header-bleed" not in body  # the breadcrumb header is suppressed

    @pytest.mark.parametrize(
        "name", ["heartbeat:status/site-monitors-create", "heartbeat:status/endpoints-create"]
    )
    def test_plain_get_returns_full_page(self, staff_client, db, name):
        body = staff_client.get(reverse(name)).content.decode()
        assert "<html" in body.lower()
        assert 'id="sidebar"' in body  # sidebar present (downstreams may rebrand the links)

    def test_form_action_is_create_url_for_modal_post(self, staff_client, db):
        url = reverse("heartbeat:status/endpoints-create")
        body = staff_client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest").content.decode()
        assert f'action="{url}"' in body  # posts to the create URL, not the overview

    def test_modal_valid_post_redirects(self, staff_client, db):
        resp = staff_client.post(
            reverse("heartbeat:status/endpoints-create"),
            {
                "mode": "smallstack",
                "name": "Modal Site",
                "url": "https://modal.example",
                "method": "GET",
                "expected_status": "200",
                "timeout_seconds": "10",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert resp.status_code == 302  # the modal JS reads a redirect as success
        assert MonitoredEndpoint.objects.filter(slug="modal-site").exists()

    def test_modal_invalid_post_returns_bare_fragment(self, staff_client, db):
        resp = staff_client.post(
            reverse("heartbeat:status/endpoints-create"),
            {"mode": "custom", "name": "", "url": "not-a-url", "method": "GET", "expected_status": "200",
             "timeout_seconds": "10"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "<html" not in body.lower()  # errors re-render into the modal, not a full page
        assert "<form" in body

    def test_overview_buttons_are_modal_triggers(self, staff_client, db):
        body = staff_client.get(reverse("heartbeat:status_overview")).content.decode()
        assert "data-add-monitor" in body
        assert 'id="add-monitor-modal"' in body


class TestPublicStatusFlag:
    """SMALLSTACK_PUBLIC_STATUS_ENABLED gates the anonymous public status surface."""

    @pytest.mark.parametrize(
        "name", ["public_status", "public_status_json", "public_maintenance", "public_maintenance_calendar"]
    )
    def test_public_routes_404_when_disabled(self, client, db, name):
        from django.test import override_settings

        with override_settings(SMALLSTACK_PUBLIC_STATUS_ENABLED=False):
            assert client.get(reverse(name)).status_code == 404

    def test_public_routes_work_when_enabled(self, client, db):
        # Default on — the board renders.
        assert client.get(reverse("public_status")).status_code == 200

    def test_overview_hides_public_links_when_disabled(self, staff_client, db):
        from django.test import override_settings

        with override_settings(SMALLSTACK_PUBLIC_STATUS_ENABLED=False):
            body = staff_client.get(reverse("heartbeat:status_overview")).content.decode()
        assert ">Public page<" not in body
        # ...and the staff overview itself still works.
        assert "All systems operational" in body or "Status" in body

    def test_overview_shows_public_links_when_enabled(self, staff_client, db):
        body = staff_client.get(reverse("heartbeat:status_overview")).content.decode()
        assert ">Public page<" in body


class TestApiMcpFlags:
    """SMALLSTACK_API_ENABLED / SMALLSTACK_MCP_ENABLED gate those surfaces."""

    def test_crudview_get_urls_skips_api_when_disabled(self, db):
        from django.test import override_settings

        from apps.heartbeat.views import MonitoredEndpointCRUDView

        with override_settings(SMALLSTACK_API_ENABLED=False):
            names = [u.name for u in MonitoredEndpointCRUDView.get_urls() if u.name]
        assert not any((n or "").endswith("-api-list") for n in names)

    def test_crudview_get_urls_includes_api_when_enabled(self, db):
        from apps.heartbeat.views import MonitoredEndpointCRUDView

        names = [u.name for u in MonitoredEndpointCRUDView.get_urls() if u.name]
        assert any((n or "").endswith("-api-list") for n in names)

    def test_api_routes_dropped_when_disabled(self):
        # config/urls.py registers /api/* only when the flag is on (import-time).
        import importlib

        from django.test import override_settings
        from django.urls import NoReverseMatch, clear_url_caches

        import config.urls

        try:
            with override_settings(SMALLSTACK_API_ENABLED=False):
                importlib.reload(config.urls)
                clear_url_caches()
                with pytest.raises(NoReverseMatch):
                    reverse("api-docs")
        finally:
            importlib.reload(config.urls)
            clear_url_caches()
        assert reverse("api-docs")  # restored

    def test_mcp_routes_dropped_when_disabled(self):
        import importlib

        from django.test import override_settings
        from django.urls import NoReverseMatch, clear_url_caches

        import config.urls

        try:
            with override_settings(SMALLSTACK_MCP_ENABLED=False):
                importlib.reload(config.urls)
                clear_url_caches()
                with pytest.raises(NoReverseMatch):
                    reverse("mcp:rpc")
        finally:
            importlib.reload(config.urls)
            clear_url_caches()
        assert reverse("mcp:rpc")  # restored


class TestPublicSurfaceOrphanFilter:
    """Orphaned monitors never leak onto the public board / JSON, even if public."""

    def _public_orphan(self, monkeypatch):
        from apps.smallstack import monitors as M
        from apps.smallstack.monitors import CheckResult, Monitor

        class _Orphan(Monitor):
            key = "sm_ghost_pub"
            service = "internal"
            title = "Ghost (public)"
            public = True
            orphaned = True

            def check(self):
                return CheckResult.up()

        monkeypatch.setattr(M, "_monitor_sources", M._monitor_sources + [lambda: [_Orphan()]])

    def test_orphan_excluded_from_json(self, client, db, monkeypatch):
        self._public_orphan(monkeypatch)
        keys = [m["key"] for m in client.get(reverse("public_status_json")).json()["monitors"]]
        assert "sm_ghost_pub" not in keys

    def test_orphan_excluded_from_public_board(self, client, db, monkeypatch):
        self._public_orphan(monkeypatch)
        body = client.get(reverse("public_status")).content.decode()
        assert "Ghost (public)" not in body


class TestStatusBackLinks:
    """Back-navigation: monitor detail → its list; public page → overview (auth only)."""

    def test_endpoint_monitor_links_back_to_endpoints(self, staff_client, db):
        MonitoredEndpoint.objects.create(name="Docs", slug="docs-x", service="custom", url="https://d/health/")
        body = staff_client.get(
            reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "ep_docs-x"})
        ).content.decode()
        assert reverse("heartbeat:status/endpoints-list") in body
        assert "Monitored endpoints" in body

    def test_surface_monitor_links_back_to_site_monitors(self, staff_client, db, monkeypatch):
        from apps.heartbeat import surfaces
        from apps.heartbeat.models import MonitoredSurface

        monkeypatch.setattr(surfaces, "exposed_keys", lambda: {("mcp", "search_all")})
        MonitoredSurface.objects.create(kind="mcp", target="search_all", name="Search", slug="search-x")
        body = staff_client.get(
            reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "sm_search-x"})
        ).content.decode()
        assert reverse("heartbeat:status/site-monitors-list") in body
        assert "Site monitors" in body

    def test_core_monitor_has_no_list_crumb(self, staff_client, db):
        body = staff_client.get(reverse("heartbeat:monitor_detail", kwargs={"monitor_key": "site"})).content.decode()
        assert "Monitored endpoints" not in body
        assert "Site monitors" not in body

    def test_public_page_shows_overview_link_when_logged_in(self, staff_client, db):
        body = staff_client.get(reverse("public_status")).content.decode()
        assert reverse("heartbeat:status_overview") in body
        assert "Status overview" in body

    def test_public_page_hides_overview_link_when_anonymous(self, client, db):
        body = client.get(reverse("public_status")).content.decode()
        assert "Status overview" not in body


class TestExposedSurfaces:
    """surfaces.py enumerates what's actually exposed (real registries, not mocked)."""

    def test_enumerates_real_api_and_mcp_surfaces(self, db):
        from apps.heartbeat.surfaces import get_exposed_surfaces

        # Force the full URLconf to load so every CRUDView.get_urls() has run and
        # populated _api_registry (built lazily on first reverse/resolve).
        reverse("heartbeat:status_overview")

        by_kind = {}
        for s in get_exposed_surfaces():
            by_kind.setdefault(s.kind, []).append(s.target)
        # The MonitoredEndpoint CRUDView is enable_api=True → at least one API surface.
        assert by_kind.get("api"), "expected an exposed API surface"
        # The search MCP tools register by default → at least one MCP surface.
        assert by_kind.get("mcp"), "expected an exposed MCP surface"

    def test_is_surface_exposed_matches_enumeration(self, db):
        from apps.heartbeat.surfaces import exposed_keys, get_exposed_surfaces, is_surface_exposed

        surface = get_exposed_surfaces()[0]
        assert is_surface_exposed(surface.kind, surface.target)
        assert (surface.kind, surface.target) in exposed_keys()
        assert not is_surface_exposed(surface.kind, "definitely-not-a-real-target")

    def test_surface_value_encodes_kind_and_target(self):
        from apps.heartbeat.surfaces import Surface

        assert Surface(kind="mcp", target="search_all", label="x").value == "mcp:search_all"


class TestDailyTimelineTodayColoring:
    """Regression: a sparse, all-OK *current* day must not render red on the 90-day
    timeline. Today is partial, so it's judged by its actual beats (failure-based),
    not an elapsed-since-midnight denominator that paints a few-beats day red."""

    def test_today_sparse_ok_classifies_up(self, db):
        # epoch a few days ago so today isn't pre-epoch; NO daily summary for today,
        # so the raw-beats path runs.
        key = "sm_sparse_today"
        HeartbeatEpoch.objects.create(monitor_key=key, started_at=now() - timedelta(days=3))
        base = now().replace(second=0, microsecond=0)
        for i in range(3):  # only 3 OK beats today — far fewer than a full day
            Heartbeat.objects.create(monitor_key=key, timestamp=base - timedelta(minutes=i), status="ok")

        slots = status_mod._build_daily_timeline(days=90, monitor_key=key)
        today_slot = slots[-1]
        assert today_slot["date"] == localdate()
        assert today_slot["status"] == "up"  # was "down" under the elapsed-time denominator
        assert today_slot["uptime"] == 100.0

    def test_today_with_failures_still_degraded(self, db):
        # A real outage today (mixed ok/fail) must still read as degraded/down, not up.
        key = "sm_today_fail"
        HeartbeatEpoch.objects.create(monitor_key=key, started_at=now() - timedelta(days=3))
        base = now().replace(second=0, microsecond=0)
        Heartbeat.objects.create(monitor_key=key, timestamp=base, status="ok")
        for i in range(1, 4):
            Heartbeat.objects.create(monitor_key=key, timestamp=base - timedelta(minutes=i), status="fail")

        today_slot = status_mod._build_daily_timeline(days=90, monitor_key=key)[-1]
        assert today_slot["status"] in ("degraded", "down")  # 1/4 ok → not "up"


class TestMaintenancePill:
    """An active maintenance window masks the live status as 'Under maintenance'
    (accent), not a red outage — on _get_status_data, the public pill, and the JSON."""

    def _site_fail_now(self):
        # A failing 'site' beat at the current minute (site is public by default).
        Heartbeat.objects.create(
            monitor_key="site", timestamp=now().replace(second=0, microsecond=0), status="fail"
        )

    def _window(self, monitor_key="site"):
        from apps.heartbeat.models import MaintenanceWindow

        MaintenanceWindow.objects.create(
            monitor_key=monitor_key,
            title="Deploy",
            start=now() - timedelta(minutes=10),
            end=now() + timedelta(minutes=10),
        )

    def test_get_status_data_masks_down_as_maintenance(self, db):
        self._site_fail_now()
        assert status_mod._get_status_data("site")["status"] == "down"  # no window yet
        self._window("site")
        data = status_mod._get_status_data("site")
        assert data["status"] == "maintenance"
        assert data["status_label"] == "Under maintenance"

    def test_public_pill_shows_under_maintenance(self, client, db):
        self._site_fail_now()
        self._window("site")
        body = client.get(reverse("public_status")).content.decode()
        assert "under maintenance" in body.lower()
        assert "status-overall maintenance" in body  # the accent pill, not down

    def test_json_reports_maintenance(self, client, db):
        self._site_fail_now()
        self._window("site")
        data = client.get(reverse("public_status_json")).json()
        site = next(m for m in data["monitors"] if m["key"] == "site")
        assert site["status"] == "maintenance"

    def test_real_down_outranks_maintenance(self, db, monkeypatch):
        # A genuine outage on a monitor NOT in a window still wins the overall roll-up.
        from apps.smallstack import monitors as M
        from apps.smallstack.monitors import CheckResult, Monitor

        class _Down(Monitor):
            key = "pubdown"
            service = "site"
            title = "Real outage"
            public = True

            def check(self):
                return CheckResult.down("boom")

        monkeypatch.setattr(M, "_monitor_sources", M._monitor_sources + [lambda: [_Down()]])
        Heartbeat.objects.create(monitor_key="pubdown", timestamp=now().replace(second=0, microsecond=0), status="fail")
        self._site_fail_now()
        self._window("site")  # site is masked to maintenance...
        from apps.heartbeat.views import _status_overview_context

        ctx = _status_overview_context(public_only=True)
        assert ctx["overall_state"] == "down"  # ...but the real outage on pubdown wins


class TestStandaloneStatusCssFallback:
    """The standalone status pages (/status/, public maintenance) don't load Django
    admin's base.css, so --body-quiet-color is undefined off the high-contrast
    palette. Every use must carry a var() fallback or the calendar/timeline cells
    color-mix to `transparent` and vanish. Regression guard for the invisible-cells bug."""

    @pytest.mark.parametrize(
        "name", ["public_status", "public_maintenance", "public_maintenance_calendar"]
    )
    def test_no_bare_body_quiet_color(self, client, db, name):
        body = client.get(reverse(name)).content.decode()
        assert "var(--body-quiet-color)" not in body  # bare = undefined off admin pages → invisible
        assert "var(--body-quiet-color, " in body  # the fallback form is present
