"""Explorer access-control fixes from the 2026-11-14 access-control round.

B1: a token's owner can't be changed after it is made (Explorer and Django admin).
B2: the models that hold access itself always check Django model permissions.
B3: delete (single or bulk) follows the ModelAdmin's has_delete_permission and
    a read-only model's missing Delete action.
B4: the Explorer example pages and index widgets follow model permissions.
"""

from __future__ import annotations

import json

import pytest
from django.contrib import admin
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.urls import reverse

from apps.explorer.registry import ExplorerSite, explorer_uses_model_permissions
from apps.runbook.models import Runbook
from apps.smallstack.admin import APITokenAdmin, LogEntryAdmin
from apps.smallstack.crud import Action, BulkAction
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()
TOKENS = "explorer/auth/apitoken"


def grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def staff():
    return User.objects.create_user("fx-staff", password="p", is_staff=True)


@pytest.fixture
def root():
    return User.objects.create_superuser("fx-root", password="p", email="r@example.com")


@pytest.fixture
def token(staff):
    return APIToken.create_token(user=staff, name="mine")[0]


def _build(model, admin_class, **attrs):
    site = ExplorerSite()
    admin_class = type(admin_class.__name__, (admin_class,), attrs) if attrs else admin_class
    site.register(model, admin_class, group="Fixes")
    site.build_crud_classes()
    return site._crud_classes[0]


def _url(view_cls, name):
    for pattern in view_cls.get_urls():
        if pattern.name and pattern.name.endswith(name):
            return pattern
    return None


# --- B1 ----------------------------------------------------------------------


def test_b1_explorer_token_owner_cannot_be_moved(client, staff, root, token):
    manager = grant(staff, "view_apitoken", "change_apitoken")
    client.force_login(manager)
    r = client.post(
        reverse(f"{TOKENS}-update", kwargs={"pk": token.pk}),
        {"name": "renamed", "user": root.pk, "token_type": "manual", "access_level": "staff", "is_active": "on"},
    )
    assert r.status_code in (200, 302)
    token.refresh_from_db()
    assert token.user_id == staff.pk  # the key still authenticates only as its maker
    assert token.name == "renamed"  # the rest of the form still saves


def test_b1_explorer_token_owner_is_chosen_on_create(client, staff, root):
    manager = grant(staff, "view_apitoken", "add_apitoken")
    client.force_login(manager)
    client.post(
        reverse(f"{TOKENS}-create"),
        {"name": "for-root", "user": root.pk, "token_type": "manual", "access_level": "staff", "is_active": "on"},
    )
    assert APIToken.objects.filter(name="for-root", user=root).exists()


def test_b1_django_admin_token_owner_is_read_only_on_change(staff, token):
    request = RequestFactory().get("/")
    request.user = staff
    model_admin = APITokenAdmin(APIToken, admin.site)
    assert "user" in model_admin.get_readonly_fields(request, token)
    assert "user" not in model_admin.get_readonly_fields(request, None)


def test_b1_django_admin_post_cannot_move_token(client, staff, root, token):
    manager = grant(staff, "view_apitoken", "change_apitoken")
    client.force_login(manager)
    client.post(
        f"/admin/smallstack/apitoken/{token.pk}/change/",
        {"name": "x", "user": root.pk, "token_type": "manual", "access_level": "staff", "is_active": "on"},
    )
    token.refresh_from_db()
    assert token.user_id == staff.pk


# --- B2 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_label", ["accounts.user", "auth.group", "auth.permission", "smallstack.apitoken", "admin.logentry"]
)
def test_b2_access_models_always_check_permissions(settings, model_label):
    from django.apps import apps

    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False
    model = apps.get_model(model_label)
    # Even a ModelAdmin that opts out can't make these staff-for-all.
    opted_out = type("OptOut", (admin.ModelAdmin,), {"explorer_model_permissions": False})
    assert explorer_uses_model_permissions(opted_out, model)


def test_b2_ordinary_models_keep_the_site_setting(settings):
    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False
    assert not explorer_uses_model_permissions(admin.ModelAdmin, Runbook)


def test_b2_plain_staff_cannot_edit_accounts_in_explorer(client, staff, root, settings):
    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False
    client.force_login(staff)
    url_base = next(p.name for p in _all_explorer_patterns() if p.name.endswith("accounts/user-update"))
    r = client.post(reverse(url_base, kwargs={"pk": root.pk}), {"username": root.username, "is_active": ""})
    assert r.status_code == 403
    root.refresh_from_db()
    assert root.is_active


def test_b2_plain_staff_cannot_open_tokens_in_explorer(client, staff, token, settings):
    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False
    client.force_login(staff)
    assert client.get(reverse(f"{TOKENS}-list")).status_code == 403
    assert client.get(reverse(f"{TOKENS}-update", kwargs={"pk": token.pk})).status_code == 403


def test_b2_group_built_from_djangos_admin_checks_permissions(staff, settings):
    from django.contrib.auth.admin import GroupAdmin

    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False
    crud = _build(Group, GroupAdmin)
    request = RequestFactory().get("/")
    request.user = staff
    assert not crud.has_model_permission(request, "change")


