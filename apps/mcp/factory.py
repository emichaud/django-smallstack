"""Auto-derive MCP tools from a CRUDView's existing configuration.

The factory walks `view_cls.actions` (filtered by `view_cls.mcp_actions` if
set) and emits one tool per action. Handlers are sync because they call the
Django ORM directly; the dispatcher in views.py supports both sync and
async handlers, so cross-cutting tools added via @tool can still be async.
Each tool reuses the same helpers
the REST API uses (serialize, apply_search, apply_filters, apply_ordering),
calls the CRUDView's tenancy hook (get_list_queryset), and respects the
existing form-based create/update path including `on_form_valid` side
effects. The goal is "what works on /api/<resource>/ also works on /mcp".
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, QueryDict

from apps.smallstack.api import (
    apply_filters,
    apply_ordering,
    apply_search,
    field_to_schema,
    serialize,
)
from apps.smallstack.audit import ADDITION, CHANGE, DELETION, log_write
from apps.smallstack.crud import Action
from apps.smallstack.form_bridge import merge_form_payload
from apps.smallstack.mixins import StaffRequiredMixin

from .server import TOOL_REGISTRY, ToolDef, current_context, tool

logger = logging.getLogger("smallstack.mcp.factory")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_request(user) -> HttpRequest:
    """Minimal HttpRequest stand-in so CRUDView hooks see request.user.

    CRUDView.get_list_queryset(qs, request) reads request.user and request.GET
    for tenancy filtering. We synthesize both — GET stays empty because MCP
    tools pass filter args explicitly via the args dict, not query params.
    """
    req = HttpRequest()
    req.method = "GET"
    req.user = user
    req.GET = QueryDict("", mutable=False)
    req.META = {}
    return req


def _has_staff_mixin(view_cls) -> bool:
    return any(
        issubclass(m, StaffRequiredMixin) or getattr(m, "__name__", "") == "StaffRequiredMixin"
        for m in view_cls._resolved_mixins()
    )


# Per-action verb prefix so the LLM sees distinct descriptions for each tool
# from the same CRUDView instead of five copies of the same `mcp_description`.
_ACTION_VERB = {
    Action.LIST:   "List ",
    Action.DETAIL: "Get a single ",
    Action.CREATE: "Create a new ",
    Action.UPDATE: "Update an existing ",
    Action.DELETE: "Delete a ",
}

#: Actions whose tool addresses exactly one row by identifier.
_SINGLE_OBJECT_ACTIONS = frozenset({Action.DETAIL, Action.UPDATE, Action.DELETE})


def _action_description(view_cls, action: Action) -> str:
    """Build the grammatically-correct per-action description for an MCP tool.

    LIST uses the plural noun; every other action uses singular. The user's
    `mcp_description` (when set) is appended as a tail clause via " — " so
    the LLM still sees the model-level hint without it bending the grammar
    of the auto-prefix.

    Resolution order:
    1. view_cls.mcp_descriptions[action] — explicit per-action override (wins)
    2. f"<verb><noun> — <mcp_description>" — auto-prefix + tail clause
    3. f"<verb><noun>"                     — auto-prefix only (no description set)

    For LIST, <noun> is mcp_plural or model._meta.verbose_name_plural.
    For DETAIL/CREATE/UPDATE/DELETE, <noun> is mcp_singular or verbose_name.
    """
    overrides = getattr(view_cls, "mcp_descriptions", None) or {}
    if action in overrides:
        return str(overrides[action])

    verb = _ACTION_VERB[action]
    if action == Action.LIST:
        noun = view_cls.mcp_plural or str(view_cls.model._meta.verbose_name_plural)
    else:
        noun = view_cls.mcp_singular or str(view_cls.model._meta.verbose_name)

    head = f"{verb}{noun}"
    if view_cls.mcp_description:
        out = f"{head} — {view_cls.mcp_description}"
    else:
        out = head
    # Name the identifier in prose, not only in inputSchema. A model reasoning
    # from the previous tool's output ("it returned id: 2254") plus a prose
    # instruction is the documented HITL loop, and that loop failed on its first
    # call while `pk` was the only accepted key and the only place it was
    # written down. (F-25.)
    if action in _SINGLE_OBJECT_ACTIONS:
        out = f"{out}. Identify the row by 'id' — the value list/get/create returns ('pk' is accepted as an alias)"
    return out


def _build_list_input_schema(view_cls) -> dict[str, Any]:
    """Map filter_fields + search_fields + ordering + limit into JSON Schema."""
    props: dict[str, Any] = {}

    if getattr(view_cls, "_resolve_search_fields", None):
        if view_cls._resolve_search_fields():
            props["q"] = {"type": "string", "description": "Text search across configured fields."}

    filter_fields = view_cls._resolve_filter_fields() if hasattr(view_cls, "_resolve_filter_fields") else []
    for fname in filter_fields:
        # Light schema — the helper accepts strings for booleans/dates already.
        props[fname] = {"type": "string", "description": f"Filter by {fname}."}

    props["ordering"] = {
        "type": "string",
        "description": "Comma-separated field names; prefix with '-' for descending.",
    }
    props["limit"] = {
        "type": "integer",
        "minimum": 1,
        "maximum": 200,
        "default": 50,
        "description": "Max rows to return (capped at 200).",
    }
    return {"type": "object", "properties": props, "additionalProperties": False}


# field_to_schema emits SmallStack-internal type names ("text", "fk", "datetime",
# "choice", …). MCP clients validate inputs against real JSON Schema, so each
# internal name maps to a valid JSON-Schema type here.
_JSON_SCHEMA_TYPES: dict[str, Any] = {
    "string": "string",
    "text": "string",
    "email": "string",
    "url": "string",
    "date": "string",
    "datetime": "string",
    "time": "string",
    "choice": "string",
    "file": "string",
    "integer": "integer",
    "fk": "integer",
    "float": "number",
    "decimal": "number",
    "boolean": "boolean",
    # JSONField accepts any JSON value — native arrays/objects or a JSON-encoded string.
    "json": ["array", "object", "string"],
}


def _to_json_schema_prop(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert one field_to_schema dict to a valid JSON-Schema property."""
    internal = schema.get("type", "string")
    prop: dict[str, Any] = {"type": _JSON_SCHEMA_TYPES.get(internal, "string")}
    if internal == "choice" and schema.get("choices"):
        prop["enum"] = [c[0] for c in schema["choices"]]
    if internal == "fk" and schema.get("related_model"):
        prop["description"] = f"Primary key of the related {schema['related_model']}."
    if schema.get("max_length") is not None:
        prop["maxLength"] = schema["max_length"]
    if schema.get("min_value") is not None:
        prop["minimum"] = schema["min_value"]
    if schema.get("max_value") is not None:
        prop["maximum"] = schema["max_value"]
    return prop


