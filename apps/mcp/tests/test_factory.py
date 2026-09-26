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
    assert TOOL_REGISTRY["get_widget"].description.startswith(f"Get a single widget — {desc}")
    assert TOOL_REGISTRY["create_widget"].description == f"Create a new widget — {desc}"
    assert TOOL_REGISTRY["update_widget"].description.startswith(f"Update an existing widget — {desc}")
    assert TOOL_REGISTRY["delete_widget"].description.startswith(f"Delete a widget — {desc}")


def test_default_descriptions_are_grammatical_without_user_input(widget_view):
    """Without mcp_description set, descriptions are just <verb><noun>.
    The point of the singular/plural split is that 'Get a single widget'
    and 'List widgets' both parse as English."""

    class _Bare(widget_view):
        url_base = "bare_widgets"
        mcp_description = None

    register_mcp_tools_from_crudview(_Bare)
    assert TOOL_REGISTRY["list_bare_widgets"].description == "List widgets"
    assert TOOL_REGISTRY["get_widget"].description.startswith("Get a single widget")
    assert TOOL_REGISTRY["create_widget"].description == "Create a new widget"
    assert TOOL_REGISTRY["delete_widget"].description.startswith("Delete a widget")


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
    assert TOOL_REGISTRY["get_ticket"].description.startswith("Get a single ticket")


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
    assert TOOL_REGISTRY["get_widget"].description.startswith("Get a single " + verbose)


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


# --- update / delete tool handlers (factory.py 325-394) ---------------------


def _ctx_call(tool_name, args, user, token):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    ctx = set_context(ToolContext(user=user, token=token))
    try:
        return TOOL_HANDLERS[tool_name](args)
    finally:
        reset_context(ctx)


def test_update_widget_handler_updates(widget_view, user_a, readonly_token, monkeypatch):
    from .models import Widget

    # Audit logging is tested separately; a LogEntry for the test-only Widget's
    # ContentType trips SQLite's teardown FK check, so no-op it here.
    monkeypatch.setattr("apps.mcp.factory.log_write", lambda *a, **k: None)
    register_mcp_tools_from_crudview(widget_view)
    w = Widget.objects.create(name="old", owner=user_a)
    token, _ = readonly_token
    result = _ctx_call("update_widget", {"pk": w.pk, "name": "new"}, user_a, token)
    assert "error" not in result and "errors" not in result
    w.refresh_from_db()
    assert w.name == "new"


def test_update_widget_handler_missing_pk(widget_view, user_a, readonly_token):
    register_mcp_tools_from_crudview(widget_view)
    token, _ = readonly_token
    # F-25: `id` is the wire name, `pk` a permanent alias; the message names both.
    assert _ctx_call("update_widget", {"name": "x"}, user_a, token) == {
        "error": {"code": "invalid_argument", "message": "id is required (alias: pk)"}
    }


def test_update_widget_handler_not_found(widget_view, user_a, readonly_token):
    register_mcp_tools_from_crudview(widget_view)
    token, _ = readonly_token
    result = _ctx_call("update_widget", {"pk": 999999, "name": "x"}, user_a, token)
    # F-53: refusals carry a machine-readable code, not bare prose.
    assert result["error"]["code"] == "not_found"
    assert "not found" in result["error"]["message"]


def test_delete_widget_handler_deletes(widget_view, user_a, readonly_token, monkeypatch):
    from .models import Widget

    monkeypatch.setattr("apps.mcp.factory.log_write", lambda *a, **k: None)
    register_mcp_tools_from_crudview(widget_view)
    w = Widget.objects.create(name="doomed", owner=user_a)
    token, _ = readonly_token
    result = _ctx_call("delete_widget", {"pk": w.pk}, user_a, token)
    # Both spellings on the way out, so a caller that sent `pk` still finds it.
    assert result == {"deleted": True, "id": w.pk, "pk": w.pk}
    assert not Widget.objects.filter(pk=w.pk).exists()


def test_delete_widget_handler_missing_pk(widget_view, user_a, readonly_token):
    register_mcp_tools_from_crudview(widget_view)
    token, _ = readonly_token
    assert _ctx_call("delete_widget", {}, user_a, token) == {
        "error": {"code": "invalid_argument", "message": "id is required (alias: pk)"}
    }


def test_delete_widget_handler_not_found(widget_view, user_a, readonly_token):
    register_mcp_tools_from_crudview(widget_view)
    token, _ = readonly_token
    result = _ctx_call("delete_widget", {"pk": 999999}, user_a, token)
    # F-53: refusals carry a machine-readable code, not bare prose.
    assert result["error"]["code"] == "not_found"
    assert "not found" in result["error"]["message"]


