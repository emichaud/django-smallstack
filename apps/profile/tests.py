"""
Tests for the profile app.
"""

import pytest
from django.contrib.auth import get_user_model
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
