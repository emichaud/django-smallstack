"""Stock Django REST API views for CRUDView.

~200 lines of throwaway glue. If the project graduates to DRF,
delete this file and write DRF viewsets. Everything else
(filters, tokens, models, exports) transfers directly.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.urls import URLPattern, path
from django.views.decorators.csrf import csrf_exempt

from .crud import Action


def build_api_urls(crud_config) -> list[URLPattern]:
    """Generate API URL patterns from a CRUDView config."""
    prefix = getattr(settings, "SMALLSTACK_API_PREFIX", "api/")
    url_base = crud_config._get_url_base()
    name_base = url_base.replace("/", "-")

    list_view = _make_api_list_view(crud_config)
    detail_view = _make_api_detail_view(crud_config)

    return [
        path(f"{prefix}{url_base}/", list_view, name=f"{name_base}-api-list"),
        path(
            f"{prefix}{url_base}/<int:pk>/",
            detail_view,
            name=f"{name_base}-api-detail",
        ),
    ]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def _authenticate_api_request(
    request: HttpRequest,
) -> tuple[object | None, JsonResponse | None]:
    """Authenticate via Bearer token or existing session. API views only."""
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")

    if auth_header.startswith("Bearer "):
        from .models import APIToken

        raw_key = auth_header[7:]
        user = APIToken.authenticate(raw_key)
        if user is None:
            return None, JsonResponse({"error": "Invalid token"}, status=401)
        request.user = user
        request._api_token_auth = True
        return user, None

    # No Bearer header — use existing session auth
    if request.user.is_authenticated:
        return request.user, None

    return None, JsonResponse({"error": "Authentication required"}, status=401)


# ---------------------------------------------------------------------------
# Permission checking
# ---------------------------------------------------------------------------


def _check_api_permissions(request, crud_config):
    """Translate CRUDView mixins to API responses (JSON, not redirects)."""
    from apps.smallstack.mixins import StaffRequiredMixin

    for mixin in crud_config.mixins:
        if issubclass(mixin, StaffRequiredMixin) or mixin.__name__ == "StaffRequiredMixin":
            if not request.user.is_staff:
                return JsonResponse({"error": "Staff access required"}, status=403)
    return None


# ---------------------------------------------------------------------------
# JSON body parsing
# ---------------------------------------------------------------------------


def _parse_json_body(request):
    """Parse JSON body into a QueryDict for ModelForm compatibility."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None, JsonResponse(
            {"errors": {"__all__": ["Invalid JSON"]}}, status=400
        )

    q = QueryDict(mutable=True)
    for key, value in data.items():
        if isinstance(value, list):
            q.setlist(key, [str(v) for v in value])
        elif value is None:
            q[key] = ""
        else:
            q[key] = str(value)
    return q, None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize(obj, fields, extra_fields=None):
    """Serialize a model instance to a dict."""
    data = {"id": obj.pk}
    all_fields = list(fields) + list(extra_fields or [])
    for f in all_fields:
        val = getattr(obj, f, None)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        elif hasattr(val, "pk"):
            val = val.pk
        elif isinstance(val, bool):
            val = val  # keep as bool for JSON
        data[f] = val
    return data


# ---------------------------------------------------------------------------
# View factories
# ---------------------------------------------------------------------------


def _make_api_list_view(crud_config):
    """Create a list+create API view for the given CRUDView config."""

    @csrf_exempt
    def api_list_view(request):
        user, err = _authenticate_api_request(request)
        if err:
            return err
        perm_err = _check_api_permissions(request, crud_config)
        if perm_err:
            return perm_err

        if request.method == "GET":
            return _api_list(request, crud_config)
        elif request.method == "POST":
            if Action.CREATE not in crud_config.actions:
                return JsonResponse({"error": "Method not allowed"}, status=405)
            return _api_create(request, crud_config)
        return JsonResponse({"error": "Method not allowed"}, status=405)

    return api_list_view


def _make_api_detail_view(crud_config):
    """Create a detail+update+delete API view for the given CRUDView config."""

    @csrf_exempt
    def api_detail_view(request, pk):
        user, err = _authenticate_api_request(request)
        if err:
            return err
        perm_err = _check_api_permissions(request, crud_config)
        if perm_err:
            return perm_err

        qs = crud_config._get_queryset()
        try:
            obj = qs.get(pk=pk)
        except qs.model.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)

        if request.method == "GET":
            fields = crud_config._get_detail_fields() or crud_config.fields
            return JsonResponse(_serialize(obj, fields, crud_config.api_extra_fields))

        elif request.method in ("PUT", "PATCH"):
            if Action.UPDATE not in crud_config.actions:
                return JsonResponse({"error": "Method not allowed"}, status=405)
            if not crud_config.can_update(obj, request):
                return JsonResponse({"error": "Permission denied"}, status=403)
            return _api_update(request, obj, crud_config)

        elif request.method == "DELETE":
            if Action.DELETE not in crud_config.actions:
                return JsonResponse({"error": "Method not allowed"}, status=405)
            if not crud_config.can_delete(obj, request):
                return JsonResponse({"error": "Permission denied"}, status=403)
            obj.delete()
            return HttpResponse(status=204)

        return JsonResponse({"error": "Method not allowed"}, status=405)

    return api_detail_view


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------


