"""Auto-derive MCP tools from a CRUDView's existing configuration.

The factory walks `view_cls.actions` (filtered by `view_cls.mcp_actions` if
set) and emits one async tool per action. Each tool reuses the same helpers
the REST API uses (serialize, apply_search, apply_filters, apply_ordering),
calls the CRUDView's tenancy hook (get_list_queryset), and respects the
existing form-based create/update path including `on_form_valid` side
effects. The goal is "what works on /api/<resource>/ also works on /mcp".
"""

from __future__ import annotations

import logging
from typing import Any

from django.forms.models import model_to_dict
from django.http import HttpRequest, QueryDict

from apps.smallstack.api import (
    apply_filters,
    apply_ordering,
    apply_search,
    field_to_schema,
    serialize,
)
from apps.smallstack.crud import Action
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


def _args_to_querydict(args: dict[str, Any]) -> QueryDict:
    """Convert an MCP tool args dict to a QueryDict for ModelForm consumption."""
    qd = QueryDict(mutable=True)
    for key, value in args.items():
        if value is None:
            qd[key] = ""
        elif isinstance(value, list):
            qd.setlist(key, [str(v) for v in value])
        elif isinstance(value, bool):
            qd[key] = "true" if value else "false"
        else:
            qd[key] = str(value)
    return qd


def _has_staff_mixin(view_cls) -> bool:
    return any(
        issubclass(m, StaffRequiredMixin) or getattr(m, "__name__", "") == "StaffRequiredMixin"
        for m in (view_cls.mixins or [])
    )


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


def _build_form_input_schema(view_cls, *, include_pk: bool = False) -> dict[str, Any]:
    """JSON Schema for create/update inputs, derived from form_class or fields."""
    form_class = view_cls.form_class or (
        view_cls._make_form_class() if hasattr(view_cls, "_make_form_class") else None
    )
    props: dict[str, Any] = {}
    required: list[str] = []

    if include_pk:
        props["pk"] = {"type": "integer", "description": "Primary key of the record."}
        required.append("pk")

    if form_class is not None:
        try:
            form_instance = form_class()
            for fname, ffield in form_instance.fields.items():
                schema = field_to_schema(fname, ffield, view_cls.model)
                props[fname] = {k: v for k, v in schema.items() if k not in ("required",)}
                if schema.get("required") and not include_pk:
                    required.append(fname)
        except Exception:
            logger.exception("Failed to introspect form_class for %s", view_cls)

    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Tool builders (one per Action)
# ---------------------------------------------------------------------------


def _build_list_tool(view_cls, *, base: str, description: str):
    name = f"list_{base}"

    async def handler(args: dict[str, Any]):
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
        rows = list(qs[:limit])
        return {
            "count": len(rows),
            "limit": limit,
            "results": [serialize(obj, fields, extra) for obj in rows],
        }

    desc = description or f"List {view_cls.model._meta.verbose_name_plural}. Supports filters + search."
    schema = _build_list_input_schema(view_cls)
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, requires_access=requires)(handler)


def _build_get_tool(view_cls, *, singular: str, description: str):
    name = f"get_{singular}"

    async def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        qs = view_cls._get_queryset()
        qs = view_cls.get_list_queryset(qs, request)
        pk = args.get("pk")
        if pk is None:
            return {"error": "pk is required"}
        try:
            obj = qs.get(pk=pk)
        except view_cls.model.DoesNotExist:
            return {"error": f"{view_cls.model.__name__} pk={pk} not found"}
        fields = view_cls._get_detail_fields() or view_cls.fields
        extra = getattr(view_cls, "api_extra_fields", [])
        return serialize(obj, fields, extra)

    schema = {
        "type": "object",
        "properties": {"pk": {"type": "integer", "description": "Primary key."}},
        "required": ["pk"],
        "additionalProperties": False,
    }
    desc = description or f"Fetch one {view_cls.model._meta.verbose_name} by primary key."
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, requires_access=requires)(handler)


def _build_create_tool(view_cls, *, singular: str, description: str):
    name = f"create_{singular}"

    async def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        form_class = view_cls.form_class or (
            view_cls._make_form_class() if hasattr(view_cls, "_make_form_class") else None
        )
        if form_class is None:
            return {"error": "no form_class available"}
        form = form_class(_args_to_querydict(args))
        if not form.is_valid():
            return {"errors": form.errors}
        obj = form.save()
        view_cls.on_form_valid(request, form, obj, is_create=True)
        fields = view_cls._get_detail_fields() or view_cls.fields
        extra = getattr(view_cls, "api_extra_fields", [])
        return serialize(obj, fields, extra)

    schema = _build_form_input_schema(view_cls)
    desc = description or f"Create a new {view_cls.model._meta.verbose_name}."
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, write=True, requires_access=requires)(handler)


