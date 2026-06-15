"""CRUDView factory: introspect, emit, gate."""

import pytest

from apps.mcp.factory import register_mcp_tools_from_crudview
from apps.mcp.server import TOOL_REGISTRY
from apps.smallstack.crud import Action

from .conftest import GadgetCRUDView, WidgetCRUDView


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _wipe(clean_registry):
    yield


def test_enable_mcp_false_emits_nothing():
    class _Disabled(WidgetCRUDView):
        enable_mcp = False

    register_mcp_tools_from_crudview(_Disabled)
    assert not any(n.startswith("list_") for n in TOOL_REGISTRY)


def test_full_actions_emit_all_five_tools(widget_view):
    register_mcp_tools_from_crudview(widget_view)
    expected = {"list_widgets", "get_widget", "create_widget", "update_widget", "delete_widget"}
    assert expected.issubset(TOOL_REGISTRY.keys())


def test_partial_actions_only_list_and_detail(gadget_view):
    register_mcp_tools_from_crudview(gadget_view)
    assert "list_gadgets" in TOOL_REGISTRY
    assert "get_gadget" in TOOL_REGISTRY
    assert "create_gadget" not in TOOL_REGISTRY


def test_mcp_actions_can_narrow_below_actions(widget_view):
    class _ReadOnlyWidget(WidgetCRUDView):
        mcp_actions = [Action.LIST]

    register_mcp_tools_from_crudview(_ReadOnlyWidget)
    assert "list_widgets" in TOOL_REGISTRY
    assert "create_widget" not in TOOL_REGISTRY
    assert "delete_widget" not in TOOL_REGISTRY


def test_mcp_description_used_in_tool(widget_view):
    """The model-level mcp_description is the BASE; each action's
    description is the verb prefix + the base. The LLM sees distinct
    descriptions for each tool instead of five copies of the same line."""
    register_mcp_tools_from_crudview(widget_view)
    assert TOOL_REGISTRY["list_widgets"].description == "List " + widget_view.mcp_description
    assert TOOL_REGISTRY["get_widget"].description == "Get a single " + widget_view.mcp_description
    assert TOOL_REGISTRY["create_widget"].description == "Create a new " + widget_view.mcp_description
    assert TOOL_REGISTRY["update_widget"].description == "Update an existing " + widget_view.mcp_description
    assert TOOL_REGISTRY["delete_widget"].description == "Delete a " + widget_view.mcp_description


def test_mcp_descriptions_override_per_action(widget_view):
    """mcp_descriptions = {Action.X: "..."} overrides ONLY that action.
    Other actions still use the auto-prefixed default."""

    class _CustomDesc(widget_view):
        url_base = "custom_desc_widgets"
        mcp_descriptions = {
            Action.CREATE: "File a brand-new widget. Use sparingly.",
        }

    register_mcp_tools_from_crudview(_CustomDesc)
    # create_<singular> still uses the model's verbose_name (singular), not
    # url_base. P23 adds mcp_singular for the override knob.
    assert (
        TOOL_REGISTRY["create_widget"].description
        == "File a brand-new widget. Use sparingly."
    )
    # Other tools still get the auto-prefix.
    assert (
        TOOL_REGISTRY["list_custom_desc_widgets"].description
        == "List " + widget_view.mcp_description
    )


def test_descriptions_fall_back_to_verbose_name(widget_view):
    """When mcp_description is unset, descriptions use model._meta.verbose_name."""

    class _NoDesc(widget_view):
        url_base = "no_desc_widgets"
        mcp_description = None

    register_mcp_tools_from_crudview(_NoDesc)
    verbose = str(_NoDesc.model._meta.verbose_name)
    assert TOOL_REGISTRY["list_no_desc_widgets"].description == "List " + verbose


def test_write_actions_marked_write(widget_view):
    register_mcp_tools_from_crudview(widget_view)
    assert TOOL_REGISTRY["create_widget"].write is True
    assert TOOL_REGISTRY["update_widget"].write is True
    assert TOOL_REGISTRY["delete_widget"].write is True
    assert TOOL_REGISTRY["list_widgets"].write is False


def test_idempotent_registration(widget_view):
    register_mcp_tools_from_crudview(widget_view)
    before = dict(TOOL_REGISTRY)
    register_mcp_tools_from_crudview(widget_view)
    assert TOOL_REGISTRY == before


def test_list_schema_includes_filters_and_search(widget_view):
    register_mcp_tools_from_crudview(widget_view)
    schema = TOOL_REGISTRY["list_widgets"].input_schema
    props = schema["properties"]
    assert "q" in props
    assert "owner" in props
    assert "limit" in props


def test_fk_expansion_via_api_expand_fields(widget_view, user_a, readonly_token):
    """A CRUDView with api_expand_fields=['owner'] makes the factory
    serialize FKs as nested {id, name} dicts instead of bare PKs — the
    LLM-friendly form. Mirrors the REST API's ?expand= behavior."""
    import inspect

    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    from .models import Widget

    class _ExpandWidget(widget_view):
        url_base = "expand_widgets"
        api_expand_fields = ["owner"]

    register_mcp_tools_from_crudview(_ExpandWidget)
    Widget.objects.create(name="W1", owner=user_a)
    token, _ = readonly_token

    ctx = set_context(ToolContext(user=user_a, token=token))
    try:
        handler = TOOL_HANDLERS["list_expand_widgets"]
        result = handler({}) if not inspect.iscoroutinefunction(handler) else None  # sync handler
    finally:
        reset_context(ctx)

    assert result["count"] == 1
    owner = result["results"][0]["owner"]
    # Without expand: would be a bare int. With expand: {id, name}.
    assert isinstance(owner, dict)
    assert owner["id"] == user_a.pk
    assert owner["name"] == str(user_a)


def test_no_expand_keeps_fk_as_bare_pk(widget_view, user_a, readonly_token):
    """Sanity check: a CRUDView WITHOUT api_expand_fields still emits
    FKs as bare PKs (the existing default behaviour). Backwards-compat."""
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    from .models import Widget

    class _PlainWidget(widget_view):
        url_base = "plain_widgets"
        api_expand_fields = []

    register_mcp_tools_from_crudview(_PlainWidget)
    Widget.objects.create(name="W2", owner=user_a)
    token, _ = readonly_token

    ctx = set_context(ToolContext(user=user_a, token=token))
    try:
        result = TOOL_HANDLERS["list_plain_widgets"]({})
    finally:
        reset_context(ctx)

    assert result["results"][0]["owner"] == user_a.pk  # bare int, not dict