def _api_list(request, crud_config):
    """Handle GET on list endpoint: list, search, filter, paginate, export."""
    from django.db.models import Q

    qs = crud_config._get_queryset()
    qs = crud_config.get_list_queryset(qs, request)

    # Search
    search_fields = crud_config._resolve_search_fields()
    if search_fields:
        q = request.GET.get("q", "").strip()
        if q:
            query = Q()
            for field in search_fields:
                query |= Q(**{f"{field}__icontains": q})
            qs = qs.filter(query)

    # Filter
    filter_fields = crud_config._resolve_filter_fields()
    filter_class = crud_config._resolve_filter_class()
    if filter_fields or filter_class:
        import django_filters

        fs_class = filter_class
        if not fs_class:
            fs_class = type(
                "AutoFilter",
                (django_filters.FilterSet,),
                {
                    "Meta": type(
                        "Meta",
                        (),
                        {"model": crud_config.model, "fields": filter_fields},
                    )
                },
            )
        filterset = fs_class(request.GET, queryset=qs)
        qs = filterset.qs

    # Export
    export_fmt = request.GET.get("format")
    export_formats = crud_config._resolve_export_formats()
    if export_fmt and export_fmt in export_formats:
        return _api_export(qs, crud_config, export_fmt)

    # Paginate
    page_size = crud_config._resolve_paginate_by() or 25
    page_num = int(request.GET.get("page", 1))
    total = qs.count()
    start = (page_num - 1) * page_size
    items = list(qs[start : start + page_size])

    fields = crud_config._get_list_fields()
    results = [_serialize(obj, fields, crud_config.api_extra_fields) for obj in items]

    # Build next/previous URLs
    base_path = request.path
    next_url = f"{base_path}?page={page_num + 1}" if start + page_size < total else None
    prev_url = f"{base_path}?page={page_num - 1}" if page_num > 1 else None

    return JsonResponse(
        {
            "count": total,
            "next": next_url,
            "previous": prev_url,
            "results": results,
        }
    )


def _api_create(request, crud_config):
    """Handle POST on list endpoint: create a new object."""
    data, err = _parse_json_body(request)
    if err:
        return err

    form_class = crud_config.form_class or crud_config._make_form_class()
    form = form_class(data)
    if form.is_valid():
        obj = form.save()
        crud_config.on_form_valid(request, form, obj, is_create=True)
        return JsonResponse(_serialize(obj, crud_config._get_detail_fields() or crud_config.fields, crud_config.api_extra_fields), status=201)
    return JsonResponse({"errors": form.errors}, status=400)


def _api_update(request, obj, crud_config):
    """Handle PUT/PATCH on detail endpoint."""
    data, err = _parse_json_body(request)
    if err:
        return err

    form_class = crud_config.form_class or crud_config._make_form_class()

    if request.method == "PATCH":
        # Merge existing object data with incoming partial data
        from django.forms.models import model_to_dict

        existing = model_to_dict(obj, fields=crud_config.fields or crud_config._get_detail_fields())
        merged = QueryDict(mutable=True)
        for key, value in existing.items():
            if value is None:
                merged[key] = ""
            elif isinstance(value, list):
                merged.setlist(key, [str(v) for v in value])
            else:
                merged[key] = str(value)
        # Override with incoming data
        for key in data:
            if data.getlist(key):
                merged.setlist(key, data.getlist(key))
            else:
                merged[key] = data[key]
        data = merged

    form = form_class(data, instance=obj)
    if form.is_valid():
        obj = form.save()
        crud_config.on_form_valid(request, form, obj, is_create=False)
        return JsonResponse(_serialize(obj, crud_config._get_detail_fields() or crud_config.fields, crud_config.api_extra_fields))
    return JsonResponse({"errors": form.errors}, status=400)


def _api_export(qs, crud_config, fmt):
    """Handle ?format=csv|json on API list endpoint."""
    import tablib
    from django.utils import timezone

    fields = crud_config._get_list_fields()
    model = crud_config.model

    headers = []
    for f in fields:
        try:
            headers.append(str(model._meta.get_field(f).verbose_name).capitalize())
        except Exception:
            headers.append(f.replace("_", " ").capitalize())

    dataset = tablib.Dataset(headers=headers)
    for obj in qs.iterator():
        row = []
        for f in fields:
            val = getattr(obj, f, "")
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            elif hasattr(val, "pk"):
                val = str(val)
            elif isinstance(val, bool):
                val = str(val).lower()
            row.append(val if val is not None else "")
        dataset.append(row)

    content_types = {"csv": "text/csv", "json": "application/json"}
    prefix = str(model._meta.verbose_name_plural).replace(" ", "_")
    datestamp = timezone.now().strftime("%Y-%m-%d")
    filename = f"{prefix}_{datestamp}.{fmt}"

    response = HttpResponse(
        getattr(dataset, fmt),
        content_type=content_types.get(fmt, "application/octet-stream"),
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
