"""Tests for the website app views."""

import pytest


@pytest.mark.django_db
class TestWebsiteViews:
    """Smoke tests for all website views."""

    def test_home_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"SmallStack" in response.content

    def test_home_page_feature_cards(self, client):
        """Feature cards should render with doc links."""
        response = client.get("/")
        content = response.content.decode()
        assert "feature-card" in content
        assert "Read docs" in content

    def test_home_page_customize_banner(self, client):
        """Customize banner should appear on home page."""
        response = client.get("/")
        content = response.content.decode()
        assert "Make it yours" in content
        assert "customization" in content

    def test_about_page(self, client):
        response = client.get("/about/")
        assert response.status_code == 200

    def test_getting_started_page(self, client):
        response = client.get("/getting-started/")
        assert response.status_code == 200

    def test_starter_page(self, client):
        response = client.get("/starter/")
        assert response.status_code == 200

    def test_starter_basic_page(self, client):
        response = client.get("/starter/basic/")
        assert response.status_code == 200

    def test_starter_forms_page(self, client):
        response = client.get("/starter/forms/")
        assert response.status_code == 200

    def test_components_redirects(self, client):
        response = client.get("/components/")
        assert response.status_code == 302
        assert "/help/" in response.url


@pytest.mark.django_db
class TestHomePageAuthenticated:
    """Test home page with authenticated user."""

    @pytest.fixture
    def staff_user(self, django_user_model):
        return django_user_model.objects.create_user(
            username="staff", password="testpass", is_staff=True
        )

    def test_quick_links_for_staff(self, client, staff_user):
        """Staff users should see all quick links including built-in apps."""
        client.force_login(staff_user)
        response = client.get("/")
        content = response.content.decode()
        assert "quick-link" in content
        assert "Explorer" in content
        assert "Activity" in content
        assert "Status" in content
        assert "Backups" in content
        assert "Dashboard" in content
        assert "Users" in content

    def test_quick_links_for_regular_user(self, client, django_user_model):
        """Regular users should see basic quick links only."""
        user = django_user_model.objects.create_user(
            username="regular", password="testpass"
        )
        client.force_login(user)
        response = client.get("/")
        content = response.content.decode()
        assert "My Profile" in content
        assert "Help &amp; Docs" in content
        # Staff-only links should not appear
        assert "Admin Panel" not in content
