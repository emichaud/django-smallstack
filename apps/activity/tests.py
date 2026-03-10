"""Tests for the activity app."""

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from django.urls import reverse

from .middleware import ActivityMiddleware
from .models import RequestLog

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
def request_factory():
    return RequestFactory()


class TestRequestLogModel:
    """Tests for the RequestLog model."""

    def test_str(self, db):
        log = RequestLog.objects.create(
            path="/test/",
            method="GET",
            status_code=200,
            response_time_ms=42,
        )
        assert str(log) == "GET /test/ [200]"

    def test_ordering(self, db):
        RequestLog.objects.create(path="/first/", method="GET", status_code=200, response_time_ms=10)
        RequestLog.objects.create(path="/second/", method="GET", status_code=200, response_time_ms=10)
        logs = list(RequestLog.objects.all())
        assert logs[0].path == "/second/"
        assert logs[1].path == "/first/"


class TestActivityMiddleware:
    """Tests for the ActivityMiddleware."""

    def _get_middleware(self, response_status=200):
        def get_response(request):
            from django.http import HttpResponse

            return HttpResponse(status=response_status)

        return ActivityMiddleware(get_response)

    def test_records_request(self, db, request_factory):
        middleware = self._get_middleware()
        request = request_factory.get("/test-page/")
        request.user = None
        middleware(request)
        assert RequestLog.objects.count() == 1
        log = RequestLog.objects.first()
        assert log.path == "/test-page/"
        assert log.method == "GET"
        assert log.status_code == 200

    def test_skips_static(self, db, request_factory):
        middleware = self._get_middleware()
        request = request_factory.get("/static/css/main.css")
        request.user = None
        middleware(request)
        assert RequestLog.objects.count() == 0

    def test_skips_media(self, db, request_factory):
        middleware = self._get_middleware()
        request = request_factory.get("/media/uploads/photo.jpg")
        request.user = None
        middleware(request)
        assert RequestLog.objects.count() == 0

    def test_skips_favicon(self, db, request_factory):
        middleware = self._get_middleware()
        request = request_factory.get("/favicon.ico")
        request.user = None
        middleware(request)
        assert RequestLog.objects.count() == 0

    def test_records_authenticated_user(self, db, user, request_factory):
        middleware = self._get_middleware()
        request = request_factory.get("/page/")
        request.user = user
        middleware(request)
        log = RequestLog.objects.first()
        assert log.user == user

    def test_records_anonymous_user_as_null(self, db, request_factory):
        from django.contrib.auth.models import AnonymousUser

        middleware = self._get_middleware()
        request = request_factory.get("/page/")
        request.user = AnonymousUser()
        middleware(request)
        log = RequestLog.objects.first()
        assert log.user is None

    def test_records_response_time(self, db, request_factory):
        middleware = self._get_middleware()
        request = request_factory.get("/page/")
        request.user = None
        middleware(request)
        log = RequestLog.objects.first()
        assert log.response_time_ms >= 0

    @override_settings(ACTIVITY_MAX_ROWS=5, ACTIVITY_PRUNE_INTERVAL=1)
    def test_prune_keeps_table_bounded(self, db, request_factory):
        middleware = self._get_middleware()
        for i in range(10):
            request = request_factory.get(f"/page/{i}/")
            request.user = None
            middleware(request)
        assert RequestLog.objects.count() <= 5


class TestActivityDashboardView:
    """Tests for the overview dashboard."""

    def test_requires_login(self, client):
        response = client.get(reverse("activity:dashboard"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_requires_staff(self, client, user):
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("activity:dashboard"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:dashboard"))
        assert response.status_code == 200

    def test_context_contains_request_stats(self, client, staff_user):
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:dashboard"))
        assert "total_requests" in response.context
        assert "avg_response_time" in response.context
        assert "status_groups" in response.context
        assert "top_paths" in response.context
        assert "recent_requests" in response.context

    def test_context_contains_user_stats(self, client, staff_user):
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:dashboard"))
        assert "user_count" in response.context
        assert "recent_signup_count" in response.context
        assert "top_theme_bar" in response.context
        assert "top_users" in response.context


class TestRequestListView:
    """Tests for the requests detail page."""

    def test_requires_login(self, client):
        response = client.get(reverse("activity:requests"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_requires_staff(self, client, user):
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("activity:requests"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:requests"))
        assert response.status_code == 200

    def test_context_contains_data(self, client, staff_user):
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:requests"))
        # Full page includes status cards and default (recent) tab with tables2
        assert "table" in response.context
        assert "status_groups" in response.context
        assert "total_requests" in response.context
        assert "active_tab" in response.context
        assert response.context["active_tab"] == "recent"

    def test_tab_param_selects_tab(self, client, staff_user):
        """?tab= param selects the correct tab context."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:requests") + "?tab=top_paths")
        assert response.context["active_tab"] == "top_paths"
        assert "table" in response.context

    def test_htmx_returns_partial(self, client, staff_user):
        """htmx requests should return only the partial template."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(
            reverse("activity:requests") + "?tab=recent",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="recent-requests"' in content
        assert "<html" not in content

    def test_normal_returns_full_page(self, client, staff_user):
        """Normal requests should return the full page."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:requests"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "<html" in content

    def test_title_bar_has_breadcrumbs(self, client, staff_user):
        """Requests page should have inline breadcrumbs in title bar."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:requests"))
        content = response.content.decode()
        assert "Home" in content
        assert "Activity" in content
        assert "Requests" in content

    def test_recent_tab_uses_tables2(self, client, staff_user, db):
        """Recent tab should use django-tables2 with crud-table class."""
        from .models import RequestLog

        RequestLog.objects.create(path="/test/", method="GET", status_code=200, response_time_ms=10)
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:requests"))
        content = response.content.decode()
        assert "crud-table" in content


class TestUserActivityView:
    """Tests for the users detail page."""

    def test_requires_login(self, client):
        response = client.get(reverse("activity:users"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_requires_staff(self, client, user):
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("activity:users"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:users"))
        assert response.status_code == 200

    def test_context_contains_user_data(self, client, staff_user):
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:users"))
        # Default tab is top_users
        assert "top_users" in response.context
        assert "page_obj" in response.context
        assert "active_tab" in response.context
        assert response.context["active_tab"] == "top_users"

    def test_tab_param_selects_tab(self, client, staff_user):
        """?tab= param selects the correct tab context."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:users") + "?tab=activity")
        assert response.context["active_tab"] == "activity"
        assert "recent_user_activity" in response.context
        assert "page_obj" in response.context

    def test_htmx_returns_partial(self, client, staff_user):
        """htmx requests should return only the partial template."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(
            reverse("activity:users") + "?tab=top_users",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "Top Users" in content
        assert "<html" not in content

    def test_normal_returns_full_page(self, client, staff_user):
        """Normal requests should return the full page."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:users"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "<html" in content

    def test_title_bar_has_breadcrumbs(self, client, staff_user):
        """User activity page should have inline breadcrumbs in title bar."""
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:users"))
        content = response.content.decode()
        assert "Home" in content
        assert "Activity" in content
        assert "user_count" in response.context
        assert "recent_signup_count" in response.context

    def test_shows_user_with_requests(self, client, staff_user, user):
        RequestLog.objects.create(
            path="/test/",
            method="GET",
            status_code=200,
            response_time_ms=50,
            user=user,
        )
        client.login(username="staffuser", password="testpass123")
        response = client.get(reverse("activity:users"))
        top_users = list(response.context["top_users"])
        assert any(e["user__username"] == "testuser" for e in top_users)