def _build_form_input_schema(view_cls, *, include_pk: bool = False) -> dict[str, Any]:
    """JSON Schema for create/update inputs, derived from form_class or fields."""
    form_class = view_cls.form_class or (
        view_cls._make_form_class() if hasattr(view_cls, "_make_form_class") else None
    )
    props: dict[str, Any] = {}
    required: list[str] = []

    if include_pk:
        # `id` is the wire name (serialize() emits it); `pk` is a permanent alias.
        props.update(_OBJECT_ID_SCHEMA)

    if form_class is not None:
        try:
            form_instance = form_class()
            for fname, ffield in form_instance.fields.items():
                schema = field_to_schema(fname, ffield, view_cls.model)
                props[fname] = _to_json_schema_prop(schema)
                if schema.get("required") and not include_pk:
                    required.append(fname)
        except Exception:
            logger.exception("Failed to introspect form_class for %s", view_cls)

    out: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }
    if include_pk:
        out["anyOf"] = [{"required": ["id"]}, {"required": ["pk"]}]
    return out


# ---------------------------------------------------------------------------
# Tool builders (one per Action)
# ---------------------------------------------------------------------------


def _build_list_tool(view_cls, *, base: str):
    name = f"list_{base}"

    def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)

        qs = view_cls._get_queryset()
        qs = view_cls.get_list_queryset(qs, request)

        # Search
        q = (args.get("q") or "").strip() if isinstance(args.get("q"), str) else ""
        if q and hasattr(view_cls, "_resolve_search_fields") and view_cls._resolve_search_fields():
            request.GET = QueryDict(f"q={q}", mutable=False)
            qs = apply_search(qs, request, view_cls)

        # Filter — push known filter fields through the GET path the helper expects.
        filter_fields = view_cls._resolve_filter_fields() if hasattr(view_cls, "_resolve_filter_fields") else []
        get_pairs = []
        for fname in filter_fields:
            if fname in args and args[fname] not in (None, ""):
                get_pairs.append(f"{fname}={args[fname]}")
        if get_pairs:
            request.GET = QueryDict("&".join(get_pairs), mutable=False)
            qs = apply_filters(qs, request, view_cls)

        # Ordering
        ordering = (args.get("ordering") or "").strip() if isinstance(args.get("ordering"), str) else ""
        if ordering:
            allowed = set(view_cls._get_list_fields()) | set(getattr(view_cls, "api_extra_fields", []))
            qs = apply_ordering(qs, ordering, allowed)

        # Limit
        limit = args.get("limit") or 50
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50

        fields = view_cls._get_list_fields()
        extra = getattr(view_cls, "api_extra_fields", [])
        expand = set(getattr(view_cls, "api_expand_fields", []) or [])
        rows = list(qs[:limit])
        return {
            "count": len(rows),
            "limit": limit,
            "results": [serialize(obj, fields, extra, expand) for obj in rows],
        }

    desc = _action_description(view_cls, Action.LIST)
    schema = _build_list_input_schema(view_cls)
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, requires_access=requires)(handler)


