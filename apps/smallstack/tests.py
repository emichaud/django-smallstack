"""Tests for the SmallStack backup system, timezone middleware, template tags, and topbar nav."""

import zoneinfo
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from .context_processors import _resolve_nav_items
from .middleware import TimezoneMiddleware
from .models import BackupRecord

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a regular test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def staff_user(db):
    """Create a staff test user."""
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def success_record(db):
    """Create a successful backup record."""
    return BackupRecord.objects.create(
        filename="db-20260308-120000.sqlite3",
        file_size=100000,
        duration_ms=15,
        status="success",
        triggered_by="manual",
    )


@pytest.fixture
def failed_record(db):
    """Create a failed backup record."""
    return BackupRecord.objects.create(
        filename="",
        file_size=0,
        duration_ms=5,
        status="failed",
        error_message="disk full",
        triggered_by="command",
    )


@pytest.fixture
def pruned_record(db):
    """Create a pruned backup record (success record with pruned_at set)."""
    return BackupRecord.objects.create(
        filename="db-20260301-080000.sqlite3",
        file_size=95000,
        duration_ms=12,
        status="success",
        triggered_by="cron",
        pruned_at=timezone.now(),
    )


# ── Model Tests ──────────────────────────────────────────────


class TestBackupRecordModel:
    """Tests for the BackupRecord model."""

    def test_str_success(self, success_record):
        assert str(success_record) == "db-20260308-120000.sqlite3 (success)"

    def test_str_failed(self, failed_record):
        assert str(failed_record) == "failed (failed)"

    def test_ordering(self, success_record, failed_record):
        """Most recent records should come first."""
        records = list(BackupRecord.objects.all())
        assert records[0] == failed_record  # created second = more recent
        assert records[1] == success_record

    def test_get_absolute_url(self, success_record):
        url = success_record.get_absolute_url()
        assert url == f"/backups/{success_record.pk}/"

    def test_is_pruned_false(self, success_record):
        assert success_record.is_pruned is False

    def test_is_pruned_true(self, pruned_record):
        assert pruned_record.is_pruned is True

    def test_file_exists_no_filename(self, failed_record):
        assert failed_record.file_exists is False

    def test_file_exists_pruned_short_circuits(self, pruned_record):
        """Pruned records should return False without checking disk."""
        assert pruned_record.file_exists is False

    def test_file_exists_missing_file(self, success_record):
        """File doesn't exist on disk, so file_exists should be False."""
        assert success_record.file_exists is False


# ── Prune Logic Tests ────────────────────────────────────────


class TestPruneBackups:
    """Tests for the _prune_backups helper."""

    @override_settings(BACKUP_RETENTION=None)
    def test_prune_returns_empty_when_no_retention(self, db):
        from .views import _prune_backups

        result = _prune_backups(keep=None)
        assert result == []

    @override_settings(BACKUP_RETENTION=2)
    def test_prune_marks_records_with_pruned_at(self, db, tmp_path):
        """Pruning should set pruned_at on the original success record."""
        from .views import _prune_backups

        # Create 3 backup files
        for i in range(3):
            fname = f"db-20260301-00000{i}.sqlite3"
            (tmp_path / fname).write_bytes(b"x" * 100)
            BackupRecord.objects.create(
                filename=fname,
                file_size=100,
                duration_ms=5,
                status="success",
                triggered_by="manual",
            )

        with override_settings(BACKUP_DIR=str(tmp_path), BACKUP_RETENTION=2):
            pruned = _prune_backups()

        assert len(pruned) == 1
        # The pruned file's record should have pruned_at set
        pruned_rec = BackupRecord.objects.get(filename=pruned[0])
        assert pruned_rec.pruned_at is not None
        assert pruned_rec.status == "success"

    @override_settings(BACKUP_RETENTION=5)
    def test_prune_no_files_to_remove(self, db, tmp_path):
        """If fewer files than retention, nothing should be pruned."""
        from .views import _prune_backups

        (tmp_path / "db-20260301-000000.sqlite3").write_bytes(b"x" * 100)

        with override_settings(BACKUP_DIR=str(tmp_path), BACKUP_RETENTION=5):
            pruned = _prune_backups()

        assert pruned == []


# ── View Permission Tests ────────────────────────────────────


