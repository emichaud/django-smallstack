# MCP for End Users

**Read this** when you want a *non-staff* user — Alice, a paying customer, a tenant — to call MCP tools that act on *her* data. The bundled MCP tools (`list_users`, `search_api_tokens`, `search_users`, …) ship staff-only by design. End-user MCP needs three deliberate moves on the CRUDView, mirroring the web/REST story in [`building-a-user-facing-site.md`](../building-a-user-facing-site.md).

If you haven't read it, read `building-a-user-facing-site.md` first — this skill assumes you already understand the web/REST side of "Alice signs in and sees her stuff." Most of the work happens on the same CRUDView; the MCP factory inherits the same decisions for free.

## What the framework does for end users by default

When a CRUDView declares `enable_mcp = True`, the MCP factory in `apps/mcp/factory.py` mints a tool per action — `list_<plural>`, `get_<singular>`, `create_<singular>`, `update_<singular>`, `delete_<singular>` — and reads the CRUDView's auth mixin to set each tool's required `access_level`:

| CRUDView mixin | Generated tools require | Effect |
|---|---|---|
| `StaffRequiredMixin` | `access_level=staff` | Only a staff-tier token can call them. |
| `LoginRequiredMixin` | `access_level=readonly` (write tools also need `write` scope) | Any authenticated user with a token can call read tools; only `write`-scoped tokens can hit `create_*` / `update_*` / `delete_*`. |
| *(none)* | `access_level=readonly` + a startup warning | The CRUDView has no web auth either — usually a bug. |

The MCP factory invokes each tool through the CRUDView's `get_list_queryset(qs, request)` hook with `request.user = ctx.user` (the user the calling token belongs to). **That's where end-user tenancy is enforced for MCP, same as for REST and HTML.** Get `get_list_queryset` right and the same scope holds across all three surfaces; get it wrong and all three leak.

## The three moves

### 1. `LoginRequiredMixin` on the CRUDView (not `StaffRequiredMixin`)

```python
# apps/billing/views.py
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.smallstack.crud import Action, CRUDView
from .models import Invoice


class InvoiceCRUDView(CRUDView):
    model = Invoice
    url_base = "invoices"
    mixins = [LoginRequiredMixin]   # ← not StaffRequiredMixin
    enable_mcp = True
    enable_search = True   # see Move 3
```

The MCP tools generated for this view now accept tokens with `access_level=readonly` (for `list_invoices`, `get_invoice`, `search_invoices`) and `access_level=readonly` plus the `write` scope (for `create_invoice`, `update_invoice`, `delete_invoice`).

### 2. `get_list_queryset` scoping (where the gate actually lives)

`LoginRequiredMixin` admits Alice; it does not constrain what she sees. **`get_list_queryset` is the single hook that scopes the data across all three surfaces:**

```python
class InvoiceCRUDView(CRUDView):
    # … as above …

    def get_list_queryset(self, qs, request):
        # SINGLE place tenancy is enforced. Web list, REST list, AND
        # every MCP tool (list_, get_, search_) run through this.
        # Get this wrong and Alice sees Bob's invoices everywhere.
        return qs.filter(owner=request.user)

    def can_update(self, obj, request):
        return obj.owner_id == request.user.id

    can_delete = can_update
```

Three things to know about this:

- **MCP tools call `get_list_queryset` for you.** The factory's `_fake_request` carries the token user as `request.user`, so your filter sees the right identity automatically.
- **`get_<singular>` runs the scoped queryset's `.get(pk=…)`**. If Alice asks for `get_invoice(pk=99)` and invoice 99 belongs to Bob, the scoped queryset's `.get` raises `DoesNotExist`, the framework returns `{"error": "Invoice pk=99 not found"}`, and Alice can't enumerate Bob's row by guessing pks.
- **Write tools (`create_*`/`update_*`/`delete_*`) still need per-row checks.** `can_update(obj, request)` and `can_delete(obj, request)` guard those. Don't skip them — `LoginRequiredMixin` admits Alice; only the per-row hook stops her from overwriting Bob's row by passing his pk to `update_invoice`.

### 3. `search_access` + `search_visibility` for findability via MCP

If the CRUDView opts into search (`enable_search = True`), the *search-MCP* tools (`search_invoices`, `search_all`) gate independently via the registry's access tier (since v0.11.9 — round-2 audit §3.3). Configure both:

```python
from apps.search.access import SearchAccess


class InvoiceCRUDView(CRUDView):
    # … as above …

    enable_search = True
    search_fields = ["number", "customer_reference", "notes"]
    search_display = "number"

    # Any authenticated user can find rows from this view via search MCP …
    search_access = SearchAccess.AUTHENTICATED

    # … but only THEIR rows. Mirrors get_list_queryset.
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(owner=user)
    )
```