# --- the single-object identifier -------------------------------------------
#
# `serialize()` emits the row's identity as **"id"** (apps/smallstack/api.py's
# `_serialize`), and three hand-written tools (`logs_get`,
# `runbook_get_document`, `decide_approval`) accept `id`. The generated
# get_/update_/delete_ tools accepted only `pk`, so an agent that did the
# obvious thing — take the `id` the previous tool returned and pass it to the
# next — got `{"error": "pk is required"}` on its first call. In approvals that
# was actively mis-instructed: `request_approval`'s own description says "poll
# get_approval with that id". (F-25.)
#
# Fix: `id` is the wire name everywhere; `pk` stays a permanent alias so no
# existing client breaks.

# Refusals carry a machine-readable `code` so a model can branch on the KIND of
# failure instead of pattern-matching English. `isError` (set by the dispatcher
# from the presence of this "error" key) already separates failure from success;
# without a code, an agent still cannot tell not-found from not-permitted from
# bad-argument on a generated tool. F-20 gave the hand-written approvals tools
# this shape and the harness asserts it; F-53 is that shape reaching the ~12
# apps' worth of GENERATED tools, where the three cases were already
# distinguished in code but never named.
#
# Codes are a closed vocabulary — add to it deliberately, since agents branch on
# these strings: invalid_argument · not_found · not_permitted · validation_error
# · unsupported.
def _tool_error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, **extra}}


_OBJECT_ID_SCHEMA = {
    "id": {
        "type": "integer",
        "description": "Row id — the `id` returned by list/get/create.",
    },
    "pk": {
        "type": "integer",
        "description": "Alias for `id` (Django's primary-key name). Pass either.",
    },
}


def _object_id_schema() -> dict[str, Any]:
    """Input schema for a tool that addresses exactly one row.

    Both keys are declared and exactly one is required, expressed as ``anyOf``
    so ``additionalProperties: false`` still holds and a client that hedges by
    sending both is not a schema violation.
    """
    return {
        "type": "object",
        "properties": dict(_OBJECT_ID_SCHEMA),
        "anyOf": [{"required": ["id"]}, {"required": ["pk"]}],
        "additionalProperties": False,
    }


