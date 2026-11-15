"""CRUDView: Django model permissions (opt-in), audited web writes, a history
page, and a delete confirmation that says what goes with the row.

* ``model_permissions = True`` checks ``has_perm`` for view / add / change /
  delete on every surface: the generated pages, bulk actions, REST, MCP and
  ``sc --user``. Explorer turns it on with ``SMALLSTACK_EXPLORER_MODEL_PERMISSIONS``.
* The create, edit and delete pages write a ``LogEntry``, as REST, MCP, ``sc``
  and the bulk views already did.
* ``enable_history`` adds ``<pk>/history/``; Explorer has it on.
* The delete page and the delete modal list what cascades, and refuse a
  delete that's protected or, with permissions on, would remove rows of a
  model the user may not delete.
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.runbook.models import Runbook, Section
from apps.smallstack.deletion import summarize_deletion
from apps.smallstack.models import APIToken
from apps.webhooks.models import WebhookReceipt, WebhookReceiver
from apps.webhooks.views import WebhookReceiverCRUDView

pytestmark = pytest.mark.django_db

User = get_user_model()
RUNBOOKS = "explorer/smallstack-runbook/runbook"


def grant(user, *codenames: str):
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    # has_perm caches per user object; a fresh one sees the grant.
    return User.objects.get(pk=user.pk)


@pytest.fixture
def staff():
    return User.objects.create_user("perm-staff", password="p", is_staff=True)


@pytest.fixture
def perms_on(settings):
    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = True


@pytest.fixture
def runbook():
    rb = Runbook.objects.create(name="Ops book", slug="ops-book")
    Section.objects.create(runbook=rb, name="Deploys", slug="deploys")
    Section.objects.create(runbook=rb, name="Backups", slug="backups")
    return rb


def url(name: str, **kwargs) -> str:
    return reverse(f"{RUNBOOKS}-{name}", kwargs=kwargs or None)


# --- model permissions: Explorer pages ---------------------------------------


def test_off_by_default_any_staff_account_keeps_full_access(client, staff, runbook):
    client.force_login(staff)
    assert client.get(url("list")).status_code == 200
    assert client.get(url("update", pk=runbook.pk)).status_code == 200
    assert client.get(url("delete", pk=runbook.pk)).status_code == 200


def test_on_a_staff_account_with_no_permissions_is_refused(client, staff, runbook, perms_on):
    client.force_login(staff)
    for name, kwargs in [("list", {}), ("detail", {"pk": runbook.pk}), ("create", {}),
                         ("update", {"pk": runbook.pk}), ("delete", {"pk": runbook.pk}),
                         ("history", {"pk": runbook.pk})]:
        assert client.get(url(name, **kwargs)).status_code == 403, name
    assert client.post(url("delete", pk=runbook.pk)).status_code == 403
    assert Runbook.objects.filter(pk=runbook.pk).exists()


def test_each_action_needs_its_own_permission(client, staff, runbook, perms_on):
    staff = grant(staff, "view_runbook")
    client.force_login(staff)
    assert client.get(url("list")).status_code == 200
    assert client.get(url("detail", pk=runbook.pk)).status_code == 200
    assert client.get(url("update", pk=runbook.pk)).status_code == 403
    assert client.get(url("create")).status_code == 403
    assert client.post(url("delete", pk=runbook.pk)).status_code == 403


def test_change_implies_view_as_in_django_admin(client, staff, runbook, perms_on):
    client.force_login(grant(staff, "change_runbook"))
    assert client.get(url("detail", pk=runbook.pk)).status_code == 200
    assert client.get(url("update", pk=runbook.pk)).status_code == 200


def test_buttons_follow_the_permissions(client, staff, runbook, perms_on):
    client.force_login(grant(staff, "view_runbook"))
    page = client.get(url("detail", pk=runbook.pk)).content.decode()
    assert 'href="edit/"' not in page and 'data-delete-url="delete/"' not in page
    listing = client.get(url("list"))
    assert "create_view_url" not in listing.context or not listing.context["create_view_url"]
    client.force_login(grant(staff, "change_runbook", "delete_runbook", "add_runbook"))
    page = client.get(url("detail", pk=runbook.pk)).content.decode()
    assert 'href="edit/"' in page and 'data-delete-url="delete/"' in page
    assert client.get(url("list")).context["create_view_url"]


def test_superusers_hold_every_permission(client, runbook, perms_on):
    root = User.objects.create_superuser("perm-root", password="p")
    client.force_login(root)
    assert client.get(url("update", pk=runbook.pk)).status_code == 200


def test_a_model_admin_flag_overrides_the_setting(client, staff, runbook, perms_on, monkeypatch):
    from apps.explorer.registry import explorer

    crud = next(c for c in explorer._crud_classes if c.model is Runbook)
    monkeypatch.setattr(crud.admin_class, "explorer_model_permissions", False, raising=False)
    client.force_login(staff)
    assert client.get(url("update", pk=runbook.pk)).status_code == 200


def test_the_index_hides_models_the_user_may_not_view(client, staff, perms_on):
    client.force_login(grant(staff, "view_runbook"))
    shown = {m.model_name for m in client.get(reverse("explorer-index")).context["models"]}
    assert "runbook" in shown and "section" not in shown


def test_related_tabs_need_view_permission_on_the_related_model(client, staff, runbook, perms_on):
    client.force_login(grant(staff, "view_runbook"))
    detail = client.get(url("detail", pk=runbook.pk))
    assert not any(t["accessor"] == "sections" for t in detail.context.get("related_tabs", []))
    assert client.get(url("related-tab", pk=runbook.pk, accessor="sections")).status_code == 404


# --- model permissions: REST, MCP, sc ----------------------------------------


@pytest.fixture
def receiver_perms(monkeypatch):
    monkeypatch.setattr(WebhookReceiverCRUDView, "model_permissions", True)


@pytest.fixture
def receiver():
    return WebhookReceiver.objects.create(name="Inbound", slug="inbound")


def _api(client, user, method, path, body=None):
    _token, raw = APIToken.create_token(user=user, name="perm-test")
    kwargs = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    if body is not None:
        kwargs.update(data=json.dumps(body), content_type="application/json")
    return getattr(client, method)(path, **kwargs)


def test_rest_maps_methods_to_permissions(client, staff, receiver, receiver_perms):
    detail = reverse("webhooks-receivers-api-detail", kwargs={"pk": receiver.pk})
    assert _api(client, staff, "get", reverse("webhooks-receivers-api-list")).status_code == 403
    staff = grant(staff, "view_webhookreceiver")
    assert _api(client, staff, "get", detail).status_code == 200
    assert _api(client, staff, "patch", detail, {"name": "x"}).status_code == 403
    assert _api(client, staff, "delete", detail).status_code == 403
    staff = grant(staff, "change_webhookreceiver")
    assert _api(client, staff, "patch", detail, {"name": "Renamed"}).status_code == 200


def _mcp(tool, args, user):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    ctx = set_context(ToolContext(user=user, token=None))
    try:
        return TOOL_HANDLERS[tool](args)
    finally:
        reset_context(ctx)


def test_mcp_tools_refuse_without_the_permission(staff, receiver, receiver_perms):
    assert _mcp("list_webhook_receivers", {}, staff)["error"]["code"] == "not_permitted"
    staff = grant(staff, "view_webhookreceiver")
    assert "results" in _mcp("list_webhook_receivers", {}, staff)
    refused = _mcp("delete_webhook_receiver", {"id": receiver.pk}, staff)
    assert refused["error"]["code"] == "not_permitted"
    assert WebhookReceiver.objects.filter(pk=receiver.pk).exists()


def test_sc_checks_the_users_permission(staff, receiver, receiver_perms):
    with pytest.raises(CommandError, match="lacks the delete permission"):
        call_command("sc", "rm", "webhooks.webhookreceiver", str(receiver.pk), "--force",
                     "--user", staff.username, stdout=StringIO())
    with pytest.raises(CommandError, match="lacks the view permission"):
        call_command("sc", "ls", "webhooks.webhookreceiver", "--user", staff.username, stdout=StringIO())


# --- audit of web writes + the history page -----------------------------------


def _entries(obj):
    return list(LogEntry.objects.filter(object_id=str(obj.pk), object_repr=str(obj)).order_by("pk"))


def test_create_edit_and_delete_pages_write_log_entries(client, staff, runbook):
    client.force_login(staff)
    resp = client.post(url("update", pk=runbook.pk), {"name": "Ops book 2", "slug": "ops-book"})
    assert resp.status_code == 302, resp.content
    entry = LogEntry.objects.get(object_id=str(runbook.pk), action_flag=CHANGE, content_type__model="runbook")
    assert entry.user == staff and "Name" in entry.get_change_message()

    resp = client.post(url("create"), {"name": "Fresh", "slug": "fresh"})
    assert resp.status_code == 302, resp.content
    fresh = Runbook.objects.get(slug="fresh")
    assert LogEntry.objects.filter(
        object_id=str(fresh.pk), action_flag=ADDITION, user=staff, content_type__model="runbook"
    ).exists()

    pk = fresh.pk
    assert client.post(url("delete", pk=pk)).status_code == 302
    assert LogEntry.objects.filter(object_id=str(pk), action_flag=DELETION, object_repr="Fresh").exists()


def test_a_refused_delete_leaves_no_entry(client, staff, runbook, monkeypatch):
    from apps.smallstack import crud as crud_module

    def boom(self, form):  # the delete fails inside the transaction
        raise crud_module.IntegrityError("nope")

    monkeypatch.setattr(crud_module.DeleteView, "form_valid", boom)
    client.force_login(staff)
    client.post(url("delete", pk=runbook.pk))
    assert not LogEntry.objects.filter(object_id=str(runbook.pk), action_flag=DELETION).exists()


def test_the_history_page_lists_every_surface(client, staff, runbook):
    from apps.smallstack.audit import log_write

    log_write(staff, runbook, CHANGE, "REST API")
    client.force_login(staff)
    client.post(url("update", pk=runbook.pk), {"name": "Renamed", "slug": "ops-book"})
    detail = client.get(url("detail", pk=runbook.pk)).content.decode()
    assert url("history", pk=runbook.pk) in detail
    page = client.get(url("history", pk=runbook.pk)).content.decode()
    assert "via REST API" in page and "Changed Name." in page and "perm-staff" in page


def test_history_is_opt_in_on_a_plain_crudview(client, staff, receiver):
    client.force_login(staff)
    assert "history_url" not in client.get(reverse("webhooks/receivers-detail", kwargs={"pk": receiver.pk})).context


# --- what a delete takes with it ----------------------------------------------


def test_the_confirmation_lists_the_cascade(client, staff, runbook):
    client.force_login(staff)
    page = client.get(url("delete", pk=runbook.pk)).content.decode()
    assert "also deletes 2 related records" in page
    assert "2 sections: Backups, Deploys" in page


def test_the_modal_fetches_the_same_summary(client, staff, runbook):
    client.force_login(staff)
    resp = client.get(url("delete", pk=runbook.pk), HTTP_X_SMALLSTACK_DELETE_SUMMARY="1")
    body = resp.content.decode()
    assert "<html" not in body and "2 sections" in body
    assert "X-SmallStack-Delete-Blocked" not in resp


def test_a_member_sees_counts_not_names():
    rb = Runbook.objects.create(name="Counts", slug="counts")
    Section.objects.create(runbook=rb, name="Secret section", slug="s")
    summary = summarize_deletion(rb, names=False)
    assert summary.cascade_count == 1 and summary.cascades[0].samples == []


def test_a_protected_row_blocks_the_delete(client, staff, runbook, monkeypatch):
    from apps.smallstack.deletion import DeletionSummary, ModelGroup

    blocked = DeletionSummary(protected=[ModelGroup("invoice", 1, ["INV-1"])])
    monkeypatch.setattr("apps.smallstack.deletion.summarize_deletion", lambda *a, **k: blocked)
    client.force_login(staff)
    page = client.get(url("delete", pk=runbook.pk)).content.decode()
    assert "can't be deleted" in page and "1 invoice: INV-1" in page
    assert 'class="btn-danger">Delete</button>' not in page
    modal = client.get(url("delete", pk=runbook.pk), HTTP_X_SMALLSTACK_DELETE_SUMMARY="1")
    assert modal["X-SmallStack-Delete-Blocked"] == "1"


def test_with_permissions_on_a_cascade_into_an_unpermitted_model_is_refused(client, staff, runbook, perms_on):
    staff = grant(staff, "view_runbook", "delete_runbook")
    client.force_login(staff)
    page = client.get(url("delete", pk=runbook.pk)).content.decode()
    assert "would also delete sections" in page
    resp = client.post(url("delete", pk=runbook.pk), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert resp.status_code == 403 and Runbook.objects.filter(pk=runbook.pk).exists()

    staff = grant(staff, "delete_section")
    client.force_login(staff)
    assert client.post(url("delete", pk=runbook.pk)).status_code == 302
    assert not Section.objects.filter(runbook_id=runbook.pk).exists()


def test_rest_and_mcp_deletes_check_the_cascade_too(client, staff, receiver_perms):
    receiver = WebhookReceiver.objects.create(name="Has receipts", slug="has-receipts")
    WebhookReceipt.objects.create(receiver=receiver)
    staff = grant(staff, "view_webhookreceiver", "delete_webhookreceiver")
    resp = _api(client, staff, "delete", reverse("webhooks-receivers-api-detail", kwargs={"pk": receiver.pk}))
    assert resp.status_code == 403
    refused = _mcp("delete_webhook_receiver", {"id": receiver.pk}, staff)
    assert refused["error"]["code"] == "not_permitted" and "webhook receipts" in refused["error"]["message"].lower()
    assert WebhookReceiver.objects.filter(pk=receiver.pk).exists()
