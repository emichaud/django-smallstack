# Building a User-Facing Site

**Read this** when the user says *"I want my customers to log in and see their stuff"*, *"I'm building a SaaS, not an admin tool"*, or anything else that implies non-staff end users navigating the site. The bundled SmallStack chrome (`/smallstack/*`) is **staff-only by design** — every dashboard, explorer, admin search, and built-in CRUDView ships with `StaffRequiredMixin`. A signed-in non-staff user trying to reach those URLs gets a bare 403.

This skill walks the four moves you need to make for a user-facing surface:

1. **Build pages in `apps/website/`** (the "edit freely" boundary).
2. **Use `LoginRequiredMixin`, not `StaffRequiredMixin`**, on your CRUDViews + custom views.
3. **Scope querysets by `request.user`** via `get_list_queryset` (CRUDView's tenancy hook).
4. **Override `search_access` + `search_visibility`** on any CRUDView whose data the user should be able to *find* (not just browse).

## Why the default is staff-only

SmallStack treats `/smallstack/*` as the operator console. Dashboard, Explorer, MCP admin, API admin, Backups, Tokens, Search — all assume the visitor is the person who deploys + administers the site. The framework opts the bundled `User` and `APIToken` CRUDViews into `StaffRequiredMixin` + `SearchAccess.STAFF` so a fresh install ships with zero PII exposure on any user-reachable surface.

End-user pages — "log in, see your invoices, file a support ticket" — live somewhere different, and you're responsible for building them. The framework still hands you the same building blocks (CRUDView, search, MCP), just configured differently. The split is intentional: an internal IT-ops tool needs nothing in `apps/website/`; a multi-tenant SaaS uses `apps/website/` for almost everything user-facing.

## The four-move pattern

### Move 1 — Put your views in `apps/website/` or a project app

`apps/website/` is documented as the "edit freely" surface and is never overwritten by upstream merges. For a small project, one app is enough; for anything multi-module, prefer one app per domain concern (e.g. `apps/billing/`, `apps/support/`, `apps/projects/`).

```python
# apps/billing/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "billing/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["invoices"] = self.request.user.invoices.filter(status="open")
        ctx["projects"] = self.request.user.projects.all()
        return ctx
```

Then wire `apps/billing/urls.py` into `config/urls.py`:

```python
# config/urls.py
urlpatterns = [
    path("admin/", admin.site.urls),
    path("smallstack/", include("apps.smallstack.site_urls")),
    path("", include("apps.website.urls")),
    path("billing/", include("apps.billing.urls")),   # ← your user-facing surface
]
```

`/billing/` is now public — auth checks come from the views themselves.

### Move 2 — `LoginRequiredMixin`, not `StaffRequiredMixin`

For CRUDViews backing user-facing data, drop `StaffRequiredMixin` and use Django's `LoginRequiredMixin`. The page is still gated (anonymous redirects to `/accounts/login/`), but any signed-in user can reach it.

```python
# apps/billing/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.smallstack.crud import CRUDView, Action
from .models import Invoice


class InvoiceCRUDView(CRUDView):
    model = Invoice
    url_base = "invoices"
    mixins = [LoginRequiredMixin]   # ← not StaffRequiredMixin
    actions = [Action.LIST, Action.DETAIL]     # read-only for users
    list_fields = ["number", "amount_due", "due_date", "status"]
```

**Wait — but the MCP tools the factory generates will inherit that mixin too.** Yes, exactly. A `LoginRequiredMixin` CRUDView produces MCP tools that accept any `readonly` token instead of demanding `staff`. That's the user-facing tenancy story extended to MCP: the same Alice who logs in via the browser can hit `list_invoices` via her readonly token and get the same scoped result set.

### Move 3 — Scope by `request.user` in `get_list_queryset`

`LoginRequiredMixin` admits the user; it doesn't constrain what they see. Without scoping, Alice signed in and visiting `/billing/invoices/` would see *every* invoice — every other tenant's data, leaked. The CRUDView's `get_list_queryset` hook is where you narrow the set:

```python
class InvoiceCRUDView(CRUDView):
    model = Invoice
    url_base = "invoices"
    mixins = [LoginRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]
    list_fields = ["number", "amount_due", "due_date", "status"]

    def get_list_queryset(self, qs, request):
        # The single most important method on a user-facing CRUDView.
        # Runs for HTML list, REST list, AND every MCP tool (list_,
        # get_, search_). Get it wrong here and every surface leaks.
        return qs.filter(owner=request.user)

    def can_update(self, obj, request):
        # CRUDView also exposes can_update / can_delete for per-row
        # action gating, but for read-only views the list scope is
        # usually enough.
        return obj.owner_id == request.user.id

    can_delete = can_update
```

Three rules for `get_list_queryset`:

1. **Always filter by a user-bound field** (`owner=request.user`, `team__members=request.user`, `tenant=request.user.tenant`, etc.). A `qs.all()` here is a security bug.
2. **The hook runs for every surface**: HTML list, REST `GET /api/invoices/`, MCP `list_invoices`, MCP `search_invoices`, MCP `get_invoice` (which fetches via the scoped queryset). One filter, three surfaces.
3. **Don't trust the URL `pk`**: `get_invoice(pk=99)` should return "not found" if Alice doesn't own invoice 99. The scoped queryset's `.get(pk=99)` raises `DoesNotExist`, which the framework turns into a 404 / `not found` error. Don't bypass it with `Invoice.objects.get(...)`.

### Move 4 — Configure `search_access` + `search_visibility` for findability

The web/MCP search surfaces have their own gate, separate from the CRUDView's auth mixin. If a model is opted in to `enable_search = True`, the registry's `search_access` flag (default `STAFF`) determines who can find rows. For a user-facing CRUDView you want users to be able to *search* their own data, not just list it — so:

```python
from apps.search.access import SearchAccess


class InvoiceCRUDView(CRUDView):
    model = Invoice
    url_base = "invoices"
    mixins = [LoginRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]
    list_fields = ["number", "amount_due", "due_date", "status"]

    # Search opt-in
    enable_search = True
    search_fields = ["number", "customer_reference"]
    search_display = "number"

    # Access — any signed-in user can find rows from this view.
    search_access = SearchAccess.AUTHENTICATED

    # Row scoping — but only THEIR rows. Mirrors get_list_queryset.
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(owner=user)
    )

    def get_list_queryset(self, qs, request):
        return qs.filter(owner=request.user)
```

Now Alice visits `/search/?q=2024-Q1`, the registry runs `search_invoices`, the FTS5 backend returns matching invoice ids, the registry pipes them through `search_visibility(qs, alice)` which keeps only Alice's invoices, and she sees her own results.

If the model is genuinely public (a `KnowledgeArticle.is_published=True`, a published `BlogPost`, a `Job` listing), use `SearchAccess.ANONYMOUS` and gate the visibility to the public subset:

```python
search_access = SearchAccess.ANONYMOUS
search_visibility = staticmethod(
    lambda qs, user: qs.filter(is_published=True)
)
```

This is the "Recipe 4" pattern in `apps/smallstack/docs/search.md`.

## A complete user-facing CRUDView

Putting all four moves together:

```python
# apps/billing/views.py
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.search.access import SearchAccess
from apps.smallstack.crud import CRUDView, Action

from .models import Invoice


class InvoiceCRUDView(CRUDView):
    model = Invoice
    url_base = "invoices"

    # Web + MCP auth (any signed-in user, no staff requirement)
    mixins = [LoginRequiredMixin]

    # User-readable: list + detail. No create/update/delete from this surface
    # (you'd build those into a separate staff CRUDView).
    actions = [Action.LIST, Action.DETAIL]

    # API surface — emits /<include>/api/invoices/ for Alice's mobile app or SPA.
    enable_api = True

    # MCP surface — emits list_invoices, get_invoice. Alice's readonly token
    # can call both; the gate is the same tenancy filter as the web view.
    enable_mcp = True

    # Search surface — Alice can find her invoices by free text.
    enable_search = True
    search_fields = ["number", "customer_reference", "notes"]
    search_display = "number"
    search_subtitle = "customer_reference"

    search_access = SearchAccess.AUTHENTICATED
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(owner=user)
    )

    list_fields = ["number", "customer_reference", "amount_due", "due_date", "status"]

    def get_list_queryset(self, qs, request):
        # SINGLE place tenancy is enforced. Web list, REST list, MCP
        # list/get/search, search page, omnibar — all go through here.
        return qs.filter(owner=request.user)

    def can_update(self, obj, request):
        return obj.owner_id == request.user.id

    can_delete = can_update
```

The same one class produces four user-facing surfaces (web list/detail at `/billing/invoices/`, REST at `/billing/api/invoices/`, MCP tools `list_invoices`/`get_invoice`/`search_invoices`, plus a row on the public `/search/` page), each scoped per user, all gated by the same `get_list_queryset` filter.

## What `/smallstack/*` is and isn't

| URL | Audience | Notes |
|---|---|---|
| `/smallstack/` (dashboard) | Staff only | Operator console. Don't reuse for end users. |
| `/smallstack/explorer/` | Staff only | Database browser. Powerful — never lift its gate. |
| `/smallstack/search/` | Any signed-in user (since v0.11.8) | Page-level gate is `LoginRequiredMixin`; the **registry** filters per-view. Non-staff land here and see only `AUTHENTICATED`+ tier models. |
| `/smallstack/tokens/` | Any signed-in user (tenancy-scoped) | The CRUDView's `get_list_queryset` scopes by `owner`. Users see only their own. |
| `/smallstack/help/` | Anyone, including anonymous | Documentation. |
| `/smallstack/api/`, `/smallstack/mcp/` | Staff only | Admin observers for the API + MCP surfaces. |
| `/search/` (public) | Anyone, including anonymous | The user-facing search surface — uses the same registry. |
| `/admin/` | Staff (Django admin) | Standard `is_staff` gate. |

**Don't put user-facing pages under `/smallstack/`.** That URL prefix is reserved for the operator console — putting customer surfaces there blurs the security model and makes the operator's mental model harder. Mount your user pages at `/` (in `apps/website/`) or a domain prefix (`/billing/`, `/projects/`).

## Migration — turning an existing staff CRUDView into a user CRUDView

If you started with `StaffRequiredMixin` and now want non-staff users in:

1. **Swap the mixin**: `StaffRequiredMixin` → `LoginRequiredMixin`. Test that anonymous still redirects.
2. **Add `get_list_queryset` scoping**: filter by a user-bound field. Run the test suite — every list/detail/search test for that CRUDView should still pass with `request.user` scoping in place.
3. **Add `search_access` + `search_visibility`** if the CRUDView opts in to search. Default `STAFF` is the wrong call here.
4. **Audit MCP**: the factory will now emit non-staff-callable `list_/get_/create_/etc.` tools. Any caller with a `readonly` token can call them. Verify each tool returns only the caller's rows (the scoped queryset takes care of this automatically).
5. **Run `make mcp-test`** with a `readonly` token (default for the smoke). Should pass — the smoke uses a readonly token and expects readonly tools to be reachable.

## Sanity tests for a user-facing CRUDView

Three tests are non-negotiable. Add them to your app's test module:

```python
import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


def test_list_is_scoped_to_request_user(client):
    User = get_user_model()
    alice = User.objects.create_user("alice", "alice@x.test", "pw")
    bob = User.objects.create_user("bob", "bob@x.test", "pw")

    from apps.billing.models import Invoice
    Invoice.objects.create(owner=alice, number="A-1", amount_due=100)
    Invoice.objects.create(owner=bob,   number="B-1", amount_due=200)

    client.force_login(alice)
    response = client.get("/billing/invoices/")
    body = response.content.decode()

    assert "A-1" in body         # Alice sees her own
    assert "B-1" not in body     # Alice doesn't see Bob's


def test_detail_is_scoped_to_request_user(client):
    # Same setup …
    client.force_login(alice)
    response = client.get(f"/billing/invoices/{bob_invoice.pk}/")
    assert response.status_code == 404   # not 200 or 403 — pretend it doesn't exist


def test_anonymous_is_redirected_to_login(client):
    response = client.get("/billing/invoices/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url
```

For each user-facing CRUDView these three tests cover the entire security envelope: anon out, owner in, non-owner can't enumerate by pk.

## Common combinations

- **CRUDView + LoginRequiredMixin + `get_list_queryset`** — the canonical user-facing pattern. Web + REST + MCP all scoped.
- **CRUDView + `LoginRequiredMixin` + `SearchAccess.AUTHENTICATED` + `search_visibility`** — same plus public-search findability for the user's own data.
- **`enable_mcp = True` on a user CRUDView** — Alice gets `list_invoices` / `get_invoice` / `search_invoices` via her readonly token. The MCP factory inherits the `LoginRequiredMixin` decision and emits tools that accept `access_level=readonly` — no extra config.
- **Two CRUDViews on the same model** — one staff (full fields, internal notes, `url_base = "manage/invoices"`), one user (public-safe fields, `url_base = "billing/invoices"`, `get_list_queryset` scoped). Same model, two audiences. See the Inventory walkthrough in `apps/smallstack/docs/search.md` for the full worked example.

## Don't

- **Don't lift `StaffRequiredMixin` off a `/smallstack/*` CRUDView.** Those are operator surfaces and the audit history says non-staff visitors hit them and report bugs. If you want a non-staff version, build a separate CRUDView at a different URL.
- **Don't put `qs.all()` in `get_list_queryset`.** Even temporarily, for debugging. It will ship and leak.
- **Don't gate at the view level and skip the queryset filter.** A CRUDView with `LoginRequiredMixin` and unscoped `get_list_queryset` lets Alice see Bob's data — the auth check only confirms she's signed in.
- **Don't reach for `Model.objects.get(pk=...)` inside a CRUDView method.** Use `self.get_object()` / the framework's scoped queryset access.
- **Don't rely on `is_staff` being false to mean "Alice can read her own data."** Test the row-scoping explicitly.

## Related

- `docs/skills/crud-views.md` — full CRUDView reference (the auth mixin, `get_list_queryset`, `can_update`).
- `docs/skills/search.md` — `SearchAccess` levels + `search_visibility` recipes, including the Inventory walkthrough.
- `docs/skills/mcp/enable-mcp-for-a-model.md` — mixin → token `access_level` mapping; what `readonly` callers can and can't reach.
- `apps/smallstack/docs/search.md` — same security model from the user-facing reference angle.