Without this, search MCP defaults to `SearchAccess.STAFF` and non-staff tokens get `{"denied": true}` when calling `search_invoices`. The web `/smallstack/search/` page would show the same gate.

## Worked example — the complete user-facing CRUDView

Putting all three moves together:

```python
# apps/billing/views.py
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.search.access import SearchAccess
from apps.smallstack.crud import Action, CRUDView

from .models import Invoice


class InvoiceCRUDView(CRUDView):
    model = Invoice
    url_base = "invoices"

    # Any signed-in user (web + MCP + REST)
    mixins = [LoginRequiredMixin]

    # All three surfaces — one declarative class, four entry points
    enable_api = True       # → /<include>/api/invoices/
    enable_mcp = True       # → list_invoices, get_invoice, create_invoice, …
    enable_search = True    # → search_invoices + a row on /search/

    # Search opt-in (visibility for read; access for findability)
    search_fields = ["number", "customer_reference", "notes"]
    search_display = "number"
    search_subtitle = "customer_reference"
    search_access = SearchAccess.AUTHENTICATED
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(owner=user)
    )

    list_fields = ["number", "customer_reference", "amount_due", "due_date", "status"]

    def get_list_queryset(self, qs, request):
        # SINGLE source of truth — web/REST/MCP all flow through this.
        return qs.filter(owner=request.user)

    def can_update(self, obj, request):
        return obj.owner_id == request.user.id

    can_delete = can_update
```

That one class produces, for Alice (signed in, `access_level=readonly` token):

| Surface | Endpoint | What Alice sees |
|---|---|---|
| Web list | `/billing/invoices/` | Her own invoices (table) |
| Web detail | `/billing/invoices/<pk>/` | Her invoice, or 404 if Bob's |
| REST list | `GET /billing/api/invoices/` | JSON of her own invoices |
| REST detail | `GET /billing/api/invoices/<pk>/` | Her invoice, or 404 |
| MCP `list_invoices` | tools/call | Same JSON, scoped to her rows |
| MCP `get_invoice` | tools/call | Her invoice, or `{"error": "Invoice pk=99 not found"}` |
| MCP `search_invoices` | tools/call | FTS5 hits, scoped to her rows |
| Public `/search/` | `?q=…` | Search panel includes her invoices (only) |

For Bob's view of the same data: same shape, only his rows. For an unauthenticated visitor: anon redirects on web; 401 on REST + MCP.

## How write tools (`create_*` / `update_*` / `delete_*`) behave

By default the MCP factory tags write tools with `write=True` plus the inherited `access_level`. The MCP server's auth layer enforces:

- **Token must have the `write` scope.** A token minted as `readonly` cannot call any write tool — even if the access level matches.
- **Token's `access_level` must satisfy the tool's mixin** (`readonly` works for `LoginRequiredMixin` views; `staff` is required for `StaffRequiredMixin` views).
- **The CRUDView's `can_update(obj, request)` / `can_delete(obj, request)` hooks run for write actions.** If `obj.owner_id != request.user.id`, deny. The MCP tool returns `{"error": "Permission denied"}` instead of the success payload.

If you want Alice to be able to CREATE her own invoices via MCP but not modify them through the public surface, leave `create_invoice` with the default behaviour (her token's user becomes the `owner` via the form's `on_form_valid` hook) and skip `update_invoice`/`delete_invoice` by setting:

```python
actions = [Action.LIST, Action.DETAIL, Action.CREATE]   # read + create only
```

The factory only emits tools for the actions you declare.

## Minting an end-user MCP token

Three paths, in increasing rigour:

### Path 1 — direct mint (CLI, for testing)

```bash
uv run python manage.py create_api_token alice --name "alice's mcp" \
    --access-level readonly --scopes read
# Prints the raw key once. Save it.
```

Alice can now hit `/mcp` with `Authorization: Bearer <raw>` and call `list_invoices` directly.

### Path 2 — self-service mint (web UI)

A signed-in non-staff user can visit `/smallstack/tokens/` and mint their own token. The tokenmgr CRUDView ships with `get_list_queryset` scoped to `user=request.user`, so they only see their own keys (audit-verified). The form lets them choose `access_level` and `scopes` within the tiers their account can request — `readonly` + `read` is the default and produces an MCP-callable token for read tools.

### Path 3 — OAuth/PKCE (for clients)

Claude Desktop, the Connectors UI, and any other RFC 7591 client can complete the dynamic-client-registration → authorize → consent → code-exchange flow against `/mcp/oauth/*`. The user lands on the consent screen as themselves, approves the scope, and the client receives a bearer token tagged `token_type="oauth"` (v0.11.9) scoped to their identity.

