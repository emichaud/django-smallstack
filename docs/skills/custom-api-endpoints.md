# Skill: Custom API Endpoints

SmallStack's REST API auto-generates CRUD endpoints from CRUDView configs. But not every endpoint fits the CRUD pattern — actions, integrations, reports, and orchestration workflows all need custom logic. The `api_view` decorator lets you build these endpoints with the same authentication, error handling, and response format as the generated ones.

## Overview

`api_view` is a function decorator that wraps a plain Django view with the SmallStack API layer: CSRF exemption, method checking, Bearer/session authentication, JSON body parsing, and response wrapping. You write only the business logic; the decorator handles the rest.

## File Locations

```
apps/smallstack/
├── api.py                 # api_view decorator, api_error helper
```

Your custom endpoints go wherever makes sense for your app:

```
apps/myapp/
├── api.py                 # Custom endpoints using api_view
├── urls.py                # Wire them into urlpatterns
```

## The Decorator

```python
from apps.smallstack.api import api_view, api_error
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `methods` | `["GET"]` | Allowed HTTP methods |
| `require_auth` | `True` | Require Bearer token or session auth (401 if missing) |
| `require_staff` | `False` | Require `is_staff=True` (403 if not) |
| `require_auth_token` | `False` | Require auth-level manual token (403 if not) |

### What It Handles

1. **`@csrf_exempt`** — applied automatically for API clients
2. **Method checking** — wrong method returns 405
3. **OPTIONS** — returns `{"methods": [...]}` with `Allow` header
4. **Authentication** — Bearer token or session, returns 401 if missing
5. **Permission checks** — staff and auth-token checks, returns 403
6. **JSON body parsing** — `request.json` is set to the parsed dict for POST/PUT/PATCH/DELETE, or `None` for GET/HEAD
7. **Invalid JSON** — returns 400 with standard error envelope
8. **Response wrapping** — dict return becomes `JsonResponse`

### Return Value Conventions

| Return | Result |
|--------|--------|
| `dict` | `JsonResponse(data, status=200)` |
| `(dict, int)` | `JsonResponse(data, status=int)` |
| `HttpResponse` | Passed through unchanged |
| `api_error(msg, status)` | `{"errors": {"__all__": [msg]}}` with given status |

## Examples

### Simple Action Endpoint

Trigger a sync operation. Staff-only, POST, returns a count.

```python
# apps/integrations/api.py
from apps.smallstack.api import api_view, api_error

@api_view(methods=["POST"], require_staff=True)
def run_sync(request):
    target = request.json.get("target")
    if not target:
        return api_error("target is required", 400)
    count = sync_from_external(target)
    return {"synced": count}
```

```python
# apps/integrations/urls.py
from django.urls import path
from . import api

urlpatterns = [
    path("api/integrations/sync/", api.run_sync, name="api-integrations-sync"),
]
```

```bash
curl -X POST http://localhost:8005/api/integrations/sync/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"target": "inventory"}'

# → {"synced": 42}
```

### Public Health Check

No authentication, GET only.

```python
@api_view(methods=["GET"], require_auth=False)
def health(request):
    return {"status": "ok", "version": "1.2.0"}
```

### Multi-Step Orchestration

Create a parent and its children in one request, return the result with a 201 status.

```python
@api_view(methods=["POST"], require_auth=True)
def create_order(request):
    data = request.json
    if not data.get("items"):
        return api_error("items are required", 400)

    order = Order.objects.create(
        customer=request.user,
        notes=data.get("notes", ""),
    )
    for item in data["items"]:
        OrderLine.objects.create(
            order=order,
            product_id=item["product_id"],
            quantity=item.get("quantity", 1),
        )

    return {"id": order.pk, "lines": order.lines.count()}, 201
```

### Webhook Receiver

Auth-token required (system-level), processes incoming webhook.

```python
@api_view(methods=["POST"], require_auth=True, require_auth_token=True)
def stripe_webhook(request):
    event_type = request.json.get("type")
    if event_type == "payment_intent.succeeded":
        handle_payment(request.json["data"])
    return {"received": True}
```

### Returning Non-JSON Responses

Return an `HttpResponse` directly for file downloads, redirects, or 204 No Content.

```python
from django.http import HttpResponse

@api_view(methods=["DELETE"], require_staff=True)
def clear_cache(request):
    cache.clear()
    return HttpResponse(status=204)
```

## Error Handling

Use `api_error()` for errors that match the standard SmallStack error envelope:

```python
from apps.smallstack.api import api_view, api_error

@api_view(methods=["POST"])
def approve_ticket(request):
    ticket = get_object_or_404(Ticket, pk=request.json.get("ticket_id"))

    if ticket.status == "closed":
        return api_error("Cannot approve a closed ticket", 409)

    if not request.user.has_perm("tickets.approve"):
        return api_error("Approval permission required", 403)

    ticket.status = "approved"
    ticket.approved_by = request.user
    ticket.save()
    return {"id": ticket.pk, "status": ticket.status}
```

For field-level validation errors, return a dict with an `errors` key directly:

```python
errors = {}
if not data.get("name"):
    errors["name"] = ["This field is required."]
if not data.get("email"):
    errors["email"] = ["This field is required."]
if errors:
    return {"errors": errors}, 400
```

## URL Patterns

Custom API endpoints live in your app's `urls.py` and get included in the root URL conf like any Django URL. There is no special registration step.

```python
# config/urls.py
urlpatterns = [
    # ... existing patterns ...
    path("", include("apps.integrations.urls")),
]
```

The convention is to prefix your paths with `api/` to keep them alongside the generated CRUD endpoints, but this is not enforced.

## Relationship to CRUDView APIs

| | CRUDView `enable_api` | `@api_view` decorator |
|---|---|---|
| **Use when** | Standard CRUD on a model | Anything else |
| **Generated from** | CRUDView class config | Hand-written function |
| **Auth** | Automatic from mixins | Explicit via decorator params |
| **Schema/OpenAPI** | Auto-included | Not included (manual) |
| **Serialization** | Auto from model fields | You serialize the response |
| **Filtering/pagination** | Built-in | You build it (or import helpers) |

Both share the same authentication layer, error format, and token system. A project can mix auto-generated CRUD endpoints with custom `@api_view` endpoints freely.

## Best Practices

1. **Keep business logic in your view function or a service module** — the decorator only handles HTTP concerns
2. **Use `api_error()` for all error responses** — keeps the error format consistent with auto-generated endpoints
3. **Prefix URLs with `api/`** — follows the same convention as CRUDView endpoints
4. **Use `require_auth_token=True` for system/service endpoints** — these are the endpoints that should only be called by other services, not by browser users
5. **Return `(dict, status_code)` tuples for non-200 success responses** — e.g., `return {"id": 1}, 201` for created resources
6. **Access `request.json` directly** — no need to parse `request.body` yourself; it's already a dict (or `None` for GET)
