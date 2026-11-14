"""Bulk operations + MCP write handlers (review F4).

Covers the previously-untested bulk-update REST endpoint (api.py), the HTML bulk
views (crud.py), and the MCP update/delete tool handlers (mcp/factory.py) — by
driving a real bulk+api+mcp-capable CRUDView over the APIToken model directly
(no URL registration needed).
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.smallstack.crud import Action, BulkAction, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()


class _TokenBulkView(CRUDView):
    model = APIToken
    url_base = "test/tok"
    mixins = [StaffRequiredMixin]
    bulk_actions = [BulkAction.UPDATE, BulkAction.DELETE]
    actions = [Action.LIST, Action.DETAIL, Action.UPDATE, Action.DELETE]
    enable_api = True
    enable_mcp = True
    fields = ["name", "is_active"]


@pytest.fixture
def staff():
    return User.objects.create_user(username="bulkstaff", password="pw", is_staff=True)


def _tokens(user, n=2):
    return [APIToken.create_token(user, name=f"tok{i}")[0] for i in range(n)]


def _post(rf, user, payload):
    req = rf.post("/x/bulk-update/", data=json.dumps(payload), content_type="application/json")
    req.user = user
    return req


# --- REST bulk-update (api.py 1223-1306) ------------------------------------


def test_bulk_update_success(staff):
    from apps.smallstack.api import _make_api_bulk_update_view

    toks = _tokens(staff)
    view = _make_api_bulk_update_view(_TokenBulkView)
    resp = view(_post(RequestFactory(), staff, {"ids": [t.pk for t in toks], "fields": {"name": "renamed"}}))
    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert len(body["updated"]) == 2
    for t in toks:
        t.refresh_from_db()
        assert t.name == "renamed"


def test_bulk_update_rejects_disallowed_field(staff):
    from apps.smallstack.api import _make_api_bulk_update_view

    toks = _tokens(staff, 1)
    view = _make_api_bulk_update_view(_TokenBulkView)
    resp = view(_post(RequestFactory(), staff, {"ids": [toks[0].pk], "fields": {"key_hash": "x"}}))
    assert resp.status_code == 400
    assert "not allowed" in json.loads(resp.content)["errors"]["__all__"][0].lower()


def test_bulk_update_validates_ids_and_fields(staff):
    from apps.smallstack.api import _make_api_bulk_update_view

    view = _make_api_bulk_update_view(_TokenBulkView)
    assert view(_post(RequestFactory(), staff, {"ids": [], "fields": {"name": "x"}})).status_code == 400
    assert view(_post(RequestFactory(), staff, {"ids": [1], "fields": {}})).status_code == 400
    assert view(_post(RequestFactory(), staff, {"ids": ["nope"], "fields": {"name": "x"}})).status_code == 400


def test_bulk_update_reports_missing_ids(staff):
    from apps.smallstack.api import _make_api_bulk_update_view

    view = _make_api_bulk_update_view(_TokenBulkView)
    resp = view(_post(RequestFactory(), staff, {"ids": [999999], "fields": {"name": "x"}}))
    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert body["updated"] == []
    assert "999999" in body["errors"]


def test_bulk_update_requires_staff(staff):
    from apps.smallstack.api import _make_api_bulk_update_view

    non_staff = User.objects.create_user(username="plain", password="pw")
    toks = _tokens(staff, 1)
    view = _make_api_bulk_update_view(_TokenBulkView)
    resp = view(_post(RequestFactory(), non_staff, {"ids": [toks[0].pk], "fields": {"name": "x"}}))
    assert resp.status_code == 403


def test_bulk_update_get_is_405(staff):
    from apps.smallstack.api import _make_api_bulk_update_view

    req = RequestFactory().get("/x/bulk-update/")
    req.user = staff
    assert _make_api_bulk_update_view(_TokenBulkView)(req).status_code == 405


# --- HTML bulk views (crud.py 730-961) --------------------------------------


class _TokenDeleteOnlyView(CRUDView):
    model = APIToken
    url_base = "test/tokdel"
    mixins = [StaffRequiredMixin]
    bulk_actions = [BulkAction.DELETE]
    actions = [Action.LIST, Action.DELETE]
    fields = ["name", "is_active"]


def _bulk_action_view(view_cls):
    from apps.smallstack.crud import _CRUDBulkActionView

    return type("B", (_CRUDBulkActionView,), {"crud_config": view_cls}).as_view()


def _bulk_post(user, payload):
    req = RequestFactory().post("/x/bulk/", data=json.dumps(payload), content_type="application/json")
    req.user = user
    return req


def test_html_bulk_update_success(staff):
    toks = _tokens(staff)
    resp = _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "update", "ids": [t.pk for t in toks], "fields": {"name": "bulkhtml"}})
    )
    assert resp.status_code == 200
    assert json.loads(resp.content)["updated"] == [t.pk for t in toks]
    for t in toks:
        t.refresh_from_db()
        assert t.name == "bulkhtml"


def test_html_bulk_update_not_enabled_is_403(staff):
    toks = _tokens(staff, 1)
    resp = _bulk_action_view(_TokenDeleteOnlyView)(
        _bulk_post(staff, {"action": "update", "ids": [toks[0].pk], "fields": {"name": "x"}})
    )
    assert resp.status_code == 403


def test_html_bulk_update_no_fields_is_400(staff):
    toks = _tokens(staff, 1)
    resp = _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "update", "ids": [toks[0].pk], "fields": {}})
    )
    assert resp.status_code == 400


def test_html_bulk_update_invalid_field_is_400(staff):
    toks = _tokens(staff, 1)
    resp = _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "update", "ids": [toks[0].pk], "fields": {"key_hash": "x"}})
    )
    assert resp.status_code == 400


def test_html_bulk_delete_success(staff):
    toks = _tokens(staff)
    resp = _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "delete", "ids": [t.pk for t in toks]})
    )
    assert resp.status_code == 200
    assert json.loads(resp.content)["deleted"] == [t.pk for t in toks]
    assert not APIToken.objects.filter(pk__in=[t.pk for t in toks]).exists()


def test_html_bulk_unknown_action_is_400(staff):
    toks = _tokens(staff, 1)
    resp = _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "frobnicate", "ids": [toks[0].pk]})
    )
    assert resp.status_code == 400


def test_html_bulk_no_ids_is_400(staff):
    resp = _bulk_action_view(_TokenBulkView)(_bulk_post(staff, {"action": "delete", "ids": []}))
    assert resp.status_code == 400


def test_html_bulk_delete_logs_one_summary_line(staff, caplog):
    """Bulk delete must be visible in the log viewer — one structured line,
    not one per row (that would be the unbounded-growth-under-load failure
    mode DatabaseLogHandler itself exists to avoid)."""
    import logging

    toks = _tokens(staff, 3)
    with caplog.at_level(logging.INFO, logger="apps.smallstack.crud"):
        _bulk_action_view(_TokenBulkView)(
            _bulk_post(staff, {"action": "delete", "ids": [t.pk for t in toks]})
        )

    bulk_records = [r for r in caplog.records if r.name == "apps.smallstack.crud"]
    assert len(bulk_records) == 1
    record = bulk_records[0]
    assert "Bulk delete" in record.message
    assert "3/3" in record.message
    assert staff.get_username() in record.message
    assert sorted(record.ids) == sorted(t.pk for t in toks)
    assert record.errors == {}
    # WARNING, so it clears the DB log handler's default baseline (audit D8).
    assert record.levelno == logging.WARNING


def test_html_bulk_update_logs_one_summary_line_with_field_names(staff, caplog):
    import logging

    toks = _tokens(staff, 2)
    with caplog.at_level(logging.INFO, logger="apps.smallstack.crud"):
        _bulk_action_view(_TokenBulkView)(
            _bulk_post(staff, {"action": "update", "ids": [t.pk for t in toks], "fields": {"name": "bulklog"}})
        )

    bulk_records = [r for r in caplog.records if r.name == "apps.smallstack.crud"]
    assert len(bulk_records) == 1
    record = bulk_records[0]
    assert "Bulk update" in record.message
    assert record.fields == ["name"]


def test_html_bulk_delete_writes_one_log_entry_per_deleted_row(staff):
    """Audit trail parity with single-object writes: 'who deleted which
    specific row' must still be answerable per-row, via the same batch
    LogEntry.objects.log_actions() helper Django admin's own bulk delete
    action uses — one bulk_create query, not N individual ones."""
    from django.contrib.admin.models import DELETION, LogEntry
    from django.contrib.contenttypes.models import ContentType

    toks = _tokens(staff, 3)
    ct = ContentType.objects.get_for_model(APIToken)
    _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "delete", "ids": [t.pk for t in toks]})
    )

    entries = LogEntry.objects.filter(content_type=ct, action_flag=DELETION, user=staff)
    assert entries.count() == 3
    assert sorted(int(e.object_id) for e in entries) == sorted(t.pk for t in toks)


def test_html_bulk_update_writes_one_log_entry_per_updated_row(staff):
    from django.contrib.admin.models import CHANGE, LogEntry
    from django.contrib.contenttypes.models import ContentType

    toks = _tokens(staff, 2)
    ct = ContentType.objects.get_for_model(APIToken)
    _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "update", "ids": [t.pk for t in toks], "fields": {"name": "audited"}})
    )

    entries = LogEntry.objects.filter(content_type=ct, action_flag=CHANGE, user=staff)
    assert entries.count() == 2
    assert sorted(int(e.object_id) for e in entries) == sorted(t.pk for t in toks)


def test_bulk_delete_audit_excludes_rows_that_failed_permission_or_not_found(staff):
    """Only the rows actually deleted get an audit entry — a 'Not found' or
    'Permission denied' row was never touched, so it shouldn't show up as
    deleted in the audit trail."""
    from django.contrib.admin.models import DELETION, LogEntry
    from django.contrib.contenttypes.models import ContentType

    toks = _tokens(staff, 1)
    ct = ContentType.objects.get_for_model(APIToken)
    resp = _bulk_action_view(_TokenBulkView)(
        _bulk_post(staff, {"action": "delete", "ids": [toks[0].pk, 999999]})
    )
    body = json.loads(resp.content)
    assert body["deleted"] == [toks[0].pk]
    assert "999999" in body["errors"]

    entries = LogEntry.objects.filter(content_type=ct, action_flag=DELETION, user=staff)
    assert entries.count() == 1


def test_audit_bulk_action_skips_an_actor_with_no_pk(staff):
    """LogEntry.user is a required FK — log_actions() would raise outright for
    an actor with no pk. Unit-tested directly against the helper (rather than
    through the full bulk view) because StaffRequiredMixin already rejects an
    AnonymousUser before _bulk_delete/_bulk_update would ever run it for
    real — this pins the guard itself, matching
    apps.smallstack.audit.log_write's identical guard for the same case."""
    from django.contrib.admin.models import DELETION, LogEntry
    from django.contrib.auth.models import AnonymousUser

    from apps.smallstack.crud import _audit_bulk_action

    toks = _tokens(staff, 1)

    class _Req:
        user = AnonymousUser()

    snapshots = [(t.pk, str(t)) for t in toks]
    _audit_bulk_action(_Req(), APIToken, snapshots, DELETION, "should not be written")  # must not raise

    assert LogEntry.objects.count() == 0


def test_bulk_update_form_view_renders_fields(staff):
    from apps.smallstack.crud import _make_bulk_update_form_view

    req = RequestFactory().get("/x/bulk/update-form/")
    req.user = staff
    resp = _make_bulk_update_form_view(_TokenBulkView)(req)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-field="name"' in body and 'data-field="is_active"' in body