def _build_update_tool(view_cls, *, singular: str, description: str):
    name = f"update_{singular}"

    async def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        pk = args.get("pk")
        if pk is None:
            return {"error": "pk is required"}

        qs = view_cls._get_queryset()
        qs = view_cls.get_list_queryset(qs, request)
        try:
            obj = qs.get(pk=pk)
        except view_cls.model.DoesNotExist:
            return {"error": f"{view_cls.model.__name__} pk={pk} not found"}

        if not view_cls.can_update(obj, request):
            return {"error": "update not permitted"}

        form_class = view_cls.form_class or view_cls._make_form_class()

        # Mirror api.py's PATCH merge: existing fields overlaid with incoming args.
        existing = model_to_dict(obj, fields=view_cls.fields or view_cls._get_detail_fields())
        merged = QueryDict(mutable=True)
        for key, value in existing.items():
            if value is None:
                merged[key] = ""
            elif isinstance(value, list):
                merged.setlist(key, [str(v) for v in value])
            else:
                merged[key] = str(value)
        incoming = _args_to_querydict({k: v for k, v in args.items() if k != "pk"})
        for key in incoming:
            if incoming.getlist(key):
                merged.setlist(key, incoming.getlist(key))

        form = form_class(merged, instance=obj)
        if not form.is_valid():
            return {"errors": form.errors}
        obj = form.save()
        view_cls.on_form_valid(request, form, obj, is_create=False)
        fields = view_cls._get_detail_fields() or view_cls.fields
        extra = getattr(view_cls, "api_extra_fields", [])
        return serialize(obj, fields, extra)

    schema = _build_form_input_schema(view_cls, include_pk=True)
    desc = description or f"Update a {view_cls.model._meta.verbose_name}."
    requires = "staff" if _has_staff_mixin(view_cls) else None
    return tool(name, desc, schema, write=True, requires_access=requires)(handler)


def _build_delete_tool(view_cls, *, singular: str, description: str):
    name = f"delete_{singular}"

    async def handler(args: dict[str, Any]):
        ctx = current_context()
        request = _fake_request(ctx.user)
        pk = args.get("pk")
        if pk is None:
            return {"error": "pk is required"}
        qs = view_cls._get_queryset()
        qs = view_cls.get_list_queryset(qs, request)
        try:
            obj = qs.get(pk=pk)
        except view_cls.model.DoesNotExist:
            return {"error": f"{view_cls.model.__name__} pk={pk} not found"}
        if not view_cls.can_delete(obj, request):
            return {"error": "delete not permitted"}
        obj.delete()
        return {"deleted": True, "pk": pk}

    schema = {
        "type": "object",
        "properties": {"pk": {"type": "integer", "description": "Primary key."}},
        "required": ["pk"],
        "additionalProperties": False,
    }
    desc = description or f"Delete a {view_cls.model._meta.verbose_name}."
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

    base = view_cls.url_base or view_cls.model._meta.model_name
    base = str(base).replace("/", "_").replace("-", "_")
    singular = view_cls.model._meta.verbose_name.lower().replace(" ", "_").replace("-", "_")
    description = view_cls.mcp_description or ""

    selected = view_cls.mcp_actions if view_cls.mcp_actions is not None else view_cls.actions
    selected_set = set(selected)
    registered: list[str] = []

    if Action.LIST in view_cls.actions and Action.LIST in selected_set:
        registered.append(_build_list_tool(view_cls, base=base, description=description).__name__)
    if Action.DETAIL in view_cls.actions and Action.DETAIL in selected_set:
        _build_get_tool(view_cls, singular=singular, description=description)
        registered.append(f"get_{singular}")
    if Action.CREATE in view_cls.actions and Action.CREATE in selected_set:
        _build_create_tool(view_cls, singular=singular, description=description)
        registered.append(f"create_{singular}")
    if Action.UPDATE in view_cls.actions and Action.UPDATE in selected_set:
        _build_update_tool(view_cls, singular=singular, description=description)
        registered.append(f"update_{singular}")
    if Action.DELETE in view_cls.actions and Action.DELETE in selected_set:
        _build_delete_tool(view_cls, singular=singular, description=description)
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
