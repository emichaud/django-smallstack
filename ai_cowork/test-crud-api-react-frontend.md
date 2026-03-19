# Test: SmallStack CRUDView API with React Frontend

## Objective

Build a small React frontend that consumes SmallStack's CRUDView REST API to test whether the API is sufficient for a standalone frontend project. Document everything — what works, what's missing, what's painful.

## What You're Testing

1. Can a React app perform full CRUD (create, read, update, delete) via CRUDView's REST API?
2. Is token authentication straightforward to set up and use?
3. Are the API responses well-structured for frontend consumption?
4. What gaps or friction exist in the API, docs, or setup process?

## Setup Instructions

### Step 1: Clone and Configure SmallStack Backend

```bash
cd /Users/everettmichaud/Documents/django/smallstack_home
mkdir test_crud_api
cd test_crud_api
git clone https://github.com/emichaud/django-smallstack.git backend
cd backend
```

Follow `docs/skills/from-zero-to-running.md` for setup. Key steps:

```bash
cp .env.example .env
# Edit .env — keep defaults, just change the port:
#   No changes needed for DJANGO_SETTINGS_MODULE or ALLOWED_HOSTS
make setup
```

**Use port 8020 for the Django backend:**

```bash
PORT=8020 make run
```

Verify: `http://localhost:8020/health/` should return `{"status": "ok", "database": "ok"}`

Log in at `http://localhost:8020/smallstack/accounts/login/` with `admin` / `admin`.

### Step 2: Create Models

Create a new app for the test data. This tests the "creating new apps" workflow from the docs:

```bash
mkdir -p apps/inventory
uv run python manage.py startapp inventory apps/inventory
```

Fix `apps/inventory/apps.py`:
```python
class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    verbose_name = "Inventory"
```

Add to `INSTALLED_APPS` in `config/settings/base.py`:
```python
"apps.inventory",
```

Create two related models in `apps/inventory/models.py`:

```python
from django.db import models

class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="products")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    in_stock = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
```

Run migrations:
```bash
uv run python manage.py makemigrations inventory
uv run python manage.py migrate
```

### Step 3: Create CRUDViews with API Enabled

Create `apps/inventory/views.py`:

```python
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import TableDisplay
from apps.smallstack.mixins import StaffRequiredMixin
from .models import Category, Product


class CategoryCRUDView(CRUDView):
    model = Category
    fields = ["name", "description"]
    url_base = "inventory/categories"
    paginate_by = 25
    mixins = [StaffRequiredMixin]
    displays = [TableDisplay]
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    enable_api = True
    search_fields = ["name"]


class ProductCRUDView(CRUDView):
    model = Product
    fields = ["name", "category", "price", "in_stock", "description"]
    url_base = "inventory/products"
    paginate_by = 25
    mixins = [StaffRequiredMixin]
    displays = [TableDisplay]
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    enable_api = True
    search_fields = ["name", "description"]
    filter_fields = ["category", "in_stock"]
```

Create `apps/inventory/urls.py`:

```python
from django.urls import path
from .views import CategoryCRUDView, ProductCRUDView

app_name = "inventory"

urlpatterns = [
    *CategoryCRUDView.get_urls(),
    *ProductCRUDView.get_urls(),
]
```

Add to `config/urls.py` (before the admin line):

```python
path("", include("apps.inventory.urls")),
```

### Step 4: Create API Token

```bash
uv run python manage.py create_api_token admin
```

Save the token — you'll need it for the React app.

**Verify the API works:**

```bash
# List categories (should return empty results)
curl -H "Authorization: Bearer <token>" http://localhost:8020/api/inventory/categories/

# Create a category
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"name": "Electronics", "description": "Electronic products"}' \
  http://localhost:8020/api/inventory/categories/

# List again (should show the category)
curl -H "Authorization: Bearer <token>" http://localhost:8020/api/inventory/categories/
```

### Step 5: Handle CORS

**IMPORTANT: SmallStack does NOT include CORS support.** A React dev server on port 8021 cannot call the Django API on port 8020 without CORS headers.

You need to add CORS support. Options:

**Option A: django-cors-headers (proper)**
```bash
uv add django-cors-headers
```

In `config/settings/base.py`:
```python
INSTALLED_APPS = [
    "corsheaders",  # Add before django.middleware.common
    ...
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # Must be high in the list
    "django.middleware.common.CommonMiddleware",
    ...
]

# Development only — allow React dev server
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8021",
]
CORS_ALLOW_HEADERS = [
    "authorization",
    "content-type",
]
```

