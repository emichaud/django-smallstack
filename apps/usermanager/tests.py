"""Tests for the User Manager app."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


class TestUserListView:
    """Tests for the user list page."""

    def test_requires_staff(self, client, user):
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("manage/users-list"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list"))
        assert response.status_code == 200

    def test_has_table_context(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list"))
        assert "table" in response.context

    def test_search_filters_users(self, client, staff_user, user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list") + "?q=testuser")
        assert response.status_code == 200
        content = response.content.decode()
        assert "testuser" in content

    def test_search_htmx_returns_partial(self, client, staff_user, user):
        client.force_login(staff_user)
        response = client.get(
            reverse("manage/users-list") + "?q=test",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "<html" not in content

    def test_breadcrumbs_in_title_bar(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-list"))
        content = response.content.decode()
        assert "Home" in content
        assert "Users" in content


class TestUserEditView:
    """Tests for the user edit page."""

    def test_requires_staff(self, client, user):
        client.login(username="testuser", password="testpass123")
        response = client.get(reverse("manage/users-update", kwargs={"pk": user.pk}))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user, user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-update", kwargs={"pk": user.pk}))
        assert response.status_code == 200

    def test_does_not_shadow_logged_in_user(self, client, staff_user, user):
        """Editing another user should not shadow the logged-in user context."""
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-update", kwargs={"pk": user.pk}))
        # The auth user in context should still be the staff user, not the edited user
        assert response.context["user"].username == "staffuser"


class TestUserStatDetail:
    """Tests for the stat detail drilldown endpoint."""

    def test_requires_staff(self, client, user):
        client.force_login(user)
        response = client.get(reverse("manage/users-stat-detail", kwargs={"stat_type": "total"}))
        # Uses @staff_member_required which redirects non-staff
        assert response.status_code == 302

    def test_total_returns_html(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("manage/users-stat-detail", kwargs={"stat_type": "total"}))
        assert response.status_code == 200
        assert "<table" in response.content.decode()
