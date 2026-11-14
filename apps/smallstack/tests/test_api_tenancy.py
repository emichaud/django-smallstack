"""REST detail/bulk endpoints honour get_list_queryset, same as list and MCP.

Audit 2026-09-13, C5: the REST list was scoped but detail/update/delete and
the bulk endpoints were not, so a fork scoping rows per owner leaked another
tenant's row at /api/<base>/<pk>/.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.mcp.tests.models import Widget
from apps.smallstack.api import (
    _make_api_bulk_delete_view,
    _make_api_bulk_update_view,
    _make_api_detail_view,
)
from apps.smallstack.crud import Action, BulkAction, CRUDView

pytestmark = pytest.mark.django_db
User = get_user_model()


class _OwnedWidgetView(CRUDView):
    model = Widget
    url_base = "test/owned-widgets"
    fields = ["name"]
    actions = [Action.LIST, Action.DETAIL, Action.UPDATE, Action.DELETE]
    bulk_actions = [BulkAction.UPDATE, BulkAction.DELETE]
    enable_api = True

    @classmethod
    def get_list_queryset(cls, qs, request):
        return qs.filter(owner=request.user)


@pytest.fixture
def alice():
    return User.objects.create_user(username="alice-t", password="x", is_staff=True)


@pytest.fixture
def bobs_widget():
    bob = User.objects.create_user(username="bob-t", password="x", is_staff=True)
    return Widget.objects.create(name="bob's", owner=bob)


def _req(method, user, payload=None):
    rf = RequestFactory()
    if payload is None:
        req = getattr(rf, method)("/x/")
    else:
        req = getattr(rf, method)("/x/", data=json.dumps(payload), content_type="application/json")
    req.user = user
    return req


def test_detail_get_patch_delete_are_scoped(alice, bobs_widget):
    view = _make_api_detail_view(_OwnedWidgetView)
    assert view(_req("get", alice), pk=bobs_widget.pk).status_code == 404
    assert view(_req("patch", alice, {"name": "pwned"}), pk=bobs_widget.pk).status_code == 404
    assert view(_req("delete", alice), pk=bobs_widget.pk).status_code == 404
    bobs_widget.refresh_from_db()
    assert bobs_widget.name == "bob's"


def test_bulk_endpoints_are_scoped(alice, bobs_widget):
    _make_api_bulk_update_view(_OwnedWidgetView)(
        _req("post", alice, {"ids": [bobs_widget.pk], "fields": {"name": "pwned"}})
    )
    _make_api_bulk_delete_view(_OwnedWidgetView)(_req("post", alice, {"ids": [bobs_widget.pk]}))
    bobs_widget.refresh_from_db()
    assert bobs_widget.name == "bob's"


def test_owner_still_reaches_their_own_row(alice):
    mine = Widget.objects.create(name="mine", owner=alice)
    view = _make_api_detail_view(_OwnedWidgetView)
    assert view(_req("get", alice), pk=mine.pk).status_code == 200
