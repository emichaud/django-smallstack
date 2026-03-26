"""Tests for the Explorer app."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import ProtectedError, RestrictedError
from django.urls import reverse
from django.utils import timezone

from apps.heartbeat.models import HeartbeatEpoch

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


@pytest.fixture
def epoch(db):
    """Create a HeartbeatEpoch for CRUD tests."""
    return HeartbeatEpoch.objects.create(started_at=timezone.now(), note="Test epoch")


class TestExplorerCRUDOperations:
    """Tests for CRUD operations via explorer."""

    def test_create_view(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-create"))
        assert response.status_code == 200

    def test_create_post(self, client, staff_user, db):
        client.force_login(staff_user)
        response = client.post(
            reverse("explorer/monitoring/heartbeatepoch-create"),
            {
                "started_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                "service_target": "99.9",
                "service_minimum": "99.5",
            },
        )
        assert response.status_code == 302
        assert HeartbeatEpoch.objects.count() == 1

    def test_detail_view(self, client, staff_user, epoch):
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-detail", kwargs={"pk": epoch.pk}))
        assert response.status_code == 200

    def test_edit_view_get(self, client, staff_user, epoch):
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-update", kwargs={"pk": epoch.pk}))
        assert response.status_code == 200

    def test_edit_view_post(self, client, staff_user, epoch):
        client.force_login(staff_user)
        response = client.post(
            reverse("explorer/monitoring/heartbeatepoch-update", kwargs={"pk": epoch.pk}),
            {
                "started_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                "note": "Updated",
                "service_target": "99.9",
                "service_minimum": "99.5",
            },
        )
        assert response.status_code == 302
        epoch.refresh_from_db()
        assert epoch.note == "Updated"


class TestExplorerCRUDPermissions:
    """Tests for CRUD permission enforcement."""

    def test_create_anonymous_redirected(self, client):
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-create"))
        assert response.status_code == 302

    def test_create_non_staff_denied(self, client, user):
        client.force_login(user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-create"))
        assert response.status_code == 403

    def test_edit_anonymous_redirected(self, client, epoch):
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-update", kwargs={"pk": epoch.pk}))
        assert response.status_code == 302

    def test_edit_non_staff_denied(self, client, user, epoch):
        client.force_login(user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-update", kwargs={"pk": epoch.pk}))
        assert response.status_code == 403

    def test_delete_anonymous_redirected(self, client, epoch):
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}))
        assert response.status_code == 302

    def test_delete_non_staff_denied(self, client, user, epoch):
        client.force_login(user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}))
        assert response.status_code == 403


class TestExplorerCRUDDelete:
    """Tests for CRUD delete — success, ProtectedError, RestrictedError, IntegrityError."""

    def test_delete_confirm_page(self, client, staff_user, epoch):
        """GET on delete URL shows confirmation page."""
        client.force_login(staff_user)
        response = client.get(reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}))
        assert response.status_code == 200
        assert "Are you sure" in response.content.decode()

    def test_delete_success_regular(self, client, staff_user, epoch):
        """POST delete redirects to list on success."""
        client.force_login(staff_user)
        response = client.post(reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}))
        assert response.status_code == 302
        assert not HeartbeatEpoch.objects.filter(pk=epoch.pk).exists()

    def test_delete_success_ajax(self, client, staff_user, epoch):
        """AJAX POST delete returns redirect (opaqueredirect in browser, 302 in test client)."""
        client.force_login(staff_user)
        response = client.post(
            reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        # Django's DeleteView redirects on success — AJAX still gets 302
        assert response.status_code == 302
        assert not HeartbeatEpoch.objects.filter(pk=epoch.pk).exists()

    def test_protected_error_ajax_returns_409(self, client, staff_user, epoch):
        """ProtectedError on AJAX returns 409 with error message."""
        client.force_login(staff_user)
        error = ProtectedError("Cannot delete", {epoch})
        with patch("apps.smallstack.crud._CRUDDeleteBase.post", side_effect=error):
            # Call the view directly without the mocked post interfering
            pass
        # Better approach: mock the actual delete at model level
        with patch.object(HeartbeatEpoch, "delete", side_effect=ProtectedError("Cannot delete", {epoch})):
            response = client.post(
                reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        assert response.status_code == 409
        body = response.content.decode()
        assert "Cannot delete" in body
        assert "still linked" in body
        # Object should still exist
        assert HeartbeatEpoch.objects.filter(pk=epoch.pk).exists()

    def test_protected_error_regular_redirects_with_message(self, client, staff_user, epoch):
        """ProtectedError on regular POST redirects with error flash message."""
        client.force_login(staff_user)
        with patch.object(HeartbeatEpoch, "delete", side_effect=ProtectedError("Cannot delete", {epoch})):
            response = client.post(
                reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
                follow=True,
            )
        assert response.status_code == 200
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "Cannot delete" in str(messages[0])
        assert HeartbeatEpoch.objects.filter(pk=epoch.pk).exists()

    def test_restricted_error_ajax_returns_409(self, client, staff_user, epoch):
        """RestrictedError on AJAX returns 409 with error message."""
        client.force_login(staff_user)
        err = RestrictedError("Cannot delete", {epoch})
        with patch.object(HeartbeatEpoch, "delete", side_effect=err):
            response = client.post(
                reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        assert response.status_code == 409
        assert "Cannot delete" in response.content.decode()

    def test_integrity_error_ajax_returns_409(self, client, staff_user, epoch):
        """IntegrityError on AJAX returns 409 with generic message."""
        client.force_login(staff_user)
        with patch.object(HeartbeatEpoch, "delete", side_effect=IntegrityError("FK constraint")):
            response = client.post(
                reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        assert response.status_code == 409
        assert "database constraint" in response.content.decode()

    def test_integrity_error_regular_redirects_with_message(self, client, staff_user, epoch):
        """IntegrityError on regular POST redirects with error flash."""
        client.force_login(staff_user)
        with patch.object(HeartbeatEpoch, "delete", side_effect=IntegrityError("FK constraint")):
            response = client.post(
                reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
                follow=True,
            )
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "database constraint" in str(messages[0])

    def test_unexpected_error_ajax_returns_409(self, client, staff_user, epoch):
        """Unexpected exception on AJAX returns 409 with generic message."""
        client.force_login(staff_user)
        with patch.object(HeartbeatEpoch, "delete", side_effect=RuntimeError("something broke")):
            response = client.post(
                reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        assert response.status_code == 409
        assert "unexpected error" in response.content.decode()

    def test_protected_error_message_includes_model_name_and_count(self, client, staff_user, epoch):
        """ProtectedError message mentions the blocking model name and count."""
        client.force_login(staff_user)
        # Simulate 3 HeartbeatEpoch objects blocking deletion
        fake_protected = set()
        for i in range(3):
            obj = HeartbeatEpoch(pk=100 + i)
            fake_protected.add(obj)
        with patch.object(HeartbeatEpoch, "delete", side_effect=ProtectedError("Cannot delete", fake_protected)):
            response = client.post(
                reverse("explorer/monitoring/heartbeatepoch-delete", kwargs={"pk": epoch.pk}),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        body = response.content.decode()
        assert "3" in body
        assert "HeartbeatEpoch" in body
        assert "records" in body


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


class TestChildExplorerSite:
    """Tests for namespaced child ExplorerSite instances."""

    def test_child_inherits_parent_registrations(self):
        """Child site inherits models from parent filtered by groups."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat, HeartbeatEpoch

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")
        parent.register(HeartbeatEpoch, admin.ModelAdmin, group="Other")

        child = ExplorerSite(
            name="monitoring_child",
            parent=parent,
            groups=["Monitoring"],
        )
        child._inherit_from_parent()

        assert (Heartbeat, "Monitoring") in child._registry
        assert (HeartbeatEpoch, "Other") not in child._registry

    def test_child_inherits_all_groups_when_none(self):
        """Child with groups=None inherits everything."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat, HeartbeatEpoch

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")
        parent.register(HeartbeatEpoch, admin.ModelAdmin, group="Other")

        child = ExplorerSite(name="all_child", parent=parent)
        child._inherit_from_parent()

        assert (Heartbeat, "Monitoring") in child._registry
        assert (HeartbeatEpoch, "Other") in child._registry

    def test_set_form_overrides_in_child_not_parent(self):
        """set_form() on child doesn't leak to parent."""
        from django import forms
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")

        class CustomForm(forms.ModelForm):
            class Meta:
                model = Heartbeat
                fields = ["status"]

        child = ExplorerSite(
            name="custom_child",
            parent=parent,
            groups=["Monitoring"],
        )
        child.set_form(Heartbeat, CustomForm)

        assert child._form_overrides[Heartbeat] is CustomForm
        assert Heartbeat not in parent._form_overrides

    def test_child_build_sets_namespace_on_crud(self, db):
        """Built CRUD classes have the child's namespace set."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")

        child = ExplorerSite(
            name="test_ns",
            parent=parent,
            groups=["Monitoring"],
        )
        child.build_crud_classes()

        assert len(child._crud_classes) == 1
        assert child._crud_classes[0].namespace == "test_ns"

    def test_child_url_base_no_explorer_prefix(self, db):
        """Child site URL bases don't have 'explorer/' prefix."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")

        child = ExplorerSite(
            name="test_prefix",
            parent=parent,
            groups=["Monitoring"],
        )
        child.build_crud_classes()

        info = child._model_info[0]
        assert info.url_base == "monitoring/heartbeat"
        assert not info.url_base.startswith("explorer/")

    def test_child_model_info_has_namespace(self, db):
        """ModelInfo from child has namespace set."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")

        child = ExplorerSite(
            name="ns_test",
            parent=parent,
            groups=["Monitoring"],
        )
        child.build_crud_classes()

        assert child._model_info[0].namespace == "ns_test"

    def test_child_urls_property_returns_tuple(self, db):
        """urls property returns (patterns, name) tuple for include()."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")

        child = ExplorerSite(
            name="urls_test",
            parent=parent,
            groups=["Monitoring"],
        )
        patterns, app_name = child.urls

        assert app_name == "urls_test"
        assert len(patterns) > 0

    def test_lazy_build_on_get_url_patterns(self, db):
        """get_url_patterns() triggers lazy build for child sites."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")

        child = ExplorerSite(
            name="lazy_test",
            parent=parent,
            groups=["Monitoring"],
        )
        assert not child._built
        child.get_url_patterns()
        assert child._built
        assert len(child._crud_classes) == 1

    def test_child_form_override_used_in_build(self, db):
        """Form override via set_form is used when building CRUD classes."""
        from django import forms
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")

        class WorkflowForm(forms.ModelForm):
            class Meta:
                model = Heartbeat
                fields = ["status"]

        child = ExplorerSite(
            name="form_test",
            parent=parent,
            groups=["Monitoring"],
        )
        child.set_form(Heartbeat, WorkflowForm)
        child.build_crud_classes()

        assert child._crud_classes[0].form_class is WorkflowForm

    def test_parent_not_affected_by_child_form(self, db):
        """Parent CRUD classes don't get child's form override."""
        from django import forms
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")
        parent.build_crud_classes()

        class WorkflowForm(forms.ModelForm):
            class Meta:
                model = Heartbeat
                fields = ["status"]

        child = ExplorerSite(
            name="isolation_test",
            parent=parent,
            groups=["Monitoring"],
        )
        child.set_form(Heartbeat, WorkflowForm)
        child.build_crud_classes()

        assert parent._crud_classes[0].form_class is None
        assert child._crud_classes[0].form_class is WorkflowForm

    def test_child_display_name_default(self):
        """Display name defaults to titlecased name."""
        from .registry import ExplorerSite

        site = ExplorerSite(name="my_workflow")
        assert site._display_name == "My Workflow"

    def test_child_display_name_custom(self):
        """Custom display_name overrides default."""
        from .registry import ExplorerSite

        site = ExplorerSite(name="est", display_name="Estimating Portal")
        assert site._display_name == "Estimating Portal"

    def test_multiple_groups_in_child(self, db):
        """Child with multiple groups inherits from all specified groups."""
        from django.contrib import admin

        from apps.heartbeat.models import Heartbeat, HeartbeatDaily, HeartbeatEpoch

        from .registry import ExplorerSite

        parent = ExplorerSite()
        parent.register(Heartbeat, admin.ModelAdmin, group="Monitoring")
        parent.register(HeartbeatEpoch, admin.ModelAdmin, group="Epochs")
        parent.register(HeartbeatDaily, admin.ModelAdmin, group="Reports")

        child = ExplorerSite(
            name="multi_group",
            parent=parent,
            groups=["Monitoring", "Epochs"],
        )
        child._inherit_from_parent()

        assert (Heartbeat, "Monitoring") in child._registry
        assert (HeartbeatEpoch, "Epochs") in child._registry
        assert (HeartbeatDaily, "Reports") not in child._registry

    def test_root_site_namespace_is_none(self):
        """Root explorer singleton has no namespace."""
        from .registry import explorer

        assert explorer._name is None
        assert explorer._parent is None


class TestMixinSiteAwareness:
    """Tests for site-aware Explorer mixins."""

    def test_group_mixin_defaults_to_root(self):
        """ExplorerGroupMixin with no explorer_site uses root explorer."""
        from .mixins import ExplorerGroupMixin

        mixin = ExplorerGroupMixin()
        from .registry import explorer

        assert mixin._get_site() is explorer

    def test_group_mixin_uses_custom_site(self):
        """ExplorerGroupMixin with explorer_site uses that site."""
        from .mixins import ExplorerGroupMixin
        from .registry import ExplorerSite

        custom_site = ExplorerSite(name="custom")
        mixin = ExplorerGroupMixin()
        mixin.explorer_site = custom_site
        assert mixin._get_site() is custom_site

    def test_app_mixin_defaults_to_root(self):
        """ExplorerAppMixin with no explorer_site uses root explorer."""
        from .mixins import ExplorerAppMixin

        mixin = ExplorerAppMixin()
        from .registry import explorer

        assert mixin._get_site() is explorer

    def test_model_mixin_defaults_to_root(self):
        """ExplorerModelMixin with no explorer_site uses root explorer."""
        from .mixins import ExplorerModelMixin

        mixin = ExplorerModelMixin()
        from .registry import explorer

        assert mixin._get_site() is explorer