**Option B: Simple middleware (quick hack for testing)**

Create a middleware that adds CORS headers. Less robust but zero dependencies.

**Document which approach you used and any issues encountered.**

### Step 6: Create React Frontend

```bash
cd /Users/everettmichaud/Documents/django/smallstack_home/test_crud_api
npx create-react-app frontend
# OR: npm create vite@latest frontend -- --template react
cd frontend
```

**Use port 8021 for the React dev server.** Add to `package.json`:
```json
"scripts": {
  "start": "PORT=8021 react-scripts start"
}
```
Or for Vite: configure `vite.config.js` with `server: { port: 8021 }`.

### Step 7: Build the React App

Build a simple multi-page React app that exercises the full CRUD lifecycle:

**Pages to build:**

1. **Categories List** — fetch and display all categories, with delete button
2. **Category Form** — create and edit categories
3. **Products List** — fetch and display all products with category name, filter by category, search by name
4. **Product Form** — create and edit products (category as dropdown populated from API)
5. **Dashboard** — show counts (total categories, total products, in-stock vs out-of-stock)

**API integration requirements:**

- Store the Bearer token in an env var or config file (`REACT_APP_API_TOKEN` or similar)
- Create a simple API client module that handles:
  - Base URL (`http://localhost:8020/api/`)
  - Authorization header
  - JSON parsing
  - Error handling (400 validation errors, 401/403 auth errors, 404)
- Handle paginated responses (`count`, `next`, `previous`, `results`)
- Handle the `category` ForeignKey — it returns as a pk integer. The frontend needs to resolve this to a name (either by fetching categories separately or by noting this as an API limitation).

**Things to specifically test and document:**

- [ ] Can you list items with pagination?
- [ ] Can you create an item via POST?
- [ ] Can you update an item via PATCH?
- [ ] Can you delete an item via DELETE?
- [ ] Can you search with `?q=`?
- [ ] Can you filter with query params (e.g., `?category=1&in_stock=true`)?
- [ ] How does the API handle validation errors? Are they useful for form display?
- [ ] How does the ForeignKey field serialize? Is the pk-only response sufficient or do you need nested data?
- [ ] Is the pagination format easy to work with?
- [ ] Does the token auth flow work smoothly?

## Evaluation Criteria

After building, write an evaluation document at `test_crud_api/evaluation.md` covering:

### What Worked Well
- What was easy, intuitive, well-documented?

### Documentation Issues
- What was missing, wrong, or confusing in the setup docs?
- What steps required guessing or trial-and-error?
- Note specific doc files and what should be added/fixed.

### API Issues
- What's missing from the CRUDView API for frontend use?
- Known likely issues to watch for:
  - **CORS** — not included, must be added manually
  - **ForeignKey serialization** — returns pk only, not nested object or string representation
  - **No OPTIONS/preflight handling** — may cause issues before CORS is added
  - **No bulk operations** — can't create/update/delete multiple items in one request
  - **No field selection** — can't request only specific fields
  - **Pagination format** — is `count/next/previous/results` easy to use?
  - **Error format** — are 400 validation errors structured well for React forms?
  - **Token creation** — management command only, no self-service UI

### Improvement Recommendations
Prioritize as:
- **P0** — Blocks basic usage (e.g., CORS)
- **P1** — Major friction (e.g., FK serialization)
- **P2** — Nice to have (e.g., bulk operations)

### Verdict
One paragraph: Is the CRUDView API sufficient to run a frontend project? What's the minimum set of improvements needed?

## Ports

| Service | Port |
|---------|------|
| Django backend | 8020 |
| React frontend | 8021 |
| (reserved) | 8022-8025 |

## Files to Produce

```
test_crud_api/
├── backend/                  # SmallStack clone with inventory app
├── frontend/                 # React app
├── evaluation.md             # Detailed evaluation (see criteria above)
└── doc-issues.md             # Specific doc fixes needed upstream
```

## Important Notes

- **Do NOT modify SmallStack core files** (apps/smallstack/*) except for adding CORS support. The goal is to test the API as-shipped.
- **Do NOT use Django REST Framework.** The point is to test SmallStack's built-in API.
- **Document every friction point** — even small ones. This is a UX test, not just a functionality test.
- **Keep the React app simple.** Plain CSS is fine. The UI doesn't need to be pretty — it needs to exercise every API endpoint.
- **Test error paths** — submit invalid data, use wrong tokens, try to delete nonexistent items. Document how the API responds.
- **If something doesn't work, note it but work around it.** The goal is a complete evaluation, not a blocked test.
