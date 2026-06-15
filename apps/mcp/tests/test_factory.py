"""CRUDView factory: introspect, emit, gate."""

import pytest

from apps.mcp.factory import register_mcp_tools_from_crudview
from apps.mcp.server import TOOL_REGISTRY
from apps.smallstack.crud import Action

from .conftest import WidgetCRUDView

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
    """LIST uses plural noun; non-LIST uses singular. mcp_description is
    appended as a tail clause via " — " so users who phrased their
    description in plural don't get "Get a single Service tickets..."
    style broken grammar."""
    register_mcp_tools_from_crudview(widget_view)
    desc = widget_view.mcp_description
    # WidgetCRUDView model: verbose_name="widget", verbose_name_plural="widgets"
    assert TOOL_REGISTRY["list_widgets"].description == f"List widgets — {desc}"
    assert TOOL_REGISTRY["get_widget"].description == f"Get a single widget — {desc}"
    assert TOOL_REGISTRY["create_widget"].description == f"Create a new widget — {desc}"
    assert TOOL_REGISTRY["update_widget"].description == f"Update an existing widget — {desc}"
    assert TOOL_REGISTRY["delete_widget"].description == f"Delete a widget — {desc}"


def test_default_descriptions_are_grammatical_without_user_input(widget_view):
    """Without mcp_description set, descriptions are just <verb><noun>.
    The point of the singular/plural split is that 'Get a single widget'
    and 'List widgets' both parse as English."""

    class _Bare(widget_view):
        url_base = "bare_widgets"
        mcp_description = None

    register_mcp_tools_from_crudview(_Bare)
    assert TOOL_REGISTRY["list_bare_widgets"].description == "List widgets"
    assert TOOL_REGISTRY["get_widget"].description == "Get a single widget"
    assert TOOL_REGISTRY["create_widget"].description == "Create a new widget"
    assert TOOL_REGISTRY["delete_widget"].description == "Delete a widget"


def test_mcp_singular_plural_used_for_descriptions(widget_view):
    """When mcp_singular/mcp_plural are set, the auto-prefix uses them
    too — not just the tool name."""

    class _Renamed(widget_view):
        url_base = "renamed"
        mcp_singular = "ticket"
        mcp_plural = "tickets"
        mcp_description = None

    register_mcp_tools_from_crudview(_Renamed)
    assert TOOL_REGISTRY["list_tickets"].description == "List tickets"
    assert TOOL_REGISTRY["get_ticket"].description == "Get a single ticket"


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
    # Other tools still get the auto-prefix + tail clause.
    assert (
        TOOL_REGISTRY["list_custom_desc_widgets"].description
        == f"List widgets — {widget_view.mcp_description}"
    )


def test_descriptions_fall_back_to_verbose_name(widget_view):
    """When mcp_description is unset, LIST uses verbose_name_plural and
    non-LIST uses verbose_name. No trailing " — " clause."""

    class _NoDesc(widget_view):
        url_base = "no_desc_widgets"
        mcp_description = None

    register_mcp_tools_from_crudview(_NoDesc)
    verbose = str(_NoDesc.model._meta.verbose_name)
    verbose_pl = str(_NoDesc.model._meta.verbose_name_plural)
    assert TOOL_REGISTRY["list_no_desc_widgets"].description == "List " + verbose_pl
    assert TOOL_REGISTRY["get_widget"].description == "Get a single " + verbose


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


def test_mcp_singular_plural_overrides(widget_view):
    """Setting mcp_singular + mcp_plural gives consistent tool names
    regardless of model.verbose_name or url_base."""

    class _Renamed(widget_view):
        url_base = "anything_else"
        mcp_singular = "ticket"
        mcp_plural = "tickets"

    register_mcp_tools_from_crudview(_Renamed)
    assert "list_tickets" in TOOL_REGISTRY
    assert "get_ticket" in TOOL_REGISTRY
    assert "create_ticket" in TOOL_REGISTRY
    assert "update_ticket" in TOOL_REGISTRY
    assert "delete_ticket" in TOOL_REGISTRY


def test_default_naming_unchanged_when_no_overrides(widget_view):
    """Without mcp_singular/mcp_plural, factory matches pre-P23 behaviour:
    list_<url_base>, get_<verbose_name>. WidgetCRUDView has url_base
    'widgets' and model.verbose_name 'widget', so the names are
    list_widgets + get_widget."""
    register_mcp_tools_from_crudview(widget_view)
    assert "list_widgets" in TOOL_REGISTRY
    assert "get_widget" in TOOL_REGISTRY


def test_mcp_plural_alone_uses_verbose_name_for_singular(widget_view):
    """Setting only mcp_plural doesn't change the singular tools."""

    class _OnlyPlural(widget_view):
        url_base = "raw"
        mcp_plural = "items"
        mcp_singular = None  # keep default

    register_mcp_tools_from_crudview(_OnlyPlural)
    assert "list_items" in TOOL_REGISTRY
    assert "get_widget" in TOOL_REGISTRY  # falls back to verbose_name


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
