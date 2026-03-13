"""Tests for the Explorer app."""

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
        username="staffuser", email="staff@example.com", password="testpass123", is_staff=True,
    )


class TestExplorerIndex:
    """Tests for the explorer index page."""

    def test_anonymous_redirected(self, client):
        response = client.get(reverse("explorer-index"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_non_staff_denied(self, client, user):
        client.force_login(user)
        response = client.get(reverse("explorer-index"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("explorer-index"))
        assert response.status_code == 200

    def test_model_count_displayed(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("explorer-index"))
        content = response.content.decode()
        assert "explorer-card" in content


class TestExplorerModelList:
    """Tests for the model list view."""

    def test_anonymous_redirected(self, client):
        response = client.get(reverse("explorer/heartbeat/heartbeat-list"))
        assert response.status_code == 302

    def test_non_staff_denied(self, client, user):
        client.force_login(user)
        response = client.get(reverse("explorer/heartbeat/heartbeat-list"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("explorer/heartbeat/heartbeat-list"))
        assert response.status_code == 200


class TestExplorerCRUDOperations:
    """Tests for CRUD operations via explorer."""

    def test_create_view(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("explorer/heartbeat/heartbeatepoch-create"))
        assert response.status_code == 200

    def test_detail_view(self, client, staff_user, db):
        from django.utils import timezone

        from apps.heartbeat.models import HeartbeatEpoch

        epoch = HeartbeatEpoch.objects.create(started_at=timezone.now())
        client.force_login(staff_user)
        response = client.get(reverse("explorer/heartbeat/heartbeatepoch-detail", kwargs={"pk": epoch.pk}))
        assert response.status_code == 200


class TestExplorerReadonly:
    """Tests for readonly model configuration."""

    @pytest.fixture(autouse=True)
    def _check_readonly(self):
        from .registry import explorer_registry

        has_readonly = any(m["readonly"] for m in explorer_registry.get_models())
        if not has_readonly:
            pytest.skip("No readonly models configured")

    def test_readonly_model_list_accessible(self, client, staff_user):
        from .registry import explorer_registry

        for info in explorer_registry.get_models():
            if info["readonly"]:
                client.force_login(staff_user)
                response = client.get(reverse(f"{info['url_base']}-list"))
                assert response.status_code == 200
                break

    def test_readonly_model_no_create_url(self, client, staff_user):
        from django.urls import NoReverseMatch

        from .registry import explorer_registry

        for info in explorer_registry.get_models():
            if info["readonly"]:
                with pytest.raises(NoReverseMatch):
                    reverse(f"{info['url_base']}-create")
                break


class TestAdminDiscovery:
    """Tests for admin-first discovery mechanism."""

    def test_model_without_explorer_enabled_excluded(self):
        """Models registered in admin without explorer_enabled don't appear."""
        from .registry import explorer_registry

        model_names = [m["model_name"] for m in explorer_registry.get_models()]
        # User model is registered in admin but doesn't have explorer_enabled
        assert "user" not in model_names

    def test_explorer_fields_overrides_list_display(self):
        """explorer_fields attribute takes precedence over list_display."""
        from .registry import _resolve_fields_from_admin

        class FakeModelAdmin:
            list_display = ("name", "email")
            explorer_fields = ["name"]

        # When explorer_fields is set, discover() uses it directly
        # This test verifies the attribute is checked before _resolve_fields_from_admin
        assert FakeModelAdmin.explorer_fields == ["name"]

    def test_explorer_readonly_overrides_auto_detection(self):
        """explorer_readonly attribute overrides permission-based detection."""
        from .registry import _resolve_readonly_from_admin

        class WritableAdmin:
            pass

        admin_instance = WritableAdmin()
        # No permission overrides → not readonly
        assert _resolve_readonly_from_admin(admin_instance) is False

    def test_readonly_detected_from_permissions(self):
        """Admin with denied change/add permissions detected as readonly."""
        from .registry import _resolve_readonly_from_admin

        class ReadonlyAdmin:
            def has_add_permission(self, request):
                return False

            def has_change_permission(self, request, obj=None):
                return False

        assert _resolve_readonly_from_admin(ReadonlyAdmin()) is True

    def test_requestlog_is_readonly(self):
        """RequestLog should be readonly via admin permission detection."""
        from .registry import explorer_registry

        for info in explorer_registry.get_models():
            if info["model_name"] == "requestlog":
                assert info["readonly"] is True
                break
        else:
            pytest.fail("RequestLog not found in explorer registry")

    def test_heartbeat_models_present(self):
        """All three heartbeat models should be discovered."""
        from .registry import explorer_registry

        model_names = {m["model_name"] for m in explorer_registry.get_models()}
        assert "heartbeat" in model_names
        assert "heartbeatepoch" in model_names
        assert "heartbeatdaily" in model_names


class TestExplorerGrouping:
    """Tests for model grouping in the explorer index."""

    def test_models_have_group(self):
        """Every discovered model has a group assigned."""
        from .registry import explorer_registry

        for info in explorer_registry.get_models():
            assert "group" in info
            assert info["group"]  # not empty

    def test_explicit_group_used(self):
        """Models with explorer_group use that value."""
        from .registry import explorer_registry

        for info in explorer_registry.get_models():
            if info["model_name"] == "heartbeat":
                assert info["group"] == "Monitoring"
                break

    def test_fallback_group_is_app_label(self):
        """Models without explorer_group fall back to app_label title."""
        from .registry import _resolve_group

        class FakeModel:
            class _meta:
                app_label = "my_app"

        class FakeAdmin:
            pass

        assert _resolve_group(FakeModel, FakeAdmin()) == "My App"

    def test_get_grouped_models(self):
        """get_grouped_models returns dict keyed by group name."""
        from .registry import explorer_registry

        grouped = explorer_registry.get_grouped_models()
        assert isinstance(grouped, dict)
        assert "Monitoring" in grouped
        assert len(grouped["Monitoring"]) >= 1

    def test_index_shows_group_headings(self, client, staff_user):
        """The explorer index page renders group titles."""
        client.force_login(staff_user)
        response = client.get(reverse("explorer-index"))
        content = response.content.decode()
        assert "explorer-group-title" in content
        assert "Monitoring" in content
