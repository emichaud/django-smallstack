"""Stock Django REST API views for CRUDView.

~200 lines of throwaway glue. If the project graduates to DRF,
delete this file and write DRF viewsets. Everything else
(filters, tokens, models, exports) transfers directly.
"""

from __future__ import annotations

import json
import math

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.urls import URLPattern, path
from django.views.decorators.csrf import csrf_exempt

from .crud import Action


def build_api_urls(crud_config) -> list[URLPattern]:
    """Generate API URL patterns from a CRUDView config."""
    # Safety warning: public API endpoints with no auth mixins
    if not crud_config.mixins:
        import warnings

        warnings.warn(
            f"{crud_config.__name__} has enable_api=True with no mixins — API endpoints are public",
            stacklevel=2,
        )

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


def _error(message, status):
    """Return a consistent error JsonResponse."""
    return JsonResponse({"errors": {"__all__": [message]}}, status=status)


def _authenticate_api_request(
    request: HttpRequest,
) -> tuple[object | None, JsonResponse | None]:
    """Authenticate via Bearer token or existing session. API views only."""
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")

    if auth_header.startswith("Bearer "):
        from .models import APIToken

        raw_key = auth_header[7:]
        user, token = APIToken.authenticate(raw_key)
        if user is None:
            return None, _error("Invalid token", 401)
        request.user = user
        request._api_token = token
        request._api_token_auth = True
        return user, None

    # No Bearer header — use existing session auth
    if request.user.is_authenticated:
        return request.user, None

    return None, _error("Authentication required", 401)


# ---------------------------------------------------------------------------
# Permission checking
# ---------------------------------------------------------------------------


def _check_api_permissions(request, crud_config, method="GET"):
    """Translate CRUDView mixins to API responses (JSON, not redirects)."""
    from apps.smallstack.mixins import StaffRequiredMixin

    for mixin in crud_config.mixins:
        if issubclass(mixin, StaffRequiredMixin) or mixin.__name__ == "StaffRequiredMixin":
            if not request.user.is_staff:
                return _error("Staff access required", 403)

    # Enforce access_level on manual tokens
    token = getattr(request, "_api_token", None)
    if token and token.token_type == "manual":
        if token.access_level == "readonly" and method not in ("GET", "HEAD", "OPTIONS"):
            return _error("Token is read-only", 403)
    return None


def _require_auth_token(request):
    """Check that the request uses a manual token with access_level='auth'."""
    token = getattr(request, "_api_token", None)
    if not token or token.token_type != "manual" or token.access_level != "auth":
        return _error("Auth-level token required", 403)
    return None


# ---------------------------------------------------------------------------
# JSON body parsing
# ---------------------------------------------------------------------------


