"""Tests for the heartbeat app."""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.timezone import activate, deactivate, now

from .forms import SLAForm
from .models import Heartbeat, HeartbeatEpoch
from .views import _calc_overall_uptime, _calc_uptime, _sla_color

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
        beats.append(Heartbeat(
            status="ok",
            response_time_ms=1,
            timestamp=base + timedelta(seconds=i * 60),
        ))
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
        for i in range(30):
            Heartbeat.objects.create(status="ok", response_time_ms=1)
        # Fix timestamps to be in the first 30 minutes only
        for i, b in enumerate(Heartbeat.objects.order_by("pk")):
            Heartbeat.objects.filter(pk=b.pk).update(
                timestamp=base + timedelta(seconds=i * 60)
            )
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
            Heartbeat.objects.create(status="ok", response_time_ms=1)
        for i, b in enumerate(Heartbeat.objects.order_by("pk")):
            Heartbeat.objects.filter(pk=b.pk).update(
                timestamp=base + timedelta(seconds=i * 60)
            )
        uptime = _calc_uptime(24)
        assert uptime is not None
        assert uptime == 100.0

    def test_failures_reduce_uptime(self, epoch):
        """Mix of ok and fail heartbeats should reduce uptime."""
        base = epoch.started_at
        for i in range(60):
            status = "ok" if i < 50 else "fail"
            Heartbeat.objects.create(status=status, response_time_ms=1)
        for i, b in enumerate(Heartbeat.objects.order_by("pk")):
            Heartbeat.objects.filter(pk=b.pk).update(
                timestamp=base + timedelta(seconds=i * 60)
            )
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
            form = SLAForm(data={
                "started_at": "2026-03-10T14:30",
                "service_target": "99.9",
                "service_minimum": "99.5",
                "note": "",
            })
            assert form.is_valid(), form.errors
            dt = form.cleaned_data["started_at"]
            assert dt.tzinfo is not None
        finally:
            deactivate()

    def test_form_datetime_interpreted_in_user_timezone(self, db):
        """2:30 PM with EDT active should be 6:30 PM UTC."""
        activate(EDT)
        try:
            form = SLAForm(data={
                "started_at": "2026-03-10T14:30",
                "service_target": "99.9",
                "service_minimum": "99.5",
                "note": "",
            })
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
            form = SLAForm(data={
                "started_at": "2026-03-10T14:30",
                "service_target": "99.9",
                "service_minimum": "99.5",
                "note": "",
            })
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
            username="regular", password="testpass123",
        )
        client.force_login(user)
        response = client.post(reverse("heartbeat:reset_epoch"), data={
            "started_at": "2026-03-10T14:30",
            "service_target": "99.9",
            "service_minimum": "99.5",
        })
        assert response.status_code == 403

    def test_uptime_100_after_reset_to_recent(self, staff_client, db):
        """Reset epoch to recent past + heartbeats = 100% uptime."""
        # Create heartbeats for the last 10 minutes
        base = now() - timedelta(minutes=10)
        for i in range(10):
            Heartbeat.objects.create(status="ok", response_time_ms=1)
        for i, b in enumerate(Heartbeat.objects.order_by("pk")):
            Heartbeat.objects.filter(pk=b.pk).update(
                timestamp=base + timedelta(seconds=i * 60)
            )
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
            Heartbeat.objects.create(status="ok", response_time_ms=1)
        for i, b in enumerate(Heartbeat.objects.order_by("pk")):
            Heartbeat.objects.filter(pk=b.pk).update(
                timestamp=base + timedelta(seconds=i * 60)
            )
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
            Heartbeat.objects.create(status="ok", response_time_ms=1)
        for i, b in enumerate(Heartbeat.objects.order_by("pk")):
            Heartbeat.objects.filter(pk=b.pk).update(
                timestamp=base + timedelta(seconds=i * 60)
            )
        response = staff_client.get(reverse("heartbeat:sla"))
        # The uptime color values should be green (success), not yellow (warning).
        # Check the context directly — uptime_*_color should all be success-fg.
        assert response.context["uptime_overall_color"] == "var(--success-fg)"
        assert response.context["uptime_24h_color"] == "var(--success-fg)"
        assert response.context["uptime_7d_color"] == "var(--success-fg)"