def _object_id(args: dict[str, Any]) -> Any:
    """Read the row identifier, accepting either spelling. ``id`` wins."""
    pk = args.get("id")
    if pk is None:
        pk = args.get("pk")
    return pk


def _fetch_one(view_cls, args: dict[str, Any], request) -> Any:
    """Resolve one row for a generated single-object tool.

    Returns the instance, or an error dict ready to return to the caller. Applies
    both halves of the single-object read contract: ``get_detail_queryset``
    (scoping — a row you cannot see is "not found") and
    ``check_object_permission`` (authorization — F-27), so a CRUDView that
    expresses ownership in the hook is protected over MCP too.
    """
    pk = _object_id(args)
    if pk is None:
        return _tool_error("invalid_argument", "id is required (alias: pk)")
    qs = view_cls.get_detail_queryset(view_cls._get_queryset(), request)
    try:
        obj = qs.get(pk=pk)
    except (view_cls.model.DoesNotExist, ValueError, TypeError, ValidationError):
        return _tool_error("not_found", f"{view_cls.model.__name__} id={pk} not found")
    try:
        view_cls.check_object_permission(obj, request)
    except (PermissionDenied, Http404):
        # Existence-hiding: an agent that may not touch the row is told the same
        # thing as an agent naming a row that isn't there.
        return _tool_error("not_found", f"{view_cls.model.__name__} id={pk} not found")
    return obj


def _build_get_tool(view_cls, *, singular: str):
    name = f"get_{singular}"

    def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        obj = _fetch_one(view_cls, args, request)
        if isinstance(obj, dict):
            return obj
        fields = view_cls._get_detail_fields() or view_cls.fields
        extra = getattr(view_cls, "api_extra_fields", [])
        expand = set(getattr(view_cls, "api_expand_fields", []) or [])
        return serialize(obj, fields, extra, expand)

    schema = _object_id_schema()
    desc = _action_description(view_cls, Action.DETAIL)
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, requires_access=requires)(handler)


def _build_create_tool(view_cls, *, singular: str):
    name = f"create_{singular}"

    def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        form_class = view_cls.form_class or (
            view_cls._make_form_class() if hasattr(view_cls, "_make_form_class") else None
        )
        if form_class is None:
            return _tool_error("unsupported", "no form_class available")
        # Native JSON args pass straight through (arrays/objects stay native);
        # omitted fields fall back to model defaults, mirroring REST create.
        form = form_class(merge_form_payload(form_class, args, fill_defaults=True))
        if not form.is_valid():
            return _tool_error("validation_error", "the submitted fields are not valid", fields=form.errors)
        obj = form.save()
        view_cls.on_form_valid(request, form, obj, is_create=True)
        log_write(ctx.user, obj, ADDITION, "MCP")
        fields = view_cls._get_detail_fields() or view_cls.fields
        extra = getattr(view_cls, "api_extra_fields", [])
        expand = set(getattr(view_cls, "api_expand_fields", []) or [])
        return serialize(obj, fields, extra, expand)

    schema = _build_form_input_schema(view_cls)
    desc = _action_description(view_cls, Action.CREATE)
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, write=True, requires_access=requires)(handler)


def _build_update_tool(view_cls, *, singular: str):
    name = f"update_{singular}"

    def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        obj = _fetch_one(view_cls, args, request)
        if isinstance(obj, dict):
            return obj

        if not view_cls.can_update(obj, request):
            return _tool_error("not_permitted", "update not permitted")

        form_class = view_cls.form_class or view_cls._make_form_class()

        # Mirror api.py's PATCH merge: existing fields (native values) overlaid
        # with incoming args — a populated JSONField round-trips unchanged.
        merged = merge_form_payload(
            form_class,
            {k: v for k, v in args.items() if k not in ("pk", "id")},
            instance=obj,
            instance_fields=view_cls.fields or view_cls._get_detail_fields(),
        )

        form = form_class(merged, instance=obj)
        if not form.is_valid():
            return _tool_error("validation_error", "the submitted fields are not valid", fields=form.errors)
        obj = form.save()
        view_cls.on_form_valid(request, form, obj, is_create=False)
        log_write(ctx.user, obj, CHANGE, "MCP")
        fields = view_cls._get_detail_fields() or view_cls.fields
        extra = getattr(view_cls, "api_extra_fields", [])
        expand = set(getattr(view_cls, "api_expand_fields", []) or [])
        return serialize(obj, fields, extra, expand)

    schema = _build_form_input_schema(view_cls, include_pk=True)
    desc = _action_description(view_cls, Action.UPDATE)
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, write=True, requires_access=requires)(handler)