def _parse_json_body(request):
    """Parse JSON body into a QueryDict for ModelForm compatibility."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None, JsonResponse({"errors": {"__all__": ["Invalid JSON"]}}, status=400)

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
# Pagination helpers
# ---------------------------------------------------------------------------

# Named page values accepted by ?page=
_PAGE_ALIASES: dict[str, str] = {"first": "first", "last": "last", "next": "next", "prev": "prev", "previous": "prev"}


def _resolve_page(raw: str, total_pages: int, current: int | None = None) -> int:
    """Resolve a page parameter to a 1-based page number.

    Accepts numeric strings ("1", "3") and named aliases:
      - "first" → 1
      - "last"  → total_pages
      - "next"  → current + 1 (clamped to total_pages)
      - "prev" / "previous" → current - 1 (clamped to 1)

    Out-of-range numeric values are clamped to [1, total_pages].
    Invalid strings fall back to page 1.
    """
    key = raw.strip().lower()
    alias = _PAGE_ALIASES.get(key)

    if alias == "first":
        return 1
    if alias == "last":
        return total_pages
    if alias == "next":
        base = current if current is not None else 1
        return min(base + 1, total_pages)
    if alias == "prev":
        base = current if current is not None else 1
        return max(base - 1, 1)

    # Numeric — clamp to valid range
    try:
        page = int(raw)
    except (ValueError, TypeError):
        return 1
    return max(1, min(page, total_pages))


# ---------------------------------------------------------------------------
# FK expansion helpers
# ---------------------------------------------------------------------------


def _resolve_expand_fields(request: HttpRequest, crud_config) -> set[str]:
    """Merge api_expand_fields with ?expand= query param."""
    expand: set[str] = set(getattr(crud_config, "api_expand_fields", []))
    param = request.GET.get("expand", "").strip()
    if param:
        expand.update(f.strip() for f in param.split(",") if f.strip())
    return expand


def _apply_select_related(qs, model, expand_fields: set[str]):
    """Add select_related() for FK fields in the expand set to avoid N+1."""
    if not expand_fields:
        return qs
    fk_names: list[str] = []
    for name in expand_fields:
        try:
            field = model._meta.get_field(name)
            if field.is_relation and (field.many_to_one or field.one_to_one):
                fk_names.append(name)
        except Exception:
            pass
    if fk_names:
        qs = qs.select_related(*fk_names)
    return qs


# ---------------------------------------------------------------------------
# Smart filter field spec builder
# ---------------------------------------------------------------------------

_DATE_LOOKUPS: list[str] = ["exact", "gte", "lte", "gt", "lt"]


def _build_filter_fields_spec(model, filter_fields: list[str]) -> dict[str, list[str]] | list[str]:
    """Convert a flat filter_fields list to a dict with smart lookups.

    Date and DateTime fields automatically get range lookups (gte, lte, gt, lt)
    in addition to exact match. Other fields keep exact match only.
    """
    from django.db import models as django_models

    spec: dict[str, list[str]] = {}
    has_dates = False
    for name in filter_fields:
        try:
            field = model._meta.get_field(name)
            if isinstance(field, (django_models.DateField, django_models.DateTimeField)):
                spec[name] = _DATE_LOOKUPS
                has_dates = True
            else:
                spec[name] = ["exact"]
        except Exception:
            spec[name] = ["exact"]
    # Only return dict if we found date fields; otherwise keep list for simplicity
    return spec if has_dates else filter_fields


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_AGG_OPS: set[str] = {"sum", "avg", "min", "max"}


def _compute_aggregations(request: HttpRequest, qs, crud_config) -> tuple[dict, JsonResponse | None]:
    """Process aggregation query params and return (extra_data, error_or_none).

    Supported params:
        ?count_by=<field>       — group counts (field must be in filter_fields)
        ?sum=<field>            — sum (field must be in api_aggregate_fields)
        ?avg=<field>            — average
        ?min=<field>            — minimum
        ?max=<field>            — maximum

    Multiple aggregate ops can be combined. Returns dict of extra keys to merge
    into the response, or a 400 JsonResponse on validation error.
    """
    from django.db.models import Avg, Count, Max, Min, Sum

    extra: dict = {}
    filter_fields = set(crud_config._resolve_filter_fields())
    agg_fields = set(getattr(crud_config, "api_aggregate_fields", []))

    # count_by
    count_by = request.GET.get("count_by", "").strip()
    if count_by:
        if count_by not in filter_fields:
            return {}, _error(f"count_by field '{count_by}' not in filter_fields", 400)
        rows = qs.values(count_by).annotate(_count=Count("id")).order_by(count_by)
        extra["counts"] = {
            str(row[count_by]).lower() if isinstance(row[count_by], bool) else str(row[count_by]): row["_count"]
            for row in rows
        }

    # sum / avg / min / max
    agg_funcs = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}
    agg_kwargs: dict = {}
    for op in _AGG_OPS:
        field_name = request.GET.get(op, "").strip()
        if not field_name:
            continue
        if field_name not in agg_fields:
            return {}, _error(f"{op} field '{field_name}' not in api_aggregate_fields", 400)
        agg_kwargs[f"{op}_{field_name}"] = agg_funcs[op](field_name)

    if agg_kwargs:
        result = qs.aggregate(**agg_kwargs)
        for key, val in result.items():
            extra[key] = round(val, 2) if isinstance(val, float) else val

    return extra, None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize(
    obj,
    fields: list[str],
    extra_fields: list[str] | None = None,
    expand_fields: set[str] | None = None,
) -> dict:
    """Serialize a model instance to a dict.

    When *expand_fields* is provided, FK fields in that set are serialized as
    ``{"id": pk, "name": str(related_obj)}`` instead of a bare integer PK.
    Nullable FKs still serialize as ``null``.
    """
    data: dict = {"id": obj.pk}
    all_fields = list(fields) + list(extra_fields or [])
    for f in all_fields:
        val = getattr(obj, f, None)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        elif hasattr(val, "pk"):
            if expand_fields and f in expand_fields:
                val = {"id": val.pk, "name": str(val)}
            else:
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
        perm_err = _check_api_permissions(request, crud_config, method=request.method)
        if perm_err:
            return perm_err

        if request.method == "GET":
            return _api_list(request, crud_config)
        elif request.method == "POST":
            if Action.CREATE not in crud_config.actions:
                return _error("Method not allowed", 405)
            return _api_create(request, crud_config)
        return _error("Method not allowed", 405)

    return api_list_view


def _make_api_detail_view(crud_config):
    """Create a detail+update+delete API view for the given CRUDView config."""

    @csrf_exempt
    def api_detail_view(request, pk):
        user, err = _authenticate_api_request(request)
        if err:
            return err
        perm_err = _check_api_permissions(request, crud_config, method=request.method)
        if perm_err:
            return perm_err

        qs = crud_config._get_queryset()
        expand_fields = _resolve_expand_fields(request, crud_config)
        if expand_fields:
            qs = _apply_select_related(qs, crud_config.model, expand_fields)
        try:
            obj = qs.get(pk=pk)
        except qs.model.DoesNotExist:
            return _error("Not found", 404)

        if request.method == "GET":
            fields = crud_config._get_detail_fields() or crud_config.fields
            return JsonResponse(_serialize(obj, fields, crud_config.api_extra_fields, expand_fields))

        elif request.method in ("PUT", "PATCH"):
            if Action.UPDATE not in crud_config.actions:
                return _error("Method not allowed", 405)
            if not crud_config.can_update(obj, request):
                return _error("Permission denied", 403)
            return _api_update(request, obj, crud_config)

        elif request.method == "DELETE":
            if Action.DELETE not in crud_config.actions:
                return _error("Method not allowed", 405)
            if not crud_config.can_delete(obj, request):
                return _error("Permission denied", 403)
            obj.delete()
            return HttpResponse(status=204)

        return _error("Method not allowed", 405)

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
            fields_spec = _build_filter_fields_spec(crud_config.model, filter_fields)
            fs_class = type(
                "AutoFilter",
                (django_filters.FilterSet,),
                {
                    "Meta": type(
                        "Meta",
                        (),
                        {"model": crud_config.model, "fields": fields_spec},
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

    # Aggregation (computed before pagination, on the full filtered queryset)
    agg_extra, agg_err = _compute_aggregations(request, qs, crud_config)
    if agg_err:
        return agg_err

    # FK expansion
    expand_fields = _resolve_expand_fields(request, crud_config)
    if expand_fields:
        qs = _apply_select_related(qs, crud_config.model, expand_fields)

    # Paginate (client can override page size via ?page_size=N, capped at 1000)
    _MAX_PAGE_SIZE: int = 1000
    page_size: int = crud_config._resolve_paginate_by() or 25
    raw_page_size = request.GET.get("page_size", "").strip()
    if raw_page_size:
        try:
            page_size = max(1, min(int(raw_page_size), _MAX_PAGE_SIZE))
        except (ValueError, TypeError):
            pass
    total: int = qs.count()
    total_pages: int = max(1, math.ceil(total / page_size))
    page_num: int = _resolve_page(request.GET.get("page", "1"), total_pages)
    start: int = (page_num - 1) * page_size
    items = list(qs[start : start + page_size])

    fields = crud_config._get_list_fields()
    results: list[dict] = [_serialize(obj, fields, crud_config.api_extra_fields, expand_fields) for obj in items]

    # Build next/previous URLs
    base_path: str = request.path
    next_url: str | None = f"{base_path}?page={page_num + 1}" if page_num < total_pages else None
    prev_url: str | None = f"{base_path}?page={page_num - 1}" if page_num > 1 else None

    response_data: dict = {
        "count": total,
        "page": page_num,
        "total_pages": total_pages,
        "next": next_url,
        "previous": prev_url,
        "results": results,
    }
    # Merge aggregation data into response (counts, sum_*, avg_*, etc.)
    response_data.update(agg_extra)

    return JsonResponse(response_data)


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
        expand_fields = _resolve_expand_fields(request, crud_config)
        fields = crud_config._get_detail_fields() or crud_config.fields
        return JsonResponse(
            _serialize(obj, fields, crud_config.api_extra_fields, expand_fields),
            status=201,
        )
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
        expand_fields = _resolve_expand_fields(request, crud_config)
        fields = crud_config._get_detail_fields() or crud_config.fields
        return JsonResponse(_serialize(obj, fields, crud_config.api_extra_fields, expand_fields))
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


# ---------------------------------------------------------------------------
# Auth token endpoint
# ---------------------------------------------------------------------------


def _user_json(user):
    """Serialize a user to a dict for API responses."""
    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": getattr(user, "email", ""),
        "is_staff": user.is_staff,
    }


@csrf_exempt
def api_auth_token(request: HttpRequest) -> JsonResponse:
    """Exchange username + password for a Bearer token (upsert).

    POST /api/auth/token/
    {"username": "alice", "password": "secret123", "expires_hours": 24}

    Upserts: finds existing active login token for the user, regenerates key
    and updates expiry. Old raw key immediately stops working.
    """
    if request.method != "POST":
        return _error("Method not allowed", 405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error("Invalid JSON", 400)

    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return _error("username and password are required", 400)

    from datetime import timedelta

    from django.contrib.auth import authenticate
    from django.utils import timezone

    from .models import APIToken

    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return _error("Invalid credentials", 401)

    # Compute expiry
    default_hours = getattr(settings, "SMALLSTACK_LOGIN_TOKEN_EXPIRY_HOURS", 24)
    max_hours = getattr(settings, "SMALLSTACK_LOGIN_TOKEN_MAX_HOURS", 168)
    requested_hours = data.get("expires_hours", default_hours)
    try:
        requested_hours = int(requested_hours)
    except (ValueError, TypeError):
        requested_hours = default_hours
    expiry_hours = min(max(1, requested_hours), max_hours)
    expires_at = timezone.now() + timedelta(hours=expiry_hours)

    # Upsert: find existing active login token for this user
    existing = APIToken.objects.filter(
        user=user, token_type="login", is_active=True,
    ).first()

    raw_key, prefix, hashed = APIToken._generate_raw_key()

    if existing:
        existing.prefix = prefix
        existing.hashed_key = hashed
        existing.expires_at = expires_at
        existing.last_used_at = timezone.now()
        existing.save(update_fields=["prefix", "hashed_key", "expires_at", "last_used_at"])
        token = existing
    else:
        token = APIToken.objects.create(
            user=user, name="Login token", prefix=prefix, hashed_key=hashed,
            token_type="login", access_level="", expires_at=expires_at,
        )

    return JsonResponse({
        "token": raw_key,
        "user": _user_json(user),
        "expires_at": expires_at.isoformat(),
    })


@csrf_exempt
def api_auth_register(request: HttpRequest) -> JsonResponse:
    """Create a new user and return a login token.

    POST /api/auth/register/
    {"username": "alice", "password": "secret123", "email": "alice@example.com"}

    Requires auth-level Bearer token.
    """
    if request.method != "POST":
        return _error("Method not allowed", 405)

    user, err = _authenticate_api_request(request)
    if err:
        return err
    perm_err = _require_auth_token(request)
    if perm_err:
        return perm_err

    if not getattr(settings, "SMALLSTACK_API_REGISTER_ENABLED", False):
        return _error("Registration is disabled", 403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error("Invalid JSON", 400)

    username = data.get("username", "").strip()
    password = data.get("password", "")
    email = data.get("email", "").strip()

    if not username or not password:
        return _error("username and password are required", 400)

    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    User = get_user_model()

    # Check uniqueness
    if User.objects.filter(username=username).exists():
        return JsonResponse({"errors": {"username": ["A user with that username already exists."]}}, status=400)

    # Validate password
    try:
        validate_password(password)
    except ValidationError as e:
        return JsonResponse({"errors": {"password": e.messages}}, status=400)

    # Create user — always non-staff, non-superuser
    new_user = User.objects.create_user(
        username=username, password=password, email=email,
        is_staff=False, is_superuser=False, is_active=True,
    )

    from datetime import timedelta

    from django.utils import timezone

    from .models import APIToken

    default_hours = getattr(settings, "SMALLSTACK_LOGIN_TOKEN_EXPIRY_HOURS", 24)
    expires_at = timezone.now() + timedelta(hours=default_hours)

    token, raw_key = APIToken.create_token(
        user=new_user, name="Login token",
        token_type="login", access_level="", expires_at=expires_at,
    )

    return JsonResponse({
        "token": raw_key,
        "user": _user_json(new_user),
        "expires_at": expires_at.isoformat(),
    }, status=201)


@csrf_exempt
def api_auth_me(request: HttpRequest) -> JsonResponse:
    """Return the authenticated user's profile.

    GET /api/auth/me/
    """
    if request.method != "GET":
        return _error("Method not allowed", 405)

    user, err = _authenticate_api_request(request)
    if err:
        return err

    return JsonResponse(_user_json(user))


@csrf_exempt
def api_auth_password(request: HttpRequest) -> JsonResponse:
    """User changes their own password.

    POST /api/auth/password/
    {"current_password": "old123", "new_password": "new456"}
    """
    if request.method != "POST":
        return _error("Method not allowed", 405)

    user, err = _authenticate_api_request(request)
    if err:
        return err

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error("Invalid JSON", 400)

    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not current_password or not new_password:
        return _error("current_password and new_password are required", 400)

    if not user.check_password(current_password):
        return _error("Current password is incorrect", 400)

    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    try:
        validate_password(new_password, user=user)
    except ValidationError as e:
        return JsonResponse({"errors": {"new_password": e.messages}}, status=400)

    user.set_password(new_password)
    user.save(update_fields=["password"])

    return JsonResponse({"message": "Password updated"})


@csrf_exempt
def api_auth_user_password(request: HttpRequest, user_id: int) -> JsonResponse:
    """System changes a user's password (no current password required).

    POST /api/auth/users/<id>/password/
    {"new_password": "new456"}

    Requires auth-level Bearer token.
    """
    if request.method != "POST":
        return _error("Method not allowed", 405)

    caller, err = _authenticate_api_request(request)
    if err:
        return err
    perm_err = _require_auth_token(request)
    if perm_err:
        return perm_err

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error("Invalid JSON", 400)

    new_password = data.get("new_password", "")
    if not new_password:
        return _error("new_password is required", 400)

    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    User = get_user_model()
    try:
        target_user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return _error("User not found", 404)

    try:
        validate_password(new_password, user=target_user)
    except ValidationError as e:
        return JsonResponse({"errors": {"new_password": e.messages}}, status=400)

    target_user.set_password(new_password)
    target_user.save(update_fields=["password"])

    return JsonResponse({"message": "Password updated"})


def api_auth_password_requirements(request: HttpRequest) -> JsonResponse:
    """Return the active password validation rules.

    GET /api/auth/password-requirements/
    """
    if request.method != "GET":
        return _error("Method not allowed", 405)

    from django.contrib.auth.password_validation import password_validators_help_texts

    return JsonResponse({"requirements": password_validators_help_texts()})


@csrf_exempt
def api_auth_user_deactivate(request: HttpRequest, user_id: int) -> JsonResponse:
    """System deactivates a user account and revokes all their tokens.

    POST /api/auth/users/<id>/deactivate/

    Requires auth-level Bearer token.
    """
    if request.method != "POST":
        return _error("Method not allowed", 405)

    caller, err = _authenticate_api_request(request)
    if err:
        return err
    perm_err = _require_auth_token(request)
    if perm_err:
        return perm_err

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from .models import APIToken

    User = get_user_model()
    try:
        target_user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return _error("User not found", 404)

    target_user.is_active = False
    target_user.save(update_fields=["is_active"])

    # Revoke all active tokens for this user
    APIToken.objects.filter(user=target_user, is_active=True).update(
        is_active=False, revoked_at=timezone.now(),
    )

    return JsonResponse({"message": "User deactivated"})


@csrf_exempt
def api_auth_logout(request: HttpRequest) -> JsonResponse:
    """Revoke the caller's login token.

    POST /api/auth/logout/
    """
    if request.method != "POST":
        return _error("Method not allowed", 405)

    user, err = _authenticate_api_request(request)
    if err:
        return err

    token = getattr(request, "_api_token", None)
    if token:
        token.revoke()

    return JsonResponse({"message": "Logged out"})
