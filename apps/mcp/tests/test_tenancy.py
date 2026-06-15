"""Multi-tenant access via CRUDView.get_list_queryset."""

import inspect

import pytest

from apps.mcp.factory import register_mcp_tools_from_crudview
from apps.mcp.server import (
    TOOL_HANDLERS,
    ToolContext,
    reset_context,
    set_context,
)

from .conftest import WidgetCRUDView
from .models import Widget

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _wipe(clean_registry):
    yield


def _call(name, args, user, token):
    ctx_tok = set_context(ToolContext(user=user, token=token))
    try:
        handler = TOOL_HANDLERS[name]
        if inspect.iscoroutinefunction(handler):
            import asyncio
            return asyncio.run(handler(args))
        return handler(args)
    finally:
        reset_context(ctx_tok)


def test_list_filtered_by_owner(user_a, user_b, readonly_token):
    register_mcp_tools_from_crudview(WidgetCRUDView)
    Widget.objects.create(name="A1", owner=user_a)
    Widget.objects.create(name="B1", owner=user_b)
    token, _raw = readonly_token  # belongs to user_a

    result = _call("list_widgets", {}, user_a, token)
    names = [r["name"] for r in result["results"]]
    assert names == ["A1"]


def test_get_rejects_other_owner_pk(user_a, user_b, readonly_token):
    register_mcp_tools_from_crudview(WidgetCRUDView)
    own = Widget.objects.create(name="mine", owner=user_a)
    other = Widget.objects.create(name="not mine", owner=user_b)
    token, _ = readonly_token

    ok = _call("get_widget", {"pk": own.pk}, user_a, token)
    assert ok["name"] == "mine"

    err = _call("get_widget", {"pk": other.pk}, user_a, token)
    assert "error" in err


def test_unauth_user_sees_nothing(user_a, user_b, readonly_token):
    register_mcp_tools_from_crudview(WidgetCRUDView)
    Widget.objects.create(name="A1", owner=user_a)
    Widget.objects.create(name="B1", owner=user_b)
    token, _ = readonly_token
    from django.contrib.auth.models import AnonymousUser

    result = _call("list_widgets", {}, AnonymousUser(), token)
    assert result["results"] == []
