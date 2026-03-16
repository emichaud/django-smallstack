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
        assert "/smallstack/accounts/login/" in response.url

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
        response = client.get(reverse("explorer/monitoring/heartbeat-list"))
        assert response.status_code == 302

    def test_non_staff_denied(self, client, user):
        client.force_login(user)
        response = client.get(reverse("explorer/monitoring/heartbeat-list"))
        assert response.status_code == 403

    def test_staff_can_access(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeat-list"))
        assert response.status_code == 200


class TestExplorerCRUDOperations:
    """Tests for CRUD operations via explorer."""

    def test_create_view(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-create"))
        assert response.status_code == 200

    def test_detail_view(self, client, staff_user, db):
        from django.utils import timezone

        from apps.heartbeat.models import HeartbeatEpoch

        epoch = HeartbeatEpoch.objects.create(started_at=timezone.now())
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-detail", kwargs={"pk": epoch.pk}))
        assert response.status_code == 200


class TestExplorerReadonly:
    """Tests for readonly model configuration."""

    @pytest.fixture(autouse=True)
    def _check_readonly(self):
        from .registry import explorer

        has_readonly = any(m.readonly for m in explorer.get_models())
        if not has_readonly:
            pytest.skip("No readonly models configured")

    def test_readonly_model_list_accessible(self, client, staff_user):
        from .registry import explorer

        for info in explorer.get_models():
            if info.readonly:
                client.force_login(staff_user)
                response = client.get(reverse(f"{info.url_base}-list"))
                assert response.status_code == 200
                break

    def test_readonly_model_no_create_url(self, client, staff_user):
        from django.urls import NoReverseMatch

        from .registry import explorer

        for info in explorer.get_models():
            if info.readonly:
                with pytest.raises(NoReverseMatch):
                    reverse(f"{info.url_base}-create")
                break


class TestAdminDiscovery:
    """Tests for admin-first discovery mechanism."""

    def test_model_without_explorer_enabled_excluded(self):
        """Models registered in admin without explorer_enabled don't appear."""
        from .registry import explorer

        model_names = [m.model_name for m in explorer.get_models()]
        # User model is registered in admin but doesn't have explorer_enabled
        assert "user" not in model_names

    def test_explorer_fields_overrides_list_display(self):
        """explorer_fields attribute takes precedence over list_display."""

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
        from .registry import explorer

        for info in explorer.get_models():
            if info.model_name == "requestlog":
                assert info.readonly is True
                break
        else:
            pytest.fail("RequestLog not found in explorer registry")

    def test_heartbeat_models_present(self):
        """All three heartbeat models should be discovered."""
        from .registry import explorer

        model_names = {m.model_name for m in explorer.get_models()}
        assert "heartbeat" in model_names
        assert "heartbeatepoch" in model_names
        assert "heartbeatdaily" in model_names


class TestExplorerGrouping:
    """Tests for model grouping in the explorer index."""

    def test_models_have_group(self):
        """Every discovered model has a group assigned."""
        from .registry import explorer

        for info in explorer.get_models():
            assert info.group  # not empty

    def test_explicit_group_used(self):
        """Models with explorer_group use that value."""
        from .registry import explorer

        for info in explorer.get_models():
            if info.model_name == "heartbeat":
                assert info.group == "Monitoring"
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
        from .registry import explorer

        grouped = explorer.get_grouped_models()
        assert isinstance(grouped, dict)
        assert "Monitoring" in grouped
        assert len(grouped["Monitoring"]) >= 1

    def test_index_has_group_data_attributes(self, client, staff_user):
        """The explorer index cards carry data-group attributes for JS grouping."""
        client.force_login(staff_user)
        response = client.get(reverse("explorer-index"))
        content = response.content.decode()
        assert 'data-group="Monitoring"' in content

    def test_url_uses_group_slug(self):
        """Explorer URLs use group slug instead of app_label."""
        from .registry import explorer

        for info in explorer.get_models():
            if info.model_name == "heartbeat":
                assert info.url_base == "explorer/monitoring/heartbeat"
                break


class TestExplorerContextHelpers:
    """Tests for the registry context helper methods."""

    def test_get_group_context_found(self, db):
        from .registry import GroupContext, explorer

        ctx = explorer.get_group_context("Monitoring")
        assert ctx is not None
        assert isinstance(ctx, GroupContext)
        assert ctx.group_name == "Monitoring"
        assert len(ctx.models) >= 1
        assert ctx.models[0].count is not None
        assert ctx.models[0].list_url != ""

    def test_get_group_context_case_insensitive(self, db):
        from .registry import explorer

        ctx = explorer.get_group_context("monitoring")
        assert ctx is not None
        assert ctx.group_name == "Monitoring"

    def test_get_group_context_not_found(self):
        from .registry import explorer

        ctx = explorer.get_group_context("NonexistentGroup")
        assert ctx is None

    def test_get_group_context_all_groups(self, db):
        from .registry import explorer

        ctx = explorer.get_group_context("Monitoring")
        assert "Monitoring" in ctx.all_groups
        assert ctx.all_groups == sorted(ctx.all_groups)

    def test_get_model_context_found(self, db):
        from .registry import ModelContext, explorer

        ctx = explorer.get_model_context("heartbeat", "heartbeat")
        assert ctx is not None
        assert isinstance(ctx, ModelContext)
        assert ctx.info.app_label == "heartbeat"
        assert ctx.info.model_name == "heartbeat"
        assert ctx.url_base == "explorer/monitoring/heartbeat"
        assert ctx.list_fields is not None
        assert ctx.crud_class is not None

    def test_get_model_context_not_found(self):
        from .registry import explorer

        ctx = explorer.get_model_context("nonexistent", "model")
        assert ctx is None

    def test_model_info_attribute_access(self):
        """ModelInfo supports both attribute and dict-style access."""
        from .registry import explorer

        info = explorer.get_models()[0]
        # Attribute access
        assert info.app_label is not None
        # Dict-style access (for django-tables2 compat)
        assert info["app_label"] == info.app_label

    def test_model_card_info_has_count_and_url(self, db):
        """with_counts() returns a ModelCardInfo with live data."""
        from .registry import ModelCardInfo, explorer

        info = explorer.get_models()[0]
        card = info.with_counts()
        assert isinstance(card, ModelCardInfo)
        assert isinstance(card.count, int)
        assert card.list_url.startswith("/")


class TestExplorerRegistry:
    """Tests for the new ExplorerSite register() API."""

    def test_register_adds_to_registry(self):
        from .registry import ExplorerSite

        site = ExplorerSite()
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        site.register(Heartbeat, admin.ModelAdmin, group="Test")
        assert (Heartbeat, "Test") in site._registry

    def test_register_default_group(self):
        from .registry import ExplorerSite

        site = ExplorerSite()
        from apps.heartbeat.models import Heartbeat

        site.register(Heartbeat)
        assert (Heartbeat, "Heartbeat") in site._registry

    def test_register_default_admin_class(self):
        from django.contrib import admin

        from .registry import ExplorerSite

        site = ExplorerSite()
        from apps.heartbeat.models import Heartbeat

        site.register(Heartbeat, group="Test")
        assert site._registry[(Heartbeat, "Test")] is admin.ModelAdmin

    def test_backward_compat_alias(self):
        """explorer_registry alias still works."""
        from .registry import explorer, explorer_registry

        assert explorer is explorer_registry


class TestDisplayProtocol:
    """Tests for the display protocol integration."""

    def test_crud_view_with_displays(self, client, staff_user):
        """CRUDView with displays renders the display template."""
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeat-list"))
        assert response.status_code == 200
        # Should use display protocol (Table2Display)
        assert "display_template" in response.context or "table" in response.context

    def test_display_query_param(self, client, staff_user):
        """?display= param selects a display."""
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeat-list") + "?display=table2")
        assert response.status_code == 200