class TestBackupViewPermissions:
    """Tests for backup view access control."""

    def test_backup_page_requires_login(self, client, db):
        response = client.get(reverse("smallstack:backups"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_backup_page_requires_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("smallstack:backups"))
        assert response.status_code == 403

    def test_backup_page_accessible_by_staff(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backups"))
        assert response.status_code == 200

    def test_backup_detail_requires_login(self, client, success_record):
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        assert response.status_code == 302

    def test_backup_detail_requires_staff(self, client, user, success_record):
        client.force_login(user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        assert response.status_code == 403

    def test_backup_detail_accessible_by_staff(self, client, staff_user, success_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        assert response.status_code == 200

    def test_backup_list_has_breadcrumbs(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backups"))
        content = response.content.decode()
        assert "Home" in content
        assert "Backups" in content

    def test_backup_detail_has_breadcrumbs(self, client, staff_user, success_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        content = response.content.decode()
        assert "Home" in content
        assert "Backups" in content
        assert f"#{success_record.pk}" in content

    def test_backup_detail_404_for_missing_record(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": 99999}))
        assert response.status_code == 404

    def test_stat_detail_requires_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "success"}))
        assert response.status_code == 403

    def test_stat_detail_invalid_stat_404(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "bogus"}))
        assert response.status_code == 404

    def test_file_download_missing_file_404(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_file_download", kwargs={"filename": "nonexistent.sqlite3"}))
        assert response.status_code == 404


# ── View Context Tests ───────────────────────────────────────


class TestBackupPageContext:
    """Tests for BackupPageView context data."""

    def test_context_has_stats(self, client, staff_user, success_record, failed_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backups"))
        ctx = response.context

        assert ctx["success_count"] == 1  # only non-pruned success
        assert ctx["failed_count"] == 1
        assert ctx["pruned_count"] == 1
        assert ctx["total_backups"] == 3

    def test_context_total_size_excludes_pruned(self, client, staff_user, success_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backups"))
        ctx = response.context

        # Only the non-pruned success record's size
        assert ctx["total_backup_size"] == success_record.file_size


class TestBackupDetailContext:
    """Tests for BackupDetailView context data."""

    def test_success_record_has_created_event(self, client, staff_user, success_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        events = response.context["events"]

        assert len(events) >= 1
        assert events[0]["label"] == "Backup created"
        assert events[0]["status"] == "success"

    def test_failed_record_has_error_event(self, client, staff_user, failed_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": failed_record.pk}))
        events = response.context["events"]

        assert len(events) == 2
        assert events[1]["label"] == "Backup failed"
        assert events[1]["detail"] == "disk full"

    def test_pruned_record_has_pruned_event(self, client, staff_user, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": pruned_record.pk}))
        events = response.context["events"]

        assert any(e["label"] == "File pruned" for e in events)

    def test_missing_file_has_warning_event(self, client, staff_user, success_record):
        """A success record whose file is gone should show a warning."""
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_detail", kwargs={"pk": success_record.pk}))
        events = response.context["events"]

        assert any(e["label"] == "File missing" for e in events)


# ── Timezone Middleware Tests ────────────────────────────────


class TestTimezoneMiddleware:
    """Tests for TimezoneMiddleware timezone activation and caching."""

    def _get_middleware(self):
        return TimezoneMiddleware(lambda request: None)

    @override_settings(TIME_ZONE="America/New_York")
    def test_anonymous_user_gets_server_tz(self, db):
        """Anonymous users should use the server TIME_ZONE."""
        factory = RequestFactory()
        request = factory.get("/")
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()

        self._get_middleware()(request)

        assert str(request._tz_server) == "America/New_York"
        assert str(request._tz_user) == "America/New_York"
        assert request._tz_differs is False

    @override_settings(TIME_ZONE="America/New_York")
    def test_user_without_tz_gets_server_tz(self, user):
        """Logged-in user with no timezone preference should use server TZ."""
        user.profile.timezone = ""
        user.profile.save()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user

        self._get_middleware()(request)

        assert str(request._tz_user) == "America/New_York"
        assert request._tz_differs is False

    @override_settings(TIME_ZONE="America/New_York")
    def test_user_with_tz_overrides_server(self, user):
        """User with timezone preference should override server TZ."""
        user.profile.timezone = "America/Los_Angeles"
        user.profile.save()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user

        self._get_middleware()(request)

        assert str(request._tz_user) == "America/Los_Angeles"
        assert str(request._tz_server) == "America/New_York"
        assert request._tz_differs is True

    @override_settings(TIME_ZONE="America/New_York")
    def test_user_matching_server_tz_no_diff(self, user):
        """User whose TZ matches server TZ should have _tz_differs=False."""
        user.profile.timezone = "America/New_York"
        user.profile.save()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user

        self._get_middleware()(request)

        assert request._tz_differs is False

    @override_settings(TIME_ZONE="America/New_York")
    def test_middleware_activates_timezone(self, user):
        """Middleware should call timezone.activate with the resolved TZ."""
        user.profile.timezone = "Europe/London"
        user.profile.save()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user

        self._get_middleware()(request)

        current_tz = timezone.get_current_timezone()
        assert str(current_tz) == "Europe/London"


# ── Template Tag Tests ──────────────────────────────────────


class TestLocaltimeTooltipTag:
    """Tests for the {% localtime_tooltip %} template tag."""

    def _render(self, template_str, context_dict):
        template = Template(template_str)
        return template.render(Context(context_dict))

    def _make_request(self, user_tz, server_tz):
        """Create a mock request with cached TZ info (as middleware would set)."""
        request = RequestFactory().get("/")
        request._tz_server = zoneinfo.ZoneInfo(server_tz)
        request._tz_user = zoneinfo.ZoneInfo(user_tz)
        request._tz_differs = user_tz != server_tz
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()
        return request

    @override_settings(TIME_ZONE="America/New_York")
    def test_same_tz_returns_plain_text(self):
        """When user TZ matches server TZ, output should be plain text."""
        request = self._make_request("America/New_York", "America/New_York")
        dt = datetime(2026, 6, 15, 18, 0, 0, tzinfo=dt_timezone.utc)
        output = self._render(
            '{% load theme_tags %}{% localtime_tooltip dt "M d, Y g:i A T" %}',
            {"dt": dt, "request": request},
        )
        assert "tz-tip" not in output
        assert "Jun" in output

    @override_settings(TIME_ZONE="America/New_York")
    def test_different_tz_returns_tooltip_span(self):
        """When user TZ differs from server, output should have tz-tip class."""
        request = self._make_request("America/Los_Angeles", "America/New_York")
        dt = datetime(2026, 6, 15, 18, 0, 0, tzinfo=dt_timezone.utc)
        output = self._render(
            '{% load theme_tags %}{% localtime_tooltip dt "M d, Y g:i A T" %}',
            {"dt": dt, "request": request},
        )
        assert 'class="tz-tip"' in output
        assert "data-tz-server=" in output
        assert "data-tz-utc=" in output

    @override_settings(TIME_ZONE="America/New_York")
    def test_tooltip_shows_correct_times(self):
        """Tooltip should show server time and UTC time."""
        request = self._make_request("America/Los_Angeles", "America/New_York")
        # June 15 18:00 UTC = 14:00 EDT (NY) = 11:00 AM PDT (LA)
        dt = datetime(2026, 6, 15, 18, 0, 0, tzinfo=dt_timezone.utc)
        output = self._render(
            '{% load theme_tags %}{% localtime_tooltip dt "M d, Y g:i A T" %}',
            {"dt": dt, "request": request},
        )
        assert "11:00 AM" in output  # user time (PDT)
        assert "Server:" in output
        assert "UTC:" in output

    @override_settings(TIME_ZONE="America/New_York")
    def test_none_datetime_returns_empty(self):
        """None datetime should return empty string."""
        request = self._make_request("America/New_York", "America/New_York")
        output = self._render(
            '{% load theme_tags %}{% localtime_tooltip dt %}',
            {"dt": None, "request": request},
        )
        assert output.strip() == ""


class TestUserLocaltimeFilter:
    """Tests for the |user_localtime template filter."""

    def test_authenticated_user_converts_to_user_tz(self, user):
        """Filter should convert to authenticated user's timezone."""
        user.profile.timezone = "America/New_York"
        user.profile.save()

        request = RequestFactory().get("/")
        request.user = user

        dt = datetime(2026, 6, 15, 18, 0, 0, tzinfo=dt_timezone.utc)

        # Activate user TZ (as middleware would) so |date renders correctly
        timezone.activate(zoneinfo.ZoneInfo("America/New_York"))
        try:
            template = Template(
                '{% load theme_tags %}{{ dt|user_localtime:request|date:"H" }}'
            )
            output = template.render(Context({"dt": dt, "request": request}))
            assert output.strip() == "14"  # 18 UTC - 4 = 14 EDT
        finally:
            timezone.deactivate()

    def test_anonymous_falls_back_to_server_tz(self, db):
        """Filter should fall back to TIME_ZONE for anonymous users."""
        request = RequestFactory().get("/")
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()

        dt = datetime(2026, 1, 15, 18, 0, 0, tzinfo=dt_timezone.utc)

        # Activate server TZ (as middleware would for anonymous)
        timezone.activate(zoneinfo.ZoneInfo("America/New_York"))
        try:
            template = Template(
                '{% load theme_tags %}{{ dt|user_localtime:request|date:"H" }}'
            )
            output = template.render(Context({"dt": dt, "request": request}))
            assert output.strip() == "13"  # 18 UTC - 5 = 13 EST (January)
        finally:
            timezone.deactivate()

    def test_none_returns_none(self, db):
        """Filter should handle None gracefully."""
        request = RequestFactory().get("/")
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()

        template = Template(
            '{% load theme_tags %}{{ dt|user_localtime:request|default:"empty" }}'
        )
        output = template.render(Context({"dt": None, "request": request}))
        assert "empty" in output


class TestBackupStatDetailView:
    """Tests for stat detail filtering."""

    def test_success_filter_excludes_pruned(self, client, staff_user, success_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "success"}))
        records = response.context["records"]

        filenames = [r.filename for r in records]
        assert success_record.filename in filenames
        assert pruned_record.filename not in filenames

    def test_pruned_filter_includes_pruned(self, client, staff_user, success_record, pruned_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "pruned"}))
        records = response.context["records"]

        filenames = [r.filename for r in records]
        assert pruned_record.filename in filenames
        assert success_record.filename not in filenames

    def test_failed_filter(self, client, staff_user, failed_record, success_record):
        client.force_login(staff_user)
        response = client.get(reverse("smallstack:backup_stat_detail", kwargs={"stat": "failed"}))
        records = response.context["records"]

        assert len(records) == 1
        assert records[0].status == "failed"


# ── Legal Pages & Cookie Banner Tests ─────────────────────


class TestLegalPages:
    """Tests for privacy policy and terms of service pages."""

    def test_privacy_page_loads(self, client, db):
        response = client.get("/privacy/")
        assert response.status_code == 200
        assert "Privacy Policy" in response.content.decode()

    def test_terms_page_loads(self, client, db):
        response = client.get("/terms/")
        assert response.status_code == 200
        assert "Terms of Service" in response.content.decode()

    def test_privacy_page_is_public(self, client, db):
        """Privacy page should not require login."""
        response = client.get("/privacy/")
        assert response.status_code == 200

    def test_invalid_legal_page_404s(self, client, db):
        """Non-existent legal page should 404."""

        # Try accessing via the view directly with a bad page name
        from django.test import RequestFactory

        from config.views import legal_page_view

        factory = RequestFactory()
        request = factory.get("/")
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()

        with pytest.raises(Exception):
            legal_page_view(request, page="nonexistent-page")

    def test_footer_contains_legal_links(self, client, db):
        """Footer should contain privacy and terms links."""
        response = client.get("/")
        content = response.content.decode()
        assert 'href="/privacy/"' in content
        assert 'href="/terms/"' in content

    @override_settings(BRAND_PRIVACY_URL="", BRAND_TERMS_URL="")
    def test_footer_hides_links_when_disabled(self, client, db):
        """Footer should not show links when URLs are empty."""
        response = client.get("/")
        content = response.content.decode()
        assert "Privacy</a>" not in content
        assert "Terms</a>" not in content

    def test_cookie_banner_present(self, client, db):
        """Cookie banner should be in the page HTML."""
        response = client.get("/")
        content = response.content.decode()
        assert "cookie-banner" in content

    @override_settings(BRAND_COOKIE_BANNER=False)
    def test_cookie_banner_hidden_when_disabled(self, client, db):
        """Cookie banner should not render when disabled."""
        response = client.get("/")
        content = response.content.decode()
        assert "cookie-banner" not in content

    def test_signup_terms_notice(self, client, db):
        """Signup page should show terms notice."""
        response = client.get("/accounts/signup/")
        content = response.content.decode()
        assert "Terms of Service" in content
        assert "Privacy Policy" in content


# ── Topbar Navigation Tests ──────────────────────────────


class TestTopbarNav:
    """Tests for configurable topbar navigation."""

    def _make_request(self, path="/", user=None):
        factory = RequestFactory()
        request = factory.get(path)
        if user:
            request.user = user
        else:
            request.user = type("AnonymousUser", (), {"is_authenticated": False, "is_staff": False})()
        return request

    def test_disabled_by_default(self, client, db):
        """Topbar nav should not appear when disabled (default)."""
        response = client.get("/")
        content = response.content.decode()
        assert "topbar-nav" not in content

    @override_settings(SMALLSTACK_TOPBAR_NAV_ENABLED=True, SMALLSTACK_TOPBAR_NAV_ITEMS=[
        {"label": "Home", "url": "website:home"},
    ])
    def test_enabled_with_items(self, client, db):
        """Topbar nav should render when enabled with items."""
        response = client.get("/")
        content = response.content.decode()
        assert "topbar-nav" in content
        assert "Home" in content

    def test_resolve_url_name(self, db):
        """URL names should be resolved via reverse()."""
        request = self._make_request("/")
        items = [{"label": "Home", "url": "website:home"}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 1
        assert resolved[0]["url"] == "/"
        assert resolved[0]["label"] == "Home"

    def test_resolve_absolute_path(self, db):
        """Absolute paths should pass through."""
        request = self._make_request("/")
        items = [{"label": "Docs", "url": "/docs/"}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 1
        assert resolved[0]["url"] == "/docs/"

    def test_resolve_external_url(self, db):
        """External URLs should pass through with external flag."""
        request = self._make_request("/")
        items = [{"label": "GitHub", "url": "https://github.com", "external": True}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 1
        assert resolved[0]["external"] is True
        assert resolved[0]["url"] == "https://github.com"

    def test_bad_url_name_skipped(self, db):
        """Items with unresolvable URL names should be silently skipped."""
        request = self._make_request("/")
        items = [{"label": "Bad", "url": "nonexistent:page"}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 0

    def test_active_state_exact_match(self, db):
        """Active state on exact path match."""
        request = self._make_request("/")
        items = [{"label": "Home", "url": "website:home"}]
        resolved = _resolve_nav_items(items, request)
        assert resolved[0]["active"] is True

    def test_active_state_prefix_match(self, db):
        """Active state on prefix path match."""
        request = self._make_request("/help/some-page/")
        items = [{"label": "Help", "url": "/help/"}]
        resolved = _resolve_nav_items(items, request)
        assert resolved[0]["active"] is True

    def test_inactive_state(self, db):
        """Items should not be active when path doesn't match."""
        request = self._make_request("/other/")
        items = [{"label": "Help", "url": "/help/"}]
        resolved = _resolve_nav_items(items, request)
        assert resolved[0]["active"] is False

    def test_submenu_rendering(self, db):
        """Submenu items should be resolved recursively."""
        request = self._make_request("/")
        items = [{"label": "More", "children": [
            {"label": "Home", "url": "website:home"},
            {"label": "Docs", "url": "/docs/"},
        ]}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 1
        assert "children" in resolved[0]
        assert len(resolved[0]["children"]) == 2

    def test_submenu_has_active_child(self, db):
        """Parent should have has_active_child when a child is active."""
        request = self._make_request("/")
        items = [{"label": "More", "children": [
            {"label": "Home", "url": "website:home"},
        ]}]
        resolved = _resolve_nav_items(items, request)
        assert resolved[0]["has_active_child"] is True

    def test_auth_required_filters_anonymous(self, db):
        """auth_required items should be hidden for anonymous users."""
        request = self._make_request("/")
        items = [{"label": "Dashboard", "url": "/dashboard/", "auth_required": True}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 0

    def test_auth_required_shows_for_authenticated(self, user):
        """auth_required items should show for authenticated users."""
        request = self._make_request("/")
        request.user = user
        items = [{"label": "Dashboard", "url": "/dashboard/", "auth_required": True}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 1

    def test_staff_required_filters_non_staff(self, user):
        """staff_required items should be hidden for non-staff users."""
        request = self._make_request("/")
        request.user = user
        items = [{"label": "Admin", "url": "/admin/", "staff_required": True}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 0

    def test_staff_required_shows_for_staff(self, staff_user):
        """staff_required items should show for staff users."""
        request = self._make_request("/")
        request.user = staff_user
        items = [{"label": "Admin", "url": "/admin/", "staff_required": True}]
        resolved = _resolve_nav_items(items, request)
        assert len(resolved) == 1

    @override_settings(SMALLSTACK_TOPBAR_NAV_ENABLED=True, SMALLSTACK_TOPBAR_NAV_ITEMS=[
        {"label": "GitHub", "url": "https://github.com", "external": True},
    ])
    def test_external_link_attributes(self, client, db):
        """External links should have target=_blank and rel=noopener."""
        response = client.get("/")
        content = response.content.decode()
        assert 'target="_blank"' in content
        assert 'rel="noopener"' in content