# --- F-25: `id` is the wire name for every single-object tool ---------------
#
# `serialize()` emits the row identity as "id" and three hand-written tools
# accept `id`, but the generated get_/update_/delete_ tools required `pk`. An
# agent that passed the id it had just been handed got
# `{"error": "pk is required"}` on its first call — and approvals'
# `request_approval` description explicitly told it to do exactly that.


def test_single_object_tools_accept_id_as_well_as_pk(widget_view, user_a, readonly_token):
    from .models import Widget

    register_mcp_tools_from_crudview(widget_view)
    w = Widget.objects.create(name="by-id", owner=user_a)
    token, _ = readonly_token

    by_id = _ctx_call("get_widget", {"id": w.pk}, user_a, token)
    by_pk = _ctx_call("get_widget", {"pk": w.pk}, user_a, token)
    assert "error" not in by_id, by_id
    assert by_id == by_pk
    # The identity the tool hands back is the key the next call accepts.
    assert by_id["id"] == w.pk


def test_the_id_a_tool_returns_is_accepted_by_the_next_tool(widget_view, user_a, readonly_token):
    """The documented loop, end to end, using only keys the wire actually uses."""
    from .models import Widget

    register_mcp_tools_from_crudview(widget_view)
    token, _ = readonly_token
    listed = _ctx_call("list_widgets", {}, user_a, token)
    Widget.objects.create(name="loopable", owner=user_a)
    listed = _ctx_call("list_widgets", {}, user_a, token)
    assert listed["results"], listed
    row_id = listed["results"][0]["id"]
    fetched = _ctx_call("get_widget", {"id": row_id}, user_a, token)
    assert "error" not in fetched, fetched


def test_single_object_schemas_declare_both_keys_and_require_one(widget_view):
    register_mcp_tools_from_crudview(widget_view)
    for name in ("get_widget", "update_widget", "delete_widget"):
        schema = TOOL_REGISTRY[name].input_schema
        props = schema["properties"]
        assert "id" in props, f"{name} does not accept 'id'"
        assert "pk" in props, f"{name} dropped the 'pk' alias"
        assert schema["additionalProperties"] is False, name
        assert schema.get("anyOf") == [{"required": ["id"]}, {"required": ["pk"]}], name
        # `required` must not demand pk alone, or an id-only call is invalid.
        assert "pk" not in schema.get("required", []), name


def test_single_object_tool_descriptions_name_the_parameter(widget_view):
    register_mcp_tools_from_crudview(widget_view)
    for name in ("get_widget", "update_widget", "delete_widget"):
        assert "'id'" in TOOL_REGISTRY[name].description, name
    # …and the clause is not bolted onto tools that take no identifier.
    for name in ("list_widgets", "create_widget"):
        assert "Identify the row by" not in TOOL_REGISTRY[name].description, name


# --- F-53: generated tools name the KIND of failure, not just the prose ------


def test_refusals_carry_a_machine_readable_code(widget_view, user_a, readonly_token):
    """Every generated refusal is {"error": {"code", "message"}}.

    `isError` already separates failure from success (F-20), but a model still
    could not tell not-found from not-permitted from bad-argument on a generated
    tool without parsing English — while the hand-written approvals tools had
    carried a `code` since F-20. The three cases were distinguished in code all
    along; they just were not named.
    """
    register_mcp_tools_from_crudview(widget_view)
    token, _ = readonly_token

    cases = [
        ("get_widget", {}, "invalid_argument"),
        ("get_widget", {"id": 999999}, "not_found"),
        ("update_widget", {}, "invalid_argument"),
        ("update_widget", {"id": 999999, "name": "x"}, "not_found"),
        ("delete_widget", {}, "invalid_argument"),
        ("delete_widget", {"id": 999999}, "not_found"),
    ]
    for name, args, expected in cases:
        result = _ctx_call(name, args, user_a, token)
        err = result["error"]
        assert isinstance(err, dict), f"{name}{args} still returns bare prose: {err!r}"
        assert err["code"] == expected, f"{name}{args} → {err['code']!r}, want {expected!r}"
        assert err["message"], f"{name}{args} has a code but no human message"


def test_validation_failure_is_an_error_not_a_success_payload(
    widget_view, user_a, readonly_token
):
    """A rejected create used to return {"errors": …} with no top-level "error"
    key — so the dispatcher reported isError:false and a model reading the
    protocol flag saw "created". Same class as F-20, one shape over."""
    register_mcp_tools_from_crudview(widget_view)
    token, _ = readonly_token

    result = _ctx_call("create_widget", {"name": ""}, user_a, token)
    assert "error" in result, f"validation failure has no top-level 'error': {result!r}"
    assert result["error"]["code"] == "validation_error"
    # The per-field detail a client needs to fix the call is preserved.
    assert result["error"]["fields"], "field-level errors were dropped"