def _all_explorer_patterns():
    from apps.explorer.registry import explorer

    return explorer.get_url_patterns()


# --- B3 ----------------------------------------------------------------------


def _log_entry(user):
    return LogEntry.objects.create(
        user=user,
        content_type=ContentType.objects.get_for_model(Runbook),
        object_id="1",
        object_repr="x",
        action_flag=ADDITION,
    )


def test_b3_read_only_explorer_model_offers_no_bulk_delete(staff, root):
    crud = _build(LogEntry, LogEntryAdmin)
    assert crud.actions == [Action.LIST, Action.DETAIL]
    assert crud.bulk_actions == []
    request = RequestFactory().get("/")
    request.user = root
    assert crud.permitted_bulk_actions(request) == []
    assert _url(crud, "-bulk") is None


def test_b3_bulk_delete_refused_when_view_has_no_delete_action(staff, root):
    """crud.py: bulk delete needs Action.DELETE in ``actions`` too."""
    crud = _build(LogEntry, LogEntryAdmin)
    assert Action.DELETE not in crud.actions
    crud.bulk_actions = [BulkAction.DELETE]  # what e385789 built for every read-only model
    entry = _log_entry(root)
    from apps.smallstack.crud import _CRUDBulkActionView

    view = type("B", (_CRUDBulkActionView,), {"crud_config": crud}).as_view()
    request = RequestFactory().post("/", json.dumps({"action": "delete", "ids": [entry.pk]}), "application/json")
    request.user = root
    request._dont_enforce_csrf_checks = True
    response = view(request)
    assert response.status_code == 403
    assert LogEntry.objects.filter(pk=entry.pk).exists()


def test_b3_modeladmin_has_delete_permission_is_honoured(staff, root, settings):
    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False

    class NoDelete(admin.ModelAdmin):
        def has_delete_permission(self, request, obj=None):
            return False

    crud = _build(Runbook, NoDelete)
    book = Runbook.objects.create(name="Keep", slug="keep")
    for user in (staff, root):
        request = RequestFactory().get("/")
        request.user = user
        assert not crud.has_model_permission(request, "delete")
        assert Action.DELETE not in crud.permitted_actions(request)
        assert crud.permitted_bulk_actions(request) == []
    from apps.smallstack.crud import _CRUDBulkActionView

    view = type("B", (_CRUDBulkActionView,), {"crud_config": crud}).as_view()
    request = RequestFactory().post("/", json.dumps({"action": "delete", "ids": [book.pk]}), "application/json")
    request.user = staff
    request._dont_enforce_csrf_checks = True
    assert view(request).status_code == 403
    assert Runbook.objects.filter(pk=book.pk).exists()


def test_b3_logentry_delete_superuser_only_per_its_admin(staff, root):
    crud = _build(LogEntry, LogEntryAdmin)
    request = RequestFactory().get("/")
    request.user = grant(staff, "view_logentry", "delete_logentry")
    assert not crud.has_model_permission(request, "delete")


# --- B4 ----------------------------------------------------------------------


@pytest.fixture
def perms_on(settings):
    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = True


def test_b4_example_model_page_refuses_without_view(client, staff, perms_on):
    Runbook.objects.create(name="B4 Secret Book", slug="b4-secret")
    client.force_login(staff)
    r = client.get("/smallstack/explorer/examples/model/smallstack_runbook/runbook/")
    assert r.status_code == 403
    assert b"B4 Secret Book" not in r.content


def test_b4_example_model_page_refuses_accounts_with_setting_off(client, staff, root, settings):
    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False
    client.force_login(staff)
    r = client.get("/smallstack/explorer/examples/model/accounts/user/")
    assert r.status_code == 403
    assert root.email.encode() not in r.content


def test_b4_example_model_page_opens_with_view(client, staff, perms_on):
    Runbook.objects.create(name="B4 Open Book", slug="b4-open")
    client.force_login(grant(staff, "view_runbook"))
    r = client.get("/smallstack/explorer/examples/model/smallstack_runbook/runbook/")
    assert r.status_code == 200
    assert b"B4 Open Book" in r.content


def test_b4_example_app_and_group_pages_leave_out_unviewable_models(client, staff, perms_on):
    client.force_login(staff)
    r = client.get("/smallstack/explorer/examples/app/smallstack_runbook/")
    assert r.status_code == 200
    assert r.context["models"] == []
    assert "smallstack_runbook" not in r.context["all_apps"]
    r = client.get("/smallstack/explorer/examples/group/monitoring/")
    assert r.status_code == 200
    assert r.context["models"] == []


def test_b4_index_widgets_follow_model_permissions(client, staff, perms_on):
    client.force_login(staff)
    r = client.get(reverse("explorer-index") + "?group=Monitoring&view=widgets")
    assert r.status_code == 200
    assert not r.context["has_widgets"]
    client.force_login(grant(staff, "view_heartbeat"))
    r = client.get(reverse("explorer-index") + "?group=Monitoring&view=widgets")
    assert [c["model_name"] for c in r.context["widget_contexts"]] == ["heartbeat"]
