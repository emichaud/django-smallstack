"""
Tests for the profile app.
"""

import zoneinfo
from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from .models import UserProfile

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(db):
    """Create another test user."""
    return User.objects.create_user(
        username="otheruser",
        email="other@example.com",
        password="otherpass123",
    )


class TestUserProfileModel:
    """Tests for the UserProfile model."""

    def test_profile_created_on_user_creation(self, user):
        """Profile should be auto-created when user is created."""
        assert hasattr(user, "profile")
        assert isinstance(user.profile, UserProfile)

    def test_profile_str(self, user):
        """Profile __str__ should include username."""
        assert str(user.profile) == f"Profile for {user.username}"

    def test_get_display_name_with_display_name(self, user):
        """get_display_name should return display_name if set."""
        user.profile.display_name = "Test Display Name"
        user.profile.save()
        assert user.profile.get_display_name() == "Test Display Name"

    def test_get_display_name_fallback(self, user):
        """get_display_name should fallback to username."""
        user.profile.display_name = ""
        user.profile.save()
        assert user.profile.get_display_name() == user.username


class TestProfileTimezone:
    """Tests for timezone methods on UserProfile."""

    def test_get_timezone_returns_user_tz(self, user):
        """get_timezone should return the user's configured timezone."""
        user.profile.timezone = "America/Los_Angeles"
        user.profile.save()
        tz = user.profile.get_timezone()
        assert str(tz) == "America/Los_Angeles"

    @override_settings(TIME_ZONE="America/Chicago")
    def test_get_timezone_falls_back_to_server_tz(self, user):
        """get_timezone should fall back to TIME_ZONE when user has no preference."""
        user.profile.timezone = ""
        user.profile.save()
        tz = user.profile.get_timezone()
        assert str(tz) == "America/Chicago"

    def test_to_local_time_converts_utc(self, user):
        """to_local_time should convert UTC datetime to user's timezone."""
        user.profile.timezone = "America/New_York"
        user.profile.save()
        utc_dt = datetime(2026, 6, 15, 18, 0, 0, tzinfo=dt_timezone.utc)
        local_dt = user.profile.to_local_time(utc_dt)
        # June = EDT (UTC-4), so 18:00 UTC = 14:00 EDT
        assert local_dt.hour == 14
        assert str(local_dt.tzinfo) == "America/New_York"

    def test_to_local_time_handles_dst(self, user):
        """to_local_time should handle DST transitions correctly."""
        user.profile.timezone = "America/New_York"
        user.profile.save()
        # January = EST (UTC-5)
        winter_utc = datetime(2026, 1, 15, 18, 0, 0, tzinfo=dt_timezone.utc)
        winter_local = user.profile.to_local_time(winter_utc)
        assert winter_local.hour == 13  # 18:00 UTC - 5 = 13:00 EST

        # June = EDT (UTC-4)
        summer_utc = datetime(2026, 6, 15, 18, 0, 0, tzinfo=dt_timezone.utc)
        summer_local = user.profile.to_local_time(summer_utc)
        assert summer_local.hour == 14  # 18:00 UTC - 4 = 14:00 EDT

    def test_profile_edit_saves_timezone(self, client, user):
        """Timezone should be saved via the profile edit form."""
        client.login(username="testuser", password="testpass123")
        response = client.post(
            reverse("profile_edit"),
            {
                "display_name": "Test User",
                "timezone": "Europe/London",
            },
        )
        assert response.status_code == 302
        user.profile.refresh_from_db()
        assert user.profile.timezone == "Europe/London"

    def test_profile_edit_clears_timezone(self, client, user):
        """Submitting empty timezone should clear it (use system default)."""
        user.profile.timezone = "America/Denver"
        user.profile.save()
        client.login(username="testuser", password="testpass123")
        response = client.post(
            reverse("profile_edit"),
            {
                "display_name": "Test User",
                "timezone": "",
            },
        )
        assert response.status_code == 302
        user.profile.refresh_from_db()
        assert user.profile.timezone == ""


class TestProfileViews:
    """Tests for profile views."""

    def test_profile_view_requires_login(self, client):
        """Profile view should require authentication."""
        response = client.get(reverse("profile"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_profile_view_authenticated(self, client, user):
        """Authenticated user should see their profile."""
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("profile"))
        assert response.status_code == 200
        assert "profile" in response.context

    def test_profile_edit_view_requires_login(self, client):
        """Profile edit view should require authentication."""
        response = client.get(reverse("profile_edit"))
        assert response.status_code == 302

    def test_profile_edit_view_authenticated(self, client, user):
        """Authenticated user should see profile edit form."""
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("profile_edit"))
        assert response.status_code == 200
        assert "form" in response.context

    def test_profile_edit_update(self, client, user):
        """User should be able to update their profile."""
        client.login(username="testuser", password="testpass123")
        response = client.post(
            reverse("profile_edit"),
            {
                "display_name": "New Display Name",
                "bio": "Test bio content",
                "location": "Test City",
            },
        )
        assert response.status_code == 302  # Redirect on success

        user.profile.refresh_from_db()
        assert user.profile.display_name == "New Display Name"
        assert user.profile.bio == "Test bio content"

    def test_profile_edit_email(self, client, user):
        """User should be able to update their email via profile form."""
        client.login(username="testuser", password="testpass123")
        response = client.post(
            reverse("profile_edit"),
            {
                "email": "newemail@example.com",
                "display_name": "Test User",
            },
        )
        assert response.status_code == 302  # Redirect on success

        user.refresh_from_db()
        assert user.email == "newemail@example.com"

    def test_profile_detail_view_public(self, client, user):
        """Anyone should be able to view a user's public profile."""
        response = client.get(reverse("profile_detail", kwargs={"username": user.username}))
        assert response.status_code == 200
        assert response.context["profile"].user == user

    @pytest.mark.django_db
    def test_profile_detail_view_404(self, client):
        """Profile detail should return 404 for non-existent user."""
        response = client.get(reverse("profile_detail", kwargs={"username": "nonexistent"}))
        assert response.status_code == 404


class TestThemePreferenceView:
    """Tests for the theme preference endpoint."""

    def test_theme_save_requires_login(self, client):
        """Theme preference endpoint should require authentication."""
        response = client.post(reverse("theme_preference"), {"theme": "light"})
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_theme_save_dark(self, client, user):
        """Authenticated user should be able to save dark theme."""
        client.login(username="testuser", password="testpass123")
        response = client.post(reverse("theme_preference"), {"theme": "dark"})
        assert response.status_code == 204
        user.profile.refresh_from_db()
        assert user.profile.theme_preference == "dark"

    def test_theme_save_light(self, client, user):
        """Authenticated user should be able to save light theme."""
        client.login(username="testuser", password="testpass123")
        response = client.post(reverse("theme_preference"), {"theme": "light"})
        assert response.status_code == 204
        user.profile.refresh_from_db()
        assert user.profile.theme_preference == "light"

    def test_theme_save_invalid_value(self, client, user):
        """Invalid theme value should be ignored (no error, no change)."""
        client.login(username="testuser", password="testpass123")
        original = user.profile.theme_preference
        response = client.post(reverse("theme_preference"), {"theme": "invalid"})
        assert response.status_code == 204
        user.profile.refresh_from_db()
        assert user.profile.theme_preference == original

    def test_theme_save_get_not_allowed(self, client, user):
        """GET requests should return 405."""
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("theme_preference"))
        assert response.status_code == 405