def _build_delete_tool(view_cls, *, singular: str):
    name = f"delete_{singular}"

    def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        obj = _fetch_one(view_cls, args, request)
        if isinstance(obj, dict):
            return obj
        if not view_cls.can_delete(obj, request):
            return _tool_error("not_permitted", "delete not permitted")
        pk = obj.pk
        log_write(ctx.user, obj, DELETION, "MCP")  # before delete — obj.pk needed
        obj.delete()
        # Both spellings on the way out, so a caller that sent `pk` still finds it.
        return {"deleted": True, "id": pk, "pk": pk}

    schema = _object_id_schema()
    desc = _action_description(view_cls, Action.DELETE)
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, write=True, requires_access=requires)(handler)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def register_mcp_tools_from_crudview(view_cls) -> list[str]:
    """Emit MCP tools for one CRUDView. Returns list of tool names registered.

    Idempotent: a name already in TOOL_REGISTRY is skipped (the @tool decorator
    logs a warning and bails). Safe to call multiple times.
    """
    if not getattr(view_cls, "enable_mcp", False):
        return []
    if view_cls.model is None:
        return []

    def _slug(value) -> str:
        return str(value).lower().replace(" ", "_").replace("/", "_").replace("-", "_")

    # Naming: explicit mcp_plural/mcp_singular win; otherwise fall back to the
    # historical defaults (url_base for the list verb, verbose_name for the
    # singular verbs). Keeping the fallback in place means existing CRUDViews
    # produce the same tool names they did before this knob existed.
    base = _slug(
        view_cls.mcp_plural
        or view_cls.url_base
        or view_cls.model._meta.verbose_name_plural
    )
    singular = _slug(view_cls.mcp_singular or view_cls.model._meta.verbose_name)

    selected = view_cls.mcp_actions if view_cls.mcp_actions is not None else view_cls.actions
    selected_set = set(selected)
    registered: list[str] = []

    if Action.LIST in view_cls.actions and Action.LIST in selected_set:
        _build_list_tool(view_cls, base=base)
        # Append the registered tool name (``list_<base>``), not the inner
        # handler's ``__name__`` — they differ, which previously dropped the list
        # tool from this function's reported names even though it registered fine.
        registered.append(f"list_{base}")
    if Action.DETAIL in view_cls.actions and Action.DETAIL in selected_set:
        _build_get_tool(view_cls, singular=singular)
        registered.append(f"get_{singular}")
    if Action.CREATE in view_cls.actions and Action.CREATE in selected_set:
        _build_create_tool(view_cls, singular=singular)
        registered.append(f"create_{singular}")
    if Action.UPDATE in view_cls.actions and Action.UPDATE in selected_set:
        _build_update_tool(view_cls, singular=singular)
        registered.append(f"update_{singular}")
    if Action.DELETE in view_cls.actions and Action.DELETE in selected_set:
        _build_delete_tool(view_cls, singular=singular)
        registered.append(f"delete_{singular}")

    # Filter out duplicates that the decorator skipped (already in registry
    # from a prior call). Compare against the actual registry state.
    return [n for n in registered if n in TOOL_REGISTRY]


def get_view_for_tool(tool_name: str):
    """Reverse lookup — not used by HTTP, but handy for debugging/doctor."""
    return TOOL_REGISTRY.get(tool_name)


__all__ = [
    "register_mcp_tools_from_crudview",
    "get_view_for_tool",
    "ToolDef",
]
