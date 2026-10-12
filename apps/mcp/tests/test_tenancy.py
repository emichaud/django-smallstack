"""Multi-tenant access via CRUDView.get_list_queryset."""

import inspect

import pytest
from django import forms

from apps.mcp.factory import register_mcp_tools_from_crudview
from apps.mcp.server import (
    TOOL_HANDLERS,
    ToolContext,
    reset_context,
    set_context,
)
from apps.smallstack.crud import Action, CRUDView

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


# ---------------------------------------------------------------------------
# A *generated* create tool must honour a user-scoped FK queryset.
#
# Found by the integration harness 2026-10-11: the generated create/update
# handlers built their form directly, with no `user=`, so a form that scopes its
# own ModelChoiceField never narrowed — and that queryset *is* the validation.
# A create has nothing for can_update/check_object_permission to inspect, so the
# form was the only gate. The hand-written tools in apps/blog refused correctly
# while `create_blog_post` wrote into another tenant's blog, which is what made
# the split visible.
# ---------------------------------------------------------------------------
class _ScopedWidgetForm(forms.ModelForm):
    """Accepts ``user=`` and narrows its choices, as apps/blog/forms.py does."""

    class Meta:
        model = Widget
        fields = ["name", "owner"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields["owner"].queryset = type(user).objects.filter(pk=user.pk)


class _ScopedWidgetCRUDView(CRUDView):
    model = Widget
    form_class = _ScopedWidgetForm
    fields = ["name", "owner"]
    list_fields = ["name", "owner"]
    detail_fields = ["name", "owner"]
    url_base = "scoped-widgets"
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE]
    enable_mcp = True
    mcp_singular = "scoped_widget"
    mcp_plural = "scoped_widgets"
    mcp_description = "Test widgets with a per-user scoped owner field."

    @classmethod
    def get_list_queryset(cls, qs, request):
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            return qs.filter(owner=request.user)
        return qs.none()


def test_generated_create_tool_cannot_point_a_scoped_fk_at_another_user(
    user_a, user_b, staff_token
):
    register_mcp_tools_from_crudview(_ScopedWidgetCRUDView)
    token, _ = staff_token

    result = _call(
        "create_scoped_widget",
        {"name": "injected", "owner": user_b.pk},
        user_a,
        token,
    )

    assert "error" in result, "generated create accepted an out-of-scope FK pk"
    assert not Widget.objects.filter(owner=user_b, name="injected").exists()


def test_generated_create_tool_still_accepts_an_in_scope_fk(user_a, staff_token):
    register_mcp_tools_from_crudview(_ScopedWidgetCRUDView)
    token, _ = staff_token

    result = _call(
        "create_scoped_widget", {"name": "mine", "owner": user_a.pk}, user_a, token
    )

    assert "error" not in result, result
    assert Widget.objects.filter(owner=user_a, name="mine").exists()