For end-user use, prefer Path 3: the user never sees the token; revocation is one click in `/smallstack/tokens/`; consent leaves an audit trail.

## Sanity tests for an end-user MCP tool

Add these to `apps/<your_app>/tests/test_mcp.py`. They cover the entire end-user envelope: anon out, self in, cross-user denied.

```python
import pytest
from django.contrib.auth import get_user_model

from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

pytestmark = pytest.mark.django_db


def _call(name, args, *, user):
    ctx = set_context(ToolContext(user=user, token=None))
    try:
        return TOOL_HANDLERS[name](args)
    finally:
        reset_context(ctx)


def test_alice_lists_only_her_invoices():
    User = get_user_model()
    alice = User.objects.create_user("alice", password="x")
    bob = User.objects.create_user("bob", password="x")

    from apps.billing.models import Invoice
    Invoice.objects.create(owner=alice, number="A-1", amount_due=100)
    Invoice.objects.create(owner=bob,   number="B-1", amount_due=200)

    result = _call("list_invoices", {}, user=alice)
    numbers = {row["number"] for row in result["results"]}
    assert numbers == {"A-1"}        # her own
    assert "B-1" not in numbers       # not Bob's


def test_alice_cannot_get_bobs_invoice_by_pk():
    User = get_user_model()
    alice = User.objects.create_user("alice", password="x")
    bob = User.objects.create_user("bob", password="x")

    from apps.billing.models import Invoice
    bob_inv = Invoice.objects.create(owner=bob, number="B-1", amount_due=200)

    result = _call("get_invoice", {"pk": bob_inv.pk}, user=alice)
    # 404-equivalent — pretend the row doesn't exist
    assert "error" in result
    assert str(bob_inv.pk) in result["error"]


def test_alice_search_excludes_bobs_invoices():
    """search_invoices applies search_visibility so even a query that would
    match Bob's row returns only Alice's."""
    User = get_user_model()
    alice = User.objects.create_user("alice", password="x")
    bob = User.objects.create_user("bob", password="x")

    from apps.billing.models import Invoice
    Invoice.objects.create(owner=alice, number="A-needle", amount_due=100)
    Invoice.objects.create(owner=bob,   number="B-needle", amount_due=200)

    # Rebuild the FTS index for the test row visibility.
    from apps.search.backends import get_backend
    from apps.search.registry import all_views
    backend = get_backend()
    for view in all_views():
        if view.model_label.endswith(".Invoice"):
            backend.rebuild(view)

    result = _call("search_invoices", {"query": "needle"}, user=alice)
    numbers = {hit["display"] for hit in result["results"]}
    assert numbers == {"A-needle"}
```

## Anti-patterns

**Don't skip `get_list_queryset`.** A CRUDView with `LoginRequiredMixin` and the default `get_list_queryset` (returns `qs.all()`) lets Alice's `list_invoices` return Bob's rows. Web + REST + MCP all leak.

**Don't grant `write` scope to a token meant for read-only end-user use.** A `readonly + read` token can't call `delete_invoice` even if `can_delete` would allow it. Promote-by-mistake here is the single biggest "blast radius" risk.

**Don't use `mcp_descriptions` to claim a different security model than the gate enforces.** If the description says "Get *any* invoice by id" but the queryset scopes to `owner=user`, the LLM will be confused; the gate is correct, the description is wrong. Match them.

**Don't drop `enable_search = True` on a per-user CRUDView and assume search MCP scopes for free.** It doesn't — `search_access` defaults to `STAFF`, so without setting `SearchAccess.AUTHENTICATED` + `search_visibility`, Alice's `search_invoices` returns `{"denied": true}`. Either configure both, or skip search opt-in for this CRUDView and rely on `list_invoices` + filter args.

**Don't run write tools without `can_update` / `can_delete`.** Even if `get_list_queryset` filters the LIST, a malicious-or-mistaken `update_invoice(pk=99, …)` would silently apply to Bob's invoice if `can_update` doesn't reject it. Wire both.

## Related

- [`building-a-user-facing-site.md`](../building-a-user-facing-site.md) — the parent skill for the web/REST side. Read first.
- [`enable-mcp-for-a-model.md`](enable-mcp-for-a-model.md) — the MCP factory + mixin → access_level mapping.
- [`../search.md`](../search.md) — `SearchAccess` levels and `search_visibility` recipes (Inventory walkthrough).
- [`../crud-views.md`](../crud-views.md) — `get_list_queryset`, `can_update`, `can_delete` reference.
- [`connect-claude-desktop.md`](connect-claude-desktop.md) — the OAuth/PKCE handshake from the client side.
