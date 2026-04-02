# Custom API Endpoints

SmallStack auto-generates REST endpoints when you set `enable_api = True` on a CRUDView. That covers the standard list, create, read, update, and delete operations. But real applications need endpoints that don't map to a single model — triggering actions, orchestrating multi-step workflows, integrating with external services, or returning computed results.

The `api_view` decorator gives you a clean way to build these endpoints while keeping the same authentication, error format, and conventions as the generated ones.

## Quick Start

```python
# apps/myapp/api.py
from apps.smallstack.api import api_view, api_error

@api_view(methods=["POST"], require_staff=True)
def approve_ticket(request):
    ticket_id = request.json.get("ticket_id")
    if not ticket_id:
        return api_error("ticket_id is required", 400)

    ticket = Ticket.objects.get(pk=ticket_id)
    ticket.status = "approved"
    ticket.approved_by = request.user
    ticket.save()
    return {"id": ticket.pk, "status": "approved"}
```

```python
# apps/myapp/urls.py
from django.urls import path
from . import api

urlpatterns = [
    path("api/tickets/approve/", api.approve_ticket, name="api-tickets-approve"),
]
```

That's it. The decorator handles CSRF exemption, authentication, JSON parsing, and response formatting. You write the business logic.

## What the Decorator Does

When you decorate a view with `@api_view`, every request goes through these steps before your function runs:

1. **CSRF exemption** — API clients don't send CSRF tokens, so the decorator exempts the view automatically
2. **Method check** — if the request method isn't in your `methods` list, the client gets a `405 Method Not Allowed`
3. **Authentication** — checks for a `Bearer` token in the `Authorization` header, then falls back to Django session auth. Returns `401` if neither is present (unless you set `require_auth=False`)
4. **Permission checks** — if you set `require_staff=True`, non-staff users get `403`. If you set `require_auth_token=True`, only auth-level API tokens are accepted
5. **JSON body parsing** — for POST, PUT, PATCH, and DELETE requests, the body is parsed into a Python dict and attached as `request.json`. GET requests get `request.json = None`. Malformed JSON returns `400`

After your function returns, the decorator wraps the result:

| You return | Client receives |
|------------|----------------|
| `{"key": "value"}` | `200` with JSON body |
| `{"key": "value"}, 201` | `201` with JSON body |
| `HttpResponse(status=204)` | `204` passed through as-is |
| `api_error("message", 400)` | `400` with `{"errors": {"__all__": ["message"]}}` |

## Parameters

```python
@api_view(
    methods=["GET"],           # Allowed HTTP methods
    require_auth=True,         # Require Bearer token or session (401 if missing)
    require_staff=False,       # Require is_staff=True (403 if not)
    require_auth_token=False,  # Require auth-level manual token (403 if not)
)
```

## Common Patterns

### Public Endpoint (No Auth)

```python
@api_view(methods=["GET"], require_auth=False)
def health_check(request):
    return {"status": "ok"}
```

### Staff-Only Action

```python
@api_view(methods=["POST"], require_staff=True)
def run_report(request):
    report = generate_monthly_report(request.json.get("month"))
    return {"url": report.file.url}
```

### System-to-System (Auth Token)

For endpoints called by other services, not browser users. Requires a manual API token with `access_level="auth"`.

```python
@api_view(methods=["POST"], require_auth_token=True)
def webhook_receiver(request):
    process_event(request.json)
    return {"received": True}
```

### Creating Resources (201)

Return a tuple of `(dict, status_code)` for non-200 responses.

```python
@api_view(methods=["POST"])
def create_order(request):
    order = Order.objects.create(
        customer=request.user,
        notes=request.json.get("notes", ""),
    )
    for item in request.json["items"]:
        OrderLine.objects.create(order=order, product_id=item["product_id"])
    return {"id": order.pk, "total_lines": order.lines.count()}, 201
```

### No Content (204)

Return an `HttpResponse` directly when there's no body to send.

```python
from django.http import HttpResponse

@api_view(methods=["DELETE"], require_staff=True)
def clear_cache(request):
    cache.clear()
    return HttpResponse(status=204)
```

## Error Handling

Use `api_error()` for errors. It produces the same `{"errors": {"__all__": [message]}}` envelope used by the auto-generated CRUD endpoints, so frontend code only needs to handle one error shape.

```python
from apps.smallstack.api import api_view, api_error

@api_view(methods=["POST"])
def transfer_ownership(request):
    if not request.json.get("new_owner_id"):
        return api_error("new_owner_id is required", 400)

    asset = Asset.objects.filter(pk=request.json["asset_id"]).first()
    if not asset:
        return api_error("Asset not found", 404)

    if asset.owner != request.user:
        return api_error("You can only transfer assets you own", 403)

    asset.owner_id = request.json["new_owner_id"]
    asset.save()
    return {"id": asset.pk, "owner_id": asset.owner_id}
```

For field-level validation errors (like Django form errors), return a dict with an `errors` key:

```python
errors = {}
if not data.get("name"):
    errors["name"] = ["This field is required."]
if not data.get("email"):
    errors["email"] = ["This field is required."]
if errors:
    return {"errors": errors}, 400
```

## Wiring Up URLs

Custom endpoints are standard Django views. Add them to your app's `urls.py` and include them in the root URL conf.

```python
# config/urls.py
urlpatterns = [
    # ... existing patterns ...
    path("", include("apps.myapp.urls")),
]
```

By convention, prefix paths with `api/` so they sit alongside the auto-generated CRUD endpoints. This isn't enforced — it's just a good idea for consistency.

## When to Use What

| Situation | Approach |
|-----------|----------|
| Standard CRUD on a model | `enable_api = True` on CRUDView |
| Trigger an action (approve, sync, deploy) | `@api_view` with POST |
| Multi-model orchestration | `@api_view` with your own logic |
| Webhook receiver | `@api_view` with `require_auth_token=True` |
| Computed report or dashboard data | `@api_view` with GET |
| Public status/health endpoint | `@api_view` with `require_auth=False` |

Both patterns share the same token system, error format, and authentication layer. You can mix them freely in the same project.
